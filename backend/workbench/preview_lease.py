"""本地开发服务器预览的短期 owner/project/session/port 租约。"""

from __future__ import annotations

import asyncio
import inspect
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Awaitable, Callable

from workbench.errors import WorkbenchError
from workbench.runtime_registry import (
    RuntimeResourceType,
    WorkbenchRuntimeRegistry,
    runtime_registry,
)


class PreviewLeaseNotFound(WorkbenchError):
    code = "workbench_preview_lease_not_found"

    def __init__(self) -> None:
        super().__init__("预览租约不存在或已失效")


class PreviewLeaseForbidden(WorkbenchError):
    code = "workbench_preview_listener_forbidden"

    def __init__(self) -> None:
        super().__init__("端口不属于指定的工作台运行会话")


class PreviewLeaseLimitExceeded(WorkbenchError):
    code = "workbench_preview_lease_limit_exceeded"

    def __init__(self) -> None:
        super().__init__("单个运行会话最多允许三个活动预览租约")


class PreviewSessionKind(str, Enum):
    TERMINAL = "terminal"
    ACP = "acp"


@dataclass(frozen=True)
class PreviewLease:
    preview_id: str
    user_id: str
    project_id: str
    port: int
    session_kind: PreviewSessionKind
    session_id: str
    created_at: datetime
    expires_at: datetime


VerifyProject = Callable[[], Awaitable[None] | None]
VerifyListener = Callable[
    [str, str, PreviewSessionKind, str, int],
    Awaitable[bool] | bool,
]
NowFactory = Callable[[], datetime]


async def _resolve_callback_result(result):
    if inspect.isawaitable(result):
        return await result
    return result


class PreviewLeaseRegistry:
    """维护十五分钟预览租约，并同步到工作台运行时占用注册表。"""

    TTL = timedelta(minutes=15)
    MAX_PER_SESSION = 3

    def __init__(
        self,
        *,
        runtime_registry: WorkbenchRuntimeRegistry,
        now: NowFactory | None = None,
    ) -> None:
        self._runtime_registry = runtime_registry
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._leases: dict[str, PreviewLease] = {}
        self._lock = asyncio.Lock()

    async def issue(
        self,
        *,
        user_id: str,
        project_id: str,
        session_kind: PreviewSessionKind,
        session_id: str,
        port: int,
        verify_project: VerifyProject,
        verify_listener: VerifyListener,
    ) -> PreviewLease:
        if not 1 <= port <= 65535:
            raise PreviewLeaseForbidden()
        await self._purge_expired()

        async def verify_all() -> None:
            await _resolve_callback_result(verify_project())
            listener_owned = await _resolve_callback_result(
                verify_listener(
                    str(user_id),
                    str(project_id),
                    session_kind,
                    session_id,
                    port,
                )
            )
            if listener_owned is not True:
                raise PreviewLeaseForbidden()

        preview_id = secrets.token_urlsafe(32)

        async def drop_lease_only() -> None:
            async with self._lock:
                self._leases.pop(preview_id, None)

        await self._runtime_registry.acquire(
            user_id=user_id,
            project_id=project_id,
            resource_type=RuntimeResourceType.PREVIEW_LEASE,
            resource_id=preview_id,
            verify_project=verify_all,
            close_callback=drop_lease_only,
        )

        now = self._now()
        lease = PreviewLease(
            preview_id=preview_id,
            user_id=str(user_id),
            project_id=str(project_id),
            port=port,
            session_kind=session_kind,
            session_id=session_id,
            created_at=now,
            expires_at=now + self.TTL,
        )
        limit_exceeded = False
        async with self._lock:
            active_count = sum(
                1
                for item in self._leases.values()
                if item.user_id == str(user_id)
                and item.project_id == str(project_id)
                and item.session_kind is session_kind
                and item.session_id == session_id
                and item.expires_at > now
            )
            if active_count >= self.MAX_PER_SESSION:
                limit_exceeded = True
            else:
                self._leases[preview_id] = lease

        if limit_exceeded:
            await self._release_runtime(lease)
            raise PreviewLeaseLimitExceeded()
        return lease

    async def get_owned(
        self,
        *,
        preview_id: str,
        user_id: str,
        project_id: str,
    ) -> PreviewLease:
        expired: PreviewLease | None = None
        async with self._lock:
            lease = self._leases.get(preview_id)
            if (
                lease is None
                or lease.user_id != str(user_id)
                or lease.project_id != str(project_id)
            ):
                raise PreviewLeaseNotFound()
            if lease.expires_at <= self._now():
                expired = self._leases.pop(preview_id)
            else:
                return lease
        if expired is not None:
            await self._release_runtime(expired)
        raise PreviewLeaseNotFound()

    async def renew(
        self,
        *,
        preview_id: str,
        user_id: str,
        project_id: str,
        verify_project: VerifyProject,
        verify_listener: VerifyListener,
    ) -> PreviewLease:
        lease = await self.consume(
            preview_id=preview_id,
            user_id=user_id,
            project_id=project_id,
            verify_project=verify_project,
            verify_listener=verify_listener,
        )
        renewed = replace(lease, expires_at=self._now() + self.TTL)
        async with self._lock:
            if self._leases.get(preview_id) != lease:
                raise PreviewLeaseNotFound()
            self._leases[preview_id] = renewed
        return renewed

    async def consume(
        self,
        *,
        preview_id: str,
        user_id: str,
        project_id: str,
        verify_project: VerifyProject,
        verify_listener: VerifyListener,
    ) -> PreviewLease:
        """每次代理消费前重验项目和 listener，但不延长租约。"""
        lease = await self.get_owned(
            preview_id=preview_id,
            user_id=user_id,
            project_id=project_id,
        )
        try:
            await _resolve_callback_result(verify_project())
            listener_owned = await _resolve_callback_result(
                verify_listener(
                    lease.user_id,
                    lease.project_id,
                    lease.session_kind,
                    lease.session_id,
                    lease.port,
                )
            )
        except Exception:
            await self._invalidate(lease)
            raise
        if listener_owned is not True:
            await self._invalidate(lease)
            raise PreviewLeaseForbidden()
        return lease

    async def revoke(self, *, preview_id: str, user_id: str, project_id: str) -> None:
        lease = await self.get_owned(
            preview_id=preview_id,
            user_id=user_id,
            project_id=project_id,
        )
        async with self._lock:
            self._leases.pop(preview_id, None)
        await self._release_runtime(lease)

    async def revoke_session(
        self,
        *,
        user_id: str,
        project_id: str,
        session_kind: PreviewSessionKind,
        session_id: str,
    ) -> None:
        async with self._lock:
            leases = tuple(
                item
                for item in self._leases.values()
                if item.user_id == str(user_id)
                and item.project_id == str(project_id)
                and item.session_kind is session_kind
                and item.session_id == session_id
            )
            for lease in leases:
                self._leases.pop(lease.preview_id, None)
        for lease in leases:
            await self._release_runtime(lease)

    async def _release_runtime(self, lease: PreviewLease) -> None:
        await self._runtime_registry.release(
            user_id=lease.user_id,
            project_id=lease.project_id,
            resource_type=RuntimeResourceType.PREVIEW_LEASE,
            resource_id=lease.preview_id,
        )

    async def _invalidate(self, lease: PreviewLease) -> None:
        """仅在租约仍是当前版本时移除，并同步释放运行时占用。"""
        removed = False
        async with self._lock:
            if self._leases.get(lease.preview_id) == lease:
                self._leases.pop(lease.preview_id, None)
                removed = True
        if removed:
            await self._release_runtime(lease)

    async def _purge_expired(self) -> None:
        now = self._now()
        async with self._lock:
            expired = tuple(
                lease for lease in self._leases.values() if lease.expires_at <= now
            )
            for lease in expired:
                self._leases.pop(lease.preview_id, None)
        for lease in expired:
            await self._release_runtime(lease)


preview_lease_registry = PreviewLeaseRegistry(runtime_registry=runtime_registry)

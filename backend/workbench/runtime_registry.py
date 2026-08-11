"""工作台本地运行时资源注册表与项目级串行化锁。"""

from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from typing import AsyncIterator, Awaitable, Callable, Optional

from workbench.errors import ProjectInUse


class RuntimeResourceType(str, Enum):
    ACP_SESSION = "acp_session"
    ACP_TURN = "acp_turn"
    TERMINAL_SESSION = "terminal_session"
    PTY_SESSION = "pty_session"
    OPENCODE_INSTALL = "opencode_install"
    PREVIEW_LEASE = "preview_lease"
    LSP_SESSION = "lsp_session"


CloseCallback = Callable[[], Awaitable[None] | None]
VerifyCallback = Callable[[], Awaitable[None] | None]


@dataclass(frozen=True)
class RuntimeResource:
    resource_type: RuntimeResourceType
    resource_id: str
    close_callback: Optional[CloseCallback] = None


class _ExclusiveProjectGuard:
    """调用方持有项目锁期间使用的同步视图。"""

    def __init__(self, registry: "WorkbenchRuntimeRegistry", key: tuple[str, str]) -> None:
        self._registry = registry
        self._key = key

    @property
    def active_resources(self) -> tuple[RuntimeResource, ...]:
        return tuple(self._registry._resources.get(self._key, {}).values())

    def assert_not_in_use(self) -> None:
        resources = self.active_resources
        if resources:
            raise ProjectInUse(item.resource_id for item in resources)


class WorkbenchRuntimeRegistry:
    """让运行时 acquire 与项目禁用/删除共享同一把项目锁。"""

    def __init__(self) -> None:
        self._locks: defaultdict[tuple[str, str], asyncio.Lock] = defaultdict(asyncio.Lock)
        self._resources: dict[
            tuple[str, str],
            dict[tuple[RuntimeResourceType, str], RuntimeResource],
        ] = {}

    @asynccontextmanager
    async def exclusive(self, user_id: str, project_id: str) -> AsyncIterator[_ExclusiveProjectGuard]:
        key = (str(user_id), str(project_id))
        async with self._locks[key]:
            yield _ExclusiveProjectGuard(self, key)

    async def acquire(
        self,
        *,
        user_id: str,
        project_id: str,
        resource_type: RuntimeResourceType,
        resource_id: str,
        verify_project: VerifyCallback,
        close_callback: Optional[CloseCallback] = None,
    ) -> None:
        key = (str(user_id), str(project_id))
        async with self._locks[key]:
            verification = verify_project()
            if inspect.isawaitable(verification):
                await verification
            resources = self._resources.setdefault(key, {})
            resources[(resource_type, resource_id)] = RuntimeResource(
                resource_type=resource_type,
                resource_id=resource_id,
                close_callback=close_callback,
            )

    async def release(
        self,
        *,
        user_id: str,
        project_id: str,
        resource_type: RuntimeResourceType,
        resource_id: str,
    ) -> None:
        key = (str(user_id), str(project_id))
        async with self._locks[key]:
            resources = self._resources.get(key)
            if resources is None:
                return
            resources.pop((resource_type, resource_id), None)
            if not resources:
                self._resources.pop(key, None)

    async def list_active(self, user_id: str, project_id: str) -> tuple[RuntimeResource, ...]:
        key = (str(user_id), str(project_id))
        async with self._locks[key]:
            return tuple(self._resources.get(key, {}).values())

    async def close_all(self, user_id: str, project_id: str) -> None:
        key = (str(user_id), str(project_id))
        async with self._locks[key]:
            resources = tuple(self._resources.pop(key, {}).values())
            for resource in resources:
                if resource.close_callback is None:
                    continue
                result = resource.close_callback()
                if inspect.isawaitable(result):
                    await result

    async def reset(self) -> None:
        """测试或应用关闭时清空全部注册项。"""
        for user_id, project_id in tuple(self._resources):
            await self.close_all(user_id, project_id)


runtime_registry = WorkbenchRuntimeRegistry()


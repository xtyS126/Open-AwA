from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from workbench.preview_lease import (
    PreviewLeaseForbidden,
    PreviewLeaseLimitExceeded,
    PreviewLeaseNotFound,
    PreviewLeaseRegistry,
    PreviewSessionKind,
)
from workbench.runtime_registry import WorkbenchRuntimeRegistry


class MutableClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 12, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


@pytest.fixture()
def lease_fixture():
    clock = MutableClock()
    runtime_registry = WorkbenchRuntimeRegistry()
    registry = PreviewLeaseRegistry(runtime_registry=runtime_registry, now=clock.now)
    valid_ports = {3000}

    async def verify_project() -> None:
        return None

    async def verify_listener(user_id, project_id, session_kind, session_id, port) -> bool:
        return (
            user_id == "user-1"
            and project_id == "project-1"
            and session_kind is PreviewSessionKind.TERMINAL
            and session_id == "terminal-1"
            and port in valid_ports
        )

    return registry, runtime_registry, clock, valid_ports, verify_project, verify_listener


@pytest.mark.asyncio
async def test_issue_requires_verified_session_descendant_listener(lease_fixture) -> None:
    registry, _runtime_registry, _clock, _valid_ports, verify_project, verify_listener = lease_fixture

    with pytest.raises(PreviewLeaseForbidden):
        await registry.issue(
            user_id="user-1",
            project_id="project-1",
            session_kind=PreviewSessionKind.TERMINAL,
            session_id="terminal-1",
            port=9999,
            verify_project=verify_project,
            verify_listener=verify_listener,
        )


@pytest.mark.asyncio
async def test_issue_binds_owner_project_port_and_runtime_resource(lease_fixture) -> None:
    registry, runtime_registry, _clock, _valid_ports, verify_project, verify_listener = lease_fixture

    lease = await registry.issue(
        user_id="user-1",
        project_id="project-1",
        session_kind=PreviewSessionKind.TERMINAL,
        session_id="terminal-1",
        port=3000,
        verify_project=verify_project,
        verify_listener=verify_listener,
    )

    assert len(lease.preview_id) >= 43
    assert lease.port == 3000
    assert lease.expires_at - lease.created_at == timedelta(minutes=15)
    loaded = await registry.get_owned(
        preview_id=lease.preview_id,
        user_id="user-1",
        project_id="project-1",
    )
    assert loaded == lease
    resources = await runtime_registry.list_active("user-1", "project-1")
    assert [item.resource_id for item in resources] == [lease.preview_id]


@pytest.mark.asyncio
async def test_listener_verification_receives_owner_and_project_identity() -> None:
    runtime_registry = WorkbenchRuntimeRegistry()
    registry = PreviewLeaseRegistry(runtime_registry=runtime_registry)
    listener_calls: list[tuple[object, ...]] = []

    def verify_listener(*args) -> bool:
        listener_calls.append(args)
        return True

    await registry.issue(
        user_id="user-1",
        project_id="project-1",
        session_kind=PreviewSessionKind.TERMINAL,
        session_id="terminal-1",
        port=3000,
        verify_project=lambda: None,
        verify_listener=verify_listener,
    )

    assert listener_calls == [
        ("user-1", "project-1", PreviewSessionKind.TERMINAL, "terminal-1", 3000)
    ]


@pytest.mark.asyncio
async def test_cross_user_or_cross_project_access_is_not_found(lease_fixture) -> None:
    registry, _runtime_registry, _clock, _valid_ports, verify_project, verify_listener = lease_fixture
    lease = await registry.issue(
        user_id="user-1",
        project_id="project-1",
        session_kind=PreviewSessionKind.TERMINAL,
        session_id="terminal-1",
        port=3000,
        verify_project=verify_project,
        verify_listener=verify_listener,
    )

    with pytest.raises(PreviewLeaseNotFound):
        await registry.get_owned(
            preview_id=lease.preview_id,
            user_id="user-2",
            project_id="project-1",
        )
    with pytest.raises(PreviewLeaseNotFound):
        await registry.get_owned(
            preview_id=lease.preview_id,
            user_id="user-1",
            project_id="project-2",
        )


@pytest.mark.asyncio
async def test_expired_lease_is_revoked_from_both_registries(lease_fixture) -> None:
    registry, runtime_registry, clock, _valid_ports, verify_project, verify_listener = lease_fixture
    lease = await registry.issue(
        user_id="user-1",
        project_id="project-1",
        session_kind=PreviewSessionKind.TERMINAL,
        session_id="terminal-1",
        port=3000,
        verify_project=verify_project,
        verify_listener=verify_listener,
    )
    clock.advance(901)

    with pytest.raises(PreviewLeaseNotFound):
        await registry.get_owned(
            preview_id=lease.preview_id,
            user_id="user-1",
            project_id="project-1",
        )
    assert await runtime_registry.list_active("user-1", "project-1") == ()


@pytest.mark.asyncio
async def test_issue_purges_idle_expired_leases_from_runtime_registry(lease_fixture) -> None:
    registry, runtime_registry, clock, valid_ports, verify_project, verify_listener = lease_fixture
    first = await registry.issue(
        user_id="user-1",
        project_id="project-1",
        session_kind=PreviewSessionKind.TERMINAL,
        session_id="terminal-1",
        port=3000,
        verify_project=verify_project,
        verify_listener=verify_listener,
    )
    clock.advance(901)
    valid_ports.add(3001)
    second = await registry.issue(
        user_id="user-1",
        project_id="project-1",
        session_kind=PreviewSessionKind.TERMINAL,
        session_id="terminal-1",
        port=3001,
        verify_project=verify_project,
        verify_listener=verify_listener,
    )

    resources = await runtime_registry.list_active("user-1", "project-1")
    assert [item.resource_id for item in resources] == [second.preview_id]
    assert first.preview_id != second.preview_id


@pytest.mark.asyncio
async def test_renew_rechecks_listener_and_extends_exact_ttl(lease_fixture) -> None:
    registry, _runtime_registry, clock, valid_ports, verify_project, verify_listener = lease_fixture
    lease = await registry.issue(
        user_id="user-1",
        project_id="project-1",
        session_kind=PreviewSessionKind.TERMINAL,
        session_id="terminal-1",
        port=3000,
        verify_project=verify_project,
        verify_listener=verify_listener,
    )
    clock.advance(300)
    renewed = await registry.renew(
        preview_id=lease.preview_id,
        user_id="user-1",
        project_id="project-1",
        verify_project=verify_project,
        verify_listener=verify_listener,
    )
    assert renewed.expires_at == clock.now() + timedelta(minutes=15)

    valid_ports.clear()
    with pytest.raises(PreviewLeaseForbidden):
        await registry.renew(
            preview_id=lease.preview_id,
            user_id="user-1",
            project_id="project-1",
            verify_project=verify_project,
            verify_listener=verify_listener,
        )


@pytest.mark.asyncio
async def test_consume_revalidates_project_and_listener_without_extending_ttl(lease_fixture) -> None:
    registry, runtime_registry, clock, valid_ports, _verify_project, verify_listener = lease_fixture
    lease = await registry.issue(
        user_id="user-1",
        project_id="project-1",
        session_kind=PreviewSessionKind.TERMINAL,
        session_id="terminal-1",
        port=3000,
        verify_project=lambda: None,
        verify_listener=verify_listener,
    )
    clock.advance(60)
    project_checks = 0

    def verify_project() -> None:
        nonlocal project_checks
        project_checks += 1

    assert hasattr(registry, "consume"), "预览代理消费入口尚未实现"
    consume = getattr(registry, "consume")
    consumed = await consume(
        preview_id=lease.preview_id,
        user_id="user-1",
        project_id="project-1",
        verify_project=verify_project,
        verify_listener=verify_listener,
    )

    assert consumed == lease
    assert consumed.expires_at == lease.expires_at
    assert project_checks == 1

    valid_ports.clear()
    with pytest.raises(PreviewLeaseForbidden):
        await consume(
            preview_id=lease.preview_id,
            user_id="user-1",
            project_id="project-1",
            verify_project=verify_project,
            verify_listener=verify_listener,
        )
    assert await runtime_registry.list_active("user-1", "project-1") == ()
    with pytest.raises(PreviewLeaseNotFound):
        await registry.get_owned(
            preview_id=lease.preview_id,
            user_id="user-1",
            project_id="project-1",
        )


@pytest.mark.asyncio
async def test_consume_project_failure_invalidates_runtime_lease(lease_fixture) -> None:
    """项目 fresh 重验失败时也必须清除租约，避免永久阻塞项目操作。"""
    registry, runtime_registry, _clock, _valid_ports, verify_project, verify_listener = lease_fixture
    lease = await registry.issue(
        user_id="user-1",
        project_id="project-1",
        session_kind=PreviewSessionKind.TERMINAL,
        session_id="terminal-1",
        port=3000,
        verify_project=verify_project,
        verify_listener=verify_listener,
    )

    def reject_project() -> None:
        raise RuntimeError("项目根已失效")

    with pytest.raises(RuntimeError, match="项目根已失效"):
        await registry.consume(
            preview_id=lease.preview_id,
            user_id="user-1",
            project_id="project-1",
            verify_project=reject_project,
            verify_listener=verify_listener,
        )

    assert await runtime_registry.list_active("user-1", "project-1") == ()
    with pytest.raises(PreviewLeaseNotFound):
        await registry.get_owned(
            preview_id=lease.preview_id,
            user_id="user-1",
            project_id="project-1",
        )


@pytest.mark.asyncio
async def test_session_has_at_most_three_active_leases(lease_fixture) -> None:
    registry, _runtime_registry, _clock, valid_ports, verify_project, _verify_listener = lease_fixture
    valid_ports.update({3001, 3002, 3003})

    async def verify_listener(_user_id, _project_id, _session_kind, _session_id, port) -> bool:
        return port in valid_ports

    for port in (3000, 3001, 3002):
        await registry.issue(
            user_id="user-1",
            project_id="project-1",
            session_kind=PreviewSessionKind.TERMINAL,
            session_id="terminal-1",
            port=port,
            verify_project=verify_project,
            verify_listener=verify_listener,
        )

    with pytest.raises(PreviewLeaseLimitExceeded):
        await registry.issue(
            user_id="user-1",
            project_id="project-1",
            session_kind=PreviewSessionKind.TERMINAL,
            session_id="terminal-1",
            port=3003,
            verify_project=verify_project,
            verify_listener=verify_listener,
        )


@pytest.mark.asyncio
async def test_revoke_session_removes_every_related_lease(lease_fixture) -> None:
    registry, runtime_registry, _clock, valid_ports, verify_project, _verify_listener = lease_fixture
    valid_ports.add(3001)

    async def verify_listener(_user_id, _project_id, _session_kind, _session_id, port) -> bool:
        return port in valid_ports

    for port in (3000, 3001):
        await registry.issue(
            user_id="user-1",
            project_id="project-1",
            session_kind=PreviewSessionKind.TERMINAL,
            session_id="terminal-1",
            port=port,
            verify_project=verify_project,
            verify_listener=verify_listener,
        )

    await registry.revoke_session(
        user_id="user-1",
        project_id="project-1",
        session_kind=PreviewSessionKind.TERMINAL,
        session_id="terminal-1",
    )

    assert await runtime_registry.list_active("user-1", "project-1") == ()

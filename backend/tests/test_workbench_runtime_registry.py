import asyncio

import pytest

from workbench.errors import ProjectInUse
from workbench.runtime_registry import RuntimeResourceType, WorkbenchRuntimeRegistry


@pytest.mark.asyncio
async def test_acquire_rechecks_project_before_registering() -> None:
    registry = WorkbenchRuntimeRegistry()
    verified = False

    async def verify() -> None:
        nonlocal verified
        verified = True

    await registry.acquire(
        user_id="user-1",
        project_id="project-1",
        resource_type=RuntimeResourceType.PTY_SESSION,
        resource_id="pty-1",
        verify_project=verify,
    )

    assert verified is True
    resources = await registry.list_active("user-1", "project-1")
    assert [(item.resource_type, item.resource_id) for item in resources] == [
        (RuntimeResourceType.PTY_SESSION, "pty-1")
    ]


@pytest.mark.asyncio
async def test_exclusive_guard_blocks_new_resource_until_delete_finishes() -> None:
    registry = WorkbenchRuntimeRegistry()
    delete_started = asyncio.Event()
    allow_delete_finish = asyncio.Event()
    acquire_finished = asyncio.Event()

    async def delete_project() -> None:
        async with registry.exclusive("user-1", "project-1") as guard:
            guard.assert_not_in_use()
            delete_started.set()
            await allow_delete_finish.wait()

    async def acquire_resource() -> None:
        await delete_started.wait()
        await registry.acquire(
            user_id="user-1",
            project_id="project-1",
            resource_type=RuntimeResourceType.ACP_SESSION,
            resource_id="acp-1",
            verify_project=lambda: None,
        )
        acquire_finished.set()

    delete_task = asyncio.create_task(delete_project())
    acquire_task = asyncio.create_task(acquire_resource())
    await delete_started.wait()
    await asyncio.sleep(0)
    assert acquire_finished.is_set() is False

    allow_delete_finish.set()
    await asyncio.gather(delete_task, acquire_task)
    assert acquire_finished.is_set() is True


@pytest.mark.asyncio
async def test_guard_reports_project_in_use() -> None:
    registry = WorkbenchRuntimeRegistry()
    await registry.acquire(
        user_id="user-1",
        project_id="project-1",
        resource_type=RuntimeResourceType.ACP_TURN,
        resource_id="turn-1",
        verify_project=lambda: None,
    )

    async with registry.exclusive("user-1", "project-1") as guard:
        with pytest.raises(ProjectInUse) as exc_info:
            guard.assert_not_in_use()

    assert exc_info.value.resource_ids == ("turn-1",)


@pytest.mark.asyncio
async def test_release_and_close_all_do_not_leak_resources() -> None:
    registry = WorkbenchRuntimeRegistry()
    closed: list[str] = []

    async def close_resource() -> None:
        closed.append("pty-1")

    await registry.acquire(
        user_id="user-1",
        project_id="project-1",
        resource_type=RuntimeResourceType.PTY_SESSION,
        resource_id="pty-1",
        verify_project=lambda: None,
        close_callback=close_resource,
    )
    await registry.close_all("user-1", "project-1")

    assert closed == ["pty-1"]
    assert await registry.list_active("user-1", "project-1") == ()


@pytest.mark.asyncio
async def test_release_is_idempotent() -> None:
    registry = WorkbenchRuntimeRegistry()
    await registry.release(
        user_id="user-1",
        project_id="project-1",
        resource_type=RuntimeResourceType.PTY_SESSION,
        resource_id="missing",
    )

    assert await registry.list_active("user-1", "project-1") == ()


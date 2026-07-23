"""
ChatTaskManager 单测：覆盖任务生命周期、订阅回放、断连重连、取消、失败路径。

测试目标：
- 任务在独立 asyncio.Task 中运行，SSE 断连不终止任务
- 事件按 seq 顺序持久化，前端重连可从 from_seq 恢复完整历史
- 用户主动取消时 background_task 收到 CancelledError 并标记 cancelled
- 任务异常时标记 failed 并广播 error 事件
- 已完成任务重连仅回放历史事件后退出
- list_user_tasks 按用户/会话隔离且按创建时间倒序
"""

import asyncio

import pytest

from core.chat_task_manager import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_PENDING,
    TASK_STATUS_RUNNING,
    ChatTaskManager,
    generate_task_id,
    get_chat_task_manager,
)


@pytest.fixture
def manager():
    """每个用例独立 manager 实例，避免单例污染。"""
    return ChatTaskManager()


async def _collect_events(gen):
    """收集异步生成器的所有事件，返回 list。"""
    events = []
    async for event in gen:
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_register_task_creates_pending_task(manager):
    """注册任务应创建 pending 状态的 ChatTask。"""
    task_id = generate_task_id()
    task = await manager.register_task(task_id, "user-1", "session-1", "req-1")

    assert task.task_id == task_id
    assert task.user_id == "user-1"
    assert task.session_id == "session-1"
    assert task.status == TASK_STATUS_PENDING
    assert task.next_seq == 0
    assert len(task.events) == 0
    assert task.background_task is None


@pytest.mark.asyncio
async def test_register_task_is_idempotent(manager):
    """重复注册同一 task_id 应返回已有任务（幂等）。"""
    task_id = generate_task_id()
    first = await manager.register_task(task_id, "user-1", "session-1", "req-1")
    second = await manager.register_task(task_id, "user-1", "session-1", "req-2")

    assert first is second


@pytest.mark.asyncio
async def test_start_task_runs_to_completion(manager):
    """任务正常结束应标记 completed，事件按 seq 顺序持久化。"""

    async def fake_run():
        yield {"type": "status", "message": "step 1"}
        yield {"type": "content", "text": "hello"}
        yield {"type": "done"}

    task_id = generate_task_id()
    await manager.register_task(task_id, "user-1", "session-1", "req-1")
    await manager.start_task(task_id, fake_run)

    # 等待后台任务完成
    task = manager._tasks[task_id]
    assert task.background_task is not None
    await task.background_task

    assert task.status == TASK_STATUS_COMPLETED
    assert task.finished_at is not None
    assert len(task.events) == 3
    assert [e.seq for e in task.events] == [0, 1, 2]
    assert task.next_seq == 3


@pytest.mark.asyncio
async def test_subscribe_replays_history_and_yields_realtime(manager):
    """订阅应先回放历史事件，再继续推送实时事件。"""
    received = []

    async def fake_run():
        yield {"type": "content", "text": "a"}
        yield {"type": "content", "text": "b"}
        await asyncio.sleep(0.05)
        yield {"type": "content", "text": "c"}

    task_id = generate_task_id()
    await manager.register_task(task_id, "user-1", "session-1", "req-1")

    # 启动后台任务前先订阅，确保能收到全部事件
    # 但 subscribe 会先添加 queue 再回放历史，此时无历史可回放
    subscribe_gen = manager.subscribe(task_id, from_seq=0)

    # 启动任务
    await manager.start_task(task_id, fake_run)

    # 消费所有事件
    received = await _collect_events(subscribe_gen)

    assert len(received) == 3
    assert [e["_seq"] for e in received] == [0, 1, 2]
    assert received[0]["text"] == "a"
    assert received[2]["text"] == "c"


@pytest.mark.asyncio
async def test_subscribe_completed_task_only_replays_history(manager):
    """已完成任务订阅应仅回放历史事件后立即退出。"""

    async def fake_run():
        yield {"type": "content", "text": "x"}
        yield {"type": "content", "text": "y"}

    task_id = generate_task_id()
    await manager.register_task(task_id, "user-1", "session-1", "req-1")
    await manager.start_task(task_id, fake_run)
    task = manager._tasks[task_id]
    await task.background_task  # 等待完成

    # 任务完成后订阅
    events = await _collect_events(manager.subscribe(task_id, from_seq=0))

    assert len(events) == 2
    assert [e["_seq"] for e in events] == [0, 1]


@pytest.mark.asyncio
async def test_resubscribe_from_seq_skips_replayed(manager):
    """断连重连时 from_seq > 0 应跳过已消费事件。"""

    async def fake_run():
        yield {"type": "content", "text": "1"}
        yield {"type": "content", "text": "2"}
        yield {"type": "content", "text": "3"}
        yield {"type": "content", "text": "4"}

    task_id = generate_task_id()
    await manager.register_task(task_id, "user-1", "session-1", "req-1")
    await manager.start_task(task_id, fake_run)
    task = manager._tasks[task_id]
    await task.background_task

    # 模拟前端已收到 seq 0、1（lastSeq=1），重连时 from_seq=2
    events = await _collect_events(manager.subscribe(task_id, from_seq=2))

    assert len(events) == 2
    assert [e["_seq"] for e in events] == [2, 3]
    assert events[0]["text"] == "3"
    assert events[1]["text"] == "4"


@pytest.mark.asyncio
async def test_resubscribe_nonexistent_task_returns_empty(manager):
    """订阅不存在的 task_id 应返回空流（不抛异常）。"""
    events = await _collect_events(manager.subscribe("nonexistent", from_seq=0))
    assert events == []


@pytest.mark.asyncio
async def test_cancel_task_marks_cancelled(manager):
    """用户主动取消应让 background_task 收到 CancelledError 并标记 cancelled。"""

    async def slow_run():
        yield {"type": "content", "text": "start"}
        await asyncio.sleep(10)
        yield {"type": "content", "text": "should not reach"}

    task_id = generate_task_id()
    await manager.register_task(task_id, "user-1", "session-1", "req-1")
    await manager.start_task(task_id, slow_run)
    task = manager._tasks[task_id]

    # 等任务发出第一个事件
    await asyncio.sleep(0.05)
    assert task.status == TASK_STATUS_RUNNING

    cancelled = await manager.cancel_task(task_id)
    assert cancelled is True

    # 等待 background_task 处理 CancelledError
    with pytest.raises(asyncio.CancelledError):
        await task.background_task

    assert task.status == TASK_STATUS_CANCELLED
    assert task.finished_at is not None


@pytest.mark.asyncio
async def test_cancel_nonexistent_or_finished_task_returns_false(manager):
    """取消不存在或已完成的任务应返回 False。"""

    async def fake_run():
        yield {"type": "content", "text": "done"}

    # 不存在
    assert await manager.cancel_task("nonexistent") is False

    # 已完成
    task_id = generate_task_id()
    await manager.register_task(task_id, "user-1", "session-1", "req-1")
    await manager.start_task(task_id, fake_run)
    task = manager._tasks[task_id]
    await task.background_task

    assert await manager.cancel_task(task_id) is False


@pytest.mark.asyncio
async def test_failed_task_emits_error_event_and_marks_failed(manager):
    """任务抛异常应广播 error 事件并标记 failed。"""

    async def failing_run():
        yield {"type": "content", "text": "partial"}
        raise RuntimeError("boom")

    task_id = generate_task_id()
    await manager.register_task(task_id, "user-1", "session-1", "req-1")
    await manager.start_task(task_id, failing_run)
    task = manager._tasks[task_id]

    # 订阅应能收到 partial + error 事件
    events = await _collect_events(manager.subscribe(task_id, from_seq=0))

    # 等待 background_task 结束
    await task.background_task

    assert task.status == TASK_STATUS_FAILED
    assert task.error is not None
    assert task.error["code"] == "task_internal_error"
    assert "boom" in task.error["message"]

    # 事件流应包含 partial + error
    assert len(events) == 2
    assert events[0]["text"] == "partial"
    assert events[1]["type"] == "error"
    assert events[1]["error"]["code"] == "task_internal_error"


@pytest.mark.asyncio
async def test_get_task_status_returns_summary(manager):
    """get_task_status 应返回任务摘要 dict。"""

    async def fake_run():
        yield {"type": "content", "text": "hi"}

    task_id = generate_task_id()
    await manager.register_task(task_id, "user-1", "session-1", "req-1")
    await manager.start_task(task_id, fake_run)
    task = manager._tasks[task_id]
    await task.background_task

    status = await manager.get_task_status(task_id)
    assert status is not None
    assert status["task_id"] == task_id
    assert status["status"] == TASK_STATUS_COMPLETED
    assert status["event_count"] == 1
    assert status["next_seq"] == 1
    assert status["session_id"] == "session-1"
    assert status["user_id"] == "user-1"
    assert status["finished_at"] is not None


@pytest.mark.asyncio
async def test_get_task_status_returns_none_for_nonexistent(manager):
    """查询不存在的任务应返回 None。"""
    assert await manager.get_task_status("nonexistent") is None


@pytest.mark.asyncio
async def test_list_user_tasks_filters_by_user_and_session(manager):
    """list_user_tasks 应按 user_id 过滤，可选按 session_id 过滤。"""
    # 用户 1 的两个会话
    t1 = generate_task_id()
    await manager.register_task(t1, "user-1", "session-a", "r1")
    t2 = generate_task_id()
    await manager.register_task(t2, "user-1", "session-b", "r2")
    # 用户 2 的任务
    t3 = generate_task_id()
    await manager.register_task(t3, "user-2", "session-c", "r3")

    # user-1 全部会话
    tasks = await manager.list_user_tasks("user-1")
    assert {t["task_id"] for t in tasks} == {t1, t2}

    # user-1 仅 session-a
    tasks = await manager.list_user_tasks("user-1", session_id="session-a")
    assert {t["task_id"] for t in tasks} == {t1}

    # user-2
    tasks = await manager.list_user_tasks("user-2")
    assert {t["task_id"] for t in tasks} == {t3}


@pytest.mark.asyncio
async def test_list_user_tasks_excludes_finished_by_default(manager):
    """默认不返回已完成任务，include_finished=True 才返回。"""

    async def fake_run():
        yield {"type": "content", "text": "done"}

    # 已完成
    t1 = generate_task_id()
    await manager.register_task(t1, "user-1", "session-a", "r1")
    await manager.start_task(t1, fake_run)
    await manager._tasks[t1].background_task

    # pending
    t2 = generate_task_id()
    await manager.register_task(t2, "user-1", "session-a", "r2")

    # 默认排除已完成
    tasks = await manager.list_user_tasks("user-1")
    assert {t["task_id"] for t in tasks} == {t2}

    # include_finished=True 包含已完成
    tasks = await manager.list_user_tasks("user-1", include_finished=True)
    assert {t["task_id"] for t in tasks} == {t1, t2}


@pytest.mark.asyncio
async def test_list_user_tasks_sorted_by_created_at_desc(manager):
    """list_user_tasks 应按 created_at 倒序排列。"""
    t1 = generate_task_id()
    await manager.register_task(t1, "user-1", "session-a", "r1")
    # 微小延迟确保 created_at 不同
    await asyncio.sleep(0.005)
    t2 = generate_task_id()
    await manager.register_task(t2, "user-1", "session-a", "r2")
    await asyncio.sleep(0.005)
    t3 = generate_task_id()
    await manager.register_task(t3, "user-1", "session-a", "r3")

    tasks = await manager.list_user_tasks("user-1", include_finished=True)
    assert [t["task_id"] for t in tasks] == [t3, t2, t1]


@pytest.mark.asyncio
async def test_event_seq_injected_into_payload(manager):
    """subscribe 返回的事件 payload 应注入 _seq 字段。"""

    async def fake_run():
        yield {"type": "content", "text": "a"}
        yield {"type": "content", "text": "b"}

    task_id = generate_task_id()
    await manager.register_task(task_id, "user-1", "session-1", "req-1")
    await manager.start_task(task_id, fake_run)
    task = manager._tasks[task_id]
    await task.background_task

    events = await _collect_events(manager.subscribe(task_id, from_seq=0))
    assert all("_seq" in e for e in events)
    assert [e["_seq"] for e in events] == [0, 1]


@pytest.mark.asyncio
async def test_get_chat_task_manager_returns_singleton():
    """get_chat_task_manager 应返回同一单例。"""
    m1 = get_chat_task_manager()
    m2 = get_chat_task_manager()
    assert m1 is m2


@pytest.mark.asyncio
async def test_generate_task_id_is_unique_hex():
    """generate_task_id 应返回 32 位 hex 字符串且唯一。"""
    ids = {generate_task_id() for _ in range(100)}
    assert len(ids) == 100
    for tid in ids:
        assert len(tid) == 32
        int(tid, 16)  # 校验是合法 hex

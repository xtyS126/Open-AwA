"""多 Agent 讨论编排器 DiscussionOrchestrator 单元测试。

测试目标：
  覆盖 core/discussion/orchestrator.py 的 DiscussionOrchestrator 类核心方法：
  - create_task：创建讨论任务并写入数据库
  - run_discussion_round：顺序调用三个角色（critic/validator/approver）评审
  - tally_votes：统计投票结果决定后续状态
  - revise_action：提交修订触发新一轮
  - execute_approved_action：执行被批准的提议动作
  - subscribe/unsubscribe/_emit_event：事件总线订阅与推送

测试策略：
  - 数据库：in-memory SQLite + StaticPool，仅创建 User/DiscussionTask/DiscussionVote 三张表
  - LLM 调用：使用工厂函数构造可配置返回内容的 async caller，不依赖真实 LLM 服务
  - 后台触发：patch _safe_run_discussion_round 与 _safe_execute_approved_action 为 AsyncMock，
    禁用 create_task/revise/tally 内部的 fire-and-forget，保证测试确定性
  - 执行器：patch _execute_tool_call 等 executor 方法，mock 外部 tool_registry 依赖

测试隔离：
  每个测试通过 fixture 获取独立的 orchestrator 实例与干净的数据库会话工厂；
  数据库表在模块级创建一次，每个测试通过 _seed_task 直接插入数据绕过自动触发。
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# 将 backend 目录加入 sys.path
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from core.discussion.definitions import (  # noqa: E402
    DiscussionExecutionError,
    DiscussionParseError,
    DiscussionRoundLimitError,
    DiscussionStateError,
    DiscussionStatus,
    DiscussionTaskData,
    DiscussionVoteData,
    ProposedAction,
    VoteDecision,
)
from core.discussion.orchestrator import DiscussionOrchestrator  # noqa: E402
from db.models import Base, DiscussionTask, DiscussionVote, User  # noqa: E402
import core.subagent_task_runtime_bridge as bridge  # noqa: E402


# ── 模块级测试数据库 ──────────────────────────────────────────────
# 所有连接共享同一 in-memory 数据库（StaticPool 保证连接复用）
_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
# 仅创建讨论相关三张表，避免全量建表开销与外键依赖问题
Base.metadata.create_all(
    bind=_engine,
    tables=[User.__table__, DiscussionTask.__table__, DiscussionVote.__table__],
)


def _db_session_factory():
    """返回支持上下文管理器的测试数据库会话，签名与 db.models.SessionLocal 一致。"""
    return _TestingSessionLocal()


def _make_llm_caller(*responses: str):
    """
    构造可配置的 async LLM caller，按顺序返回 responses。

    responses 耗尽后返回默认 approve，避免多轮测试中 StopIteration 中断。
    """
    iterator = iter(responses)

    async def _caller(messages):
        try:
            return next(iterator)
        except StopIteration:
            return '{"vote": "approve", "reason": "默认通过"}'

    return _caller


def _default_approve_caller():
    """返回始终 approve 的 LLM caller（三方一致通过场景）。"""
    return _make_llm_caller(
        '{"vote": "approve", "reason": "critic 认可"}',
        '{"vote": "approve", "reason": "validator 认可"}',
        '{"vote": "approve", "reason": "approver 认可"}',
    )


def _seed_task(
    *,
    status: str = "created",
    round_num: int = 1,
    max_rounds: int = 3,
    user_id: str = "u1",
    title: str = "测试任务",
    description: str = "测试描述",
    proposed_action_type: str = "tool_call",
) -> str:
    """
    直接向数据库插入讨论任务记录，绕过 create_task 的自动触发。

    返回新创建的任务 ID，便于测试在特定状态下初始化。
    """
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    with _TestingSessionLocal() as db:
        task = DiscussionTask(
            id=task_id,
            user_id=user_id,
            title=title,
            description=description,
            proposed_action={
                "type": proposed_action_type,
                "payload": {"tool": "test_tool", "parameters": {}},
            },
            context={},
            status=status,
            round=round_num,
            max_rounds=max_rounds,
            created_at=now,
            updated_at=now,
        )
        db.add(task)
        db.commit()
    return task_id


def _seed_user(user_id: str = "u1", username: str = "tester"):
    """插入测试用户记录，满足 DiscussionTask.user_id 外键约束。"""
    with _TestingSessionLocal() as db:
        user = User(
            id=user_id,
            username=username,
            password_hash="hash",
            role="user",
        )
        db.add(user)
        db.commit()


def _load_task_status(task_id: str) -> str:
    """从数据库加载任务当前状态，便于断言。"""
    with _TestingSessionLocal() as db:
        task = db.get(DiscussionTask, task_id)
        return task.status if task else "missing"


def _load_task_round(task_id: str) -> int:
    """从数据库加载任务当前轮次。"""
    with _TestingSessionLocal() as db:
        task = db.get(DiscussionTask, task_id)
        return task.round if task else -1


def _count_votes(task_id: str, round_num: int = 1) -> int:
    """统计指定任务指定轮次的投票记录数。"""
    with _TestingSessionLocal() as db:
        return (
            db.query(DiscussionVote)
            .filter(
                DiscussionVote.discussion_id == task_id,
                DiscussionVote.round == round_num,
            )
            .count()
        )


def _count_all_votes(task_id: str) -> int:
    """统计指定任务的全部投票记录数。"""
    with _TestingSessionLocal() as db:
        return db.query(DiscussionVote).filter(DiscussionVote.discussion_id == task_id).count()


def _seed_subagent_delegate_task(
    *,
    status: str = "approved",
    agent: str = "searcher",
    instruction: str = "调研代码库中子代理实现",
    context_snippet: str = "",
) -> str:
    """直接插入 subagent_delegate 类型的讨论任务，返回任务 ID。"""
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    with _TestingSessionLocal() as db:
        task = DiscussionTask(
            id=task_id,
            user_id="u1",
            title="子代理委派",
            description="委派调研任务",
            proposed_action={
                "type": "subagent_delegate",
                "payload": {
                    "agent": agent,
                    "instruction": instruction,
                    "context_snippet": context_snippet,
                },
            },
            context={},
            status=status,
            round=1,
            max_rounds=3,
            created_at=now,
            updated_at=now,
        )
        db.add(task)
        db.commit()
    return task_id


def _make_fake_spawn_stream(
    summary: str = "调研完成，找到相关实现",
    state: str = "completed",
):
    """构造 spawn_agent 的前台事件流 mock，避免依赖真实 LLM。"""

    async def fake_spawn_agent(*args, **kwargs):
        async def stream():
            yield {
                "type": "subagent_start",
                "agent_id": "agent-mock-1",
                "agent_type": kwargs.get("agent_type", "Explore"),
            }
            yield {
                "type": "subagent_stop",
                "state": state,
                "summary": summary,
                "agent_id": "agent-mock-1",
            }

        return stream()

    return fake_spawn_agent


# ── fixture ──────────────────────────────────────────────────────


@pytest.fixture
def db_session_factory():
    """提供测试数据库会话工厂，每个测试前后清理投票与任务表。"""
    # 前置清理
    with _TestingSessionLocal() as db:
        db.query(DiscussionVote).delete()
        db.query(DiscussionTask).delete()
        db.query(User).delete()
        db.commit()
    _seed_user()
    yield _db_session_factory
    # 后置清理
    with _TestingSessionLocal() as db:
        db.query(DiscussionVote).delete()
        db.query(DiscussionTask).delete()
        db.query(User).delete()
        db.commit()


@pytest.fixture
def mock_llm_caller():
    """返回默认 approve 的 LLM caller，测试中可通过 monkeypatch 替换。"""
    return _default_approve_caller()


@pytest.fixture
def orchestrator(db_session_factory, mock_llm_caller):
    """
    构造 DiscussionOrchestrator 实例，注入测试数据库与 mock LLM。

    关键：patch _safe_run_discussion_round 与 _safe_execute_approved_action 为 AsyncMock，
    禁用 create_task/revise/tally 内部的 fire-and-forget 后台任务，保证测试确定性。
    测试需要执行讨论轮次时直接 await run_discussion_round；
    需要执行动作时直接 await execute_approved_action。
    """
    orch = DiscussionOrchestrator(
        db_session_factory=db_session_factory,
        llm_caller=mock_llm_caller,
    )
    # 禁用后台自动触发：create_task 与 revise_action 内部 asyncio.create_task 包装的回调
    orch._safe_run_discussion_round = AsyncMock(return_value=None)
    # 禁用 tally_votes 内部自动触发的执行回调
    orch._safe_execute_approved_action = AsyncMock(return_value=None)
    yield orch


def _make_proposed_action(action_type: str = "tool_call") -> ProposedAction:
    """构造测试用 ProposedAction。"""
    return ProposedAction(
        type=action_type,
        payload={"tool": "test_tool", "parameters": {}},
    )


# ── 创建任务测试 ──────────────────────────────────────────────────


async def test_create_task_persists_to_db(orchestrator):
    """create_task 后数据库应有 1 条记录，状态为 created。"""
    task_id = await orchestrator.create_task(
        user_id="u1",
        title="新建任务",
        description="描述内容",
        proposed_action=_make_proposed_action(),
        context={},
    )
    # 让 create_task 内部的 asyncio.create_task（包装 AsyncMock）完成，避免 pending 警告
    await asyncio.sleep(0.05)

    with _TestingSessionLocal() as db:
        tasks = db.query(DiscussionTask).all()
        assert len(tasks) == 1
        assert tasks[0].id == task_id
        # create_task 写入时状态为 created，后台 _safe_run 被 patch 为 no-op 不改变状态
        assert tasks[0].status == "created"


async def test_create_task_returns_task_data_with_id(orchestrator):
    """create_task 返回的 task_id 应为非空字符串。"""
    task_id = await orchestrator.create_task(
        user_id="u1",
        title="带 ID 的任务",
        description="描述",
        proposed_action=_make_proposed_action(),
        context={},
    )
    await asyncio.sleep(0.05)

    assert isinstance(task_id, str)
    assert len(task_id) > 0
    # 校验返回的 ID 能在数据库中查到
    with _TestingSessionLocal() as db:
        assert db.get(DiscussionTask, task_id) is not None


async def test_create_task_rejects_empty_title(orchestrator):
    """空标题应抛 ValueError（create_task 内部基础校验）。"""
    with pytest.raises(ValueError):
        await orchestrator.create_task(
            user_id="u1",
            title="",
            description="描述",
            proposed_action=_make_proposed_action(),
            context={},
        )


async def test_create_task_rejects_empty_description(orchestrator):
    """空描述应抛 ValueError。"""
    with pytest.raises(ValueError):
        await orchestrator.create_task(
            user_id="u1",
            title="标题",
            description="",
            proposed_action=_make_proposed_action(),
            context={},
        )


async def test_create_task_rejects_invalid_max_rounds(orchestrator):
    """max_rounds < 1 应抛 ValueError。"""
    with pytest.raises(ValueError):
        await orchestrator.create_task(
            user_id="u1",
            title="标题",
            description="描述",
            proposed_action=_make_proposed_action(),
            context={},
            max_rounds=0,
        )


# ── 三方通过场景测试 ──────────────────────────────────────────────


async def test_run_discussion_round_three_approves_transitions_to_approved(orchestrator):
    """三个角色都 approve -> 任务状态转 approved。"""
    task_id = _seed_task(status="created")
    await orchestrator.run_discussion_round(task_id)

    assert _load_task_status(task_id) == "approved"


async def test_run_discussion_round_writes_three_votes_to_db(orchestrator):
    """三轮投票都写入 DB，共 3 条 vote 记录。"""
    task_id = _seed_task(status="created")
    await orchestrator.run_discussion_round(task_id)

    assert _count_all_votes(task_id) == 3
    assert _count_votes(task_id, round_num=1) == 3


# ── 任一拒绝场景测试 ──────────────────────────────────────────────


async def test_run_discussion_round_critic_rejects_transitions_to_pending_approval():
    """critic 投 reject -> 任务转 pending_approval 等待修订。"""
    caller = _make_llm_caller(
        '{"vote": "reject", "reason": "critic 反对"}',
        '{"vote": "approve", "reason": "validator 同意"}',
        '{"vote": "approve", "reason": "approver 同意"}',
    )
    orch = DiscussionOrchestrator(db_session_factory=_db_session_factory, llm_caller=caller)
    orch._safe_run_discussion_round = AsyncMock(return_value=None)
    orch._safe_execute_approved_action = AsyncMock(return_value=None)

    task_id = _seed_task(status="created")
    await orch.run_discussion_round(task_id)

    assert _load_task_status(task_id) == "pending_approval"


async def test_run_discussion_round_validator_rejects_transitions_to_pending_approval():
    """validator 投 reject -> 任务转 pending_approval。"""
    caller = _make_llm_caller(
        '{"vote": "approve", "reason": "critic 同意"}',
        '{"vote": "reject", "reason": "validator 反对"}',
        '{"vote": "approve", "reason": "approver 同意"}',
    )
    orch = DiscussionOrchestrator(db_session_factory=_db_session_factory, llm_caller=caller)
    orch._safe_run_discussion_round = AsyncMock(return_value=None)
    orch._safe_execute_approved_action = AsyncMock(return_value=None)

    task_id = _seed_task(status="created")
    await orch.run_discussion_round(task_id)

    assert _load_task_status(task_id) == "pending_approval"


async def test_run_discussion_round_approver_rejects_transitions_to_pending_approval():
    """approver 投 reject -> 任务转 pending_approval。"""
    caller = _make_llm_caller(
        '{"vote": "approve", "reason": "critic 同意"}',
        '{"vote": "approve", "reason": "validator 同意"}',
        '{"vote": "reject", "reason": "approver 最终否决"}',
    )
    orch = DiscussionOrchestrator(db_session_factory=_db_session_factory, llm_caller=caller)
    orch._safe_run_discussion_round = AsyncMock(return_value=None)
    orch._safe_execute_approved_action = AsyncMock(return_value=None)

    task_id = _seed_task(status="created")
    await orch.run_discussion_round(task_id)

    assert _load_task_status(task_id) == "pending_approval"


# ── 修订重试场景测试 ──────────────────────────────────────────────


async def test_revise_action_increments_round(orchestrator):
    """当前 round=1 -> revise 后 round=2。"""
    task_id = _seed_task(status="pending_approval", round_num=1, max_rounds=3)
    await orchestrator.revise_action(task_id, _make_proposed_action())
    await asyncio.sleep(0.05)

    assert _load_task_round(task_id) == 2


async def test_revise_action_resets_votes_for_new_round(orchestrator):
    """revise 后新一轮（round=2）无 vote 记录，旧轮次记录保留。"""
    task_id = _seed_task(status="pending_approval", round_num=1, max_rounds=3)
    # 第一轮已有投票
    with _TestingSessionLocal() as db:
        db.add(DiscussionVote(
            id=str(uuid.uuid4()),
            discussion_id=task_id,
            role="critic",
            round=1,
            vote="reject",
            reason="反对",
            transcript=[],
        ))
        db.commit()
    assert _count_votes(task_id, round_num=1) == 1

    await orchestrator.revise_action(task_id, _make_proposed_action())
    await asyncio.sleep(0.05)

    # 新轮次无投票记录
    assert _count_votes(task_id, round_num=2) == 0
    # 旧轮次记录保留（不删除）
    assert _count_votes(task_id, round_num=1) == 1


# ── 超过最大轮次测试 ──────────────────────────────────────────────


async def test_revise_action_exceeding_max_rounds_raises(orchestrator):
    """max_rounds=3，当前 round=3 -> revise 抛 DiscussionRoundLimitError。"""
    task_id = _seed_task(status="pending_approval", round_num=3, max_rounds=3)
    with pytest.raises(DiscussionRoundLimitError):
        await orchestrator.revise_action(task_id, _make_proposed_action())
    # 超过轮次应转为 rejected 终态
    assert _load_task_status(task_id) == "rejected"


async def test_revise_action_rejects_when_in_approved(orchestrator):
    """approved 状态不允许修订，抛 DiscussionStateError。"""
    task_id = _seed_task(status="approved", round_num=1, max_rounds=3)
    with pytest.raises(DiscussionStateError):
        await orchestrator.revise_action(task_id, _make_proposed_action())


async def test_revise_action_rejects_when_in_completed(orchestrator):
    """completed 终态不允许修订，抛 DiscussionStateError。"""
    task_id = _seed_task(status="completed", round_num=1, max_rounds=3)
    with pytest.raises(DiscussionStateError):
        await orchestrator.revise_action(task_id, _make_proposed_action())


# ── 执行测试 ──────────────────────────────────────────────────────


async def test_execute_approved_action_transitions_to_executing_then_completed(orchestrator):
    """approved -> execute -> executing -> completed（mock 执行器返回成功）。"""
    task_id = _seed_task(status="approved", round_num=1, max_rounds=3)
    # mock 执行器避免触发真实 tool_registry
    with patch.object(
        orchestrator,
        "_execute_tool_call",
        new=AsyncMock(return_value={"ok": True, "result": "执行成功"}),
    ):
        result = await orchestrator.execute_approved_action(task_id)

    assert _load_task_status(task_id) == "completed"
    assert result["ok"] is True
    # 结果应回写到 context.result
    with _TestingSessionLocal() as db:
        task = db.get(DiscussionTask, task_id)
        assert task.context.get("result") == {"ok": True, "result": "执行成功"}


async def test_execute_approved_action_fails_transitions_to_failed(orchestrator):
    """mock 执行器抛异常 -> 状态转 failed。"""
    task_id = _seed_task(status="approved", round_num=1, max_rounds=3)
    with patch.object(
        orchestrator,
        "_execute_tool_call",
        new=AsyncMock(side_effect=DiscussionExecutionError("工具执行失败")),
    ):
        with pytest.raises(DiscussionExecutionError):
            await orchestrator.execute_approved_action(task_id)

    assert _load_task_status(task_id) == "failed"
    # 错误信息应回写到 context.error
    with _TestingSessionLocal() as db:
        task = db.get(DiscussionTask, task_id)
        assert "工具执行失败" in task.context.get("error", "")


async def test_execute_approved_action_rejects_when_not_approved(orchestrator):
    """非 approved 状态执行应抛 DiscussionStateError。"""
    task_id = _seed_task(status="created", round_num=1, max_rounds=3)
    with pytest.raises(DiscussionStateError):
        await orchestrator.execute_approved_action(task_id)


async def test_execute_approved_action_rejects_unknown_task(orchestrator):
    """不存在的任务执行应抛 DiscussionStateError。"""
    with pytest.raises(DiscussionStateError):
        await orchestrator.execute_approved_action("nonexistent-task-id")


# ── LLM 解析错误测试 ──────────────────────────────────────────────


async def test_run_discussion_round_handles_llm_invalid_json():
    """LLM 返回非 JSON -> 优雅降级为 abstain 投票（不抛异常）。"""
    caller = _make_llm_caller(
        "这不是合法 JSON 内容",
        '{"vote": "approve", "reason": "ok"}',
        '{"vote": "approve", "reason": "ok"}',
    )
    orch = DiscussionOrchestrator(db_session_factory=_db_session_factory, llm_caller=caller)
    orch._safe_run_discussion_round = AsyncMock(return_value=None)
    orch._safe_execute_approved_action = AsyncMock(return_value=None)

    task_id = _seed_task(status="created")
    # 不抛异常，critic 投票降级为 abstain
    await orch.run_discussion_round(task_id)

    # abstain 属于非 approve，应转 pending_approval
    assert _load_task_status(task_id) == "pending_approval"
    # 验证 critic 投票为 abstain
    with _TestingSessionLocal() as db:
        vote = db.query(DiscussionVote).filter(
            DiscussionVote.discussion_id == task_id,
            DiscussionVote.role == "critic",
        ).first()
        assert vote is not None
        assert vote.vote == "abstain"


async def test_run_discussion_round_handles_llm_missing_vote_field():
    """LLM 返回 JSON 但缺 vote 字段 -> 降级为 abstain 投票。"""
    caller = _make_llm_caller(
        '{"reason": "我忘了 vote 字段", "concerns": []}',
        '{"vote": "approve", "reason": "ok"}',
        '{"vote": "approve", "reason": "ok"}',
    )
    orch = DiscussionOrchestrator(db_session_factory=_db_session_factory, llm_caller=caller)
    orch._safe_run_discussion_round = AsyncMock(return_value=None)
    orch._safe_execute_approved_action = AsyncMock(return_value=None)

    task_id = _seed_task(status="created")
    await orch.run_discussion_round(task_id)

    # abstain -> 非 approve -> pending_approval
    assert _load_task_status(task_id) == "pending_approval"


async def test_run_discussion_round_handles_empty_llm_output():
    """LLM 返回空字符串 -> 降级为 abstain。"""
    caller = _make_llm_caller(
        "",
        '{"vote": "approve", "reason": "ok"}',
        '{"vote": "approve", "reason": "ok"}',
    )
    orch = DiscussionOrchestrator(db_session_factory=_db_session_factory, llm_caller=caller)
    orch._safe_run_discussion_round = AsyncMock(return_value=None)
    orch._safe_execute_approved_action = AsyncMock(return_value=None)

    task_id = _seed_task(status="created")
    await orch.run_discussion_round(task_id)

    assert _load_task_status(task_id) == "pending_approval"


# ── 事件总线测试 ──────────────────────────────────────────────────


async def test_subscribe_receives_events(orchestrator):
    """subscribe 后调用 run_discussion_round，订阅者应收到 discussion_message/vote_cast 事件。"""
    task_id = _seed_task(status="created")
    queue = orchestrator.subscribe(task_id)

    await orchestrator.run_discussion_round(task_id)

    # 排空队列收集事件
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    event_types = [e["type"] for e in events]

    # 应包含状态变更、讨论消息与投票事件
    assert "status_changed" in event_types
    assert "discussion_message" in event_types
    assert "vote_cast" in event_types
    # 三个角色应各触发一次 vote_cast
    vote_events = [e for e in events if e["type"] == "vote_cast"]
    assert len(vote_events) == 3


async def test_unsubscribe_stops_receiving_events(orchestrator):
    """unsubscribe 后不再收到事件。"""
    task_id = _seed_task(status="created")
    queue = orchestrator.subscribe(task_id)
    orchestrator.unsubscribe(task_id, queue)

    await orchestrator.run_discussion_round(task_id)

    # 取消订阅后队列应为空
    assert queue.empty()


async def test_emit_event_to_multiple_subscribers(orchestrator):
    """多个订阅者应同时收到事件。"""
    task_id = _seed_task(status="created")
    queue1 = orchestrator.subscribe(task_id)
    queue2 = orchestrator.subscribe(task_id)

    await orchestrator._emit_event(task_id, "test_event", {"task_id": task_id})

    assert not queue1.empty()
    assert not queue2.empty()
    event1 = queue1.get_nowait()
    event2 = queue2.get_nowait()
    assert event1["type"] == "test_event"
    assert event2["type"] == "test_event"


# ── 状态转换校验测试 ──────────────────────────────────────────────


async def test_run_discussion_round_rejects_when_in_approved(orchestrator):
    """approved 状态不允许进入讨论，抛 DiscussionStateError。"""
    task_id = _seed_task(status="approved", round_num=1, max_rounds=3)
    with pytest.raises(DiscussionStateError):
        await orchestrator.run_discussion_round(task_id)


async def test_run_discussion_round_rejects_unknown_task(orchestrator):
    """不存在的任务执行讨论轮次应抛 DiscussionStateError。"""
    with pytest.raises(DiscussionStateError):
        await orchestrator.run_discussion_round("nonexistent-task-id")


# ── parse_llm_vote_output 单元测试 ──────────────────────────────────


def test_parse_llm_vote_output_extracts_approve():
    """合法 JSON 含 approve vote 应正确解析。"""
    orch = DiscussionOrchestrator(db_session_factory=_db_session_factory, llm_caller=_default_approve_caller())
    vote, reason = orch._parse_llm_vote_output('{"vote": "approve", "reason": "通过"}')
    assert vote == "approve"
    assert reason == "通过"


def test_parse_llm_vote_output_extracts_reject():
    """合法 JSON 含 reject vote 应正确解析。"""
    orch = DiscussionOrchestrator(db_session_factory=_db_session_factory, llm_caller=_default_approve_caller())
    vote, reason = orch._parse_llm_vote_output('{"vote": "reject", "reason": "反对"}')
    assert vote == "reject"
    assert reason == "反对"


def test_parse_llm_vote_output_handles_json_code_block():
    """markdown 代码块包裹的 JSON 应正确解析。"""
    orch = DiscussionOrchestrator(db_session_factory=_db_session_factory, llm_caller=_default_approve_caller())
    output = '```json\n{"vote": "approve", "reason": "代码块通过"}\n```'
    vote, reason = orch._parse_llm_vote_output(output)
    assert vote == "approve"
    assert reason == "代码块通过"


def test_parse_llm_vote_output_defaults_to_abstain_on_garbage():
    """完全无法解析的内容应降级为 abstain。"""
    orch = DiscussionOrchestrator(db_session_factory=_db_session_factory, llm_caller=_default_approve_caller())
    vote, reason = orch._parse_llm_vote_output("完全不包含 JSON 的内容")
    assert vote == "abstain"


def test_parse_llm_vote_output_defaults_to_abstain_on_empty():
    """空输出应降级为 abstain。"""
    orch = DiscussionOrchestrator(db_session_factory=_db_session_factory, llm_caller=_default_approve_caller())
    vote, reason = orch._parse_llm_vote_output("")
    assert vote == "abstain"


# ── subagent_delegate 执行器测试（经 task_runtime 委派） ─────────────


async def test_execute_subagent_delegate_via_task_runtime(orchestrator):
    """subagent_delegate 应经 task_runtime.spawn_agent 委派并回写结果。"""
    task_id = _seed_subagent_delegate_task()

    fake_spawn = _make_fake_spawn_stream(summary="调研完成：入口在 core/agent.py")
    with patch.object(
        bridge.task_runtime, "spawn_agent", new=AsyncMock(side_effect=fake_spawn)
    ) as mock_spawn:
        result = await orchestrator.execute_approved_action(task_id)

    assert _load_task_status(task_id) == "completed"
    assert result["ok"] is True
    assert result["runtime"] == "task_runtime"
    assert "调研完成" in result["output"]

    # 内置名称 searcher -> task_runtime 原生类型 Explore
    mock_spawn.assert_awaited_once()
    call_kwargs = mock_spawn.await_args.kwargs
    assert call_kwargs["agent_type"] == "Explore"
    assert call_kwargs["force_foreground"] is True
    assert call_kwargs["background"] is False
    # 指令应注入到 prompt（含 context_snippet 为空时不追加）
    assert "调研代码库中子代理实现" in call_kwargs["prompt"]


async def test_execute_subagent_delegate_includes_context_snippet(orchestrator):
    """context_snippet 应追加到委派 prompt，供子代理可见。"""
    task_id = _seed_subagent_delegate_task(
        instruction="分析代码结构", context_snippet="目标目录 backend/core"
    )
    fake_spawn = _make_fake_spawn_stream()
    with patch.object(
        bridge.task_runtime, "spawn_agent", new=AsyncMock(side_effect=fake_spawn)
    ) as mock_spawn:
        await orchestrator.execute_approved_action(task_id)

    prompt = mock_spawn.await_args.kwargs["prompt"]
    assert "分析代码结构" in prompt
    assert "backend/core" in prompt


async def test_execute_subagent_delegate_fails_when_stream_failed(orchestrator):
    """委派事件流以 failed 终态结束时，任务应转 failed 并抛 DiscussionExecutionError。"""
    task_id = _seed_subagent_delegate_task()
    fake_spawn = _make_fake_spawn_stream(summary="执行出错", state="failed")
    with patch.object(
        bridge.task_runtime, "spawn_agent", new=AsyncMock(side_effect=fake_spawn)
    ):
        with pytest.raises(DiscussionExecutionError):
            await orchestrator.execute_approved_action(task_id)

    assert _load_task_status(task_id) == "failed"


async def test_execute_subagent_delegate_fails_when_agent_unregistered(orchestrator):
    """目标代理类型未注册（委派返回 None）时抛 DiscussionExecutionError。"""
    task_id = _seed_subagent_delegate_task(agent="no_such_agent")
    with patch.object(bridge.task_runtime, "spawn_agent", new=AsyncMock()):
        with pytest.raises(DiscussionExecutionError):
            await orchestrator.execute_approved_action(task_id)


async def test_execute_subagent_delegate_rejects_missing_fields(orchestrator):
    """payload 缺 agent/instruction 时抛 DiscussionExecutionError，不触发委派。"""
    task_id = _seed_subagent_delegate_task(instruction="")
    with pytest.raises(DiscussionExecutionError):
        await orchestrator.execute_approved_action(task_id)

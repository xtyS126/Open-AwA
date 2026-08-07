"""
Agent 短期记忆注入 system prompt 单元测试（Spec memory-quality-and-short-term-recovery Task 12）。

覆盖：
- _build_recent_short_term_memories_system_prompt 返回正确格式
- 无短期记忆时返回空串（不注入区块）
- content_preview 截断到 100 字符
- 跳过 system 角色消息
- 按时间正序排列（最早在前）
- _build_messages_with_history 中正确注入短期记忆 system message
- memory_manager 未注入时跳过（不影响主流程）
- user_id 为空时跳过
- 加载异常时静默返回空串
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.models import ConversationRecord, ShortTermMemory, init_db
from memory.manager import MemoryManager


def _build_manager():
    """构造 MemoryManager + 内存数据库。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(bind_engine=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    class _FakeVectorStore:
        provider_name = "fake"
        embedding_provider = None

        async def search(self, *args, **kwargs):
            return []

        async def upsert_memory(self, *args, **kwargs):
            pass

        def update_memory_metadata(self, *args, **kwargs):
            pass

        def delete_memory(self, *args, **kwargs):
            pass

        def count(self, **kwargs):
            return 0

        def close(self):
            pass

    MemoryManager._shared_vector_store = _FakeVectorStore()
    manager = MemoryManager(factory)
    return manager, factory


@pytest.fixture(autouse=True)
def _reset_shared_vector_store():
    """每个用例前清理类级共享向量库。"""
    saved = MemoryManager._shared_vector_store
    yield
    MemoryManager._shared_vector_store = saved


def _insert_conversation_record(factory, *, session_id: str, user_id: str):
    with factory() as db:
        record = ConversationRecord(
            session_id=session_id,
            user_id=user_id,
            node_type="user_message",
            user_message="测试消息",
            timestamp=datetime.now(timezone.utc),
            status="success",
        )
        db.add(record)
        db.commit()
        return record.id


def _insert_short_term_memory(
    factory,
    *,
    session_id: str,
    role: str,
    content: str,
    timestamp=None,
    workspace_id: str = "default",
):
    with factory() as db:
        memory = ShortTermMemory(
            session_id=session_id,
            role=role,
            content=content,
            timestamp=timestamp or datetime.now(timezone.utc),
            workspace_id=workspace_id,
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)
        return memory.id


class _StubExecutor:
    """
    最小化的 ExecutionLayer 替身，仅暴露 _build_recent_short_term_memories_system_prompt
    与 _build_messages_with_history（用于验证短期记忆注入是否正确）。

    _build_recent_short_term_memories_system_prompt 直接复用 executor.py 中的模块级纯函数
    build_recent_short_term_memories_prompt，避免复制粘贴生产代码（brooks-lint T4 Mock Abuse）。
    """

    def __init__(self, memory_manager=None):
        self.memory_manager = memory_manager

    def _build_agent_capability_system_prompt(self, context):
        return ""

    def _build_relevant_memories_system_prompt(self, context):
        return ""

    def _build_auto_execution_system_prompt(self, auto_execution_results):
        return ""

    def _build_recent_short_term_memories_system_prompt(self, context):
        # 直接复用生产代码的模块级纯函数，避免 stub 漂移
        from core.executor import build_recent_short_term_memories_prompt

        return build_recent_short_term_memories_prompt(
            getattr(self, "memory_manager", None),
            context,
        )

    def _build_messages_with_history(self, prompt: str, context):
        messages = []
        system_prompt = self._build_agent_capability_system_prompt(context)
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        memories_prompt = self._build_relevant_memories_system_prompt(context)
        if memories_prompt:
            messages.append({"role": "system", "content": memories_prompt})

        # Spec memory-quality-and-short-term-recovery Task 12：
        # 注入用户最近 N 条短期记忆
        short_term_prompt = self._build_recent_short_term_memories_system_prompt(context)
        if short_term_prompt:
            messages.append({"role": "system", "content": short_term_prompt})

        messages.append({"role": "user", "content": prompt})
        return messages


# ---------------------------------------------------------------------------
# SubTask 12.1 & 12.2：基础注入格式
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_injects_short_term_memories_in_correct_format():
    """
    场景：有短期记忆时，注入 [近期对话记忆] 区块，每条 [{session_short}] {role}: {content_preview}。

    Given 用户 user-1 在 s1 中有 2 条短期记忆（user + assistant）
    When 调用 _build_recent_short_term_memories_system_prompt
    Then 返回格式为 [近期对话记忆] + 两行 [{session_short}] role: content
    """
    manager, factory = _build_manager()
    _insert_conversation_record(factory, session_id="session-1", user_id="user-1")
    base_time = datetime.now(timezone.utc)
    _insert_short_term_memory(
        factory,
        session_id="session-1",
        role="user",
        content="帮我写个 Python 函数",
        timestamp=base_time,
    )
    _insert_short_term_memory(
        factory,
        session_id="session-1",
        role="assistant",
        content="好的，我来写一个示例",
        timestamp=base_time + timedelta(seconds=10),
    )

    executor = _StubExecutor(memory_manager=manager)
    prompt = executor._build_recent_short_term_memories_system_prompt(
        context={"user_id": "user-1", "workspace_id": "default"}
    )

    assert prompt.startswith("[近期对话记忆]")
    # 时间正序：user 在前，assistant 在后
    # session_id "session-1" 共 9 字符，截断到前 8 字符为 "session-"
    lines = prompt.split("\n")
    assert len(lines) == 3  # 标题 + 2 条记忆
    assert "[session-] user: 帮我写个 Python 函数" in lines[1]
    assert "[session-] assistant: 好的，我来写一个示例" in lines[2]


# ---------------------------------------------------------------------------
# SubTask 12.3：无短期记忆时不注入区块
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_empty_string_when_no_short_term_memories():
    """
    场景：用户没有任何短期记忆时，返回空串。

    Given 用户 user-new 没有任何短期记忆
    When 调用 _build_recent_short_term_memories_system_prompt
    Then 返回空串（不注入 [近期对话记忆] 区块）
    """
    manager, _ = _build_manager()
    executor = _StubExecutor(memory_manager=manager)

    prompt = executor._build_recent_short_term_memories_system_prompt(
        context={"user_id": "user-new"}
    )

    assert prompt == ""


@pytest.mark.asyncio
async def test_returns_empty_string_when_memory_manager_not_injected():
    """
    场景：memory_manager 未注入时（如测试或离线场景），返回空串。

    Given _StubExecutor 未传入 memory_manager
    When 调用 _build_recent_short_term_memories_system_prompt
    Then 返回空串（不抛异常）
    """
    executor = _StubExecutor(memory_manager=None)

    prompt = executor._build_recent_short_term_memories_system_prompt(
        context={"user_id": "user-1"}
    )

    assert prompt == ""


@pytest.mark.asyncio
async def test_returns_empty_string_when_user_id_missing():
    """
    场景：context 中缺少 user_id 时，返回空串。

    Given context = {}（无 user_id）
    When 调用 _build_recent_short_term_memories_system_prompt
    Then 返回空串
    """
    manager, _ = _build_manager()
    executor = _StubExecutor(memory_manager=manager)

    prompt = executor._build_recent_short_term_memories_system_prompt(context={})

    assert prompt == ""


# ---------------------------------------------------------------------------
# SubTask 12.2：content_preview 截断到 100 字符
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_content_preview_truncated_to_100_chars():
    """
    场景：长内容被截断到 100 字符 + "..." 后缀。

    Given 一条 content 长度为 200 字符的短期记忆
    When 调用 _build_recent_short_term_memories_system_prompt
    Then content_preview 为前 100 字符 + "..."
    """
    manager, factory = _build_manager()
    _insert_conversation_record(factory, session_id="s1", user_id="user-1")
    long_content = "X" * 200
    _insert_short_term_memory(
        factory, session_id="s1", role="user", content=long_content
    )

    executor = _StubExecutor(memory_manager=manager)
    prompt = executor._build_recent_short_term_memories_system_prompt(
        context={"user_id": "user-1"}
    )

    # 找到包含截断内容的行
    lines = prompt.split("\n")
    content_line = next(line for line in lines if "user:" in line)
    # 应包含 100 个 X + "..."
    assert "X" * 100 + "..." in content_line
    # 不应包含完整的 200 个 X
    assert "X" * 200 not in content_line


@pytest.mark.asyncio
async def test_short_content_not_truncated():
    """
    场景：短内容（<= 100 字符）不被截断。

    Given 一条 content 长度为 50 字符的短期记忆
    When 调用 _build_recent_short_term_memories_system_prompt
    Then content_preview 为完整 50 字符，无 "..." 后缀
    """
    manager, factory = _build_manager()
    _insert_conversation_record(factory, session_id="s1", user_id="user-1")
    short_content = "短消息，无需截断"
    _insert_short_term_memory(
        factory, session_id="s1", role="user", content=short_content
    )

    executor = _StubExecutor(memory_manager=manager)
    prompt = executor._build_recent_short_term_memories_system_prompt(
        context={"user_id": "user-1"}
    )

    assert short_content in prompt
    assert "..." not in prompt  # 不应出现截断后缀


# ---------------------------------------------------------------------------
# SubTask 12.2：跳过 system 角色消息
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skips_system_role_messages():
    """
    场景：跳过 system 角色消息，只注入 user/assistant。

    Given 1 条 system + 1 条 user + 1 条 assistant 短期记忆
    When 调用 _build_recent_short_term_memories_system_prompt
    Then 只返回 user 与 assistant 行，不含 system 行
    """
    manager, factory = _build_manager()
    _insert_conversation_record(factory, session_id="s1", user_id="user-1")
    base_time = datetime.now(timezone.utc)
    _insert_short_term_memory(
        factory, session_id="s1", role="system", content="系统消息",
        timestamp=base_time,
    )
    _insert_short_term_memory(
        factory, session_id="s1", role="user", content="用户消息",
        timestamp=base_time + timedelta(seconds=1),
    )
    _insert_short_term_memory(
        factory, session_id="s1", role="assistant", content="助手回复",
        timestamp=base_time + timedelta(seconds=2),
    )

    executor = _StubExecutor(memory_manager=manager)
    prompt = executor._build_recent_short_term_memories_system_prompt(
        context={"user_id": "user-1"}
    )

    assert "系统消息" not in prompt
    assert "用户消息" in prompt
    assert "助手回复" in prompt


# ---------------------------------------------------------------------------
# SubTask 12.2：按时间正序排列（最早在前）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memories_ordered_chronologically_ascending():
    """
    场景：短期记忆按时间正序排列（最早在前）。

    Given 3 条短期记忆（t1 < t2 < t3）
    When 调用 _build_recent_short_term_memories_system_prompt
    Then 返回顺序为 t1, t2, t3（最早在前）
    """
    manager, factory = _build_manager()
    _insert_conversation_record(factory, session_id="s1", user_id="user-1")
    base_time = datetime.now(timezone.utc)
    # 故意乱序插入，验证返回时按 timestamp 排序
    _insert_short_term_memory(
        factory, session_id="s1", role="user", content="第三条（最新）",
        timestamp=base_time + timedelta(seconds=20),
    )
    _insert_short_term_memory(
        factory, session_id="s1", role="user", content="第一条（最早）",
        timestamp=base_time,
    )
    _insert_short_term_memory(
        factory, session_id="s1", role="user", content="第二条（中间）",
        timestamp=base_time + timedelta(seconds=10),
    )

    executor = _StubExecutor(memory_manager=manager)
    prompt = executor._build_recent_short_term_memories_system_prompt(
        context={"user_id": "user-1"}
    )

    lines = prompt.split("\n")
    # 跳过标题行，从第二行开始检查顺序
    memory_lines = lines[1:]
    assert "第一条（最早）" in memory_lines[0]
    assert "第二条（中间）" in memory_lines[1]
    assert "第三条（最新）" in memory_lines[2]


# ---------------------------------------------------------------------------
# SubTask 12.4：_build_messages_with_history 中正确注入
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_messages_with_history_includes_short_term_system_message():
    """
    场景：_build_messages_with_history 正确注入短期记忆 system message。

    Given 用户 user-1 有 1 条短期记忆
    When 调用 _build_messages_with_history
    Then messages 列表包含 role=system, content=[近期对话记忆] 的消息
    """
    manager, factory = _build_manager()
    _insert_conversation_record(factory, session_id="s1", user_id="user-1")
    _insert_short_term_memory(
        factory, session_id="s1", role="user", content="测试注入"
    )

    executor = _StubExecutor(memory_manager=manager)
    messages = executor._build_messages_with_history(
        prompt="当前用户输入",
        context={"user_id": "user-1"},
    )

    # 应包含一个 system message with [近期对话记忆]
    short_term_msgs = [
        m for m in messages
        if m["role"] == "system" and "[近期对话记忆]" in m["content"]
    ]
    assert len(short_term_msgs) == 1
    assert "测试注入" in short_term_msgs[0]["content"]

    # 最后一条消息应是当前用户输入
    assert messages[-1] == {"role": "user", "content": "当前用户输入"}


@pytest.mark.asyncio
async def test_build_messages_with_history_omits_short_term_when_empty():
    """
    场景：无短期记忆时，_build_messages_with_history 不注入 system message。

    Given 用户 user-new 没有短期记忆
    When 调用 _build_messages_with_history
    Then messages 列表中不含 [近期对话记忆] system message
    """
    manager, _ = _build_manager()
    executor = _StubExecutor(memory_manager=manager)

    messages = executor._build_messages_with_history(
        prompt="输入", context={"user_id": "user-new"}
    )

    short_term_msgs = [
        m for m in messages
        if m["role"] == "system" and "[近期对话记忆]" in m["content"]
    ]
    assert len(short_term_msgs) == 0


# ---------------------------------------------------------------------------
# 异常路径
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_raises_when_manager_raises_exception():
    """
    场景：memory_manager._get_recent_short_term_memories_sync 抛异常时，异常自然传播。

    Given memory_manager 是个 mock，_get_recent_short_term_memories_sync 抛 RuntimeError
    When 调用 _build_recent_short_term_memories_system_prompt
    Then 异常向调用方传播，禁止静默降级为空串
    """

    class _BrokenManager:
        def _get_recent_short_term_memories_sync(self, *args, **kwargs):
            raise RuntimeError("DB connection failed")

    executor = _StubExecutor(memory_manager=_BrokenManager())

    with pytest.raises(RuntimeError, match="DB connection failed"):
        executor._build_recent_short_term_memories_system_prompt(
            context={"user_id": "user-1"}
        )


# ---------------------------------------------------------------------------
# session_id 短哈希格式
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_id_shortened_to_8_chars():
    """
    场景：session_id 在注入时被截断到前 8 字符。

    Given 一条 session_id="very-long-session-id-1234567890" 的短期记忆
    When 调用 _build_recent_short_term_memories_system_prompt
    Then 注入格式为 [very-long] role: content（前 8 字符）
    """
    manager, factory = _build_manager()
    long_session_id = "very-long-session-id-1234567890"
    _insert_conversation_record(factory, session_id=long_session_id, user_id="user-1")
    _insert_short_term_memory(
        factory, session_id=long_session_id, role="user", content="测试 session_id 截断"
    )

    executor = _StubExecutor(memory_manager=manager)
    prompt = executor._build_recent_short_term_memories_system_prompt(
        context={"user_id": "user-1"}
    )

    # session_id "very-long-session-id-1234567890" 截断到前 8 字符为 "very-lon"
    assert "[very-lon]" in prompt
    # 不应包含完整的 session_id
    assert f"[{long_session_id}]" not in prompt

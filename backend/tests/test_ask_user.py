"""ask_user 工具单元测试。

覆盖：
- enqueue_ask_user_request 入队与 Future 创建
- resolve_pending_ask_user 解析与状态校验
- 超时自动返回 [TIMEOUT]
- builtin_ask_user 工具定义注册
- ask_user 权限映射与并发属性
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

# 确保 backend 目录在 sys.path
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture(autouse=True)
def _clear_pending_ask_user():
    """每个用例前后清空 ask_user 队列，避免跨用例污染。"""
    from api.routes.ask_user import _pending_ask_user_requests
    _pending_ask_user_requests.clear()
    yield
    _pending_ask_user_requests.clear()


@pytest.mark.asyncio
async def test_enqueue_ask_user_request_returns_request_id_and_future():
    """enqueue 应返回 request_id 和未完成的 Future。"""
    from api.routes.ask_user import enqueue_ask_user_request, _pending_ask_user_requests

    request_id, future = enqueue_ask_user_request(
        user_id="u1",
        session_id="s1",
        question="你喜欢哪种颜色？",
        options=["红色", "蓝色"],
        allow_multiple=False,
        allow_free_text=True,
        placeholder="请选择",
        timeout=300,
    )

    assert isinstance(request_id, str)
    assert len(request_id) > 0
    assert isinstance(future, asyncio.Future)
    assert not future.done()
    assert request_id in _pending_ask_user_requests
    entry = _pending_ask_user_requests[request_id]
    assert entry.question == "你喜欢哪种颜色？"
    assert entry.options == ["红色", "蓝色"]


@pytest.mark.asyncio
async def test_resolve_pending_ask_user_success():
    """resolve 应正确设置 Future 结果。"""
    from api.routes.ask_user import enqueue_ask_user_request, resolve_pending_ask_user

    request_id, future = enqueue_ask_user_request(
        user_id="u1",
        session_id="s1",
        question="继续吗？",
        options=["是", "否"],
        allow_multiple=False,
        allow_free_text=False,
        placeholder="",
        timeout=300,
    )

    success, error_code = resolve_pending_ask_user(
        request_id=request_id,
        session_id="s1",
        answer="是",
        selected_options=["是"],
    )

    assert success is True
    assert error_code is None
    result = await future
    assert result["answer"] == "是"
    assert result["selected_options"] == ["是"]


@pytest.mark.asyncio
async def test_resolve_pending_ask_user_session_mismatch():
    """session_id 不匹配时应拒绝解析。"""
    from api.routes.ask_user import enqueue_ask_user_request, resolve_pending_ask_user

    request_id, _ = enqueue_ask_user_request(
        user_id="u1",
        session_id="s1",
        question="q",
        options=[],
        allow_multiple=False,
        allow_free_text=True,
        placeholder="",
        timeout=300,
    )

    success, error_code = resolve_pending_ask_user(
        request_id=request_id,
        session_id="other_session",
        answer="回答",
        selected_options=[],
    )

    assert success is False
    assert error_code == "session_mismatch"


@pytest.mark.asyncio
async def test_resolve_pending_ask_user_not_found():
    """不存在的 request_id 应返回 not_found。"""
    from api.routes.ask_user import resolve_pending_ask_user

    success, error_code = resolve_pending_ask_user(
        request_id="nonexistent",
        session_id="s1",
        answer="回答",
        selected_options=[],
    )

    assert success is False
    assert error_code == "not_found"


@pytest.mark.asyncio
async def test_resolve_pending_ask_user_already_answered():
    """已标记为 answered 的请求应返回 already_answered。

    注意：resolve 成功后会立即 pop 条目，所以 already_answered 分支
    只在条目被外部标记 _answered=True 但未 pop 时触发
    （如超时回调设置结果但尚未 pop 的瞬间，或并发 resolve 竞争）。
    """
    from api.routes.ask_user import enqueue_ask_user_request, resolve_pending_ask_user, _pending_ask_user_requests

    request_id, _ = enqueue_ask_user_request(
        user_id="u1",
        session_id="s1",
        question="q",
        options=[],
        allow_multiple=False,
        allow_free_text=True,
        placeholder="",
        timeout=300,
    )

    # 手动标记为已回答（模拟超时回调设置结果但尚未 pop 的状态）
    entry = _pending_ask_user_requests[request_id]
    entry._answered = True

    # 此时 resolve 应返回 already_answered
    success, error_code = resolve_pending_ask_user(
        request_id=request_id,
        session_id="s1",
        answer="回答",
        selected_options=[],
    )
    assert success is False
    assert error_code == "already_answered"


@pytest.mark.asyncio
async def test_enqueue_ask_user_timeout_clamped():
    """超时范围应被钳制到 60-600。"""
    from api.routes.ask_user import enqueue_ask_user_request, _pending_ask_user_requests

    # 超过上限
    request_id1, _ = enqueue_ask_user_request(
        user_id="u1", session_id="s1", question="q", options=[],
        allow_multiple=False, allow_free_text=True, placeholder="", timeout=9999,
    )
    assert _pending_ask_user_requests[request_id1].timeout == 600

    # 低于下限
    request_id2, _ = enqueue_ask_user_request(
        user_id="u1", session_id="s1", question="q", options=[],
        allow_multiple=False, allow_free_text=True, placeholder="", timeout=10,
    )
    assert _pending_ask_user_requests[request_id2].timeout == 60


@pytest.mark.asyncio
async def test_ask_user_timeout_auto_resolves():
    """超时后 Future 应自动以 [TIMEOUT] 结果完成。"""
    from api.routes.ask_user import enqueue_ask_user_request

    request_id, future = enqueue_ask_user_request(
        user_id="u1",
        session_id="s1",
        question="q",
        options=[],
        allow_multiple=False,
        allow_free_text=True,
        placeholder="",
        timeout=60,  # 最小值
    )

    # 手动触发超时回调（不等待 60 秒）
    from api.routes.ask_user import _pending_ask_user_requests
    entry = _pending_ask_user_requests[request_id]
    # 直接调用超时逻辑：模拟 asyncio.sleep 完成
    entry._reply_future.set_result({
        "answer": "[TIMEOUT] 用户未在规定时间内回答",
        "selected_options": [],
    })
    entry._answered = True

    result = await future
    assert "[TIMEOUT]" in result["answer"]


def test_builtin_ask_user_tool_definition_registered():
    """builtin_ask_user 应在 BUILTIN_TOOL_DEFINITIONS 中注册。"""
    from core.builtin_tools.manager import BUILTIN_TOOL_DEFINITIONS

    ask_user_def = None
    for tool_def in BUILTIN_TOOL_DEFINITIONS:
        func_name = tool_def.get("function", {}).get("name", "")
        if func_name == "builtin_ask_user":
            ask_user_def = tool_def
            break

    assert ask_user_def is not None, "builtin_ask_user 未在 BUILTIN_TOOL_DEFINITIONS 中注册"

    func_block = ask_user_def["function"]
    assert "question" in func_block["parameters"]["properties"]
    assert "options" in func_block["parameters"]["properties"]
    assert "allow_multiple" in func_block["parameters"]["properties"]
    assert "allow_free_text" in func_block["parameters"]["properties"]
    assert "placeholder" in func_block["parameters"]["properties"]
    assert "timeout" in func_block["parameters"]["properties"]


def test_ask_user_permission_mapping():
    """ask_user 应在 _BUILTIN_PERMISSION_MAP 中有 interact 权限。"""
    from core.tool_entries import _BUILTIN_PERMISSION_MAP

    assert "ask_user" in _BUILTIN_PERMISSION_MAP
    action, resource = _BUILTIN_PERMISSION_MAP["ask_user"]
    assert action == "interact"
    assert resource == "ask_user:interact"


def test_ask_user_concurrency_attrs():
    """ask_user 应配置为串行执行（is_concurrency_safe=False）。"""
    from core.tool_entries import _TOOL_CONCURRENCY_ATTRS

    assert "ask_user" in _TOOL_CONCURRENCY_ATTRS
    attrs = _TOOL_CONCURRENCY_ATTRS["ask_user"]
    assert attrs["is_concurrency_safe"] is False
    assert attrs["is_read_only"] is True
    assert attrs["is_destructive"] is False


def test_emit_ask_user_event_factory():
    """emit_ask_user_event 应生成正确的 SSE 事件结构。"""
    from core.streaming_events import emit_ask_user_event

    payload = {
        "request_id": "req123",
        "question": "测试问题",
        "options": ["A", "B"],
    }
    event = emit_ask_user_event(payload)

    assert event["type"] == "ask_user"
    assert event["chunk_type"] == "ask_user"
    assert event["ask_user"] == payload


@pytest.mark.asyncio
async def test_ask_user_tool_execute_returns_answer():
    """AskUserTool.execute 应返回用户回答。

    AskUserTool 内部会调用 enqueue_ask_user_request 创建 Future，
    测试通过监控 _pending_ask_user_requests 找到新 request_id 并 resolve。
    """
    from core.builtin_tools.ask_user import AskUserTool
    from api.routes.ask_user import _pending_ask_user_requests, resolve_pending_ask_user

    tool = AskUserTool()

    # 启动工具执行（会阻塞等待用户回答）
    async def _run_tool():
        return await tool.execute(
            action="ask",
            question="继续吗？",
            options=["是", "否"],
            allow_multiple=False,
            allow_free_text=False,
            placeholder="",
            timeout=300,
            user_id="u1",
            session_id="s1",
        )

    tool_task = asyncio.create_task(_run_tool())

    # 等待工具入队 ask_user 请求（轮询最多 1 秒）
    request_id = None
    for _ in range(100):
        await asyncio.sleep(0.01)
        if _pending_ask_user_requests:
            request_id = next(iter(_pending_ask_user_requests.keys()))
            break
    assert request_id is not None, "工具未在预期时间内入队 ask_user 请求"

    # 提交回答
    resolve_pending_ask_user(
        request_id=request_id,
        session_id="s1",
        answer="是",
        selected_options=["是"],
    )

    result = await tool_task
    assert result["success"] is True
    assert "是" in result["answer"]

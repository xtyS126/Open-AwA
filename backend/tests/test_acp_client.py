# -*- coding: utf-8 -*-
"""
ACP client 模块单元测试。

覆盖 ACPHostedClient 的事件分发、增量合并、权限挂起/恢复、finish_prompt 等行为。
测试不依赖外部 acp SDK（_ACP_AVAILABLE=False 场景），直接调用方法验证状态变化
与 emit 的 payload。
"""

from __future__ import annotations

import asyncio
from typing import Any, List, Tuple

import pytest

from acp_host.client import ACPHostedClient, _safe_isinstance
from acp_host.core import ACPAgentConfig


def _make_agent_config(**overrides: Any) -> ACPAgentConfig:
    """构造测试用 ACPAgentConfig。

    Args:
        **overrides: 覆盖默认字段的参数。

    Returns:
        默认填充 agent_id/name/command 的 ACPAgentConfig 实例。
    """
    base: dict[str, Any] = {
        "agent_id": "test-agent",
        "name": "Test Agent",
        "command": "echo",
    }
    base.update(overrides)
    return ACPAgentConfig(**base)


def _make_client(cwd: str = ".") -> ACPHostedClient:
    """构造测试用 ACPHostedClient。"""
    return ACPHostedClient(
        agent_name="test",
        agent_config=_make_agent_config(),
        cwd=cwd,
    )


async def _collect_messages(client: ACPHostedClient) -> List[Tuple[dict[str, Any], bool]]:
    """为 client 设置捕获所有 emit 事件的 on_message 回调，返回事件列表。

    Returns:
        (payload, is_last) 元组列表。
    """
    captured: List[Tuple[dict[str, Any], bool]] = []

    async def on_message(payload: dict[str, Any], is_last: bool) -> None:
        captured.append((payload, is_last))

    client.start_prompt(on_message)
    return captured


class TestSafeIsinstance:
    """_safe_isinstance 辅助函数测试。"""

    def test_none_class_returns_false(self) -> None:
        """cls 为 None 时永远返回 False。"""
        assert _safe_isinstance("any", None) is False
        assert _safe_isinstance(None, None) is False

    def test_real_class_uses_isinstance(self) -> None:
        """cls 为真实类型时走原生 isinstance。"""
        assert _safe_isinstance("x", str) is True
        assert _safe_isinstance(123, str) is False


class TestInstantiation:
    """ACPHostedClient 实例化测试。"""

    def test_can_instantiate_without_acp_sdk(self) -> None:
        """无 acp SDK 时 ACPHostedClient 仍可正常实例化。"""
        client = _make_client()
        assert client.agent_name == "test"
        assert client.tool_parse_mode == "update_detail"
        assert client._on_message is None
        assert client._assistant_text == ""
        assert client._emitted_assistant_text == ""
        assert client._thinking_active is False
        assert client._pending_permission is None
        assert client._permission_future is None

    def test_pending_permission_property_default_none(self) -> None:
        """pending_permission 属性默认为 None。"""
        client = _make_client()
        assert client.pending_permission is None


class TestStartPrompt:
    """start_prompt 行为测试。"""

    def test_sets_callback_and_resets_state(self) -> None:
        """start_prompt 设置 on_message 并重置 _assistant_text 等累积状态。"""
        client = _make_client()
        # 预先污染状态
        client._assistant_text = "leftover"
        client._emitted_assistant_text = "leftover"
        client._thinking_active = True
        client._pending_permission = None  # type: ignore[assignment]

        async def on_message(payload: dict[str, Any], is_last: bool) -> None:
            return None

        client.start_prompt(on_message)
        assert client._on_message is on_message
        assert client._assistant_text == ""
        assert client._emitted_assistant_text == ""
        assert client._thinking_active is False
        assert client._pending_permission is None


class TestFlushAssistantText:
    """flush_assistant_text 增量合并测试。"""

    @pytest.mark.asyncio
    async def test_no_emit_when_empty(self) -> None:
        """无累积文本时 flush 不 emit。"""
        client = _make_client()
        captured = await _collect_messages(client)
        await client.flush_assistant_text()
        assert captured == []

    @pytest.mark.asyncio
    async def test_no_emit_when_already_emitted(self) -> None:
        """已 emit 过的文本再次 flush 不重复 emit。"""
        client = _make_client()
        captured = await _collect_messages(client)
        client._assistant_text = "hello"
        await client.flush_assistant_text()
        first_count = len(captured)
        await client.flush_assistant_text()  # 重复 flush
        assert len(captured) == first_count

    @pytest.mark.asyncio
    async def test_emits_delta_when_new_text(self) -> None:
        """有新文本时 flush emit 自上次以来的增量 delta。"""
        client = _make_client()
        captured = await _collect_messages(client)
        client._assistant_text = "hello world"
        await client.flush_assistant_text()
        assert len(captured) == 1
        payload, is_last = captured[0]
        assert payload == {"type": "text", "text": "hello world", "is_chunk": False}
        assert is_last is False
        assert client._emitted_assistant_text == "hello world"

    @pytest.mark.asyncio
    async def test_emits_incremental_delta(self) -> None:
        """累积文本增长时只 emit 新增部分。"""
        client = _make_client()
        captured = await _collect_messages(client)
        client._assistant_text = "abc"
        await client.flush_assistant_text()
        client._assistant_text = "abcdef"
        await client.flush_assistant_text()
        assert len(captured) == 2
        assert captured[0][0]["text"] == "abc"
        assert captured[1][0]["text"] == "def"


class TestMergeAssistantText:
    """_merge_assistant_text 四种合并场景测试。"""

    def test_identical_text_is_ignored(self) -> None:
        """text 与已累积文本完全相同时被忽略。"""
        client = _make_client()
        client._assistant_text = "hello"
        client._merge_assistant_text("hello")
        assert client._assistant_text == "hello"

    def test_empty_text_is_ignored(self) -> None:
        """空字符串被忽略。"""
        client = _make_client()
        client._assistant_text = "hello"
        client._merge_assistant_text("")
        assert client._assistant_text == "hello"

    def test_first_text_assigned_directly(self) -> None:
        """已累积为空时直接赋值。"""
        client = _make_client()
        client._merge_assistant_text("first")
        assert client._assistant_text == "first"

    def test_text_starts_with_assistant_text(self) -> None:
        """text 以已累积文本为前缀时用 text 替换。"""
        client = _make_client()
        client._assistant_text = "hello"
        client._merge_assistant_text("hello world")
        assert client._assistant_text == "hello world"

    def test_overlap_is_merged(self) -> None:
        """已累积末尾与新文本开头存在重叠时去重拼接。"""
        client = _make_client()
        client._assistant_text = "hello wor"
        client._merge_assistant_text("world")
        assert client._assistant_text == "hello world"

    def test_partial_overlap_picks_largest(self) -> None:
        """多个候选重叠时选取最大的那个。"""
        client = _make_client()
        # "abab" 末尾与 "abab" 开头有多个重叠，最大是 "abab"（但等同会触发
        # startswith 分支提前 return，故选非等价场景）
        client._assistant_text = "abcab"
        client._merge_assistant_text("abxyz")
        # 重叠 "ab" → 拼接为 "abcab" + "xyz"
        assert client._assistant_text == "abcabxyz"

    def test_no_overlap_is_concatenated(self) -> None:
        """无重叠时直接追加。"""
        client = _make_client()
        client._assistant_text = "hello"
        client._merge_assistant_text("world")
        assert client._assistant_text == "helloworld"


class TestExtractTextFromContent:
    """_extract_text_from_content 多形态提取测试。"""

    def test_none_returns_empty(self) -> None:
        """None 输入返回空串。"""
        client = _make_client()
        assert client._extract_text_from_content(None) == ""

    def test_str_object_with_text_attr(self) -> None:
        """含 text 属性（str 类型）的对象返回 text。"""
        client = _make_client()

        class FakeContent:
            def __init__(self, text: str) -> None:
                self.text = text

        assert client._extract_text_from_content(FakeContent("hi")) == "hi"

    def test_list_is_joined(self) -> None:
        """list 输入递归提取后拼接。"""
        client = _make_client()
        result = client._extract_text_from_content(
            [
                {"type": "text", "text": "a"},
                {"type": "text", "text": "b"},
            ],
        )
        assert result == "ab"

    def test_dict_with_text_type(self) -> None:
        """dict type=text 时返回 text 字段。"""
        client = _make_client()
        assert (
            client._extract_text_from_content({"type": "text", "text": "x"})
            == "x"
        )

    def test_dict_without_text_type_returns_empty(self) -> None:
        """dict 非 text 类型时返回空串。"""
        client = _make_client()
        assert (
            client._extract_text_from_content({"type": "image", "url": "u"})
            == ""
        )

    def test_object_with_name_and_uri(self) -> None:
        """对象含 name 与 uri 属性时返回 name 或 uri。"""
        client = _make_client()

        class FakeResource:
            def __init__(self, name: str, uri: str) -> None:
                self.name = name
                self.uri = uri

        assert client._extract_text_from_content(FakeResource("n", "u")) == "n"

    def test_object_with_resource_text(self) -> None:
        """对象含 resource 字段时递归提取 resource.text。"""
        client = _make_client()

        class FakeResource:
            text = "deep"

        class FakeContent:
            resource = FakeResource()

        assert client._extract_text_from_content(FakeContent()) == "deep"


class TestRequestPermission:
    """request_permission / resolve_permission 行为测试。"""

    @pytest.mark.asyncio
    async def test_hard_blocked_returns_cancelled(self) -> None:
        """命中硬阻断命令时返回 cancelled_response，不挂起 future。"""
        client = _make_client()
        captured = await _collect_messages(client)
        tool_call = {
            "title": "Shell",
            "kind": "shell",
            "rawInput": {"command": "rm -rf /"},
        }
        result = await client.request_permission(
            options=[],
            session_id="s1",
            tool_call=tool_call,
        )
        # 应该 emit 了 permission_request 事件
        assert any(
            payload.get("type") == "permission_request"
            for payload, _ in captured
        )
        # 返回 cancelled 占位 dict
        assert isinstance(result, dict)
        assert result["outcome"]["outcome"] == "cancelled"
        # 未挂起 future
        assert client._pending_permission is None
        assert client._permission_future is None

    @pytest.mark.asyncio
    async def test_non_blocked_suspends_future(self) -> None:
        """非硬阻断时挂起 future 等待 resolve_permission。"""
        client = _make_client()
        await _collect_messages(client)
        tool_call = {
            "title": "Read",
            "kind": "read",
            "rawInput": {"file_path": "test.txt"},
            "locations": [{"path": "test.txt"}],
        }
        options = [
            {"optionId": "allow_once", "title": "Allow Once"},
            {"optionId": "deny", "title": "Deny"},
        ]
        # 异步发起 request_permission，主线程随后 resolve
        task = asyncio.create_task(
            client.request_permission(
                options=options,
                session_id="s1",
                tool_call=tool_call,
            ),
        )
        # 等待 _permission_requested 被设置
        await asyncio.wait_for(client.wait_for_permission_request(), timeout=1.0)
        # 挂起状态生效
        assert client._pending_permission is not None
        assert client._permission_future is not None
        assert not client._permission_future.done()
        # resolve
        client.resolve_permission("allow_once")
        result = await asyncio.wait_for(task, timeout=1.0)
        # 返回 selected 占位 dict
        assert isinstance(result, dict)
        assert result["outcome"]["outcome"] == "selected"
        assert result["outcome"]["optionId"] == "allow_once"
        # 挂起状态已清理
        assert client._pending_permission is None
        assert client._permission_future is None

    def test_resolve_permission_raises_when_no_pending(self) -> None:
        """无挂起权限请求时 resolve_permission 抛 ValueError。"""
        client = _make_client()
        with pytest.raises(ValueError, match="No pending"):
            client.resolve_permission("any")


class TestWaitForPermissionRequest:
    """wait_for_permission_request 行为测试。"""

    @pytest.mark.asyncio
    async def test_returns_after_set(self) -> None:
        """_permission_requested.set() 后 wait 立即返回。"""
        client = _make_client()
        # 在另一协程中等待
        task = asyncio.create_task(client.wait_for_permission_request())
        # 让出控制权让 task 进入等待
        await asyncio.sleep(0)
        assert not task.done()
        client._permission_requested.set()
        await asyncio.wait_for(task, timeout=1.0)


class TestFinishPrompt:
    """finish_prompt 行为测试。"""

    @pytest.mark.asyncio
    async def test_returns_none_when_empty(self) -> None:
        """无累积文本时 finish_prompt 返回 None。"""
        client = _make_client()
        await _collect_messages(client)
        result = await client.finish_prompt()
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_dict_when_text_present(self) -> None:
        """有累积文本时 finish_prompt 返回最终 text 事件 dict。"""
        client = _make_client()
        captured = await _collect_messages(client)
        client._assistant_text = "final answer"
        result = await client.finish_prompt()
        assert result is not None
        assert result == {
            "type": "text",
            "text": "final answer",
            "is_chunk": False,
        }
        # finish_prompt 也会先 flush，触发 delta emit
        assert any(
            payload.get("text") == "final answer"
            for payload, _ in captured
        )


class TestEmitPermissionResolved:
    """emit_permission_resolved 行为测试。"""

    @pytest.mark.asyncio
    async def test_emits_status_event(self) -> None:
        """emit_permission_resolved emit permission_resolved 状态事件。"""
        client = _make_client()
        captured = await _collect_messages(client)
        await client.emit_permission_resolved()
        assert len(captured) == 1
        payload, is_last = captured[0]
        assert payload["type"] == "status"
        assert payload["status"] == "permission_resolved"
        assert is_last is True


class TestUpdateCwd:
    """update_cwd 行为测试。"""

    def test_replaces_permission_adapter(self) -> None:
        """update_cwd 用新的 cwd 重建 permission_adapter。"""
        client = _make_client(cwd=".")
        old_adapter = client._permission_adapter
        client.update_cwd("/tmp")
        new_adapter = client._permission_adapter
        assert new_adapter is not old_adapter
        assert "/tmp" in new_adapter.cwd or "tmp" in new_adapter.cwd


class TestExtMethod:
    """ext_method / ext_notification 行为测试。"""

    @pytest.mark.asyncio
    async def test_ext_method_raises_request_error(self) -> None:
        """ext_method 始终抛 RequestError（code=-32601）。"""
        from acp_host.client import RequestError

        client = _make_client()
        with pytest.raises(RequestError) as exc_info:
            await client.ext_method("custom.method", {})
        # 占位 RequestError 把 code 与 message 都存到属性
        assert getattr(exc_info.value, "code", None) == -32601 or "-32601" in str(
            exc_info.value,
        )

    @pytest.mark.asyncio
    async def test_ext_notification_raises_request_error(self) -> None:
        """ext_notification 始终抛 RequestError。"""
        from acp_host.client import RequestError

        client = _make_client()
        with pytest.raises(RequestError):
            await client.ext_notification("custom.notify", {})


class TestResumePrompt:
    """resume_prompt 行为测试。"""

    def test_sets_callback_and_clears_permission_flag(self) -> None:
        """resume_prompt 设置 on_message 并清除 _permission_requested。"""
        client = _make_client()
        client._permission_requested.set()

        async def on_message(payload: dict[str, Any], is_last: bool) -> None:
            return None

        client.resume_prompt(on_message)
        assert client._on_message is on_message
        assert not client._permission_requested.is_set()

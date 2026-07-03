# -*- coding: utf-8 -*-
"""
ACP tool_adapter 模块单元测试。

覆盖五类事件渲染（text/tool_call/status/permission_request/error）、
render_event_text 主分发函数、以及 format_* 响应构造函数的行为。
测试不依赖外部 acp SDK，全部以 dict 形式构造 mock 事件与 SuspendedPermission。
"""

from __future__ import annotations

from pathlib import Path

from acp_host.core import SuspendedPermission
from acp_host.tool_adapter import (
    _render_error_event,
    _render_permission_event,
    _render_status_event,
    _render_text_event,
    _render_tool_event,
    format_close_response,
    format_final_assistant_response,
    format_permission_suspended_response,
    render_event_text,
)


class TestRenderTextEvent:
    """_render_text_event 文本事件渲染测试。"""

    def test_text_event_with_text_returns_assistant_prefixed(self) -> None:
        """有 text 字段时返回 "[assistant]\n{text}"（SubTask 用例 1）。"""
        result = _render_text_event({"type": "text", "text": "hello"})

        assert result == "[assistant]\nhello"

    def test_text_event_with_empty_text_returns_none(self) -> None:
        """text 为空时返回 None（SubTask 用例 2）。"""
        result = _render_text_event({"type": "text", "text": ""})

        assert result is None


class TestRenderToolEvent:
    """_render_tool_event 工具调用事件渲染测试。"""

    def test_tool_event_with_kind_and_detail_returns_formatted(self) -> None:
        """kind + detail 都有时返回 "[tool_call] {kind} ({detail})"（SubTask 用例 3）。"""
        result = _render_tool_event({"kind": "shell", "detail": "ls -la"})

        assert result == "[tool_call] shell (ls -la)"

    def test_tool_event_missing_kind_returns_none(self) -> None:
        """缺 kind 时返回 None（SubTask 用例 4 变体）。"""
        result = _render_tool_event({"detail": "ls -la"})

        assert result is None

    def test_tool_event_missing_detail_returns_none(self) -> None:
        """缺 detail 时返回 None（SubTask 用例 4 变体）。"""
        result = _render_tool_event({"kind": "shell"})

        assert result is None


class TestRenderStatusEvent:
    """_render_status_event 状态事件渲染测试。"""

    def test_status_run_finished_returns_none(self) -> None:
        """status="run_finished" 返回 None（SubTask 用例 5）。"""
        result = _render_status_event({"status": "run_finished"})

        assert result is None

    def test_status_agent_thinking_with_summary_returns_summary(self) -> None:
        """status="agent_thinking" + summary 返回 summary（SubTask 用例 6）。"""
        result = _render_status_event(
            {"status": "agent_thinking", "summary": "planning next step"},
        )

        assert result == "planning next step"

    def test_status_unknown_with_summary_returns_status_prefixed(self) -> None:
        """status="unknown" + summary 返回 "[status] unknown\n{summary}"（SubTask 用例 7）。"""
        result = _render_status_event(
            {"status": "unknown", "summary": "some summary"},
        )

        assert result == "[status] unknown\nsome summary"


class TestRenderPermissionEvent:
    """_render_permission_event 权限请求事件渲染测试。"""

    def test_permission_event_with_title_and_options_returns_multiline(self) -> None:
        """title + 多个 options 时返回多行字符串（SubTask 用例 8）。"""
        result = _render_permission_event(
            {
                "title": "Allow shell command",
                "options": [
                    {"optionId": "allow_once", "title": "Allow Once"},
                    {"optionId": "deny", "title": "Deny"},
                ],
            },
        )

        assert "[permission_request] Allow shell command" in result
        assert "Allow Once (allow_once)" in result
        assert "Deny (deny)" in result
        # 多行结构验证
        assert "\n" in result


class TestRenderErrorEvent:
    """_render_error_event 错误事件渲染测试。"""

    def test_error_event_with_message_returns_error_prefixed(self) -> None:
        """有 message 时返回 "[error] {message}"（SubTask 用例 9）。"""
        result = _render_error_event({"message": "boom"})

        assert result == "[error] boom"

    def test_error_event_without_message_returns_none(self) -> None:
        """无 message 时返回 None（SubTask 用例 10）。"""
        result = _render_error_event({})

        assert result is None


class TestRenderEventTextDispatch:
    """render_event_text 主分发函数测试。"""

    def test_dispatch_text_event_calls_render_text_event(self) -> None:
        """type="text" 调用 _render_text_event（SubTask 用例 11）。"""
        result = render_event_text({"type": "text", "text": "hi"})

        assert result == "[assistant]\nhi"

    def test_dispatch_tool_call_event_calls_render_tool_event(self) -> None:
        """type="tool_call" 调用 _render_tool_event（SubTask 用例 12）。"""
        result = render_event_text(
            {"type": "tool_call", "kind": "file", "detail": "readme.md"},
        )

        assert result == "[tool_call] file (readme.md)"

    def test_dispatch_status_event_calls_render_status_event(self) -> None:
        """type="status" 调用 _render_status_event（SubTask 用例 13）。"""
        result = render_event_text(
            {"type": "status", "status": "agent_thinking", "summary": "thinking"},
        )

        assert result == "thinking"

    def test_dispatch_permission_request_event_calls_render_permission_event(
        self,
    ) -> None:
        """type="permission_request" 调用 _render_permission_event（SubTask 用例 14）。"""
        result = render_event_text(
            {
                "type": "permission_request",
                "title": "Confirm",
                "options": [{"optionId": "ok", "title": "OK"}],
            },
        )

        assert "[permission_request] Confirm" in result
        assert "OK (ok)" in result

    def test_dispatch_error_event_calls_render_error_event(self) -> None:
        """type="error" 调用 _render_error_event（SubTask 用例 15）。"""
        result = render_event_text({"type": "error", "message": "fail"})

        assert result == "[error] fail"

    def test_dispatch_unknown_type_returns_none(self) -> None:
        """type="unknown_type" 返回 None（SubTask 用例 16）。"""
        result = render_event_text({"type": "unknown_type"})

        assert result is None


class TestFormatPermissionSuspendedResponse:
    """format_permission_suspended_response 响应构造测试。"""

    def test_response_does_not_contain_emoji(self) -> None:
        """输出不含 emoji，改用纯文本标记（SubTask 用例 17）。"""
        suspended = SuspendedPermission(
            payload={},
            options=[],
            agent="acp-agent",
            tool_name="shell",
            tool_kind="shell",
        )

        response = format_permission_suspended_response(
            suspended_permission=suspended,
        )

        text = response["content"][0]["text"]
        # 严禁 emoji：检查 "🔐" 不出现
        assert "🔐" not in text
        # 应包含纯文本标记替代
        assert "[Permission]" in text


class TestFormatFinalAssistantResponse:
    """format_final_assistant_response 最终响应构造测试。"""

    def test_final_event_none_returns_completed_without_text_output(self) -> None:
        """final_event=None 时 body 为 "completed without text output"（SubTask 用例 18）。"""
        response = format_final_assistant_response(
            runner_name="runner-1",
            execution_cwd=Path("/tmp"),
            final_event=None,
        )

        # content[0] 为头部块，content[1] 为 body 块
        body_block = response["content"][1]
        assert body_block["text"] == "completed without text output"
        assert response["is_last"] is True


class TestFormatCloseResponse:
    """format_close_response 关闭会话响应构造测试。"""

    def test_closed_true_mentions_closed_session(self) -> None:
        """closed=True 时含 "Closed the bound ACP session"（SubTask 用例 19）。"""
        response = format_close_response(runner_name="runner-1", closed=True)

        text = response["content"][0]["text"]
        assert "Closed the bound ACP session" in text
        assert "runner-1" in text

    def test_closed_false_mentions_no_session_found(self) -> None:
        """closed=False 时含 "No bound ACP session found"（SubTask 用例 20）。"""
        response = format_close_response(runner_name="runner-1", closed=False)

        text = response["content"][0]["text"]
        assert "No bound ACP session found" in text
        assert "runner-1" in text

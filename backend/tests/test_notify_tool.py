"""
通知推送工具 NotifyTool 单元测试。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.builtin_tools.notify import (
    CHANNEL_DESKTOP,
    CHANNEL_BRIDGE_OWNER,
    CHANNEL_AUTO,
    format_notification_text,
    normalize_channels,
    NotifyTool,
)


class TestFormatNotificationText:
    """测试通知文本格式化函数。"""

    def test_title_and_body(self):
        """测试标题和正文同时存在时以双换行分隔。"""
        result = format_notification_text("标题", "正文内容")
        assert result == "标题\n\n正文内容"

    def test_title_only(self):
        """测试只有标题时返回标题。"""
        result = format_notification_text("只有标题", "")
        assert result == "只有标题"

    def test_body_only(self):
        """测试只有正文时返回正文。"""
        result = format_notification_text("", "只有正文")
        assert result == "只有正文"

    def test_both_empty(self):
        """测试标题和正文都为空时返回空字符串。"""
        result = format_notification_text("", "")
        assert result == ""

    def test_whitespace_trimmed(self):
        """测试空白字符被去除。"""
        result = format_notification_text("  标题  ", "  正文  ")
        assert result == "标题\n\n正文"


class TestNormalizeChannels:
    """测试通道标准化函数。"""

    def test_none_returns_default(self):
        """测试 None 输入返回默认 desktop 通道。"""
        result = normalize_channels(None)
        assert result == [CHANNEL_DESKTOP]

    def test_empty_list_returns_default(self):
        """测试空列表返回默认 desktop 通道。"""
        result = normalize_channels([])
        assert result == [CHANNEL_DESKTOP]

    def test_auto_resolves_to_desktop(self):
        """测试 auto 通道被解析为 desktop。"""
        result = normalize_channels([CHANNEL_AUTO])
        assert result == [CHANNEL_DESKTOP]

    def test_invalid_filtered(self):
        """测试无效通道被过滤掉，有效通道保留。"""
        result = normalize_channels(["invalid", CHANNEL_DESKTOP])
        assert CHANNEL_DESKTOP in result
        assert "invalid" not in result

    def test_all_invalid_falls_back(self):
        """测试全部为无效通道时回退到 desktop。"""
        result = normalize_channels(["invalid1", "invalid2"])
        assert result == [CHANNEL_DESKTOP]

    def test_deduplication(self):
        """测试重复通道被去重。"""
        result = normalize_channels([CHANNEL_DESKTOP, CHANNEL_AUTO, CHANNEL_DESKTOP])
        assert result.count(CHANNEL_DESKTOP) == 1

    def test_whitespace_handled(self):
        """测试带空格的通道名也能正确处理。"""
        result = normalize_channels(["  desktop  "])
        assert result == [CHANNEL_DESKTOP]

    def test_bridge_owner_preserved(self):
        """测试 bridge_owner 通道被正确保留。"""
        result = normalize_channels([CHANNEL_BRIDGE_OWNER])
        assert result == [CHANNEL_BRIDGE_OWNER]

    def test_multiple_valid_channels(self):
        """测试多个有效通道被正确返回。"""
        result = normalize_channels([CHANNEL_DESKTOP, CHANNEL_BRIDGE_OWNER])
        assert set(result) == {CHANNEL_DESKTOP, CHANNEL_BRIDGE_OWNER}

    def test_auto_and_bridge_together(self):
        """测试 auto 和 bridge_owner 同时存在时，desktop 只出现一次。"""
        result = normalize_channels([CHANNEL_AUTO, CHANNEL_BRIDGE_OWNER])
        assert CHANNEL_DESKTOP in result
        assert CHANNEL_BRIDGE_OWNER in result
        assert len(result) == 2


@pytest.mark.asyncio
class TestNotifyTool:
    """测试 NotifyTool 核心功能。"""

    @pytest.fixture
    def tool(self):
        """创建不带回调的基础 NotifyTool 实例。"""
        return NotifyTool()

    async def test_initialize(self, tool):
        """测试初始化始终返回 True。"""
        result = await tool.initialize()
        assert result is True

    async def test_get_tools(self, tool):
        """测试 get_tools 返回操作列表。"""
        tools = tool.get_tools()
        assert isinstance(tools, list)
        assert "notify" in tools

    async def test_execute_unknown_action(self, tool):
        """测试未知操作返回错误。"""
        result = await tool.execute(action="unknown_action")
        assert result["success"] is False
        assert "未知通知操作" in result.get("error", "")

    async def test_send_desktop_with_callback(self):
        """测试通过 desktop 通道发送通知（有回调）。"""
        captured = []

        async def fake_emit(title, body, context):
            captured.append({"title": title, "body": body, "context": context})

        tool = NotifyTool(emit_desktop=fake_emit)
        result = await tool.execute(
            action="notify",
            title="测试标题",
            body="测试正文",
            channels=[CHANNEL_DESKTOP],
        )

        assert result["success"] is True
        assert len(captured) == 1
        assert captured[0]["title"] == "测试标题"
        assert captured[0]["body"] == "测试正文"

    async def test_send_desktop_without_callback(self, tool):
        """测试 desktop 通道无回调时仍能成功（仅记录日志）。"""
        result = await tool.execute(
            action="notify",
            title="无回调测试",
            body="正文",
            channels=[CHANNEL_DESKTOP],
        )

        assert result["success"] is True
        deliveries = result.get("deliveries", [])
        assert len(deliveries) == 1
        assert deliveries[0]["status"] == "sent"
        assert deliveries[0]["channel"] == CHANNEL_DESKTOP

    async def test_send_bridge_owner_with_callback(self):
        """测试通过 bridge_owner 通道发送通知（有回调）。"""
        captured = []

        async def fake_bridge(text, context):
            captured.append({"text": text, "context": context})
            return True

        tool = NotifyTool(send_bridge_owner=fake_bridge)
        result = await tool.execute(
            action="notify",
            title="提醒",
            body="您的任务已完成",
            channels=[CHANNEL_BRIDGE_OWNER],
        )

        assert result["success"] is True
        assert len(captured) == 1
        assert "提醒" in captured[0]["text"]
        assert "您的任务已完成" in captured[0]["text"]

    async def test_bridge_owner_callback_returns_false(self):
        """测试 bridge_owner 回调返回 False 时视为失败。"""

        async def fake_bridge(text, context):
            return False

        tool = NotifyTool(send_bridge_owner=fake_bridge)
        result = await tool.execute(
            action="notify",
            title="失败测试",
            body="正文",
            channels=[CHANNEL_BRIDGE_OWNER],
        )

        assert result["success"] is False
        deliveries = result.get("deliveries", [])
        assert deliveries[0]["status"] == "failed"

    async def test_bridge_owner_wrong_audience(self, tool):
        """测试 bridge_owner 通道仅接受 audience=owner。"""
        result = await tool.execute(
            action="notify",
            title="测试",
            body="内容",
            channels=[CHANNEL_BRIDGE_OWNER],
            audience="other",
        )

        assert result["success"] is False
        deliveries = result.get("deliveries", [])
        assert deliveries[0]["status"] == "failed"
        assert "audience" in deliveries[0].get("error", "").lower()

    async def test_bridge_owner_empty_text(self, tool):
        """测试 bridge_owner 通道在标题和正文为空时失败。"""
        result = await tool.execute(
            action="notify",
            title="",
            body="",
            channels=[CHANNEL_BRIDGE_OWNER],
        )

        assert result["success"] is False
        assert "不能同时为空" in result.get("error", "")

    async def test_missing_title_and_body(self, tool):
        """测试标题和正文都缺失时返回错误。"""
        result = await tool.execute(
            action="notify",
            title="",
            body="",
        )

        assert result["success"] is False
        assert "不能同时为空" in result.get("error", "")

    async def test_body_only_notification(self):
        """测试只提供正文的通知也能发送成功。"""
        captured = []

        async def fake_emit(title, body, context):
            captured.append({"title": title, "body": body})

        tool = NotifyTool(emit_desktop=fake_emit)
        result = await tool.execute(
            action="notify",
            title="",
            body="只有正文内容",
            channels=[CHANNEL_DESKTOP],
        )

        assert result["success"] is True
        assert len(captured) == 1
        assert captured[0]["body"] == "只有正文内容"

    async def test_default_channels_is_desktop(self, tool):
        """测试不指定 channels 时默认使用 desktop。"""
        result = await tool.execute(
            action="notify",
            title="默认通道",
            body="测试",
        )

        assert result["success"] is True
        deliveries = result.get("deliveries", [])
        assert len(deliveries) >= 1
        assert any(d["channel"] == CHANNEL_DESKTOP for d in deliveries)

    async def test_callback_exception_is_caught(self):
        """测试回调抛出异常时被正确捕获并返回失败状态。"""

        async def failing_emit(title, body, context):
            raise RuntimeError("回调故障")

        tool = NotifyTool(emit_desktop=failing_emit)
        result = await tool.execute(
            action="notify",
            title="异常测试",
            body="正文",
            channels=[CHANNEL_DESKTOP],
        )

        assert result["success"] is False
        deliveries = result.get("deliveries", [])
        assert deliveries[0]["status"] == "failed"
        assert "回调故障" in deliveries[0].get("error", "")

    async def test_agent_id_in_context(self):
        """测试 agent_id 被正确传递到 context 中。"""
        captured = []

        async def fake_emit(title, body, context):
            captured.append(context)

        tool = NotifyTool(emit_desktop=fake_emit)
        await tool.execute(
            action="notify",
            title="上下文测试",
            body="正文",
            channels=[CHANNEL_DESKTOP],
            agent_id="agent-123",
        )

        assert len(captured) == 1
        assert captured[0].get("agentId") == "agent-123"

    async def test_string_channel_input(self, tool):
        """测试 channels 为单字符串时也能正确处理。"""
        result = await tool.execute(
            action="notify",
            title="字符串通道",
            body="测试",
            channels="desktop",
        )

        assert result["success"] is True
        deliveries = result.get("deliveries", [])
        assert deliveries[0]["channel"] == CHANNEL_DESKTOP

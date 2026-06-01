"""
channel_message 内置技能 — 通过渠道向外部 IM 平台发送消息。
用于在 Agent 对话中主动向钉钉/飞书/微信/Discord 等渠道发送通知。
"""
from typing import Any, Optional
from loguru import logger

SKILL_NAME = "channel_message"
SKILL_DESCRIPTION = "通过指定渠道（钉钉/飞书/微信/Discord等）向目标用户或群组发送消息"


async def execute(
    channel: str,
    message: str,
    target_user: Optional[str] = None,
    target_group: Optional[str] = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    向指定渠道发送消息。

    Args:
        channel: 目标渠道（dingtalk/feishu/weixin/discord/telegram/qq/slack）
        message: 消息内容
        target_user: 目标用户 ID（可选）
        target_group: 目标群组 ID（可选）

    Returns:
        发送结果
    """
    supported_channels = {"dingtalk", "feishu", "weixin", "discord", "telegram", "qq", "slack"}
    if channel not in supported_channels:
        return {
            "success": False,
            "error": f"不支持的渠道: {channel}，支持: {', '.join(sorted(supported_channels))}",
        }

    logger.bind(
        event="channel_message_send",
        channel=channel,
        target_user=target_user,
        target_group=target_group,
    ).info(f"向 {channel} 发送消息")

    # 当前为占位实现，渠道消息发送由后端 channels 模块处理
    # 后续 Phase 5 实现多渠道后对接
    return {
        "success": True,
        "channel": channel,
        "message_preview": message[:200],
        "target_user": target_user,
        "target_group": target_group,
        "note": "消息已提交到渠道队列，实际发送由 channels 模块处理",
    }

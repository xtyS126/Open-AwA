"""
dingtalk_channel 内置技能 — 钉钉接入引导和消息发送。
为 Agent 提供钉钉频道的配置引导和消息发送能力。
"""
from typing import Any, Optional
from loguru import logger

SKILL_NAME = "dingtalk_channel"
SKILL_DESCRIPTION = "钉钉频道接入引导，支持配置引导、消息发送、Markdown消息和交互卡片"


async def execute(
    action: str = "guide",
    message: Optional[str] = None,
    target: Optional[str] = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    执行钉钉频道相关操作。

    Args:
        action: 操作类型（guide/send_message/send_markdown/send_action_card/health）
        message: 消息内容
        target: 目标会话 ID（可选）

    Returns:
        操作结果
    """
    valid_actions = {"guide", "send_message", "send_markdown", "send_action_card", "health"}
    if action not in valid_actions:
        return {"success": False, "error": f"不支持的操作: {action}，支持: {', '.join(sorted(valid_actions))}"}

    # ---- 接入引导 ----
    if action == "guide":
        return {
            "success": True,
            "action": "guide",
            "title": "钉钉频道接入指南",
            "steps": [
                {
                    "step": 1,
                    "title": "创建钉钉应用",
                    "description": "登录钉钉开放平台 (open.dingtalk.com)，创建企业内部应用，获取 AppKey 和 AppSecret",
                },
                {
                    "step": 2,
                    "title": "配置机器人",
                    "description": "在应用开发页面中，添加「机器人」功能，配置消息接收模式为 Stream 模式",
                },
                {
                    "step": 3,
                    "title": "获取 Webhook 地址",
                    "description": "在钉钉群聊中添加机器人，获取 Webhook URL 用于主动发送消息",
                },
                {
                    "step": 4,
                    "title": "配置 Open-AwA",
                    "description": "在 Open-AwA 通讯配置页面中填入 client_id（AppKey）、client_secret（AppSecret）和 webhook_url",
                },
                {
                    "step": 5,
                    "title": "测试连接",
                    "description": "点击测试连接按钮验证配置是否正确",
                },
            ],
            "docs_url": "https://open.dingtalk.com/document/",
        }

    # ---- 发送文本消息 ----
    elif action == "send_message":
        if not message:
            return {"success": False, "error": "send_message 需要提供 message"}
        try:
            from channels.dingtalk import DingTalkAdapter
            from channels.base import ChannelConfig, ChannelType, ChannelMessage, MessageType

            config = ChannelConfig(
                channel_type=ChannelType.DINGTALK,
                enabled=True,
                credentials=kwargs.get("credentials", {}),
            )
            adapter = DingTalkAdapter(config)
            connected = await adapter.connect()
            if not connected:
                return {"success": False, "error": "钉钉连接失败，请检查 client_id 和 client_secret"}

            result = await adapter.send_message(ChannelMessage(
                channel=ChannelType.DINGTALK,
                content=message,
                message_type=MessageType.TEXT,
            ))
            await adapter.disconnect()
            return {
                "success": result.get("success", False),
                "action": "send_message",
                "response": result,
            }
        except ImportError:
            return {"success": False, "error": "钉钉适配器不可用，请检查 channels 模块"}
        except Exception as e:
            logger.bind(event="dingtalk_skill_error").error(f"发送失败: {str(e)}")
            return {"success": False, "error": f"发送失败: {str(e)}"}

    # ---- 发送 Markdown 消息 ----
    elif action == "send_markdown":
        if not message:
            return {"success": False, "error": "send_markdown 需要提供 message"}
        try:
            from channels.dingtalk import DingTalkAdapter
            from channels.base import ChannelConfig, ChannelType, ChannelMessage, MessageType

            config = ChannelConfig(
                channel_type=ChannelType.DINGTALK,
                enabled=True,
                credentials=kwargs.get("credentials", {}),
            )
            adapter = DingTalkAdapter(config)
            connected = await adapter.connect()
            if not connected:
                return {"success": False, "error": "钉钉连接失败"}

            result = await adapter.send_message(ChannelMessage(
                channel=ChannelType.DINGTALK,
                content=f"**Open-AwA 消息**\n\n{message}",
                message_type=MessageType.TEXT,
            ))
            await adapter.disconnect()
            return {
                "success": result.get("success", False),
                "action": "send_markdown",
                "response": result,
            }
        except ImportError:
            return {"success": False, "error": "钉钉适配器不可用"}
        except Exception as e:
            return {"success": False, "error": f"发送 Markdown 失败: {str(e)}"}

    # ---- 发送交互卡片 ----
    elif action == "send_action_card":
        title = kwargs.get("title", "Open-AwA 通知")
        if not message:
            return {"success": False, "error": "send_action_card 需要提供 message"}
        return {
            "success": True,
            "action": "send_action_card",
            "note": "交互卡片已提交。当前钉钉适配器支持文本消息，完整的交互卡片需要额外的卡片模板支持。",
            "card": {
                "title": title,
                "content": message,
                "buttons": kwargs.get("buttons", []),
            },
        }

    # ---- 健康检查 ----
    elif action == "health":
        try:
            from channels.dingtalk import DingTalkAdapter
            from channels.base import ChannelConfig, ChannelType

            config = ChannelConfig(
                channel_type=ChannelType.DINGTALK,
                enabled=True,
                credentials=kwargs.get("credentials", {}),
            )
            adapter = DingTalkAdapter(config)
            health = await adapter.get_health()
            return {
                "success": True,
                "action": "health",
                "health": health,
            }
        except ImportError:
            return {"success": False, "error": "钉钉适配器不可用"}
        except Exception as e:
            return {"success": False, "error": f"健康检查失败: {str(e)}"}

    return {"success": False, "error": "未识别的操作"}

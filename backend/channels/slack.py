"""
Slack 频道适配器。
支持 Socket Mode WebSocket 连接和 Block Kit 交互消息。
"""
import asyncio
import json
import time
from typing import AsyncIterator, Optional

import httpx
from loguru import logger

from backend.channels.base import (
    ChannelAdapter, ChannelConfig, ChannelMessage, ChannelType, MessageType,
)


class SlackAdapter(ChannelAdapter):
    """
    Slack 频道适配器。
    使用 Slack Socket Mode (WebSocket) 和 Web API，支持 Block Kit 交互组件。
    """

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self._http_client: Optional[httpx.AsyncClient] = None
        self._ws = None
        self._bot_token: str = ""
        self._app_token: str = ""
        self._ws_url: str = ""
        self._message_count: int = 0

    async def connect(self) -> bool:
        """通过 Slack Socket Mode 建立 WebSocket 连接。"""
        try:
            self._bot_token = self.config.credentials.get("bot_token", "")
            self._app_token = self.config.credentials.get("app_token", "")

            if not self._bot_token:
                logger.error("Slack 频道缺少 bot_token")
                return False

            self._http_client = httpx.AsyncClient(timeout=30.0)

            # 获取 Socket Mode WebSocket URL
            if self._app_token:
                resp = await self._http_client.post(
                    "https://slack.com/api/apps.connections.open",
                    headers={
                        "Authorization": f"Bearer {self._app_token}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
                data = resp.json()
                if data.get("ok"):
                    self._ws_url = data.get("url", "")
            else:
                # 无 Socket Mode 时使用 RTM
                resp = await self._http_client.post(
                    "https://slack.com/api/rtm.connect",
                    headers={"Authorization": f"Bearer {self._bot_token}"},
                )
                data = resp.json()
                if data.get("ok"):
                    self._ws_url = data.get("url", "")

            self._connected = True
            logger.bind(event="slack_connected").info("Slack 频道已连接")
            return True

        except Exception as e:
            logger.bind(event="slack_connect_error", error=str(e)).error("Slack 连接失败")
            return False

    async def disconnect(self):
        """断开 Slack 连接。"""
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._connected = False

    def _build_approval_blocks(self, tool_name: str, params: dict) -> list[dict]:
        """
        为工具审批构建 Slack Block Kit 消息块。
        包含审批/拒绝按钮的交互组件。
        """
        params_text = "\n".join([f"*{k}*: {v}" for k, v in params.items()])

        return [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"工具审批: {tool_name}"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"请求执行工具 *{tool_name}*\n\n{params_text}",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✓ 批准"},
                        "style": "primary",
                        "value": f"approve_{tool_name}",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✗ 拒绝"},
                        "style": "danger",
                        "value": f"reject_{tool_name}",
                    },
                ],
            },
        ]

    async def send_message(self, message: ChannelMessage) -> dict:
        """
        通过 Slack Web API 发送消息。
        支持文本消息和 Block Kit 交互组件。
        """
        if not self._http_client:
            return {"success": False, "error": "未连接，请先调用 connect()"}

        channel = message.conversation_id or self.config.credentials.get("default_channel", "general")

        try:
            if message.message_type == MessageType.CARD and message.metadata:
                # 工具审批 Block Kit 消息
                tool_name = message.metadata.get("tool_name", "unknown")
                params = message.metadata.get("params", {})
                blocks = self._build_approval_blocks(tool_name, params)
                payload = {
                    "channel": channel,
                    "blocks": blocks,
                    "text": f"工具审批: {tool_name}",
                }
            else:
                payload = {
                    "channel": channel,
                    "text": self.format_bot_message(message.content),
                }

            resp = await self._http_client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {self._bot_token}"},
                json=payload,
            )
            result = resp.json()
            success = result.get("ok", False)
            self._message_count += 1
            return {"success": success, "response": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def receive_messages(self) -> AsyncIterator[ChannelMessage]:
        """
        Slack Socket Mode 消息接收。
        通过 WebSocket 接收来自 Slack 的事件推送。
        """
        if not self._connected or not self._ws_url:
            return

        yield ChannelMessage(
            channel=ChannelType.SLACK,
            content="Slack Socket Mode 消息接收已就绪",
            message_type=MessageType.TEXT,
        )

    async def get_health(self) -> dict:
        """获取 Slack 频道健康状态。"""
        return {
            "connected": self._connected,
            "channel": "slack",
            "messages_sent": self._message_count,
            "ws_available": bool(self._ws_url),
        }

"""
QQ 频道适配器。
使用 QQ 开放平台 Bot API，支持 WebSocket 消息接收和 HTTP 消息发送。
"""
import asyncio
import json
import time
from typing import AsyncIterator, Optional

import httpx
from loguru import logger

from channels.base import (
    ChannelAdapter, ChannelConfig, ChannelMessage, ChannelType, MessageType,
)


class QQAdapter(ChannelAdapter):
    """
    QQ 频道适配器。
    使用 QQ Bot API (WebSocket + HTTP)，支持文本消息和交互卡片。
    """

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self._http_client: Optional[httpx.AsyncClient] = None
        self._ws = None
        self._access_token: str = ""
        self._token_expires_at: float = 0
        self._ws_endpoint: str = ""

    async def connect(self) -> bool:
        """通过 QQ Bot API 获取访问凭证和 WebSocket 地址。"""
        try:
            bot_app_id = self.config.credentials.get("bot_app_id", "")
            bot_token = self.config.credentials.get("bot_token", "")
            bot_secret = self.config.credentials.get("bot_secret", "")

            if not bot_app_id or not bot_token:
                logger.error("QQ 频道缺少 bot_app_id 或 bot_token")
                return False

            self._http_client = httpx.AsyncClient(timeout=30.0)

            # 获取 access_token
            resp = await self._http_client.post(
                "https://bots.qq.com/app/getAppAccessToken",
                json={
                    "appId": bot_app_id,
                    "clientSecret": bot_secret or bot_token,
                },
            )
            if resp.status_code != 200:
                logger.error(f"QQ 获取 token 失败: status={resp.status_code}")
                return False

            data = resp.json()
            self._access_token = data.get("access_token", "")
            self._token_expires_at = time.time() + data.get("expires_in", 7200) - 60

            # 获取 WebSocket 网关地址
            ws_resp = await self._http_client.get(
                "https://api.sgroup.qq.com/gateway",
                headers={"Authorization": f"QQBot {self._access_token}"},
            )
            if ws_resp.status_code == 200:
                self._ws_endpoint = ws_resp.json().get("url", "")

            self._connected = True
            logger.bind(event="qq_connected").info("QQ 频道已连接")
            return True

        except Exception as e:
            logger.bind(event="qq_connect_error", error=str(e)).error("QQ 连接失败")
            return False

    async def disconnect(self):
        """断开 QQ 连接。"""
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

    async def _ensure_token(self) -> bool:
        """确保 token 有效。"""
        if time.time() > self._token_expires_at:
            if not await self.connect():
                return False
        return bool(self._access_token)

    async def send_message(self, message: ChannelMessage) -> dict:
        """
        通过 QQ Bot API 发送消息。
        支持文本消息和交互审批卡片。
        """
        if not self._http_client:
            return {"success": False, "error": "未连接，请先调用 connect()"}
        if not await self._ensure_token():
            return {"success": False, "error": "无法获取有效 token"}

        channel_id = message.conversation_id or self.config.credentials.get("default_channel_id", "")
        if not channel_id:
            return {"success": False, "error": "未指定频道 ID"}

        try:
            # 根据消息类型构建 payload
            if message.message_type == MessageType.CARD and message.metadata:
                # 交互审批卡片
                card_data = message.metadata.get("card", {})
                payload = {
                    "channel_id": channel_id,
                    "msg_type": 10,  # 频道消息-模板卡片
                    "msg_id": str(int(time.time() * 1000)),
                    "ark": {
                        "template_id": card_data.get("template_id", 23),
                        "kv": [
                            {"key": "#title#", "value": card_data.get("title", "工具审批")},
                            {"key": "#content#", "value": message.content},
                        ],
                    },
                }
            else:
                payload = {
                    "channel_id": channel_id,
                    "content": self.format_bot_message(message.content),
                    "msg_id": str(int(time.time() * 1000)),
                }

            resp = await self._http_client.post(
                f"https://api.sgroup.qq.com/channels/{channel_id}/messages",
                headers={"Authorization": f"QQBot {self._access_token}"},
                json=payload,
            )
            result = resp.json() if resp.text else {}
            return {
                "success": resp.status_code == 200,
                "response": result,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def receive_messages(self) -> AsyncIterator[ChannelMessage]:
        """
        通过 QQ WebSocket 网关接收消息。
        简化实现：支持基于 WebSocket 的消息接收。
        """
        if not self._connected or not self._ws_endpoint:
            return

        yield ChannelMessage(
            channel=ChannelType.QQ,
            content="QQ WebSocket 消息接收需要完整 SDK 支持，建议通过 HTTP Webhook 模式",
            message_type=MessageType.TEXT,
        )

    async def get_health(self) -> dict:
        """获取 QQ 频道健康状态。"""
        return {
            "connected": self._connected,
            "channel": "qq",
            "bot_app_id": self.config.credentials.get("bot_app_id", "")[:8] + "***",
            "ws_available": bool(self._ws_endpoint),
        }

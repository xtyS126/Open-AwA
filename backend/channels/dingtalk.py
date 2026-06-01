"""
钉钉 (DingTalk) 频道适配器。
支持 Stream 模式消息接收和 Webhook 发送。
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


class DingTalkAdapter(ChannelAdapter):
    """
    钉钉频道适配器。
    使用钉钉机器人 Stream 模式接收消息，通过 Webhook 或 API 发送消息。
    """

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self._http_client: Optional[httpx.AsyncClient] = None
        self._ws = None
        self._endpoint: str = ""
        self._ticket: str = ""

    async def connect(self) -> bool:
        """通过钉钉 Open API 获取 WebSocket 连接信息。"""
        try:
            client_id = self.config.credentials.get("client_id", "")
            client_secret = self.config.credentials.get("client_secret", "")

            if not client_id or not client_secret:
                logger.error("钉钉频道缺少 client_id 或 client_secret")
                return False

            self._http_client = httpx.AsyncClient(timeout=30.0)

            # 获取 access_token
            resp = await self._http_client.post(
                "https://api.dingtalk.com/v1.0/oauth2/accessToken",
                json={"appKey": client_id, "appSecret": client_secret},
            )
            if resp.status_code != 200:
                logger.error(f"钉钉获取 token 失败: {resp.text}")
                return False

            data = resp.json()
            access_token = data.get("accessToken", "")

            # 获取 WebSocket 连接信息 (Stream 模式)
            resp2 = await self._http_client.post(
                "https://api.dingtalk.com/v1.0/gateway/connections/open",
                headers={"x-acs-dingtalk-access-token": access_token},
                json={"clientId": client_id, "userAgent": "Open-AwA"},
            )
            if resp2.status_code != 200:
                logger.error(f"钉钉获取连接信息失败: {resp2.text}")
                return False

            conn_data = resp2.json()
            self._endpoint = conn_data.get("endpoint", "")
            self._ticket = conn_data.get("ticket", "")

            self._connected = True
            logger.bind(event="dingtalk_connected").info("钉钉频道已连接")
            return True

        except Exception as e:
            logger.bind(event="dingtalk_connect_error", error=str(e)).error("钉钉连接失败")
            return False

    async def disconnect(self):
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._connected = False

    async def send_message(self, message: ChannelMessage) -> dict:
        """通过钉钉 Webhook 发送消息。"""
        if not self._http_client:
            return {"success": False, "error": "未连接，请先调用 connect()"}
        webhook_url = self.config.credentials.get("webhook_url", "")
        if not webhook_url:
            return {"success": False, "error": "未配置 Webhook URL"}

        try:
            resp = await self._http_client.post(
                webhook_url,
                json={
                    "msgtype": "text",
                    "text": {"content": self.format_bot_message(message.content)},
                },
            )
            return {"success": resp.status_code == 200, "response": resp.text}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def receive_messages(self) -> AsyncIterator[ChannelMessage]:
        """通过 Stream 模式接收消息（简化实现）。"""
        if not self._connected:
            return

        # Stream 模式的简化实现：使用 WebSocket 连接
        # 实际生产中需要使用钉钉的 Stream 协议
        yield ChannelMessage(
            channel=ChannelType.DINGTALK,
            content="钉钉 Stream 消息接收需要完整 SDK 支持",
            message_type=MessageType.TEXT,
        )

    async def get_health(self) -> dict:
        return {
            "connected": self._connected,
            "channel": "dingtalk",
            "client_id": self.config.credentials.get("client_id", "")[:8] + "***",
        }

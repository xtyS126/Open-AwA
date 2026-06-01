"""
Discord 频道适配器。
使用 Discord Bot API 进行消息收发。
"""
import asyncio
from typing import AsyncIterator, Optional

import httpx
from loguru import logger

from channels.base import (
    ChannelAdapter, ChannelConfig, ChannelMessage, ChannelType, MessageType,
)


class DiscordAdapter(ChannelAdapter):
    """
    Discord 频道适配器。
    使用 Discord Bot Token 通过 REST API 发送消息。
    """

    BASE_URL = "https://discord.com/api/v10"

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self._http_client: Optional[httpx.AsyncClient] = None
        self._bot_token: str = ""
        self._last_message_id: str = ""

    async def connect(self) -> bool:
        """验证 Bot Token 并连接。"""
        try:
            self._bot_token = self.config.credentials.get("bot_token", "")
            if not self._bot_token:
                logger.error("Discord 频道缺少 bot_token")
                return False

            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "Authorization": f"Bot {self._bot_token}",
                    "Content-Type": "application/json",
                },
            )

            # 验证连接：获取当前 Bot 信息
            resp = await self._http_client.get(f"{self.BASE_URL}/users/@me")
            if resp.status_code == 200:
                user_data = resp.json()
                logger.bind(
                    event="discord_connected",
                    bot_name=user_data.get("username"),
                ).info("Discord Bot 已连接")
                self._connected = True
                return True
            else:
                logger.error(f"Discord 连接验证失败: {resp.status_code} {resp.text}")
                return False

        except Exception as e:
            logger.bind(event="discord_connect_error", error=str(e)).error("Discord 连接失败")
            return False

    async def disconnect(self):
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._connected = False

    async def send_message(self, message: ChannelMessage) -> dict:
        """向 Discord 频道发送消息。"""
        channel_id = message.metadata.get("channel_id") or self.config.credentials.get("channel_id", "")
        if not channel_id:
            return {"success": False, "error": "未指定 Discord channel_id"}

        if not self._http_client:
            return {"success": False, "error": "未连接"}

        try:
            resp = await self._http_client.post(
                f"{self.BASE_URL}/channels/{channel_id}/messages",
                json={"content": self.format_bot_message(message.content)},
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                return {"success": True, "message_id": data.get("id")}
            return {"success": False, "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def receive_messages(self) -> AsyncIterator[ChannelMessage]:
        """接收 Discord 消息（需要 Gateway WebSocket 连接）。"""
        if not self._connected:
            return
        # Discord Gateway 需要完整的 WebSocket 实现
        yield ChannelMessage(
            channel=ChannelType.DISCORD,
            content="Discord Gateway 消息接收需要 WebSocket 连接",
            message_type=MessageType.TEXT,
        )

    async def get_health(self) -> dict:
        return {
            "connected": self._connected,
            "channel": "discord",
            "base_url": self.BASE_URL,
        }

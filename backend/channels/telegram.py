"""
Telegram 频道适配器。
使用 Telegram Bot API 进行消息收发，支持流式输出。
"""
import asyncio
from typing import AsyncIterator, Optional

import httpx
from loguru import logger

from backend.channels.base import (
    ChannelAdapter, ChannelConfig, ChannelMessage, ChannelType, MessageType,
)


class TelegramAdapter(ChannelAdapter):
    """
    Telegram 频道适配器。
    使用 Telegram Bot API Token 通过 HTTP 收发消息。
    支持长轮询 (getUpdates) 接收消息。
    """

    BASE_URL = "https://api.telegram.org"

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self._http_client: Optional[httpx.AsyncClient] = None
        self._bot_token: str = ""
        self._offset: int = 0
        self._polling: bool = False

    async def connect(self) -> bool:
        """验证 Bot Token 并连接。"""
        try:
            self._bot_token = self.config.credentials.get("bot_token", "")
            if not self._bot_token:
                logger.error("Telegram 频道缺少 bot_token")
                return False

            self._http_client = httpx.AsyncClient(timeout=30.0)

            # 验证 Token
            resp = await self._http_client.get(
                f"{self.BASE_URL}/bot{self._bot_token}/getMe"
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    bot_info = data.get("result", {})
                    logger.bind(
                        event="telegram_connected",
                        bot_name=bot_info.get("username"),
                    ).info("Telegram Bot 已连接")
                    self._connected = True
                    return True

            logger.error(f"Telegram 验证失败: {resp.text}")
            return False

        except Exception as e:
            logger.bind(event="telegram_connect_error", error=str(e)).error("Telegram 连接失败")
            return False

    async def disconnect(self):
        self._polling = False
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._connected = False

    async def send_message(self, message: ChannelMessage) -> dict:
        """向 Telegram 聊天发送消息。"""
        chat_id = message.metadata.get("chat_id") or self.config.credentials.get("chat_id", "")
        if not chat_id:
            return {"success": False, "error": "未指定 Telegram chat_id"}

        if not self._http_client:
            return {"success": False, "error": "未连接"}

        try:
            resp = await self._http_client.post(
                f"{self.BASE_URL}/bot{self._bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": self.format_bot_message(message.content),
                    "parse_mode": "Markdown",
                },
            )
            data = resp.json()
            if data.get("ok"):
                return {"success": True, "message_id": data["result"].get("message_id")}
            return {"success": False, "error": data.get("description", "未知错误")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def receive_messages(self) -> AsyncIterator[ChannelMessage]:
        """
        通过长轮询接收 Telegram 消息。
        """
        if not self._connected or not self._http_client:
            return

        self._polling = True
        while self._polling:
            try:
                resp = await self._http_client.get(
                    f"{self.BASE_URL}/bot{self._bot_token}/getUpdates",
                    params={"offset": self._offset, "timeout": 30},
                )
                data = resp.json()
                if data.get("ok"):
                    for update in data.get("result", []):
                        self._offset = update["update_id"] + 1
                        msg = update.get("message", {})
                        text = msg.get("text", "")
                        if text:
                            chat = msg.get("chat", {})
                            yield ChannelMessage(
                                channel=ChannelType.TELEGRAM,
                                content=text,
                                sender_id=str(msg.get("from", {}).get("id", "")),
                                sender_name=msg.get("from", {}).get("username", ""),
                                conversation_id=str(chat.get("id", "")),
                                message_type=MessageType.TEXT,
                                metadata={"chat_id": str(chat.get("id", ""))},
                            )
                await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"Telegram 轮询错误: {e}")
                await asyncio.sleep(5)

    async def get_health(self) -> dict:
        return {
            "connected": self._connected,
            "channel": "telegram",
            "polling": self._polling,
        }

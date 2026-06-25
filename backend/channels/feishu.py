"""
飞书 (Feishu/Lark) 频道适配器。
支持 tenant_access_token 认证、消息发送和事件订阅。
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


class FeishuAdapter(ChannelAdapter):
    """
    飞书频道适配器。
    使用飞书开放平台 API，支持文本消息和交互卡片。
    """

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self._http_client: Optional[httpx.AsyncClient] = None
        self._tenant_access_token: str = ""
        self._token_expires_at: float = 0

    async def connect(self) -> bool:
        """通过飞书开放平台获取 tenant_access_token。"""
        try:
            app_id = self.config.credentials.get("app_id", "")
            app_secret = self.config.credentials.get("app_secret", "")

            if not app_id or not app_secret:
                logger.error("飞书频道缺少 app_id 或 app_secret")
                return False

            self._http_client = httpx.AsyncClient(timeout=30.0)

            # 获取 tenant_access_token
            resp = await self._http_client.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            if resp.status_code != 200:
                logger.error(f"飞书获取 token 失败: status={resp.status_code}")
                return False

            data = resp.json()
            self._tenant_access_token = data.get("tenant_access_token", "")
            expire = data.get("expire", 7200)
            self._token_expires_at = time.time() + expire - 60  # 提前 60 秒刷新

            self._connected = True
            logger.bind(event="feishu_connected").info("飞书频道已连接")
            return True

        except Exception as e:
            logger.bind(event="feishu_connect_error", error=str(e)).error("飞书连接失败")
            return False

    async def disconnect(self):
        """断开飞书连接。"""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._connected = False
        self._tenant_access_token = ""

    async def _ensure_token(self) -> bool:
        """确保 token 有效，必要时刷新。"""
        if time.time() > self._token_expires_at:
            if not await self.connect():
                return False
        return bool(self._tenant_access_token)

    async def send_message(self, message: ChannelMessage) -> dict:
        """
        通过飞书消息 API 发送消息。
        支持文本和交互卡片两种消息类型。
        """
        if not self._http_client:
            return {"success": False, "error": "未连接，请先调用 connect()"}
        if not await self._ensure_token():
            return {"success": False, "error": "无法获取有效 token"}

        receive_id = message.conversation_id or self.config.credentials.get("default_chat_id", "")
        if not receive_id:
            return {"success": False, "error": "未指定接收方 ID (conversation_id)"}

        try:
            # 支持交互卡片 (CardKit)
            if message.message_type == MessageType.CARD and message.metadata:
                card = message.metadata.get("card", {})
                payload = {
                    "receive_id": receive_id,
                    "msg_type": "interactive",
                    "content": json.dumps(card),
                }
            else:
                payload = {
                    "receive_id": receive_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": self.format_bot_message(message.content)}),
                }

            resp = await self._http_client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                headers={"Authorization": f"Bearer {self._tenant_access_token}"},
                json=payload,
            )
            result = resp.json()
            success = result.get("code") == 0
            return {
                "success": success,
                "response": result,
                "message_id": result.get("data", {}).get("message_id", ""),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def receive_messages(self) -> AsyncIterator[ChannelMessage]:
        """
        飞书事件订阅接收消息。
        实际由 webhook 回调触发，此处为轮询模式的简化实现。
        生产环境应通过飞书事件订阅 (Event Subscription) 接收 Webhook 回调。
        """
        if not self._connected:
            return

        # 飞书事件订阅通过 HTTP Webhook 回调，此方法主要用于轮询模式
        if self._http_client and await self._ensure_token():
            yield ChannelMessage(
                channel=ChannelType.FEISHU,
                content="飞书事件接收通过 Webhook 回调，请配置回调地址",
                message_type=MessageType.TEXT,
            )

    async def get_health(self) -> dict:
        """获取飞书频道健康状态。"""
        healthy = self._connected and bool(self._tenant_access_token)
        return {
            "connected": self._connected,
            "channel": "feishu",
            "healthy": healthy,
            "app_id": self.config.credentials.get("app_id", "")[:8] + "***",
            "token_expires_in": max(0, int(self._token_expires_at - time.time())),
        }

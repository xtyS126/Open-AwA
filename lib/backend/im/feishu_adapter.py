"""
飞书渠道适配器，基于飞书开放平台 API 实现消息收发。
需要配置 app_id 和 app_secret，通过事件回调接收消息。
"""

import asyncio
from typing import AsyncGenerator, Optional
import httpx
from loguru import logger
from im.adapter_base import IMAdapter, IMMessage, IMChannelConfig


class FeishuAdapter(IMAdapter):
    """飞书渠道适配器（框架实现，需要配合 Webhook 使用）。"""

    def __init__(self, config: IMChannelConfig):
        super().__init__(config)
        self._tenant_access_token: str = ""
        self._client: Optional[httpx.AsyncClient] = None
        self._message_queue: asyncio.Queue[IMMessage] = asyncio.Queue()

    async def start(self) -> None:
        """启动适配器，获取 tenant_access_token。"""
        self._client = httpx.AsyncClient(timeout=30.0)

        try:
            resp = await self._client.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": self._config.app_id,
                    "app_secret": self._config.app_secret,
                },
            )
            data = resp.json()
            if data.get("code") != 0:
                raise ValueError(f"飞书认证失败: {data.get('msg')}")
            self._tenant_access_token = data.get("tenant_access_token", "")
            logger.bind(
                event="feishu_auth_success",
                module="im_feishu",
            ).info("飞书适配器认证成功")
        except Exception as e:
            self._running = False
            raise

        self._running = True

    async def stop(self) -> None:
        """停止适配器。"""
        self._running = False
        if self._client:
            await self._client.aclose()
        logger.bind(event="feishu_stopped", module="im_feishu").info("飞书适配器已停止")

    async def send_message(self, chat_id: str, text: str) -> bool:
        """发送消息到飞书。"""
        if not self._client or not self._tenant_access_token:
            return False
        try:
            resp = await self._client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                params={"receive_id_type": "chat_id"},
                headers={"Authorization": f"Bearer {self._tenant_access_token}"},
                json={
                    "receive_id": chat_id,
                    "msg_type": "text",
                    "content": f'{{"text":"{text}"}}',
                },
            )
            data = resp.json()
            return data.get("code") == 0
        except Exception as e:
            logger.bind(
                event="feishu_send_error",
                module="im_feishu",
                chat_id=chat_id,
                error=str(e),
            ).error(f"飞书发送消息失败: {e}")
            return False

    async def receive_message(self) -> AsyncGenerator[IMMessage, None]:
        """接收来自飞书的消息流（通过 Webhook 推入队列）。"""
        while self._running:
            try:
                message = await asyncio.wait_for(
                    self._message_queue.get(), timeout=1.0
                )
                yield message
            except asyncio.TimeoutError:
                continue

    async def push_webhook_message(self, event_data: dict) -> None:
        """处理飞书 Webhook 回调事件，将消息推入队列。"""
        from datetime import datetime
        try:
            event = event_data.get("event", {})
            message = event.get("message", {})
            content = message.get("content", "{}")

            import json
            content_obj = json.loads(content) if isinstance(content, str) else content
            text = content_obj.get("text", "") if isinstance(content_obj, dict) else str(content)

            im_message = IMMessage(
                message_id=message.get("message_id", ""),
                chat_id=message.get("chat_id", ""),
                sender_id=event.get("sender", {}).get("sender_id", {}).get("open_id", ""),
                sender_name=event.get("sender", {}).get("sender_id", {}).get("name", ""),
                content=text,
                channel="feishu",
                timestamp=datetime.now(),
                metadata=message,
            )
            await self._message_queue.put(im_message)
        except Exception as e:
            logger.bind(
                event="feishu_webhook_error",
                module="im_feishu",
                error=str(e),
            ).error(f"飞书 Webhook 消息处理失败: {e}")

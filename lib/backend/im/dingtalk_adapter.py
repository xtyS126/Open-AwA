"""
钉钉 (DingTalk) 渠道适配器，基于钉钉开放平台 API 实现消息收发。
需要配置 app_id (AppKey) 和 app_secret (AppSecret)，通过 Webhook 发送消息。
Stream 模式消息接收需要完整 SDK 支持，当前仅实现 Webhook 发送。
"""

from typing import AsyncGenerator, Optional

import httpx
from loguru import logger

from im.adapter_base import IMAdapter, IMChannelConfig, IMMessage


class DingtalkAdapter(IMAdapter):
    """钉钉渠道适配器。"""

    def __init__(self, config: IMChannelConfig):
        super().__init__(config)
        self._client: Optional[httpx.AsyncClient] = None
        self._access_token: str = ""

    async def start(self) -> None:
        """启动适配器，获取 access_token。"""
        self._client = httpx.AsyncClient(timeout=30.0)
        try:
            resp = await self._client.post(
                "https://api.dingtalk.com/v1.0/oauth2/accessToken",
                json={
                    "appKey": self._config.app_id,
                    "appSecret": self._config.app_secret,
                },
            )
            if resp.status_code != 200:
                raise ValueError(f"钉钉获取 token 失败: status={resp.status_code}")
            data = resp.json()
            self._access_token = data.get("accessToken", "")
            if not self._access_token:
                raise ValueError("钉钉返回的 accessToken 为空")
            logger.bind(
                event="dingtalk_auth_success",
                module="im_dingtalk",
            ).info("钉钉适配器认证成功")
        except Exception:
            # 认证失败时关闭已创建的 httpx 客户端，避免资源泄露
            await self._client.aclose()
            self._client = None
            self._running = False
            raise

        self._running = True

    async def stop(self) -> None:
        """停止适配器。"""
        self._running = False
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.bind(event="dingtalk_stopped", module="im_dingtalk").info("钉钉适配器已停止")

    async def send_message(self, chat_id: str, text: str) -> bool:
        """通过钉钉 Webhook 发送消息。

        Webhook 模式下消息固定发送到 Webhook 对应的群聊，chat_id 参数未使用。
        """
        if not self._client:
            return False
        webhook_url = self._config.webhook_url
        if not webhook_url:
            logger.bind(
                event="dingtalk_no_webhook",
                module="im_dingtalk",
            ).error("未配置 Webhook URL")
            return False
        try:
            resp = await self._client.post(
                webhook_url,
                json={
                    "msgtype": "text",
                    "text": {"content": text},
                },
            )
            return resp.status_code == 200
        except Exception as e:
            logger.bind(
                event="dingtalk_send_error",
                module="im_dingtalk",
                chat_id=chat_id,
                error=str(e),
            ).error(f"钉钉发送消息失败: {e}")
            return False

    async def receive_message(self) -> AsyncGenerator[IMMessage, None]:
        """接收来自钉钉的消息流。

        钉钉 Stream 模式需要完整的 Stream SDK 支持，当前为占位实现。
        """
        return
        yield  # noqa: E701 -- 使函数成为空 async generator

    async def health_check(self) -> bool:
        """健康检查。"""
        return self._running

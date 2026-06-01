"""
企业微信 (WeCom) 频道适配器。
支持 corpid/corpsecret 认证、应用消息发送和回调消息接收。
"""
import asyncio
import hashlib
import json
import time
from typing import AsyncIterator, Optional

import httpx
from loguru import logger

from backend.channels.base import (
    ChannelAdapter, ChannelConfig, ChannelMessage, ChannelType, MessageType,
)


class WeComAdapter(ChannelAdapter):
    """
    企业微信频道适配器。
    使用企业微信应用 API，支持文本/Markdown 消息的流式输出。
    """

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self._http_client: Optional[httpx.AsyncClient] = None
        self._access_token: str = ""
        self._token_expires_at: float = 0

    async def connect(self) -> bool:
        """通过 corpid 和 corpsecret 获取 access_token。"""
        try:
            corpid = self.config.credentials.get("corpid", "")
            corpsecret = self.config.credentials.get("corpsecret", "")
            agent_id = self.config.credentials.get("agent_id", "")

            if not corpid or not corpsecret:
                logger.error("企业微信频道缺少 corpid 或 corpsecret")
                return False

            self._http_client = httpx.AsyncClient(timeout=30.0)

            # 获取 access_token
            resp = await self._http_client.get(
                "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
                params={"corpid": corpid, "corpsecret": corpsecret},
            )
            if resp.status_code != 200:
                logger.error(f"企业微信获取 token 失败: {resp.text}")
                return False

            data = resp.json()
            if data.get("errcode") != 0:
                logger.error(f"企业微信 token 错误: {data.get('errmsg')}")
                return False

            self._access_token = data.get("access_token", "")
            self._token_expires_at = time.time() + data.get("expires_in", 7200) - 60

            self._connected = True
            logger.bind(event="wecom_connected").info("企业微信频道已连接")
            return True

        except Exception as e:
            logger.bind(event="wecom_connect_error", error=str(e)).error("企业微信连接失败")
            return False

    async def disconnect(self):
        """断开企业微信连接。"""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._connected = False
        self._access_token = ""

    async def _ensure_token(self) -> bool:
        """确保 token 有效。"""
        if time.time() > self._token_expires_at:
            if not await self.connect():
                return False
        return bool(self._access_token)

    def _verify_signature(self, signature: str, timestamp: str, nonce: str, echostr: str = "") -> bool:
        """
        验证企业微信回调 URL 签名。
        用于接收消息时的安全校验。
        """
        token = self.config.credentials.get("token", "")
        if not token:
            return False
        tmp_list = sorted([token, timestamp, nonce])
        tmp_str = "".join(tmp_list)
        calculated = hashlib.sha1(tmp_str.encode()).hexdigest()
        return calculated == signature

    async def send_message(self, message: ChannelMessage) -> dict:
        """
        通过企业微信应用消息 API 发送消息。
        支持 text 和 markdown 两种消息类型，提供流式输出的基础能力。
        """
        if not self._http_client:
            return {"success": False, "error": "未连接，请先调用 connect()"}
        if not await self._ensure_token():
            return {"success": False, "error": "无法获取有效 token"}

        agent_id = self.config.credentials.get("agent_id", "")
        if not agent_id:
            return {"success": False, "error": "未配置 agent_id"}

        touser = message.conversation_id or "@all"

        try:
            if message.message_type == MessageType.CARD or message.metadata:
                # Markdown 格式消息
                content = self.format_bot_message(message.content)
                payload = {
                    "touser": touser,
                    "agentid": int(agent_id),
                    "msgtype": "markdown",
                    "markdown": {"content": content},
                }
            else:
                payload = {
                    "touser": touser,
                    "agentid": int(agent_id),
                    "msgtype": "text",
                    "text": {"content": self.format_bot_message(message.content)},
                }

            resp = await self._http_client.post(
                f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={self._access_token}",
                json=payload,
            )
            result = resp.json()
            success = result.get("errcode") == 0
            return {"success": success, "response": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def receive_messages(self) -> AsyncIterator[ChannelMessage]:
        """
        企业微信消息接收。
        实际通过回调 URL (XML 格式) 接收，此处为简化实现。
        生产环境需配置回调地址并解析 XML body。
        """
        if not self._connected:
            return

        yield ChannelMessage(
            channel=ChannelType.WECHAT,
            content="企业微信消息通过回调 URL 接收，请配置 /api/channels/wecom/callback",
            message_type=MessageType.TEXT,
        )

    async def get_health(self) -> dict:
        """获取企业微信频道健康状态。"""
        return {
            "connected": self._connected,
            "channel": "wecom",
            "corpid": self.config.credentials.get("corpid", "")[:8] + "***",
            "token_expires_in": max(0, int(self._token_expires_at - time.time())),
        }

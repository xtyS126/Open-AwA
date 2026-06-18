"""
统一消息路由器，负责消息标准化、会话映射和角色分发。
将来自不同 IM 渠道的消息路由到 Agent 引擎，并将 Agent 回复发送回对应渠道。
"""

import asyncio
from typing import Any, Dict, Optional
from loguru import logger
from im.adapter_base import IMAdapter, IMMessage, IMChannelConfig


class SessionMapper:
    """IM 会话与 Agent 会话的映射管理。"""

    def __init__(self):
        self._mappings: Dict[str, str] = {}  # im_session_key -> agent_session_id

    def _make_key(self, channel: str, chat_id: str) -> str:
        """生成映射键。"""
        return f"{channel}:{chat_id}"

    def get_agent_session(self, channel: str, chat_id: str) -> Optional[str]:
        """根据 IM 渠道和会话 ID 获取 Agent 会话 ID。"""
        return self._mappings.get(self._make_key(channel, chat_id))

    def set_mapping(self, channel: str, chat_id: str, agent_session_id: str) -> None:
        """设置 IM 会话到 Agent 会话的映射。"""
        key = self._make_key(channel, chat_id)
        self._mappings[key] = agent_session_id
        logger.bind(
            event="session_mapped",
            module="im_router",
            im_session=key,
            agent_session=agent_session_id,
        ).info(f"会话映射: {key} -> {agent_session_id}")

    def remove_mapping(self, channel: str, chat_id: str) -> None:
        """移除映射。"""
        key = self._make_key(channel, chat_id)
        self._mappings.pop(key, None)


class MessageRouter:
    """
    统一消息路由器。

    职责：
    1. 管理各渠道适配器的生命周期
    2. 接收来自各渠道的消息
    3. 将消息路由到 Agent 引擎处理
    4. 将 Agent 回复发送回对应渠道
    """

    def __init__(self):
        self._adapters: Dict[str, IMAdapter] = {}
        self._session_mapper = SessionMapper()
        self._message_handler = None
        self._running = False

    def register_adapter(self, adapter: IMAdapter) -> None:
        """注册渠道适配器。"""
        channel = adapter.channel_name
        self._adapters[channel] = adapter
        logger.bind(
            event="adapter_registered",
            module="im_router",
            channel=channel,
        ).info(f"适配器已注册: {channel}")

    def set_message_handler(self, handler) -> None:
        """设置消息处理函数。

        handler 签名: async def handler(message: IMMessage, agent_session_id: str) -> str
        返回值为 Agent 的回复文本。
        """
        self._message_handler = handler

    async def start_all(self) -> None:
        """启动所有已注册的适配器。"""
        self._running = True
        for channel, adapter in self._adapters.items():
            try:
                await adapter.start()
                logger.bind(
                    event="adapter_started",
                    module="im_router",
                    channel=channel,
                ).info(f"适配器已启动: {channel}")
            except Exception as e:
                logger.bind(
                    event="adapter_start_error",
                    module="im_router",
                    channel=channel,
                    error=str(e),
                ).error(f"适配器启动失败 {channel}: {e}")

    async def stop_all(self) -> None:
        """停止所有适配器。"""
        self._running = False
        for channel, adapter in self._adapters.items():
            try:
                await adapter.stop()
                logger.bind(
                    event="adapter_stopped",
                    module="im_router",
                    channel=channel,
                ).info(f"适配器已停止: {channel}")
            except Exception as e:
                logger.bind(
                    event="adapter_stop_error",
                    module="im_router",
                    channel=channel,
                    error=str(e),
                ).error(f"适配器停止失败 {channel}: {e}")

    async def route_message(self, message: IMMessage) -> None:
        """路由消息到 Agent 引擎并发送回复。"""
        if not self._message_handler:
            logger.bind(
                event="no_message_handler",
                module="im_router",
                channel=message.channel,
            ).warning("未设置消息处理函数")
            return

        # 获取或创建 Agent 会话映射
        agent_session_id = self._session_mapper.get_agent_session(
            message.channel, message.chat_id
        )
        if not agent_session_id:
            agent_session_id = f"im_{message.channel}_{message.chat_id}"
            self._session_mapper.set_mapping(
                message.channel, message.chat_id, agent_session_id
            )

        # 调用消息处理函数
        try:
            reply_text = await self._message_handler(message, agent_session_id)

            # 发送回复到对应渠道
            if reply_text:
                adapter = self._adapters.get(message.channel)
                if adapter:
                    await adapter.send_message(message.chat_id, reply_text)
        except Exception as e:
            logger.bind(
                event="route_message_error",
                module="im_router",
                channel=message.channel,
                error=str(e),
            ).error(f"消息路由失败: {e}")

    def get_registered_channels(self) -> list[str]:
        """获取已注册的渠道列表。"""
        return list(self._adapters.keys())

    def get_adapter(self, channel: str) -> Optional[IMAdapter]:
        """获取指定渠道的适配器。"""
        return self._adapters.get(channel)


# 全局消息路由器单例
message_router = MessageRouter()

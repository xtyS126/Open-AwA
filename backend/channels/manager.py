"""
频道连接管理器和连接池。
"""
from dataclasses import dataclass, field
from typing import Any, Optional
from loguru import logger

from channels.base import (
    ChannelAdapter, ChannelConfig, ChannelType, ChannelMessage,
)


@dataclass
class ChannelState:
    """频道运行状态。"""
    adapter: ChannelAdapter
    config: ChannelConfig
    connected: bool = False
    connected_at: Optional[str] = None
    message_count: int = 0
    error_count: int = 0
    last_error: Optional[str] = None


class ChannelManager:
    """
    频道管理器。
    管理所有 IM 频道的生命周期：连接、收发消息、健康检查。
    """

    def __init__(self):
        self._adapters: dict[ChannelType, ChannelState] = {}
        self._message_queue: list[ChannelMessage] = []

    def register_adapter(self, adapter: ChannelAdapter, config: ChannelConfig):
        """
        注册频道适配器。
        """
        self._adapters[adapter.channel_type] = ChannelState(
            adapter=adapter,
            config=config,
        )
        logger.bind(event="channel_registered", channel=adapter.channel_type.value).info("频道已注册")

    async def connect_channel(self, channel_type: ChannelType) -> bool:
        """连接指定频道。"""
        state = self._adapters.get(channel_type)
        if not state:
            return False

        if not state.config.enabled:
            logger.bind(event="channel_disabled", channel=channel_type.value).info("频道已禁用，跳过连接")
            return False

        try:
            success = await state.adapter.connect()
            state.connected = success
            if success:
                from datetime import datetime, timezone
                state.connected_at = datetime.now(timezone.utc).isoformat()
                logger.bind(event="channel_connected", channel=channel_type.value).info("频道已连接")
            return success
        except Exception as e:
            state.error_count += 1
            state.last_error = str(e)
            logger.bind(event="channel_connect_error", channel=channel_type.value, error=str(e)).error("频道连接失败")
            return False

    async def connect_all_enabled(self):
        """连接所有已启用的频道。"""
        for channel_type, state in self._adapters.items():
            if state.config.enabled:
                await self.connect_channel(channel_type)

    async def disconnect_all(self):
        """断开所有频道连接。"""
        for channel_type, state in self._adapters.items():
            try:
                await state.adapter.disconnect()
                state.connected = False
            except Exception as e:
                logger.warning(f"频道 {channel_type.value} 断开失败: {e}")

    async def send_to_channel(self, channel_type: ChannelType, message: ChannelMessage) -> dict:
        """向指定频道发送消息。"""
        state = self._adapters.get(channel_type)
        if not state or not state.connected:
            return {"success": False, "error": f"频道 {channel_type.value} 未连接"}

        try:
            result = await state.adapter.send_message(message)
            state.message_count += 1
            return result
        except Exception as e:
            state.error_count += 1
            state.last_error = str(e)
            return {"success": False, "error": str(e)}

    async def broadcast(self, message: ChannelMessage, channels: Optional[list[ChannelType]] = None):
        """向多个频道广播消息。"""
        targets = channels or [
            ct for ct, state in self._adapters.items() if state.connected
        ]
        results = {}
        for ct in targets:
            results[ct.value] = await self.send_to_channel(ct, message)
        return results

    def get_status(self) -> dict:
        """获取所有频道状态。"""
        return {
            ct.value: {
                "connected": state.connected,
                "enabled": state.config.enabled,
                "message_count": state.message_count,
                "error_count": state.error_count,
                "last_error": state.last_error,
                "connected_at": state.connected_at,
            }
            for ct, state in self._adapters.items()
        }

    def get_enabled_channels(self) -> list[ChannelType]:
        """获取已启用的频道列表。"""
        return [
            ct for ct, state in self._adapters.items()
            if state.config.enabled and state.connected
        ]

"""
频道抽象层 — 多渠道 IM 接入。
"""
from backend.channels.base import (
    ChannelAdapter, ChannelConfig, ChannelMessage,
    ChannelType, MessageType,
)
from backend.channels.manager import ChannelManager

__all__ = [
    "ChannelAdapter", "ChannelConfig", "ChannelMessage",
    "ChannelType", "MessageType", "ChannelManager",
]

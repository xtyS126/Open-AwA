"""
频道抽象层 — 多渠道 IM 接入。
"""
from backend.channels.base import (
    ChannelAdapter, ChannelConfig, ChannelMessage,
    ChannelType, MessageType,
)
from backend.channels.manager import ChannelManager
from backend.channels.dingtalk import DingTalkAdapter
from backend.channels.discord import DiscordAdapter
from backend.channels.telegram import TelegramAdapter
from backend.channels.feishu import FeishuAdapter
from backend.channels.qq import QQAdapter
from backend.channels.wecom import WeComAdapter
from backend.channels.slack import SlackAdapter
from backend.channels.matrix import MatrixAdapter
from backend.channels.imessage import IMessageAdapter

__all__ = [
    "ChannelAdapter", "ChannelConfig", "ChannelMessage",
    "ChannelType", "MessageType", "ChannelManager",
    "DingTalkAdapter", "DiscordAdapter", "TelegramAdapter",
    "FeishuAdapter", "QQAdapter", "WeComAdapter",
    "SlackAdapter", "MatrixAdapter", "IMessageAdapter",
]

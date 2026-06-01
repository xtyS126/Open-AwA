"""
频道抽象层 — 多渠道 IM 接入。
"""
from channels.base import (
    ChannelAdapter, ChannelConfig, ChannelMessage,
    ChannelType, MessageType,
)
from channels.manager import ChannelManager
from channels.dingtalk import DingTalkAdapter
from channels.discord import DiscordAdapter
from channels.telegram import TelegramAdapter
from channels.feishu import FeishuAdapter
from channels.qq import QQAdapter
from channels.wecom import WeComAdapter
from channels.slack import SlackAdapter
from channels.matrix import MatrixAdapter
from channels.imessage import IMessageAdapter

__all__ = [
    "ChannelAdapter", "ChannelConfig", "ChannelMessage",
    "ChannelType", "MessageType", "ChannelManager",
    "DingTalkAdapter", "DiscordAdapter", "TelegramAdapter",
    "FeishuAdapter", "QQAdapter", "WeComAdapter",
    "SlackAdapter", "MatrixAdapter", "IMessageAdapter",
]

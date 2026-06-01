"""
频道适配器抽象基类和类型定义。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, AsyncIterator


class ChannelType(Enum):
    DINGTALK = "dingtalk"
    FEISHU = "feishu"
    WECHAT = "weixin"
    DISCORD = "discord"
    TELEGRAM = "telegram"
    QQ = "qq"
    SLACK = "slack"
    CONSOLE = "console"


class MessageType(Enum):
    TEXT = "text"
    IMAGE = "image"
    FILE = "file"
    VOICE = "voice"
    VIDEO = "video"
    CARD = "card"


@dataclass
class ChannelMessage:
    channel: ChannelType
    message_type: MessageType = MessageType.TEXT
    content: str = ""
    sender_id: str = ""
    sender_name: str = ""
    conversation_id: str = ""
    attachments: list[dict] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""


@dataclass
class ChannelConfig:
    channel_type: ChannelType
    enabled: bool = False
    credentials: dict[str, Any] = field(default_factory=dict)
    bot_prefix: str = "[BOT]"
    filter_tool_messages: bool = False
    access_control: dict[str, Any] = field(default_factory=dict)


class ChannelAdapter(ABC):
    def __init__(self, config: ChannelConfig):
        self.config = config
        self._connected = False

    @property
    def channel_type(self) -> ChannelType:
        return self.config.channel_type

    @property
    def is_connected(self) -> bool:
        return self._connected

    @abstractmethod
    async def connect(self) -> bool: ...

    @abstractmethod
    async def disconnect(self): ...

    @abstractmethod
    async def send_message(self, message: ChannelMessage) -> dict: ...

    @abstractmethod
    async def receive_messages(self) -> AsyncIterator[ChannelMessage]: ...

    @abstractmethod
    async def get_health(self) -> dict: ...

    def format_bot_message(self, text: str) -> str:
        prefix = self.config.bot_prefix
        if prefix:
            return f"{prefix} {text}"
        return text

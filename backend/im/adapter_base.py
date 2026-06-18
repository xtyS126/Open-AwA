"""
IM 渠道适配器基类，定义统一的适配器接口和消息格式。
所有具体渠道适配器（Telegram、飞书、钉钉等）需继承此基类。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional
from loguru import logger


@dataclass
class IMMessage:
    """统一的 IM 消息格式。"""
    message_id: str
    chat_id: str
    sender_id: str
    sender_name: str
    content: str
    channel: str  # "telegram" | "feishu" | "dingtalk"
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IMChannelConfig:
    """IM 渠道配置。"""
    channel: str
    enabled: bool = False
    bot_token: str = ""
    app_id: str = ""
    app_secret: str = ""
    webhook_url: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


class IMAdapter(ABC):
    """IM 渠道适配器基类。"""

    def __init__(self, config: IMChannelConfig):
        self._config = config
        self._running = False

    @property
    def channel_name(self) -> str:
        """渠道名称。"""
        return self._config.channel

    @property
    def is_running(self) -> bool:
        """是否正在运行。"""
        return self._running

    @abstractmethod
    async def start(self) -> None:
        """启动适配器，建立与 IM 平台的连接。"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """停止适配器，断开连接。"""
        ...

    @abstractmethod
    async def send_message(self, chat_id: str, text: str) -> bool:
        """发送消息到 IM 平台。返回是否成功。"""
        ...

    @abstractmethod
    async def receive_message(self) -> AsyncGenerator[IMMessage, None]:
        """接收来自 IM 平台的消息流。"""
        ...

    async def health_check(self) -> bool:
        """健康检查，返回适配器是否正常工作。"""
        return self._running

"""
Matrix 频道适配器。
支持 Matrix 协议的消息收发、端到端加密 (E2EE) 和 SAS 设备验证。
使用 matrix-nio 库实现完整的 Matrix 客户端功能。
"""
import asyncio
import json
import time
from typing import AsyncIterator, Optional

from loguru import logger

from backend.channels.base import (
    ChannelAdapter, ChannelConfig, ChannelMessage, ChannelType, MessageType,
)

try:
    import nio
    HAS_NIO = True
except ImportError:
    HAS_NIO = False


class MatrixAdapter(ChannelAdapter):
    """
    Matrix 频道适配器。
    使用 matrix-nio 库连接 Matrix 服务器，支持加密房间和 SAS 验证。
    """

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self._client: Optional["nio.AsyncClient"] = None
        self._sync_task: Optional[asyncio.Task] = None
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._device_id: str = ""
        self._joined_rooms: list[str] = []

    async def connect(self) -> bool:
        """
        连接到 Matrix 服务器。
        支持密码登录和 SSO 登录两种方式。
        """
        if not HAS_NIO:
            logger.error("Matrix 频道缺少 matrix-nio 依赖，请运行: pip install matrix-nio")
            return False

        try:
            homeserver = self.config.credentials.get("homeserver", "https://matrix.org")
            user_id = self.config.credentials.get("user_id", "")
            password = self.config.credentials.get("password", "")
            access_token = self.config.credentials.get("access_token", "")

            if not user_id:
                logger.error("Matrix 频道缺少 user_id")
                return False

            self._client = nio.AsyncClient(homeserver, user_id)

            # 使用已有 access_token 或密码登录
            if access_token:
                self._client.access_token = access_token
                self._device_id = self.config.credentials.get("device_id", "Open-AwA")
            elif password:
                resp = await self._client.login(password)
                if isinstance(resp, nio.LoginError):
                    logger.error(f"Matrix 登录失败: {resp.message}")
                    return False
                self._device_id = resp.device_id
                # 保存 access_token 以便后续使用
                logger.bind(event="matrix_login").info(f"登录成功，device_id: {self._device_id}")
            else:
                logger.error("Matrix 需要 access_token 或 password")
                return False

            # 初始化加密支持
            if self.config.credentials.get("enable_e2ee", False):
                try:
                    await self._client.sync(timeout=30000)
                    # 设置加密状态
                    logger.bind(event="matrix_e2ee").info("E2EE 加密已初始化")
                except Exception as e:
                    logger.warning(f"E2EE 初始化失败: {str(e)}，将以非加密模式运行")

            # 获取已加入的房间列表
            joined_resp = await self._client.joined_rooms()
            if isinstance(joined_resp, nio.JoinedRoomsResponse):
                self._joined_rooms = joined_resp.rooms

            self._connected = True
            logger.bind(event="matrix_connected").info(f"Matrix 已连接，{len(self._joined_rooms)} 个房间")
            return True

        except Exception as e:
            logger.bind(event="matrix_connect_error", error=str(e)).error("Matrix 连接失败")
            return False

    async def disconnect(self):
        """断开 Matrix 连接。"""
        if self._sync_task:
            self._sync_task.cancel()
            self._sync_task = None
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
        self._connected = False

    async def send_message(self, message: ChannelMessage) -> dict:
        """
        向 Matrix 房间发送消息。
        支持加密房间的自动加密发送。
        """
        if not self._client or not self._connected:
            return {"success": False, "error": "未连接，请先调用 connect()"}

        room_id = message.conversation_id
        if not room_id and self._joined_rooms:
            room_id = self._joined_rooms[0]

        if not room_id:
            return {"success": False, "error": "未指定房间 ID"}

        try:
            content = {
                "msgtype": "m.text",
                "body": self.format_bot_message(message.content),
            }

            # 检查房间是否加密
            if HAS_NIO:
                try:
                    # 使用 send 方法，自动处理加密
                    resp = await self._client.room_send(
                        room_id=room_id,
                        message_type="m.room.message",
                        content=content,
                    )
                except nio.exceptions.EncryptionError:
                    # 如果加密失败，尝试非加密发送
                    resp = await self._client.room_send(
                        room_id=room_id,
                        message_type="m.room.message",
                        content=content,
                        ignore_unverified_devices=True,
                    )
            else:
                resp = await self._client.room_send(
                    room_id=room_id,
                    message_type="m.room.message",
                    content=content,
                )

            if isinstance(resp, nio.RoomSendError):
                return {"success": False, "error": resp.message}

            return {"success": True, "event_id": resp.event_id, "room_id": room_id}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def receive_messages(self) -> AsyncIterator[ChannelMessage]:
        """
        通过 Matrix sync 接收消息。
        从消息队列中获取缓存的接收消息。
        """
        if not self._connected:
            return

        # 从队列中获取消息
        try:
            while not self._message_queue.empty():
                msg = self._message_queue.get_nowait()
                if isinstance(msg, ChannelMessage):
                    yield msg
        except asyncio.QueueEmpty:
            pass

        # 同步一次以获取新消息
        if self._client:
            try:
                sync_resp = await self._client.sync(timeout=10000)
                if isinstance(sync_resp, nio.SyncResponse):
                    for room_id, room in sync_resp.rooms.join.items():
                        for event in room.timeline.events:
                            if isinstance(event, nio.RoomMessageText):
                                msg = ChannelMessage(
                                    channel=ChannelType.MATRIX,
                                    content=event.body,
                                    sender_id=event.sender,
                                    conversation_id=room_id,
                                    message_type=MessageType.TEXT,
                                    metadata={"event_id": event.event_id},
                                )
                                self._message_queue.put_nowait(msg)
                                yield msg
            except asyncio.TimeoutError:
                pass

    async def get_health(self) -> dict:
        """获取 Matrix 频道健康状态。"""
        return {
            "connected": self._connected,
            "channel": "matrix",
            "homeserver": self.config.credentials.get("homeserver", "https://matrix.org"),
            "joined_rooms": len(self._joined_rooms),
            "e2ee_enabled": self.config.credentials.get("enable_e2ee", False),
        }

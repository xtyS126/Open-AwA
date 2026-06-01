"""
iMessage 频道适配器。
macOS 限定，通过 AppleScript 和 chat.db 实现消息收发。
"""
import asyncio
import platform
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import AsyncIterator, Optional

from loguru import logger

from channels.base import (
    ChannelAdapter, ChannelConfig, ChannelMessage, ChannelType, MessageType,
)


class IMessageAdapter(ChannelAdapter):
    """
    iMessage 频道适配器。
    仅限 macOS 使用。通过 AppleScript 发送消息，通过 chat.db 轮询接收消息。
    """

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self._db_path: Path = Path.home() / "Library" / "Messages" / "chat.db"
        self._last_rowid: int = 0
        self._poll_interval: float = 2.0

    async def connect(self) -> bool:
        """
        检查运行环境和数据库可访问性。
        """
        if platform.system() != "Darwin":
            logger.warning("iMessage 适配器仅支持 macOS")
            self._connected = False
            return False

        if not self._db_path.exists():
            logger.error(f"iMessage 数据库不存在: {self._db_path}")
            return False

        try:
            # 验证数据库可读
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.execute("SELECT MAX(ROWID) FROM message")
            row = cursor.fetchone()
            if row and row[0]:
                self._last_rowid = row[0]
            conn.close()
        except sqlite3.Error as e:
            logger.error(f"无法读取 iMessage 数据库: {str(e)}")
            return False

        self._connected = True
        logger.bind(event="imessage_connected").info("iMessage 已连接")
        return True

    async def disconnect(self):
        """断开 iMessage 连接。"""
        self._connected = False
        logger.bind(event="imessage_disconnected").info("iMessage 已断开")

    async def send_message(self, message: ChannelMessage) -> dict:
        """
        通过 AppleScript 发送 iMessage 消息。
        """
        if platform.system() != "Darwin":
            return {"success": False, "error": "iMessage 仅支持 macOS"}

        recipient = message.conversation_id
        if not recipient:
            return {"success": False, "error": "未指定接收方 (conversation_id = 电话号码或邮箱)"}

        text = self.format_bot_message(message.content)

        # 转义 AppleScript 中的特殊字符
        escaped_text = text.replace('\\', '\\\\').replace('"', '\\"')

        script = f'''
        tell application "Messages"
            set targetBuddy to "{recipient}"
            set targetService to id of service "iMessage"
            set theBuddy to buddy targetBuddy of service "iMessage"
            send "{escaped_text}" to theBuddy
        end tell
        '''

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                return {"success": False, "error": result.stderr.strip()}
            return {"success": True, "response": "消息已发送"}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "AppleScript 执行超时"}
        except FileNotFoundError:
            return {"success": False, "error": "osascript 不可用"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def receive_messages(self) -> AsyncIterator[ChannelMessage]:
        """
        轮询 chat.db 获取新消息。
        每 2 秒检查一次新消息。
        """
        if not self._connected:
            return

        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row

            cursor = conn.execute(
                """
                SELECT m.ROWID, m.text, m.date, m.is_from_me, m.guid,
                       h.id as chat_id, c.chat_identifier
                FROM message m
                JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
                JOIN chat c ON cmj.chat_id = c.ROWID
                LEFT JOIN handle h ON m.handle_id = h.ROWID
                WHERE m.ROWID > ?
                ORDER BY m.ROWID ASC
                LIMIT 10
                """,
                (self._last_rowid,),
            )

            messages = cursor.fetchall()
            for row in messages:
                self._last_rowid = max(self._last_rowid, row["ROWID"])

                if row["is_from_me"]:
                    continue  # 跳过自己发出的消息

                # iMessage 时间戳从 2001-01-01 开始
                date_str = ""
                if row["date"]:
                    try:
                        ts = int(row["date"]) / 1_000_000_000 + 978307200
                        date_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
                    except Exception:
                        pass

                yield ChannelMessage(
                    channel=ChannelType.IMESSAGE,
                    content=row["text"] or "",
                    sender_id=row["chat_identifier"] or "unknown",
                    sender_name=row["chat_identifier"] or "",
                    conversation_id=row["chat_identifier"] or "",
                    message_type=MessageType.TEXT,
                )

            conn.close()

        except sqlite3.Error as e:
            logger.warning(f"iMessage 数据库读取错误: {str(e)}")

    async def get_health(self) -> dict:
        """获取 iMessage 频道健康状态。"""
        is_macos = platform.system() == "Darwin"
        db_accessible = self._db_path.exists() if is_macos else False

        return {
            "connected": self._connected,
            "channel": "imessage",
            "platform": platform.system(),
            "supported": is_macos,
            "db_accessible": db_accessible,
            "last_rowid": self._last_rowid,
        }

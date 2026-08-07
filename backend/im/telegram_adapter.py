"""
Telegram 渠道适配器，基于 Telegram Bot API 实现消息收发。
需要配置 bot_token，通过 long polling 方式接收消息。
"""

import asyncio
from typing import AsyncGenerator, Optional
import httpx
from loguru import logger
from im.adapter_base import IMAdapter, IMMessage, IMChannelConfig


class TelegramAdapter(IMAdapter):
    """Telegram 渠道适配器。"""

    # 连续轮询失败上限：超过后停止轮询并标记渠道错误状态（禁止无限重试）
    MAX_CONSECUTIVE_POLL_FAILURES = 5

    def __init__(self, config: IMChannelConfig):
        super().__init__(config)
        self._base_url = f"https://api.telegram.org/bot{config.bot_token}"
        self._offset = 0
        self._client: Optional[httpx.AsyncClient] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._message_queue: asyncio.Queue[IMMessage] = asyncio.Queue()
        self._consecutive_poll_failures = 0
        # 渠道错误状态（非 None 表示渠道已进入错误状态，暴露给诊断）
        self._channel_error: Optional[str] = None

    async def start(self) -> None:
        """启动适配器，验证 Bot Token 并开始轮询。"""
        self._client = httpx.AsyncClient(timeout=30.0)

        # 验证 Bot Token
        try:
            resp = await self._client.get(f"{self._base_url}/getMe")
            data = resp.json()
            if not data.get("ok"):
                raise ValueError(f"Bot Token 验证失败: {data.get('description')}")
            bot_info = data.get("result", {})
            logger.bind(
                event="telegram_bot_verified",
                module="im_telegram",
                bot_username=bot_info.get("username"),
            ).info(f"Telegram Bot 已连接: @{bot_info.get('username')}")
        except Exception:
            # 验证失败不会启动轮询，仍需释放已经创建的 HTTP 客户端。
            if self._client is not None:
                await self._client.aclose()
                self._client = None
            self._running = False
            raise

        self._running = True

        # 启动轮询任务
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """停止适配器。"""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.bind(event="telegram_stopped", module="im_telegram").info("Telegram 适配器已停止")

    async def send_message(self, chat_id: str, text: str) -> bool:
        """发送消息到 Telegram。

        失败时抛出结构化异常让路由层感知（禁止返回 False 被路由层忽略）。

        Raises:
            RuntimeError: 适配器未启动。
            ValueError: Telegram API 返回错误。
            Exception: 网络/HTTP 异常（显式传播）。
        """
        if not self._client:
            raise RuntimeError("Telegram 适配器未启动，无法发送消息")

        # Telegram 消息最大 4096 字符
        if len(text) > 4096:
            text = text[:4090] + "..."

        resp = await self._client.post(
            f"{self._base_url}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        )
        data = resp.json()
        if not data.get("ok", False):
            raise ValueError(
                f"Telegram 发送消息失败: {data.get('description', 'unknown error')}"
            )
        return True

    async def _poll_loop(self) -> None:
        """Long polling 循环，获取 Telegram 更新。

        连续失败达到上限时停止轮询并标记渠道错误状态（禁止无限重试）。
        """
        while self._running:
            try:
                resp = await self._client.get(
                    f"{self._base_url}/getUpdates",
                    params={"offset": self._offset, "timeout": 30},
                )
                data = resp.json()
                if not data.get("ok"):
                    self._consecutive_poll_failures += 1
                    if self._consecutive_poll_failures >= self.MAX_CONSECUTIVE_POLL_FAILURES:
                        self._mark_channel_error(
                            f"连续 {self.MAX_CONSECUTIVE_POLL_FAILURES} 次轮询失败: "
                            f"{data.get('description')}"
                        )
                        break
                    logger.bind(
                        event="telegram_poll_error",
                        module="im_telegram",
                        error=str(data.get("description")),
                        consecutive_failures=self._consecutive_poll_failures,
                    ).warning(f"Telegram 轮询错误: {data.get('description')}")
                    await asyncio.sleep(5)
                    continue

                self._consecutive_poll_failures = 0
                updates = data.get("result", [])
                for update in updates:
                    self._offset = update.get("update_id", 0) + 1
                    message = update.get("message")
                    if message:
                        im_message = self._parse_message(message)
                        if im_message:
                            await self._message_queue.put(im_message)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._consecutive_poll_failures += 1
                if self._consecutive_poll_failures >= self.MAX_CONSECUTIVE_POLL_FAILURES:
                    self._mark_channel_error(
                        f"连续 {self.MAX_CONSECUTIVE_POLL_FAILURES} 次轮询异常: {e}"
                    )
                    break
                logger.bind(
                    event="telegram_poll_exception",
                    module="im_telegram",
                    error=str(e),
                    consecutive_failures=self._consecutive_poll_failures,
                ).error(f"Telegram 轮询异常: {e}")
                await asyncio.sleep(5)

    def _mark_channel_error(self, reason: str) -> None:
        """标记渠道错误状态并停止轮询（错误暴露给诊断）。"""
        self._channel_error = reason
        self._running = False
        logger.bind(
            event="telegram_channel_error",
            module="im_telegram",
            error=reason,
        ).critical(f"Telegram 渠道进入错误状态: {reason}")

    async def health_check(self) -> bool:
        """健康检查：渠道处于错误状态时视为不健康。"""
        return self._running and self._channel_error is None

    def _parse_message(self, tg_message: dict) -> Optional[IMMessage]:
        """将 Telegram 消息解析为统一格式。"""
        from datetime import datetime
        try:
            return IMMessage(
                message_id=str(tg_message.get("message_id", "")),
                chat_id=str(tg_message.get("chat", {}).get("id", "")),
                sender_id=str(tg_message.get("from", {}).get("id", "")),
                sender_name=tg_message.get("from", {}).get("first_name", ""),
                content=tg_message.get("text", ""),
                channel="telegram",
                timestamp=datetime.fromtimestamp(
                    tg_message.get("date", 0)
                ),
                metadata={
                    "chat_type": tg_message.get("chat", {}).get("type", ""),
                    "username": tg_message.get("from", {}).get("username", ""),
                },
            )
        except Exception as e:
            logger.bind(
                event="telegram_parse_error",
                module="im_telegram",
                error=str(e),
            ).warning(f"Telegram 消息解析失败: {e}")
            return None

    async def receive_message(self) -> AsyncGenerator[IMMessage, None]:
        """接收来自 Telegram 的消息流。"""
        while self._running:
            try:
                message = await asyncio.wait_for(
                    self._message_queue.get(), timeout=1.0
                )
                yield message
            except asyncio.TimeoutError:
                continue

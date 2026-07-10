"""
微信自动回复运行时服务。

该模块负责把"拉取微信入站消息 -> 调用 AI 生成回复 -> 清洗回复文本 -> 回发微信"
串成一个可重复调用、可持久化恢复的后端闭环。

v2: 集成跨渠道上下文，使微信回复能引用 web UI 中的对话历史。
v3: 支持多媒体消息识别（图片/语音/文件），并通过事件总线向 WebSocket 推送实时通知。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from core.agent import AIAgent
from db.models import SessionLocal, ShortTermMemory, WeixinBinding, WeixinAutoReplyRule
from skills.weixin_skill_adapter import (
    WeixinAdapterError,
    WeixinRuntimeConfig,
    WeixinSkillAdapter,
    load_binding,
)


AutoReplyGenerator = Callable[[Session, WeixinBinding, Dict[str, Any]], Awaitable[Dict[str, Any]]]

DEFAULT_AUTO_REPLY_FALLBACK_TEXT = "我暂时无法生成合适的回复，请稍后再试。"
DEFAULT_AUTO_REPLY_POLL_INTERVAL_SECONDS = 3

# 多媒体消息类型常量
MULTIMEDIA_TYPE_IMAGE = "image"
MULTIMEDIA_TYPE_VOICE = "voice"
MULTIMEDIA_TYPE_FILE = "file"
MULTIMEDIA_TYPE_VIDEO = "video"

# 微信上游 item.type 与多媒体类型的映射
_ITEM_TYPE_TO_MULTIMEDIA = {
    2: MULTIMEDIA_TYPE_IMAGE,
    3: MULTIMEDIA_TYPE_VOICE,
    4: MULTIMEDIA_TYPE_VIDEO,
    5: MULTIMEDIA_TYPE_FILE,
}


class WeixinEventBus:
    """
    进程内微信消息事件总线。

    用于在自动回复轮询循环与 WebSocket 实时推送端点之间传递新消息事件。
    每个用户的每个设备拥有独立的 asyncio.Queue，支持同用户多设备并发订阅，
    事件发布时广播到该用户所有设备的队列。
    """

    def __init__(self) -> None:
        # user_id -> 该用户所有订阅队列列表（每个设备一个独立队列）
        self._subscribers: Dict[str, List[asyncio.Queue[Dict[str, Any]]]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, user_id: str, maxsize: int = 100) -> asyncio.Queue[Dict[str, Any]]:
        """为指定用户订阅事件，每个设备返回独立队列。"""
        user_key = _safe_text(user_id)
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=max(maxsize, 1))
        async with self._lock:
            self._subscribers.setdefault(user_key, []).append(queue)
        return queue

    async def unsubscribe(
        self,
        user_id: str,
        queue: Optional[asyncio.Queue[Dict[str, Any]]] = None,
    ) -> None:
        """移除指定设备订阅；未传队列时兼容旧调用并清理该用户全部订阅。"""
        user_key = _safe_text(user_id)
        async with self._lock:
            queues = self._subscribers.get(user_key)
            if not queues:
                return
            if queue is None:
                queues.clear()
            else:
                try:
                    queues.remove(queue)
                except ValueError:
                    pass
            if not queues:
                self._subscribers.pop(user_key, None)

    async def publish(self, user_id: str, event: Dict[str, Any]) -> None:
        """向指定用户的所有设备广播事件。"""
        user_key = _safe_text(user_id)
        async with self._lock:
            queues = list(self._subscribers.get(user_key, []))
        if not queues:
            return
        for queue in queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # 队列满，丢弃最旧事件后重试
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.bind(
                        module="weixin.event_bus",
                        user_id=user_key,
                    ).warning("事件队列已满，丢弃新事件")


# 全局事件总线单例
_EVENT_BUS: Optional[WeixinEventBus] = None


def get_event_bus() -> WeixinEventBus:
    """获取全局微信事件总线单例。"""
    global _EVENT_BUS
    if _EVENT_BUS is None:
        _EVENT_BUS = WeixinEventBus()
    return _EVENT_BUS


DEFAULT_MAX_PROCESSED_MESSAGES = 500
DEFAULT_MAX_REPLY_LENGTH = 1000
DEFAULT_MAX_MESSAGE_PROCESS_RETRIES = 3
DEFAULT_CROSS_CHANNEL_CONTEXT_TURNS = 10

_REASONING_BLOCK_RE = re.compile(
    r"<(?:think|thinking|reasoning)[^>]*>[\s\S]*?</(?:think|thinking|reasoning)>",
    re.IGNORECASE,
)
_REASONING_FENCE_RE = re.compile(
    r"```(?:thinking|reasoning|analysis)[\s\S]*?```",
    re.IGNORECASE,
)
_FINAL_MARKERS = (
    "最终答案：",
    "最终答案:",
    "最终回复：",
    "最终回复:",
    "最终回答：",
    "最终回答:",
    "答复：",
    "答复:",
)
_REASONING_LINE_PREFIXES = (
    "思考过程",
    "推理过程",
    "链路分析",
    "内部推理",
    "reasoning",
    "analysis",
    "chain of thought",
)


def _utcnow_iso() -> str:
    """统一生成 UTC 时间戳，便于状态文件和日志对齐。"""
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    """把任意值安全转换为字符串。"""
    return str(value or "").strip()


def _truncate_text(text: str, max_length: int = 200) -> str:
    """限制状态文件中的预览长度，避免持久化数据无限增长。"""
    normalized = _safe_text(text)
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max(0, max_length - 3)] + "..."


def _truncate_reply_text(text: str, max_length: int) -> str:
    """
    按 Unicode 字符边界截断微信最终回复文本。

    Python 3 的 `str` 切片基于 Unicode 码点，不会把常见中文字符切成半个字符。
    这里单独抽成函数，便于明确表达该意图并为后续回归测试提供稳定入口。
    """
    normalized = _safe_text(text)
    if len(normalized) <= max_length:
        return normalized
    return normalized[:max_length].rstrip()


def extract_weixin_text(message: Dict[str, Any]) -> str:
    """
    从微信消息结构中尽量提取可回复文本。

    兼容当前项目已经遇到的几类上游结构：
    - 顶层直接提供 `text` / `content`
    - `msg.text` / `msg.content`
    - `item_list[].text_item.text`
    """
    if not isinstance(message, dict):
        return ""

    direct_candidates = [
        message.get("text"),
        message.get("content"),
    ]
    nested_msg = message.get("msg")
    if isinstance(nested_msg, dict):
        direct_candidates.extend(
            [
                nested_msg.get("text"),
                nested_msg.get("content"),
            ]
        )

    for candidate in direct_candidates:
        text = _safe_text(candidate)
        if text:
            return text

    item_list = message.get("item_list")
    if not isinstance(item_list, list) and isinstance(nested_msg, dict):
        item_list = nested_msg.get("item_list")

    if isinstance(item_list, list):
        text_parts = []
        for item in item_list:
            if not isinstance(item, dict):
                continue
            text_item = item.get("text_item")
            if isinstance(text_item, dict):
                text = _safe_text(text_item.get("text"))
                if text:
                    text_parts.append(text)
                    continue
            text = _safe_text(item.get("text"))
            if text:
                text_parts.append(text)
        return "\n".join(part for part in text_parts if part).strip()

    return ""


def extract_weixin_multimedia(message: Dict[str, Any]) -> Dict[str, Any]:
    """
    从微信消息结构中提取多媒体信息。

    返回字典包含以下字段（缺失则为空）：
    - media_type: image/voice/file/video，无多媒体时为空字符串
    - media_id: 上游媒体资源 ID
    - file_url: 媒体文件 URL（图片/视频）
    - file_name: 文件名（文件消息）
    - file_size: 文件大小（字节）
    - duration_ms: 语音/视频时长（毫秒）
    - format: 媒体格式（如 amr/mp4/jpg）

    当消息不是多媒体消息时，返回 media_type 为空字符串的字典。
    """
    if not isinstance(message, dict):
        return {"media_type": ""}

    nested_msg = message.get("msg") if isinstance(message.get("msg"), dict) else message
    item_list = message.get("item_list")
    if not isinstance(item_list, list) and isinstance(nested_msg, dict):
        item_list = nested_msg.get("item_list")

    result: Dict[str, Any] = {
        "media_type": "",
        "media_id": "",
        "file_url": "",
        "file_name": "",
        "file_size": 0,
        "duration_ms": 0,
        "format": "",
    }

    # 顶层 message_type 字段优先识别
    top_type = _safe_text(message.get("message_type") or message.get("type"))
    if top_type in {MULTIMEDIA_TYPE_IMAGE, MULTIMEDIA_TYPE_VOICE, MULTIMEDIA_TYPE_FILE, MULTIMEDIA_TYPE_VIDEO}:
        result["media_type"] = top_type

    # 遍历 item_list 识别多媒体条目
    if isinstance(item_list, list):
        for item in item_list:
            if not isinstance(item, dict):
                continue
            item_type_raw = item.get("type")
            try:
                item_type_int = int(item_type_raw) if item_type_raw is not None else None
            except (TypeError, ValueError):
                item_type_int = None

            mapped = _ITEM_TYPE_TO_MULTIMEDIA.get(item_type_int) if item_type_int is not None else None
            if not result["media_type"] and mapped:
                result["media_type"] = mapped

            # 提取各类多媒体字段
            image_item = item.get("image_item") if isinstance(item.get("image_item"), dict) else {}
            voice_item = item.get("voice_item") if isinstance(item.get("voice_item"), dict) else {}
            file_item = item.get("file_item") if isinstance(item.get("file_item"), dict) else {}
            video_item = item.get("video_item") if isinstance(item.get("video_item"), dict) else {}

            if image_item:
                result["media_id"] = result["media_id"] or _safe_text(image_item.get("media_id") or image_item.get("md5"))
                result["file_url"] = result["file_url"] or _safe_text(image_item.get("url") or image_item.get("file_url"))
                result["format"] = result["format"] or _safe_text(image_item.get("format"))
            if voice_item:
                result["media_id"] = result["media_id"] or _safe_text(voice_item.get("media_id"))
                result["format"] = result["format"] or _safe_text(voice_item.get("format") or "amr")
                try:
                    result["duration_ms"] = int(voice_item.get("duration_ms") or voice_item.get("duration") or 0)
                except (TypeError, ValueError):
                    result["duration_ms"] = 0
            if file_item:
                result["media_id"] = result["media_id"] or _safe_text(file_item.get("media_id"))
                result["file_name"] = result["file_name"] or _safe_text(file_item.get("file_name") or file_item.get("name"))
                try:
                    result["file_size"] = int(file_item.get("file_size") or file_item.get("size") or 0)
                except (TypeError, ValueError):
                    result["file_size"] = 0
                result["format"] = result["format"] or _safe_text(file_item.get("format"))
            if video_item:
                result["media_id"] = result["media_id"] or _safe_text(video_item.get("media_id"))
                result["file_url"] = result["file_url"] or _safe_text(video_item.get("url") or video_item.get("file_url"))
                try:
                    result["duration_ms"] = result["duration_ms"] or int(video_item.get("duration_ms") or 0)
                except (TypeError, ValueError):
                    pass
                result["format"] = result["format"] or _safe_text(video_item.get("format") or "mp4")

    # 顶层字段兜底
    if not result["media_id"]:
        result["media_id"] = _safe_text(message.get("media_id") or nested_msg.get("media_id"))
    if not result["file_url"]:
        result["file_url"] = _safe_text(message.get("file_url") or nested_msg.get("file_url"))
    if not result["file_name"]:
        result["file_name"] = _safe_text(message.get("file_name") or nested_msg.get("file_name"))

    return result


def build_multimedia_description(multimedia: Dict[str, Any]) -> str:
    """
    根据多媒体信息生成可读的描述文本，用于注入 AI 上下文或日志展示。

    返回空字符串表示多媒体信息不可用。
    """
    media_type = _safe_text(multimedia.get("media_type"))
    if not media_type:
        return ""

    parts: List[str] = []
    if media_type == MULTIMEDIA_TYPE_IMAGE:
        parts.append("[图片消息]")
    elif media_type == MULTIMEDIA_TYPE_VOICE:
        parts.append("[语音消息]")
    elif media_type == MULTIMEDIA_TYPE_FILE:
        parts.append("[文件消息]")
    elif media_type == MULTIMEDIA_TYPE_VIDEO:
        parts.append("[视频消息]")

    file_name = _safe_text(multimedia.get("file_name"))
    if file_name:
        parts.append(f"文件名: {file_name}")
    file_size = int(multimedia.get("file_size") or 0)
    if file_size > 0:
        parts.append(f"大小: {file_size} 字节")
    duration_ms = int(multimedia.get("duration_ms") or 0)
    if duration_ms > 0:
        parts.append(f"时长: {duration_ms} 毫秒")
    media_format = _safe_text(multimedia.get("format"))
    if media_format:
        parts.append(f"格式: {media_format}")
    file_url = _safe_text(multimedia.get("file_url"))
    if file_url:
        parts.append(f"URL: {file_url}")

    return " ".join(parts)


def build_weixin_message_id(message: Dict[str, Any]) -> str:
    """
    构造稳定消息 ID。

    如果上游已经提供消息主键则直接使用；
    否则使用关键字段做哈希，确保同一条消息被重复拉取时仍能命中幂等去重。
    """
    if not isinstance(message, dict):
        return ""

    candidates = [
        message.get("message_id"),
        message.get("msg_id"),
        message.get("id"),
        message.get("client_id"),
    ]
    nested_msg = message.get("msg")
    if isinstance(nested_msg, dict):
        candidates.extend(
            [
                nested_msg.get("message_id"),
                nested_msg.get("msg_id"),
                nested_msg.get("id"),
                nested_msg.get("client_id"),
            ]
        )

    for candidate in candidates:
        normalized = _safe_text(candidate)
        if normalized:
            return normalized

    fingerprint_source = {
        "from_user_id": _safe_text(message.get("from_user_id")),
        "context_token": _safe_text(message.get("context_token")),
        "text": extract_weixin_text(message),
        "create_time": message.get("create_time"),
        "timestamp": message.get("timestamp"),
    }
    digest = hashlib.sha256(
        json.dumps(fingerprint_source, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"wxmsg-{digest[:32]}"


def sanitize_weixin_reply_text(text: str) -> str:
    """
    对微信渠道回复做最终清洗，确保不会把思维链或调试片段发送给终端用户。

    该函数只做保守过滤：
    - 去除常见 `<think>` / `<reasoning>` 包裹块
    - 去除显式 thinking/reasoning 代码块
    - 如果正文包含"最终答案/最终回复"等标记，则只保留最终结果部分
    - 删除明显的"思考过程/Reasoning"标题行
    """
    normalized = _safe_text(text).replace("\r\n", "\n")
    if not normalized:
        return ""

    normalized = _REASONING_BLOCK_RE.sub("", normalized)
    normalized = _REASONING_FENCE_RE.sub("", normalized)

    for marker in _FINAL_MARKERS:
        if marker in normalized:
            normalized = normalized.split(marker)[-1].strip()

    filtered_lines = []
    for line in normalized.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if any(lowered.startswith(prefix) for prefix in _REASONING_LINE_PREFIXES):
            continue
        filtered_lines.append(line)

    normalized = "\n".join(filtered_lines)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    return normalized


def build_weixin_reply_text(ai_result: Dict[str, Any], max_length: int = DEFAULT_MAX_REPLY_LENGTH) -> str:
    """
    从 AI 结果中提取微信最终可发送文本。

    即使模型返回了 `reasoning_content`，这里也只消费最终正文，并在必要时提供兜底文案。
    """
    candidate = ""
    if isinstance(ai_result, dict):
        candidate = _safe_text(
            ai_result.get("response")
            or ai_result.get("content")
            or ai_result.get("message")
        )

    cleaned = sanitize_weixin_reply_text(candidate)
    if not cleaned:
        cleaned = DEFAULT_AUTO_REPLY_FALLBACK_TEXT

    return _truncate_reply_text(cleaned, max_length)


def strip_reasoning_content(payload: Any) -> Any:
    """
    递归移除 `reasoning_content`，作为微信 final_only 的最后一道兜底。
    """
    if isinstance(payload, dict):
        return {
            key: strip_reasoning_content(value)
            for key, value in payload.items()
            if key != "reasoning_content"
        }
    if isinstance(payload, list):
        return [strip_reasoning_content(item) for item in payload]
    return payload


def normalize_inbound_message(message: Dict[str, Any]) -> Dict[str, Any]:
    """
    统一整理微信入站消息，方便后续做过滤、幂等和发送。

    多媒体消息（图片/语音/文件/视频）即使没有可回复文本也会被标记为 replyable，
    并附带 multimedia 字段供上层处理。
    """
    from_user_id = _safe_text(message.get("from_user_id"))
    context_token = _safe_text(message.get("context_token"))
    text = extract_weixin_text(message)
    message_id = build_weixin_message_id(message)
    message_type = _safe_text(message.get("message_type") or message.get("type"))
    multimedia = extract_weixin_multimedia(message)
    media_type = _safe_text(multimedia.get("media_type"))

    # 多媒体消息即使没有文本也允许回复，AI 可基于描述生成回复
    has_multimedia = bool(media_type)
    replyable = bool(from_user_id and context_token and (text or has_multimedia))
    skip_reason = ""
    if not from_user_id:
        skip_reason = "missing_from_user_id"
    elif not context_token:
        skip_reason = "missing_context_token"
    elif not text and not has_multimedia:
        skip_reason = "missing_text"

    return {
        "message_id": message_id,
        "from_user_id": from_user_id,
        "context_token": context_token,
        "text": text,
        "message_type": message_type or media_type,
        "multimedia": multimedia,
        "multimedia_description": build_multimedia_description(multimedia) if has_multimedia else "",
        "replyable": replyable,
        "skip_reason": skip_reason,
        "raw_message": dict(message),
    }


class WeixinAutoReplyService:
    """
    微信自动回复运行时服务。

    设计目标：
    1. 轮询游标只有在整批消息处理完成后才推进，避免"先移动游标、后发送失败"导致漏消息。
    2. 已处理消息持久化到本地状态文件，避免重复拉取时再次发送。
    3. AI 返回的思维链只允许留在内部结果，不允许进入微信下发文本。
    4. 跨渠道上下文：微信回复能引用主用户在 Web UI 中的对话历史。
    """

    def __init__(
        self,
        *,
        adapter: Optional[WeixinSkillAdapter] = None,
        session_factory: Optional[Callable[[], Session]] = None,
        ai_reply_generator: Optional[AutoReplyGenerator] = None,
        poll_interval_seconds: int = DEFAULT_AUTO_REPLY_POLL_INTERVAL_SECONDS,
        max_processed_messages: int = DEFAULT_MAX_PROCESSED_MESSAGES,
    ):
        self.adapter = adapter or WeixinSkillAdapter()
        self.session_factory = session_factory or SessionLocal
        self.ai_reply_generator = ai_reply_generator or self._default_ai_reply_generator
        self.poll_interval_seconds = max(1, int(poll_interval_seconds))
        self.max_processed_messages = max(20, int(max_processed_messages))
        self._tasks: Dict[str, asyncio.Task] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    async def start(self, user_id: str) -> Dict[str, Any]:
        """
        启动指定用户的自动回复后台轮询任务。
        已在运行时保持幂等，不重复创建任务。
        """
        user_key = _safe_text(user_id)
        runtime = self._load_runtime_or_raise(user_key)
        state = self._load_state(runtime.account_id)
        state["enabled"] = True
        state["last_state_change_at"] = _utcnow_iso()
        await self._save_state(runtime.account_id, state)

        task = self._tasks.get(user_key)
        if task and not task.done():
            return self.get_status(user_key)

        task = asyncio.create_task(
            self._run_loop(user_key),
            name=f"weixin-auto-reply-{user_key}",
        )
        self._tasks[user_key] = task
        task.add_done_callback(lambda _: self._tasks.pop(user_key, None))
        return self.get_status(user_key)

    async def stop(self, user_id: str) -> Dict[str, Any]:
        """
        停止指定用户的自动回复任务，并保留状态文件供诊断查看。
        """
        user_key = _safe_text(user_id)
        runtime = self._try_load_runtime(user_key)
        if runtime:
            state = self._load_state(runtime.account_id)
            state["enabled"] = False
            state["last_state_change_at"] = _utcnow_iso()
            await self._save_state(runtime.account_id, state)

        task = self._tasks.pop(user_key, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        return self.get_status(user_key)

    async def restart(self, user_id: str) -> Dict[str, Any]:
        """先停止再启动，便于用户在状态异常时做最小化恢复。"""
        await self.stop(user_id)
        return await self.start(user_id)

    def get_status(self, user_id: str) -> Dict[str, Any]:
        """
        返回当前用户的微信绑定状态与自动回复运行状态。
        """
        user_key = _safe_text(user_id)
        runtime = self._try_load_runtime(user_key)
        running = self.is_running(user_key)

        if not runtime:
            return {
                "user_id": user_key,
                "binding_status": "unbound",
                "binding_ready": False,
                "auto_reply_enabled": False,
                "auto_reply_running": running,
                "last_poll_at": "",
                "last_poll_status": "idle",
                "last_error": "",
                "last_error_at": "",
                "last_success_at": "",
                "last_reply_at": "",
                "last_replied_user_id": "",
                "last_processed_message_id": "",
                "cursor": "",
                "processed_message_count": 0,
            }

        state = self._load_state(runtime.account_id)
        return {
            "user_id": user_key,
            "binding_status": runtime.binding_status,
            "binding_ready": runtime.binding_status == "bound",
            "weixin_account_id": runtime.account_id,
            "weixin_user_id": runtime.user_id,
            "auto_reply_enabled": bool(state.get("enabled", False)),
            "auto_reply_running": running,
            "last_poll_at": _safe_text(state.get("last_poll_at")),
            "last_poll_status": _safe_text(state.get("last_poll_status")) or "idle",
            "last_error": _safe_text(state.get("last_error")),
            "last_error_at": _safe_text(state.get("last_error_at")),
            "last_success_at": _safe_text(state.get("last_success_at")),
            "last_reply_at": _safe_text(state.get("last_reply_at")),
            "last_replied_user_id": _safe_text(state.get("last_replied_user_id")),
            "last_processed_message_id": _safe_text(state.get("last_processed_message_id")),
            "cursor": self.adapter.load_cursor(runtime.account_id),
            "processed_message_count": len(self._get_processed_messages(state)),
        }

    def is_running(self, user_id: str) -> bool:
        """检查当前用户是否存在活跃后台任务。"""
        task = self._tasks.get(_safe_text(user_id))
        return bool(task and not task.done())

    async def process_once(self, user_id: str) -> Dict[str, Any]:
        """
        执行单次轮询和回复。

        该方法既供后台循环复用，也供测试或诊断接口显式调用。
        """
        user_key = _safe_text(user_id)
        lock = self._locks.get(user_key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[user_key] = lock
        async with lock:
            return await self._process_once_locked(user_key)

    async def _run_loop(self, user_id: str) -> None:
        """
        后台轮询主循环。

        循环内部即使遇到临时错误也不会直接退出，而是记录状态后继续下一轮，
        这样用户只需关注状态接口即可知道最近一次轮询是否失败。
        当检测到 token 过期或绑定状态变更时自动停止轮询。
        """
        while True:
            try:
                await self.process_once(user_id)
            except asyncio.CancelledError:
                raise
            except ValueError:
                logger.bind(
                    module="weixin.auto_reply",
                    user_id=user_id,
                ).info("weixin auto reply loop stopped due to binding state change")
                return
            except Exception as exc:
                logger.bind(
                    module="weixin.auto_reply",
                    user_id=user_id,
                    error_type=type(exc).__name__,
                ).exception("weixin auto reply loop failed")
            await asyncio.sleep(self.poll_interval_seconds)

    async def _process_once_locked(self, user_id: str) -> Dict[str, Any]:
        """在单用户串行锁内执行一次完整轮询。"""
        runtime = self._load_runtime_or_raise(user_id)
        now_iso = _utcnow_iso()
        state = self._load_state(runtime.account_id)

        logger.bind(
            module="weixin.auto_reply",
            user_id=user_id,
            account_id=runtime.account_id,
            phase="poll_start",
        ).info("开始拉取微信入站消息")

        try:
            updates = await self.adapter.get_updates(
                runtime,
                cursor=self.adapter.load_cursor(runtime.account_id),
                persist_cursor=False,
            )
        except WeixinAdapterError as exc:
            logger.bind(
                module="weixin.auto_reply",
                user_id=user_id,
                account_id=runtime.account_id,
                phase="poll_error",
                error_code=exc.code,
            ).warning(f"拉取消息失败: {exc.message}")
            state["last_poll_at"] = now_iso
            state["last_poll_status"] = "timeout" if exc.code == "WEIXIN_TIMEOUT" else "error"
            state["last_error"] = exc.message
            state["last_error_at"] = now_iso
            await self._save_state(runtime.account_id, state)
            if exc.code == "WEIXIN_TOKEN_EXPIRED":
                self._persist_binding_status(user_id, "expired", runtime.account_id)
            return {
                "ok": exc.code == "WEIXIN_TIMEOUT",
                "status": state["last_poll_status"],
                "processed": 0,
                "skipped": 0,
                "duplicates": 0,
                "errors": 1 if exc.code != "WEIXIN_TIMEOUT" else 0,
                "cursor_advanced": False,
                "error": exc.message,
            }

        raw_messages = updates.get("response", {}).get("msgs") or []
        next_cursor = _safe_text(updates.get("cursor"))

        logger.bind(
            module="weixin.auto_reply",
            user_id=user_id,
            account_id=runtime.account_id,
            phase="poll_received",
            message_count=len(raw_messages),
        ).info(f"收到 {len(raw_messages)} 条入站消息")

        processed_messages = self._get_processed_messages(state)
        sent_count = 0
        skipped_count = 0
        duplicate_count = 0
        error_count = 0
        poison_skipped_count = 0

        db = self.session_factory()
        try:
            binding = db.query(WeixinBinding).filter(WeixinBinding.user_id == user_id).first()
            if not binding:
                raise ValueError("未找到微信绑定记录")

            for raw_message in raw_messages:
                if not isinstance(raw_message, dict):
                    skipped_count += 1
                    continue

                inbound = normalize_inbound_message(raw_message)
                existing = processed_messages.get(inbound["message_id"])
                if existing and existing.get("status") == "sent":
                    duplicate_count += 1
                    continue

                if existing and existing.get("status") == "error":
                    retry_count = int(existing.get("retry_count", 0))
                    if retry_count >= DEFAULT_MAX_MESSAGE_PROCESS_RETRIES:
                        poison_skipped_count += 1
                        self._record_processed_message(
                            state,
                            inbound,
                            status="poison_skipped",
                            error=existing.get("error", "max retries exceeded"),
                        )
                        continue

                # 发布新消息事件到事件总线，供 WebSocket 实时推送
                await get_event_bus().publish(
                    user_id,
                    {
                        "event": "new_message",
                        "message_id": inbound["message_id"],
                        "from_user_id": inbound["from_user_id"],
                        "text": _truncate_text(inbound["text"], 200),
                        "message_type": inbound["message_type"],
                        "multimedia": inbound.get("multimedia") if inbound.get("multimedia", {}).get("media_type") else None,
                        "timestamp": now_iso,
                    },
                )

                if not inbound["replyable"]:
                    skipped_count += 1
                    self._record_processed_message(
                        state,
                        inbound,
                        status="skipped",
                        error=inbound["skip_reason"],
                    )
                    continue

                try:
                    logger.bind(
                        module="weixin.auto_reply",
                        user_id=user_id,
                        phase="ai_generate",
                        message_id=inbound["message_id"],
                        from_user_id=inbound["from_user_id"],
                    ).info("开始调用 AI 生成回复")

                    ai_result = await self.ai_reply_generator(db, binding, inbound)
                    reply_text = build_weixin_reply_text(ai_result)

                    logger.bind(
                        module="weixin.auto_reply",
                        user_id=user_id,
                        phase="send_reply",
                        message_id=inbound["message_id"],
                        reply_length=len(reply_text),
                    ).info("开始发送微信回复")

                    send_result = await self.adapter.send_text_message(
                        runtime,
                        {
                            "to_user_id": inbound["from_user_id"],
                            "context_token": inbound["context_token"],
                            "text": reply_text,
                        },
                    )
                    sent_count += 1
                    logger.bind(
                        module="weixin.auto_reply",
                        user_id=user_id,
                        phase="send_success",
                        message_id=inbound["message_id"],
                        to_user_id=inbound["from_user_id"],
                    ).info("微信回复发送成功")
                    state["last_reply_at"] = now_iso
                    state["last_replied_user_id"] = inbound["from_user_id"]
                    state["last_processed_message_id"] = inbound["message_id"]
                    self._record_processed_message(
                        state,
                        inbound,
                        status="sent",
                        reply_preview=reply_text,
                        send_result=send_result,
                    )
                except WeixinAdapterError as exc:
                    error_count += 1
                    if exc.code == "WEIXIN_TOKEN_EXPIRED":
                        self._persist_binding_status(user_id, "expired", runtime.account_id)
                    logger.bind(
                        module="weixin.auto_reply",
                        user_id=user_id,
                        phase="send_error",
                        message_id=inbound["message_id"],
                        error_code=exc.code,
                    ).error(f"消息处理/发送失败: {exc.message}")
                    state["last_error"] = str(exc.message)
                    state["last_error_at"] = now_iso
                    self._record_processed_message(
                        state,
                        inbound,
                        status="error",
                        error=exc.message,
                        retry_count=(int(existing.get("retry_count", 0)) + 1) if existing else 1,
                    )
                except Exception as exc:
                    error_count += 1
                    logger.bind(
                        module="weixin.auto_reply",
                        user_id=user_id,
                        phase="send_error",
                        message_id=inbound["message_id"],
                        error_type=type(exc).__name__,
                    ).error(f"消息处理/发送失败: {exc}")
                    state["last_error"] = str(exc)
                    state["last_error_at"] = now_iso
                    self._record_processed_message(
                        state,
                        inbound,
                        status="error",
                        error=str(exc),
                        retry_count=(int(existing.get("retry_count", 0)) + 1) if existing else 1,
                    )
        finally:
            db.close()

        cursor_advanced = error_count == 0
        if cursor_advanced and next_cursor:
            await self.adapter.save_cursor(runtime.account_id, next_cursor)

        state["last_poll_at"] = now_iso
        state["last_poll_status"] = "ok" if error_count == 0 else "partial_error"
        if sent_count > 0:
            state["last_success_at"] = now_iso
        if poison_skipped_count > 0:
            state["poison_skipped"] = state.get("poison_skipped", 0) + poison_skipped_count
        state["last_saved_cursor"] = self.adapter.load_cursor(runtime.account_id)
        await self._save_state(runtime.account_id, state)

        return {
            "ok": error_count == 0,
            "status": state["last_poll_status"],
            "processed": sent_count,
            "skipped": skipped_count,
            "duplicates": duplicate_count,
            "errors": error_count,
            "poison_skipped": poison_skipped_count,
            "cursor_advanced": cursor_advanced,
            "cursor": self.adapter.load_cursor(runtime.account_id),
        }

    # ──────────────────────────────────────────────
    #  跨渠道上下文集成
    # ──────────────────────────────────────────────

    @staticmethod
    def _load_main_user_recent_conversations(
        db: Session,
        user_id: str,
        max_turns: int = DEFAULT_CROSS_CHANNEL_CONTEXT_TURNS,
    ) -> List[Dict[str, str]]:
        """
        加载主用户在 Web UI 中的最近对话历史（排除微信渠道的会话），
        用于在生成微信回复时注入跨渠道上下文。
        """
        try:
            memories = (
                db.query(ShortTermMemory)
                .filter(
                    ShortTermMemory.role.in_(["user", "assistant"]),
                    ShortTermMemory.workspace_id == "default",
                )
                .order_by(ShortTermMemory.timestamp.desc())
                .limit(max_turns * 8)
                .all()
            )

            # 过滤掉微信渠道的 session，只保留主用户的 Web UI 对话
            web_conversations: List[Dict[str, str]] = []
            seen_session_ids: set = set()
            for mem in memories:
                sid = str(mem.session_id or "")
                if "weixin:" in sid:
                    continue
                if sid not in seen_session_ids:
                    seen_session_ids.add(sid)
                web_conversations.append({
                    "role": mem.role,
                    "content": str(mem.content or "")[:400],
                })
                if len(web_conversations) >= max_turns * 2:
                    break

            # 按时间正序排列
            web_conversations.reverse()
            return web_conversations
        except Exception as exc:
            logger.warning(f"[weixin] 加载主用户 Web 对话历史失败: {exc}")
            return []

    @staticmethod
    def _load_weixin_conversation_history(
        db: Session,
        session_id: str,
        max_turns: int = 20,
    ) -> List[Dict[str, str]]:
        """
        加载当前微信联系人的对话历史。
        """
        try:
            memories = (
                db.query(ShortTermMemory)
                .filter(
                    ShortTermMemory.session_id == session_id,
                    ShortTermMemory.role.in_(["user", "assistant"]),
                    ShortTermMemory.workspace_id == "default",
                )
                .order_by(ShortTermMemory.timestamp.desc())
                .limit(max_turns)
                .all()
            )
            history = []
            for mem in reversed(memories):
                history.append({
                    "role": mem.role,
                    "content": str(mem.content or "")[:400],
                })
            return history
        except Exception as exc:
            logger.warning(f"[weixin] 加载微信对话历史失败: {exc}")
            return []

    @staticmethod
    def _build_cross_channel_system_prompt(
        web_conversations: List[Dict[str, str]],
        weixin_conversations: List[Dict[str, str]],
        inbound_text: str,
    ) -> str:
        """
        构建跨渠道系统提示词，告知 AI 当前运行环境并注入必要的对话上下文。
        """
        lines: List[str] = []

        lines.append("你是 Open-AwA 平台的 AI Agent，当前通过微信渠道回复用户消息。")
        lines.append("平台使用者（你的主人）可能通过 Web UI 与你交互并设定过行为偏好。")
        lines.append("你需要基于主人的设定和微信对话的上下文，自然地回复微信联系人。")
        lines.append("回复应该简洁、自然，像一个真实的人在微信上聊天。")
        lines.append("")

        # 注入 Web UI 上下文
        if web_conversations:
            lines.append("=== 主用户在 Web UI 中的最近对话（供参考主人的偏好与设定） ===")
            for msg in web_conversations[:20]:
                role_label = "主人" if msg["role"] == "user" else "你"
                lines.append(f"[{role_label}]: {msg['content'][:300]}")
            lines.append("")

        # 注入微信联系人对话历史
        if weixin_conversations:
            lines.append("=== 与当前微信联系人的对话历史 ===")
            for msg in weixin_conversations[-10:]:
                role_label = "微信联系人" if msg["role"] == "user" else "你"
                lines.append(f"[{role_label}]: {msg['content'][:200]}")
            lines.append("")

        lines.append("当前微信联系人发来消息: " + inbound_text[:500])
        lines.append("")
        lines.append("请直接生成回复。不要输出 JSON、代码块、分析过程或调度指令。回复要像真人微信聊天一样自然。")

        return "\n".join(lines)

    async def _default_ai_reply_generator(
        self,
        db: Session,
        binding: WeixinBinding,
        inbound: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        默认回复生成入口：优先匹配用户定义的自动回复规则，如果无匹配再调用 AI。

        集成跨渠道上下文：
        1. 优先使用用户定义的自动回复规则
        2. 如果无匹配，加载主用户在 Web UI 中的最近对话 + 当前微信联系人对话历史
        3. 构建跨渠道系统提示词
        4. 调用 AI 生成回复，并记录到统一记忆系统
        """
        inbound_text = inbound.get("text", "").strip()
        weixin_session_id = f"weixin:auto:{binding.weixin_account_id}:{inbound['from_user_id']}"

        # 1. 规则匹配引擎 (Rule Engine)
        rules = db.query(WeixinAutoReplyRule).filter(
            WeixinAutoReplyRule.user_id == binding.user_id,
            WeixinAutoReplyRule.is_active == True
        ).order_by(WeixinAutoReplyRule.priority.desc(), WeixinAutoReplyRule.created_at.desc()).all()

        for rule in rules:
            if rule.match_type == "keyword":
                if rule.match_pattern in inbound_text:
                    logger.bind(
                        module="weixin.auto_reply",
                        user_id=binding.user_id,
                        rule_id=rule.id,
                        match_type="keyword"
                    ).info(f"触发关键词回复规则: {rule.rule_name}")
                    return {"response": rule.reply_content}
            elif rule.match_type == "regex":
                try:
                    if re.search(rule.match_pattern, inbound_text):
                        logger.bind(
                            module="weixin.auto_reply",
                            user_id=binding.user_id,
                            rule_id=rule.id,
                            match_type="regex"
                        ).info(f"触发正则回复规则: {rule.rule_name}")
                        return {"response": rule.reply_content}
                except re.error as e:
                    logger.warning(f"规则 {rule.id} 的正则表达式错误: {e}")

        # 2. 加载跨渠道上下文
        web_conversations = self._load_main_user_recent_conversations(db, binding.user_id)
        weixin_conversations = self._load_weixin_conversation_history(db, weixin_session_id)
        if web_conversations:
            logger.bind(
                module="weixin.auto_reply",
                user_id=binding.user_id,
                web_turns=len(web_conversations),
                weixin_turns=len(weixin_conversations),
            ).info("已加载跨渠道上下文")

        # 3. AI 回复生成 (Fallback) — 使用跨渠道上下文
        cross_channel_prompt = self._build_cross_channel_system_prompt(
            web_conversations, weixin_conversations, inbound_text
        )

        agent = AIAgent(db_session=db)
        context = {
            "user_id": binding.user_id,
            "username": f"weixin:{binding.weixin_account_id or binding.weixin_user_id or binding.user_id}",
            "session_id": weixin_session_id,
            "db": db,
            "channel": "weixin",
            "output_mode": "final_only",
            "suppress_reasoning": True,
            "message": cross_channel_prompt,
            "weixin_account_id": binding.weixin_account_id,
            "weixin_message_id": inbound["message_id"],
            "weixin_context_token": inbound["context_token"],
            "weixin_from_user_id": inbound["from_user_id"],
            # 启用记忆检索以利用长期记忆
            "retrieve_experiences": True,
            "retrieve_long_term_memory": True,
        }
        result = await agent.process(cross_channel_prompt, context)
        if isinstance(result, dict):
            return strip_reasoning_content(result)
        return {"response": _safe_text(result)}

    def clear_runtime_state(self, account_id: str) -> None:
        """解绑或切换账号后清理本地状态文件。"""
        self.adapter.clear_account_state(account_id)

    def _persist_binding_status(self, user_id: str, status: str, account_id: str) -> None:
        """将 binding_status 变更持久化到数据库，确保 token 过期等状态不会因内存刷新丢失。"""
        db = self.session_factory()
        try:
            binding = db.query(WeixinBinding).filter(WeixinBinding.user_id == user_id).first()
            if binding:
                binding.binding_status = status
                db.commit()
                logger.bind(
                    module="weixin.auto_reply",
                    user_id=user_id,
                    account_id=account_id,
                    new_status=status,
                ).info("weixin binding_status 已持久化")
        except Exception as exc:
            db.rollback()
            logger.bind(
                module="weixin.auto_reply",
                user_id=user_id,
            ).warning(f"持久化 binding_status 失败: {exc}")
        finally:
            db.close()

    def _try_load_runtime(self, user_id: str) -> Optional[WeixinRuntimeConfig]:
        """尝试读取微信绑定，找不到时返回 None。"""
        db = self.session_factory()
        try:
            return load_binding(db, user_id)
        finally:
            db.close()

    def _load_runtime_or_raise(self, user_id: str) -> WeixinRuntimeConfig:
        """读取绑定并校验是否已经达到可启动自动回复的状态。"""
        runtime = self._try_load_runtime(user_id)
        if not runtime or not runtime.account_id or not runtime.token:
            raise ValueError("请先完成微信绑定后再启动自动回复")
        if runtime.binding_status != "bound":
            raise ValueError("当前微信账号尚未处于已绑定状态，无法启动自动回复")
        return runtime

    def _load_state(self, account_id: str) -> Dict[str, Any]:
        """读取状态文件并补齐最小默认结构。"""
        state = self.adapter.load_auto_reply_state(account_id)
        if not isinstance(state, dict):
            state = {}
        state.setdefault("enabled", False)
        state.setdefault("processed_messages", {})
        state.setdefault("last_poll_status", "idle")
        return state

    async def _save_state(self, account_id: str, state: Dict[str, Any]) -> None:
        """保存状态前统一裁剪处理记录，防止状态文件无限膨胀。"""
        processed_messages = self._get_processed_messages(state)
        if len(processed_messages) > self.max_processed_messages:
            ordered_items = sorted(
                processed_messages.items(),
                key=lambda item: float(item[1].get("updated_at_ts", 0)),
            )
            processed_messages = dict(ordered_items[-self.max_processed_messages :])
        state["processed_messages"] = processed_messages
        await self.adapter.save_auto_reply_state(account_id, state)

    @staticmethod
    def _get_processed_messages(state: Dict[str, Any]) -> Dict[str, Any]:
        """从状态中提取消息幂等记录表。"""
        processed = state.get("processed_messages")
        if isinstance(processed, dict):
            return processed
        return {}

    def _record_processed_message(
        self,
        state: Dict[str, Any],
        inbound: Dict[str, Any],
        *,
        status: str,
        error: str = "",
        reply_preview: str = "",
        send_result: Optional[Dict[str, Any]] = None,
        retry_count: int = 0,
    ) -> None:
        """
        记录消息处理结果。

        这里的记录既承担诊断作用，也承担"同一消息不要再次回发"的幂等作用。
        """
        message_id = _safe_text(inbound.get("message_id"))
        if not message_id:
            return

        processed_messages = self._get_processed_messages(state)
        processed_messages[message_id] = {
            "status": status,
            "from_user_id": _safe_text(inbound.get("from_user_id")),
            "context_token": _safe_text(inbound.get("context_token")),
            "text_preview": _truncate_text(inbound.get("text"), max_length=120),
            "reply_preview": _truncate_text(reply_preview, max_length=120),
            "error": _truncate_text(error, max_length=200),
            "retry_count": retry_count,
            "updated_at": _utcnow_iso(),
            "updated_at_ts": datetime.now(timezone.utc).timestamp(),
            "send_request": (
                send_result.get("request", {}) if isinstance(send_result, dict) else {}
            ),
        }
        state["processed_messages"] = processed_messages


_AUTO_REPLY_MANAGER: WeixinAutoReplyService = WeixinAutoReplyService()
"""
全局自动回复管理器单例，用于在整个应用中共享同一个 WeixinAutoReplyService 实例。
位于服务层而非路由层，避免路由模块被 main.py 或其他模块导入时产生循环依赖。
"""


def get_auto_reply_manager() -> WeixinAutoReplyService:
    """集中管理自动回复单例，便于测试时替换。"""
    return _AUTO_REPLY_MANAGER

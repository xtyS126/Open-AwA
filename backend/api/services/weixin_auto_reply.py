"""
微信自动回复运行时服务。

该模块负责把“拉取微信入站消息 -> 调用 AI 生成回复 -> 清洗回复文本 -> 回发微信”
串成一个可重复调用、可持久化恢复的后端闭环。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from loguru import logger
from sqlalchemy.orm import Session

from core.agent import AIAgent
from db.models import SessionLocal, WeixinBinding, WeixinAutoReplyRule
from skills.weixin_skill_adapter import (
    WeixinAdapterError,
    WeixinRuntimeConfig,
    WeixinSkillAdapter,
    load_binding,
)


AutoReplyGenerator = Callable[[Session, WeixinBinding, Dict[str, Any]], Awaitable[Dict[str, Any]]]

DEFAULT_AUTO_REPLY_FALLBACK_TEXT = "我暂时无法生成合适的回复，请稍后再试。"
DEFAULT_AUTO_REPLY_POLL_INTERVAL_SECONDS = 3
DEFAULT_MAX_PROCESSED_MESSAGES = 500
DEFAULT_MAX_REPLY_LENGTH = 1000

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
    - 如果正文包含“最终答案/最终回复”等标记，则只保留最终结果部分
    - 删除明显的“思考过程/Reasoning”标题行
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
    """
    from_user_id = _safe_text(message.get("from_user_id"))
    context_token = _safe_text(message.get("context_token"))
    text = extract_weixin_text(message)
    message_id = build_weixin_message_id(message)
    message_type = _safe_text(message.get("message_type") or message.get("type"))
    replyable = bool(from_user_id and context_token and text)
    skip_reason = ""
    if not from_user_id:
        skip_reason = "missing_from_user_id"
    elif not context_token:
        skip_reason = "missing_context_token"
    elif not text:
        skip_reason = "missing_text"

    return {
        "message_id": message_id,
        "from_user_id": from_user_id,
        "context_token": context_token,
        "text": text,
        "message_type": message_type,
        "replyable": replyable,
        "skip_reason": skip_reason,
        "raw_message": dict(message),
    }


class WeixinAutoReplyService:
    """
    微信自动回复运行时服务。

    设计目标：
    1. 轮询游标只有在整批消息处理完成后才推进，避免“先移动游标、后发送失败”导致漏消息。
    2. 已处理消息持久化到本地状态文件，避免重复拉取时再次发送。
    3. AI 返回的思维链只允许留在内部结果，不允许进入微信下发文本。
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
        self._save_state(runtime.account_id, state)

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
            self._save_state(runtime.account_id, state)

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
        lock = self._locks.setdefault(user_key, asyncio.Lock())
        async with lock:
            return await self._process_once_locked(user_key)

    async def _run_loop(self, user_id: str) -> None:
        """
        后台轮询主循环。

        循环内部即使遇到临时错误也不会直接退出，而是记录状态后继续下一轮，
        这样用户只需关注状态接口即可知道最近一次轮询是否失败。
        """
        while True:
            try:
                await self.process_once(user_id)
            except asyncio.CancelledError:
                raise
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
            self._save_state(runtime.account_id, state)
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
                    )
        finally:
            db.close()

        cursor_advanced = error_count == 0
        if cursor_advanced and next_cursor:
            self.adapter.save_cursor(runtime.account_id, next_cursor)

        state["last_poll_at"] = now_iso
        state["last_poll_status"] = "ok" if error_count == 0 else "partial_error"
        if sent_count > 0:
            state["last_success_at"] = now_iso
        state["last_saved_cursor"] = self.adapter.load_cursor(runtime.account_id)
        self._save_state(runtime.account_id, state)

        return {
            "ok": error_count == 0,
            "status": state["last_poll_status"],
            "processed": sent_count,
            "skipped": skipped_count,
            "duplicates": duplicate_count,
            "errors": error_count,
            "cursor_advanced": cursor_advanced,
            "cursor": self.adapter.load_cursor(runtime.account_id),
        }

    async def _default_ai_reply_generator(
        self,
        db: Session,
        binding: WeixinBinding,
        inbound: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        默认回复生成入口：优先匹配用户定义的自动回复规则，如果无匹配再调用 AI。
        """
        inbound_text = inbound.get("text", "").strip()
        
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

        # 2. AI 回复生成 (Fallback)
        agent = AIAgent(db_session=db)
        context = {
            "user_id": binding.user_id,
            "username": f"weixin:{binding.weixin_account_id or binding.weixin_user_id or binding.user_id}",
            "session_id": f"weixin:auto:{binding.weixin_account_id}:{inbound['from_user_id']}",
            "db": db,
            "channel": "weixin",
            "output_mode": "final_only",
            "suppress_reasoning": True,
            "message": inbound_text,
            "weixin_account_id": binding.weixin_account_id,
            "weixin_message_id": inbound["message_id"],
            "weixin_context_token": inbound["context_token"],
            "weixin_from_user_id": inbound["from_user_id"],
        }
        result = await agent.process(inbound_text, context)
        if isinstance(result, dict):
            return strip_reasoning_content(result)
        return {"response": _safe_text(result)}

    def clear_runtime_state(self, account_id: str) -> None:
        """解绑或切换账号后清理本地状态文件。"""
        self.adapter.clear_account_state(account_id)

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

    def _save_state(self, account_id: str, state: Dict[str, Any]) -> None:
        """保存状态前统一裁剪处理记录，防止状态文件无限膨胀。"""
        processed_messages = self._get_processed_messages(state)
        if len(processed_messages) > self.max_processed_messages:
            ordered_items = sorted(
                processed_messages.items(),
                key=lambda item: float(item[1].get("updated_at_ts", 0)),
            )
            processed_messages = dict(ordered_items[-self.max_processed_messages :])
        state["processed_messages"] = processed_messages
        self.adapter.save_auto_reply_state(account_id, state)

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
    ) -> None:
        """
        记录消息处理结果。

        这里的记录既承担诊断作用，也承担“同一消息不要再次回发”的幂等作用。
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
            "updated_at": _utcnow_iso(),
            "updated_at_ts": datetime.now(timezone.utc).timestamp(),
            "send_request": (
                send_result.get("request", {}) if isinstance(send_result, dict) else {}
            ),
        }
        state["processed_messages"] = processed_messages

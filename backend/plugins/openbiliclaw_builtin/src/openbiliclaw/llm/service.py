"""prompt 组装与 LLM 执行的共享服务 facade。"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import logging
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, cast

from openbiliclaw.soul.profile import SoulProfile, preference_layer_from_dict
from openbiliclaw.soul.tone import ToneProfile, build_tone_profile

from .base import LLMProviderError, LLMRateLimitError
from .prompts import build_socratic_dialogue_prompt

logger = logging.getLogger(__name__)
DEFAULT_LLM_CONCURRENCY = 3

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from openbiliclaw.memory.manager import MemoryManager

    from .base import LLMResponse


class SupportsComplete(Protocol):
    """带 complete 方法的 provider 或 registry 的 Protocol。"""

    @property
    def default_provider(self) -> str: ...

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
        reasoning_effort: str | None = None,
    ) -> LLMResponse: ...

    async def complete_provider(
        self,
        provider_name: str,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
        reasoning_effort: str | None = None,
        model: str | None = None,
    ) -> LLMResponse: ...

    def is_chat_capable(self, name: str) -> bool: ...


class LLMServiceError(Exception):
    """服务层 LLM 错误的基类异常。"""


class LLMResponseContentError(LLMServiceError):
    """当 LLM 调用返回空内容时抛出。"""


class LLMProviderExecutionError(LLMServiceError):
    """当底层 provider 或 registry 调用失败时抛出。"""


_RATE_LIMIT_ERROR_MARKERS = (
    "rate limit",
    "429",
    "402",
    "cooling down",
    "too many requests",
    "resource exhausted",
    "quota exceeded",
    "payment required",
    "insufficient balance",
    "billing",
    "out of credit",
    "credit exhausted",
    "余额不足",
    "账户余额",
)


def is_llm_rate_limit_error(exc: BaseException) -> bool:
    """当异常链代表 provider 限流退避时返回 True。

    批量调用方用它来避免在 registry 已经在退避时，把一次 provider 限流
    事件炸成 N 个注定失败的逐项调用。
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, LLMRateLimitError):
            return True
        message = str(current).lower()
        if any(marker in message for marker in _RATE_LIMIT_ERROR_MARKERS):
            return True
        current = current.__cause__ or current.__context__
    return False


@dataclass(frozen=True)
class ModuleOverride:
    """按模块覆盖的 LLM 路由配置。"""

    provider: str = ""
    model: str = ""


_MODULE_OVERRIDE_BUCKETS = ("soul", "discovery", "recommendation", "evaluation")


def module_overrides_from_config(config: object) -> dict[str, ModuleOverride]:
    """从 ``Config.llm`` 各分块构建规范化的模块 LLM 覆盖配置。"""
    llm_config = getattr(config, "llm", None)
    if llm_config is None:
        return {}

    overrides: dict[str, ModuleOverride] = {}
    for bucket in _MODULE_OVERRIDE_BUCKETS:
        raw = getattr(llm_config, bucket, None)
        if raw is None:
            continue
        provider = str(getattr(raw, "provider", "") or "").strip().lower()
        model = str(getattr(raw, "model", "") or "").strip()
        if provider or model:
            overrides[bucket] = ModuleOverride(provider=provider, model=model)
    return overrides


class PrioritySemaphore:
    """按优先级顺序服务等待者的 asyncio 信号量。

    优先级数字越小越先获取（1 = 最高）。同一优先级桶内，通过单调递增的
    序列计数器保持 FIFO。信号量仅在有竞争时生效 —— 如果槽位空闲，调用
    方立即获取。

    并发受 ``capacity`` 限制：同时只有 ``capacity`` 个调用方能持有槽位。
    """

    def __init__(self, capacity: int = 1) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._capacity = capacity
        self._in_flight = 0
        # 堆条目：(priority, sequence, future)。序列计数器打破平局，
        # 让堆在同一桶内保持 FIFO。
        self._waiters: list[tuple[int, int, asyncio.Future[None]]] = []
        self._counter = itertools.count()

    async def acquire(self, priority: int) -> None:
        if self._in_flight < self._capacity and not self._waiters:
            self._in_flight += 1
            return
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[None] = loop.create_future()
        heapq.heappush(self._waiters, (priority, next(self._counter), fut))
        try:
            await fut
        except asyncio.CancelledError:
            # 如果还没被唤醒，把自己从堆里丢掉。
            self._waiters = [entry for entry in self._waiters if entry[2] is not fut]
            heapq.heapify(self._waiters)
            # 如果取消传播之前槽位已经交给我们，把它传给下一个等待者，
            # 避免队列死锁。
            if fut.done() and not fut.cancelled():
                self._release_one()
            raise

    def release(self) -> None:
        if self._in_flight <= 0:
            raise RuntimeError("PrioritySemaphore released too many times")
        self._release_one()

    def _release_one(self) -> None:
        # 把槽位交给最高优先级的等待者；若无人等待则只递减在飞计数。
        while self._waiters:
            _, _, fut = heapq.heappop(self._waiters)
            if not fut.done():
                fut.set_result(None)
                return
        self._in_flight = max(0, self._in_flight - 1)

    @asynccontextmanager
    async def slot(self, priority: int) -> AsyncIterator[None]:
        await self.acquire(priority)
        try:
            yield
        finally:
            self.release()


def _coerce_concurrency(value: object) -> int:
    """返回一个正数的 LLM 并发值，否则回退到默认值。"""
    if isinstance(value, bool):
        return DEFAULT_LLM_CONCURRENCY
    if isinstance(value, int | float):
        normalized = int(value)
    elif isinstance(value, str):
        try:
            normalized = int(value.strip())
        except ValueError:
            return DEFAULT_LLM_CONCURRENCY
    else:
        return DEFAULT_LLM_CONCURRENCY
    return normalized if normalized >= 1 else DEFAULT_LLM_CONCURRENCY


def _build_priority_semaphore(capacity: int = DEFAULT_LLM_CONCURRENCY) -> PrioritySemaphore:
    return PrioritySemaphore(capacity=_coerce_concurrency(capacity))


@dataclass
class LLMService:
    """组装 prompt 并把调用委托给 registry 的 facade。"""

    # v0.3.63+: 调用方标签 → 优先级映射。数字越小越优先。通过对传给
    # ``complete_with_core_memory`` 的 ``caller`` 标签做最长前缀匹配来
    # 解析。未打标签或未匹配的调用方回落到 ``_DEFAULT_PRIORITY``。意图：
    # 当系统处于负载下，弹窗可见的任务（write_expression、活跃 discovery
    # 批次的 evaluate_batch）应先于后台批量打分（delight_score）或冷路径
    # 的 soul/xhs 分析获得下一个 LLM 槽位。否则一次漫长的 delight 打分
    # 扫描可能让用户可见的表达回填饿死几分钟。
    _PRIORITY_MAP: ClassVar[dict[str, int]] = {
        "recommendation.write_expression": 1,
        "discovery.evaluate_batch": 1,
        "recommendation.delight_score": 2,
        "soul": 2,
        "xhs": 2,
    }
    _DEFAULT_PRIORITY: ClassVar[int] = 3
    _ROUTE_BUCKET_PREFIXES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("recommendation.delight_score", "evaluation"),
        ("recommendation.evaluate_batch", "evaluation"),
        ("discovery.evaluate", "evaluation"),
        ("discovery.eval", "evaluation"),
        ("eval", "evaluation"),
        ("discovery.search", "discovery"),
        ("discovery.explore", "discovery"),
        ("discovery.trending", "discovery"),
        ("discovery.related", "discovery"),
        ("yt_search", "discovery"),
        ("sources.xhs", "discovery"),
        ("recommendation", "recommendation"),
        ("soul", "soul"),
    )

    registry: SupportsComplete
    memory: MemoryManager
    # v0.3.26+: 可选的 usage 账本写入端。提供后，每次成功的 LLM 响应都会
    # 写入 ``llm_usage`` 表，``openbiliclaw cost`` 即可按日报告花费。
    # 默认 None 保留测试/独立调用方先前不关心成本追踪时的行为。
    usage_recorder: object | None = None
    module_overrides: Mapping[str, ModuleOverride] = field(default_factory=dict)
    concurrency: int = DEFAULT_LLM_CONCURRENCY
    # v0.3.63+: 懒初始化的优先级闸门。``init=False`` 让信号量保持私有，
    # 同时 ``concurrency`` 仍然可配置。
    _priority_sem: PrioritySemaphore = field(init=False, repr=False)
    _logged_unknown_override_keys: set[tuple[str, str]] = field(
        default_factory=set, init=False, repr=False
    )

    def __post_init__(self) -> None:
        self.concurrency = _coerce_concurrency(self.concurrency)
        self._priority_sem = _build_priority_semaphore(self.concurrency)

    @classmethod
    def _resolve_priority(cls, caller: str) -> int:
        """对 ``caller`` 与 ``_PRIORITY_MAP`` 做最长前缀匹配。

        ``"recommendation.write_expression"`` 完全匹配，而
        ``"soul.preference"`` 匹配 ``"soul"`` 前缀。未知调用方（或空标签）
        回落到 ``_DEFAULT_PRIORITY``。
        """
        if not caller:
            return cls._DEFAULT_PRIORITY
        best: tuple[int, int] | None = None  # (前缀长度, 优先级)
        for prefix, priority in cls._PRIORITY_MAP.items():
            if caller == prefix or caller.startswith(prefix + "."):
                length = len(prefix)
                if best is None or length > best[0]:
                    best = (length, priority)
        return best[1] if best is not None else cls._DEFAULT_PRIORITY

    @classmethod
    def _route_bucket_for_caller(cls, caller: str) -> str | None:
        """把具体 caller 标签映射到模块覆盖桶。"""
        tag = caller.strip()
        if not tag:
            return None
        for prefix, bucket in cls._ROUTE_BUCKET_PREFIXES:
            if cls._caller_matches_route_prefix(tag, prefix):
                return bucket
        return None

    @staticmethod
    def _caller_matches_route_prefix(caller: str, prefix: str) -> bool:
        return (
            caller == prefix or caller.startswith(prefix + ".") or caller.startswith(prefix + "_")
        )

    def _resolve_module_override(self, caller: str) -> tuple[str, str | None] | None:
        bucket = self._route_bucket_for_caller(caller)
        if bucket is None:
            return None
        override = self.module_overrides.get(bucket)
        if override is None:
            return None

        provider = override.provider.strip().lower()
        model = override.model.strip()
        if not provider and not model:
            return None
        if not provider:
            provider = self.registry.default_provider.strip().lower()
        if not provider:
            return None

        if not self.registry.is_chat_capable(provider):
            log_key = (bucket, provider)
            if log_key not in self._logged_unknown_override_keys:
                self._logged_unknown_override_keys.add(log_key)
                logger.info(
                    "LLM module override ignored: bucket=%s provider=%s "
                    "is not registered or chat-capable; using default provider.",
                    bucket,
                    provider,
                )
            return None
        return provider, model or None

    async def complete_with_core_memory(
        self,
        *,
        system_instruction: str,
        user_input: str,
        history: list[dict[str, str]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
        caller: str = "",
        reasoning_effort: str | None = None,
        bypass_semaphore: bool = False,
        inject_core_memory: bool = True,
    ) -> LLMResponse:
        """执行任务并自动注入 core memory 上下文。

        ``caller`` 是可选的自由格式标签（如 ``"soul.preference"``、
        ``"discovery.eval"``），附加到 usage 行上，``cost`` 报告即可按模块
        拆分花费。

        ``reasoning_effort``（v0.3.51+）让调用方为不会从思考中受益的任务
        （结构化 eval / classify / write-expression）强制禁用 provider 的
        思考模式。``None`` 保留 provider 默认；``""`` 表示此次调用显式禁用。

        ``bypass_semaphore``（v0.3.64+）完全跳过全局并发闸门。用于用户
        发起的交互式请求（如聊天对话），这些请求绝不能排在后台任务之后。

        ``inject_core_memory`` 让热路径评估器在已经在 ``user_input`` 中
        传入任务专属结构化画像时选择退出。这样可在不改变任务可用信息的
        前提下，保持 provider 端 prompt-cache 前缀稳定。
        """
        core_memory_block = ""
        if inject_core_memory and self.memory is not None:
            with suppress(Exception):
                core_memory_block = self.memory.render_core_memory_prompt()
        parts = [system_instruction.strip()]
        if core_memory_block:
            parts.append("以下是当前用户的 core memory，请作为理解背景：")
            parts.append(core_memory_block)
        system_content = "\n\n".join(parts)
        messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_input})
        priority = self._resolve_priority(caller)

        async def _do_llm_call() -> LLMResponse:
            routed = self._resolve_module_override(caller)
            if routed is None:
                return await self.registry.complete(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    reasoning_effort=reasoning_effort,
                )
            provider, model = routed
            return await self.registry.complete_provider(
                provider,
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
                reasoning_effort=reasoning_effort,
                model=model,
            )

        try:
            if bypass_semaphore:
                response = await _do_llm_call()
            else:
                async with self._priority_sem.slot(priority):
                    response = await _do_llm_call()
        except LLMProviderError as exc:
            raise LLMProviderExecutionError(str(exc)) from exc
        if not response.content.strip():
            raise LLMResponseContentError("LLM returned an empty response.")
        # 尽力而为的 usage 账本写入。recorder 自己吞掉异常，这样账单表
        # 出问题不会影响刚刚成功的 LLM 响应。
        recorder = self.usage_recorder
        if recorder is not None:
            record_fn = getattr(recorder, "record", None)
            if callable(record_fn):
                with suppress(Exception):
                    record_fn(response, caller=caller)
        return response

    async def complete_structured_task(
        self,
        *,
        system_instruction: str,
        user_input: str,
        history: list[dict[str, str]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        caller: str = "",
        reasoning_effort: str | None = None,
        inject_core_memory: bool = True,
    ) -> LLMResponse:
        """执行带 core memory 注入的 JSON 模式任务。

        ``reasoning_effort``（v0.3.51+）：传 ``""`` 为此次调用禁用 provider
        的思考模式。推荐用于不会从思维链中受益的结构化任务
        （eval / classify / write-expression）—— 在 DeepSeek-V4 上禁用可把
        30 项批量从 ~10 min 降到 ~30s。
        """
        return await self.complete_with_core_memory(
            system_instruction=system_instruction,
            user_input=user_input,
            history=history,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
            caller=caller,
            reasoning_effort=reasoning_effort,
            inject_core_memory=inject_core_memory,
        )

    def supports_image_input(self, caller: str = "discovery.evaluate_batch") -> bool:
        """尽力检查 OpenAI 兼容的视觉能力路由。"""
        routed = self._resolve_module_override(caller)
        provider_name = (
            routed[0] if routed is not None else self.registry.default_provider
        ).strip()
        provider_key = provider_name.lower()
        if provider_key not in {"openai", "openai_compatible", "openrouter"}:
            return False

        provider_obj: object | None = None
        get_provider = getattr(self.registry, "get", None)
        if callable(get_provider):
            with suppress(Exception):
                provider_obj = get_provider(provider_key)
        model = ""
        if routed is not None and routed[1]:
            model = routed[1]
        elif provider_obj is not None:
            model = str(getattr(provider_obj, "_model", "") or "")
        model_lower = model.lower()
        vision_markers = (
            "gpt-4o",
            "gpt-4.1",
            "gpt-5",
            "o3",
            "o4",
            "vision",
            "vl",
            "qwen-vl",
            "pixtral",
            "llava",
            "gemini",
            "claude-3",
            "claude-sonnet-4",
        )
        return any(marker in model_lower for marker in vision_markers)

    async def complete_multimodal_structured_task(
        self,
        *,
        system_instruction: str,
        user_input: str,
        image_inputs: list[dict[str, str]],
        history: list[dict[str, str]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        caller: str = "",
        reasoning_effort: str | None = None,
        inject_core_memory: bool = True,
    ) -> LLMResponse:
        """执行带用户文本和图像输入的 JSON 模式任务。"""
        core_memory_block = ""
        if inject_core_memory and self.memory is not None:
            with suppress(Exception):
                core_memory_block = self.memory.render_core_memory_prompt()
        parts = [system_instruction.strip()]
        if core_memory_block:
            parts.append("以下是当前用户的 core memory，请作为理解背景：")
            parts.append(core_memory_block)
        system_content = "\n\n".join(parts)

        user_parts: list[dict[str, Any]] = [{"type": "text", "text": user_input}]
        for image in image_inputs:
            content_id = str(image.get("content_id") or "").strip()
            data_url = str(image.get("data_url") or "").strip()
            if not content_id or not data_url:
                continue
            cover_ref = f"cover:{content_id}"
            user_parts.append(
                {
                    "type": "text",
                    "text": (
                        f"Cover image {cover_ref} maps to the content_batch item whose "
                        f"cover_image_ref is {cover_ref}."
                    ),
                }
            )
            user_parts.append({"type": "image_url", "image_url": {"url": data_url}})

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_content}]
        if history:
            messages.extend(cast("list[dict[str, Any]]", history))
        messages.append({"role": "user", "content": user_parts})
        priority = self._resolve_priority(caller)

        async def _do_llm_call() -> LLMResponse:
            routed = self._resolve_module_override(caller)
            if routed is None:
                return await self.registry.complete(
                    cast("Any", messages),
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=True,
                    reasoning_effort=reasoning_effort,
                )
            provider, model = routed
            return await self.registry.complete_provider(
                provider,
                cast("Any", messages),
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=True,
                reasoning_effort=reasoning_effort,
                model=model,
            )

        try:
            async with self._priority_sem.slot(priority):
                response = await _do_llm_call()
        except LLMProviderError as exc:
            raise LLMProviderExecutionError(str(exc)) from exc
        if not response.content.strip():
            raise LLMResponseContentError("LLM returned an empty response.")
        recorder = self.usage_recorder
        if recorder is not None:
            record_fn = getattr(recorder, "record", None)
            if callable(record_fn):
                with suppress(Exception):
                    record_fn(response, caller=caller)
        return response

    async def complete_with_tools(
        self,
        *,
        system_instruction: str,
        user_input: str,
        tools: list[dict[str, object]],
        history: list[dict[str, str]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        caller: str = "",
        bypass_semaphore: bool = False,
    ) -> LLMResponse:
        """执行可能包含工具/函数调用的补全。

        LLM 会收到一组工具定义。如果它决定调用工具，响应里会填好
        ``tool_calls``；否则 ``content`` 中是文本回复。

        本方法底层使用 JSON 模式：工具被序列化进 system prompt，模型被
        要求返回带 ``reply`` 或 ``tool_call`` 键的 JSON 包装。
        """
        tools_desc = "\n".join(f"- {t['name']}: {t.get('description', '')}" for t in tools)
        tool_names = [t["name"] for t in tools]
        augmented_system = (
            system_instruction + "\n\n"
            "<available_tools>\n" + tools_desc + "\n"
            "</available_tools>\n\n"
            "<tool_call_format>\n"
            "如果你需要调用工具，请返回如下 JSON（不要附带任何其他文字）：\n"
            '{"tool_call": {"name": "工具名", "arguments": {参数}}}\n'
            "如果不需要调用工具，正常回复用户即可（不要输出 JSON）。\n"
            "</tool_call_format>"
        )
        response = await self.complete_with_core_memory(
            system_instruction=augmented_system,
            user_input=user_input,
            history=history,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=False,
            caller=caller,
            bypass_semaphore=bypass_semaphore,
        )

        # 尝试从响应里解析工具调用
        import json

        content = (response.content or "").strip()
        if content.startswith("{"):
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict) and "tool_call" in parsed:
                    call = parsed["tool_call"]
                    if isinstance(call, dict) and call.get("name") in tool_names:
                        response.tool_calls = [call]
                        response.content = ""
            except (json.JSONDecodeError, TypeError):
                pass  # 不是合法 JSON —— 当作普通文本回复

        return response

    async def complete_socratic_dialogue(
        self,
        *,
        user_message: str,
        history: list[dict[str, str]],
        caller: str = "",
    ) -> LLMResponse:
        """使用 core memory 上下文生成苏格拉底式对话回复。"""
        tone_profile = self._build_dialogue_tone_profile()
        preference_raw = self.memory.get_layer("preference").data
        source_mix = preference_layer_from_dict(preference_raw).source_platform_mix
        prompt_messages = build_socratic_dialogue_prompt(
            user_message=user_message,
            core_memory_text="",
            tone_profile=tone_profile,
            history=[],
            source_platform_mix=source_mix or None,
        )
        return await self.complete_with_core_memory(
            system_instruction=prompt_messages[0]["content"],
            user_input=user_message,
            history=history,
            caller=caller,
            bypass_semaphore=True,
        )

    def _build_dialogue_tone_profile(self) -> ToneProfile:
        """从持久化 memory 推断对话用的语气画像。"""
        soul_raw = self.memory.get_layer("soul").data
        preference_raw = self.memory.get_layer("preference").data
        profile = None
        if soul_raw:
            profile = SoulProfile.from_dict(soul_raw)
            profile.preferences = preference_layer_from_dict(preference_raw)
        return build_tone_profile(
            profile=profile,
            preference_summary=self.memory.get_core_memory().get("preference_summary", {}),
            recent_feedback=[],
        )

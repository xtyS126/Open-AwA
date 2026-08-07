"""Token 计数策略模块

优先级：
1. API 响应 usage 字段（精确）
2. 流式 chunk 累计 usage
3. usage 缺失时显式标记 method=unknown（不估算伪装，由上层决策）

tiktoken（必需依赖）与字符比率估算函数作为显式工具保留，
由上层决定何时调用；计数失败一律显式传播，禁止静默返回 0 伪装。

设计参考 cherry-studio 的 MessageStats 字段定义，统一兼容 OpenAI 与 Anthropic 两种 usage 格式。
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import logging

logger = logging.getLogger(__name__)


@dataclass
class TokenBreakdown:
    """Token 计数明细

    字段对应 cherry-studio MessageStats 的 token 维度：
    - input_tokens: 输入 token（OpenAI prompt_tokens / Anthropic input_tokens）
    - output_tokens: 输出 token（OpenAI completion_tokens / Anthropic output_tokens）
    - cache_read_tokens: 命中 prompt cache 的输入 token
    - cache_write_tokens: 写入 prompt cache 的输入 token
    - thoughts_tokens: 推理 token（OpenAI reasoning_tokens / Anthropic thinking tokens）
    - method: 计数来源，取值为 api_usage | stream | tiktoken | ratio
    - estimated: 是否为估算值（api_usage 与 stream 为 False，tiktoken 与 ratio 为 True）
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    thoughts_tokens: int = 0
    method: str = "ratio"
    estimated: bool = True

    @property
    def total_tokens(self) -> int:
        """总 token 数 = 输入 + 输出"""
        return self.input_tokens + self.output_tokens


def _is_tiktoken_enabled() -> bool:
    """读取 settings.TIKTOKEN_ENABLED 配置项

    延迟 import 避免循环依赖。配置读取失败时显式传播异常，
    禁止静默默认开启/关闭（配置状态必须真实反映）。
    """
    from config.settings import settings  # 延迟 import，避免循环依赖

    return bool(getattr(settings, "TIKTOKEN_ENABLED", True))


def count_from_usage(usage: Optional[Dict[str, Any]]) -> TokenBreakdown:
    """从 API 响应 usage 字段解析 token 数

    兼容 OpenAI 与 Anthropic 两种格式：
    - OpenAI: prompt_tokens, completion_tokens, prompt_tokens_details.cached_tokens,
              completion_tokens_details.reasoning_tokens
    - Anthropic: input_tokens, output_tokens, cache_read_input_tokens,
                 cache_creation_input_tokens

    混合场景下两种字段都尝试读取，取到非 None 即纳入对应维度。

    Args:
        usage: API 响应中的 usage 字典，允许为 None 或空字典。

    Returns:
        TokenBreakdown，method=api_usage，estimated=False。
    """
    breakdown = TokenBreakdown(method="api_usage", estimated=False)
    if not isinstance(usage, dict) or not usage:
        return breakdown

    # 输入 token：OpenAI 用 prompt_tokens，Anthropic 用 input_tokens
    prompt_tokens = usage.get("prompt_tokens")
    input_tokens = usage.get("input_tokens")
    if isinstance(prompt_tokens, int):
        breakdown.input_tokens += prompt_tokens
    if isinstance(input_tokens, int):
        breakdown.input_tokens += input_tokens

    # 输出 token：OpenAI 用 completion_tokens，Anthropic 用 output_tokens
    completion_tokens = usage.get("completion_tokens")
    output_tokens = usage.get("output_tokens")
    if isinstance(completion_tokens, int):
        breakdown.output_tokens += completion_tokens
    if isinstance(output_tokens, int):
        breakdown.output_tokens += output_tokens

    # 缓存读取 token：OpenAI 在 prompt_tokens_details.cached_tokens，
    # Anthropic 在 cache_read_input_tokens
    prompt_details = usage.get("prompt_tokens_details")
    if isinstance(prompt_details, dict):
        cached = prompt_details.get("cached_tokens")
        if isinstance(cached, int):
            breakdown.cache_read_tokens += cached
    cache_read = usage.get("cache_read_input_tokens")
    if isinstance(cache_read, int):
        breakdown.cache_read_tokens += cache_read

    # 缓存写入 token：Anthropic 用 cache_creation_input_tokens
    cache_creation = usage.get("cache_creation_input_tokens")
    if isinstance(cache_creation, int):
        breakdown.cache_write_tokens += cache_creation

    # 推理 token：OpenAI 在 completion_tokens_details.reasoning_tokens
    completion_details = usage.get("completion_tokens_details")
    if isinstance(completion_details, dict):
        reasoning = completion_details.get("reasoning_tokens")
        if isinstance(reasoning, int):
            breakdown.thoughts_tokens += reasoning

    return breakdown


def count_from_stream(chunks: List[Dict[str, Any]]) -> TokenBreakdown:
    """累计流式 chunk 的 usage

    OpenAI: stream_options.include_usage=true 时，最后一个 chunk 的 usage 字段含完整用量
            （累积值），直接取最后一份即可。
    Anthropic: message_delta.usage 含累积 usage（不是增量），同样取最后一份覆盖。

    实现策略：遍历所有 chunk，记录最后一份含 usage 的 chunk，覆盖式取值。
    这样既能兼容 OpenAI 的最终 chunk，也能兼容 Anthropic 的 message_delta。

    Args:
        chunks: 流式响应中收集的 chunk 列表，每个 chunk 是 dict。

    Returns:
        TokenBreakdown，method=stream，estimated=False。
        若所有 chunk 均未携带 usage，返回零值 breakdown（仍标记 method=stream）。
    """
    breakdown = TokenBreakdown(method="stream", estimated=False)
    if not chunks:
        return breakdown

    last_usage: Optional[Dict[str, Any]] = None
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        usage = chunk.get("usage")
        if isinstance(usage, dict) and usage:
            last_usage = usage

    if last_usage is None:
        # 流中没有任何 usage 信息，返回零值（estimated 标记为 True 以便上层降级）
        breakdown.estimated = True
        return breakdown

    # 复用 count_from_usage 解析最后一份 usage
    parsed = count_from_usage(last_usage)
    breakdown.input_tokens = parsed.input_tokens
    breakdown.output_tokens = parsed.output_tokens
    breakdown.cache_read_tokens = parsed.cache_read_tokens
    breakdown.cache_write_tokens = parsed.cache_write_tokens
    breakdown.thoughts_tokens = parsed.thoughts_tokens
    return breakdown


def estimate_with_tiktoken(text: str, model: str) -> int:
    """tiktoken 估算，按 model 选 encoding

    encoding 选择：
    - o1/o3/o4/gpt-4o/gpt-4.1 系列 → o200k_base
    - gpt-4/gpt-4-turbo/gpt-3.5-turbo → cl100k_base
    - 其他 → o200k_base（默认）

    tiktoken 是必需依赖（requirements.txt 已声明），未安装或编码失败时
    显式传播异常，禁止静默返回 0 伪装估算结果。

    Args:
        text: 待估算的文本。
        model: 模型名称，用于选择 encoding。

    Returns:
        估算 token 数。文本为空或 TIKTOKEN_ENABLED=False 时返回 0。

    Raises:
        ImportError: tiktoken 未安装（必需依赖缺失）。
        Exception: tiktoken 编码失败（显式传播）。
    """
    if not text:
        return 0

    if not _is_tiktoken_enabled():
        logger.debug("tiktoken 已被 settings.TIKTOKEN_ENABLED 关闭，跳过估算")
        return 0

    import tiktoken  # 必需依赖，未安装时 ImportError 显式传播

    encoding_name = _resolve_encoding_name(model)
    encoding = tiktoken.get_encoding(encoding_name)
    return len(encoding.encode(text))


def _resolve_encoding_name(model: str) -> str:
    """根据模型名选择 tiktoken encoding

    Args:
        model: 模型名称（不区分大小写）。

    Returns:
        encoding 名称，o200k_base 或 cl100k_base。
    """
    normalized = (model or "").strip().lower()
    if not normalized:
        return "o200k_base"

    # o200k_base 覆盖：o1/o3/o4 推理系列、gpt-4o 系列、gpt-4.1 系列
    o200k_prefixes = (
        "o1",
        "o3",
        "o4",
        "gpt-4o",
        "gpt-4.1",
        "gpt-4.5",
    )
    for prefix in o200k_prefixes:
        if normalized.startswith(prefix):
            return "o200k_base"

    # cl100k_base 覆盖：gpt-4 / gpt-4-turbo / gpt-3.5-turbo
    cl100k_prefixes = (
        "gpt-4",
        "gpt-3.5-turbo",
        "gpt-35-turbo",
    )
    for prefix in cl100k_prefixes:
        if normalized.startswith(prefix):
            return "cl100k_base"

    # 默认使用 o200k_base（更新的 encoding，兼容性更好）
    return "o200k_base"


def estimate_with_ratio(text: str, provider: Optional[str] = None) -> int:
    """字符比率兜底，委托给现有 calculator.py

    Args:
        text: 待估算的文本。
        provider: 供应商名称，影响字符/token 比率。

    Returns:
        估算 token 数。
    """
    from billing.calculator import CostCalculator

    return CostCalculator.estimate_text_tokens(text, provider=provider)


def count_tokens(
    text: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    usage: Optional[Dict[str, Any]] = None,
    stream_chunks: Optional[List[Dict[str, Any]]] = None,
) -> TokenBreakdown:
    """统一入口，按优先级返回 TokenBreakdown

    优先级：
    1. usage 非 None → count_from_usage
    2. stream_chunks 携带 usage → count_from_stream
    3. usage 完全缺失 → method=unknown（不自动估算伪装）

    当 stream_chunks 提供但未携带 usage 时，显式标记 method=unknown，
    是否启用估算由上层决策（上层可显式调用 estimate_with_tiktoken /
    estimate_with_ratio 等工具函数）。

    Args:
        text: 待估算的文本（由上层决定是否用于估算）。
        provider: 供应商名称。
        model: 模型名称。
        usage: API 响应 usage 字段。
        stream_chunks: 流式 chunk 列表。

    Returns:
        TokenBreakdown。
    """
    # 1. API usage 优先（精确值）
    if usage is not None:
        return count_from_usage(usage)

    # 2. 流式 chunk usage（精确值，但可能未携带 usage）
    if stream_chunks:
        stream_breakdown = count_from_stream(stream_chunks)
        if not (
            stream_breakdown.estimated
            and stream_breakdown.input_tokens == 0
            and stream_breakdown.output_tokens == 0
        ):
            return stream_breakdown
        # 流中确实没有 usage：显式标记 unknown，由上层决策是否估算
        stream_breakdown.method = "unknown"
        return stream_breakdown

    # 3. usage 完全缺失：显式标记 unknown（不估算伪装），由上层决策
    return TokenBreakdown(method="unknown", estimated=True)

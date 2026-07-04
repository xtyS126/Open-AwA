"""按 provider / 按模型计的 token 定价（CNY）。

费率以 **CNY 每 1K tokens** 表示，列为 ``(input, output)``。
美元计价模型（OpenAI、Claude 等）已预先乘以近似汇率，因此整个定价面
是单一货币 —— 让每日花费报告更直观，避免把汇率换算埋在热路径里。
费率会漂移，因此结果视作估算（通常在实际计费的 ±20% 以内）。

来源说明（最后更新 2026-05）：

- DeepSeek：官方平台费率 (https://platform.deepseek.com/api-docs/pricing)
- OpenAI：API 价格页面 (https://openai.com/api/pricing) × USD/CNY ≈ 7.2
- Anthropic Claude：console 定价 × USD/CNY ≈ 7.2
- Gemini：AI Studio 定价 × USD/CNY ≈ 7.2
- OpenRouter：因路由而异；``default`` 费率是中位区间占位值。要精确的
  按路由追踪，请在调用点覆盖。
- Ollama：本地推理，视为免费。

**Prompt-cache 折扣**（v0.3.28+）：当部分输入 token 由 provider 侧
prompt cache 提供时，缓存部分按深度折扣计费。每个 provider 的
``CACHE_HIT_DISCOUNT`` 表示**乘数**，应用于缓存部分的输入费率：

- DeepSeek：0.10（9 折扣 —— 官方）
- OpenAI：0.50（约 5 折，2026 年家族范围；部分模型 0.25）
- Claude：0.10（9 折读取 —— Anthropic prompt-caching）
- Gemini：0.25（约 7.5 折，对应 Context Caching API 的
  cached_content_token_count）
- 其他：当未知 provider 报告缓存 token 时，保守假设 0.50

``estimate_cost(..., cached_tokens=N)`` 应用规则：``prompt_tokens`` 的
缓存部分按 ``input_rate * discount`` 计费，非缓存部分按完整
``input_rate``，output 不变。
"""

from __future__ import annotations

# 按 provider 的缓存命中折扣乘数。0.1 表示缓存 token 按完整输入费率的
# 10% 计费（即 9 折扣）。当 provider 不在此映射中时使用 0.5
# （保守 —— 半价）。
CACHE_HIT_DISCOUNT: dict[str, float] = {
    "deepseek": 0.10,
    "openai": 0.50,
    "claude": 0.10,
    "gemini": 0.25,
    "openrouter": 0.50,
    "ollama": 0.0,  # 本地；缓存与否，成本均为 0
}

# (input_rate, output_rate) —— CNY 每 1,000 token。
PRICING: dict[str, dict[str, tuple[float, float]]] = {
    "deepseek": {
        # ``deepseek-v4-flash`` 是项目默认值和当前主力模型。
        # ``deepseek-v4-pro`` 是更高一档的 V4 变体。遗留的 V3
        # ``deepseek-chat`` 和 R1 ``deepseek-reasoner`` 行保留，以便
        # 现有配置在那些模型到达 2026/07/24 弃用日期前仍能产出准确估算。
        "deepseek-v4-flash": (0.001, 0.002),
        "deepseek-v4-pro": (0.004, 0.012),
        "deepseek-chat": (0.0007, 0.0014),
        "deepseek-reasoner": (0.004, 0.016),
        "default": (0.001, 0.002),
    },
    "openai": {
        # USD × ~7.2（2024 后 USD/CNY）。GPT-5 家族为 2026-05 当前。
        # gpt-4o 家族已从 ChatGPT 退役但 API 仍可用。
        "gpt-5.5": (0.036, 0.216),  # $5/$30 per M
        "gpt-5.5-pro": (0.216, 1.296),  # $30/$180 per M
        "gpt-5.4-mini": (0.0054, 0.0324),  # $0.75/$4.5 per M
        "gpt-5.4-nano": (0.00144, 0.009),  # $0.20/$1.25 per M
        "gpt-5-nano": (0.00036, 0.00288),  # $0.05/$0.4 per M (最便宜)
        "gpt-4o": (0.018, 0.072),
        "gpt-4o-mini": (0.0011, 0.0043),
        "gpt-4-turbo": (0.072, 0.216),
        "text-embedding-3-small": (0.000144, 0.0),
        "text-embedding-3-large": (0.00094, 0.0),
        # OpenAI 兼容中转服务（Kimi / MiniMax / Qwen / GLM / Yi）在
        # 配置中都写 provider="openai" —— 在此列出几个常见模型名，
        # 让成本报告对它们仍然有用。
        "kimi-k2.6": (0.001, 0.004),
        "kimi-k2.5": (0.001, 0.004),
        "MiniMax-M2.7": (0.00216, 0.00864),  # $0.30/$1.20 per M
        "MiniMax-M2.5": (0.00216, 0.00864),
        "qwen-flash": (0.0003, 0.0009),
        "qwen-plus": (0.0008, 0.002),
        "qwen-max": (0.0024, 0.0096),
        "glm-4.7-flash": (0.0, 0.0),  # 免费层
        "glm-5": (0.005, 0.020),
        "yi-spark": (0.0001, 0.0001),
        "yi-medium": (0.0025, 0.0025),
        "yi-large": (0.02, 0.02),
        "default": (0.018, 0.072),
    },
    "claude": {
        # USD × 7.2；与 platform.claude.com 2026-05 定价一致。
        "claude-opus-4-7": (0.108, 0.540),  # $15/$75 per M (Opus 档)
        "claude-opus-4-6": (0.036, 0.180),  # $5/$25 per M
        "claude-sonnet-4-6": (0.0216, 0.108),  # $3/$15 per M
        "claude-sonnet-4-5": (0.0216, 0.108),
        "claude-haiku-4-5": (0.0054, 0.027),  # 便宜档
        "claude-sonnet-4-20250514": (0.022, 0.108),
        "claude-3-5-sonnet": (0.022, 0.108),
        "claude-3-haiku": (0.0018, 0.009),
        "default": (0.0216, 0.108),
    },
    "gemini": {
        # 2.5 系列稳定；3.x preview 档在 2026-05 仍在变动。
        # 3.1 Pro 当前仅 Public Preview —— 它在 Google API 上的真实
        # model id 是 "gemini-3.1-pro-preview"。两者都列出，让
        # estimate_cost 匹配 usage 日志中出现的那种拼写。
        "gemini-3.1-pro": (0.014, 0.056),
        "gemini-3.1-pro-preview": (0.014, 0.056),
        "gemini-3-pro-preview": (0.014, 0.056),
        "gemini-3-flash-preview": (0.0014, 0.0058),
        "gemini-3-flash": (0.0014, 0.0058),
        "gemini-3.1-flash-lite-preview": (0.00072, 0.0029),
        "gemini-2.5-flash": (0.0011, 0.0029),
        "gemini-2.5-pro": (0.009, 0.072),
        "gemini-embedding-001": (0.000108, 0.0),
        "default": (0.0011, 0.0029),
    },
    "openrouter": {
        # OpenRouter 路由差异巨大（从本地 Ollama 的"免费"中转到
        # GPT-4o 级别）。在不知道路由的情况下使用中位估算，让用户
        # 按调用覆盖。
        "default": (0.005, 0.015),
    },
    "ollama": {
        "default": (0.0, 0.0),
    },
}


def estimate_cost(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
) -> float:
    """估算单次 LLM 调用的 CNY 成本。

    当表中没有精确模型时回退到 provider 级 ``default`` 费率，再不行
    则回退到通用兜底 —— 这样未知模型仍会产出非零数字，而非悄然为 0。

    ``cached_tokens``（v0.3.28+）是 ``prompt_tokens`` 中由 provider 侧
    prompt cache 提供的部分；该部分按
    ``input_rate * CACHE_HIT_DISCOUNT[provider]`` 计费（通常为完整费率
    的 10-50%）。缓存未命中 / 未知时传 0（默认）。

    >>> estimate_cost("deepseek", "deepseek-v4-flash", 5000, 3000)
    0.011
    >>> estimate_cost("deepseek", "deepseek-v4-flash", 5000, 3000, cached_tokens=4000)
    0.0074
    >>> estimate_cost("ollama", "llama3", 10000, 5000)
    0.0
    """
    provider_rates = PRICING.get(provider, {})
    rates = provider_rates.get(model)
    if rates is None:
        rates = provider_rates.get("default")
    if rates is None:
        # 未知 provider —— 选一个中位费率，让用户在账单中注意到
        # 这个意外的 provider，而不是看到 0。
        rates = (0.001, 0.003)

    input_rate, output_rate = rates
    prompt_tokens = max(0, prompt_tokens)
    completion_tokens = max(0, completion_tokens)
    cached_tokens = max(0, min(cached_tokens, prompt_tokens))
    non_cached = prompt_tokens - cached_tokens

    discount = CACHE_HIT_DISCOUNT.get(provider, 0.5)
    return round(
        (non_cached / 1000.0) * input_rate
        + (cached_tokens / 1000.0) * input_rate * discount
        + (completion_tokens / 1000.0) * output_rate,
        6,
    )

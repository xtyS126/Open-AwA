"""把每次 LLM 调用的 usage 记录到数据库，用于成本追踪。

在每次 provider 响应成功后挂入 ``LLMService``。service 把
``LLMResponse``（其中带 provider 上报的 ``usage`` 字段）交给我们，我们
在 ``openbiliclaw.llm.pricing`` 中查价格档位，向 ``llm_usage`` 表追加
一行。``openbiliclaw cost`` 读回这张表做每日汇总。

失败在 ``record()`` 内部被刻意吞掉 —— 计费绝不能阻止一次成功的 LLM
响应到达调用方。

两个用于实时可观测性的旁路通道：

- 每次成功调用打一条 INFO 日志：
  ``[llm-cost] caller=discovery.evaluate model=deepseek-v4-flash 850→230 tok ≈ ¥0.0010``
  让你可以 ``tail -f`` 守护进程日志实时看到成本流入。
- 当*单次*调用超过 ``EXPENSIVE_CALL_CNY_THRESHOLD``（默认 ¥0.10）时打
  WARN 日志。用来捕捉失控的 prompt（不然一次 32K-token 的推理调用会
  静默花掉 ~¥0.5）。
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Protocol

from openbiliclaw.llm.pricing import estimate_cost

if TYPE_CHECKING:
    from openbiliclaw.llm.base import LLMResponse

logger = logging.getLogger(__name__)

# 单次调用超过即打 WARN 的阈值。大多数合法的 OpenBiliClaw 调用成本
# <¥0.01；¥0.10 约是其 10 倍，远高于任何预期的单次调用成本，进入
# "出问题了"区间。如果部署有意跑更高质量模型（仅 Opus 4.7 在长 prompt
# 上就可能超阈值），可通过环境变量覆盖。
_EXPENSIVE_THRESHOLD_DEFAULT = 0.10
EXPENSIVE_CALL_CNY_THRESHOLD = float(
    os.environ.get("OPENBILICLAW_LLM_EXPENSIVE_CNY", _EXPENSIVE_THRESHOLD_DEFAULT)
)


class _UsageSink(Protocol):
    """recorder 从类数据库对象所需的最小契约。"""

    def insert_llm_usage(
        self,
        *,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        estimated_cost_cny: float,
        caller: str = "",
        success: bool = True,
        cached_input_tokens: int = 0,
    ) -> int: ...


class UsageRecorder:
    """向 LLM 账本追加每次调用的 usage 行。

    每进程构造一次（通常由 ``runtime_context`` 负责），传入
    ``LLMService``。每次响应时 service 调用 ``record()`` —— recorder 从
    响应的 ``usage`` dict 里取出 token 计数，通过 ``pricing`` 估算成本，
    追加一行。
    """

    def __init__(self, sink: _UsageSink | None) -> None:
        self._sink = sink

    @property
    def enabled(self) -> bool:
        return self._sink is not None

    def record(
        self,
        response: LLMResponse | None,
        *,
        caller: str = "",
    ) -> None:
        """为一次 LLM 响应持久化 usage 行。

        ``response`` 可能为 None（退化路径）—— 我们静默 no-op 而非抛出，
        因为调用方在热路径上。
        """
        if response is None:
            return

        usage = getattr(response, "usage", None) or {}
        provider = str(getattr(response, "provider", "") or "").strip().lower()
        model = str(getattr(response, "model", "") or "").strip()

        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        # 规范化的缓存字段 —— 当 provider 后端从 prompt cache 服务部分输入
        # token 时填入。``cached_input_tokens`` 始终 <= prompt_tokens。
        # 参见 openai_provider.py / claude_provider.py / gemini_provider.py
        # 中的 provider 文档。
        cached_tokens = int(usage.get("cached_input_tokens", 0) or 0)

        try:
            cost = estimate_cost(
                provider,
                model,
                prompt_tokens,
                completion_tokens,
                cached_tokens=cached_tokens,
            )
        except Exception:
            logger.debug("estimate_cost failed", exc_info=True)
            return

        # 实时 INFO 日志，让 `journalctl -fu openbiliclaw` / `docker logs -f`
        # 能看到成本累计。未打标签时 caller 默认为 "?"，让日志读起来一致。
        # 命中时附上缓存命中率，便于发现污染 prompt 前缀的构造器。
        caller_tag = caller or "?"
        cache_note = ""
        if cached_tokens > 0 and prompt_tokens > 0:
            hit = cached_tokens / prompt_tokens * 100
            cache_note = f" cache_hit={cached_tokens}/{prompt_tokens} ({hit:.0f}%)"
        logger.info(
            "[llm-cost] caller=%s model=%s tokens=%d→%d ≈ ¥%.4f%s",
            caller_tag,
            model or "(unknown)",
            prompt_tokens,
            completion_tokens,
            cost,
            cache_note,
        )

        # 异常 WARN —— 单次调用超阈值几乎总是失控的 prompt（忘了截断
        # 历史、批量过大、误开推理预算等）。值得大声记录，让人在 ¥¥ 累积
        # 之前注意到。
        if cost >= EXPENSIVE_CALL_CNY_THRESHOLD:
            logger.warning(
                "[llm-cost] expensive single call: caller=%s model=%s "
                "%d→%d tokens ≈ ¥%.4f (threshold ¥%.2f, override via "
                "OPENBILICLAW_LLM_EXPENSIVE_CNY)",
                caller_tag,
                model or "(unknown)",
                prompt_tokens,
                completion_tokens,
                cost,
                EXPENSIVE_CALL_CNY_THRESHOLD,
            )

        if self._sink is None:
            return

        try:
            self._sink.insert_llm_usage(
                provider=provider or "unknown",
                model=model or "",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cached_input_tokens=cached_tokens,
                estimated_cost_cny=cost,
                caller=caller,
                success=True,
            )
        except Exception:
            # 绝不让账单表写入阻塞 LLM 热路径。最坏情况：漏掉一行部分
            # 数据；账本漂移 ~0.1%。
            logger.debug("UsageRecorder.record failed", exc_info=True)

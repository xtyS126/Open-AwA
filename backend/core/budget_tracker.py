"""
预算追踪模块 — 追踪 Agent 主循环中的 token 使用量。

BudgetTracker 是纯数据类，不涉及 LLM 调用，仅负责累计 token 用量并提供
预算耗尽判断，供 AIAgent 状态机在每轮 LLM 调用后查询。
"""

from dataclasses import dataclass, field


# 预算即将耗尽的使用率阈值（90%）
_BUDGET_NEAR_COMPLETION_RATIO = 0.9
# 剩余预算不足的绝对值阈值（500 tokens）
_BUDGET_DIMINISHING_REMAINING = 500


@dataclass
class BudgetTracker:
    """
    追踪 token 使用量的预算追踪器。

    总预算 = max_input_tokens + max_output_tokens
    总使用量 = input_tokens + output_tokens + cache_read_tokens + cache_write_tokens

    通过 is_near_completion() 判断使用率是否达到阈值（用于状态机退出），
    通过 is_diminishing() 判断剩余预算是否过低（用于提前告警/降级）。
    """

    # 输入 token 预算上限
    max_input_tokens: int = 100_000
    # 输出 token 预算上限
    max_output_tokens: int = 16_384

    # 已使用的输入 token 数（非缓存部分）
    _input_tokens: int = field(init=False, default=0)
    # 已使用的输出 token 数
    _output_tokens: int = field(init=False, default=0)
    # 已读取的缓存 token 数
    _cache_read_tokens: int = field(init=False, default=0)
    # 已写入的缓存 token 数
    _cache_write_tokens: int = field(init=False, default=0)

    def record_usage(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read: int = 0,
        cache_write: int = 0,
    ) -> None:
        """
        记录一次 LLM 调用的 token 使用量，累加到内部计数器。

        参数:
            input_tokens: 非缓存的输入 token 数
            output_tokens: 输出 token 数
            cache_read: 缓存读取的 token 数
            cache_write: 缓存写入的 token 数
        """
        self._input_tokens += max(0, int(input_tokens))
        self._output_tokens += max(0, int(output_tokens))
        self._cache_read_tokens += max(0, int(cache_read))
        self._cache_write_tokens += max(0, int(cache_write))

    def total_used(self) -> int:
        """返回累计的总 token 使用量。"""
        return (
            self._input_tokens
            + self._output_tokens
            + self._cache_read_tokens
            + self._cache_write_tokens
        )

    def remaining(self) -> int:
        """返回剩余预算，最小为 0。"""
        return max(0, self._total_budget() - self.total_used())

    def reset(self) -> None:
        """重置所有 token 计数器为 0，保留预算上限配置。"""
        self._input_tokens = 0
        self._output_tokens = 0
        self._cache_read_tokens = 0
        self._cache_write_tokens = 0

    def usage_ratio(self) -> float:
        """
        返回当前使用率（0.0-1.0）。

        总预算为 0 时返回 0.0，避免除零错误。
        """
        budget = self._total_budget()
        if budget <= 0:
            return 0.0
        return self.total_used() / budget

    def is_near_completion(self) -> bool:
        """
        判断使用率是否已达到或超过完成阈值（>= 90%）。

        用于状态机决定是否提前退出主循环。
        """
        return self.usage_ratio() >= _BUDGET_NEAR_COMPLETION_RATIO

    def is_diminishing(self) -> bool:
        """
        判断剩余预算是否已低于告警阈值（< 500 tokens）。

        用于提前告警或触发降级策略，与 is_near_completion 独立。
        """
        return self.remaining() < _BUDGET_DIMINISHING_REMAINING

    def _total_budget(self) -> int:
        """返回总预算（输入 + 输出上限之和）。"""
        return self.max_input_tokens + self.max_output_tokens

"""
BudgetTracker 单元测试。
覆盖初始状态、记录使用量、总使用量计算、剩余预算计算、
使用率阈值判断、重置等全部方法。
"""

import pytest

from core.budget_tracker import BudgetTracker


# ==================== 初始状态测试 ====================


class TestBudgetTrackerInitialState:
    """验证 BudgetTracker 的初始状态。"""

    def test_budget_tracker_initial_state(self):
        """新建的 BudgetTracker 应使用默认预算上限且所有计数器为 0。"""
        tracker = BudgetTracker()

        assert tracker.max_input_tokens == 100_000
        assert tracker.max_output_tokens == 16_384
        assert tracker.total_used() == 0
        assert tracker.remaining() == 100_000 + 16_384
        assert tracker.usage_ratio() == 0.0
        assert tracker.is_near_completion() is False
        assert tracker.is_diminishing() is False

    def test_budget_tracker_custom_limits(self):
        """应支持自定义预算上限。"""
        tracker = BudgetTracker(max_input_tokens=1000, max_output_tokens=500)

        assert tracker.max_input_tokens == 1000
        assert tracker.max_output_tokens == 500
        assert tracker.remaining() == 1500


# ==================== 记录使用量测试 ====================


class TestRecordUsage:
    """验证 record_usage 方法。"""

    def test_record_usage(self):
        """record_usage 应将传入的 token 数累加到对应计数器。"""
        tracker = BudgetTracker()

        tracker.record_usage(
            input_tokens=100,
            output_tokens=50,
            cache_read=20,
            cache_write=10,
        )

        assert tracker.total_used() == 180

    def test_record_usage_accumulates(self):
        """多次调用 record_usage 应累加而非覆盖。"""
        tracker = BudgetTracker()

        tracker.record_usage(input_tokens=100, output_tokens=50)
        tracker.record_usage(input_tokens=200, output_tokens=100)
        tracker.record_usage(cache_read=30, cache_write=20)

        assert tracker.total_used() == 500

    def test_record_usage_default_zero(self):
        """不传参数时 record_usage 不应改变计数器。"""
        tracker = BudgetTracker()

        tracker.record_usage()

        assert tracker.total_used() == 0

    def test_record_usage_negative_clamped_to_zero(self):
        """负数 token 数应被钳制为 0，避免计数器回退。"""
        tracker = BudgetTracker()

        tracker.record_usage(input_tokens=-100, output_tokens=-50)

        assert tracker.total_used() == 0


# ==================== 总使用量计算测试 ====================


class TestTotalUsed:
    """验证 total_used 方法。"""

    def test_total_used(self):
        """total_used 应返回所有 token 计数器之和。"""
        tracker = BudgetTracker()

        tracker.record_usage(
            input_tokens=1000,
            output_tokens=500,
            cache_read=200,
            cache_write=100,
        )

        assert tracker.total_used() == 1800

    def test_total_used_initial_zero(self):
        """初始状态 total_used 应为 0。"""
        tracker = BudgetTracker()

        assert tracker.total_used() == 0


# ==================== 剩余预算计算测试 ====================


class TestRemaining:
    """验证 remaining 方法。"""

    def test_remaining(self):
        """remaining 应返回总预算减去已使用量。"""
        tracker = BudgetTracker(max_input_tokens=1000, max_output_tokens=500)

        tracker.record_usage(input_tokens=300, output_tokens=200)

        assert tracker.remaining() == 1000

    def test_remaining_never_negative(self):
        """使用量超过预算时 remaining 应返回 0 而非负数。"""
        tracker = BudgetTracker(max_input_tokens=100, max_output_tokens=50)

        tracker.record_usage(input_tokens=200, output_tokens=100)

        assert tracker.remaining() == 0

    def test_remaining_initial_full(self):
        """初始状态 remaining 应等于总预算。"""
        tracker = BudgetTracker(max_input_tokens=1000, max_output_tokens=500)

        assert tracker.remaining() == 1500


# ==================== is_near_completion 阈值测试 ====================


class TestIsNearCompletion:
    """验证 is_near_completion 方法的阈值判断。"""

    def test_is_near_completion_below_threshold(self):
        """使用率 < 90% 时应返回 False。"""
        tracker = BudgetTracker(max_input_tokens=1000, max_output_tokens=0)

        # 使用 899，使用率 = 899/1000 = 0.899 < 0.9
        tracker.record_usage(input_tokens=899)

        assert tracker.usage_ratio() < 0.9
        assert tracker.is_near_completion() is False

    def test_is_near_completion_at_threshold(self):
        """使用率 >= 90% 时应返回 True。"""
        tracker = BudgetTracker(max_input_tokens=1000, max_output_tokens=0)

        # 使用 900，使用率 = 900/1000 = 0.9 >= 0.9
        tracker.record_usage(input_tokens=900)

        assert tracker.usage_ratio() >= 0.9
        assert tracker.is_near_completion() is True

    def test_is_near_completion_above_threshold(self):
        """使用率远超 90% 时应返回 True。"""
        tracker = BudgetTracker(max_input_tokens=1000, max_output_tokens=0)

        tracker.record_usage(input_tokens=950)

        assert tracker.is_near_completion() is True

    def test_is_near_completion_full_consumed(self):
        """预算完全耗尽时应返回 True。"""
        tracker = BudgetTracker(max_input_tokens=1000, max_output_tokens=500)

        tracker.record_usage(input_tokens=1000, output_tokens=500)

        assert tracker.is_near_completion() is True


# ==================== set_model_context_window 测试 ====================


class TestSetModelContextWindow:
    """验证按模型注入上下文窗口后预算分母与模型一致。"""

    def test_set_model_context_window_updates_budget(self):
        """set_model_context_window 应更新输入/输出预算上限（分母）。"""
        tracker = BudgetTracker()

        tracker.set_model_context_window(max_input_tokens=200_000, max_output_tokens=8_192)

        assert tracker.max_input_tokens == 200_000
        assert tracker.max_output_tokens == 8_192
        assert tracker.remaining() == 200_000 + 8_192

    def test_set_model_context_window_negative_clamped_to_zero(self):
        """负数上下文窗口应被钳制为 0，避免预算出现负分母。"""
        tracker = BudgetTracker()

        tracker.set_model_context_window(max_input_tokens=-100, max_output_tokens=-50)

        assert tracker.max_input_tokens == 0
        assert tracker.max_output_tokens == 0
        assert tracker.remaining() == 0

    def test_set_model_context_window_preserves_usage(self):
        """重设上下文窗口不应清空已记录的 usage。"""
        tracker = BudgetTracker(max_input_tokens=1000, max_output_tokens=500)
        tracker.record_usage(input_tokens=100, output_tokens=50)

        tracker.set_model_context_window(max_input_tokens=2000, max_output_tokens=1000)

        assert tracker.total_used() == 150
        assert tracker.remaining() == 3000 - 150


# ==================== is_diminishing 收益递减测试 ====================


class TestIsDiminishing:
    """验证 is_diminishing 的收益递减语义：

    continuationCount >= 3 且最近两轮增量均 < 500 token 时判定收益递减。
    """

    def test_is_diminishing_false_when_insufficient_rounds(self):
        """续写轮数不足 3 轮时应返回 False。"""
        tracker = BudgetTracker(max_input_tokens=100_000, max_output_tokens=16_384)

        tracker.record_usage(input_tokens=100, output_tokens=50)
        tracker.record_usage(input_tokens=100, output_tokens=50)

        assert tracker.is_diminishing() is False

    def test_is_diminishing_false_when_recent_increments_large(self):
        """最近两轮增量 >= 500 时应返回 False。"""
        tracker = BudgetTracker(max_input_tokens=100_000, max_output_tokens=16_384)

        tracker.record_usage(input_tokens=1000, output_tokens=1000)
        tracker.record_usage(input_tokens=1000, output_tokens=1000)
        tracker.record_usage(input_tokens=1000, output_tokens=1000)

        assert tracker.is_diminishing() is False

    def test_is_diminishing_true_when_recent_increments_small(self):
        """连续 3 轮且最近两轮增量 < 500 时应返回 True。"""
        tracker = BudgetTracker(max_input_tokens=100_000, max_output_tokens=16_384)

        tracker.record_usage(input_tokens=1000, output_tokens=1000)
        tracker.record_usage(input_tokens=100, output_tokens=100)
        tracker.record_usage(input_tokens=100, output_tokens=100)

        assert tracker.is_diminishing() is True

    def test_is_diminishing_boundary_increment_equal_500(self):
        """增量恰好等于 500 时不满足 < 500，应返回 False（边界值）。"""
        tracker = BudgetTracker(max_input_tokens=100_000, max_output_tokens=16_384)

        tracker.record_usage(input_tokens=1000, output_tokens=0)
        tracker.record_usage(input_tokens=500, output_tokens=0)
        tracker.record_usage(input_tokens=500, output_tokens=0)

        assert tracker.is_diminishing() is False

    def test_is_diminishing_reset_clears_history(self):
        """reset 应清空增量历史，is_diminishing 回到 False。"""
        tracker = BudgetTracker(max_input_tokens=100_000, max_output_tokens=16_384)

        tracker.record_usage(input_tokens=1000, output_tokens=1000)
        tracker.record_usage(input_tokens=100, output_tokens=100)
        tracker.record_usage(input_tokens=100, output_tokens=100)
        assert tracker.is_diminishing() is True

        tracker.reset()

        assert tracker.is_diminishing() is False

    def test_mark_progress_clears_diminishing_window(self):
        """工具调用等有进展的轮次调用 mark_progress 后应清除递减窗口。"""
        tracker = BudgetTracker(max_input_tokens=100_000, max_output_tokens=16_384)

        tracker.record_usage(input_tokens=1000, output_tokens=1000)
        tracker.record_usage(input_tokens=100, output_tokens=100)
        tracker.record_usage(input_tokens=100, output_tokens=100)
        assert tracker.is_diminishing() is True

        tracker.mark_progress()

        assert tracker.is_diminishing() is False
        # 累计用量应保留（mark_progress 只清窗口不清计数器）
        assert tracker.total_used() == 1000 + 1000 + 100 + 100 + 100 + 100


# ==================== 使用率计算测试 ====================


class TestUsageRatio:
    """验证 usage_ratio 方法。"""

    def test_usage_ratio(self):
        """usage_ratio 应返回使用量除以总预算的比率。"""
        tracker = BudgetTracker(max_input_tokens=1000, max_output_tokens=1000)

        tracker.record_usage(input_tokens=500, output_tokens=500)

        # 总预算 2000，已使用 1000，使用率 0.5
        assert tracker.usage_ratio() == 0.5

    def test_usage_ratio_initial_zero(self):
        """初始状态 usage_ratio 应为 0.0。"""
        tracker = BudgetTracker()

        assert tracker.usage_ratio() == 0.0

    def test_usage_ratio_full_consumed(self):
        """预算完全耗尽时 usage_ratio 应为 1.0。"""
        tracker = BudgetTracker(max_input_tokens=1000, max_output_tokens=500)

        tracker.record_usage(input_tokens=1000, output_tokens=500)

        assert tracker.usage_ratio() == 1.0

    def test_usage_ratio_zero_budget(self):
        """总预算为 0 时 usage_ratio 应返回 0.0，避免除零错误。"""
        tracker = BudgetTracker(max_input_tokens=0, max_output_tokens=0)

        assert tracker.usage_ratio() == 0.0


# ==================== 重置测试 ====================


class TestReset:
    """验证 reset 方法。"""

    def test_reset(self):
        """reset 应将所有计数器归零，但保留预算上限配置。"""
        tracker = BudgetTracker(max_input_tokens=1000, max_output_tokens=500)

        tracker.record_usage(
            input_tokens=300,
            output_tokens=200,
            cache_read=100,
            cache_write=50,
        )
        assert tracker.total_used() == 650

        tracker.reset()

        assert tracker.total_used() == 0
        assert tracker.remaining() == 1500
        assert tracker.usage_ratio() == 0.0
        assert tracker.is_near_completion() is False
        assert tracker.is_diminishing() is False
        # 预算上限配置应保留
        assert tracker.max_input_tokens == 1000
        assert tracker.max_output_tokens == 500

    def test_reset_after_multiple_records(self):
        """多次记录后 reset 应完全清空计数器。"""
        tracker = BudgetTracker()

        tracker.record_usage(input_tokens=100, output_tokens=50)
        tracker.record_usage(input_tokens=200, output_tokens=100)
        tracker.reset()

        assert tracker.total_used() == 0

        # reset 后应能继续正常记录
        tracker.record_usage(input_tokens=50, output_tokens=25)
        assert tracker.total_used() == 75

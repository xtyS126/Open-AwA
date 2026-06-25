"""
权限拒绝追踪模块单元测试。

验证 DenialTrackingState 状态、纯函数行为、回退阈值判断。
"""

import pytest

from core.denial_tracking import (
    DENIAL_LIMITS,
    DenialTrackingState,
    record_denial,
    record_success,
    should_fallback_to_prompting,
)


class TestDenialTrackingState:
    """DenialTrackingState 状态测试"""

    def test_denial_tracking_state_initial(self):
        """验证初始状态：consecutive_denials 与 total_denials 均为 0"""
        state = DenialTrackingState()
        assert state.consecutive_denials == 0
        assert state.total_denials == 0


class TestRecordDenial:
    """record_denial 纯函数测试"""

    def test_record_denial_increments(self):
        """验证记录拒绝后 consecutive_denials 与 total_denials 均递增"""
        state = DenialTrackingState(consecutive_denials=1, total_denials=2)
        new_state = record_denial(state)
        assert new_state.consecutive_denials == 2
        assert new_state.total_denials == 3

    def test_record_denial_returns_new_state(self):
        """验证 record_denial 返回新状态，不修改原状态（纯函数）"""
        state = DenialTrackingState(consecutive_denials=1, total_denials=2)
        new_state = record_denial(state)
        # 原状态保持不变
        assert state.consecutive_denials == 1
        assert state.total_denials == 2
        # 返回的是新对象
        assert new_state is not state
        # 新状态已递增
        assert new_state.consecutive_denials == 2
        assert new_state.total_denials == 3

    def test_record_denial_from_initial(self):
        """验证从初始状态记录拒绝"""
        state = DenialTrackingState()
        new_state = record_denial(state)
        assert new_state.consecutive_denials == 1
        assert new_state.total_denials == 1


class TestRecordSuccess:
    """record_success 纯函数测试"""

    def test_record_success_resets_consecutive(self):
        """验证记录成功后 consecutive_denials 重置为 0"""
        state = DenialTrackingState(consecutive_denials=5, total_denials=10)
        new_state = record_success(state)
        assert new_state.consecutive_denials == 0

    def test_record_success_keeps_total(self):
        """验证记录成功后 total_denials 保持不变"""
        state = DenialTrackingState(consecutive_denials=5, total_denials=10)
        new_state = record_success(state)
        assert new_state.total_denials == 10

    def test_record_success_returns_new_state(self):
        """验证 record_success 返回新状态，不修改原状态（纯函数）"""
        state = DenialTrackingState(consecutive_denials=5, total_denials=10)
        new_state = record_success(state)
        # 原状态保持不变
        assert state.consecutive_denials == 5
        assert state.total_denials == 10
        # 返回的是新对象
        assert new_state is not state


class TestShouldFallbackToPrompting:
    """should_fallback_to_prompting 阈值判断测试"""

    def test_should_fallback_below_consecutive_limit(self):
        """验证连续拒绝未超限时不应回退"""
        # max_consecutive=3，2 < 3 不触发
        state = DenialTrackingState(consecutive_denials=2, total_denials=0)
        assert should_fallback_to_prompting(state) is False

    def test_should_fallback_at_consecutive_limit(self):
        """验证连续拒绝达到限制时应回退"""
        # max_consecutive=3，3 >= 3 触发
        state = DenialTrackingState(consecutive_denials=3, total_denials=0)
        assert should_fallback_to_prompting(state) is True

    def test_should_fallback_above_consecutive_limit(self):
        """验证连续拒绝超过限制时应回退"""
        state = DenialTrackingState(consecutive_denials=5, total_denials=0)
        assert should_fallback_to_prompting(state) is True

    def test_should_fallback_below_total_limit(self):
        """验证累计拒绝未超限时不应回退"""
        # max_total=20，19 < 20 不触发
        state = DenialTrackingState(consecutive_denials=0, total_denials=19)
        assert should_fallback_to_prompting(state) is False

    def test_should_fallback_at_total_limit(self):
        """验证累计拒绝达到限制时应回退"""
        # max_total=20，20 >= 20 触发
        state = DenialTrackingState(consecutive_denials=0, total_denials=20)
        assert should_fallback_to_prompting(state) is True

    def test_should_fallback_above_total_limit(self):
        """验证累计拒绝超过限制时应回退"""
        state = DenialTrackingState(consecutive_denials=0, total_denials=25)
        assert should_fallback_to_prompting(state) is True

    def test_should_fallback_initial_state(self):
        """验证初始状态不应回退"""
        state = DenialTrackingState()
        assert should_fallback_to_prompting(state) is False


class TestDenialLimitsConstants:
    """DENIAL_LIMITS 常量值测试"""

    def test_denial_limits_constants(self):
        """验证 DENIAL_LIMITS 常量值正确"""
        assert DENIAL_LIMITS["max_consecutive"] == 3
        assert DENIAL_LIMITS["max_total"] == 20

    def test_denial_limits_keys(self):
        """验证 DENIAL_LIMITS 包含必需的键"""
        assert "max_consecutive" in DENIAL_LIMITS
        assert "max_total" in DENIAL_LIMITS


class TestDenialTrackingIntegration:
    """拒绝追踪流程集成测试：模拟连续拒绝后回退的场景"""

    def test_consecutive_denials_trigger_fallback(self):
        """验证连续拒绝 3 次后触发回退"""
        state = DenialTrackingState()
        # 第 1 次拒绝
        state = record_denial(state)
        assert should_fallback_to_prompting(state) is False
        # 第 2 次拒绝
        state = record_denial(state)
        assert should_fallback_to_prompting(state) is False
        # 第 3 次拒绝：触发回退
        state = record_denial(state)
        assert should_fallback_to_prompting(state) is True

    def test_success_resets_consecutive_denials(self):
        """验证成功重置连续拒绝计数，避免误触发回退"""
        state = DenialTrackingState()
        # 连续 2 次拒绝
        state = record_denial(state)
        state = record_denial(state)
        assert state.consecutive_denials == 2
        # 成功重置连续拒绝
        state = record_success(state)
        assert state.consecutive_denials == 0
        assert state.total_denials == 2
        # 再次拒绝不会触发回退
        state = record_denial(state)
        assert should_fallback_to_prompting(state) is False

    def test_total_denials_accumulate_across_successes(self):
        """验证 total_denials 跨成功持续累积，最终触发回退"""
        state = DenialTrackingState()
        # 模拟多轮拒绝+成功，累计 total_denials 达到 max_total
        for _ in range(10):
            state = record_denial(state)
            state = record_success(state)
        # 此时 total_denials=10，consecutive_denials=0
        assert state.total_denials == 10
        assert state.consecutive_denials == 0
        assert should_fallback_to_prompting(state) is False

        # 继续累积到 20
        for _ in range(10):
            state = record_denial(state)
            state = record_success(state)
        # 此时 total_denials=20，触发回退
        assert state.total_denials == 20
        assert should_fallback_to_prompting(state) is True

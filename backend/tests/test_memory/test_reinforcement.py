"""
Memory reinforcement 模块测试。
"""
import pytest
from memory.reinforcement import (
    access_reinforcement,
    importance_reinforcement,
    recency_reinforcement,
    combined_reinforcement,
)


class TestAccessReinforcement:
    """访问次数强化函数测试。"""

    def test_access_reinforcement_basic(self):
        """基本访问强化：访问次数越多，强化越高。"""
        result = access_reinforcement(access_count=50, max_count=100, reinforcement_factor=0.1)
        assert result == pytest.approx(0.05, abs=0.01)

    def test_access_reinforcement_max(self):
        """达到最大访问次数后强化因子达到上限。"""
        result = access_reinforcement(access_count=100, max_count=100, reinforcement_factor=0.1)
        assert result == pytest.approx(0.1, abs=0.01)

    def test_access_reinforcement_exceed_max(self):
        """超过最大访问次数，强化因子不超出上限。"""
        result = access_reinforcement(access_count=200, max_count=100, reinforcement_factor=0.1)
        assert result == pytest.approx(0.1, abs=0.01)

    def test_access_reinforcement_zero(self):
        """零次访问，强化为 0。"""
        result = access_reinforcement(access_count=0)
        assert result == 0.0

    def test_access_reinforcement_negative(self):
        """负数访问次数，强化为 0。"""
        result = access_reinforcement(access_count=-1)
        assert result == 0.0

    def test_access_reinforcement_custom_factor(self):
        """自定义强化因子。"""
        result = access_reinforcement(access_count=50, max_count=100, reinforcement_factor=0.2)
        assert result == pytest.approx(0.1, abs=0.01)


class TestImportanceReinforcement:
    """重要度强化函数测试。"""

    def test_importance_reinforcement_basic(self):
        """基本重要度强化。"""
        result = importance_reinforcement(importance=0.5, reinforcement_factor=0.2)
        assert result == pytest.approx(0.1, abs=0.01)

    def test_importance_reinforcement_max(self):
        """最大重要度，强化达到上限。"""
        result = importance_reinforcement(importance=1.0, reinforcement_factor=0.2)
        assert result == pytest.approx(0.2, abs=0.01)

    def test_importance_reinforcement_zero(self):
        """重要度为 0，强化为 0。"""
        result = importance_reinforcement(importance=0.0)
        assert result == 0.0

    def test_importance_reinforcement_negative(self):
        """负数重要度，强化为 0。"""
        result = importance_reinforcement(importance=-0.5)
        assert result == 0.0

    def test_importance_reinforcement_custom_factor(self):
        """自定义强化因子。"""
        result = importance_reinforcement(importance=0.8, reinforcement_factor=0.5)
        assert result == pytest.approx(0.4, abs=0.01)


class TestRecencyReinforcement:
    """时间新鲜度强化函数测试。"""

    def test_recency_reinforcement_basic(self):
        """基本新鲜度强化：3.5 天前，max_days=7，新鲜度 0.5。"""
        result = recency_reinforcement(days_since_access=3.5, max_days=7, reinforcement_factor=0.15)
        assert result == pytest.approx(0.075, abs=0.01)

    def test_recency_reinforcement_zero_days(self):
        """0 天前访问，获得最大强化。"""
        result = recency_reinforcement(days_since_access=0.0, max_days=7, reinforcement_factor=0.15)
        assert result == pytest.approx(0.15, abs=0.01)

    def test_recency_reinforcement_negative_days(self):
        """负天数（未来），获得最大强化。"""
        result = recency_reinforcement(days_since_access=-1.0)
        assert result == pytest.approx(0.15, abs=0.01)

    def test_recency_reinforcement_exceed_max(self):
        """超过最大天数，强化为 0。"""
        result = recency_reinforcement(days_since_access=10.0, max_days=7.0)
        assert result == 0.0

    def test_recency_reinforcement_exact_max(self):
        """恰好等于最大天数，强化为 0。"""
        result = recency_reinforcement(days_since_access=7.0, max_days=7.0)
        assert result == 0.0


class TestCombinedReinforcement:
    """综合强化函数测试。"""

    def test_combined_reinforcement_basic(self):
        """综合强化：结合三种强化因子。"""
        result = combined_reinforcement(
            access_count=50,
            importance=0.5,
            days_since_access=3.5,
        )
        # access_boost: 50/100 * 0.1 = 0.05
        # importance_boost: 0.5 * 0.2 = 0.1
        # recency_boost: (1 - 3.5/7) * 0.15 = 0.075
        # total = 0.05*0.3 + 0.1*0.4 + 0.075*0.3 = 0.015 + 0.04 + 0.0225 = 0.0775
        assert result == pytest.approx(0.0775, abs=0.001)

    def test_combined_reinforcement_max(self):
        """所有参数达到最大值时综合强化。"""
        result = combined_reinforcement(
            access_count=100,
            importance=1.0,
            days_since_access=0.0,
        )
        assert 0.0 < result < 1.0

    def test_combined_reinforcement_min(self):
        """所有参数为最小值时综合强化为 0。"""
        result = combined_reinforcement(
            access_count=0,
            importance=0.0,
            days_since_access=100.0,
        )
        assert result == 0.0

    def test_combined_reinforcement_custom_weights(self):
        """自定义权重。"""
        result = combined_reinforcement(
            access_count=100,
            importance=0.0,
            days_since_access=100.0,
            access_weight=1.0,
            importance_weight=0.0,
            recency_weight=0.0,
        )
        assert result == pytest.approx(0.1, abs=0.01)
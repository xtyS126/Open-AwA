"""
Memory decay 模块测试。
"""
import pytest
from datetime import datetime, timezone, timedelta
from memory.decay import exponential_decay, linear_decay, step_decay, no_decay


class TestExponentialDecay:
    """指数衰减函数测试。"""

    def test_exponential_decay_basic(self):
        """基本指数衰减：经过一个半衰期后权重为 0.5。"""
        now = datetime.now(timezone.utc)
        half_life_ago = now - timedelta(days=30)
        result = exponential_decay(half_life_ago, half_life_days=30, current_time=now)
        assert result == pytest.approx(0.5, abs=0.01)

    def test_exponential_decay_zero_days(self):
        """零天经过，权重为 1.0。"""
        now = datetime.now(timezone.utc)
        result = exponential_decay(now, half_life_days=30, current_time=now)
        assert result == 1.0

    def test_exponential_decay_negative_days(self):
        """未来时间（负天数），权重为 1.0。"""
        now = datetime.now(timezone.utc)
        future = now + timedelta(days=10)
        result = exponential_decay(future, half_life_days=30, current_time=now)
        assert result == 1.0

    def test_exponential_decay_two_half_lives(self):
        """经过两个半衰期后权重为 0.25。"""
        now = datetime.now(timezone.utc)
        two_half = now - timedelta(days=60)
        result = exponential_decay(two_half, half_life_days=30, current_time=now)
        assert result == pytest.approx(0.25, abs=0.01)

    def test_exponential_decay_custom_half_life(self):
        """自定义半衰期。"""
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=10)
        result = exponential_decay(past, half_life_days=10, current_time=now)
        assert result == pytest.approx(0.5, abs=0.01)

    def test_exponential_decay_naive_datetime(self):
        """naive datetime 自动添加时区。"""
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=30)
        past_naive = past.replace(tzinfo=None)
        result = exponential_decay(past_naive, half_life_days=30, current_time=now)
        assert result == pytest.approx(0.5, abs=0.01)

    def test_exponential_decay_default_current_time(self):
        """不传 current_time 时使用当前时间。"""
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=30)
        result = exponential_decay(past, half_life_days=30)
        # 接近 0.5
        assert 0.0 <= result <= 1.0


class TestLinearDecay:
    """线性衰减函数测试。"""

    def test_linear_decay_basic(self):
        """基本线性衰减：经过一半时间，权重为 0.5。"""
        now = datetime.now(timezone.utc)
        half = now - timedelta(days=45)
        result = linear_decay(half, max_days=90, current_time=now)
        assert result == pytest.approx(0.5, abs=0.01)

    def test_linear_decay_zero_days(self):
        """零天经过，权重为 1.0。"""
        now = datetime.now(timezone.utc)
        result = linear_decay(now, max_days=90, current_time=now)
        assert result == 1.0

    def test_linear_decay_exceed_max(self):
        """超过最大天数，权重为 0.0。"""
        now = datetime.now(timezone.utc)
        long_ago = now - timedelta(days=100)
        result = linear_decay(long_ago, max_days=90, current_time=now)
        assert result == 0.0

    def test_linear_decay_negative_days(self):
        """未来时间（负天数），权重为 1.0。"""
        now = datetime.now(timezone.utc)
        future = now + timedelta(days=10)
        result = linear_decay(future, max_days=90, current_time=now)
        assert result == 1.0

    def test_linear_decay_custom_max(self):
        """自定义最大天数。"""
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=15)
        result = linear_decay(past, max_days=30, current_time=now)
        assert result == pytest.approx(0.5, abs=0.01)


class TestStepDecay:
    """阶梯衰减函数测试。"""

    def test_step_decay_basic(self):
        """基本阶梯衰减：经过一个阶梯后权重减少 0.1。"""
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=7)
        result = step_decay(past, step_days=7, decay_per_step=0.1, current_time=now)
        assert result == pytest.approx(0.9, abs=0.01)

    def test_step_decay_two_steps(self):
        """经过两个阶梯，权重减少 0.2。"""
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=14)
        result = step_decay(past, step_days=7, decay_per_step=0.1, current_time=now)
        assert result == pytest.approx(0.8, abs=0.01)

    def test_step_decay_zero_days(self):
        """零天经过，权重为 1.0。"""
        now = datetime.now(timezone.utc)
        result = step_decay(now, step_days=7, decay_per_step=0.1, current_time=now)
        assert result == 1.0

    def test_step_decay_full_decay(self):
        """经过足够多阶梯后权重降到 0.0。"""
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=100)
        result = step_decay(past, step_days=7, decay_per_step=0.1, current_time=now)
        assert result == 0.0

    def test_step_decay_negative_days(self):
        """未来时间（负天数），权重为 1.0。"""
        now = datetime.now(timezone.utc)
        future = now + timedelta(days=5)
        result = step_decay(future, step_days=7, decay_per_step=0.1, current_time=now)
        assert result == 1.0


class TestNoDecay:
    """无衰减函数测试。"""

    def test_no_decay_always_one(self):
        """no_decay 始终返回 1.0。"""
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=365)
        result = no_decay(past, current_time=now)
        assert result == 1.0

    def test_no_decay_ignore_time(self):
        """no_decay 忽略时间参数。"""
        result = no_decay(datetime.now(timezone.utc))
        assert result == 1.0
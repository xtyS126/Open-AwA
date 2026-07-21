"""
billing/budget_manager.py 单元测试。
覆盖 BudgetManager 的预算创建、查询、更新、删除、检查等全部方法。
使用内存 SQLite 数据库和 unittest.mock 隔离外部依赖。
"""

from datetime import date, datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base
from billing.models import BudgetConfig
from billing.budget_manager import BudgetManager


# ==================== Fixtures ====================

@pytest.fixture
def db_session():
    """创建独立的内存 SQLite 数据库会话"""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def budget_manager(db_session):
    """创建 BudgetManager 实例"""
    return BudgetManager(db_session)


@pytest.fixture
def sample_budget(budget_manager):
    """创建一个示例预算配置用于测试"""
    return budget_manager.create_budget(
        budget_type="user",
        max_amount=100.0,
        scope_id="user-001",
        period_type="monthly",
        currency="USD",
        warning_threshold=0.8,
    )


# ==================== 预算创建测试 ====================

class TestCreateBudget:
    """测试 create_budget 方法：预算配置的创建与持久化"""

    def test_create_user_budget_succeeds(self, budget_manager, db_session):
        """用户类型预算创建成功并持久化到数据库"""
        budget = budget_manager.create_budget(
            budget_type="user",
            max_amount=50.0,
            scope_id="user-001",
        )
        assert budget.id is not None
        assert budget.budget_type == "user"
        assert budget.max_amount == 50.0
        assert budget.scope_id == "user-001"
        assert budget.period_type == "monthly"
        assert budget.currency == "USD"
        assert budget.warning_threshold == 0.8
        assert budget.is_active is True

        # 验证数据库中存在该记录
        saved = db_session.query(BudgetConfig).filter(
            BudgetConfig.id == budget.id
        ).first()
        assert saved is not None

    def test_create_global_budget_succeeds(self, budget_manager):
        """全局类型预算创建成功"""
        budget = budget_manager.create_budget(
            budget_type="global",
            max_amount=500.0,
            scope_id=None,
            period_type="monthly",
        )
        assert budget.budget_type == "global"
        assert budget.scope_id is None
        assert budget.max_amount == 500.0

    def test_create_daily_period_budget(self, budget_manager):
        """按天计费周期的预算创建成功"""
        budget = budget_manager.create_budget(
            budget_type="user",
            max_amount=10.0,
            scope_id="user-daily",
            period_type="daily",
        )
        assert budget.period_type == "daily"

    def test_create_yearly_period_budget(self, budget_manager):
        """按年计费周期的预算创建成功"""
        budget = budget_manager.create_budget(
            budget_type="user",
            max_amount=1000.0,
            scope_id="user-yearly",
            period_type="yearly",
        )
        assert budget.period_type == "yearly"

    def test_create_custom_warning_threshold(self, budget_manager):
        """自定义告警阈值生效"""
        budget = budget_manager.create_budget(
            budget_type="user",
            max_amount=100.0,
            scope_id="user-002",
            warning_threshold=0.5,
        )
        assert budget.warning_threshold == 0.5

    def test_create_custom_currency(self, budget_manager):
        """自定义货币单位生效"""
        budget = budget_manager.create_budget(
            budget_type="user",
            max_amount=100.0,
            scope_id="user-cny",
            currency="CNY",
        )
        assert budget.currency == "CNY"


# ==================== 预算查询测试 ====================

class TestGetBudget:
    """测试 get_budget 和 get_budgets 方法"""

    def test_get_budget_by_id_found(self, budget_manager, sample_budget):
        """通过 ID 查询存在的预算"""
        found = budget_manager.get_budget(sample_budget.id)
        assert found is not None
        assert found.id == sample_budget.id
        assert found.budget_type == sample_budget.budget_type

    def test_get_budget_by_id_not_found(self, budget_manager):
        """查询不存在的预算 ID 返回 None"""
        found = budget_manager.get_budget(9999)
        assert found is None

    def test_get_budgets_all_active(self, budget_manager, sample_budget):
        """获取所有活跃预算"""
        budgets = budget_manager.get_budgets()
        assert len(budgets) >= 1
        for b in budgets:
            assert b.is_active is True

    def test_get_budgets_filter_by_type(self, budget_manager):
        """按类型过滤预算"""
        budget_manager.create_budget(
            budget_type="user", max_amount=50.0, scope_id="u1"
        )
        budget_manager.create_budget(
            budget_type="global", max_amount=500.0
        )

        user_budgets = budget_manager.get_budgets(budget_type="user")
        assert all(b.budget_type == "user" for b in user_budgets)

        global_budgets = budget_manager.get_budgets(budget_type="global")
        assert all(b.budget_type == "global" for b in global_budgets)

    def test_get_budgets_filter_by_scope_id(self, budget_manager):
        """按 scope_id 过滤预算"""
        budget_manager.create_budget(
            budget_type="user", max_amount=50.0, scope_id="user-a"
        )
        budget_manager.create_budget(
            budget_type="user", max_amount=30.0, scope_id="user-b"
        )

        budgets_a = budget_manager.get_budgets(scope_id="user-a")
        assert all(b.scope_id == "user-a" for b in budgets_a)

        budgets_b = budget_manager.get_budgets(scope_id="user-b")
        assert all(b.scope_id == "user-b" for b in budgets_b)

    def test_get_budgets_excludes_inactive(self, budget_manager):
        """不返回非活跃预算"""
        budget = budget_manager.create_budget(
            budget_type="user", max_amount=100.0, scope_id="inactive-user"
        )
        budget_manager.delete_budget(budget.id)

        active_budgets = budget_manager.get_budgets()
        ids = [b.id for b in active_budgets]
        assert budget.id not in ids


# ==================== 用户预算获取测试 ====================

class TestGetBudgetForUser:
    """测试 get_budget_for_user 方法：用户预算查找（含全局回退）"""

    def test_returns_user_specific_budget(self, budget_manager, sample_budget):
        """存在用户专属预算时返回用户预算"""
        result = budget_manager.get_budget_for_user("user-001")
        assert result is not None
        assert result.budget_type == "user"
        assert result.scope_id == "user-001"

    def test_falls_back_to_global_budget(self, budget_manager):
        """无用户专属预算时回退到全局预算"""
        global_budget = budget_manager.create_budget(
            budget_type="global",
            max_amount=1000.0,
        )
        result = budget_manager.get_budget_for_user("user-no-budget")
        assert result is not None
        assert result.budget_type == "global"
        assert result.scope_id is None

    def test_returns_none_when_no_budgets(self, budget_manager):
        """没有任何预算配置时返回 None"""
        result = budget_manager.get_budget_for_user("orphan-user")
        assert result is None

    def test_ignores_inactive_user_budget(self, budget_manager):
        """用户专属预算已设为非活跃时，回退到全局预算"""
        user_budget = budget_manager.create_budget(
            budget_type="user", max_amount=50.0, scope_id="user-inactive"
        )
        global_budget = budget_manager.create_budget(
            budget_type="global", max_amount=500.0
        )
        # 软删除用户预算
        budget_manager.delete_budget(user_budget.id)

        result = budget_manager.get_budget_for_user("user-inactive")
        assert result is not None
        assert result.budget_type == "global"


# ==================== 预算更新测试 ====================

class TestUpdateBudget:
    """测试 update_budget 方法：预算配置的字段更新"""

    def test_update_max_amount(self, budget_manager, sample_budget):
        """更新预算上限"""
        result = budget_manager.update_budget(
            sample_budget.id, {"max_amount": 200.0}
        )
        assert result is not None
        assert result.max_amount == 200.0

    def test_update_warning_threshold(self, budget_manager, sample_budget):
        """更新告警阈值"""
        result = budget_manager.update_budget(
            sample_budget.id, {"warning_threshold": 0.9}
        )
        assert result.warning_threshold == 0.9

    def test_update_multiple_fields(self, budget_manager, sample_budget):
        """同时更新多个字段"""
        result = budget_manager.update_budget(
            sample_budget.id,
            {"max_amount": 300.0, "currency": "CNY", "period_type": "daily"},
        )
        assert result.max_amount == 300.0
        assert result.currency == "CNY"
        assert result.period_type == "daily"

    def test_update_disallowed_field_ignored(self, budget_manager, sample_budget):
        """不允许更新的字段被忽略"""
        import billing.budget_manager as bm_module

        # 源代码中 logger 未导入，需要手动注入 mock 对象
        mock_logger = MagicMock()
        bm_module.logger = mock_logger

        try:
            result = budget_manager.update_budget(
                sample_budget.id, {"non_existent_field": "should_be_ignored"}
            )
            assert result is not None
            # 验证 logger.warning 被调用了一次
            mock_logger.warning.assert_called_once()
            assert "non_existent_field" in mock_logger.warning.call_args[0][0]
        finally:
            # 清理注入的 mock
            delattr(bm_module, "logger")

    def test_update_nonexistent_budget_returns_none(self, budget_manager):
        """更新不存在的预算返回 None"""
        result = budget_manager.update_budget(9999, {"max_amount": 100.0})
        assert result is None

    def test_update_sets_updated_at(self, budget_manager, sample_budget):
        """更新后 updated_at 字段被刷新"""
        import time
        time.sleep(0.01)  # 等待一小段时间确保时间戳不同
        result = budget_manager.update_budget(
            sample_budget.id, {"max_amount": 150.0}
        )
        assert result.updated_at is not None


# ==================== 预算删除测试 ====================

class TestDeleteBudget:
    """测试 delete_budget 方法：预算的软删除"""

    def test_delete_active_budget_succeeds(self, budget_manager, sample_budget):
        """删除活跃预算成功（软删除）"""
        result = budget_manager.delete_budget(sample_budget.id)
        assert result is True

        # 验证预算已标记为非活跃
        deleted = budget_manager.get_budget(sample_budget.id)
        assert deleted.is_active is False

    def test_delete_nonexistent_budget_returns_false(self, budget_manager):
        """删除不存在的预算返回 False"""
        result = budget_manager.delete_budget(9999)
        assert result is False

    def test_delete_already_inactive_budget(self, budget_manager, sample_budget):
        """重复删除已非活跃预算仍返回 True"""
        budget_manager.delete_budget(sample_budget.id)
        result = budget_manager.delete_budget(sample_budget.id)
        assert result is True


# ==================== 预算检查测试 ====================

class TestCheckBudget:
    """测试 check_budget 方法：预算状态检查"""

    # 固定一个测试日期供 _get_period_dates 使用
    FIXED_DATE = date(2026, 5, 15)

    def test_no_budget_configured_always_allows(self, budget_manager):
        """未配置预算时始终允许继续"""
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = self.FIXED_DATE
            result = budget_manager.check_budget("no-budget-user", proposed_cost=10.0)

        assert result["has_budget"] is True
        assert result["budget_limit"] is None
        assert result["can_proceed"] is True
        assert result["budget_exceeded"] is False
        assert result["warning_threshold_reached"] is False

    def test_normal_usage_below_threshold(self, budget_manager, sample_budget):
        """正常用量未超过告警阈值"""
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = self.FIXED_DATE
            # mock UsageTracker 返回低用量
            with patch("billing.tracker.UsageTracker") as mock_tracker_cls:
                mock_tracker = MagicMock()
                mock_tracker.get_user_usage.return_value = {"total_cost": 30.0}
                mock_tracker_cls.return_value = mock_tracker

                result = budget_manager.check_budget(
                    "user-001", proposed_cost=10.0
                )

        assert result["has_budget"] is True
        assert result["current_usage"] == 30.0
        assert result["remaining"] == 70.0
        assert result["usage_percentage"] == 30.0
        assert result["warning_threshold_reached"] is False
        assert result["budget_exceeded"] is False
        assert result["can_proceed"] is True

    def test_usage_reaches_warning_threshold(self, budget_manager, sample_budget):
        """用量刚好达到告警阈值（80%）"""
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = self.FIXED_DATE
            with patch("billing.tracker.UsageTracker") as mock_tracker_cls:
                mock_tracker = MagicMock()
                mock_tracker.get_user_usage.return_value = {"total_cost": 80.0}
                mock_tracker_cls.return_value = mock_tracker

                result = budget_manager.check_budget(
                    "user-001", proposed_cost=1.0
                )

        assert result["warning_threshold_reached"] is True
        assert result["budget_exceeded"] is False
        assert result["can_proceed"] is True
        assert result["usage_percentage"] == 80.0

    def test_usage_exceeds_warning_threshold(self, budget_manager, sample_budget):
        """用量超过告警阈值但未耗尽预算"""
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = self.FIXED_DATE
            with patch("billing.tracker.UsageTracker") as mock_tracker_cls:
                mock_tracker = MagicMock()
                mock_tracker.get_user_usage.return_value = {"total_cost": 90.0}
                mock_tracker_cls.return_value = mock_tracker

                result = budget_manager.check_budget(
                    "user-001", proposed_cost=5.0
                )

        assert result["warning_threshold_reached"] is True
        assert result["budget_exceeded"] is False
        assert result["can_proceed"] is True

    def test_proposed_cost_exceeds_budget(self, budget_manager, sample_budget):
        """拟消耗额度导致总用量超出预算"""
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = self.FIXED_DATE
            with patch("billing.tracker.UsageTracker") as mock_tracker_cls:
                mock_tracker = MagicMock()
                mock_tracker.get_user_usage.return_value = {"total_cost": 95.0}
                mock_tracker_cls.return_value = mock_tracker

                result = budget_manager.check_budget(
                    "user-001", proposed_cost=10.0
                )

        assert result["budget_exceeded"] is True
        assert result["can_proceed"] is False
        assert result["usage_percentage"] == 95.0

    def test_budget_exactly_exhausted(self, budget_manager, sample_budget):
        """预算刚好耗尽（现有用量 = 预算上限）"""
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = self.FIXED_DATE
            with patch("billing.tracker.UsageTracker") as mock_tracker_cls:
                mock_tracker = MagicMock()
                mock_tracker.get_user_usage.return_value = {"total_cost": 100.0}
                mock_tracker_cls.return_value = mock_tracker

                result = budget_manager.check_budget(
                    "user-001", proposed_cost=1.0
                )

        assert result["usage_percentage"] == 100.0
        assert result["budget_exceeded"] is True
        assert result["can_proceed"] is False

    def test_zero_max_amount_budget(self, budget_manager):
        """max_amount 为 0 的预算特殊处理"""
        budget_manager.create_budget(
            budget_type="user",
            max_amount=0,
            scope_id="user-zero",
        )
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = self.FIXED_DATE
            with patch("billing.tracker.UsageTracker") as mock_tracker_cls:
                mock_tracker = MagicMock()
                mock_tracker.get_user_usage.return_value = {"total_cost": 0}
                mock_tracker_cls.return_value = mock_tracker

                result = budget_manager.check_budget(
                    "user-zero", proposed_cost=10.0
                )

        assert result["warning_threshold_reached"] is False
        assert result["budget_exceeded"] is False
        assert result["can_proceed"] is True

    def test_zero_proposed_cost(self, budget_manager, sample_budget):
        """拟消耗为 0 时正常检查"""
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = self.FIXED_DATE
            with patch("billing.tracker.UsageTracker") as mock_tracker_cls:
                mock_tracker = MagicMock()
                mock_tracker.get_user_usage.return_value = {"total_cost": 50.0}
                mock_tracker_cls.return_value = mock_tracker

                result = budget_manager.check_budget(
                    "user-001", proposed_cost=0
                )

        assert result["budget_exceeded"] is False
        assert result["can_proceed"] is True

    def test_result_contains_period_type_and_currency(self, budget_manager, sample_budget):
        """检查结果包含计费周期类型和货币信息"""
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = self.FIXED_DATE
            with patch("billing.tracker.UsageTracker") as mock_tracker_cls:
                mock_tracker = MagicMock()
                mock_tracker.get_user_usage.return_value = {"total_cost": 0}
                mock_tracker_cls.return_value = mock_tracker

                result = budget_manager.check_budget("user-001")

        assert result["period_type"] == "monthly"
        assert result["currency"] == "USD"

    def test_cost_rounding_precision(self, budget_manager, sample_budget):
        """费用保留 6 位小数"""
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = self.FIXED_DATE
            with patch("billing.tracker.UsageTracker") as mock_tracker_cls:
                mock_tracker = MagicMock()
                mock_tracker.get_user_usage.return_value = {"total_cost": 33.333333}
                mock_tracker_cls.return_value = mock_tracker

                result = budget_manager.check_budget("user-001")

        assert result["current_usage"] == 33.333333
        assert result["remaining"] == 66.666667


# ==================== 预算状态获取测试 ====================

class TestGetBudgetStatus:
    """测试 get_budget_status 方法：获取详细预算状态"""

    FIXED_DATE = date(2026, 5, 15)

    def test_no_budget_configured_status(self, budget_manager):
        """未配置预算时返回对应状态"""
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = self.FIXED_DATE
            result = budget_manager.get_budget_status("no-budget-user")

        assert result["has_budget_configured"] is False
        assert result["message"] == "No budget configured"

    def test_budget_configured_returns_full_status(self, budget_manager, sample_budget):
        """已配置预算时返回完整状态信息"""
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = self.FIXED_DATE
            with patch("billing.tracker.UsageTracker") as mock_tracker_cls:
                mock_tracker = MagicMock()
                mock_tracker.get_user_usage.return_value = {"total_cost": 25.0}
                mock_tracker_cls.return_value = mock_tracker

                result = budget_manager.get_budget_status("user-001")

        assert result["has_budget_configured"] is True
        assert result["budget_type"] == "user"
        assert result["max_amount"] == 100.0
        assert result["current_usage"] == 25.0
        assert result["remaining"] == 75.0
        assert result["usage_percentage"] == 25.0
        assert result["warning_threshold"] == 0.8
        assert result["period_type"] == "monthly"
        assert "period_start" in result
        assert "period_end" in result
        assert result["currency"] == "USD"
        assert result["is_warning"] is False
        assert result["is_exceeded"] is False

    def test_budget_warning_status(self, budget_manager, sample_budget):
        """达到告警阈值时 is_warning 为 True"""
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = self.FIXED_DATE
            with patch("billing.tracker.UsageTracker") as mock_tracker_cls:
                mock_tracker = MagicMock()
                mock_tracker.get_user_usage.return_value = {"total_cost": 85.0}
                mock_tracker_cls.return_value = mock_tracker

                result = budget_manager.get_budget_status("user-001")

        assert result["is_warning"] is True
        assert result["is_exceeded"] is False

    def test_budget_exceeded_status(self, budget_manager, sample_budget):
        """超出预算时 is_exceeded 为 True"""
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = self.FIXED_DATE
            with patch("billing.tracker.UsageTracker") as mock_tracker_cls:
                mock_tracker = MagicMock()
                mock_tracker.get_user_usage.return_value = {"total_cost": 100.0}
                mock_tracker_cls.return_value = mock_tracker

                result = budget_manager.get_budget_status("user-001")

        assert result["is_warning"] is True
        assert result["is_exceeded"] is True


# ==================== 计费周期日期计算测试 ====================

class TestGetPeriodDates:
    """测试 _get_period_dates 方法：计费周期起止日期计算"""

    def test_daily_period(self, budget_manager):
        """按天计费周期：起止为同一天"""
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 15)
            start, end = budget_manager._get_period_dates("daily")

        assert start == date(2026, 5, 15)
        assert end == date(2026, 5, 15)

    def test_weekly_period_monday(self, budget_manager):
        """按周计费周期：周一起始"""
        # 2026-05-11 是周一
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 11)
            start, end = budget_manager._get_period_dates("weekly")

        assert start == date(2026, 5, 11)
        assert end == date(2026, 5, 17)

    def test_weekly_period_wednesday(self, budget_manager):
        """按周计费周期：周三应回到本周周一"""
        # 2026-05-13 是周三
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 13)
            start, end = budget_manager._get_period_dates("weekly")

        assert start == date(2026, 5, 11)
        assert end == date(2026, 5, 17)

    def test_weekly_period_sunday(self, budget_manager):
        """按周计费周期：周日应回到本周周一"""
        # 2026-05-17 是周日
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 17)
            start, end = budget_manager._get_period_dates("weekly")

        assert start == date(2026, 5, 11)
        assert end == date(2026, 5, 17)

    def test_monthly_period_first_day(self, budget_manager):
        """按月计费周期：月初"""
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 1)
            start, end = budget_manager._get_period_dates("monthly")

        assert start == date(2026, 5, 1)
        assert end == date(2026, 5, 31)

    def test_monthly_period_mid_month(self, budget_manager):
        """按月计费周期：月中"""
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 15)
            start, end = budget_manager._get_period_dates("monthly")

        assert start == date(2026, 5, 1)
        assert end == date(2026, 5, 31)

    def test_monthly_period_end_of_month(self, budget_manager):
        """按月计费周期：月末"""
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 31)
            start, end = budget_manager._get_period_dates("monthly")

        assert start == date(2026, 5, 1)
        assert end == date(2026, 5, 31)

    def test_monthly_period_december(self, budget_manager):
        """按月计费周期：12月跨年"""
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = date(2026, 12, 10)
            start, end = budget_manager._get_period_dates("monthly")

        assert start == date(2026, 12, 1)
        assert end == date(2026, 12, 31)

    def test_yearly_period(self, budget_manager):
        """按年计费周期"""
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = date(2026, 7, 1)
            start, end = budget_manager._get_period_dates("yearly")

        assert start == date(2026, 1, 1)
        assert end == date(2026, 12, 31)

    def test_unknown_period_falls_back_to_monthly(self, budget_manager):
        """未知周期类型回退为按月"""
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 15)
            start, end = budget_manager._get_period_dates("unknown_period_type")

        assert start == date(2026, 5, 1)

    def test_february_leap_year(self, budget_manager):
        """二月（闰年 2024）"""
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = date(2024, 2, 15)
            start, end = budget_manager._get_period_dates("monthly")

        assert start == date(2024, 2, 1)
        assert end == date(2024, 2, 29)


# ==================== 跨计费周期测试 ====================

class TestCrossPeriodBudget:
    """测试跨计费周期的预算行为"""

    def test_new_month_resets_usage_effectively(self, budget_manager):
        """新计费月份不同日期产生不同的 period_start"""
        budget = budget_manager.create_budget(
            budget_type="user", max_amount=100.0, scope_id="user-period",
        )

        # 模拟 5 月份
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 15)
            with patch("billing.tracker.UsageTracker") as mock_tracker_cls:
                mock_tracker = MagicMock()
                mock_tracker.get_user_usage.return_value = {"total_cost": 50.0}
                mock_tracker_cls.return_value = mock_tracker
                result_may = budget_manager.check_budget("user-period")

        assert result_may["current_usage"] == 50.0
        assert result_may["period_type"] == "monthly"

        # 模拟 6 月份（但不 mock UsageTracker 的查询结果）
        # _calculate_current_usage 会使用 period_start/period_end 调用 tracker.get_user_usage
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = date(2026, 6, 5)
            with patch("billing.tracker.UsageTracker") as mock_tracker_cls:
                mock_tracker = MagicMock()
                mock_tracker.get_user_usage.return_value = {"total_cost": 10.0}
                mock_tracker_cls.return_value = mock_tracker
                result_june = budget_manager.check_budget("user-period")

        assert result_june["current_usage"] == 10.0


    def test_daily_period_different_days(self, budget_manager):
        """按天计费周期不同日期 usage 查询使用不同的参数"""
        budget_manager.create_budget(
            budget_type="user", max_amount=10.0, scope_id="user-daily",
            period_type="daily",
        )

        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 15)
            with patch("billing.tracker.UsageTracker") as mock_tracker_cls:
                mock_tracker = MagicMock()
                mock_tracker.get_user_usage.return_value = {"total_cost": 5.0}
                mock_tracker_cls.return_value = mock_tracker
                result_day1 = budget_manager.check_budget("user-daily")

        # 验证 tracker 被调用时传入了正确的日期范围
        with patch("billing.budget_manager.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 16)
            with patch("billing.tracker.UsageTracker") as mock_tracker_cls:
                mock_tracker = MagicMock()
                mock_tracker.get_user_usage.return_value = {"total_cost": 2.0}
                mock_tracker_cls.return_value = mock_tracker
                result_day2 = budget_manager.check_budget("user-daily")

        assert result_day1 is not None
        assert result_day2 is not None

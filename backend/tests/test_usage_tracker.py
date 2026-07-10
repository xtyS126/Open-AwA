"""billing/usage_tracker.py 单元测试

覆盖 UsageTracker.record_llm_call 的核心场景：
1. 写入 usage_records 表（计费扣减闭环）
2. 成本计算公式（input/output/cache_read/cache_write）
3. 含 cache_read_tokens 的成本计算
4. ENABLE_BILLING=False 时跳过
5. pricing 查询失败时不抛异常（不传播）
6. pricing 为 None 或字段为 NULL 时按 0 处理
7. 触发预算扣减（通过写入 usage_records 实现）
8. 触发预警检查（BudgetAlertService.check_and_generate_alerts）
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from billing.models import ModelPricing, UsageRecord
from billing.token_counter import TokenBreakdown
from billing.usage_tracker import UsageTracker
from db.models import Base


# ==================== 公共 fixture ====================


@pytest.fixture
def db_session():
    """创建独立内存数据库，建表后返回会话。

    使用 Base.metadata.create_all 一次性创建所有表（含 usage_records /
    model_pricing / user_usage_summary 等），保证 PricingManager.ensure_pricing_schema
    检测到所有列已存在，跳过 ALTER TABLE。
    """
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def usage_tracker(db_session):
    """构造 UsageTracker 实例，绑定内存数据库。"""
    return UsageTracker(db_session)


def _make_pricing(
    db_session,
    provider: str = "openai",
    model: str = "gpt-4o",
    input_price: float = 5.0,
    output_price: float = 15.0,
    cache_read_price=None,
    cache_write_price=None,
    currency: str = "USD",
) -> ModelPricing:
    """插入一条 ModelPricing 记录用于测试。"""
    pricing = ModelPricing(
        provider=provider,
        model=model,
        input_price=input_price,
        output_price=output_price,
        currency=currency,
        cache_read_price=cache_read_price,
        cache_write_price=cache_write_price,
        is_active=True,
    )
    db_session.add(pricing)
    db_session.commit()
    db_session.refresh(pricing)
    return pricing


# ==================== 写入 usage_records 表测试 ====================


class TestRecordLlmCallWritesUsageRecords:
    """验证 record_llm_call 能正确写入 usage_records 表"""

    async def test_record_llm_call_writes_usage_records(
        self, usage_tracker, db_session
    ):
        """调用后 usage_records 表应有新记录，字段值与传入参数一致"""
        _make_pricing(db_session, input_price=10.0, output_price=30.0)

        breakdown = TokenBreakdown(
            input_tokens=1000,
            output_tokens=500,
            method="api_usage",
            estimated=False,
        )

        call_id = await usage_tracker.record_llm_call(
            user_id=42,
            session_id="sess-test-1",
            provider="openai",
            model="gpt-4o",
            token_breakdown=breakdown,
            duration_ms=1200,
        )

        assert call_id is not None
        assert call_id.startswith("call_")

        # 查询 DB 验证记录
        records = db_session.query(UsageRecord).all()
        assert len(records) == 1

        record = records[0]
        assert record.call_id == call_id
        assert record.user_id == "42"  # user_id 统一转 str
        assert record.session_id == "sess-test-1"
        assert record.provider == "openai"
        assert record.model == "gpt-4o"
        assert record.input_tokens == 1000
        assert record.output_tokens == 500
        assert record.duration_ms == 1200
        assert record.cache_hit is False

        # 成本：input 1000 * 10 / 1e6 = 0.01, output 500 * 30 / 1e6 = 0.015
        assert record.input_cost == pytest.approx(0.01, rel=1e-6)
        assert record.output_cost == pytest.approx(0.015, rel=1e-6)
        assert record.total_cost == pytest.approx(0.025, rel=1e-6)


# ==================== 成本计算公式测试 ====================


class TestRecordLlmCallCalculatesCost:
    """验证 record_llm_call 的成本计算公式"""

    async def test_record_llm_call_calculates_cost_correctly(
        self, usage_tracker, db_session
    ):
        """验证 input/output 成本计算公式：tokens * price / 1e6"""
        _make_pricing(
            db_session,
            input_price=5.0,    # 5 USD / 百万 token
            output_price=15.0,  # 15 USD / 百万 token
        )

        breakdown = TokenBreakdown(
            input_tokens=2000,
            output_tokens=1000,
            method="api_usage",
            estimated=False,
        )

        await usage_tracker.record_llm_call(
            user_id="user-1",
            session_id="sess-1",
            provider="openai",
            model="gpt-4o",
            token_breakdown=breakdown,
        )

        record = db_session.query(UsageRecord).first()
        # input: 2000 * 5 / 1e6 = 0.01
        # output: 1000 * 15 / 1e6 = 0.015
        # total: 0.025
        assert record.input_cost == pytest.approx(0.01, rel=1e-6)
        assert record.output_cost == pytest.approx(0.015, rel=1e-6)
        assert record.total_cost == pytest.approx(0.025, rel=1e-6)

    async def test_record_llm_call_with_cache_tokens(
        self, usage_tracker, db_session
    ):
        """含 cache_read_tokens / cache_write_tokens 的成本计算"""
        _make_pricing(
            db_session,
            input_price=5.0,
            output_price=15.0,
            cache_read_price=0.5,   # 缓存读取单价（比 input 便宜）
            cache_write_price=6.25,  # 缓存写入单价（比 input 略贵）
        )

        breakdown = TokenBreakdown(
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=800,
            cache_write_tokens=200,
            method="api_usage",
            estimated=False,
        )

        await usage_tracker.record_llm_call(
            user_id="user-1",
            session_id="sess-1",
            provider="openai",
            model="gpt-4o",
            token_breakdown=breakdown,
        )

        record = db_session.query(UsageRecord).first()

        # 预期成本：
        # input: 1000 * 5 / 1e6 = 0.005
        # output: 500 * 15 / 1e6 = 0.0075
        # cache_read: 800 * 0.5 / 1e6 = 0.0004
        # cache_write: 200 * 6.25 / 1e6 = 0.00125
        # folded_input = input + cache_read + cache_write = 0.005 + 0.0004 + 0.00125 = 0.00665
        # total = folded_input + output = 0.00665 + 0.0075 = 0.01415
        expected_folded_input = 0.005 + 0.0004 + 0.00125
        assert record.input_cost == pytest.approx(expected_folded_input, rel=1e-5)
        assert record.output_cost == pytest.approx(0.0075, rel=1e-6)
        assert record.total_cost == pytest.approx(
            expected_folded_input + 0.0075, rel=1e-5
        )

        # cache_hit 标记应为 True（因为 cache_read_tokens > 0）
        assert record.cache_hit is True

        # extra_data 应包含完整明细
        extra = json.loads(record.extra_data)
        assert extra["input_cost"] == pytest.approx(0.005, rel=1e-6)
        assert extra["output_cost"] == pytest.approx(0.0075, rel=1e-6)
        assert extra["cache_read_cost"] == pytest.approx(0.0004, rel=1e-6)
        assert extra["cache_write_cost"] == pytest.approx(0.00125, rel=1e-6)
        assert extra["cache_read_tokens"] == 800
        assert extra["cache_write_tokens"] == 200


# ==================== ENABLE_BILLING 开关测试 ====================


class TestRecordLlmCallBillingSwitch:
    """验证 ENABLE_BILLING 开关行为"""

    async def test_record_llm_call_disabled_when_billing_off(
        self, usage_tracker, db_session
    ):
        """ENABLE_BILLING=False 时应跳过计费，不写入 usage_records"""
        _make_pricing(db_session)

        breakdown = TokenBreakdown(input_tokens=100, output_tokens=50)

        with patch("config.settings.settings.ENABLE_BILLING", False):
            call_id = await usage_tracker.record_llm_call(
                user_id="user-1",
                session_id="sess-1",
                provider="openai",
                model="gpt-4o",
                token_breakdown=breakdown,
            )

        assert call_id is None
        # 不应写入任何记录
        assert db_session.query(UsageRecord).count() == 0


# ==================== 异常处理测试 ====================


class TestRecordLlmCallErrorHandling:
    """验证 record_llm_call 的异常隔离行为"""

    async def test_record_llm_call_does_not_propagate_errors(
        self, usage_tracker, db_session
    ):
        """pricing 查询失败时不抛异常，返回 None"""
        _make_pricing(db_session)

        breakdown = TokenBreakdown(input_tokens=100, output_tokens=50)

        # mock PricingManager.get_pricing 抛异常
        with patch(
            "billing.pricing_manager.PricingManager.get_pricing",
            side_effect=RuntimeError("模拟定价查询失败"),
        ):
            call_id = await usage_tracker.record_llm_call(
                user_id="user-1",
                session_id="sess-1",
                provider="openai",
                model="gpt-4o",
                token_breakdown=breakdown,
            )

        # 不抛异常，返回 None
        assert call_id is None
        # 不应写入记录
        assert db_session.query(UsageRecord).count() == 0


# ==================== pricing 为 None / NULL 字段测试 ====================


class TestCalculateCostHandlesNullPricing:
    """验证 _calculate_cost 在 pricing 缺失或字段为 NULL 时的容错"""

    def test_calculate_cost_handles_null_pricing(self, usage_tracker):
        """pricing 为 None 时所有成本按 0 处理"""
        breakdown = TokenBreakdown(
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=200,
            cache_write_tokens=100,
        )

        cost = usage_tracker._calculate_cost(breakdown, None)

        assert cost["input_cost"] == 0.0
        assert cost["output_cost"] == 0.0
        assert cost["cache_read_cost"] == 0.0
        assert cost["cache_write_cost"] == 0.0
        assert cost["total_cost"] == 0.0

    def test_calculate_cost_handles_null_pricing_fields(
        self, usage_tracker, db_session
    ):
        """pricing 字段为 NULL 时按 0 处理（cache_read_price / cache_write_price 为 None）"""
        # 创建 pricing，cache_read_price 和 cache_write_price 为 None
        pricing = _make_pricing(
            db_session,
            input_price=5.0,
            output_price=15.0,
            cache_read_price=None,
            cache_write_price=None,
        )

        breakdown = TokenBreakdown(
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=800,
            cache_write_tokens=200,
        )

        cost = usage_tracker._calculate_cost(breakdown, pricing)

        # input / output 正常计算
        assert cost["input_cost"] == pytest.approx(0.005, rel=1e-6)
        assert cost["output_cost"] == pytest.approx(0.0075, rel=1e-6)
        # cache 字段为 NULL，按 0 处理
        assert cost["cache_read_cost"] == 0.0
        assert cost["cache_write_cost"] == 0.0
        # total = input + output + 0 + 0
        assert cost["total_cost"] == pytest.approx(0.0125, rel=1e-6)

    def test_calculate_cost_with_zero_pricing(self, usage_tracker, db_session):
        """pricing 字段为 0（免费模型）时成本应为 0，不被 or 陷阱误判"""
        pricing = _make_pricing(
            db_session,
            input_price=0.0,
            output_price=0.0,
            cache_read_price=0.0,
            cache_write_price=0.0,
        )

        breakdown = TokenBreakdown(
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=200,
            cache_write_tokens=100,
        )

        cost = usage_tracker._calculate_cost(breakdown, pricing)

        # 所有成本应为 0（免费模型）
        assert cost["input_cost"] == 0.0
        assert cost["output_cost"] == 0.0
        assert cost["cache_read_cost"] == 0.0
        assert cost["cache_write_cost"] == 0.0
        assert cost["total_cost"] == 0.0

    async def test_record_llm_call_with_no_pricing_record(
        self, usage_tracker, db_session
    ):
        """pricing 记录不存在时仍写入 usage_records（成本为 0），不抛异常"""
        # 不创建 pricing 记录
        breakdown = TokenBreakdown(input_tokens=100, output_tokens=50)

        call_id = await usage_tracker.record_llm_call(
            user_id="user-1",
            session_id="sess-1",
            provider="unknown_provider",
            model="unknown_model",
            token_breakdown=breakdown,
        )

        # 应返回 call_id（记录写入成功），成本为 0
        assert call_id is not None
        record = db_session.query(UsageRecord).first()
        assert record is not None
        assert record.input_cost == 0.0
        assert record.output_cost == 0.0
        assert record.total_cost == 0.0
        assert record.input_tokens == 100
        assert record.output_tokens == 50


# ==================== 预算扣减与预警触发测试 ====================


class TestRecordLlmCallTriggersBudgetAndAlert:
    """验证 record_llm_call 触发预算扣减与预警检查"""

    async def test_record_llm_call_triggers_budget_deduct(
        self, usage_tracker, db_session
    ):
        """验证预算扣减：写入 usage_records 表即完成扣减

        BudgetManager 没有 deduct 方法，预算通过 usage_records 表的
        total_cost 聚合动态计算。写入记录 = 扣减预算。
        """
        _make_pricing(db_session, input_price=10.0, output_price=30.0)

        breakdown = TokenBreakdown(input_tokens=1000, output_tokens=500)

        await usage_tracker.record_llm_call(
            user_id="user-budget-1",
            session_id="sess-budget",
            provider="openai",
            model="gpt-4o",
            token_breakdown=breakdown,
        )

        # 验证 usage_records 表有记录（即预算被扣减）
        records = db_session.query(UsageRecord).filter(
            UsageRecord.user_id == "user-budget-1"
        ).all()
        assert len(records) == 1
        # total_cost > 0 表示实际扣减了预算
        assert records[0].total_cost > 0

    async def test_record_llm_call_triggers_alert_check(
        self, usage_tracker, db_session
    ):
        """验证 AlertManager.check_and_alert 被调用（mock BudgetAlertService）"""
        _make_pricing(db_session)

        breakdown = TokenBreakdown(input_tokens=100, output_tokens=50)

        # mock BudgetAlertService.check_and_generate_alerts 验证被调用
        with patch(
            "billing.alerts.BudgetAlertService.check_and_generate_alerts"
        ) as mock_check:
            mock_check.return_value = []
            await usage_tracker.record_llm_call(
                user_id="user-alert-1",
                session_id="sess-alert",
                provider="openai",
                model="gpt-4o",
                token_breakdown=breakdown,
            )

            # 验证预警检查被调用，且传入正确的 user_id
            mock_check.assert_called_once_with("user-alert-1")

    async def test_record_llm_call_alert_check_failure_does_not_propagate(
        self, usage_tracker, db_session
    ):
        """预警检查失败时不传播，计费记录仍应写入"""
        _make_pricing(db_session)

        breakdown = TokenBreakdown(input_tokens=100, output_tokens=50)

        with patch(
            "billing.alerts.BudgetAlertService.check_and_generate_alerts",
            side_effect=RuntimeError("模拟预警检查失败"),
        ):
            call_id = await usage_tracker.record_llm_call(
                user_id="user-alert-2",
                session_id="sess-alert-2",
                provider="openai",
                model="gpt-4o",
                token_breakdown=breakdown,
            )

        # 预警失败不影响计费记录写入
        assert call_id is not None
        assert db_session.query(UsageRecord).count() == 1


# ==================== 边界场景测试 ====================


class TestRecordLlmCallEdgeCases:
    """验证 record_llm_call 的边界场景"""

    async def test_record_llm_call_with_empty_user_id_skipped(
        self, usage_tracker, db_session
    ):
        """user_id 为空时应跳过，不写入记录"""
        _make_pricing(db_session)

        breakdown = TokenBreakdown(input_tokens=100, output_tokens=50)

        call_id = await usage_tracker.record_llm_call(
            user_id="",
            session_id="sess-1",
            provider="openai",
            model="gpt-4o",
            token_breakdown=breakdown,
        )

        assert call_id is None
        assert db_session.query(UsageRecord).count() == 0

    async def test_record_llm_call_with_none_user_id_skipped(
        self, usage_tracker, db_session
    ):
        """user_id 为 None 时应跳过"""
        _make_pricing(db_session)

        breakdown = TokenBreakdown(input_tokens=100, output_tokens=50)

        call_id = await usage_tracker.record_llm_call(
            user_id=None,
            session_id="sess-1",
            provider="openai",
            model="gpt-4o",
            token_breakdown=breakdown,
        )

        assert call_id is None
        assert db_session.query(UsageRecord).count() == 0

    async def test_record_llm_call_with_int_user_id_converted_to_str(
        self, usage_tracker, db_session
    ):
        """int 类型 user_id 应转为 str 存储（DB schema 为 String）"""
        _make_pricing(db_session)

        breakdown = TokenBreakdown(input_tokens=100, output_tokens=50)

        await usage_tracker.record_llm_call(
            user_id=12345,
            session_id="sess-1",
            provider="openai",
            model="gpt-4o",
            token_breakdown=breakdown,
        )

        record = db_session.query(UsageRecord).first()
        assert record.user_id == "12345"

    async def test_record_llm_call_with_custom_currency(
        self, usage_tracker, db_session
    ):
        """pricing 配置 CNY 货币时应写入 UsageRecord.currency"""
        _make_pricing(db_session, currency="CNY")

        breakdown = TokenBreakdown(input_tokens=100, output_tokens=50)

        await usage_tracker.record_llm_call(
            user_id="user-1",
            session_id="sess-1",
            provider="openai",
            model="gpt-4o",
            token_breakdown=breakdown,
        )

        record = db_session.query(UsageRecord).first()
        assert record.currency == "CNY"

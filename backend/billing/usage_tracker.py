"""Usage 追踪与计费扣减模块

在 Agent 流程 _schedule_record 中调用，将 token 用量与成本持久化到 usage_records 表，
并触发预算扣减与预警。

与 billing/tracker.py 中 UsageTracker 的关系：
- 继承现有 UsageTracker，复用 create_usage_record / _update_user_summary 等方法
- 扩展 record_llm_call：接受 TokenBreakdown，自动计算成本、写入 usage_records、触发预警
- _calculate_cost：按 cherry-studio 公式计算 input/output/cache_read/cache_write 四项成本

设计约束：
- 计费失败必须显式传播（计费记录是资金敏感数据，禁止静默吞掉后按 0 计费）
- ENABLE_BILLING=False 时跳过计费
- pricing 缺失或字段损坏时抛出 PricingUnavailableError，禁止按 0 计费（免费计费漏洞）
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from billing.token_counter import TokenBreakdown
from billing.tracker import UsageTracker as _BaseUsageTracker

logger = logging.getLogger(__name__)


class PricingUnavailableError(RuntimeError):
    """定价配置缺失或损坏，无法计算成本。

    计费是资金敏感路径：定价不可用时必须显式报错，
    禁止静默按 0 计费导致免费计费漏洞。
    """


class UsageTracker(_BaseUsageTracker):
    """扩展的 Usage 追踪器，含成本计算与预算扣减

    继承自 billing.tracker.UsageTracker，复用 create_usage_record 写入 usage_records 表，
    新增 record_llm_call 方法用于 Agent 流程的计费扣减闭环。
    """

    def __init__(self, db: Session):
        """初始化追踪器，绑定数据库会话。

        Args:
            db: 同步 SQLAlchemy 会话（与现有 tracker.py 保持一致）。
        """
        super().__init__(db)

    async def record_llm_call(
        self,
        *,
        user_id: Any,
        session_id: str,
        provider: str,
        model: str,
        token_breakdown: TokenBreakdown,
        duration_ms: int = 0,
        content_type: str = "chat",
    ) -> Optional[str]:
        """记录一次 LLM 调用的 token 用量与成本

        流程：
        1. 检查 ENABLE_BILLING 开关，关闭则跳过
        2. 查询 PricingManager.get_pricing(provider, model) 获取单价
        3. 计算 input_cost / output_cost / cache_read_cost / cache_write_cost / total_cost
        4. 调用 self.create_usage_record() 写入 usage_records 表（含预算汇总原子更新）
        5. 调用 BudgetAlertService.check_and_generate_alerts 检查预警
        6. 返回 call_id

        异常处理：计费失败（含定价缺失、DB 写入失败）显式传播异常，
        由调用方感知（调用方在后台任务中调用时通过 done callback 记录）。

        Args:
            user_id: 用户 ID（int 或 str，内部统一转 str）。
            session_id: 会话 ID。
            provider: 供应商名称（如 openai / anthropic）。
            model: 模型名称。
            token_breakdown: Token 计数明细，含 input/output/cache 维度。
            duration_ms: 调用耗时（毫秒）。
            content_type: 内容类型，默认 chat。

        Returns:
            成功时返回 call_id（如 "call_xxx"），跳过计费时返回 None。

        Raises:
            PricingUnavailableError: 定价缺失或字段损坏（禁止按 0 计费）。
            Exception: 计费记录写入失败等真实错误。
        """
        # 1. 检查 ENABLE_BILLING 开关
        from config.settings import settings
        if not getattr(settings, "ENABLE_BILLING", True):
            logger.debug("ENABLE_BILLING=False，跳过计费记录")
            return None

        # user_id 统一转 str（DB schema 为 String）
        user_id_str = str(user_id) if user_id is not None else ""
        if not user_id_str or not user_id_str.strip():
            logger.debug("user_id 为空，跳过计费记录")
            return None

        # 2. 查询定价（缺失时抛出 PricingUnavailableError）
        pricing = self._get_pricing(provider, model)

        # 3. 计算成本
        cost = self._calculate_cost(token_breakdown, pricing)

        # 4. 写入 usage_records 表
        # 将 cache_read_cost + cache_write_cost 折入 input_cost，
        # 保证 base 类的 total_cost = input_cost + output_cost 正确
        # 完整明细存入 metadata.extra_data 便于审计
        folded_input_cost = (
            cost["input_cost"]
            + cost["cache_read_cost"]
            + cost["cache_write_cost"]
        )
        cache_hit = token_breakdown.cache_read_tokens > 0

        metadata = {
            "input_cost": cost["input_cost"],
            "output_cost": cost["output_cost"],
            "cache_read_cost": cost["cache_read_cost"],
            "cache_write_cost": cost["cache_write_cost"],
            "cache_read_tokens": token_breakdown.cache_read_tokens,
            "cache_write_tokens": token_breakdown.cache_write_tokens,
            "thoughts_tokens": token_breakdown.thoughts_tokens,
            "method": token_breakdown.method,
            "estimated": token_breakdown.estimated,
        }

        currency = self._extract_currency(pricing)

        record = self.create_usage_record(
            user_id=user_id_str,
            session_id=session_id,
            provider=provider,
            model=model,
            content_type=content_type,
            input_tokens=token_breakdown.input_tokens,
            output_tokens=token_breakdown.output_tokens,
            input_cost=folded_input_cost,
            output_cost=cost["output_cost"],
            currency=currency,
            cache_hit=cache_hit,
            duration_ms=duration_ms,
            metadata=metadata,
        )

        call_id = record.call_id if record else None

        # 5. 触发预警检查（计费扣减已通过 usage_records 写入完成）
        self._trigger_alert_check(user_id_str)

        return call_id

    def _get_pricing(self, provider: str, model: str) -> Optional[Any]:
        """查询指定 provider/model 的定价配置

        延迟导入 PricingManager 避免循环依赖。
        定价缺失（返回 None）时由 _calculate_cost 抛出 PricingUnavailableError，
        禁止写入 0 成本记录。

        Args:
            provider: 供应商名称。
            model: 模型名称。

        Returns:
            ModelPricing ORM 对象，或 None（未配置定价，上层抛 PricingUnavailableError）。

        Raises:
            Exception: 定价查询过程中发生异常（显式传播）。
        """
        from billing.pricing_manager import PricingManager
        pricing_manager = PricingManager(self.db)
        return pricing_manager.get_pricing(provider, model)

    def _extract_currency(self, pricing: Optional[Any]) -> str:
        """从定价对象提取货币单位，未配置时默认 USD

        Args:
            pricing: ModelPricing ORM 对象或 None。

        Returns:
            货币字符串（USD / CNY）。
        """
        if pricing is None:
            return "USD"
        currency = getattr(pricing, "currency", None)
        if currency is None or not str(currency).strip():
            return "USD"
        return str(currency)

    def _calculate_cost(
        self,
        breakdown: TokenBreakdown,
        pricing: Optional[Any],
    ) -> Dict[str, float]:
        """计算成本

        公式（单价单位：USD / 百万 token）：
        - input_cost = input_tokens * input_price / 1e6
        - output_cost = output_tokens * output_price / 1e6
        - cache_read_cost = cache_read_tokens * cache_read_price / 1e6
        - cache_write_cost = cache_write_tokens * cache_write_price / 1e6
        - total_cost = input_cost + output_cost + cache_read_cost + cache_write_cost

        pricing 为 None，或必填定价字段（input_price/output_price）缺失/损坏时，
        抛出 PricingUnavailableError，禁止按 0 计费（免费计费漏洞）。
        可选缓存单价字段（cache_read_price/cache_write_price，DB 可空）
        为 None 表示"未配置缓存单价"，按 0 处理属合法语义。

        Args:
            breakdown: Token 计数明细。
            pricing: ModelPricing ORM 对象或 None。

        Returns:
            成本字典，含 input_cost / output_cost / cache_read_cost /
            cache_write_cost / total_cost 五个键。

        Raises:
            PricingUnavailableError: 定价缺失或必填字段损坏。
        """
        if pricing is None:
            raise PricingUnavailableError(
                "未配置模型定价，无法计算成本（禁止按 0 计费）"
            )

        input_price = self._safe_pricing_value(
            getattr(pricing, "input_price", None), "input_price"
        )
        output_price = self._safe_pricing_value(
            getattr(pricing, "output_price", None), "output_price"
        )
        cache_read_price = self._safe_optional_pricing_value(
            getattr(pricing, "cache_read_price", None), "cache_read_price"
        )
        cache_write_price = self._safe_optional_pricing_value(
            getattr(pricing, "cache_write_price", None), "cache_write_price"
        )

        input_cost = breakdown.input_tokens * input_price / 1_000_000
        output_cost = breakdown.output_tokens * output_price / 1_000_000
        cache_read_cost = breakdown.cache_read_tokens * cache_read_price / 1_000_000
        cache_write_cost = breakdown.cache_write_tokens * cache_write_price / 1_000_000
        total_cost = input_cost + output_cost + cache_read_cost + cache_write_cost

        return {
            "input_cost": round(input_cost, 8),
            "output_cost": round(output_cost, 8),
            "cache_read_cost": round(cache_read_cost, 8),
            "cache_write_cost": round(cache_write_cost, 8),
            "total_cost": round(total_cost, 8),
        }

    @staticmethod
    def _safe_pricing_value(value: Any, field_name: str) -> float:
        """提取必填定价字段；缺失或损坏时抛出 PricingUnavailableError

        input_price/output_price 是 DB 非空列，为 None 或无法转换为数值时
        说明定价数据损坏，必须显式报错，禁止静默按 0 计费（免费计费漏洞）。
        字段值为 0（免费模型）是合法值，正常返回 0.0。

        Args:
            value: 原始字段值（int / float / None）。
            field_name: 字段名（用于错误信息）。

        Returns:
            float 类型的单价。

        Raises:
            PricingUnavailableError: 字段为 None 或无法转换为数值。
        """
        if value is None:
            raise PricingUnavailableError(
                f"必填定价字段 {field_name} 缺失（None），无法计算成本（禁止按 0 计费）"
            )
        try:
            return float(value)
        except (TypeError, ValueError):
            raise PricingUnavailableError(
                f"定价字段 {field_name} 损坏，无法转换为数值: {value!r}（禁止按 0 计费）"
            ) from None

    @staticmethod
    def _safe_optional_pricing_value(value: Any, field_name: str) -> float:
        """提取可选定价字段；None 视为未配置（按 0 处理），损坏时报错

        cache_read_price/cache_write_price 是 DB 可空列，None 表示
        "未配置缓存单价"，按 0 处理是合法业务语义；
        但字段损坏（无法转换数值）仍必须显式报错，不得静默按 0。

        Args:
            value: 原始字段值（int / float / None）。
            field_name: 字段名（用于错误信息）。

        Returns:
            float 类型的单价。

        Raises:
            PricingUnavailableError: 字段损坏（无法转换为数值）。
        """
        if value is None:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            raise PricingUnavailableError(
                f"定价字段 {field_name} 损坏，无法转换为数值: {value!r}"
            ) from None

    def _trigger_alert_check(self, user_id: str) -> None:
        """触发预算预警检查

        延迟导入 BudgetAlertService 避免循环依赖。
        预警检查失败不传播，仅记录警告（计费记录已写入，预警是附加行为）。

        Args:
            user_id: 用户 ID。
        """
        try:
            from billing.alerts import BudgetAlertService
            alert_service = BudgetAlertService(self.db)
            alert_service.check_and_generate_alerts(user_id)
        except Exception as exc:
            logger.warning(
                "预警检查失败 user_id=%s: %s",
                user_id, exc,
            )

"""Usage 追踪与计费扣减模块

在 Agent 流程 _schedule_record 中调用，将 token 用量与成本持久化到 usage_records 表，
并触发预算扣减与预警。

与 billing/tracker.py 中 UsageTracker 的关系：
- 继承现有 UsageTracker，复用 create_usage_record / _update_user_summary 等方法
- 扩展 record_llm_call：接受 TokenBreakdown，自动计算成本、写入 usage_records、触发预警
- _calculate_cost：按 cherry-studio 公式计算 input/output/cache_read/cache_write 四项成本

设计约束：
- 计费失败不能影响 Agent 主流程（catch + log，不 raise）
- ENABLE_BILLING=False 时跳过计费
- pricing 字段为 NULL 时按 0 处理（使用 is not None 检查，避免 or 陷阱）
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from billing.token_counter import TokenBreakdown
from billing.tracker import UsageTracker as _BaseUsageTracker

logger = logging.getLogger(__name__)


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

        异常处理：计费失败不传播，仅记录 ERROR 日志，返回 None，不影响 Agent 主流程。

        Args:
            user_id: 用户 ID（int 或 str，内部统一转 str）。
            session_id: 会话 ID。
            provider: 供应商名称（如 openai / anthropic）。
            model: 模型名称。
            token_breakdown: Token 计数明细，含 input/output/cache 维度。
            duration_ms: 调用耗时（毫秒）。
            content_type: 内容类型，默认 chat。

        Returns:
            成功时返回 call_id（如 "call_xxx"），跳过或失败时返回 None。
        """
        # 1. 检查 ENABLE_BILLING 开关
        try:
            from config.settings import settings
            if not getattr(settings, "ENABLE_BILLING", True):
                logger.debug("ENABLE_BILLING=False，跳过计费记录")
                return None
        except Exception as exc:
            # settings 加载失败时默认开启计费，但记录警告
            logger.warning("读取 ENABLE_BILLING 配置失败，按默认开启处理: %s", exc)

        # user_id 统一转 str（DB schema 为 String）
        user_id_str = str(user_id) if user_id is not None else ""
        if not user_id_str or not user_id_str.strip():
            logger.debug("user_id 为空，跳过计费记录")
            return None

        try:
            # 2. 查询定价
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

        except Exception as exc:
            # 计费失败不传播，仅记录 ERROR 日志
            logger.error(
                "计费扣减失败 user_id=%s provider=%s model=%s: %s",
                user_id_str, provider, model, exc,
                exc_info=True,
            )
            return None

    def _get_pricing(self, provider: str, model: str) -> Optional[Any]:
        """查询指定 provider/model 的定价配置

        延迟导入 PricingManager 避免循环依赖。
        不在此处捕获异常：定价查询失败应传播到 record_llm_call 的外层 try/except，
        由其统一记录 ERROR 日志并返回 None（计费失败语义）。
        返回 None 仅表示"未配置定价"（非异常），此时仍写入 0 成本记录。

        Args:
            provider: 供应商名称。
            model: 模型名称。

        Returns:
            ModelPricing ORM 对象，或 None（未配置定价）。

        Raises:
            Exception: 定价查询过程中发生异常（由上层捕获）。
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
        - cache_read_cost = cache_read_tokens * (cache_read_price or 0) / 1e6
        - cache_write_cost = cache_write_tokens * (cache_write_price or 0) / 1e6
        - total_cost = input_cost + output_cost + cache_read_cost + cache_write_cost

        pricing 为 None 时所有成本按 0 处理（仍记录 token 用量）。
        定价字段为 NULL 时按 0 处理（使用 _safe_pricing_value 避免 or 陷阱）。

        Args:
            breakdown: Token 计数明细。
            pricing: ModelPricing ORM 对象或 None。

        Returns:
            成本字典，含 input_cost / output_cost / cache_read_cost /
            cache_write_cost / total_cost 五个键。
        """
        if pricing is None:
            return {
                "input_cost": 0.0,
                "output_cost": 0.0,
                "cache_read_cost": 0.0,
                "cache_write_cost": 0.0,
                "total_cost": 0.0,
            }

        input_price = self._safe_pricing_value(getattr(pricing, "input_price", None))
        output_price = self._safe_pricing_value(getattr(pricing, "output_price", None))
        cache_read_price = self._safe_pricing_value(getattr(pricing, "cache_read_price", None))
        cache_write_price = self._safe_pricing_value(getattr(pricing, "cache_write_price", None))

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
    def _safe_pricing_value(value: Any) -> float:
        """安全提取定价字段值，None 视为 0

        避免 `getattr(x, 'field', 0) or 0` 的 or 陷阱：
        当字段值为 0（免费模型）时，`0 or 0` 仍返回 0，结果正确；
        但当字段值为 None（未配置）时，`None or 0` 也返回 0。
        使用 is not None 检查更明确，符合项目规范。

        Args:
            value: 原始字段值（int / float / None）。

        Returns:
            float 类型的单价，None 时返回 0.0。
        """
        if value is None:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

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

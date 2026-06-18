"""
计费用量预警与成本优化建议模块。
负责检测预算阈值、生成预警事件、提供成本优化建议。
"""
from __future__ import annotations

from datetime import date, timedelta, timezone
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from billing.budget_manager import BudgetManager
from billing.models import BudgetConfig, UsageRecord
from billing.tracker import UsageTracker


class BudgetAlertService:
    """
    预算预警服务：检测预算阈值、生成预警事件、查询预警状态。
    预警事件通过内存队列暂存，前端通过 /api/billing/alerts 拉取。
    """

    def __init__(self, db: Session):
        self.db = db
        self.budget_manager = BudgetManager(db)
        self.tracker = UsageTracker(db)

    def check_and_generate_alerts(self, user_id: str) -> List[Dict[str, Any]]:
        """
        检查用户预算状态，生成预警事件列表。
        预警级别：info（50%）、warning（80%）、critical（95%）、exceeded（100%）。
        """
        alerts: List[Dict[str, Any]] = []
        status = self.budget_manager.get_budget_status(user_id)

        if not status.get("has_budget_configured"):
            return alerts

        usage_pct = status.get("usage_percentage", 0)
        warning_threshold = status.get("warning_threshold", 0.8) * 100

        # 预算超支
        if status.get("is_exceeded"):
            alerts.append(self._build_alert(
                level="critical",
                title="预算已超支",
                message=f"当前周期用量 {status['current_usage']} {status.get('currency', 'USD')}，"
                        f"已超过预算上限 {status['max_amount']}",
                user_id=user_id,
                status=status,
            ))
        # 临界预警（95%）
        elif usage_pct >= 95:
            alerts.append(self._build_alert(
                level="critical",
                title="预算即将耗尽",
                message=f"当前用量已达预算的 {usage_pct}%，请立即关注",
                user_id=user_id,
                status=status,
            ))
        # 警告（达到阈值）
        elif usage_pct >= warning_threshold:
            alerts.append(self._build_alert(
                level="warning",
                title="预算达到预警阈值",
                message=f"当前用量已达预算的 {usage_pct}%（阈值 {warning_threshold}%）",
                user_id=user_id,
                status=status,
            ))
        # 提示（50%）
        elif usage_pct >= 50:
            alerts.append(self._build_alert(
                level="info",
                title="预算使用过半",
                message=f"当前用量已达预算的 {usage_pct}%",
                user_id=user_id,
                status=status,
            ))

        return alerts

    def get_active_alerts(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取当前活跃的预警事件。
        本实现基于实时预算状态计算，不持久化历史预警。
        """
        if user_id:
            return self.check_and_generate_alerts(user_id)

        # 查询所有有预算的用户
        budgets = self.db.query(BudgetConfig).filter(
            and_(
                BudgetConfig.is_active == True,
                BudgetConfig.budget_type == "user",
            )
        ).all()

        all_alerts: List[Dict[str, Any]] = []
        for budget in budgets:
            if budget.scope_id:
                all_alerts.extend(self.check_and_generate_alerts(budget.scope_id))
        return all_alerts

    def _build_alert(
        self,
        level: str,
        title: str,
        message: str,
        user_id: str,
        status: Dict[str, Any],
    ) -> Dict[str, Any]:
        """构建预警事件结构。"""
        return {
            "level": level,
            "title": title,
            "message": message,
            "user_id": user_id,
            "usage_percentage": status.get("usage_percentage", 0),
            "current_usage": status.get("current_usage", 0),
            "max_amount": status.get("max_amount", 0),
            "currency": status.get("currency", "USD"),
            "period_type": status.get("period_type", "monthly"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


class CostOptimizationService:
    """
    成本优化建议服务：基于历史用量分析，提供性价比模型推荐、
    缓存命中率统计与优化建议、闲置模型检测。
    """

    def __init__(self, db: Session):
        self.db = db
        self.tracker = UsageTracker(db)

    def get_optimization_suggestions(self, user_id: str) -> Dict[str, Any]:
        """生成综合成本优化建议报告。"""
        end_date = date.today()
        start_date = end_date - timedelta(days=30)

        suggestions: List[Dict[str, Any]] = []

        # 1. 模型性价比分析
        model_stats = self._get_model_usage_stats(user_id, start_date, end_date)
        model_suggestion = self._analyze_model_cost_efficiency(model_stats)
        if model_suggestion:
            suggestions.append(model_suggestion)

        # 2. 缓存命中率分析
        cache_stats = self._get_cache_stats(user_id, start_date, end_date)
        cache_suggestion = self._analyze_cache_efficiency(cache_stats)
        if cache_suggestion:
            suggestions.append(cache_suggestion)

        # 3. 闲置模型检测
        idle_models = self._detect_idle_models(user_id, model_stats)
        if idle_models:
            suggestions.append({
                "type": "idle_models",
                "title": "检测到闲置模型配置",
                "message": f"以下模型在过去 30 天内无调用记录，可考虑清理：{', '.join(idle_models)}",
                "impact": "low",
                "models": idle_models,
            })

        # 4. 高成本模型识别
        expensive = self._identify_expensive_models(model_stats)
        if expensive:
            suggestions.append({
                "type": "expensive_models",
                "title": "高成本模型识别",
                "message": f"以下模型成本占比过高，建议评估替代方案：{', '.join(expensive)}",
                "impact": "medium",
                "models": expensive,
            })

        return {
            "user_id": user_id,
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "suggestions": suggestions,
            "total_suggestions": len(suggestions),
        }

    def _get_model_usage_stats(
        self,
        user_id: str,
        start_date: date,
        end_date: date,
    ) -> List[Dict[str, Any]]:
        """获取按模型分组的用量统计。"""
        try:
            rows = self.db.query(
                UsageRecord.model_name,
                func.sum(UsageRecord.total_cost).label("total_cost"),
                func.sum(UsageRecord.input_tokens).label("total_input"),
                func.sum(UsageRecord.output_tokens).label("total_output"),
                func.count(UsageRecord.id).label("call_count"),
            ).filter(
                and_(
                    UsageRecord.user_id == user_id,
                    UsageRecord.created_at >= start_date,
                    UsageRecord.created_at <= end_date,
                )
            ).group_by(UsageRecord.model_name).all()

            return [
                {
                    "model_name": row.model_name,
                    "total_cost": float(row.total_cost or 0),
                    "total_input": int(row.total_input or 0),
                    "total_output": int(row.total_output or 0),
                    "call_count": int(row.call_count or 0),
                }
                for row in rows
            ]
        except Exception as exc:
            logger.warning(f"获取模型用量统计失败: {exc}")
            return []

    def _analyze_model_cost_efficiency(
        self,
        model_stats: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """分析模型性价比，推荐更优替代方案。"""
        if not model_stats:
            return None

        # 按成本排序，找出最贵的模型
        sorted_stats = sorted(model_stats, key=lambda x: x["total_cost"], reverse=True)
        most_expensive = sorted_stats[0]
        total_cost = sum(s["total_cost"] for s in model_stats)

        if total_cost == 0:
            return None

        cost_ratio = most_expensive["total_cost"] / total_cost
        if cost_ratio < 0.5:
            return None

        # 简单的替代建议规则
        model_name = most_expensive["model_name"] or ""
        alternatives = self._get_cheaper_alternatives(model_name)
        if not alternatives:
            return None

        return {
            "type": "model_efficiency",
            "title": "模型性价比优化建议",
            "message": f"模型 {model_name} 占总成本 {cost_ratio*100:.1f}%，"
                       f"可考虑切换到性价比更高的替代模型：{', '.join(alternatives)}",
            "impact": "high",
            "current_model": model_name,
            "alternatives": alternatives,
            "potential_savings": most_expensive["total_cost"] * 0.3,
        }

    def _get_cheaper_alternatives(self, model_name: str) -> List[str]:
        """根据模型名称推荐更便宜的替代模型。"""
        alternatives: List[str] = []
        name_lower = model_name.lower()

        # GPT-4 系列 -> GPT-4o-mini / GPT-3.5
        if "gpt-4" in name_lower and "mini" not in name_lower:
            alternatives.append("gpt-4o-mini")
        # Claude 3 Opus -> Claude 3.5 Sonnet / Haiku
        elif "claude-3-opus" in name_lower:
            alternatives.extend(["claude-3-5-sonnet", "claude-3-haiku"])
        # DeepSeek-V3 -> DeepSeek-Chat
        elif "deepseek-v3" in name_lower:
            alternatives.append("deepseek-chat")
        # 通义千问 Max -> Turbo
        elif "qwen-max" in name_lower:
            alternatives.append("qwen-turbo")

        return alternatives

    def _get_cache_stats(
        self,
        user_id: str,
        start_date: date,
        end_date: date,
    ) -> Dict[str, Any]:
        """获取缓存命中率统计。"""
        try:
            rows = self.db.query(
                func.sum(UsageRecord.cache_hit_tokens).label("cache_tokens"),
                func.sum(UsageRecord.input_tokens).label("total_input"),
            ).filter(
                and_(
                    UsageRecord.user_id == user_id,
                    UsageRecord.created_at >= start_date,
                    UsageRecord.created_at <= end_date,
                )
            ).first()

            cache_tokens = int(rows.cache_tokens or 0) if rows else 0
            total_input = int(rows.total_input or 0) if rows else 0
            hit_rate = (cache_tokens / total_input * 100) if total_input > 0 else 0

            return {
                "cache_tokens": cache_tokens,
                "total_input": total_input,
                "hit_rate": round(hit_rate, 2),
            }
        except Exception as exc:
            logger.warning(f"获取缓存统计失败: {exc}")
            return {"cache_tokens": 0, "total_input": 0, "hit_rate": 0}

    def _analyze_cache_efficiency(self, cache_stats: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """分析缓存效率，提供优化建议。"""
        hit_rate = cache_stats.get("hit_rate", 0)
        if hit_rate >= 50:
            return None

        if cache_stats.get("total_input", 0) < 1000:
            return None  # 用量太小，不提建议

        return {
            "type": "cache_optimization",
            "title": "缓存命中率优化建议",
            "message": f"当前缓存命中率为 {hit_rate}%，建议启用 prompt 缓存以降低成本。"
                       f"对于重复的系统提示词和上下文，缓存可节省 50%+ 的输入 token 成本。",
            "impact": "medium",
            "current_hit_rate": hit_rate,
            "target_hit_rate": 50,
        }

    def _detect_idle_models(
        self,
        user_id: str,
        model_stats: List[Dict[str, Any]],
    ) -> List[str]:
        """检测闲置模型（有配置但无调用）。"""
        active_models = {s["model_name"] for s in model_stats if s["model_name"]}
        # 从定价配置中获取所有已知模型
        try:
            from billing.pricing_manager import PricingManager
            pricing = PricingManager(self.db)
            all_models = pricing.list_models()
            idle = [m for m in all_models if m not in active_models]
            return idle[:5]  # 最多返回 5 个
        except Exception:
            return []

    def _identify_expensive_models(
        self,
        model_stats: List[Dict[str, Any]],
    ) -> List[str]:
        """识别成本占比过高的模型。"""
        if not model_stats:
            return []
        total_cost = sum(s["total_cost"] for s in model_stats)
        if total_cost == 0:
            return []
        return [
            s["model_name"]
            for s in model_stats
            if s["model_name"] and (s["total_cost"] / total_cost) > 0.4
        ]


# 延迟导入 datetime，避免循环依赖
from datetime import datetime  # noqa: E402

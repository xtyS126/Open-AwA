"""
计费与用量管理模块，负责价格配置、预算控制、用量追踪与报表能力。
这一部分直接关联成本核算、调用统计以及运维观测。
"""

from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from typing import List, Optional, Dict
from datetime import datetime, date, timedelta, timezone
import uuid
import json

from billing.models import UsageRecord, UserUsageSummary


class UsageTracker:
    """
    用量追踪器：负责创建、查询、汇总 LLM 调用用量记录（UsageRecord）和用户用量汇总（UserUsageSummary）。
    所有写操作在调用方统一 commit，保证明细与汇总的事务原子性。
    """
    def __init__(self, db: Session):
        """初始化追踪器，绑定数据库会话。"""
        self.db = db

    def create_usage_record(
        self,
        user_id: str,
        session_id: str,
        provider: str,
        model: str,
        content_type: str,
        input_tokens: int,
        output_tokens: int,
        input_cost: float,
        output_cost: float,
        currency: str = "USD",
        cache_hit: bool = False,
        duration_ms: int = 0,
        metadata: Optional[dict] = None
    ) -> UsageRecord:
        """创建一条 LLM 调用用量记录，同步更新用户月度汇总（同一事务内提交）。"""
        call_id = f"call_{uuid.uuid4().hex[:16]}"
        
        record = UsageRecord(
            call_id=call_id,
            user_id=user_id,
            session_id=session_id,
            provider=provider,
            model=model,
            content_type=content_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_cost=input_cost,
            output_cost=output_cost,
            total_cost=input_cost + output_cost,
            currency=currency,
            cache_hit=cache_hit,
            duration_ms=duration_ms,
            extra_data=json.dumps(metadata) if metadata else None
        )
        
        try:
            self.db.add(record)
            # 先更新汇总，再一次性提交，保证明细与汇总数据原子一致
            self._update_user_summary(user_id, input_tokens, output_tokens, input_cost + output_cost, currency)
            self.db.commit()
            self.db.refresh(record)
        except Exception:
            self.db.rollback()
            raise
        
        return record

    def get_usage_record(self, call_id: str) -> Optional[UsageRecord]:
        """按 call_id 查询单条用量记录，未找到返回 None。"""
        return self.db.query(UsageRecord).filter(UsageRecord.call_id == call_id).first()

    def get_usage_records(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[UsageRecord]:
        """按用户/会话/模型/时间范围多条件查询用量记录列表，支持分页。"""
        query = self.db.query(UsageRecord)
        
        if user_id:
            query = query.filter(UsageRecord.user_id == user_id)
        if session_id:
            query = query.filter(UsageRecord.session_id == session_id)
        if provider:
            query = query.filter(UsageRecord.provider == provider)
        if model:
            query = query.filter(UsageRecord.model == model)
        if start_date:
            query = query.filter(UsageRecord.created_at >= start_date)
        if end_date:
            query = query.filter(UsageRecord.created_at <= end_date)
        
        return query.order_by(UsageRecord.created_at.desc()).offset(offset).limit(limit).all()

    def get_session_usage(self, session_id: str) -> Dict:
        """汇总指定会话的 token 用量和费用，按模型分组返回。使用 SQL 聚合查询避免全量加载。"""
        # 总体聚合：一次查询获取汇总值
        agg = (
            self.db.query(
                func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("total_input"),
                func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("total_output"),
                func.coalesce(func.sum(UsageRecord.total_cost), 0.0).label("total_cost"),
                func.count(UsageRecord.id).label("call_count"),
            )
            .filter(UsageRecord.session_id == session_id)
            .first()
        )

        # 按模型分组聚合
        by_model_rows = (
            self.db.query(
                UsageRecord.provider,
                UsageRecord.model,
                func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(UsageRecord.total_cost), 0.0).label("cost"),
            )
            .filter(UsageRecord.session_id == session_id)
            .group_by(UsageRecord.provider, UsageRecord.model)
            .all()
        )

        by_model = {}
        for row in by_model_rows:
            key = f"{row.provider}:{row.model}"
            by_model[key] = {
                "input_tokens": int(row.input_tokens),
                "output_tokens": int(row.output_tokens),
                "cost": round(float(row.cost), 6),
            }

        return {
            "session_id": session_id,
            "total_input_tokens": int(agg.total_input),
            "total_output_tokens": int(agg.total_output),
            "total_cost": round(float(agg.total_cost), 6),
            "by_model": by_model,
            "call_count": int(agg.call_count),
        }

    def get_user_usage(
        self,
        user_id: str,
        period_start: Optional[date] = None,
        period_end: Optional[date] = None
    ) -> Dict:
        """汇总指定用户在给定时间段内的用量（token/费用），按模型和内容类型分组。默认统计当月。使用 SQL 聚合查询避免全量加载。"""
        if not period_start:
            period_start = date.today().replace(day=1)
        if not period_end:
            period_end = date.today()

        base_filter = and_(
            UsageRecord.user_id == user_id,
            func.date(UsageRecord.created_at) >= period_start,
            func.date(UsageRecord.created_at) <= period_end,
        )

        # 总体聚合
        agg = (
            self.db.query(
                func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("total_input"),
                func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("total_output"),
                func.coalesce(func.sum(UsageRecord.total_cost), 0.0).label("total_cost"),
                func.count(UsageRecord.id).label("call_count"),
            )
            .filter(base_filter)
            .first()
        )

        # 按模型分组聚合
        by_model_rows = (
            self.db.query(
                UsageRecord.provider,
                UsageRecord.model,
                func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(UsageRecord.total_cost), 0.0).label("cost"),
            )
            .filter(base_filter)
            .group_by(UsageRecord.provider, UsageRecord.model)
            .all()
        )

        by_model = {}
        for row in by_model_rows:
            key = f"{row.provider}:{row.model}"
            by_model[key] = {
                "input_tokens": int(row.input_tokens),
                "output_tokens": int(row.output_tokens),
                "cost": round(float(row.cost), 6),
            }

        # 按内容类型分组聚合
        by_content_type_rows = (
            self.db.query(
                UsageRecord.content_type,
                func.coalesce(func.sum(UsageRecord.input_tokens + UsageRecord.output_tokens), 0).label("tokens"),
                func.coalesce(func.sum(UsageRecord.total_cost), 0.0).label("cost"),
            )
            .filter(base_filter)
            .group_by(UsageRecord.content_type)
            .all()
        )

        by_content_type = {}
        for row in by_content_type_rows:
            by_content_type[row.content_type] = {
                "tokens": int(row.tokens),
                "cost": round(float(row.cost), 6),
            }

        return {
            "user_id": user_id,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "total_input_tokens": int(agg.total_input),
            "total_output_tokens": int(agg.total_output),
            "total_cost": round(float(agg.total_cost), 6),
            "by_model": by_model,
            "by_content_type": by_content_type,
            "call_count": int(agg.call_count),
        }

    def get_daily_usage_trend(
        self,
        user_id: Optional[str] = None,
        days: int = 30
    ) -> List[Dict]:
        """获取近 N 天的每日用量趋势（费用/token），支持按用户过滤。默认30天。"""
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)
        
        query = self.db.query(
            func.date(UsageRecord.created_at).label("date"),
            func.sum(UsageRecord.total_cost).label("cost"),
            func.sum(UsageRecord.input_tokens).label("input_tokens"),
            func.sum(UsageRecord.output_tokens).label("output_tokens")
        ).filter(
            UsageRecord.created_at >= start_date
        )
        
        if user_id:
            query = query.filter(UsageRecord.user_id == user_id)
        
        results = query.group_by(func.date(UsageRecord.created_at)).all()
        
        return [
            {
                "date": r.date.isoformat() if hasattr(r.date, 'isoformat') else str(r.date),
                "cost": float(r.cost or 0),
                "input_tokens": int(r.input_tokens or 0),
                "output_tokens": int(r.output_tokens or 0)
            }
            for r in results
        ]

    def _update_user_summary(
        self,
        user_id: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        currency: str
    ):
        """使用数据库级原子 UPDATE 更新用户月度用量汇总，避免并发下的 read-then-write 竞态。不存在时自动创建。"""
        today = date.today()
        period_start = today.replace(day=1)
        
        if today.month == 12:
            period_end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            period_end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
        
        # 使用数据库级原子 UPDATE 避免并发下的 read-then-write 竞态条件
        rows_updated = self.db.query(UserUsageSummary).filter(
            and_(
                UserUsageSummary.user_id == user_id,
                UserUsageSummary.period_start == period_start
            )
        ).update(
            {
                UserUsageSummary.total_input_tokens: UserUsageSummary.total_input_tokens + input_tokens,
                UserUsageSummary.total_output_tokens: UserUsageSummary.total_output_tokens + output_tokens,
                UserUsageSummary.total_cost: UserUsageSummary.total_cost + cost,
            },
            synchronize_session='fetch'
        )

        if rows_updated == 0:
            summary = UserUsageSummary(
                user_id=user_id,
                period_start=period_start,
                period_end=period_end,
                total_input_tokens=input_tokens,
                total_output_tokens=output_tokens,
                total_cost=cost,
                currency=currency
            )
            self.db.add(summary)

        # 注意：不在此处单独 commit，调用方应在所有操作完成后统一提交以保证事务原子性

    def get_usage_statistics(self, user_id: Optional[str] = None) -> Dict:
        """获取全局或按用户的用量统计：总调用次数、总 token、总费用、按 Provider 分组。"""
        query = self.db.query(UsageRecord)
        if user_id:
            query = query.filter(UsageRecord.user_id == user_id)
        
        total_records = query.count()
        total_input_tokens = query.with_entities(func.sum(UsageRecord.input_tokens)).scalar() or 0
        total_output_tokens = query.with_entities(func.sum(UsageRecord.output_tokens)).scalar() or 0
        total_cost = query.with_entities(func.sum(UsageRecord.total_cost)).scalar() or 0
        
        provider_stats = self.db.query(
            UsageRecord.provider,
            func.count(UsageRecord.id).label("count"),
            func.sum(UsageRecord.total_cost).label("cost")
        )
        if user_id:
            provider_stats = provider_stats.filter(UsageRecord.user_id == user_id)
        provider_results = provider_stats.group_by(UsageRecord.provider).all()
        
        return {
            "total_calls": total_records,
            "total_input_tokens": int(total_input_tokens),
            "total_output_tokens": int(total_output_tokens),
            "total_cost": round(float(total_cost), 6),
            "by_provider": [
                {
                    "provider": r.provider,
                    "count": r.count,
                    "cost": float(r.cost or 0)
                }
                for r in provider_results
            ]
        }

    def cleanup_old_records(self, retention_days: int = 365) -> int:
        """删除超过保留天数的用量记录，返回删除条数。默认保留365天。"""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
        
        deleted_count = self.db.query(UsageRecord).filter(
            UsageRecord.created_at < cutoff_date
        ).delete()
        
        self.db.commit()
        return deleted_count

    def get_record_count(self) -> int:
        """返回用量记录总数。"""
        return self.db.query(UsageRecord).count()

    def get_oldest_record_date(self) -> Optional[datetime]:
        """返回最早一条用量记录的创建时间，无记录时返回 None。"""
        record = self.db.query(UsageRecord).order_by(UsageRecord.created_at.asc()).first()
        return record.created_at if record else None

    def get_newest_record_date(self) -> Optional[datetime]:
        """返回最新一条用量记录的创建时间，无记录时返回 None。"""
        record = self.db.query(UsageRecord).order_by(UsageRecord.created_at.desc()).first()
        return record.created_at if record else None

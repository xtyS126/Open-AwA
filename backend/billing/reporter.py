from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from typing import List, Optional, Dict, Any
from datetime import date, timedelta
import csv
import io

from billing.models import UsageRecord
from billing.tracker import UsageTracker
from billing.pricing_manager import PricingManager


class BillingReporter:
    def __init__(self, db: Session):
        self.db = db
        self.tracker = UsageTracker(db)
        self.pricing_manager = PricingManager(db)

    def get_cost_statistics(
        self,
        user_id: Optional[str] = None,
        period: str = "monthly"
    ) -> Dict:
        period_start, period_end = self._get_period_dates(period)
        
        if period_start is None and period_end is None:
            query = self.db.query(UsageRecord)
        else:
            query = self.db.query(UsageRecord).filter(
                and_(
                    func.date(UsageRecord.created_at) >= period_start,
                    func.date(UsageRecord.created_at) <= period_end
                )
            )
        
        if user_id:
            query = query.filter(UsageRecord.user_id == user_id)
        
        records: list[UsageRecord] = query.all()

        total_input_tokens = sum(r.input_tokens for r in records)
        total_output_tokens = sum(r.output_tokens for r in records)
        total_cost = sum(r.total_cost for r in records)
        
        by_model: dict[str, dict[str, Any]] = {}
        for r in records:
            key = f"{r.provider}:{r.model}"
            if key not in by_model:
                by_model[key] = {
                    "provider": r.provider,
                    "model": r.model,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost": 0.0,
                    "call_count": 0
                }
            by_model[key]["input_tokens"] += r.input_tokens
            by_model[key]["output_tokens"] += r.output_tokens
            by_model[key]["cost"] += r.total_cost
            by_model[key]["call_count"] += 1
        
        by_content_type = {}
        for r in records:
            if r.content_type not in by_content_type:
                by_content_type[r.content_type] = {"tokens": 0, "cost": 0.0}
            by_content_type[r.content_type]["tokens"] += r.input_tokens + r.output_tokens
            by_content_type[r.content_type]["cost"] += r.total_cost
        
        trend_days = 365 if period == "all" else 30
        trend = self.tracker.get_daily_usage_trend(user_id=user_id, days=trend_days)
        
        return {
            "period": period,
            "period_start": period_start.isoformat() if period_start else "all",
            "period_end": period_end.isoformat() if period_end else "now",
            "total_cost": round(total_cost, 6),
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_calls": len(records),
            "by_model": list(by_model.values()),
            "by_content_type": by_content_type,
            "trend": trend,
            "currency": "USD"
        }

    def get_model_usage_report(
        self,
        user_id: Optional[str] = None,
        period: str = "monthly"
    ) -> List[Dict]:
        period_start, period_end = self._get_period_dates(period)
        
        query = self.db.query(
            UsageRecord.provider,
            UsageRecord.model,
            func.count(UsageRecord.id).label("call_count"),
            func.sum(UsageRecord.input_tokens).label("total_input_tokens"),
            func.sum(UsageRecord.output_tokens).label("total_output_tokens"),
            func.sum(UsageRecord.total_cost).label("total_cost"),
            func.avg(UsageRecord.duration_ms).label("avg_duration_ms")
        ).filter(
            and_(
                func.date(UsageRecord.created_at) >= period_start,
                func.date(UsageRecord.created_at) <= period_end
            )
        )
        
        if user_id:
            query = query.filter(UsageRecord.user_id == user_id)
        
        results = query.group_by(
            UsageRecord.provider,
            UsageRecord.model
        ).all()
        
        return [
            {
                "provider": r.provider,
                "model": r.model,
                "call_count": r.call_count,
                "total_input_tokens": int(r.total_input_tokens or 0),
                "total_output_tokens": int(r.total_output_tokens or 0),
                "total_cost": round(float(r.total_cost or 0), 6),
                "avg_duration_ms": round(float(r.avg_duration_ms or 0), 2)
            }
            for r in results
        ]

    def get_user_comparison_report(
        self,
        period: str = "monthly",
        limit: int = 10
    ) -> List[Dict]:
        period_start, period_end = self._get_period_dates(period)
        
        results = self.db.query(
            UsageRecord.user_id,
            func.count(UsageRecord.id).label("call_count"),
            func.sum(UsageRecord.total_cost).label("total_cost"),
            func.sum(UsageRecord.input_tokens).label("total_input_tokens"),
            func.sum(UsageRecord.output_tokens).label("total_output_tokens")
        ).filter(
            and_(
                func.date(UsageRecord.created_at) >= period_start,
                func.date(UsageRecord.created_at) <= period_end
            )
        ).group_by(
            UsageRecord.user_id
        ).order_by(
            func.sum(UsageRecord.total_cost).desc()
        ).limit(limit).all()
        
        return [
            {
                "user_id": r.user_id,
                "call_count": r.call_count,
                "total_cost": round(float(r.total_cost or 0), 6),
                "total_input_tokens": int(r.total_input_tokens or 0),
                "total_output_tokens": int(r.total_output_tokens or 0)
            }
            for r in results
        ]

    def get_content_type_analysis(
        self,
        user_id: Optional[str] = None,
        period: str = "monthly"
    ) -> Dict:
        period_start, period_end = self._get_period_dates(period)
        
        query = self.db.query(
            UsageRecord.content_type,
            func.count(UsageRecord.id).label("call_count"),
            func.sum(UsageRecord.total_cost).label("total_cost"),
            func.sum(UsageRecord.input_tokens).label("total_input_tokens"),
            func.sum(UsageRecord.output_tokens).label("total_output_tokens")
        ).filter(
            and_(
                func.date(UsageRecord.created_at) >= period_start,
                func.date(UsageRecord.created_at) <= period_end
            )
        )
        
        if user_id:
            query = query.filter(UsageRecord.user_id == user_id)
        
        results = query.group_by(UsageRecord.content_type).all()
        
        total_cost = sum(float(r.total_cost or 0) for r in results)
        
        return {
            "period": period,
            "content_types": [
                {
                    "content_type": r.content_type,
                    "call_count": r.call_count,
                    "total_cost": round(float(r.total_cost or 0), 6),
                    "cost_percentage": round((float(r.total_cost or 0) / total_cost * 100), 2) if total_cost > 0 else 0,
                    "total_input_tokens": int(r.total_input_tokens or 0),
                    "total_output_tokens": int(r.total_output_tokens or 0)
                }
                for r in results
            ],
            "total_cost": round(total_cost, 6)
        }

    def generate_csv_report(
        self,
        user_id: Optional[str] = None,
        period: str = "monthly"
    ) -> str:
        period_start, period_end = self._get_period_dates(period)
        
        query = self.db.query(UsageRecord).filter(
            and_(
                func.date(UsageRecord.created_at) >= period_start,
                func.date(UsageRecord.created_at) <= period_end
            )
        )
        
        if user_id:
            query = query.filter(UsageRecord.user_id == user_id)
        
        records = query.order_by(UsageRecord.created_at.desc()).all()
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        writer.writerow([
            "Call ID",
            "User ID",
            "Session ID",
            "Provider",
            "Model",
            "Content Type",
            "Input Tokens",
            "Output Tokens",
            "Input Cost",
            "Output Cost",
            "Total Cost",
            "Currency",
            "Cache Hit",
            "Duration (ms)",
            "Created At"
        ])
        
        for r in records:
            writer.writerow([
                r.call_id,
                r.user_id,
                r.session_id,
                r.provider,
                r.model,
                r.content_type,
                r.input_tokens,
                r.output_tokens,
                r.input_cost,
                r.output_cost,
                r.total_cost,
                r.currency,
                "Yes" if r.cache_hit else "No",
                r.duration_ms,
                r.created_at.isoformat() if r.created_at else ""
            ])
        
        return output.getvalue()

    def _get_period_dates(self, period: str) -> tuple:
        today = date.today()
        
        if period == "daily":
            return today, today
        elif period == "weekly":
            days_since_monday = today.weekday()
            period_start = today - timedelta(days=days_since_monday)
            period_end = period_start + timedelta(days=6)
        elif period == "monthly":
            period_start = today.replace(day=1)
            if today.month == 12:
                period_end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                period_end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
        elif period == "yearly":
            period_start = today.replace(month=1, day=1)
            period_end = today.replace(month=12, day=31)
        elif period == "all":
            return None, None
        else:
            period_start = today.replace(day=1)
            period_end = today
        
        return period_start, period_end

from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from typing import List, Optional, Dict
from datetime import datetime, date, timedelta
import uuid
import json

from billing.models import UsageRecord, UserUsageSummary


class UsageTracker:
    def __init__(self, db: Session):
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
        metadata: dict = None
    ) -> UsageRecord:
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
        
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        
        self._update_user_summary(user_id, input_tokens, output_tokens, input_cost + output_cost, currency)
        
        return record

    def get_usage_record(self, call_id: str) -> Optional[UsageRecord]:
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
        records = self.db.query(UsageRecord).filter(
            UsageRecord.session_id == session_id
        ).all()
        
        total_input_tokens = sum(r.input_tokens for r in records)
        total_output_tokens = sum(r.output_tokens for r in records)
        total_cost = sum(r.total_cost for r in records)
        
        by_model = {}
        for r in records:
            key = f"{r.provider}:{r.model}"
            if key not in by_model:
                by_model[key] = {"input_tokens": 0, "output_tokens": 0, "cost": 0.0}
            by_model[key]["input_tokens"] += r.input_tokens
            by_model[key]["output_tokens"] += r.output_tokens
            by_model[key]["cost"] += r.total_cost
        
        return {
            "session_id": session_id,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_cost": round(total_cost, 6),
            "by_model": by_model,
            "call_count": len(records)
        }

    def get_user_usage(
        self,
        user_id: str,
        period_start: Optional[date] = None,
        period_end: Optional[date] = None
    ) -> Dict:
        if not period_start:
            period_start = date.today().replace(day=1)
        if not period_end:
            period_end = date.today()
        
        records = self.db.query(UsageRecord).filter(
            and_(
                UsageRecord.user_id == user_id,
                func.date(UsageRecord.created_at) >= period_start,
                func.date(UsageRecord.created_at) <= period_end
            )
        ).all()
        
        total_input_tokens = sum(r.input_tokens for r in records)
        total_output_tokens = sum(r.output_tokens for r in records)
        total_cost = sum(r.total_cost for r in records)
        
        by_model = {}
        by_content_type = {}
        
        for r in records:
            model_key = f"{r.provider}:{r.model}"
            if model_key not in by_model:
                by_model[model_key] = {"input_tokens": 0, "output_tokens": 0, "cost": 0.0}
            by_model[model_key]["input_tokens"] += r.input_tokens
            by_model[model_key]["output_tokens"] += r.output_tokens
            by_model[model_key]["cost"] += r.total_cost
            
            if r.content_type not in by_content_type:
                by_content_type[r.content_type] = {"tokens": 0, "cost": 0.0}
            by_content_type[r.content_type]["tokens"] += r.input_tokens + r.output_tokens
            by_content_type[r.content_type]["cost"] += r.total_cost
        
        return {
            "user_id": user_id,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_cost": round(total_cost, 6),
            "by_model": by_model,
            "by_content_type": by_content_type,
            "call_count": len(records)
        }

    def get_daily_usage_trend(
        self,
        user_id: Optional[str] = None,
        days: int = 30
    ) -> List[Dict]:
        end_date = datetime.utcnow()
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
        today = date.today()
        period_start = today.replace(day=1)
        
        if today.month == 12:
            period_end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            period_end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
        
        summary = self.db.query(UserUsageSummary).filter(
            and_(
                UserUsageSummary.user_id == user_id,
                UserUsageSummary.period_start == period_start
            )
        ).first()
        
        if summary:
            summary.total_input_tokens += input_tokens
            summary.total_output_tokens += output_tokens
            summary.total_cost += cost
        else:
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
        
        self.db.commit()

    def get_usage_statistics(self, user_id: Optional[str] = None) -> Dict:
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
        cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
        
        deleted_count = self.db.query(UsageRecord).filter(
            UsageRecord.created_at < cutoff_date
        ).delete()
        
        self.db.commit()
        return deleted_count

    def get_record_count(self) -> int:
        return self.db.query(UsageRecord).count()

    def get_oldest_record_date(self) -> Optional[datetime]:
        record = self.db.query(UsageRecord).order_by(UsageRecord.created_at.asc()).first()
        return record.created_at if record else None

    def get_newest_record_date(self) -> Optional[datetime]:
        record = self.db.query(UsageRecord).order_by(UsageRecord.created_at.desc()).first()
        return record.created_at if record else None

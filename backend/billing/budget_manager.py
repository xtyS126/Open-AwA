from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import List, Optional, Dict
from datetime import datetime, date, timedelta, timezone

from billing.models import BudgetConfig


class BudgetManager:
    def __init__(self, db: Session):
        self.db = db

    def create_budget(
        self,
        budget_type: str,
        max_amount: float,
        scope_id: Optional[str] = None,
        period_type: str = "monthly",
        currency: str = "USD",
        warning_threshold: float = 0.8
    ) -> BudgetConfig:
        budget = BudgetConfig(
            budget_type=budget_type,
            scope_id=scope_id,
            max_amount=max_amount,
            period_type=period_type,
            currency=currency,
            warning_threshold=warning_threshold
        )
        self.db.add(budget)
        self.db.commit()
        self.db.refresh(budget)
        return budget

    def get_budget(self, budget_id: int) -> Optional[BudgetConfig]:
        return self.db.query(BudgetConfig).filter(BudgetConfig.id == budget_id).first()

    def get_budgets(
        self,
        budget_type: Optional[str] = None,
        scope_id: Optional[str] = None,
        is_active: bool = True
    ) -> List[BudgetConfig]:
        query = self.db.query(BudgetConfig).filter(BudgetConfig.is_active == is_active)
        
        if budget_type:
            query = query.filter(BudgetConfig.budget_type == budget_type)
        if scope_id:
            query = query.filter(BudgetConfig.scope_id == scope_id)
        
        return query.all()

    def get_budget_for_user(self, user_id: str) -> Optional[BudgetConfig]:
        user_budget = self.db.query(BudgetConfig).filter(
            and_(
                BudgetConfig.budget_type == "user",
                BudgetConfig.scope_id == user_id,
                BudgetConfig.is_active == True
            )
        ).first()
        
        if user_budget:
            return user_budget
        
        return self.db.query(BudgetConfig).filter(
            and_(
                BudgetConfig.budget_type == "global",
                BudgetConfig.scope_id == None,
                BudgetConfig.is_active == True
            )
        ).first()

    def update_budget(self, budget_id: int, budget_data: Dict) -> Optional[BudgetConfig]:
        budget = self.get_budget(budget_id)
        if budget:
            for key, value in budget_data.items():
                setattr(budget, key, value)
            budget.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(budget)
        return budget

    def delete_budget(self, budget_id: int) -> bool:
        budget = self.get_budget(budget_id)
        if budget:
            budget.is_active = False
            self.db.commit()
            return True
        return False

    def check_budget(
        self,
        user_id: str,
        proposed_cost: float = 0
    ) -> Dict:
        budget = self.get_budget_for_user(user_id)
        
        if not budget:
            return {
                "has_budget": True,
                "budget_limit": None,
                "current_usage": 0,
                "remaining": None,
                "warning_threshold_reached": False,
                "budget_exceeded": False,
                "can_proceed": True
            }
        
        period_start, period_end = self._get_period_dates(budget.period_type)
        
        current_usage = self._calculate_current_usage(user_id, budget, period_start, period_end)
        
        warning_threshold_reached = False
        budget_exceeded = False
        
        if budget.max_amount > 0:
            usage_ratio = current_usage / budget.max_amount
            warning_threshold_reached = usage_ratio >= budget.warning_threshold
            budget_exceeded = (current_usage + proposed_cost) > budget.max_amount
        else:
            warning_threshold_reached = False
            budget_exceeded = False
        
        return {
            "has_budget": True,
            "budget_limit": budget.max_amount,
            "current_usage": round(current_usage, 6),
            "remaining": round(budget.max_amount - current_usage, 6) if budget.max_amount > 0 else None,
            "usage_percentage": round((current_usage / budget.max_amount * 100), 2) if budget.max_amount > 0 else 0,
            "warning_threshold": budget.warning_threshold,
            "warning_threshold_reached": warning_threshold_reached,
            "budget_exceeded": budget_exceeded,
            "can_proceed": not budget_exceeded,
            "period_type": budget.period_type,
            "currency": budget.currency
        }

    def get_budget_status(self, user_id: str) -> Dict:
        budget = self.get_budget_for_user(user_id)
        
        if not budget:
            return {
                "has_budget_configured": False,
                "message": "No budget configured"
            }
        
        period_start, period_end = self._get_period_dates(budget.period_type)
        current_usage = self._calculate_current_usage(user_id, budget, period_start, period_end)
        
        usage_percentage = (current_usage / budget.max_amount * 100) if budget.max_amount > 0 else 0
        
        return {
            "has_budget_configured": True,
            "budget_type": budget.budget_type,
            "max_amount": budget.max_amount,
            "current_usage": round(current_usage, 6),
            "remaining": round(budget.max_amount - current_usage, 6),
            "usage_percentage": round(usage_percentage, 2),
            "warning_threshold": budget.warning_threshold,
            "period_type": budget.period_type,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "currency": budget.currency,
            "is_warning": usage_percentage >= (budget.warning_threshold * 100),
            "is_exceeded": current_usage >= budget.max_amount
        }

    def _get_period_dates(self, period_type: str) -> tuple:
        today = date.today()
        
        if period_type == "daily":
            period_start = today
            period_end = today
        elif period_type == "weekly":
            days_since_monday = today.weekday()
            period_start = today - timedelta(days=days_since_monday)
            period_end = period_start + timedelta(days=6)
        elif period_type == "monthly":
            period_start = today.replace(day=1)
            if today.month == 12:
                period_end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                period_end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
        elif period_type == "yearly":
            period_start = today.replace(month=1, day=1)
            period_end = today.replace(month=12, day=31)
        else:
            period_start = today.replace(day=1)
            period_end = date.today()
        
        return period_start, period_end

    def _calculate_current_usage(
        self,
        user_id: str,
        budget: BudgetConfig,
        period_start: date,
        period_end: date
    ) -> float:
        from billing.tracker import UsageTracker
        tracker = UsageTracker(self.db)
        usage = tracker.get_user_usage(user_id, period_start, period_end)
        return usage["total_cost"]

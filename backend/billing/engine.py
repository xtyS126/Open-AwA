"""
计费与用量管理模块，负责价格配置、预算控制、用量追踪与报表能力。
这一部分直接关联成本核算、调用统计以及运维观测。
"""

from sqlalchemy.orm import Session
from typing import Dict, Optional
import time

from billing.calculator import CostCalculator
from billing.pricing_manager import PricingManager
from billing.tracker import UsageTracker
from billing.budget_manager import BudgetManager


class BillingEngine:
    """
    封装与BillingEngine相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(self, db: Session):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.db = db
        self.calculator = CostCalculator()
        self.pricing_manager = PricingManager(db)
        self.tracker = UsageTracker(db)
        self.budget_manager = BudgetManager(db)

    def before_llm_call(
        self,
        user_id: str,
        session_id: str,
        provider: str,
        model: str,
        content_type: str,
        text: str = "",
        num_images: int = 0,
        audio_seconds: float = 0,
        video_seconds: float = 0
    ) -> Dict:
        """
        处理before、llm、call相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        start_time = time.time()
        
        pricing = self.pricing_manager.get_pricing(provider, model)
        if not pricing:
            raise ValueError(f"Pricing not found for {provider}:{model}")
        
        tokens_result = self.calculator.calculate_multimodal_tokens(
            text=text,
            num_images=num_images,
            audio_seconds=audio_seconds,
            video_seconds=video_seconds
        )
        
        budget_check = self.budget_manager.check_budget(
            user_id=user_id,
            proposed_cost=0
        )
        
        if not budget_check["can_proceed"]:
            raise PermissionError(
                f"Budget exceeded. Current usage: {budget_check['current_usage']}, "
                f"Limit: {budget_check['budget_limit']}"
            )
        
        return {
            "provider": provider,
            "model": model,
            "content_type": content_type,
            "input_tokens": tokens_result["total_tokens"],
            "tokens_breakdown": tokens_result,
            "currency": pricing.currency,
            "input_price": pricing.input_price,
            "output_price": pricing.output_price,
            "cache_hit_price": pricing.cache_hit_price,
            "start_time": start_time,
            "budget_warning": budget_check.get("warning_threshold_reached", False),
            "budget_status": budget_check
        }

    def after_llm_call(
        self,
        before_result: Dict,
        output_text: str,
        output_tokens: Optional[int] = None,
        cache_hit: bool = False,
        api_response_usage: Optional[dict] = None
    ) -> Dict:
        """
        处理after、llm、call相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        start_time = before_result["start_time"]
        duration_ms = int((time.time() - start_time) * 1000)
        
        if api_response_usage and "prompt_tokens" in api_response_usage:
            input_tokens = api_response_usage["prompt_tokens"]
        else:
            input_tokens = before_result["input_tokens"]
        
        if api_response_usage and "completion_tokens" in api_response_usage:
            output_tokens = api_response_usage["completion_tokens"]
        elif output_tokens is None:
            output_tokens = self.calculator.estimate_text_tokens(output_text)
        
        cost_result = self.calculator.calculate_cost(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_price=before_result["input_price"],
            output_price=before_result["output_price"],
            cache_hit=cache_hit,
            cache_hit_price=before_result.get("cache_hit_price") or 0.0
        )
        
        usage_record = self.tracker.create_usage_record(
            user_id=before_result.get("user_id") or "",
            session_id=before_result.get("session_id") or "",
            provider=before_result["provider"],
            model=before_result["model"],
            content_type=before_result["content_type"],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_cost=cost_result["input_cost"],
            output_cost=cost_result["output_cost"],
            currency=before_result["currency"],
            cache_hit=cache_hit,
            duration_ms=duration_ms,
            metadata={
                "tokens_breakdown": before_result.get("tokens_breakdown"),
                "output_length": len(output_text) if output_text else 0
            }
        )
        
        return {
            "call_id": usage_record.call_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "input_cost": cost_result["input_cost"],
            "output_cost": cost_result["output_cost"],
            "total_cost": cost_result["total_cost"],
            "currency": before_result["currency"],
            "duration_ms": duration_ms,
            "cache_hit": cache_hit
        }

    def record_call(
        self,
        user_id: str,
        session_id: str,
        provider: str,
        model: str,
        content_type: str,
        input_tokens: int,
        output_tokens: int,
        cache_hit: bool = False,
        duration_ms: int = 0,
        metadata: Optional[dict] = None
    ) -> Dict:
        """
        处理record、call相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        pricing = self.pricing_manager.get_pricing(provider, model)
        if not pricing:
            raise ValueError(f"Pricing not found for {provider}:{model}")
        
        cost_result = self.calculator.calculate_cost(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_price=pricing.input_price,
            output_price=pricing.output_price,
            cache_hit=cache_hit,
            cache_hit_price=pricing.cache_hit_price
        )
        
        usage_record = self.tracker.create_usage_record(
            user_id=user_id,
            session_id=session_id,
            provider=provider,
            model=model,
            content_type=content_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_cost=cost_result["input_cost"],
            output_cost=cost_result["output_cost"],
            currency=pricing.currency,
            cache_hit=cache_hit,
            duration_ms=duration_ms,
            metadata=metadata
        )
        
        return {
            "call_id": usage_record.call_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "input_cost": cost_result["input_cost"],
            "output_cost": cost_result["output_cost"],
            "total_cost": cost_result["total_cost"],
            "currency": pricing.currency
        }

    def estimate_cost(
        self,
        provider: str,
        model: str,
        text: str = "",
        num_images: int = 0,
        audio_seconds: float = 0,
        video_seconds: float = 0
    ) -> Dict:
        """
        处理estimate、cost相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        pricing = self.pricing_manager.get_pricing(provider, model)
        if not pricing:
            raise ValueError(f"Pricing not found for {provider}:{model}")
        
        tokens_result = self.calculator.calculate_multimodal_tokens(
            text=text,
            num_images=num_images,
            audio_seconds=audio_seconds,
            video_seconds=video_seconds
        )
        
        cost_result = self.calculator.calculate_cost(
            input_tokens=tokens_result["total_tokens"],
            output_tokens=0,
            input_price=pricing.input_price,
            output_price=pricing.output_price
        )
        
        return {
            "provider": provider,
            "model": model,
            "input_tokens": tokens_result["total_tokens"],
            "tokens_breakdown": tokens_result,
            "estimated_input_cost": cost_result["input_cost"],
            "currency": pricing.currency
        }

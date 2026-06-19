"""
LLM 用量记录器，追踪每次调用的 token 用量、成本和延迟。
"""

from typing import Optional
from datetime import datetime
from sqlalchemy.orm import Session
from db.models import LLMUsage
from llm.response import TokenUsage
from loguru import logger


class UsageRecorder:
    """
    LLM 用量记录器。
    负责将每次 LLM 调用的用量信息持久化到数据库。
    """
    
    def __init__(self, db_session_factory):
        """
        初始化用量记录器。
        
        Args:
            db_session_factory: 数据库会话工厂
        """
        self.db_session_factory = db_session_factory
        logger.info("UsageRecorder 初始化完成")
    
    async def record(
        self,
        user_id: Optional[str],
        task_type: str,
        provider: str,
        model: str,
        usage: TokenUsage,
        cost: float,
        latency_ms: int,
        success: bool,
        error_message: Optional[str] = None,
    ) -> None:
        """
        记录一次 LLM 调用的用量信息。
        
        Args:
            user_id: 用户 ID（可选）
            task_type: 任务类型（如 "soul"、"agent"、"discovery"）
            provider: Provider 名称（如 "openai"、"claude"）
            model: 模型名称
            usage: Token 用量统计
            cost: 成本（美元）
            latency_ms: 延迟（毫秒）
            success: 是否成功
            error_message: 错误信息（失败时）
        """
        try:
            # 使用独立的数据库会话，避免影响主业务事务
            with self.db_session_factory() as session:
                usage_record = LLMUsage(
                    user_id=user_id,
                    task_type=task_type,
                    provider=provider,
                    model=model,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    total_tokens=usage.total_tokens,
                    cost=cost,
                    latency_ms=latency_ms,
                    success=success,
                    error_message=error_message,
                    created_at=datetime.utcnow(),
                )
                
                session.add(usage_record)
                session.commit()
                
                logger.debug(
                    f"LLM 用量记录: user={user_id}, task={task_type}, "
                    f"provider={provider}, model={model}, "
                    f"tokens={usage.total_tokens}, cost=${cost:.4f}, "
                    f"latency={latency_ms}ms, success={success}"
                )
                
        except Exception as e:
            # 记录失败不应影响主业务流程
            logger.error(f"LLM 用量记录失败: {e}")
    
    async def get_user_usage_summary(
        self,
        user_id: str,
        days: int = 30,
    ) -> dict:
        """
        获取用户用量摘要。
        
        Args:
            user_id: 用户 ID
            days: 统计天数（默认 30 天）
        
        Returns:
            dict: 用量摘要（总调用次数、总 token、总成本等）
        """
        try:
            with self.db_session_factory() as session:
                from datetime import timedelta
                from sqlalchemy import func
                
                start_date = datetime.utcnow() - timedelta(days=days)
                
                # 查询统计数据
                result = session.query(
                    func.count(LLMUsage.id).label('total_calls'),
                    func.sum(LLMUsage.total_tokens).label('total_tokens'),
                    func.sum(LLMUsage.cost).label('total_cost'),
                    func.avg(LLMUsage.latency_ms).label('avg_latency_ms'),
                ).filter(
                    LLMUsage.user_id == user_id,
                    LLMUsage.created_at >= start_date,
                    LLMUsage.success == True,
                ).first()
                
                return {
                    'user_id': user_id,
                    'period_days': days,
                    'total_calls': result.total_calls or 0,
                    'total_tokens': result.total_tokens or 0,
                    'total_cost': float(result.total_cost or 0.0),
                    'avg_latency_ms': int(result.avg_latency_ms or 0),
                }
                
        except Exception as e:
            logger.error(f"获取用户用量摘要失败: {e}")
            return {
                'user_id': user_id,
                'period_days': days,
                'total_calls': 0,
                'total_tokens': 0,
                'total_cost': 0.0,
                'avg_latency_ms': 0,
            }
    
    async def get_usage_by_provider(
        self,
        days: int = 30,
    ) -> list:
        """
        按 Provider 统计用量。
        
        Args:
            days: 统计天数（默认 30 天）
        
        Returns:
            list: 各 Provider 的用量统计
        """
        try:
            with self.db_session_factory() as session:
                from datetime import timedelta
                from sqlalchemy import func
                
                start_date = datetime.utcnow() - timedelta(days=days)
                
                # 按 Provider 分组统计
                results = session.query(
                    LLMUsage.provider,
                    func.count(LLMUsage.id).label('call_count'),
                    func.sum(LLMUsage.total_tokens).label('total_tokens'),
                    func.sum(LLMUsage.cost).label('total_cost'),
                ).filter(
                    LLMUsage.created_at >= start_date,
                    LLMUsage.success == True,
                ).group_by(
                    LLMUsage.provider
                ).all()
                
                return [
                    {
                        'provider': r.provider,
                        'call_count': r.call_count,
                        'total_tokens': r.total_tokens or 0,
                        'total_cost': float(r.total_cost or 0.0),
                    }
                    for r in results
                ]
                
        except Exception as e:
            logger.error(f"获取 Provider 用量统计失败: {e}")
            return []
    
    async def get_usage_by_task_type(
        self,
        days: int = 30,
    ) -> list:
        """
        按任务类型统计用量。
        
        Args:
            days: 统计天数（默认 30 天）
        
        Returns:
            list: 各任务类型的用量统计
        """
        try:
            with self.db_session_factory() as session:
                from datetime import timedelta
                from sqlalchemy import func
                
                start_date = datetime.utcnow() - timedelta(days=days)
                
                # 按任务类型分组统计
                results = session.query(
                    LLMUsage.task_type,
                    func.count(LLMUsage.id).label('call_count'),
                    func.sum(LLMUsage.total_tokens).label('total_tokens'),
                    func.sum(LLMUsage.cost).label('total_cost'),
                ).filter(
                    LLMUsage.created_at >= start_date,
                    LLMUsage.success == True,
                ).group_by(
                    LLMUsage.task_type
                ).all()
                
                return [
                    {
                        'task_type': r.task_type,
                        'call_count': r.call_count,
                        'total_tokens': r.total_tokens or 0,
                        'total_cost': float(r.total_cost or 0.0),
                    }
                    for r in results
                ]
                
        except Exception as e:
            logger.error(f"获取任务类型用量统计失败: {e}")
            return []

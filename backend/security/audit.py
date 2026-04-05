"""
安全控制模块，负责权限约束、沙箱限制、审计记录或安全边界保护。
这里的逻辑通常用于避免未授权操作、危险行为或不可控的资源访问。
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from db.models import AuditLog
from loguru import logger


class AuditLogger:
    """
    封装与AuditLogger相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(self, db: Session):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.db = db
        logger.info("AuditLogger initialized")
    
    async def log(
        self,
        user_id: str,
        action: str,
        resource: str,
        result: str,
        details: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        """
        处理log相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        log_entry = AuditLog(
            user_id=user_id,
            action=action,
            resource=resource,
            result=result,
            details=str(details) if details else None
        )
        
        self.db.add(log_entry)
        self.db.commit()
        self.db.refresh(log_entry)
        
        logger.debug(f"Audit log created: {action} on {resource} by {user_id}")
        return log_entry
    
    async def log_auth_event(
        self,
        user_id: str,
        event_type: str,
        success: bool,
        details: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        """
        处理log、auth、event相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return await self.log(
            user_id=user_id,
            action=f"auth:{event_type}",
            resource="authentication",
            result="success" if success else "failure",
            details=details
        )
    
    async def log_tool_usage(
        self,
        user_id: str,
        tool_name: str,
        params: Dict[str, Any],
        result: str
    ) -> AuditLog:
        """
        处理log、tool、usage相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return await self.log(
            user_id=user_id,
            action=f"tool:{tool_name}",
            resource="tool_execution",
            result=result,
            details=params
        )
    
    async def log_file_operation(
        self,
        user_id: str,
        operation: str,
        file_path: str,
        result: str
    ) -> AuditLog:
        """
        处理log、file、operation相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return await self.log(
            user_id=user_id,
            action=f"file:{operation}",
            resource=file_path,
            result=result
        )
    
    async def log_config_change(
        self,
        user_id: str,
        config_name: str,
        old_value: Any,
        new_value: Any
    ) -> AuditLog:
        """
        处理log、config、change相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return await self.log(
            user_id=user_id,
            action="config:change",
            resource=config_name,
            result="changed",
            details={
                "old_value": str(old_value),
                "new_value": str(new_value)
            }
        )
    
    async def get_logs(
        self,
        user_id: Optional[str] = None,
        action_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100
    ) -> List[AuditLog]:
        """
        获取logs相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        query = self.db.query(AuditLog)
        
        if user_id:
            query = query.filter(AuditLog.user_id == user_id)
        
        if action_type:
            query = query.filter(AuditLog.action.startswith(action_type))
        
        if start_date:
            query = query.filter(AuditLog.timestamp >= start_date)
        
        if end_date:
            query = query.filter(AuditLog.timestamp <= end_date)
        
        logs = query.order_by(AuditLog.timestamp.desc()).limit(limit).all()
        
        return logs
    
    async def get_failed_attempts(
        self,
        user_id: Optional[str] = None,
        hours: int = 24
    ) -> List[AuditLog]:
        """
        获取failed、attempts相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        from datetime import timedelta
        
        start_date = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        query = self.db.query(AuditLog).filter(
            AuditLog.result == "failure",
            AuditLog.timestamp >= start_date
        )
        
        if user_id:
            query = query.filter(AuditLog.user_id == user_id)
        
        return query.order_by(AuditLog.timestamp.desc()).all()
    
    async def get_suspicious_activity(
        self,
        threshold: int = 5,
        hours: int = 1
    ) -> Dict[str, Any]:
        """
        获取suspicious、activity相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        from datetime import timedelta
        from sqlalchemy import func
        
        start_date = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        results = self.db.query(
            AuditLog.user_id,
            func.count(AuditLog.id).label("count")
        ).filter(
            AuditLog.result == "failure",
            AuditLog.timestamp >= start_date
        ).group_by(
            AuditLog.user_id
        ).having(
            func.count(AuditLog.id) >= threshold
        ).all()
        
        return {
            "suspicious_users": [
                {"user_id": r[0], "failed_attempts": r[1]}
                for r in results
            ],
            "time_window_hours": hours,
            "threshold": threshold
        }

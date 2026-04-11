"""
安全控制模块，负责审计日志记录与查询。
所有用户操作的审计信息通过此模块写入数据库，支持异步记录与多维度查询。
"""

import asyncio
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from db.models import AuditLog
from loguru import logger


class AuditLogger:
    """审计日志记录器，提供异步写入与便捷的事件记录方法。"""

    def __init__(self, db: Session):
        """
        初始化审计日志记录器。

        Args:
            db: 数据库会话实例。
        """
        self.db = db
        logger.info("AuditLogger initialized")

    def _log_sync(
        self,
        user_id: str,
        action: str,
        resource: str,
        result: str,
        details: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Optional[AuditLog]:
        """同步写入审计日志记录。异常时回滚并记录到文件日志，不影响主业务流程。"""
        try:
            log_entry = AuditLog(
                user_id=user_id,
                action=action,
                resource=resource,
                result=result,
                details=details,
                ip_address=ip_address,
            )
            self.db.add(log_entry)
            self.db.commit()
            self.db.refresh(log_entry)
            return log_entry
        except Exception as e:
            self.db.rollback()
            logger.error(
                f"审计日志写入失败，已回滚: action={action}, resource={resource}, "
                f"user_id={user_id}, error={type(e).__name__}: {e}"
            )
            return None

    async def log(
        self,
        user_id: str,
        action: str,
        resource: str,
        result: str,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ) -> Optional[AuditLog]:
        """
        异步记录审计日志。写入失败时不会抛出异常，返回 None。

        Args:
            user_id: 操作用户标识。
            action: 操作类型。
            resource: 操作资源。
            result: 操作结果（success/failure）。
            details: 附加详情字典。
            ip_address: 请求来源 IP。
        """
        details_str = str(details) if details else None
        log_entry = await asyncio.to_thread(
            self._log_sync, user_id, action, resource, result, details_str, ip_address
        )
        if log_entry:
            logger.debug(f"Audit log created: {action} on {resource} by {user_id}")
        return log_entry

    async def log_auth_event(
        self,
        user_id: str,
        event_type: str,
        success: bool,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ) -> AuditLog:
        """
        记录认证事件审计日志。

        Args:
            user_id: 用户标识。
            event_type: 认证事件类型（login/logout/register）。
            success: 是否成功。
            details: 附加详情。
            ip_address: 请求来源 IP。
        """
        return await self.log(
            user_id=user_id,
            action=f"auth:{event_type}",
            resource="authentication",
            result="success" if success else "failure",
            details=details,
            ip_address=ip_address,
        )

    async def log_tool_usage(
        self,
        user_id: str,
        tool_name: str,
        params: Dict[str, Any],
        result: str,
        ip_address: Optional[str] = None,
    ) -> AuditLog:
        """
        记录工具调用审计日志。

        Args:
            user_id: 用户标识。
            tool_name: 工具名称。
            params: 调用参数。
            result: 调用结果。
            ip_address: 请求来源 IP。
        """
        return await self.log(
            user_id=user_id,
            action=f"tool:{tool_name}",
            resource="tool_execution",
            result=result,
            details=params,
            ip_address=ip_address,
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
    
    def _get_logs_sync(
        self,
        user_id: Optional[str],
        action_type: Optional[str],
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        limit: int
    ) -> List[AuditLog]:
        query = self.db.query(AuditLog)
        if user_id:
            query = query.filter(AuditLog.user_id == user_id)
        if action_type:
            query = query.filter(AuditLog.action.startswith(action_type))
        if start_date:
            query = query.filter(AuditLog.timestamp >= start_date)
        if end_date:
            query = query.filter(AuditLog.timestamp <= end_date)
        return query.order_by(AuditLog.timestamp.desc()).limit(limit).all()

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
        return await asyncio.to_thread(
            self._get_logs_sync, user_id, action_type, start_date, end_date, limit
        )
    
    def _get_failed_attempts_sync(
        self, user_id: Optional[str], hours: int
    ) -> List[AuditLog]:
        from datetime import timedelta
        start_date = datetime.now(timezone.utc) - timedelta(hours=hours)
        query = self.db.query(AuditLog).filter(
            AuditLog.result == "failure",
            AuditLog.timestamp >= start_date
        )
        if user_id:
            query = query.filter(AuditLog.user_id == user_id)
        return query.order_by(AuditLog.timestamp.desc()).all()

    async def get_failed_attempts(
        self,
        user_id: Optional[str] = None,
        hours: int = 24
    ) -> List[AuditLog]:
        """
        获取failed、attempts相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        return await asyncio.to_thread(
            self._get_failed_attempts_sync, user_id, hours
        )
    
    def _get_suspicious_activity_sync(
        self, threshold: int, hours: int
    ) -> Dict[str, Any]:
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

    async def get_suspicious_activity(
        self,
        threshold: int = 5,
        hours: int = 1
    ) -> Dict[str, Any]:
        """
        获取suspicious、activity相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        return await asyncio.to_thread(
            self._get_suspicious_activity_sync, threshold, hours
        )

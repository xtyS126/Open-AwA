"""
推理审计管理器，记录和查询推理过程的元数据、耗时与 token 统计。

功能：
- 记录推理审计数据（复杂度、深度、耗时、token）
- 查询推理审计历史
- 推理性能统计（平均耗时、token 分布、复杂度分布）
- 推理内容导出（关联 short_term_memory 的 reasoning_content）

与 ReasoningAudit 模型配合，提供完整的推理审计能力。
"""

import json
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session

from db.models import ReasoningAudit, ShortTermMemory


class ReasoningAuditManager:
    """推理审计管理器，提供审计数据记录与查询能力。"""

    def __init__(self, db: Session):
        """
        初始化推理审计管理器。

        Args:
            db: 数据库会话实例。
        """
        self.db = db
        logger.debug("ReasoningAuditManager initialized")

    def record_audit(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        provider: str = "",
        model: str = "",
        thinking_depth: int = 0,
        complexity: str = "simple",
        complexity_score: int = 0,
        is_user_override: bool = False,
        reasoning_length: int = 0,
        reasoning_tokens: int = 0,
        output_tokens: int = 0,
        input_tokens: int = 0,
        reasoning_duration_ms: int = 0,
        total_duration_ms: int = 0,
        ttft_ms: int = 0,
        success: bool = True,
        error_message: Optional[str] = None,
        audit_metadata: Optional[dict] = None,
    ) -> ReasoningAudit:
        """
        记录一次推理审计数据。

        Args:
            session_id: 会话 ID。
            user_id: 用户 ID。
            provider: 模型提供商。
            model: 模型名称。
            thinking_depth: 推理深度（0-5）。
            complexity: 复杂度等级。
            complexity_score: 复杂度评分。
            is_user_override: 是否用户手动覆盖深度。
            reasoning_length: 推理内容长度。
            reasoning_tokens: 推理 token 数。
            output_tokens: 输出 token 数。
            input_tokens: 输入 token 数。
            reasoning_duration_ms: 推理耗时（毫秒）。
            total_duration_ms: 总耗时（毫秒）。
            ttft_ms: 首 token 时间（毫秒）。
            success: 是否成功。
            error_message: 错误信息。
            audit_metadata: 审计元数据。

        Returns:
            创建的 ReasoningAudit 实例。
        """
        audit = ReasoningAudit(
            session_id=session_id,
            user_id=user_id,
            provider=provider,
            model=model,
            thinking_depth=thinking_depth,
            complexity=complexity,
            complexity_score=complexity_score,
            is_user_override=is_user_override,
            reasoning_length=reasoning_length,
            reasoning_tokens=reasoning_tokens,
            output_tokens=output_tokens,
            input_tokens=input_tokens,
            reasoning_duration_ms=reasoning_duration_ms,
            total_duration_ms=total_duration_ms,
            ttft_ms=ttft_ms,
            success=success,
            error_message=error_message,
            audit_metadata=audit_metadata,
        )
        self.db.add(audit)
        self.db.commit()
        self.db.refresh(audit)
        logger.bind(
            event="reasoning_audit_recorded",
            session_id=session_id,
            complexity=complexity,
            depth=thinking_depth,
            reasoning_tokens=reasoning_tokens,
        ).debug(
            f"推理审计已记录: session={session_id}, complexity={complexity}, "
            f"depth={thinking_depth}, reasoning_tokens={reasoning_tokens}"
        )
        return audit

    def list_audits(
        self,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        complexity: Optional[str] = None,
        success: Optional[bool] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """
        查询推理审计记录列表，支持分页和多维度筛选。

        Args:
            session_id: 筛选会话 ID。
            user_id: 筛选用户 ID。
            complexity: 筛选复杂度等级。
            success: 筛选是否成功。
            start_time: 开始时间。
            end_time: 结束时间。
            page: 页码（从 1 开始）。
            page_size: 每页数量。

        Returns:
            分页结果字典：audits, total, page, page_size。
        """
        query = self.db.query(ReasoningAudit)

        if session_id:
            query = query.filter(ReasoningAudit.session_id == session_id)
        if user_id:
            query = query.filter(ReasoningAudit.user_id == user_id)
        if complexity:
            query = query.filter(ReasoningAudit.complexity == complexity)
        if success is not None:
            query = query.filter(ReasoningAudit.success == success)
        if start_time:
            query = query.filter(ReasoningAudit.created_at >= start_time)
        if end_time:
            query = query.filter(ReasoningAudit.created_at <= end_time)

        total = query.count()
        offset = (page - 1) * page_size
        audits = (
            query.order_by(ReasoningAudit.created_at.desc())
            .offset(offset)
            .limit(page_size)
            .all()
        )

        return {
            "audits": [self._audit_to_dict(a) for a in audits],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get_audit(self, audit_id: int) -> Optional[dict]:
        """
        获取指定审计记录详情。

        Args:
            audit_id: 审计记录 ID。

        Returns:
            审计记录字典，不存在返回 None。
        """
        audit = self.db.query(ReasoningAudit).filter(ReasoningAudit.id == audit_id).first()
        if not audit:
            return None
        return self._audit_to_dict(audit)

    def get_stats(
        self,
        user_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> dict:
        """
        获取推理审计统计信息。

        Args:
            user_id: 筛选用户 ID。
            start_time: 开始时间。
            end_time: 结束时间。

        Returns:
            统计字典：total, success_rate, avg_reasoning_tokens, avg_duration_ms,
            complexity_distribution, depth_distribution。
        """
        query = self.db.query(ReasoningAudit)
        if user_id:
            query = query.filter(ReasoningAudit.user_id == user_id)
        if start_time:
            query = query.filter(ReasoningAudit.created_at >= start_time)
        if end_time:
            query = query.filter(ReasoningAudit.created_at <= end_time)

        total = query.count()
        if total == 0:
            return {
                "total": 0,
                "success_rate": 0.0,
                "avg_reasoning_tokens": 0,
                "avg_output_tokens": 0,
                "avg_reasoning_duration_ms": 0,
                "avg_total_duration_ms": 0,
                "avg_ttft_ms": 0,
                "complexity_distribution": {},
                "depth_distribution": {},
            }

        success_count = query.filter(ReasoningAudit.success.is_(True)).count()
        avg_reasoning_tokens = query.with_entities(
            func.avg(ReasoningAudit.reasoning_tokens)
        ).scalar() or 0
        avg_output_tokens = query.with_entities(
            func.avg(ReasoningAudit.output_tokens)
        ).scalar() or 0
        avg_reasoning_duration = query.with_entities(
            func.avg(ReasoningAudit.reasoning_duration_ms)
        ).scalar() or 0
        avg_total_duration = query.with_entities(
            func.avg(ReasoningAudit.total_duration_ms)
        ).scalar() or 0
        avg_ttft = query.with_entities(
            func.avg(ReasoningAudit.ttft_ms)
        ).scalar() or 0

        # 复杂度分布
        complexity_stats = (
            query.with_entities(
                ReasoningAudit.complexity,
                func.count(ReasoningAudit.id),
            )
            .group_by(ReasoningAudit.complexity)
            .all()
        )
        complexity_distribution = {c: cnt for c, cnt in complexity_stats}

        # 深度分布
        depth_stats = (
            query.with_entities(
                ReasoningAudit.thinking_depth,
                func.count(ReasoningAudit.id),
            )
            .group_by(ReasoningAudit.thinking_depth)
            .all()
        )
        depth_distribution = {str(d): cnt for d, cnt in depth_stats}

        return {
            "total": total,
            "success_rate": round(success_count / total * 100, 1),
            "avg_reasoning_tokens": round(avg_reasoning_tokens, 1),
            "avg_output_tokens": round(avg_output_tokens, 1),
            "avg_reasoning_duration_ms": round(avg_reasoning_duration, 1),
            "avg_total_duration_ms": round(avg_total_duration, 1),
            "avg_ttft_ms": round(avg_ttft, 1),
            "complexity_distribution": complexity_distribution,
            "depth_distribution": depth_distribution,
        }

    def export_reasoning_content(
        self,
        session_id: str,
        format: str = "json",
    ) -> dict:
        """
        导出指定会话的推理内容。

        关联 short_term_memory 表获取 reasoning_content 字段，
        同时关联 reasoning_audits 表获取审计元数据。

        Args:
            session_id: 会话 ID。
            format: 导出格式（json/markdown）。

        Returns:
            导出结果字典：session_id, format, items, total。
        """
        # 查询会话的所有带推理内容的记忆记录
        memories = (
            self.db.query(ShortTermMemory)
            .filter(
                ShortTermMemory.session_id == session_id,
                ShortTermMemory.reasoning_content.isnot(None),
                ShortTermMemory.reasoning_content != "",
            )
            .order_by(ShortTermMemory.id.asc())
            .all()
        )

        # 查询对应的审计记录
        audits = (
            self.db.query(ReasoningAudit)
            .filter(ReasoningAudit.session_id == session_id)
            .order_by(ReasoningAudit.created_at.asc())
            .all()
        )
        audit_map = {a.session_id: a for a in audits}

        items = []
        for mem in memories:
            audit = audit_map.get(mem.session_id)
            item = {
                "memory_id": mem.id,
                "role": mem.role,
                "content": mem.content or "",
                "reasoning_content": mem.reasoning_content or "",
                "reasoning_length": len(mem.reasoning_content or ""),
                "created_at": mem.timestamp.isoformat() if mem.timestamp else None,
            }
            if audit:
                item["audit"] = {
                    "complexity": audit.complexity,
                    "thinking_depth": audit.thinking_depth,
                    "reasoning_tokens": audit.reasoning_tokens,
                    "reasoning_duration_ms": audit.reasoning_duration_ms,
                    "provider": audit.provider,
                    "model": audit.model,
                }
            items.append(item)

        return {
            "session_id": session_id,
            "format": format,
            "items": items,
            "total": len(items),
        }

    @staticmethod
    def _audit_to_dict(audit: ReasoningAudit) -> dict:
        """将 ReasoningAudit 实例转换为字典。"""
        return {
            "id": audit.id,
            "session_id": audit.session_id,
            "user_id": audit.user_id,
            "provider": audit.provider,
            "model": audit.model,
            "thinking_depth": audit.thinking_depth,
            "complexity": audit.complexity,
            "complexity_score": audit.complexity_score,
            "is_user_override": audit.is_user_override,
            "reasoning_length": audit.reasoning_length,
            "reasoning_tokens": audit.reasoning_tokens,
            "output_tokens": audit.output_tokens,
            "input_tokens": audit.input_tokens,
            "reasoning_duration_ms": audit.reasoning_duration_ms,
            "total_duration_ms": audit.total_duration_ms,
            "ttft_ms": audit.ttft_ms,
            "success": audit.success,
            "error_message": audit.error_message,
            "audit_metadata": audit.audit_metadata,
            "created_at": audit.created_at.isoformat() if audit.created_at else None,
        }


def get_audit_manager(db: Session) -> ReasoningAuditManager:
    """
    工厂函数，创建推理审计管理器实例。

    Args:
        db: 数据库会话实例。

    Returns:
        ReasoningAuditManager 实例。
    """
    return ReasoningAuditManager(db)

"""
代理会话生命周期管理，负责 session 记录的增删改查与状态机校验。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from db.models import SessionLocal, TaskAgentSession

# 合法的状态转换
VALID_TRANSITIONS: Dict[str, set] = {
    "created": {"queued"},
    "queued": {"running", "stopped", "cancelled"},
    "running": {"completed", "failed", "stopped", "waiting_user"},
    "waiting_user": {"running", "stopped", "cancelled"},
    "completed": set(),
    "failed": set(),
    "stopped": set(),
    "cancelled": set(),
}


def _generate_agent_id() -> str:
    """生成短的代理 ID，便于日志和 UI 展示。"""
    return f"agt_{uuid.uuid4().hex[:12]}"


def validate_transition(current_state: str, new_state: str) -> bool:
    """校验状态转换是否合法。"""
    allowed = VALID_TRANSITIONS.get(current_state, set())
    return new_state in allowed


def create_session(
    db: Session,
    *,
    parent_session_id: Optional[str] = None,
    root_chat_session_id: Optional[str] = None,
    agent_type: str = "general-purpose",
    run_mode: str = "foreground",
    isolation_mode: str = "inherit",
    lease_owner: Optional[str] = None,
) -> TaskAgentSession:
    """创建新的代理运行实例记录。"""
    agent_id = _generate_agent_id()
    now = datetime.now(timezone.utc)

    session = TaskAgentSession(
        agent_id=agent_id,
        parent_session_id=parent_session_id,
        root_chat_session_id=root_chat_session_id,
        agent_type=agent_type,
        state="created",
        run_mode=run_mode,
        isolation_mode=isolation_mode,
        lease_owner=lease_owner,
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    logger.bind(
        module="task_runtime",
        agent_id=agent_id,
        agent_type=agent_type,
        run_mode=run_mode,
    ).info(f"代理会话已创建: {agent_id}")
    return session


def update_session_state(
    db: Session,
    agent_id: str,
    new_state: str,
    *,
    summary: Optional[str] = None,
    last_error: Optional[str] = None,
    transcript_path: Optional[str] = None,
) -> Optional[TaskAgentSession]:
    """更新代理会话状态，含状态机校验。"""
    session = db.query(TaskAgentSession).filter(TaskAgentSession.agent_id == agent_id).first()
    if not session:
        logger.bind(module="task_runtime", agent_id=agent_id).warning(f"代理会话不存在: {agent_id}")
        return None

    if not validate_transition(session.state, new_state):
        logger.bind(
            module="task_runtime",
            agent_id=agent_id,
            current_state=session.state,
            new_state=new_state,
        ).warning(f"非法的状态转换: {session.state} -> {new_state}")
        return None

    session.state = new_state
    session.updated_at = datetime.now(timezone.utc)

    if new_state == "running" and session.started_at is None:
        session.started_at = datetime.now(timezone.utc)
    if new_state in ("completed", "failed", "stopped", "cancelled"):
        session.ended_at = datetime.now(timezone.utc)

    if summary is not None:
        session.summary = summary
    if last_error is not None:
        session.last_error = last_error
    if transcript_path is not None:
        session.transcript_path = transcript_path

    db.commit()
    db.refresh(session)
    logger.bind(
        module="task_runtime",
        agent_id=agent_id,
        state=new_state,
    ).debug(f"代理状态更新: {agent_id} -> {new_state}")
    return session


def get_session(agent_id: str) -> Optional[TaskAgentSession]:
    """按 agent_id 获取代理会话。"""
    db: Session = SessionLocal()
    try:
        return db.query(TaskAgentSession).filter(TaskAgentSession.agent_id == agent_id).first()
    finally:
        db.close()


def list_sessions(
    *,
    parent_session_id: Optional[str] = None,
    state: Optional[str] = None,
    limit: int = 50,
) -> List[TaskAgentSession]:
    """列出代理会话，支持按父会话或状态过滤。"""
    db: Session = SessionLocal()
    try:
        q = db.query(TaskAgentSession)
        if parent_session_id:
            q = q.filter(TaskAgentSession.parent_session_id == parent_session_id)
        if state:
            q = q.filter(TaskAgentSession.state == state)
        return q.order_by(TaskAgentSession.created_at.desc()).limit(limit).all()
    finally:
        db.close()


def recover_orphaned_sessions() -> int:
    """
    启动时将超时 lease 的 running 会话回收到 pending 状态。
    参考 scheduled_task_manager 的重启恢复模式。
    表尚未创建时静默跳过。
    """
    db: Session = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        orphaned = (
            db.query(TaskAgentSession)
            .filter(
                TaskAgentSession.state == "running",
                TaskAgentSession.lease_expires_at.isnot(None),
                TaskAgentSession.lease_expires_at < now,
            )
            .all()
        )
        for s in orphaned:
            s.state = "failed"
            s.last_error = "Lease expired, recovered on startup"
            s.updated_at = now
            s.ended_at = now
        db.commit()
        if orphaned:
            logger.bind(
                module="task_runtime",
                recovered_count=len(orphaned),
            ).warning(f"回收超时会话: {len(orphaned)} 个")
        return len(orphaned)
    except Exception:
        # 表可能尚未创建，静默跳过
        db.rollback()
        return 0
    finally:
        db.close()


def claim_session(
    db: Session,
    agent_id: str,
    lease_owner: str,
    lease_duration_seconds: int = 300,
) -> Optional[TaskAgentSession]:
    """
    事务性领取代理会话租约，防止多个运行器同时操作同一会话。
    若已有未过期的租约则返回 None。
    """
    now = datetime.now(timezone.utc)
    # 提交已有的隐式事务，避免 autobegin 冲突
    if db._transaction is not None:
        db.commit()
    with db.begin():
        session = db.query(TaskAgentSession).filter(
            TaskAgentSession.agent_id == agent_id,
            TaskAgentSession.state == "running",
        ).first()
        if not session:
            return None

        # 检查是否已有未过期的租约
        if session.lease_owner and session.lease_owner != lease_owner:
            expires_at = session.lease_expires_at
            # SQLite 不存储时区信息，补齐为 UTC
            if expires_at and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at and expires_at > now:
                logger.bind(
                    module="task_runtime",
                    agent_id=agent_id,
                    current_owner=session.lease_owner,
                ).debug(f"会话租约已被持有: {agent_id}")
                return None

        session.lease_owner = lease_owner
        session.lease_expires_at = now + timedelta(seconds=lease_duration_seconds)
        session.updated_at = now

    db.refresh(session)
    logger.bind(
        module="task_runtime",
        agent_id=agent_id,
        lease_owner=lease_owner,
    ).debug(f"会话租约已领取: {agent_id}")
    return session


def release_session(db: Session, agent_id: str, lease_owner: str) -> bool:
    """释放代理会话租约。"""
    session = db.query(TaskAgentSession).filter(
        TaskAgentSession.agent_id == agent_id,
        TaskAgentSession.lease_owner == lease_owner,
    ).first()
    if not session:
        return False
    session.lease_owner = None
    session.lease_expires_at = None
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    logger.bind(
        module="task_runtime",
        agent_id=agent_id,
    ).debug(f"会话租约已释放: {agent_id}")
    return True

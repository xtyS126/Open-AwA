"""
消息总线模块，为 SendMessage 提供 agent 间消息传递与恢复能力。
Phase 1 实现基础的 resume 功能，Phase 4 扩展完整的 mailbox 和 team 通信。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from loguru import logger

from .sessions import get_session, update_session_state
from .team_manager import send_teammate_message, get_mailbox, mark_message_read


def send_message(to_agent_id: str, message: str) -> Dict[str, Any]:
    """
    向指定代理发送消息，用于恢复已停止/失败的代理或给队友发送消息。
    如果代理处于终态（completed/failed/stopped），则尝试将其状态重置为 running 以恢复执行。
    如果代理在团队中且非终态，则将消息投递到邮箱。
    """
    session = get_session(to_agent_id)
    if not session:
        # 代理会话不存在，尝试作为队友消息投递到邮箱
        result = send_teammate_message(
            from_agent_id="system",
            to_agent_id=to_agent_id,
            message=message,
        )
        if result.get("ok"):
            return {
                "ok": True,
                "agent_id": to_agent_id,
                "status": "delivered",
                "message_id": result.get("message_id"),
                "message": f"消息已投递到 {to_agent_id} 的邮箱",
            }
        return {"ok": False, "error": f"代理不存在: {to_agent_id}"}

    if session.state in ("completed", "failed", "stopped"):
        # 恢复：将终态代理重新置为 running
        logger.bind(
            module="task_runtime",
            agent_id=to_agent_id,
            previous_state=session.state,
        ).info(f"恢复代理: {to_agent_id} ({session.state} -> running)")

        new_session = resume_agent(to_agent_id, message)
        if new_session:
            return {
                "ok": True,
                "agent_id": to_agent_id,
                "status": "running",
                "message": f"代理 {to_agent_id} 已恢复运行",
            }
        return {"ok": False, "error": f"无法恢复代理: {to_agent_id}"}

    if session.state == "running":
        # 运行中的代理：尝试投递到邮箱
        result = send_teammate_message(
            from_agent_id="system",
            to_agent_id=to_agent_id,
            message=message,
        )
        mailbox_msg = ""
        if result.get("ok"):
            mailbox_msg = f"，消息已投递到邮箱 ({result.get('message_id')})"

        return {
            "ok": True,
            "agent_id": to_agent_id,
            "status": "running",
            "message": f"代理 {to_agent_id} 仍在运行中，已收到消息{mailbox_msg}",
        }

    return {
        "ok": False,
        "error": f"代理 {to_agent_id} 处于 {session.state} 状态，无法接收消息",
    }


def resume_agent(agent_id: str, resume_message: str) -> Optional[Any]:
    """
    恢复已停止的代理，将状态从终态恢复为 running。
    后续运行时会读取 resume_message 作为继续执行的上下文。
    """
    from db.models import SessionLocal, TaskAgentSession

    db = SessionLocal()
    try:
        # 直接操作 DB，绕过 validate_transition 的终态限制
        session = db.query(TaskAgentSession).filter(TaskAgentSession.agent_id == agent_id).first()
        if not session:
            return None

        session.state = "running"
        session.summary = (
            f"[恢复] {resume_message}"
            if session.summary is None
            else f"{session.summary}\n[恢复] {resume_message}"
        )
        db.commit()
        db.refresh(session)
        return session
    finally:
        db.close()


def send_teammate_msg(
    from_agent_id: str,
    to_agent_id: str,
    message: str,
    team_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    向队友发送消息，存入邮箱。
    Phase 4 扩展：支持 team 内成员间直接通信。
    """
    return send_teammate_message(
        from_agent_id=from_agent_id,
        to_agent_id=to_agent_id,
        message=message,
        team_id=team_id,
    )


def check_mailbox(agent_id: str, unread_only: bool = False) -> list:
    """查询代理的邮箱消息。"""
    return get_mailbox(agent_id, unread_only=unread_only)


def read_message(message_id: str) -> Dict[str, Any]:
    """标记消息为已读。"""
    return mark_message_read(message_id)

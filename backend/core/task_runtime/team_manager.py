"""
团队管理器模块，提供 TeamCreate/TeamDelete、成员管理与邮箱消息路由。
实现实验性多代理协作场景，支持 lead/teammate 角色与共享任务清单。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from db.models import SessionLocal, TaskTeam, TaskTeamMember, TaskMailboxMessage, TaskItem

# 团队状态机：有效转换
VALID_TEAM_TRANSITIONS = {
    "starting": {"active", "failed"},
    "active": {"cleaning", "failed"},
    "cleaning": {"stopped", "failed"},
    "stopped": set(),
    "failed": set(),
}

# 成员状态
MEMBER_STATE_ACTIVE = "active"
MEMBER_STATE_IDLE = "idle"
MEMBER_STATE_STOPPED = "stopped"


def _gen_team_id() -> str:
    return f"team_{uuid.uuid4().hex[:8]}"


def _gen_message_id() -> str:
    return f"msg_{uuid.uuid4().hex[:12]}"


def validate_team_transition(current_state: str, new_state: str) -> bool:
    """校验团队状态转换是否合法。"""
    allowed = VALID_TEAM_TRANSITIONS.get(current_state, set())
    return new_state in allowed


def _get_db(db: Optional[Session] = None, *, commit: bool = False) -> Session:
    """获取数据库会话，支持外部传入（测试用）或新建。返回的会话由调用方负责关闭。"""
    if db is not None:
        if commit:
            db.commit()
        return db
    return SessionLocal()


def create_team(
    lead_agent_id: str,
    name: str = "",
    teammate_agent_ids: Optional[List[Dict[str, str]]] = None,
    task_list_id: Optional[str] = None,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    创建代理团队，lead 作为团队负责人。
    teammate_agent_ids: [{"agent_id": "...", "name": "..."}, ...]
    """
    own_db = db is None
    session = _get_db(db)
    try:
        team_id = _gen_team_id()

        team = TaskTeam(
            team_id=team_id,
            name=name,
            lead_agent_id=lead_agent_id,
            state="starting",
            task_list_id=task_list_id,
        )
        session.add(team)

        lead_member = TaskTeamMember(
            team_id=team_id,
            agent_id=lead_agent_id,
            name="lead",
            role="lead",
            state=MEMBER_STATE_ACTIVE,
        )
        session.add(lead_member)

        members = [{"agent_id": lead_agent_id, "name": "lead", "role": "lead"}]

        if teammate_agent_ids:
            for t in teammate_agent_ids:
                agent_id = t.get("agent_id", "")
                t_name = t.get("name", agent_id)
                member = TaskTeamMember(
                    team_id=team_id,
                    agent_id=agent_id,
                    name=t_name,
                    role="teammate",
                    state=MEMBER_STATE_ACTIVE,
                )
                session.add(member)
                members.append({"agent_id": agent_id, "name": t_name, "role": "teammate"})

        team.member_snapshot_json = {"members": members}
        team.state = "active"

        session.commit()
        session.refresh(team)

        logger.bind(
            module="team_manager",
            team_id=team_id,
            lead_agent_id=lead_agent_id,
        ).info(f"团队创建成功: {team_id} ({name})")

        return {
            "ok": True,
            "team_id": team_id,
            "name": name,
            "lead_agent_id": lead_agent_id,
            "state": "active",
            "members": members,
        }
    except Exception as exc:
        session.rollback()
        logger.bind(module="team_manager", error=str(exc)).error(f"创建团队失败: {exc}")
        return {"ok": False, "error": f"创建团队失败: {str(exc)}"}
    finally:
        if own_db:
            session.close()


def delete_team(team_id: str, db: Optional[Session] = None) -> Dict[str, Any]:
    """删除团队，清理所有成员与未读消息。"""
    own_db = db is None
    session = _get_db(db)
    try:
        team = session.query(TaskTeam).filter(TaskTeam.team_id == team_id).first()
        if not team:
            return {"ok": False, "error": f"团队不存在: {team_id}"}

        if team.state == "cleaning":
            return {"ok": False, "error": f"团队 {team_id} 正在清理中"}

        team.state = "cleaning"
        session.commit()

        session.query(TaskTeamMember).filter(TaskTeamMember.team_id == team_id).delete()
        session.query(TaskMailboxMessage).filter(TaskMailboxMessage.team_id == team_id).delete()

        team.state = "stopped"
        session.commit()

        logger.bind(module="team_manager", team_id=team_id).info(f"团队已删除: {team_id}")
        return {"ok": True, "team_id": team_id, "status": "stopped"}
    except Exception as exc:
        session.rollback()
        logger.bind(module="team_manager", team_id=team_id, error=str(exc)).error(f"删除团队失败: {exc}")
        return {"ok": False, "error": f"删除团队失败: {str(exc)}"}
    finally:
        if own_db:
            session.close()


def add_teammate(
    team_id: str,
    agent_id: str,
    name: str = "",
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """向团队添加新成员。"""
    own_db = db is None
    session = _get_db(db)
    try:
        team = session.query(TaskTeam).filter(TaskTeam.team_id == team_id).first()
        if not team:
            return {"ok": False, "error": f"团队不存在: {team_id}"}

        if team.state != "active":
            return {"ok": False, "error": f"团队 {team_id} 状态为 {team.state}，无法添加成员"}

        existing = session.query(TaskTeamMember).filter(
            TaskTeamMember.team_id == team_id,
            TaskTeamMember.agent_id == agent_id,
        ).first()
        if existing:
            return {"ok": False, "error": f"成员 {agent_id} 已在团队中"}

        member = TaskTeamMember(
            team_id=team_id,
            agent_id=agent_id,
            name=name or agent_id,
            role="teammate",
            state=MEMBER_STATE_ACTIVE,
        )
        session.add(member)

        snapshot = team.member_snapshot_json or {}
        members_list = snapshot.get("members", [])
        members_list.append({"agent_id": agent_id, "name": name or agent_id, "role": "teammate"})
        team.member_snapshot_json = {"members": members_list}

        session.commit()

        logger.bind(module="team_manager", team_id=team_id, agent_id=agent_id).info(f"成员加入团队: {agent_id}")
        return {"ok": True, "team_id": team_id, "agent_id": agent_id, "name": name or agent_id}
    except Exception as exc:
        session.rollback()
        return {"ok": False, "error": f"添加成员失败: {str(exc)}"}
    finally:
        if own_db:
            session.close()


def remove_teammate(
    team_id: str,
    agent_id: str,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """从团队移除成员。"""
    own_db = db is None
    session = _get_db(db)
    try:
        member = session.query(TaskTeamMember).filter(
            TaskTeamMember.team_id == team_id,
            TaskTeamMember.agent_id == agent_id,
        ).first()
        if not member:
            return {"ok": False, "error": f"成员 {agent_id} 不在团队 {team_id} 中"}

        if member.role == "lead":
            return {"ok": False, "error": "不能移除 lead，请先转移 lead 或删除团队"}

        member.state = MEMBER_STATE_STOPPED
        session.commit()

        logger.bind(module="team_manager", team_id=team_id, agent_id=agent_id).info(f"成员离开团队: {agent_id}")
        return {"ok": True, "team_id": team_id, "agent_id": agent_id, "status": "removed"}
    except Exception as exc:
        session.rollback()
        return {"ok": False, "error": f"移除成员失败: {str(exc)}"}
    finally:
        if own_db:
            session.close()


def send_teammate_message(
    from_agent_id: str,
    to_agent_id: str,
    message: str,
    team_id: Optional[str] = None,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """向队友发送消息，存入邮箱。"""
    own_db = db is None
    session = _get_db(db)
    try:
        message_id = _gen_message_id()

        msg = TaskMailboxMessage(
            message_id=message_id,
            from_agent_id=from_agent_id,
            to_agent_id=to_agent_id,
            team_id=team_id,
            payload_json={"message": message},
            delivered=False,
        )
        session.add(msg)
        session.commit()

        logger.bind(
            module="team_manager",
            message_id=message_id,
            from_agent_id=from_agent_id,
            to_agent_id=to_agent_id,
        ).info(f"队友消息已发送: {message_id}")

        return {
            "ok": True,
            "message_id": message_id,
            "from_agent_id": from_agent_id,
            "to_agent_id": to_agent_id,
            "delivered": False,
        }
    except Exception as exc:
        session.rollback()
        return {"ok": False, "error": f"发送消息失败: {str(exc)}"}
    finally:
        if own_db:
            session.close()


def get_mailbox(
    agent_id: str,
    unread_only: bool = False,
    db: Optional[Session] = None,
) -> List[Dict[str, Any]]:
    """获取代理的邮箱消息列表。"""
    own_db = db is None
    session = _get_db(db)
    try:
        query = session.query(TaskMailboxMessage).filter(
            TaskMailboxMessage.to_agent_id == agent_id
        )
        if unread_only:
            query = query.filter(TaskMailboxMessage.delivered == False)
        messages = query.order_by(TaskMailboxMessage.created_at.desc()).limit(100).all()

        return [
            {
                "message_id": m.message_id,
                "from_agent_id": m.from_agent_id,
                "to_agent_id": m.to_agent_id,
                "team_id": m.team_id,
                "payload": m.payload_json,
                "delivered": m.delivered,
                "read_at": m.read_at.isoformat() if m.read_at else None,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ]
    finally:
        if own_db:
            session.close()


def mark_message_read(
    message_id: str,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """标记消息为已读。"""
    own_db = db is None
    session = _get_db(db)
    try:
        msg = session.query(TaskMailboxMessage).filter(
            TaskMailboxMessage.message_id == message_id
        ).first()
        if not msg:
            return {"ok": False, "error": f"消息不存在: {message_id}"}

        msg.delivered = True
        msg.read_at = datetime.now(timezone.utc)
        session.commit()

        return {"ok": True, "message_id": message_id, "delivered": True}
    except Exception as exc:
        session.rollback()
        return {"ok": False, "error": f"标记已读失败: {str(exc)}"}
    finally:
        if own_db:
            session.close()


def list_teams(
    state: Optional[str] = None,
    db: Optional[Session] = None,
) -> List[Dict[str, Any]]:
    """列出团队列表。"""
    own_db = db is None
    session = _get_db(db)
    try:
        query = session.query(TaskTeam)
        if state:
            query = query.filter(TaskTeam.state == state)
        teams = query.order_by(TaskTeam.created_at.desc()).limit(50).all()

        result = []
        for t in teams:
            members = session.query(TaskTeamMember).filter(
                TaskTeamMember.team_id == t.team_id
            ).all()

            result.append({
                "team_id": t.team_id,
                "name": t.name,
                "lead_agent_id": t.lead_agent_id,
                "state": t.state,
                "task_list_id": t.task_list_id,
                "members": [
                    {
                        "agent_id": m.agent_id,
                        "name": m.name,
                        "role": m.role,
                        "state": m.state,
                    }
                    for m in members
                ],
                "created_at": t.created_at.isoformat() if t.created_at else None,
            })
        return result
    finally:
        if own_db:
            session.close()


def get_team(
    team_id: str,
    db: Optional[Session] = None,
) -> Optional[Dict[str, Any]]:
    """获取单个团队详情。"""
    own_db = db is None
    session = _get_db(db)
    try:
        t = session.query(TaskTeam).filter(TaskTeam.team_id == team_id).first()
        if not t:
            return None

        members = session.query(TaskTeamMember).filter(
            TaskTeamMember.team_id == team_id
        ).all()

        tasks = []
        if t.task_list_id:
            task_items = session.query(TaskItem).filter(
                TaskItem.list_id == t.task_list_id
            ).limit(50).all()
            tasks = [
                {
                    "task_id": ti.task_id,
                    "subject": ti.subject,
                    "status": ti.status,
                    "owner_agent_id": ti.owner_agent_id,
                }
                for ti in task_items
            ]

        return {
            "team_id": t.team_id,
            "name": t.name,
            "lead_agent_id": t.lead_agent_id,
            "state": t.state,
            "task_list_id": t.task_list_id,
            "members": [
                {
                    "agent_id": m.agent_id,
                    "name": m.name,
                    "role": m.role,
                    "state": m.state,
                    "joined_at": m.joined_at.isoformat() if m.joined_at else None,
                }
                for m in members
            ],
            "tasks": tasks,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }
    finally:
        if own_db:
            session.close()


def update_teammate_state(
    team_id: str,
    agent_id: str,
    new_state: str,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """更新团队成员状态（active/idle/stopped）。"""
    own_db = db is None
    session = _get_db(db)
    try:
        member = session.query(TaskTeamMember).filter(
            TaskTeamMember.team_id == team_id,
            TaskTeamMember.agent_id == agent_id,
        ).first()
        if not member:
            return {"ok": False, "error": f"成员 {agent_id} 不在团队 {team_id} 中"}

        valid_states = {MEMBER_STATE_ACTIVE, MEMBER_STATE_IDLE, MEMBER_STATE_STOPPED}
        if new_state not in valid_states:
            return {"ok": False, "error": f"无效成员状态: {new_state}，有效值: {valid_states}"}

        member.state = new_state
        session.commit()

        return {"ok": True, "team_id": team_id, "agent_id": agent_id, "state": new_state}
    except Exception as exc:
        session.rollback()
        return {"ok": False, "error": f"更新成员状态失败: {str(exc)}"}
    finally:
        if own_db:
            session.close()

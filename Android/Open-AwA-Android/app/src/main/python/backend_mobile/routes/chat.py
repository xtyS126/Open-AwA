"""
聊天路由 - 会话与消息管理

阶段 2 实现说明：
- 仅提供会话和消息的 CRUD（本地 SQLite 存储）
- LLM 推理由远程后端处理（通过 /api/chat/proxy 转发）
- 不依赖向量库、记忆系统、插件系统
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import Message, SessionModel, User, get_db
from .auth import get_current_user

router = APIRouter(prefix="/api/chat", tags=["Chat"])


class SessionCreate(BaseModel):
    """创建会话请求"""

    title: Optional[str] = Field(None, max_length=256, description="会话标题")


class SessionResponse(BaseModel):
    """会话响应"""

    id: str
    title: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class MessageCreate(BaseModel):
    """创建消息请求"""

    role: str = Field(..., max_length=32, description="消息角色（user/assistant/system）")
    content: str = Field(..., max_length=32000, description="消息内容")


class MessageResponse(BaseModel):
    """消息响应"""

    id: int
    session_id: str
    role: str
    content: str
    created_at: datetime

    class Config:
        orm_mode = True


@router.post("/sessions", response_model=SessionResponse)
async def create_session(
    payload: SessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """创建新会话"""
    session_id = str(uuid4())
    now = datetime.now(timezone.utc)
    session = SessionModel(
        id=session_id,
        user_id=current_user.id,
        title=payload.title or "新会话",
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/sessions", response_model=List[SessionResponse])
async def list_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[SessionModel]:
    """列出当前用户的所有会话"""
    sessions = (
        db.query(SessionModel)
        .filter(SessionModel.user_id == current_user.id)
        .order_by(SessionModel.updated_at.desc())
        .all()
    )
    return sessions


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionModel:
    """获取会话详情"""
    session = (
        db.query(SessionModel)
        .filter(
            SessionModel.id == session_id,
            SessionModel.user_id == current_user.id,
        )
        .first()
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在",
        )
    return session


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """删除会话及其所有消息"""
    session = (
        db.query(SessionModel)
        .filter(
            SessionModel.id == session_id,
            SessionModel.user_id == current_user.id,
        )
        .first()
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在",
        )
    # 删除关联消息
    db.query(Message).filter(Message.session_id == session_id).delete()
    db.delete(session)
    db.commit()


@router.get("/history/{session_id}", response_model=List[MessageResponse])
async def get_history(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[Message]:
    """
    获取会话的消息历史

    容错：当 session_id 为 'undefined' / 'null' / 'default' 字符串时返回空列表。
    前端 ChatPage 在 sessionId 未初始化时仍可能调用本接口（sessionId 字符串化后变成 'undefined'），
    返回空列表而非 404 可避免日志噪音与重试。
    """
    # 前端未选会话时的容错：避免 404 噪音
    if session_id in ("undefined", "null", "default", ""):
        return []

    # 验证会话归属
    session = (
        db.query(SessionModel)
        .filter(
            SessionModel.id == session_id,
            SessionModel.user_id == current_user.id,
        )
        .first()
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在",
        )

    messages = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    return messages


@router.post("/messages/{session_id}", response_model=MessageResponse)
async def create_message(
    session_id: str,
    payload: MessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """向会话添加消息（不含 LLM 推理，仅存储）"""
    # 验证会话归属
    session = (
        db.query(SessionModel)
        .filter(
            SessionModel.id == session_id,
            SessionModel.user_id == current_user.id,
        )
        .first()
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在",
        )

    message = Message(
        session_id=session_id,
        role=payload.role,
        content=payload.content,
    )
    db.add(message)

    # 更新会话时间
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(message)
    return message


# ============================================================================
# /api/conversations 路由（前端 conversationAPI 调用路径）
#
# 前端 frontend/src/shared/api/api.ts 中 conversationAPI 用 '/conversations' 路径，
# 与上面的 '/api/chat/sessions' 路由是同一业务的两种命名。
# 这里添加 /api/conversations 路由以兼容前端，复用 SessionModel 与 Message 表。
# 响应格式按 ConversationSessionSummary / ConversationSessionListResponse 对齐。
# ============================================================================

conversations_router = APIRouter(prefix="/api/conversations", tags=["Conversations"])


class ConversationCreatePayload(BaseModel):
    """前端 ConversationSessionCreatePayload"""

    title: Optional[str] = Field(None, max_length=256)
    session_id: Optional[str] = Field(None, max_length=128)


class ConversationRenamePayload(BaseModel):
    """前端 renameSession 请求体"""

    title: str = Field(..., max_length=256)


def _session_to_summary(session: SessionModel, message_count: int = 0) -> Dict[str, Any]:
    """将 SessionModel 转换为前端 ConversationSessionSummary 格式"""
    return {
        "session_id": session.id,
        "user_id": str(session.user_id),
        "title": session.title or "新会话",
        "summary": "",
        "last_message_preview": "",
        "last_message_role": None,
        "message_count": message_count,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        "last_message_at": session.updated_at.isoformat() if session.updated_at else None,
        "deleted_at": None,
        "restored_at": None,
        "purge_after": None,
        "conversation_metadata": {},
    }


@conversations_router.get("")
async def list_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """列出当前用户的所有会话（前端 ConversationSessionListResponse 格式）"""
    sessions = (
        db.query(SessionModel)
        .filter(SessionModel.user_id == current_user.id)
        .order_by(SessionModel.updated_at.desc())
        .all()
    )
    items = []
    for s in sessions:
        count = db.query(Message).filter(Message.session_id == s.id).count()
        items.append(_session_to_summary(s, count))
    return {
        "items": items,
        "total": len(items),
        "page": 1,
        "page_size": len(items),
        "has_more": False,
    }


@conversations_router.post("")
async def create_conversation(
    payload: ConversationCreatePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """创建新会话（前端 ConversationSessionSummary 格式）"""
    session_id = payload.session_id or str(uuid4())
    now = datetime.now(timezone.utc)
    session = SessionModel(
        id=session_id,
        user_id=current_user.id,
        title=payload.title or "新会话",
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _session_to_summary(session, 0)


@conversations_router.get("/{session_id}")
async def get_conversation(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """获取会话详情"""
    session = (
        db.query(SessionModel)
        .filter(
            SessionModel.id == session_id,
            SessionModel.user_id == current_user.id,
        )
        .first()
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在",
        )
    count = db.query(Message).filter(Message.session_id == session.id).count()
    return _session_to_summary(session, count)


@conversations_router.patch("/{session_id}")
async def rename_conversation(
    session_id: str,
    payload: ConversationRenamePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """重命名会话"""
    session = (
        db.query(SessionModel)
        .filter(
            SessionModel.id == session_id,
            SessionModel.user_id == current_user.id,
        )
        .first()
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在",
        )
    session.title = payload.title
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(session)
    count = db.query(Message).filter(Message.session_id == session.id).count()
    return _session_to_summary(session, count)


@conversations_router.delete("/{session_id}")
async def delete_conversation(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """删除会话（软删除语义，前端按 ConversationSessionSummary 接收）"""
    session = (
        db.query(SessionModel)
        .filter(
            SessionModel.id == session_id,
            SessionModel.user_id == current_user.id,
        )
        .first()
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在",
        )
    count = db.query(Message).filter(Message.session_id == session.id).count()
    summary = _session_to_summary(session, count)
    # 删除关联消息 + 会话
    db.query(Message).filter(Message.session_id == session_id).delete()
    db.delete(session)
    db.commit()
    return summary


# /api/conversations/{session_id}/messages 路由：与 /api/chat/history/{id} 等价
@conversations_router.get("/{session_id}/messages")
async def list_conversation_messages(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """列出会话消息（前端可能调用 /api/conversations/{id}/messages）"""
    session = (
        db.query(SessionModel)
        .filter(
            SessionModel.id == session_id,
            SessionModel.user_id == current_user.id,
        )
        .first()
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在",
        )
    messages = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    return [
        {
            "id": m.id,
            "session_id": m.session_id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ]

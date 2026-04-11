"""
后端接口路由模块，负责接收请求、校验输入并协调业务层返回统一响应。
这些路由函数通常是前端或外部调用与后端内部能力之间的第一层行为边界。
"""

from typing import Union, Dict
from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket
from sqlalchemy.orm import Session

from loguru import logger

from api.dependencies import get_current_user
from api.schemas import ChatMessage, ChatResponse, ConfirmationRequest
from api.services.chat_protocol import build_sse_response, handle_websocket_session
from api.services.ws_manager import ws_manager
from config.logging import REQUEST_ID_HEADER, generate_request_id, sanitize_for_logging
from core.model_service import CLIENT_VERSION_HEADER
from config.security import decode_access_token
from core.agent import AIAgent
from db.models import SessionLocal, User, get_db


router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post("", response_model=Union[ChatResponse, str])
async def chat(
    request: Request,
    message: ChatMessage,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    处理chat相关逻辑，并为调用方返回对应结果。
    如果请求 mode='stream'，则返回 SSE。否则返回 JSON。
    """
    context = {
        "user_id": current_user.id,
        "session_id": message.session_id,
        "username": current_user.username,
        "provider": message.provider,
        "model": message.model,
        "db": db,
        "request_id": getattr(request.state, "request_id", ""),
        "client_version": request.headers.get(CLIENT_VERSION_HEADER, ""),
    }

    logger.bind(
        event="chat_request",
        module="chat",
        action="chat",
        status="start",
        user_id=current_user.id,
        session_id=message.session_id,
        provider=message.provider,
        model=message.model,
        mode=message.mode,
    ).info("chat request received")

    agent = AIAgent(db_session=db)

    if message.mode == "stream":
        return await build_sse_response(agent.process_stream(message.message, context))

    result = await agent.process(message.message, context)

    status_value = result.get("status") or "error"
    logger.bind(
        event="chat_response",
        module="chat",
        action="chat",
        status=status_value,
        user_id=current_user.id,
        session_id=message.session_id,
        has_error=bool(result.get("error")),
    ).info("chat request finished")

    return ChatResponse(
        status=status_value,
        response=result.get("response", ""),
        reasoning_content=result.get("reasoning_content"),
        session_id=message.session_id,
        error=result.get("error"),
        request_id=context["request_id"],
    )


@router.post(
    "/confirm",
    summary="确认待执行操作",
    description="对智能体生成的待确认步骤进行确认或拒绝。"
)
async def confirm_operation(
    request: Request,
    confirmation: ConfirmationRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    处理confirm、operation相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    if not confirmation.step:
        logger.bind(
            event="chat_confirm_invalid",
            module="chat",
            action="confirm",
            status="failure",
            user_id=current_user.id,
        ).warning("confirmation step missing")
        raise HTTPException(status_code=400, detail="No step provided for confirmation")

    context = {
        "user_id": current_user.id,
        "session_id": "default",
        "username": current_user.username,
        "request_id": getattr(request.state, "request_id", ""),
        "client_version": request.headers.get(CLIENT_VERSION_HEADER, ""),
        "idempotency_key": confirmation.step.get("idempotency_key") if isinstance(confirmation.step, dict) else None,
    }

    agent = AIAgent(db_session=db)

    result = await agent.handle_confirmation(
        confirmed=confirmation.confirmed,
        step=confirmation.step,
        context=context
    )

    logger.bind(
        event="chat_confirm_done",
        module="chat",
        action="confirm",
        status="success",
        user_id=current_user.id,
        confirmed=confirmation.confirmed,
    ).info("confirmation handled")

    return result


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(None)
):
    """
    处理websocket、endpoint相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    if token is None:
        await websocket.close(code=4001, reason="Missing authentication token")
        return

    connection_request_id = str(
        websocket.headers.get(REQUEST_ID_HEADER, "") or generate_request_id()
    ).strip() or generate_request_id()
    client_version = websocket.headers.get(CLIENT_VERSION_HEADER, "")

    payload = decode_access_token(token)
    if payload is None:
        await websocket.close(code=4002, reason="Invalid or expired token")
        return

    username = payload.get("sub")
    if username is None:
        await websocket.close(code=4003, reason="Invalid token payload")
        return

    db = SessionLocal()

    try:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            await websocket.close(code=4004, reason="User not found")
            db.close()
            return
    except Exception as e:
        logger.bind(
            event="chat_ws_db_error",
            module="chat",
            action="websocket",
            status="failure",
            error_type=type(e).__name__,
            error_message=sanitize_for_logging(str(e)),
        ).error("database query failed")
        await websocket.close(code=4004, reason="Database error")
        db.close()
        return

    await ws_manager.connect(session_id, websocket)

    user_id = user.id
    
    logger.bind(
        event="chat_ws_connected",
        module="chat",
        action="websocket",
        status="connected",
        session_id=session_id,
        user_id=user_id,
    ).info("websocket connected")

    agent = AIAgent(db_session=db)
    
    try:
        await handle_websocket_session(
            websocket=websocket,
            session_id=session_id,
            user_id=user_id,
            username=username,
            client_version=client_version,
            connection_request_id=connection_request_id,
            agent=agent,
        )
    finally:
        # Agent has completed processing for this websocket session.
        # It's safe to close the database session here.
        db.close()


@router.get(
    "/history/{session_id}",
    summary="获取会话历史",
    description="返回指定会话在短期记忆中保存的历史消息列表。"
)
async def get_chat_history(
    session_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    获取指定会话的聊天历史，先验证会话所有权。
    防止用户越权访问其他用户的聊天记录。
    """
    from db.models import ShortTermMemory, ConversationRecord

    # 验证会话属于当前用户
    record = db.query(ConversationRecord).filter(
        ConversationRecord.session_id == session_id,
        ConversationRecord.user_id == current_user.id
    ).first()
    if not record:
        raise HTTPException(status_code=403, detail="Access denied: session does not belong to current user")

    messages = db.query(ShortTermMemory).filter(
        ShortTermMemory.session_id == session_id
    ).order_by(ShortTermMemory.timestamp).all()

    logger.bind(
        event="chat_history_loaded",
        module="chat",
        action="history",
        status="success",
        user_id=current_user.id,
        session_id=session_id,
        count=len(messages),
    ).info("chat history loaded")

    return [
        {
            "id": msg.id,
            "role": msg.role,
            "content": msg.content,
            "timestamp": msg.timestamp
        }
        for msg in messages
    ]

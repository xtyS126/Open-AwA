from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from typing import Dict
import json

from loguru import logger

from api.dependencies import get_current_user
from api.schemas import ChatMessage, ChatResponse, ConfirmationRequest
from config.logging import sanitize_for_logging
from config.security import decode_access_token
from core.agent import AIAgent
from db.models import SessionLocal, User, get_db


router = APIRouter(prefix="/chat", tags=["Chat"])


agent = AIAgent()
active_connections: Dict[str, WebSocket] = {}


@router.post("", response_model=ChatResponse)
async def chat(
    message: ChatMessage,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    context = {
        "user_id": current_user.id,
        "session_id": message.session_id,
        "username": current_user.username,
        "provider": message.provider,
        "model": message.model,
        "db": db
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
    ).info("chat request received")

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
        session_id=message.session_id,
        error=result.get("error")
    )


@router.post(
    "/confirm",
    summary="确认待执行操作",
    description="对智能体生成的待确认步骤进行确认或拒绝。"
)
async def confirm_operation(
    confirmation: ConfirmationRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
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
        "username": current_user.username
    }

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
    if token is None:
        await websocket.close(code=4001, reason="Missing authentication token")
        return

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
        return
    finally:
        db.close()

    await websocket.accept()

    user_id = user.id
    active_connections[session_id] = websocket

    logger.bind(
        event="chat_ws_connected",
        module="chat",
        action="websocket",
        status="connected",
        session_id=session_id,
        user_id=user_id,
    ).info("websocket connected")

    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)

            if message_data.get("type") == "message":
                context = {
                    "session_id": session_id,
                    "user_id": user_id,
                    "username": username
                }

                result = await agent.process(message_data.get("content", ""), context)

                await websocket.send_json({
                    "type": "response",
                    "status": result.get("status"),
                    "content": result.get("response", ""),
                    "results": result.get("results", [])
                })

            elif message_data.get("type") == "confirm":
                confirmed = message_data.get("confirmed", False)
                step = message_data.get("step")

                context = {
                    "session_id": session_id,
                    "user_id": user_id,
                    "username": username
                }
                result = await agent.handle_confirmation(confirmed, step, context)

                await websocket.send_json({
                    "type": "confirmation_result",
                    "result": result
                })

    except WebSocketDisconnect:
        if session_id in active_connections:
            del active_connections[session_id]
        logger.bind(
            event="chat_ws_disconnected",
            module="chat",
            action="websocket",
            status="disconnected",
            session_id=session_id,
            user_id=user_id,
        ).info("websocket disconnected")
    except Exception as exc:
        if session_id in active_connections:
            del active_connections[session_id]
        logger.bind(
            event="chat_ws_error",
            module="chat",
            action="websocket",
            status="failure",
            session_id=session_id,
            user_id=user_id,
            error_type=type(exc).__name__,
            error_message=sanitize_for_logging(str(exc)),
        ).exception("websocket failed")
        await websocket.close(code=4005, reason="Internal server error")
    finally:
        if session_id in active_connections:
            del active_connections[session_id]


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
    from db.models import ShortTermMemory

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

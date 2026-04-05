"""
后端接口路由模块，负责接收请求、校验输入并协调业务层返回统一响应。
这些路由函数通常是前端或外部调用与后端内部能力之间的第一层行为边界。
"""

import hashlib
from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Dict
import json

from loguru import logger

from api.dependencies import get_current_user
from api.schemas import ChatMessage, ChatResponse, ConfirmationRequest
from config.logging import REQUEST_ID_HEADER, generate_request_id, sanitize_for_logging
from core.metrics import record_websocket_message_metric
from core.model_service import CLIENT_VERSION_HEADER, build_standard_error
from config.security import decode_access_token
from core.agent import AIAgent
from db.models import SessionLocal, User, get_db


router = APIRouter(prefix="/chat", tags=["Chat"])


agent = AIAgent()
active_connections: Dict[str, WebSocket] = {}
WS_CHUNK_SIZE = 1024


def _build_chunk_checksum(payload_text: str) -> str:
    """
    为完整消息生成校验值，客户端可据此校验分段重组结果。
    """

    return hashlib.sha256(payload_text.encode("utf-8")).hexdigest()


async def _send_chunked_websocket_message(
    websocket: WebSocket,
    message_type: str,
    payload: Dict,
    request_id: str,
) -> None:
    """
    先发送分段消息，再发送兼容旧协议的完整消息。
    这样既满足新协议对 seq/checksum 的要求，也尽量不破坏现有前端行为。
    """

    payload_text = json.dumps(payload, ensure_ascii=False, default=str)
    checksum = _build_chunk_checksum(payload_text)
    chunks = [payload_text[index:index + WS_CHUNK_SIZE] for index in range(0, len(payload_text), WS_CHUNK_SIZE)] or [""]

    for seq, chunk in enumerate(chunks, start=1):
        await websocket.send_json(
            {
                "type": f"{message_type}_chunk",
                "request_id": request_id,
                "seq": seq,
                "total": len(chunks),
                "checksum": checksum,
                "chunk": chunk,
            }
        )
        record_websocket_message_metric(f"{message_type}_chunk", "sent")

    final_payload = dict(payload)
    final_payload["type"] = message_type
    final_payload["request_id"] = request_id
    final_payload["checksum"] = checksum
    final_payload["chunks_total"] = len(chunks)
    await websocket.send_json(final_payload)
    record_websocket_message_metric(message_type, "sent")


@router.post("")
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

    if message.mode == "stream":
        async def event_generator():
            async for chunk in agent.process_stream(message.message, context):
                # Format as SSE
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            
        return StreamingResponse(event_generator(), media_type="text/event-stream")

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
                record_websocket_message_metric("message", "received")
                message_request_id = str(
                    message_data.get("request_id") or connection_request_id
                ).strip() or connection_request_id
                context = {
                    "session_id": session_id,
                    "user_id": user_id,
                    "username": username,
                    "request_id": message_request_id,
                    "client_version": client_version,
                    "idempotency_key": message_data.get("idempotency_key"),
                }

                result = await agent.process(message_data.get("content", ""), context)

                await _send_chunked_websocket_message(
                    websocket,
                    "response",
                    {
                        "status": result.get("status"),
                        "content": result.get("response", ""),
                        "results": result.get("results", []),
                    },
                    message_request_id,
                )

            elif message_data.get("type") == "confirm":
                record_websocket_message_metric("confirm", "received")
                confirmed = message_data.get("confirmed", False)
                step = message_data.get("step")
                message_request_id = str(
                    message_data.get("request_id") or connection_request_id
                ).strip() or connection_request_id

                context = {
                    "session_id": session_id,
                    "user_id": user_id,
                    "username": username,
                    "request_id": message_request_id,
                    "client_version": client_version,
                    "idempotency_key": message_data.get("idempotency_key")
                    or (step.get("idempotency_key") if isinstance(step, dict) else None),
                }
                result = await agent.handle_confirmation(confirmed, step, context)

                await _send_chunked_websocket_message(
                    websocket,
                    "confirmation_result",
                    {
                        "result": result,
                    },
                    message_request_id,
                )

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
        record_websocket_message_metric("websocket", "error")
        error_request_id = connection_request_id
        try:
            await _send_chunked_websocket_message(
                websocket,
                "error",
                {
                    "error": build_standard_error(
                        "websocket_internal_error",
                        "WebSocket 内部错误",
                        request_id=error_request_id,
                        details={"reason": str(exc), "session_id": session_id},
                    )
                },
                error_request_id,
            )
        finally:
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
    """
    获取chat、history相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
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

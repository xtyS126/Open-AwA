"""
后端接口路由模块，负责接收请求、校验输入并协调业务层返回统一响应。
这些路由函数通常是前端或外部调用与后端内部能力之间的第一层行为边界。
"""

from typing import Union, Dict
import asyncio
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse
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
        # 使用 asyncio.to_thread 包裹同步 ORM 查询，避免阻塞 asyncio 事件循环
        user = await asyncio.to_thread(
            lambda: db.query(User).filter(User.username == username).first()
        )
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
    
    try:
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
        # 统一在此处关闭数据库连接，无论是正常结束还是异常退出
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
    获取指定会话的聊天历史。
    验证会话属于当前用户，防止越权访问。
    如果会话没有 ConversationRecord 但有 ShortTermMemory，仍允许访问。
    """
    from db.models import ShortTermMemory, ConversationRecord

    # 验证会话属于当前用户（如果存在 ConversationRecord）
    record = db.query(ConversationRecord).filter(
        ConversationRecord.session_id == session_id,
    ).first()
    if record and record.user_id != current_user.id:
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


# ---- 文件上传相关 ----

# 允许上传的文件扩展名白名单
ALLOWED_UPLOAD_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp",  # 图片
    ".pdf", ".txt", ".md", ".csv",              # 文档
}
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB
UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"


@router.post(
    "/upload",
    summary="上传聊天附件",
    description="上传图片或文档文件作为聊天消息的附件，返回访问 URL。"
)
async def upload_chat_file(
    file: UploadFile,
    current_user=Depends(get_current_user),
):
    """
    接收文件上传，校验类型和大小后保存到 uploads 目录。
    返回文件元信息和访问 URL。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    # 校验文件扩展名（防止任意文件上传）
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{ext}，仅允许 {', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}"
        )

    # 读取文件内容并校验大小
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail=f"文件大小超过限制（最大 {MAX_UPLOAD_SIZE // 1024 // 1024}MB）")

    # 生成安全文件名（UUID + 原始扩展名，防止路径遍历）
    safe_filename = f"{uuid.uuid4().hex}{ext}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_path = UPLOAD_DIR / safe_filename

    with open(file_path, "wb") as f:
        f.write(content)

    # 判断文件类型分类
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    file_type = "image" if ext in image_exts else "file"

    logger.bind(
        event="chat_file_uploaded",
        module="chat",
        action="upload",
        status="success",
        user_id=current_user.id,
        filename=file.filename,
        size=len(content),
    ).info("file uploaded")

    return {
        "filename": safe_filename,
        "original_name": file.filename,
        "size": len(content),
        "type": file_type,
        "url": f"/api/chat/uploads/{safe_filename}",
    }


@router.get(
    "/uploads/{filename}",
    summary="访问已上传的文件",
    description="通过文件名访问之前上传的聊天附件。"
)
async def get_uploaded_file(
    filename: str,
    current_user=Depends(get_current_user),
):
    """
    返回已上传的文件。文件名必须是系统生成的安全文件名。
    """
    # 防止路径遍历攻击：确保文件名不包含路径分隔符
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="非法文件名")

    file_path = UPLOAD_DIR / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(file_path)

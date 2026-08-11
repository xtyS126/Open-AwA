"""
后端接口路由模块，负责接收请求、校验输入并协调业务层返回统一响应。
这些路由函数通常是前端或外部调用与后端内部能力之间的第一层行为边界。
"""

from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Union
import asyncio
import functools
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from loguru import logger

from api.dependencies import get_current_user
from api.routes._session_guard import assert_session_owner
from api.schemas import ChatMessage, ChatResponse, ChatUndoOperationRequest, ConfirmationRequest, UserFeedbackRequest
from api.security.ws_auth import (
    extract_token_from_subprotocol,
    resolve_ws_user_by_name,
    resolve_ws_user_from_token,
    validate_ws_origin,
)
from api.services.chat_protocol import build_sse_response, handle_websocket_session
from api.services.assistant_context_service import (
    AssistantContextResourceError,
    build_session_agent_context,
)
from api.services.ws_manager import ws_manager
from api.adapters.workflow_repository_adapter import WorkflowRepositoryAdapter
from config.logging import REQUEST_ID_HEADER, generate_request_id, sanitize_for_logging
from config.runtime_paths import UPLOADS_DIR
from core.litellm_adapter import CLIENT_VERSION_HEADER
from config.security import ACCESS_TOKEN_COOKIE_NAME, decode_access_token
from core.agent import AIAgent
from core.agent_registry import get_registry
from core.agent_runtime_warmup import prewarm_agent_memory
from core.chat_task_manager import (
    generate_task_id,
    get_chat_task_manager,
)
from db.models import ConversationRecord, SessionLocal, User, get_db


router = APIRouter(prefix="/chat", tags=["Chat"])


async def _trigger_profile_n_turn_fallback(user_id: str) -> None:
    """
    递增对话轮次计数器，并在达阈值时强制触发画像提取（N 轮兜底）。

    整个方法设计为后台任务：由 chat 路由通过 asyncio.create_task 启动，
    不阻塞 chat 响应。使用独立 db session（SessionLocal），避免与请求级
    session 共享生命周期（请求结束后 session 会被关闭）。

    流程：
    1. 递增 turns_since_last_extract
    2. 读取 n_threshold（用户可配置，默认 5）
    3. 若 turns >= n_threshold，调用 maybe_extract(force=True)
       maybe_extract 内部有 asyncio.Lock 去重，与 feedback 触发不会重复执行

    异常全部捕获并记录日志，不影响 chat 主流程。

    Args:
        user_id: 用户 ID，从 current_user.id 获取
    """
    if not user_id:
        return
    async_db = SessionLocal()
    try:
        from plugins.user_profile_builtin.coordinator import get_coordinator

        coordinator = get_coordinator()
        turns = await coordinator.increment_turns(user_id, async_db)
        settings = coordinator.get_settings(user_id, async_db)
        n_threshold = settings.get("n_threshold") or coordinator.DEFAULT_N_THRESHOLD

        if turns >= n_threshold:
            # 达阈值：在同一 session 内强制触发画像提取
            # maybe_extract 内部有锁去重，与 feedback 触发不会重复执行
            logger.bind(
                event="profile_n_turn_fallback_triggered",
                module="chat",
                user_id=user_id,
                turns=turns,
                n_threshold=n_threshold,
            ).info("N 轮兜底触发画像提取")
            await coordinator.maybe_extract(user_id, async_db, force=True)
    except Exception as exc:
        # N 轮兜底是辅助路径，不静默吞异常，记录完整堆栈便于诊断
        logger.opt(exception=True).warning(
            f"N 轮兜底触发画像提取失败: {exc}"
        )
    finally:
        async_db.close()


async def _stream_with_profile_trigger(
    stream_gen: AsyncGenerator[Dict[str, Any], None],
    user_id: str,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    包装流式生成器，在流结束（正常/异常/取消）后触发 N 轮兜底。

    用 try/finally 确保无论流如何结束都执行计数器递增。
    通过 asyncio.create_task 启动后台任务，不阻塞 [DONE] 信号发送。

    Args:
        stream_gen: 原始流式生成器（agent.process_stream 返回值）
        user_id: 用户 ID

    Yields:
        原始流式生成器的每个 chunk
    """
    try:
        async for chunk in stream_gen:
            yield chunk
    finally:
        # 流结束后启动后台任务，不阻塞 [DONE] 信号发送
        if user_id:
            asyncio.create_task(_trigger_profile_n_turn_fallback(user_id))


def _ws_load_user_by_name(username: str):
    """
    WebSocket 鉴权专用：在独立短生命周期会话内查询用户。
    避免把请求外层 Session 传入 asyncio.to_thread（SQLAlchemy Session 非线程安全）。
    """
    return resolve_ws_user_by_name(username)


def _ws_resolve_user_from_token(token: Optional[str]) -> Optional[User]:
    """
    WebSocket 鉴权专用：统一解析 token 为 User，支持 API Key 与 JWT 两种路径。

    实现已提取到 api/security/ws_auth.py 的 resolve_ws_user_from_token，
    供 chat / terminal / weixin 等多处 WS 端点复用（保持单一实现源）。
    本函数保留为兼容别名，避免散落调用点重复实现鉴权逻辑。
    """
    return resolve_ws_user_from_token(token)


def _ws_load_session_owner_id(session_id: str) -> str:
    """
    WebSocket 鉴权专用：在独立短生命周期会话内查询会话归属 user_id。
    未找到会话记录时返回空字符串，由调用方决定是否放行。
    """
    with SessionLocal() as db:
        record = db.query(ConversationRecord).filter(
            ConversationRecord.session_id == session_id
        ).first()
        return str(getattr(record, "user_id", "") or "").strip()


def _build_upload_metadata_path(filename: str) -> Path:
    """
    为上传文件生成元数据路径。
    元数据用于校验文件所有权，避免不同用户互相访问附件。
    """
    return UPLOAD_DIR / f"{filename}.meta.json"


def _validate_uploaded_filename(filename: str) -> None:
    """
    校验系统生成的上传文件名格式，避免任意路径或任意文件名探测。
    """
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="非法文件名")

    stem, ext = os.path.splitext(filename)
    if ext.lower() not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail="非法文件类型")

    if len(stem) != 32:
        raise HTTPException(status_code=400, detail="非法文件名")

    try:
        int(stem, 16)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法文件名") from exc


def _write_file_bytes_sync(file_path: Path, content: bytes) -> None:
    """同步写入文件字节（供 asyncio.to_thread 调用，避免阻塞事件循环）。"""
    with open(file_path, "wb") as f:
        f.write(content)


def _write_metadata_sync(metadata_path: Path, metadata: Dict[str, Any]) -> None:
    """同步写入元数据 JSON（供 asyncio.to_thread 调用）。"""
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False)


def _read_metadata_sync(metadata_path: Path) -> Dict[str, Any]:
    """同步读取元数据 JSON（供 asyncio.to_thread 调用）。"""
    with open(metadata_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_user_id_for_rate_limit(request: Request) -> str:
    """从 Authorization header 提取用户标识用于限流，降级用客户端 IP。

    认证依赖 get_current_user 仅返回 User 对象，未将 user_id 写入 request.state，
    因此需从 Bearer token 解析 sub（用户名）作为限流键。token 解析失败时
    降级为 IP 限流，保证限流不因 token 异常而失效。
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            payload = decode_access_token(token)
            if payload and payload.get("sub"):
                return f"user:{payload['sub']}"
        except Exception as exc:
            logger.bind(
                event="rate_limit_token_decode_failed",
                error_type=type(exc).__name__,
            ).debug("限流身份令牌解析失败，降级为客户端 IP")
    return request.client.host if request.client else "unknown"


def _user_rate_limit(limit_str: str) -> Callable[[Callable], Callable]:
    """运行时从 request.app.state.limiter 获取限流器并应用的装饰器。

    避免顶层 ``from main import limiter`` 导致循环导入：
    main.py L24 导入 chat.py，而 limiter 在 main.py L1296 才定义。
    本装饰器在首次请求时从 app.state.limiter 取得 slowapi Limiter 实例，
    对原函数应用 ``limiter.limit(...)`` 并缓存，后续请求直接复用缓存。

    limiter 未配置（如测试环境）时直接执行原函数，不阻塞业务。
    """
    def decorator(func: Callable) -> Callable:
        cache: Dict[str, Any] = {"decorated": None}

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request: Optional[Request] = kwargs.get("request")
            if request is None and args:
                request = args[0]
            app_state = getattr(getattr(request, "app", None), "state", None)
            limiter = getattr(app_state, "limiter", None) if app_state else None
            if limiter is None:
                return await func(*args, **kwargs)
            if cache["decorated"] is None:
                cache["decorated"] = limiter.limit(
                    limit_str, key_func=_get_user_id_for_rate_limit
                )(func)
            return await cache["decorated"](*args, **kwargs)

        return wrapper

    return decorator


@router.post("", response_model=Union[ChatResponse, str])
@_user_rate_limit("30/minute")
async def chat(
    request: Request,
    message: ChatMessage,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
) -> Dict[str, Any]:
    """
    处理chat相关逻辑，并为调用方返回对应结果。
    如果请求 mode='stream'，则返回 SSE。否则返回 JSON。
    """
    # 校验 session 归属，防止用户越权使用他人 session_id 污染记忆
    assert_session_owner(db, message.session_id, current_user.id)

    # TTFT 诊断：路由入口计时起点（中间件+认证已在此前完成）
    import time as _chat_time
    _chat_t0 = _chat_time.time()

    context = {
        "user_id": current_user.id,
        "session_id": message.session_id,
        "username": current_user.username,
        "provider": message.provider,
        "model": message.model,
        "db": db,
        "request_id": getattr(request.state, "request_id", ""),
        "client_version": request.headers.get(CLIENT_VERSION_HEADER, ""),
        "attachments": [a.dict() for a in message.attachments] if message.attachments else None,
        "thinking_enabled": message.thinking_enabled,
        "thinking_depth": message.thinking_depth,
        "max_tool_call_rounds": message.max_tool_call_rounds,
        "continuation": message.continuation.dict() if message.continuation else None,
        "agent_type": getattr(message, "agent_type", None) or "general-purpose",
    }
    try:
        context = build_session_agent_context(
            db,
            message.session_id,
            str(current_user.id),
            context,
        )
    except AssistantContextResourceError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

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

    try:
        # 首次创建 Agent 前在线程中预热共享向量运行时，避免冻结服务事件循环。
        await prewarm_agent_memory(SessionLocal)
        # 通过 AIAgentRegistry 复用 AIAgent 实例，并在整个请求期间独占用户级实例
        _registry_t0 = _chat_time.time()
        registry = get_registry()
        logger.bind(
            event="ttft_stage",
            module="chat",
            stage="agent_registry",
            session_id=message.session_id,
            elapsed_ms=round((_chat_time.time() - _registry_t0) * 1000, 2),
            total_ms=round((_chat_time.time() - _chat_t0) * 1000, 2),
        ).info("阶段耗时: agent_registry")

        if message.mode == "stream":
            # 任务 ID：前端可传入（用于重连），缺省时后端生成
            task_id = message.task_id or generate_task_id()
            task_manager = get_chat_task_manager()
            # 确保清理循环已启动（幂等）
            task_manager.start_cleanup_loop()

            # 注册任务到管理器（若 task_id 已存在则复用，支持前端重连同一 task_id）
            await task_manager.register_task(
                task_id=task_id,
                user_id=current_user.id,
                session_id=message.session_id,
                request_id=context["request_id"],
            )

            # 检查任务是否已在运行（前端重连场景）：已运行则直接订阅，不重复启动
            status_info = await task_manager.get_task_status(task_id)
            if status_info and status_info["status"] == "pending":
                # 首次注册：启动后台任务执行 agent.process_stream
                async def leased_stream() -> AsyncGenerator[Dict[str, Any], None]:
                    """在任务完整生命周期内持有用户级 Agent 租约。"""
                    async with registry.acquire(current_user.id, db) as agent:
                        async for chunk in agent.process_stream(message.message, context):
                            yield chunk

                # 包装：流结束后触发 N 轮兜底
                wrapped_gen = _stream_with_profile_trigger(leased_stream(), current_user.id)
                try:
                    await task_manager.start_task(task_id, lambda: wrapped_gen)
                except Exception:
                    # 注册成功但启动失败时立即标记取消，避免留下无法订阅的孤儿任务。
                    await task_manager.cancel_task(task_id)
                    raise

            # 订阅任务事件流（断连重连时从 from_seq=0 开始回放全部历史事件）
            # 注意：subscribe 是 async generator，build_sse_response 会消费它
            from_seq = 0  # 完整回放历史事件，确保前端重连后能看到全部输出
            subscription = task_manager.subscribe(task_id, from_seq)

            # 构造 SSE 响应，附带 task_id 响应头方便前端记录
            sse_response = await build_sse_response(subscription)
            # 在响应头中暴露 task_id，前端首次连接时记录、重连时复用
            sse_response.headers["X-Chat-Task-Id"] = task_id
            return sse_response

        async with registry.acquire(current_user.id, db) as agent:
            result = await agent.process(message.message, context)
        # 非流式：chat 完成后启动后台任务递增计数器 + 检查 N 轮兜底
        # asyncio.create_task 确保不阻塞 chat 响应，任务在后台继续执行
        asyncio.create_task(_trigger_profile_n_turn_fallback(current_user.id))
    except asyncio.CancelledError:
        logger.bind(
            event="chat_cancelled",
            module="chat",
            action="chat",
            user_id=current_user.id,
            session_id=message.session_id,
        ).info("非流式 Agent 任务被用户取消")
        return ChatResponse(
            status="cancelled",
            response="",
            session_id=message.session_id,
            error={"code": "task_cancelled", "message": "任务已被用户取消"},
            request_id=context["request_id"],
        )
    except Exception as exc:
        logger.bind(
            event="chat_error",
            module="chat",
            action="chat",
            status="error",
            user_id=current_user.id,
            session_id=message.session_id,
        ).error(f"Agent处理异常: {exc}")
        return ChatResponse(
            status="error",
            response="",
            session_id=message.session_id,
            error={"code": "agent_process_failed", "message": f"处理请求时发生内部错误: {str(exc)}"},
            request_id=context["request_id"],
        )

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
) -> Dict[str, Any]:
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

    session_id = confirmation.session_id or confirmation.step.get("session_id") or "default"
    context = {
        "user_id": current_user.id,
        "session_id": session_id,
        "username": current_user.username,
        "request_id": getattr(request.state, "request_id", ""),
        "client_version": request.headers.get(CLIENT_VERSION_HEADER, ""),
        "idempotency_key": confirmation.step.get("idempotency_key") if isinstance(confirmation.step, dict) else None,
    }

    agent = AIAgent(
        db_session=db,
        workflow_repository=WorkflowRepositoryAdapter(db),
        memory_session_factory=SessionLocal,
    )

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


# ---- 取消正在执行的 Agent 任务 ----

@router.post("/cancel/{session_id}", summary="取消正在执行的 Agent 任务")
async def cancel_agent_task(
    session_id: str,
    current_user=Depends(get_current_user)
) -> Dict[str, Any]:
    """取消指定会话中正在执行的 Agent 任务。"""
    from core.agent_task_registry import get_agent_tasks

    tasks = get_agent_tasks(str(current_user.id), session_id)
    active_tasks = [task for task in tasks if not task.done()]
    if not active_tasks:
        raise HTTPException(status_code=404, detail="没有找到正在执行的任务")

    for task in active_tasks:
        task.cancel()
    logger.bind(
        event="chat_cancel",
        session_id=session_id,
        user_id=current_user.id
    ).info("agent task cancelled by user")

    return {
        "status": "cancelled",
        "session_id": session_id,
        "cancelled_count": len(active_tasks),
        "message": "任务取消请求已发送",
    }


# ---- 聊天任务管理（SSE 断连重连恢复） ----

@router.get(
    "/stream/{task_id}",
    summary="重连订阅聊天任务 SSE 流",
    description="前端切换页面或网络断开后，通过 task_id 重连订阅任务事件流，从历史事件回放后继续实时接收。",
)
async def resubscribe_chat_task(
    task_id: str,
    from_seq: int = Query(0, ge=0, description="起始事件 seq（含），默认 0 完整回放"),
    current_user=Depends(get_current_user),
):
    """重连订阅聊天任务事件流。"""
    task_manager = get_chat_task_manager()
    status_info = await task_manager.get_task_status(task_id)
    if status_info is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    # 鉴权：仅任务所有者可订阅
    if status_info.get("user_id") != current_user.id:
        raise HTTPException(status_code=403, detail="无权订阅他人任务")

    logger.bind(
        event="chat_task_resubscribe",
        module="chat",
        task_id=task_id,
        from_seq=from_seq,
        task_status=status_info.get("status"),
        user_id=current_user.id,
    ).info("重连订阅聊天任务")

    subscription = task_manager.subscribe(task_id, from_seq)
    sse_response = await build_sse_response(subscription)
    sse_response.headers["X-Chat-Task-Id"] = task_id
    return sse_response


@router.post(
    "/cancel-task/{task_id}",
    summary="取消指定聊天任务",
    description="取消指定 task_id 对应的聊天任务，级联清理所有子任务（工具执行、子代理等）。",
)
async def cancel_chat_task(
    task_id: str,
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """取消指定聊天任务。"""
    task_manager = get_chat_task_manager()
    status_info = await task_manager.get_task_status(task_id)
    if status_info is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    if status_info.get("user_id") != current_user.id:
        raise HTTPException(status_code=403, detail="无权取消他人任务")

    cancelled = await task_manager.cancel_task(task_id)
    logger.bind(
        event="chat_task_cancel",
        module="chat",
        task_id=task_id,
        user_id=current_user.id,
        cancelled=cancelled,
    ).info("用户取消聊天任务")

    return {
        "status": "cancelled" if cancelled else "already_done",
        "task_id": task_id,
        "message": "任务取消请求已发送" if cancelled else "任务已结束或不存在",
    }


@router.get(
    "/tasks",
    summary="列出当前用户的聊天任务",
    description="返回当前用户进行中的聊天任务列表，前端用于切回页面时检查可恢复的任务。",
)
async def list_chat_tasks(
    current_user=Depends(get_current_user),
    session_id: Optional[str] = Query(None, description="按会话过滤"),
    include_finished: bool = Query(False, description="是否包含已结束任务"),
) -> Dict[str, Any]:
    """列出当前用户的聊天任务。"""
    task_manager = get_chat_task_manager()
    tasks = await task_manager.list_user_tasks(
        user_id=current_user.id,
        session_id=session_id,
        include_finished=include_finished,
    )
    return {"tasks": tasks, "count": len(tasks)}


@router.get(
    "/tasks/{task_id}",
    summary="查询聊天任务状态",
    description="返回指定 task_id 的任务状态、事件计数、错误信息等。",
)
async def get_chat_task_status(
    task_id: str,
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """查询指定聊天任务状态。"""
    task_manager = get_chat_task_manager()
    status_info = await task_manager.get_task_status(task_id)
    if status_info is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    if status_info.get("user_id") != current_user.id:
        raise HTTPException(status_code=403, detail="无权查询他人任务")
    return status_info


# ---- 用户反馈 ----

@router.post(
    "/feedback",
    summary="提交用户消息反馈",
    description="对助手回复进行点赞或点踩反馈。"
)
async def submit_feedback(
    feedback: UserFeedbackRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
) -> Dict[str, Any]:
    """记录用户对助手消息的显式反馈。"""
    from core.feedback import feedback_layer_registry

    try:
        await feedback_layer_registry.record_explicit_feedback(
            session_id=feedback.session_id,
            message_id=feedback.message_id,
            user_id=current_user.id,
            rating=feedback.rating,
            comment=feedback.comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    logger.bind(
        event="chat_feedback",
        module="chat",
        action="feedback",
        status="success",
        user_id=current_user.id,
        session_id=feedback.session_id,
        rating=feedback.rating,
    ).info("user feedback recorded")

    return {"status": "ok", "message": "反馈已记录"}


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(None)
):
    """
    处理websocket、endpoint相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。

    鉴权方式（按优先级）：
    1. query 参数 token（向后兼容，存在 URL 泄露风险，建议迁移）
    2. Sec-WebSocket-Protocol 子协议头 bearer.<token>（推荐，避免 URL 泄露）
    3. Cookie access_token（与 REST API 的 Cookie 鉴权一致，覆盖纯 Cookie 登录场景）

    Cookie 兜底场景：浏览器原生 WebSocket API 无法主动设置 Authorization header，
    仅支持 Sec-WebSocket-Protocol 子协议；当用户使用 Cookie 登录而非 API Key 时，
    前端拿不到 token 无法填入子协议，需通过浏览器自动携带的 Cookie 完成鉴权。
    Origin 校验已防 CSWSH，Cookie 路径安全可控。
    """
    # Origin 校验（防 CSWSH 跨站 WebSocket 劫持，参考 P0-2）
    # 必须在 accept() 前完成，避免恶意页面借助浏览器自动携带的 Cookie 建立跨站 WS
    origin = websocket.headers.get("origin", "") or ""
    if not validate_ws_origin(origin):
        await websocket.close(code=4010, reason="Origin not allowed")
        return

    # token 解析：优先取 query 参数，缺失时尝试从 Sec-WebSocket-Protocol 子协议提取
    subprotocol: Optional[str] = None
    if not token:
        token, subprotocol = extract_token_from_subprotocol(websocket)

    # Cookie 兜底：纯 Cookie 登录场景下，前端无 token 可填入子协议，
    # 此处从浏览器自动携带的 Cookie 提取 access_token 完成鉴权
    if not token:
        cookie_token = websocket.cookies.get(ACCESS_TOKEN_COOKIE_NAME, "") if websocket.cookies else ""
        if cookie_token:
            token = cookie_token

    if token is None:
        await websocket.close(code=4001, reason="Missing authentication token")
        return

    connection_request_id = str(
        websocket.headers.get(REQUEST_ID_HEADER, "") or generate_request_id()
    ).strip() or generate_request_id()
    client_version = websocket.headers.get(CLIENT_VERSION_HEADER, "")

    # 统一鉴权：支持 API Key（登录页主路径）与 JWT（用户名密码登录路径）两种 token
    # 抽取到 _ws_resolve_user_from_token，与 get_current_user 鉴权顺序保持一致
    try:
        user = await asyncio.to_thread(_ws_resolve_user_from_token, token)
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

    if user is None:
        await websocket.close(code=4002, reason="Invalid or expired token")
        return

    try:
        record_owner_id = await asyncio.to_thread(_ws_load_session_owner_id, session_id)
        if record_owner_id and record_owner_id != str(user.id):
            await websocket.close(code=4003, reason="Unauthorized session")
            return
    except Exception as e:
        logger.bind(
            event="chat_ws_session_check_error",
            module="chat",
            action="websocket",
            status="failure",
            error_type=type(e).__name__,
            error_message=sanitize_for_logging(str(e)),
        ).error("session ownership check failed")
        await websocket.close(code=4004, reason="Database error")
        return

    # --- 鉴权通过，为 Agent 创建独立会话，贯穿整个 WebSocket 生命周期 ---
    db = SessionLocal()
    ws_connected = False
    try:
        user_id = user.id
        # 解析用户名（_ws_resolve_user_from_token 返回 User ORM 或 SimpleNamespace）
        username = getattr(user, "username", None) or str(user_id)
        try:
            agent_context = build_session_agent_context(
                db,
                session_id,
                str(user_id),
                {},
            )
        except AssistantContextResourceError:
            await websocket.close(code=4003, reason="Assistant context is not available")
            return

        await ws_manager.connect(session_id, websocket, user_id=user_id, subprotocol=subprotocol)
        ws_connected = True

        logger.bind(
            event="chat_ws_connected",
            module="chat",
            action="websocket",
            status="connected",
            session_id=session_id,
            user_id=user_id,
        ).info("websocket connected")

        # WebSocket 与 HTTP 入口共享同一套向量运行时冷启动策略。
        await prewarm_agent_memory(SessionLocal)
        agent = AIAgent(
            db_session=db,
            workflow_repository=WorkflowRepositoryAdapter(db),
            memory_session_factory=SessionLocal,
        )

        await handle_websocket_session(
            websocket=websocket,
            session_id=session_id,
            user_id=user_id,
            username=username,
            client_version=client_version,
            connection_request_id=connection_request_id,
            agent=agent,
            agent_context=agent_context,
        )
    finally:
        if ws_connected:
            ws_manager.disconnect(session_id, websocket, user_id=user_id)
        # 统一在此处关闭 Agent 使用的数据库连接
        db.close()


@router.get(
    "/history/{session_id}",
    summary="获取会话历史",
    description="返回指定会话在短期记忆中保存的历史消息列表。支持 limit 分页参数，默认返回最近 200 条。"
)
async def get_chat_history(
    session_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    workspace_id: str = "default",
    limit: int = Query(200, ge=1, le=1000, description="返回消息数量上限，默认 200，最大 1000"),
    offset: int = Query(0, ge=0, description="分页偏移量，用于翻页加载更早的消息"),
) -> List[Dict[str, Any]]:
    """
    获取指定会话的聊天历史。
    验证会话属于当前用户，防止越权访问，限制工作区范围。
    """
    from db.models import ShortTermMemory, ConversationRecord

    record = db.query(ConversationRecord).filter(
        ConversationRecord.session_id == session_id,
    ).first()
    if record and record.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied: session does not belong to current user")

    # 使用 limit + offset 分页，避免一次性加载大量消息导致 OOM。
    # 先按时间倒序取最近 N 条，再反转回正序以保持返回格式兼容。
    messages = (
        db.query(ShortTermMemory)
        .filter(
            ShortTermMemory.session_id == session_id,
            ShortTermMemory.workspace_id == workspace_id,
        )
        .order_by(ShortTermMemory.timestamp.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    messages.reverse()  # 恢复正序 (timestamp ASC) 以保证前端兼容

    logger.bind(
        event="chat_history_loaded",
        module="chat",
        action="history",
        status="success",
        user_id=current_user.id,
        session_id=session_id,
        limit=limit,
        offset=offset,
        count=len(messages),
    ).info("chat history loaded")

    return [
        {
            "id": msg.id,
            "role": msg.role,
            "content": msg.content,
            "timestamp": msg.timestamp,
            "reasoning_content": msg.reasoning_content if msg.reasoning_content else None,
            "toolEvents": msg.tool_events if msg.tool_events else None,
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
UPLOAD_DIR = UPLOADS_DIR

# 上传内容签名校验表（防扩展名/MIME 伪造）
_CHAT_UPLOAD_MAGIC_BYTES: Dict[str, tuple] = {
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".webp": (b"RIFF",),  # WEBP 容器头部，进一步校验偏移 8-12 字节为 WEBP
    ".pdf": (b"%PDF-",),
}


def _validate_chat_upload_magic_bytes(data: bytes, ext: str) -> bool:
    """校验上传文件首部 magic bytes 是否与扩展名声明一致。"""
    if ext in {".txt", ".md", ".csv"}:
        # 文本格式没有固定文件签名，拒绝二进制内容并要求 UTF-8 可解码。
        if b"\x00" in data:
            return False
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return True
    expected = _CHAT_UPLOAD_MAGIC_BYTES.get(ext)
    if not expected:
        return False
    if not any(data.startswith(magic) for magic in expected):
        return False
    # WEBP 额外校验偏移 8-12
    if ext == ".webp" and len(data) >= 12 and data[8:12] != b"WEBP":
        return False
    return True


@router.post(
    "/upload",
    summary="上传聊天附件",
    description="上传图片或文档文件作为聊天消息的附件，返回访问 URL。"
)
async def upload_chat_file(
    file: UploadFile,
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
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
    if not content:
        raise HTTPException(status_code=400, detail="文件不能为空")
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail=f"文件大小超过限制（最大 {MAX_UPLOAD_SIZE // 1024 // 1024}MB）")

    # 校验文件 magic bytes，防止扩展名/MIME 伪造（防存储型 XSS 与恶意文件上传）
    if not _validate_chat_upload_magic_bytes(content, ext):
        logger.warning(f"chat 文件上传 magic bytes 校验失败: ext={ext}, filename={file.filename}")
        raise HTTPException(status_code=400, detail="文件内容与声明的类型不匹配")

    # 生成安全文件名（UUID + 原始扩展名，防止路径遍历）
    safe_filename = f"{uuid.uuid4().hex}{ext}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_path = UPLOAD_DIR / safe_filename

    try:
        # 使用 asyncio.to_thread 包装同步文件写入，避免阻塞事件循环（大文件上传场景）
        await asyncio.to_thread(_write_file_bytes_sync, file_path, content)
    except OSError as exc:
        # 不向客户端泄露内部异常细节（文件系统路径等），仅记录日志
        logger.error(f"chat 文件上传写入失败: {exc}", exc_info=exc)
        raise HTTPException(status_code=500, detail="文件保存失败，请稍后重试")

    # 判断文件类型分类
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    file_type = "image" if ext in image_exts else "file"

    metadata_path = _build_upload_metadata_path(safe_filename)
    metadata: Dict[str, Any] = {
        "owner_id": current_user.id,
        "original_name": file.filename,
        "size": len(content),
        "type": file_type,
        "content_type": file.content_type or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    # 同样用 to_thread 包装元数据写入
    await asyncio.to_thread(_write_metadata_sync, metadata_path, metadata)

    logger.bind(
        event="chat_file_uploaded",
        module="chat",
        action="upload",
        status="success",
        user_id=current_user.id,
        file_extension=ext,
        file_type=file_type,
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
) -> Dict[str, Any]:
    """
    返回已上传的文件。文件名必须是系统生成的安全文件名。
    """
    _validate_uploaded_filename(filename)

    file_path = UPLOAD_DIR / filename
    metadata_path = _build_upload_metadata_path(filename)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    if not metadata_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    try:
        # 使用 asyncio.to_thread 包装同步文件读取，避免阻塞事件循环
        metadata = await asyncio.to_thread(_read_metadata_sync, metadata_path)
    except (OSError, json.JSONDecodeError) as exc:
        logger.bind(
            event="chat_file_metadata_error",
            module="chat",
            action="download",
            status="failure",
            filename=filename,
            error_type=type(exc).__name__,
        ).warning("file metadata missing or invalid")
        raise HTTPException(status_code=404, detail="文件不存在") from exc

    owner_id = str(metadata.get("owner_id") or "").strip()
    if current_user.role != "admin" and owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问该文件")

    return FileResponse(file_path, filename=str(metadata.get("original_name") or filename))


# ---- 操作撤销 ----

from core.checkpoint_store import checkpoint_store


@router.post(
    "/undo-operation",
    summary="撤销 AI 执行的文件操作",
    description="根据操作 ID 撤销之前 AI 执行的文件写入或创建操作。"
)
async def undo_operation(
    request: Request,
    data: ChatUndoOperationRequest,
    current_user=Depends(get_current_user)
) -> Dict[str, Any]:
    """撤销操作检查点。"""
    operation_id = data.operation_id

    result = checkpoint_store.undo(operation_id)

    logger.bind(
        event="chat_undo",
        module="chat",
        action="undo",
        status="success" if result.get("ok") else "failure",
        user_id=current_user.id,
        operation_id=operation_id,
    ).info("undo operation executed")

    return result

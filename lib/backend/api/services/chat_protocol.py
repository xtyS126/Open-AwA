"""
聊天协议服务层，负责处理 SSE 流和 WebSocket 分段协议。
"""

import hashlib
import json
from typing import Dict, Any, AsyncGenerator, Tuple
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from loguru import logger

from core.metrics import record_websocket_message_metric
from core.litellm_adapter import build_standard_error
from config.logging import sanitize_for_logging
from api.services.ws_manager import ws_manager
# 以下 emit_* 函数已迁移到 core.streaming_events，此处保留 re-export 以兼容历史引用
from core.streaming_events import emit_task_event, emit_tool_event, emit_subagent_start_event, emit_subagent_stop_event, emit_agent_message_event, emit_task_created_event, emit_task_updated_event, emit_task_stopped_event, emit_team_event, emit_ask_user_event

WS_CHUNK_SIZE = 1024

def build_chunk_checksum(payload_text: str) -> str:
    """
    为完整消息生成校验值，客户端可据此校验分段重组结果。
    """
    return hashlib.sha256(payload_text.encode("utf-8")).hexdigest()

async def send_chunked_websocket_message(
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
    checksum = build_chunk_checksum(payload_text)
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

def _extract_error_from_chunk(chunk: Dict[str, Any]) -> Tuple[str, str]:
    """
    从生成器 yield 出的 chunk 中提取结构化错误信息（code + message）。

    支持以下 chunk 结构：
    - {"type": "error", "error": {"code": ..., "message": ...}}（build_standard_error 透传）
    - {"type": "error", "message": "..."}（agent_api 异常包装）
    - {"ok": False, "error": {"code": ..., "message": ...}}（executor 返回的 dict 错误）
    - {"ok": False, "error": "..."}（executor 返回的字符串错误）
    - {"ok": False, "error": {"message": ..., "type": "timeout"}}（超时等带 type 的错误）

    缺少 code 时回退为 stream_internal_error；缺少 message 时回退为通用提示。
    """
    # 优先从 error 字段提取（兼容 dict 和 string 两种形式）
    error_info = chunk.get("error")
    if isinstance(error_info, dict):
        code = error_info.get("code") or error_info.get("type") or "stream_internal_error"
        message = error_info.get("message") or "流式响应异常，请重试"
        return str(code), str(message)
    if isinstance(error_info, str) and error_info:
        return "stream_internal_error", error_info

    # 其次从 chunk 顶层提取 message（agent_api.py 的 {"type": "error", "message": "..."} 形式）
    top_message = chunk.get("message")
    if isinstance(top_message, str) and top_message:
        return "stream_internal_error", top_message

    # 兜底：没有任何可提取的错误信息
    return "stream_internal_error", "流式响应异常，请重试"


def _extract_error_from_exception(exc: Exception) -> Tuple[str, str]:
    """
    从异常对象中提取结构化错误信息（code + message）。

    支持以下异常形式：
    - 异常 args[0] 为 dict 且包含 error 字段（如 agent 抛出 {"ok": False, "error": {...}}）
    - 异常 args[0] 为 dict 且直接包含 code/message 字段
    - 异常自身携带 code/message 属性（自定义异常类）
    - 普通异常，回退为 stream_internal_error + str(exc)
    """
    # 情况 1：异常 args[0] 是 dict 形式的错误结构
    if exc.args and isinstance(exc.args[0], dict):
        err_dict = exc.args[0]
        # 形如 {"ok": False, "error": {"code": ..., "message": ...}}
        if isinstance(err_dict.get("error"), dict):
            error_info = err_dict["error"]
            code = error_info.get("code") or error_info.get("type") or "stream_internal_error"
            message = error_info.get("message") or str(exc)
            return str(code), str(message)
        # 形如 {"ok": False, "error": "..."}（error 为字符串）
        if isinstance(err_dict.get("error"), str) and err_dict["error"]:
            return "stream_internal_error", err_dict["error"]
        # 形如 {"code": ..., "message": ...}
        if err_dict.get("code") or err_dict.get("message"):
            code = err_dict.get("code") or "stream_internal_error"
            message = err_dict.get("message") or str(exc)
            return str(code), str(message)

    # 情况 2：异常自身携带 code/message 属性（自定义异常类）
    code_attr = getattr(exc, "code", None)
    message_attr = getattr(exc, "message", None)
    if code_attr or message_attr:
        code = str(code_attr) if code_attr else "stream_internal_error"
        message = str(message_attr) if message_attr else str(exc)
        return code, message

    # 情况 3：普通异常，回退为默认 code + str(exc)
    # str(exc) 为空时（如 raise Exception()）回退为通用提示，避免前端收到空 message
    message = str(exc) or "流式响应异常，请重试"
    return "stream_internal_error", message


async def build_sse_response(stream_generator: AsyncGenerator) -> StreamingResponse:
    """
    将生成器包装为 Server-Sent Events (SSE) 流响应。
    推理内容使用 event: reasoning 类型单独发送，正常内容使用默认事件类型。
    """
    async def event_generator():
        try:
            async for chunk in stream_generator:
                chunk_type = chunk.get("type")

                # 错误事件：规范化为 {"type": "error", "error": {"code": ..., "message": ...}}
                # 兼容 type=error 透传、agent_api 的 {"type": "error", "message": "..."}、
                # 以及 executor 返回的 {"ok": False, "error": {...}} 三种结构
                if chunk_type == "error" or (
                    chunk.get("ok") is False and chunk.get("error") is not None
                ):
                    error_code, error_message = _extract_error_from_chunk(chunk)
                    yield f"data: {json.dumps({'type': 'error', 'error': {'code': error_code, 'message': error_message}}, ensure_ascii=False)}\n\n"
                    continue

                # cancelled 事件直接透传，取消后不再继续发送
                if chunk_type == "cancelled":
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                    break

                # 非 chunk 事件保持原样透传，供前端消费 status/plan/task/tool/usage 等结构化事件
                if chunk_type and chunk_type != "chunk":
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                    continue

                reasoning = chunk.get("reasoning_content", "")
                content = chunk.get("content", "")

                # 先发送推理内容（如果有），使用 reasoning 事件类型
                if reasoning:
                    yield f"event: reasoning\ndata: {json.dumps({'content': reasoning}, ensure_ascii=False)}\n\n"

                # 再发送正常内容（如果有），使用默认事件类型
                if content:
                    yield f"data: {json.dumps({'type': 'chunk', 'content': content}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            # 生成器异常时向前端发送错误事件，避免前端无限等待
            # 从异常中提取底层 error code/message，不再统一显示「流式响应异常，请重试」
            # 注意：必须用 .opt(exception=True) 记录完整堆栈，否则只看消息无法定位 numpy/Qdrant 等底层错误
            logger.bind(
                event="sse_generator_error",
                module="chat_protocol",
                error_type=type(exc).__name__,
                error_message=sanitize_for_logging(str(exc)),
            ).opt(exception=True).error(f"SSE 生成器异常: {exc}")
            error_code, error_message = _extract_error_from_exception(exc)
            yield f"data: {json.dumps({'type': 'error', 'error': {'code': error_code, 'message': error_message}}, ensure_ascii=False)}\n\n"
        finally:
            # 无论正常结束还是异常，都必须发送 [DONE] 信号，否则前端会无限等待
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

async def handle_websocket_session(
    websocket: WebSocket,
    session_id: str,
    user_id: str,
    username: str,
    client_version: str,
    connection_request_id: str,
    agent: "AIAgent",
):
    """
    处理 WebSocket 会话的收发循环。
    """
    try:
        while True:
            data = await websocket.receive_text()
            ws_manager.mark_activity(websocket)
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

                # 多端同步：将用户消息广播给同会话其他设备
                await ws_manager.broadcast_to_session(
                    session_id,
                    {
                        "type": "sync",
                        "event": "user_message",
                        "session_id": session_id,
                        "content": message_data.get("content", ""),
                        "request_id": message_request_id,
                    },
                    exclude=websocket,
                    user_id=user_id,
                )

                result = await agent.process(message_data.get("content", ""), context)

                response_payload = {
                    "status": result.get("status"),
                    "content": result.get("response", ""),
                    "results": result.get("results", []),
                }
                # 如果存在推理内容，附加到 WebSocket 响应中
                if result.get("reasoning_content"):
                    response_payload["reasoning_content"] = result["reasoning_content"]
                # 透传 agent 返回的结构化错误信息（code + message），避免错误被吞没
                if result.get("error"):
                    response_payload["error"] = result["error"]

                await send_chunked_websocket_message(
                    websocket,
                    "response",
                    response_payload,
                    message_request_id,
                )

                # 多端同步：将 Agent 响应广播给同会话其他设备
                await ws_manager.broadcast_to_session(
                    session_id,
                    {
                        "type": "sync",
                        "event": "agent_response",
                        "session_id": session_id,
                        "payload": response_payload,
                        "request_id": message_request_id,
                    },
                    exclude=websocket,
                    user_id=user_id,
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

                await send_chunked_websocket_message(
                    websocket,
                    "confirmation_result",
                    {
                        "result": result,
                    },
                    message_request_id,
                )

            elif message_data.get("type") == "pong":
                # 客户端心跳响应只刷新活动时间，不进入业务处理。
                continue

    except WebSocketDisconnect:
        ws_manager.disconnect(session_id, websocket, user_id=user_id)
        logger.bind(
            event="chat_ws_disconnected",
            module="chat",
            action="websocket",
            status="disconnected",
            session_id=session_id,
            user_id=user_id,
        ).info("websocket disconnected")
    except Exception as exc:
        ws_manager.disconnect(session_id, websocket, user_id=user_id)
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
        # 从异常中提取结构化错误信息，避免统一显示「WebSocket 内部错误」
        error_code, error_message = _extract_error_from_exception(exc)
        try:
            await send_chunked_websocket_message(
                websocket,
                "error",
                {
                    "error": build_standard_error(
                        error_code,
                        error_message,
                        request_id=error_request_id,
                        details={"reason": str(exc), "session_id": session_id},
                    )
                },
                error_request_id,
            )
        finally:
            await websocket.close(code=4005, reason="Internal server error")
    finally:
        ws_manager.disconnect(session_id, websocket, user_id=user_id)

"""
聊天协议服务层，负责处理 SSE 流和 WebSocket 分段协议。
"""

import hashlib
import json
from typing import Dict, Any, AsyncGenerator
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from loguru import logger

from core.metrics import record_websocket_message_metric
from core.model_service import build_standard_error
from config.logging import sanitize_for_logging
from api.services.ws_manager import ws_manager

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

async def build_sse_response(stream_generator: AsyncGenerator) -> StreamingResponse:
    """
    将生成器包装为 Server-Sent Events (SSE) 流响应。
    推理内容使用 event: reasoning 类型单独发送，正常内容使用默认事件类型。
    """
    async def event_generator():
        async for chunk in stream_generator:
            chunk_type = chunk.get("type")

            # 错误事件直接透传
            if chunk_type == "error":
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                continue

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

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
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

                response_payload = {
                    "status": result.get("status"),
                    "content": result.get("response", ""),
                    "results": result.get("results", []),
                }
                # 如果存在推理内容，附加到 WebSocket 响应中
                if result.get("reasoning_content"):
                    response_payload["reasoning_content"] = result["reasoning_content"]

                await send_chunked_websocket_message(
                    websocket,
                    "response",
                    response_payload,
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

                await send_chunked_websocket_message(
                    websocket,
                    "confirmation_result",
                    {
                        "result": result,
                    },
                    message_request_id,
                )

    except WebSocketDisconnect:
        ws_manager.disconnect(session_id)
        logger.bind(
            event="chat_ws_disconnected",
            module="chat",
            action="websocket",
            status="disconnected",
            session_id=session_id,
            user_id=user_id,
        ).info("websocket disconnected")
    except Exception as exc:
        ws_manager.disconnect(session_id)
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
            await send_chunked_websocket_message(
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
        ws_manager.disconnect(session_id)


def emit_task_event(task_data: Dict[str, Any]) -> Dict[str, Any]:
    # chunk_type 设置为 "task"
    # type 设置为 "task"
    # task 键设置为 task_data
    return {
        "type": "task",
        "chunk_type": "task",
        "task": task_data,
    }


def emit_tool_event(tool_data: Dict[str, Any]) -> Dict[str, Any]:
    # chunk_type 设置为 "tool"
    # type 设置为 "tool"
    # tool 键设置为 tool_data
    return {
        "type": "tool",
        "chunk_type": "tool",
        "tool": tool_data,
    }

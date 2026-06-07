"""
任务执行 API 路由模块，为自动化场景提供非交互式任务提交与执行接口。
Android/Windows 桌面应用和 CI/CD 流水线通过此端点驱动 AI 自主执行任务。
"""

import asyncio
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from api.schemas import TaskExecuteRequest, TaskExecuteResponse
from db.models import User as UserModel, get_db
from config.settings import settings

router = APIRouter(prefix="/api/tasks", tags=["Tasks"])


@router.post("/execute", response_model=TaskExecuteResponse)
async def execute_task(
    request: Request,
    body: TaskExecuteRequest,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    """
    非交互式任务执行端点。

    提交一个任务给 AI Agent 自主执行，一次性返回完整结果。
    - 不发送 SSE 流式事件
    - AI 自主执行工具调用（autonomous 模式）
    - 支持超时控制和 Webhook 回调

    适用场景：
    - Android/Windows 桌面应用提交后台任务
    - CI/CD 流水线触发 AI 代码审查/修复
    - 外部系统通过 Webhook 驱动自动化工作流
    """
    start_time = time.monotonic()
    request_id = getattr(request.state, "request_id", "")

    if not body.prompt.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="prompt 不能为空",
        )

    logger.bind(
        event="task_execute_started",
        module="tasks",
        request_id=request_id,
        user_id=current_user.id,
        provider=body.provider,
        model=body.model,
        prompt_length=len(body.prompt),
    ).info("非交互式任务开始执行")

    try:
        from core.agent import AIAgent

        agent = AIAgent()

        # 使用 session_id 或自动生成
        session_id = body.session_id or f"task_{request_id}"

        # 构建 agent 上下文
        context = {
            "session_id": session_id,
            "user_id": current_user.id,
            "provider": body.provider,
            "model": body.model,
            "mode": "nonstream",
            "autonomous": True,  # 非交互模式：自主执行
            "max_tool_call_rounds": body.max_tool_call_rounds or settings.MAX_TOOL_CALL_ROUNDS,
            "thinking_enabled": body.thinking_depth is not None,
            "thinking_depth": body.thinking_depth,
            "request_id": request_id,
            "_caller": "task_execute",
        }

        # 设置超时
        timeout = body.timeout_seconds or 300
        try:
            result = await asyncio.wait_for(
                agent.process(
                    body.prompt,
                    context=context,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            logger.bind(
                event="task_execute_timeout",
                module="tasks",
                request_id=request_id,
                timeout_seconds=timeout,
                elapsed_ms=elapsed_ms,
            ).warning("任务执行超时")

            return TaskExecuteResponse(
                status="timeout",
                request_id=request_id,
                session_id=session_id,
                response=f"任务执行超时（{timeout} 秒）",
                error=f"timeout after {timeout}s",
                execution_time_ms=elapsed_ms,
            )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        status_text = "success" if not result.get("error") else "failed"
        response_text = result.get("response", "")
        reasoning = result.get("reasoning_content", "")
        tool_calls_count = result.get("tool_calls_count", 0)
        tokens_used = result.get("tokens_used", 0)

        logger.bind(
            event="task_execute_completed",
            module="tasks",
            request_id=request_id,
            status=status_text,
            elapsed_ms=elapsed_ms,
            tool_calls_count=tool_calls_count,
            tokens_used=tokens_used,
        ).info(f"非交互式任务执行完成: {status_text}")

        # Webhook 回调（如果配置了）
        if body.webhook_url:
            _fire_webhook(
                webhook_url=body.webhook_url,
                request_id=request_id,
                session_id=session_id,
                status=status_text,
                response=response_text,
                elapsed_ms=elapsed_ms,
            )

        return TaskExecuteResponse(
            status=status_text,
            request_id=request_id,
            session_id=session_id,
            response=response_text,
            reasoning_content=reasoning,
            tool_calls_count=tool_calls_count,
            execution_time_ms=elapsed_ms,
            tokens_used=tokens_used,
            error=result.get("error"),
        )

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        logger.bind(
            event="task_execute_error",
            module="tasks",
            request_id=request_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
            elapsed_ms=elapsed_ms,
        ).error("非交互式任务执行异常")
        return TaskExecuteResponse(
            status="failed",
            request_id=request_id,
            error=f"{type(exc).__name__}: {str(exc)}",
            execution_time_ms=elapsed_ms,
        )


def _fire_webhook(
    webhook_url: str,
    request_id: str,
    session_id: str,
    status: str,
    response: str,
    elapsed_ms: int,
) -> None:
    """异步触发 Webhook 回调（fire-and-forget）。"""
    import json
    import asyncio as _asyncio

    async def _post():
        try:
            from core.model_service import get_shared_client
            client = get_shared_client()
            payload = {
                "event": "task.completed",
                "request_id": request_id,
                "session_id": session_id,
                "status": status,
                "response_preview": response[:500] if response else "",
                "elapsed_ms": elapsed_ms,
            }
            await client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
        except Exception as exc:
            logger.bind(
                event="task_webhook_failed",
                module="tasks",
                webhook_url=webhook_url,
                error=str(exc),
            ).warning("Webhook 回调失败")

    try:
        _asyncio.ensure_future(_post())
    except Exception:
        pass

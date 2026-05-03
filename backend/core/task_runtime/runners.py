"""
代理运行器模块，负责前台/后台执行子代理任务，以及停止运行中的代理。
复用 scheduled_task_manager 的隔离上下文执行模式。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, Optional

from loguru import logger
from sqlalchemy.orm import Session

from config.settings import settings
from db.models import SessionLocal, TaskAgentSession

from .definitions import get_agent_definition
from .sessions import create_session, update_session_state, get_session
from .serializers import (
    save_transcript_entry,
    build_summary,
    get_transcript_path,
    emit_subagent_start_event,
    emit_subagent_stop_event,
    emit_agent_message_event,
)
from .hook_dispatcher import hook_dispatcher, HOOK_SUBAGENT_START, HOOK_SUBAGENT_STOP
from .worktree_manager import worktree_manager

# 运行中的后台任务引用，用于 TaskStop
_running_background_tasks: Dict[str, asyncio.Task] = {}


async def run_foreground(
    *,
    agent_type: str = "Explore",
    prompt: str = "",
    description: str = "",
    model: Optional[str] = None,
    parent_session_id: Optional[str] = None,
    root_chat_session_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    前台执行子代理，直接 yield SSE 事件。
    主线程通过 async for 消费这些事件并转发给前端。
    """
    agent_def = get_agent_definition(agent_type)
    if not agent_def:
        yield {"type": "error", "error": f"未知代理类型: {agent_type}"}
        return

    db: Session = SessionLocal()
    try:
        session = create_session(
            db,
            parent_session_id=parent_session_id,
            root_chat_session_id=root_chat_session_id,
            agent_type=agent_type,
            run_mode="foreground",
            isolation_mode=agent_def.isolation_mode,
        )
        agent_id = session.agent_id
    finally:
        db.close()

    # 发射启动事件
    yield emit_subagent_start_event(agent_id, agent_type, description)
    save_transcript_entry(agent_id, {
        "event": "subagent_start",
        "agent_type": agent_type,
        "prompt": prompt,
        "description": description,
    })

    # 更新状态为 running
    db = SessionLocal()
    try:
        update_session_state(db, agent_id, "running")
    finally:
        db.close()

    # SubagentStart 钩子：子代理启动时注入附加上下文
    await hook_dispatcher.dispatch(HOOK_SUBAGENT_START, {
        "agent_id": agent_id,
        "agent_type": agent_type,
        "prompt": prompt,
        "description": description,
    })

    # worktree 隔离：写操作型代理创建独立工作副本
    worktree_info = None
    if agent_def.isolation_mode == "worktree":
        worktree_info = await worktree_manager.create_worktree(agent_id)

    try:
        # 构建子代理上下文，运行独立的 AIAgent
        from core.agent import AIAgent

        sub_context = {
            "session_id": f"subagent_{agent_id}",
            "user_id": (context or {}).get("user_id", "system"),
            "username": (context or {}).get("username", "subagent"),
            "request_id": str(uuid.uuid4()),
            "enable_skill_plugin": False,  # 子代理默认不启用技能/插件
            "subagent_type": agent_type,
            "agent_id": agent_id,
        }
        if model:
            sub_context["model"] = model
        if worktree_info:
            sub_context["work_dir"] = worktree_info.path

        sub_agent = AIAgent()

        full_response = ""
        tool_results = []

        async for chunk in sub_agent.process_stream(prompt, sub_context):
            # 记录 transcript
            if chunk.get("type") in ("plan", "task", "tool", "usage"):
                save_transcript_entry(agent_id, chunk)

            # 收集工具执行结果
            if chunk.get("type") == "tool":
                tool_data = chunk.get("tool", {})
                tool_results.append(tool_data)

            # 收集文本响应
            if chunk.get("type") == "chunk" and chunk.get("content"):
                full_response += chunk["content"]

            yield chunk

        # 构建摘要
        summary = build_summary(
            {"response": full_response, "tool_results": tool_results},
            max_length=2000,
        )

        # 更新为完成状态
        db = SessionLocal()
        try:
            transcript_path = get_transcript_path(agent_id)
            update_session_state(
                db,
                agent_id,
                "completed",
                summary=summary,
                transcript_path=transcript_path,
            )
        finally:
            db.close()

        save_transcript_entry(agent_id, {
            "event": "subagent_stop",
            "state": "completed",
            "summary": summary,
        })

        # SubagentStop 钩子：子代理完成前触发
        await hook_dispatcher.dispatch(HOOK_SUBAGENT_STOP, {
            "agent_id": agent_id,
            "agent_type": agent_type,
            "state": "completed",
            "summary": summary,
        })

        # 发射完成事件 + 摘要消息
        yield emit_subagent_stop_event(agent_id, "completed", summary)
        yield emit_agent_message_event(agent_id, summary)

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {str(exc)}"
        logger.bind(
            module="task_runtime",
            agent_id=agent_id,
            error=error_msg,
        ).error(f"子代理执行失败: {agent_id}")

        db = SessionLocal()
        try:
            update_session_state(db, agent_id, "failed", last_error=error_msg)
        finally:
            db.close()

        save_transcript_entry(agent_id, {
            "event": "subagent_stop",
            "state": "failed",
            "error": error_msg,
        })

        # SubagentStop 钩子：子代理失败时也触发
        await hook_dispatcher.dispatch(HOOK_SUBAGENT_STOP, {
            "agent_id": agent_id,
            "agent_type": agent_type,
            "state": "failed",
            "error": error_msg,
        })

        yield emit_subagent_stop_event(agent_id, "failed", error_msg)
        yield {"type": "error", "error": f"子代理执行失败: {error_msg}"}

    finally:
        # 清理 worktree（若有）
        if worktree_info:
            await worktree_manager.cleanup_worktree(agent_id)


async def run_background(
    *,
    agent_type: str = "Explore",
    prompt: str = "",
    description: str = "",
    model: Optional[str] = None,
    parent_session_id: Optional[str] = None,
    root_chat_session_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    后台执行子代理，立即返回 agent_id，异步运行。
    完成后通过 SSE 事件通知前端。
    """
    agent_def = get_agent_definition(agent_type)
    if not agent_def:
        return {"ok": False, "error": f"未知代理类型: {agent_type}"}

    db: Session = SessionLocal()
    try:
        session = create_session(
            db,
            parent_session_id=parent_session_id,
            root_chat_session_id=root_chat_session_id,
            agent_type=agent_type,
            run_mode="background",
            isolation_mode=agent_def.isolation_mode,
        )
        agent_id = session.agent_id
    finally:
        db.close()

    save_transcript_entry(agent_id, {
        "event": "subagent_start",
        "agent_type": agent_type,
        "prompt": prompt,
        "description": description,
        "run_mode": "background",
    })

    # 创建后台任务
    task = asyncio.create_task(
        _background_execute(
            agent_id=agent_id,
            agent_type=agent_type,
            prompt=prompt,
            description=description,
            model=model,
            context=context,
        )
    )
    _running_background_tasks[agent_id] = task

    return {
        "ok": True,
        "agent_id": agent_id,
        "status": "queued",
        "run_mode": "background",
    }


async def _heartbeat_loop(agent_id: str, lease_owner: str, interval_seconds: int = 60) -> None:
    """周期性续租后台代理的 lease，防止长时间运行超时。"""
    from .sessions import claim_session
    while True:
        await asyncio.sleep(interval_seconds)
        db = SessionLocal()
        try:
            session = claim_session(db, agent_id, lease_owner, lease_duration_seconds=300)
            if not session:
                logger.bind(
                    module="task_runtime",
                    agent_id=agent_id,
                ).warning(f"心跳续租失败，代理可能已被回收: {agent_id}")
                return
        except Exception as exc:
            logger.bind(
                module="task_runtime",
                agent_id=agent_id,
                error=str(exc),
            ).warning(f"心跳续租异常: {agent_id}")
        finally:
            db.close()


async def _background_execute(
    agent_id: str,
    agent_type: str,
    prompt: str,
    description: str,
    model: Optional[str],
    context: Optional[Dict[str, Any]],
) -> None:
    """后台执行子代理的实际逻辑。"""
    db = SessionLocal()
    try:
        update_session_state(db, agent_id, "running")
    finally:
        db.close()

    # SubagentStart 钩子
    await hook_dispatcher.dispatch(HOOK_SUBAGENT_START, {
        "agent_id": agent_id,
        "agent_type": agent_type,
        "prompt": prompt,
        "description": description,
    })

    # 启动心跳续租
    lease_owner = f"bg_{agent_id}"
    heartbeat_task = asyncio.create_task(_heartbeat_loop(agent_id, lease_owner, interval_seconds=60))

    try:
        from core.agent import AIAgent

        sub_context = {
            "session_id": f"subagent_{agent_id}",
            "user_id": (context or {}).get("user_id", "system"),
            "username": (context or {}).get("username", "subagent"),
            "request_id": str(uuid.uuid4()),
            "enable_skill_plugin": False,
            "subagent_type": agent_type,
            "agent_id": agent_id,
        }
        if model:
            sub_context["model"] = model

        sub_agent = AIAgent()
        result = await sub_agent.process(prompt, sub_context)

        summary = build_summary(result, max_length=2000)

        db = SessionLocal()
        try:
            transcript_path = get_transcript_path(agent_id)
            update_session_state(
                db,
                agent_id,
                "completed",
                summary=summary,
                transcript_path=transcript_path,
            )
        finally:
            db.close()

        save_transcript_entry(agent_id, {
            "event": "subagent_stop",
            "state": "completed",
            "summary": summary,
        })

        logger.bind(
            module="task_runtime",
            agent_id=agent_id,
            agent_type=agent_type,
        ).info(f"后台代理执行完成: {agent_id}")

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {str(exc)}"
        logger.bind(
            module="task_runtime",
            agent_id=agent_id,
            error=error_msg,
        ).error(f"后台代理执行失败: {agent_id}")

        db = SessionLocal()
        try:
            update_session_state(db, agent_id, "failed", last_error=error_msg)
        finally:
            db.close()

        save_transcript_entry(agent_id, {
            "event": "subagent_stop",
            "state": "failed",
            "error": error_msg,
        })
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        _running_background_tasks.pop(agent_id, None)


async def stop_run(agent_id: str) -> Dict[str, Any]:
    """停止运行中的后台代理。"""
    session = get_session(agent_id)
    if not session:
        return {"ok": False, "error": f"代理不存在: {agent_id}"}

    if session.state not in ("running", "queued", "waiting_user"):
        return {"ok": False, "error": f"代理 {agent_id} 当前状态为 {session.state}，无法停止"}

    # 尝试取消后台任务
    bg_task = _running_background_tasks.get(agent_id)
    if bg_task and not bg_task.done():
        bg_task.cancel()
        logger.bind(module="task_runtime", agent_id=agent_id).info(f"后台代理任务已取消: {agent_id}")

    db = SessionLocal()
    try:
        update_session_state(db, agent_id, "stopped", last_error="被用户手动停止")
    finally:
        db.close()

    save_transcript_entry(agent_id, {
        "event": "subagent_stop",
        "state": "stopped",
        "reason": "user_stopped",
    })

    return {"ok": True, "agent_id": agent_id, "status": "stopped"}

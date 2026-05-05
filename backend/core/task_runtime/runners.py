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


def _get_configured_model_catalog(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """从上下文中提取已配置模型目录。"""
    base_context = context or {}
    catalog = base_context.get("configured_model_catalog")
    if isinstance(catalog, dict):
        return catalog

    capabilities = base_context.get("agent_capabilities")
    if isinstance(capabilities, dict):
        nested_catalog = capabilities.get("configured_models")
        if isinstance(nested_catalog, dict):
            return nested_catalog

    return {}


def _find_provider_for_model(model: Optional[str], catalog: Dict[str, Any]) -> Optional[str]:
    """在模型目录中查找模型所属 provider。"""
    normalized_model = str(model or "").strip()
    if not normalized_model:
        return None

    matches: list[str] = []
    entries = catalog.get("entries") if isinstance(catalog.get("entries"), list) else []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("model", "")).strip() != normalized_model:
            continue
        provider = str(entry.get("provider", "")).strip().lower()
        if provider and provider not in matches:
            matches.append(provider)

    if len(matches) == 1:
        return matches[0]
    return None


def _pick_model_for_provider(provider: Optional[str], catalog: Dict[str, Any]) -> Optional[str]:
    """从模型目录中挑选 provider 的首个可用模型。"""
    normalized_provider = str(provider or "").strip().lower()
    if not normalized_provider:
        return None

    providers = catalog.get("providers") if isinstance(catalog.get("providers"), list) else []
    for item in providers:
        if not isinstance(item, dict):
            continue
        if str(item.get("provider", "")).strip().lower() != normalized_provider:
            continue
        models = item.get("models") if isinstance(item.get("models"), list) else []
        for model in models:
            normalized_model = str(model or "").strip()
            if normalized_model:
                return normalized_model

    return None


def _resolve_subagent_provider_and_model(
    provider: Optional[str],
    model: Optional[str],
    context: Optional[Dict[str, Any]],
) -> tuple[Optional[str], Optional[str]]:
    """为 runners 层补齐 provider/model 回退。"""
    normalized_provider = str(provider or "").strip().lower() or None
    normalized_model = str(model or "").strip() or None
    base_context = context or {}
    catalog = _get_configured_model_catalog(base_context)

    if not normalized_provider:
        context_provider = str(base_context.get("provider", "") or "").strip().lower()
        if context_provider:
            normalized_provider = context_provider

    if not normalized_model:
        context_model = str(base_context.get("model", "") or "").strip()
        if context_model:
            normalized_model = context_model

    if not normalized_provider and normalized_model:
        normalized_provider = _find_provider_for_model(normalized_model, catalog)

    if normalized_provider and not normalized_model:
        normalized_model = _pick_model_for_provider(normalized_provider, catalog)

    return normalized_provider, normalized_model


def _create_subagent_execution_bundle(
    agent_id: str,
    agent_type: str,
    provider: Optional[str],
    model: Optional[str],
    context: Optional[Dict[str, Any]],
    work_dir: Optional[str] = None,
) -> tuple[Any, Session, Dict[str, Any]]:
    """为子代理创建独立数据库会话、执行上下文与 Agent 实例。"""
    from core.agent import AIAgent

    resolved_provider, resolved_model = _resolve_subagent_provider_and_model(provider, model, context)
    subagent_db = SessionLocal()
    sub_context = {
        "session_id": f"subagent_{agent_id}",
        "user_id": (context or {}).get("user_id", "system"),
        "username": (context or {}).get("username", "subagent"),
        "request_id": str(uuid.uuid4()),
        "enable_skill_plugin": False,
        "subagent_type": agent_type,
        "agent_id": agent_id,
        "db": subagent_db,
    }

    configured_model_catalog = _get_configured_model_catalog(context)
    if configured_model_catalog:
        sub_context["configured_model_catalog"] = configured_model_catalog
    if resolved_provider:
        sub_context["provider"] = resolved_provider
    if resolved_model:
        sub_context["model"] = resolved_model
    if work_dir:
        sub_context["work_dir"] = work_dir

    try:
        sub_agent = AIAgent(db_session=subagent_db)
    except Exception:
        subagent_db.close()
        raise

    return sub_agent, subagent_db, sub_context


def _format_subagent_stream_chunk(chunk: Dict[str, Any]) -> Optional[str]:
    """将子代理内部流式 chunk 归一化为日志文本。"""
    chunk_type = str(chunk.get("type") or "").strip()

    if chunk_type == "chunk":
        reasoning = str(chunk.get("reasoning_content") or "").strip()
        content = str(chunk.get("content") or "").strip()
        if reasoning and content:
            return f"[思考] {reasoning}\n{content}"
        if reasoning:
            return f"[思考] {reasoning}"
        return content or None

    if chunk_type == "status":
        message = str(chunk.get("message") or "").strip()
        if message:
            return f"[状态] {message}"
        phase = str(chunk.get("phase") or "").strip()
        return f"[状态] {phase}" if phase else None

    if chunk_type == "plan":
        plan = chunk.get("plan")
        if isinstance(plan, dict):
            steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
            if steps:
                return f"[计划] 已生成 {len(steps)} 个步骤"
        return "[计划] 已生成执行计划"

    if chunk_type == "task":
        task = chunk.get("task")
        if isinstance(task, dict):
            summary = str(task.get("summary") or task.get("purpose") or task.get("action") or "").strip()
            status = str(task.get("status") or "").strip()
            if summary and status:
                return f"[任务] {summary} ({status})"
            if summary:
                return f"[任务] {summary}"
            if status:
                return f"[任务] {status}"
        return None

    if chunk_type == "tool":
        tool = chunk.get("tool")
        if isinstance(tool, dict):
            name = str(tool.get("name") or "").strip()
            detail = str(tool.get("detail") or tool.get("status") or "").strip()
            if name and detail:
                return f"[工具] {name}: {detail}"
            if name:
                return f"[工具] {name}"
            if detail:
                return f"[工具] {detail}"
        return None

    if chunk_type == "error":
        error_text = str(chunk.get("error") or "").strip()
        return f"[错误] {error_text}" if error_text else "[错误] 子代理执行失败"

    return None


async def run_foreground(
    *,
    agent_type: str = "Explore",
    prompt: str = "",
    description: str = "",
    provider: Optional[str] = None,
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

    db = SessionLocal()
    try:
        update_session_state(db, agent_id, "queued")
    finally:
        db.close()

    # 发射启动事件
    yield emit_subagent_start_event(agent_id, agent_type, description, run_mode="foreground")
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
    subagent_db: Optional[Session] = None
    if agent_def.isolation_mode == "worktree":
        worktree_info = await worktree_manager.create_worktree(agent_id)

    try:
        # 构建子代理上下文，运行独立的 AIAgent
        sub_agent, subagent_db, sub_context = _create_subagent_execution_bundle(
            agent_id=agent_id,
            agent_type=agent_type,
            provider=provider,
            model=model,
            context=context,
            work_dir=worktree_info.path if worktree_info else None,
        )

        full_response = ""
        tool_results = []

        async for chunk in sub_agent.process_stream(prompt, sub_context):
            # 记录 transcript
            if chunk.get("type") in ("plan", "task", "tool", "usage", "status"):
                save_transcript_entry(agent_id, chunk)

            # 收集工具执行结果
            if chunk.get("type") == "tool":
                tool_data = chunk.get("tool", {})
                tool_results.append(tool_data)

            # 收集文本响应
            if chunk.get("type") == "chunk" and chunk.get("content"):
                full_response += chunk["content"]

            message = _format_subagent_stream_chunk(chunk)
            if message:
                save_transcript_entry(agent_id, {
                    "event": "agent_message",
                    "message": message,
                })
                yield emit_agent_message_event(agent_id, message, agent_type=agent_type)

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
        yield emit_subagent_stop_event(agent_id, "completed", summary, agent_type=agent_type, run_mode="foreground")

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

        yield emit_subagent_stop_event(agent_id, "failed", error_msg, agent_type=agent_type, run_mode="foreground")
        yield {"type": "error", "error": f"子代理执行失败: {error_msg}"}

    finally:
        # 清理 worktree（若有）
        if worktree_info:
            await worktree_manager.cleanup_worktree(agent_id)
        if subagent_db is not None:
            subagent_db.close()


async def run_background(
    *,
    agent_type: str = "Explore",
    prompt: str = "",
    description: str = "",
    provider: Optional[str] = None,
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

    db = SessionLocal()
    try:
        update_session_state(db, agent_id, "queued")
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
            provider=provider,
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
    provider: Optional[str],
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
    subagent_db: Optional[Session] = None

    try:
        sub_agent, subagent_db, sub_context = _create_subagent_execution_bundle(
            agent_id=agent_id,
            agent_type=agent_type,
            provider=provider,
            model=model,
            context=context,
        )
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
        if subagent_db is not None:
            subagent_db.close()
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

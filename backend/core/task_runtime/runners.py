"""
代理运行器模块，负责前台/后台执行子代理任务，以及停止运行中的代理。
复用 scheduled_task_manager 的隔离上下文执行模式。
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from db.models import SessionLocal

from .definitions import AgentDefinition, get_agent_definition
from .sessions import create_session, update_session_state, get_session, claim_session
from .serializers import (
    save_transcript_entry,
    build_summary,
    get_transcript_path,
)
# emit_* 事件构造函数已统一到 core.streaming_events，避免与 serializers.py 重复定义
from core.streaming_events import (
    emit_subagent_start_event,
    emit_subagent_stop_event,
    emit_agent_message_event,
)
from core.hook_manager import hook_manager, HookName
from .worktree_manager import worktree_manager
from .agent_memory import load_agent_memory_prompt
from .permission_guard import permission_guard
from .fork import (
    build_forked_messages,
    build_child_message,
    is_in_fork_child,
    FORK_PLACEHOLDER_RESULT,
)

# 运行中的后台任务引用，用于 TaskStop
# 已从模块级字典迁移到 AgentLifecycle._running_background_tasks，
# 通过 _get_running_tasks() 辅助函数访问，支持测试隔离


def _get_running_tasks() -> Dict[str, asyncio.Task]:
    """从 AgentLifecycle 获取运行中的后台任务字典（支持测试隔离）"""
    from core.agent_lifecycle import get_agent_lifecycle
    return get_agent_lifecycle()._running_background_tasks

# 子代理流式消息达到该阈值后再刷出，避免按 token 级别污染思维链。
SUBAGENT_STREAM_MESSAGE_FLUSH_THRESHOLD = 96


async def _create_session_record(
    *,
    parent_session_id: Optional[str],
    root_chat_session_id: Optional[str],
    agent_type: str,
    run_mode: str,
    isolation_mode: str,
) -> str:
    """在线程中创建短生命周期数据库会话，避免阻塞事件循环。"""
    def _create() -> str:
        db = SessionLocal()
        try:
            return create_session(
                db,
                parent_session_id=parent_session_id,
                root_chat_session_id=root_chat_session_id,
                agent_type=agent_type,
                run_mode=run_mode,
                isolation_mode=isolation_mode,
            ).agent_id
        finally:
            db.close()

    return await asyncio.to_thread(_create)


async def _update_session_record(
    agent_id: str,
    state: str,
    **kwargs: Any,
) -> None:
    """在线程中更新短生命周期数据库会话状态，并在操作后关闭会话。"""
    def _update() -> None:
        db = SessionLocal()
        try:
            update_session_state(db, agent_id, state, **kwargs)
        finally:
            db.close()

    await asyncio.to_thread(_update)


async def _renew_session_lease(agent_id: str, lease_owner: str) -> bool:
    """在线程中续租会话，避免心跳循环因同步数据库操作阻塞。"""
    def _renew() -> bool:
        db = SessionLocal()
        try:
            return claim_session(db, agent_id, lease_owner, lease_duration_seconds=300) is not None
        finally:
            db.close()

    return await asyncio.to_thread(_renew)


class MaxTurnsExceededError(Exception):
    """代理执行达到最大轮次限制时抛出的异常。"""

    def __init__(self, agent_id: str, max_turns: int) -> None:
        self.agent_id = agent_id
        self.max_turns = max_turns
        super().__init__(f"Agent {agent_id} 达到最大轮次限制 {max_turns}")


# 努力程度到 LLM 参数的映射配置
_EFFORT_CONFIG_TABLE: Dict[str, Dict[str, Any]] = {
    "low": {"temperature": 0.2, "thinking_budget": 1024},
    "medium": {"temperature": 0.5, "thinking_budget": 4096},
    "high": {"temperature": 0.7, "thinking_budget": 16384},
}


def _get_effort_config(effort: str) -> Dict[str, Any]:
    """根据努力程度返回对应的 LLM 调用参数（temperature + thinking_budget）。

    参数:
        effort: 努力程度，取值为 "low" / "medium" / "high"

    返回:
        包含 temperature 和 thinking_budget 的配置字典；
        未知值回退到 medium 配置，保证调用方始终拿到完整字段。
    """
    return dict(_EFFORT_CONFIG_TABLE.get(effort, _EFFORT_CONFIG_TABLE["medium"]))


def _load_project_context(work_dir: Optional[str] = None) -> str:
    """加载项目上下文文件内容，包括 AGENTS.md、PROJECT_DOCUMENTATION.md 和 docs/ 目录。

    参数:
        work_dir: 工作目录路径；为 None 时使用当前工作目录。

    返回:
        拼接后的项目上下文文本；无可用文件时返回空字符串。
    """
    base_dir = Path(work_dir) if work_dir else Path.cwd()
    context_parts: list[str] = []

    # AGENTS.md
    agents_md = base_dir / "AGENTS.md"
    if agents_md.exists():
        try:
            content = agents_md.read_text(encoding="utf-8")
            if content.strip():
                context_parts.append(f"[AGENTS.md]\n{content}")
        except OSError as exc:
            logger.bind(module="task_runtime").debug(f"读取 AGENTS.md 失败: {exc}")

    # PROJECT_DOCUMENTATION.md（已迁移至 docs/ 目录）
    project_doc = base_dir / "docs" / "PROJECT_DOCUMENTATION.md"
    if project_doc.exists():
        try:
            content = project_doc.read_text(encoding="utf-8")
            if content.strip():
                context_parts.append(f"[PROJECT_DOCUMENTATION.md]\n{content}")
        except OSError as exc:
            logger.bind(module="task_runtime").debug(f"读取 PROJECT_DOCUMENTATION.md 失败: {exc}")

    # docs/ 目录下的 Markdown 文档
    docs_dir = base_dir / "docs"
    if docs_dir.exists() and docs_dir.is_dir():
        try:
            for doc_file in sorted(docs_dir.rglob("*.md")):
                try:
                    content = doc_file.read_text(encoding="utf-8")
                    if content.strip():
                        rel_path = doc_file.relative_to(base_dir)
                        context_parts.append(f"[{rel_path}]\n{content}")
                except OSError:
                    continue
        except OSError as exc:
            logger.bind(module="task_runtime").debug(f"遍历 docs 目录失败: {exc}")

    return "\n\n".join(context_parts)


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


def _resolve_agent_allowed_tools(
    agent_def: Optional[AgentDefinition],
    permission_mode: str,
) -> Optional[List[str]]:
    """按 AgentDefinition 声明的 tools / disallowed_tools 计算子代理可用工具白名单。

    组合规则（Task 17，安全语义真实生效）：
    - tools 声明非空：以声明为准（白名单），再剔除 disallowed_tools
    - tools 声明为空：无白名单限制（返回 None，表示不限制）
    - plan / dont_ask 权限模式：与 PermissionGuard 只读白名单求交集，
      保证只读 Agent 的写工具永不进入白名单

    返回 None 表示不限制；返回列表（可能为空）表示仅允许列表内工具。
    """
    declared = list(agent_def.tools or []) if agent_def else []
    disallowed = set(agent_def.disallowed_tools or []) if agent_def else set()

    if declared:
        allowed = [t for t in declared if t not in disallowed]
    else:
        allowed = None

    # plan / dont_ask 模式下只保留只读工具
    if permission_mode in ("plan", "dont_ask"):
        readonly = set(permission_guard.get_allowed_tools(permission_mode) or [])
        if allowed is None:
            allowed = sorted(readonly)
        else:
            allowed = [t for t in allowed if t in readonly]

    return allowed


async def _create_subagent_execution_bundle(
    agent_id: str,
    agent_type: str,
    provider: Optional[str],
    model: Optional[str],
    context: Optional[Dict[str, Any]],
    work_dir: Optional[str] = None,
    agent_def: Optional[AgentDefinition] = None,
) -> tuple[Any, Session, Dict[str, Any]]:
    """为子代理创建独立数据库会话、执行上下文与 Agent 实例。

    参数:
        agent_def: 代理定义，用于读取 max_turns / effort / omit_project_context 等扩展字段；
                   为 None 时按默认值处理，保持向后兼容。
    """
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

    # Task 11.4: 注入 effort 联动的 LLM 参数（temperature + thinking_budget）
    effort_value = getattr(agent_def, "effort", "medium") if agent_def else "medium"
    effort_config = _get_effort_config(effort_value)
    sub_context["effort"] = effort_value
    sub_context["effort_config"] = effort_config
    # temperature 透传给底层 LLM 调用（若上层未显式指定则覆盖）
    sub_context.setdefault("temperature", effort_config["temperature"])
    # thinking_budget 透传给思考模式参数构建逻辑
    sub_context.setdefault("thinking_budget", effort_config["thinking_budget"])

    # Task 11.2: max_turns 透传到上下文，控制内部工具调用回环上限
    max_turns_value = getattr(agent_def, "max_turns", None) if agent_def else None
    if max_turns_value is not None:
        sub_context["max_tool_call_rounds"] = max_turns_value

    # Task 11.3: omit_project_context 控制是否注入项目上下文文件
    omit_project_context = bool(getattr(agent_def, "omit_project_context", False) if agent_def else False)
    if not omit_project_context:
        project_context_text = _load_project_context(work_dir)
        if project_context_text:
            sub_context["project_context"] = project_context_text
    else:
        logger.bind(
            module="task_runtime",
            agent_id=agent_id,
            agent_type=agent_type,
        ).debug(f"已省略项目上下文注入: {agent_id}")

    # Task 15: 注入代理记忆 prompt，根据 memory_scope 从对应存储加载。
    # 存储键使用 agent_type（而非随机 agent_id），保证同类型代理跨会话共享记忆
    memory_scope = getattr(agent_def, "memory_scope", None) if agent_def else None
    if memory_scope is not None:
        memory_prompt = await load_agent_memory_prompt(agent_type, memory_scope)
        if memory_prompt:
            sub_context["agent_memory"] = memory_prompt
            logger.bind(
                module="task_runtime",
                agent_id=agent_id,
                agent_type=agent_type,
                memory_scope=memory_scope.value,
            ).debug(f"已注入代理记忆: {agent_id}")

    # Task 17: 应用 AgentDefinition 声明的权限模式与工具约束。
    # permission_mode 注入后，execution_tool_runtime._check_tool_permission 会经
    # PermissionGuard.evaluate 真正拦截 plan 模式子代理的写工具调用（此前仅 facade 打日志丢弃）；
    # allowed_tools 白名单由执行层消费（tools / disallowed_tools 声明真实生效）。
    permission_mode = getattr(agent_def, "permission_mode", "default") if agent_def else "default"
    if permission_mode and permission_mode != "default":
        sub_context["permission_mode"] = permission_mode
    resolved_allowed_tools = _resolve_agent_allowed_tools(agent_def, permission_mode or "default")
    if resolved_allowed_tools is not None:
        sub_context["allowed_tools"] = resolved_allowed_tools

    try:
        sub_agent = AIAgent(
            db_session=subagent_db,
            memory_session_factory=SessionLocal,
        )
    except Exception:
        subagent_db.close()
        raise

    return sub_agent, subagent_db, sub_context


def _get_subagent_chunk_text(chunk: Optional[Dict[str, Any]], field: str) -> str:
    """安全读取子代理 chunk 中的文本字段。"""
    if not chunk:
        return ""
    value = chunk.get(field)
    if value is None:
        return ""
    return str(value)


def _merge_subagent_stream_chunk(
    buffer_chunk: Optional[Dict[str, Any]],
    chunk: Dict[str, Any],
) -> Dict[str, Any]:
    """合并连续的文本 chunk，降低 agent_message 事件粒度。"""
    merged_chunk = dict(buffer_chunk or {"type": "chunk", "content": "", "reasoning_content": ""})
    merged_chunk["type"] = "chunk"
    merged_chunk["reasoning_content"] = (
        _get_subagent_chunk_text(merged_chunk, "reasoning_content")
        + _get_subagent_chunk_text(chunk, "reasoning_content")
    )
    merged_chunk["content"] = _get_subagent_chunk_text(merged_chunk, "content") + _get_subagent_chunk_text(chunk, "content")
    return merged_chunk


def _get_subagent_stream_chunk_size(buffer_chunk: Optional[Dict[str, Any]]) -> int:
    """统计当前缓冲区内的文本长度。"""
    if not buffer_chunk:
        return 0
    return len(_get_subagent_chunk_text(buffer_chunk, "reasoning_content")) + len(_get_subagent_chunk_text(buffer_chunk, "content"))


def _flush_subagent_stream_chunk(
    buffer_chunk: Optional[Dict[str, Any]],
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """将缓冲中的文本 chunk 一次性转换为日志消息。"""
    if not buffer_chunk:
        return None, None
    return None, _format_subagent_stream_chunk(buffer_chunk)


def _format_subagent_stream_chunk(chunk: Dict[str, Any]) -> Optional[str]:
    """将子代理内部流式 chunk 归一化为日志文本。"""
    chunk_type = str(chunk.get("type") or "").strip()

    if chunk_type == "chunk":
        reasoning = _get_subagent_chunk_text(chunk, "reasoning_content")
        content = _get_subagent_chunk_text(chunk, "content")
        has_reasoning = bool(reasoning.strip())
        has_content = bool(content.strip())
        if has_reasoning and has_content:
            return f"[思考] {reasoning}\n{content}"
        if has_reasoning:
            return f"[思考] {reasoning}"
        return content if has_content else None

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


async def _execute_subagent_core(
    *,
    agent_id: str,
    agent_type: str,
    prompt: str,
    provider: Optional[str],
    model: Optional[str],
    context: Optional[Dict[str, Any]],
    agent_def: Optional[AgentDefinition],
    work_dir: Optional[str] = None,
    run_mode: str = "subagent",
) -> AsyncGenerator[Dict[str, Any], None]:
    """子 Agent 执行核心逻辑。

    统一 run_foreground 和 _background_execute 的公共流程：
    创建子 Agent 执行上下文 -> process_stream 迭代 -> 保存 transcript ->
    处理 MaxTurnsExceeded -> 构建摘要 -> 触发 SubagentStop 钩子 ->
    通过 async generator yield 返回事件。

    参数:
        agent_id: 代理会话 ID
        agent_type: 代理类型
        prompt: 用户提示词
        provider: 模型提供商
        model: 模型名称
        context: 执行上下文
        agent_def: 代理定义
        work_dir: 工作目录（worktree 隔离模式时传入）
        run_mode: 运行模式标识（"foreground" / "background" / "subagent"）
    """
    subagent_db: Optional[Session] = None

    try:
        sub_agent, subagent_db, sub_context = await _create_subagent_execution_bundle(
            agent_id=agent_id,
            agent_type=agent_type,
            provider=provider,
            model=model,
            context=context,
            work_dir=work_dir,
            agent_def=agent_def,
        )

        full_response = ""
        tool_results: list[Dict[str, Any]] = []
        buffered_stream_chunk: Optional[Dict[str, Any]] = None
        # Task 11.2: 轮次计数器，用于强制 max_turns 限制
        current_turn = 0
        max_turns_limit: Optional[int] = agent_def.max_turns if agent_def else None

        yielded_messages: list[Dict[str, Any]] = []

        async def flush_buffered_agent_message() -> None:
            nonlocal buffered_stream_chunk
            buffered_stream_chunk, buffered_message = _flush_subagent_stream_chunk(buffered_stream_chunk)
            if buffered_message:
                save_transcript_entry(agent_id, {
                    "event": "agent_message",
                    "message": buffered_message,
                })
                yield_event = emit_agent_message_event(agent_id, buffered_message, agent_type=agent_type)
                yielded_messages.append(yield_event)

        async for chunk in sub_agent.process_stream(prompt, sub_context):
            chunk_type = str(chunk.get("type") or "").strip()

            if chunk_type != "chunk":
                await flush_buffered_agent_message()
                while yielded_messages:
                    yield yielded_messages.pop(0)

            # 记录 transcript
            if chunk_type in ("plan", "task", "tool", "usage", "status"):
                save_transcript_entry(agent_id, chunk)

            # 收集工具执行结果
            if chunk_type == "tool":
                tool_data = chunk.get("tool", {})
                tool_results.append(tool_data)
                # Task 11.2: 每次工具调用记为一次轮次，达到上限时抛出异常
                current_turn += 1
                if max_turns_limit is not None and current_turn >= max_turns_limit:
                    logger.bind(
                        module="task_runtime",
                        agent_id=agent_id,
                        agent_type=agent_type,
                        current_turn=current_turn,
                        max_turns=max_turns_limit,
                    ).warning(f"Agent {agent_id} 达到最大轮次限制 {max_turns_limit}")
                    raise MaxTurnsExceededError(agent_id, max_turns_limit)

            # 收集文本响应
            if chunk_type == "chunk" and chunk.get("content"):
                full_response += chunk["content"]

            if chunk_type == "chunk":
                buffered_stream_chunk = _merge_subagent_stream_chunk(buffered_stream_chunk, chunk)
                if _get_subagent_stream_chunk_size(buffered_stream_chunk) >= SUBAGENT_STREAM_MESSAGE_FLUSH_THRESHOLD:
                    await flush_buffered_agent_message()
                    while yielded_messages:
                        yield yielded_messages.pop(0)
                continue

            message = _format_subagent_stream_chunk(chunk)
            if message:
                save_transcript_entry(agent_id, {
                    "event": "agent_message",
                    "message": message,
                })
                yield emit_agent_message_event(agent_id, message, agent_type=agent_type)

        await flush_buffered_agent_message()
        while yielded_messages:
            yield yielded_messages.pop(0)

        # 构建摘要
        summary = build_summary(
            {"response": full_response, "tool_results": tool_results},
            max_length=2000,
        )

        # 更新为完成状态
        await _update_session_record(
            agent_id,
            "completed",
            summary=summary,
            transcript_path=get_transcript_path(agent_id),
        )

        save_transcript_entry(agent_id, {
            "event": "subagent_stop",
            "state": "completed",
            "summary": summary,
        })

        # SubagentStop 钩子：子代理完成前触发
        await hook_manager.trigger(HookName.SUBAGENT_STOP, data={
            "agent_id": agent_id,
            "agent_type": agent_type,
            "state": "completed",
            "summary": summary,
        })

        # 发射完成事件 + 摘要消息
        yield emit_subagent_stop_event(agent_id, "completed", summary, agent_type=agent_type, run_mode=run_mode)

    except MaxTurnsExceededError as exc:
        # Task 11.2: 达到最大轮次限制，记录为 completed 状态（属于预期内的优雅终止）
        max_turns_summary = f"代理达到最大轮次限制 {exc.max_turns}，已停止执行。已收集响应: {full_response[:200]}"
        logger.bind(
            module="task_runtime",
            agent_id=agent_id,
            agent_type=agent_type,
            max_turns=exc.max_turns,
        ).warning(f"Agent {agent_id} 达到最大轮次限制 {exc.max_turns}")

        await _update_session_record(
            agent_id,
            "completed",
            summary=max_turns_summary,
            transcript_path=get_transcript_path(agent_id),
            last_error=f"MaxTurnsExceeded: {exc.max_turns}",
        )

        save_transcript_entry(agent_id, {
            "event": "subagent_stop",
            "state": "completed",
            "reason": "max_turns_exceeded",
            "max_turns": exc.max_turns,
            "summary": max_turns_summary,
        })

        # SubagentStop 钩子
        await hook_manager.trigger(HookName.SUBAGENT_STOP, data={
            "agent_id": agent_id,
            "agent_type": agent_type,
            "state": "completed",
            "reason": "max_turns_exceeded",
            "summary": max_turns_summary,
        })

        yield emit_subagent_stop_event(agent_id, "completed", max_turns_summary, agent_type=agent_type, run_mode=run_mode)

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {str(exc)}"
        logger.bind(
            module="task_runtime",
            agent_id=agent_id,
            error=error_msg,
        ).error(f"子代理执行失败: {agent_id}")

        await _update_session_record(agent_id, "failed", last_error=error_msg)

        save_transcript_entry(agent_id, {
            "event": "subagent_stop",
            "state": "failed",
            "error": error_msg,
        })

        # SubagentStop 钩子：子代理失败时也触发
        await hook_manager.trigger(HookName.SUBAGENT_STOP, data={
            "agent_id": agent_id,
            "agent_type": agent_type,
            "state": "failed",
            "error": error_msg,
        })

        yield emit_subagent_stop_event(agent_id, "failed", error_msg, agent_type=agent_type, run_mode=run_mode)
        yield {"type": "error", "error": f"子代理执行失败: {error_msg}"}

    finally:
        if subagent_db is not None:
            subagent_db.close()


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
    fork_mode: bool = False,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    前台执行子代理，直接 yield SSE 事件。
    主线程通过 async for 消费这些事件并转发给前端。

    参数:
        fork_mode: 是否以 Fork 模式启动子 Agent。Fork 模式下子 Agent 继承
                   父 Agent 的完整消息上下文，启动后立即返回 task_id，
                   不阻塞主 Agent；子 Agent 完成后通过 task-notification
                   异步推送结果。
    """
    agent_def = get_agent_definition(agent_type)
    if not agent_def:
        yield {"type": "error", "error": f"未知代理类型: {agent_type}"}
        return

    agent_id = await _create_session_record(
        parent_session_id=parent_session_id,
        root_chat_session_id=root_chat_session_id,
        agent_type=agent_type,
        run_mode="foreground",
        isolation_mode=agent_def.isolation_mode,
    )
    await _update_session_record(agent_id, "queued")

    # Task 13: Fork 模式 - 克隆父上下文并异步启动子 Agent，不阻塞主 Agent
    if fork_mode:
        # 防递归检测：Fork 子 Agent 不允许再次 Fork
        if is_in_fork_child(context or {}):
            yield {"type": "error", "error": "Fork 子 Agent 不允许再次启动 Fork 子 Agent"}
            return

        # 克隆父 Agent 的消息上下文
        parent_context = context or {}
        forked_messages = build_forked_messages(parent_context)

        # 构造子任务消息（包含防递归指令）
        child_message = build_child_message(prompt)

        # 合并克隆的消息与子任务消息
        forked_messages.append(child_message)

        # 设置 is_fork_child 标志，传递给子 Agent 上下文
        fork_context = dict(parent_context)
        fork_context["messages"] = forked_messages
        fork_context["is_fork_child"] = True

        # 发射启动事件
        yield emit_subagent_start_event(agent_id, agent_type, description, run_mode="foreground")
        save_transcript_entry(agent_id, {
            "event": "subagent_start",
            "agent_type": agent_type,
            "prompt": prompt,
            "description": description,
            "fork_mode": True,
        })

        # 更新状态为 running
        await _update_session_record(agent_id, "running")

        # 异步启动子 Agent 执行，不阻塞当前协程
        # 子 Agent 完成后通过 _background_execute 内的 task-notification 机制推送结果
        task = asyncio.create_task(
            _background_execute(
                agent_id=agent_id,
                agent_type=agent_type,
                prompt=prompt,
                description=description,
                provider=provider,
                model=model,
                context=fork_context,
                root_chat_session_id=root_chat_session_id,
                agent_def=agent_def,
            )
        )
        _get_running_tasks()[agent_id] = task

        logger.bind(
            module="task_runtime",
            agent_id=agent_id,
            agent_type=agent_type,
            fork_mode=True,
        ).info(f"Fork 子 Agent 已启动: task_id={agent_id}")

        # 立即返回 task_id 与占位符结果，主 Agent 不阻塞
        yield {
            "type": "fork_started",
            "agent_id": agent_id,
            "task_id": agent_id,
            "agent_type": agent_type,
            "result": FORK_PLACEHOLDER_RESULT,
            "run_mode": "foreground",
            "fork_mode": True,
        }
        return

    # 发射启动事件
    yield emit_subagent_start_event(agent_id, agent_type, description, run_mode="foreground")
    save_transcript_entry(agent_id, {
        "event": "subagent_start",
        "agent_type": agent_type,
        "prompt": prompt,
        "description": description,
    })

    # 更新状态为 running
    await _update_session_record(agent_id, "running")

    # SubagentStart 钩子：子代理启动时注入附加上下文
    await hook_manager.trigger(HookName.SUBAGENT_START, data={
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
        async for event in _execute_subagent_core(
            agent_id=agent_id,
            agent_type=agent_type,
            prompt=prompt,
            provider=provider,
            model=model,
            context=context,
            agent_def=agent_def,
            work_dir=worktree_info.path if worktree_info else None,
            run_mode="foreground",
        ):
            yield event
    finally:
        # 清理 worktree（若有）
        if worktree_info:
            await worktree_manager.cleanup_worktree(agent_id)


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

    agent_id = await _create_session_record(
        parent_session_id=parent_session_id,
        root_chat_session_id=root_chat_session_id,
        agent_type=agent_type,
        run_mode="background",
        isolation_mode=agent_def.isolation_mode,
    )
    await _update_session_record(agent_id, "queued")

    save_transcript_entry(agent_id, {
        "event": "subagent_start",
        "agent_type": agent_type,
        "prompt": prompt,
        "description": description,
        "run_mode": "background",
    })

    # 创建后台任务，传入父会话 ID 以便后续推送事件
    task = asyncio.create_task(
        _background_execute(
            agent_id=agent_id,
            agent_type=agent_type,
            prompt=prompt,
            description=description,
            provider=provider,
            model=model,
            context=context,
            root_chat_session_id=root_chat_session_id,
            agent_def=agent_def,
        )
    )
    _get_running_tasks()[agent_id] = task

    return {
        "ok": True,
        "agent_id": agent_id,
        "status": "queued",
        "run_mode": "background",
    }


async def _heartbeat_loop(agent_id: str, lease_owner: str, interval_seconds: int = 60) -> None:
    """周期性续租后台代理的 lease，防止长时间运行超时。"""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            if not await _renew_session_lease(agent_id, lease_owner):
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


async def _push_event_to_parent_session(
    root_chat_session_id: Optional[str],
    event: Dict[str, Any],
    agent_id: str,
) -> None:
    """将事件推送至父会话的 WebSocket 连接（如存在）。推送失败时静默忽略。"""
    if not root_chat_session_id:
        return
    try:
        from api.services.ws_manager import ws_manager
        import json
        ws = ws_manager.get_connection(root_chat_session_id)
        if ws:
            await ws.send_text(json.dumps(event, ensure_ascii=False, default=str))
    except Exception as exc:
        logger.bind(
            module="task_runtime",
            agent_id=agent_id,
            error=str(exc),
        ).debug("推送事件到父会话失败（已忽略）")


async def _background_execute(
    agent_id: str,
    agent_type: str,
    prompt: str,
    description: str,
    provider: Optional[str],
    model: Optional[str],
    context: Optional[Dict[str, Any]],
    root_chat_session_id: Optional[str] = None,
    agent_def: Optional[AgentDefinition] = None,
) -> None:
    """后台执行子代理的实际逻辑，委托给 _execute_subagent_core，通过 WebSocket 推送事件给父会话。"""
    await _update_session_record(agent_id, "running")

    # SubagentStart 钩子
    await hook_manager.trigger(HookName.SUBAGENT_START, data={
        "agent_id": agent_id,
        "agent_type": agent_type,
        "prompt": prompt,
        "description": description,
    })

    # 启动心跳续租
    lease_owner = f"bg_{agent_id}"
    heartbeat_task = asyncio.create_task(_heartbeat_loop(agent_id, lease_owner, interval_seconds=60))

    try:
        async for event in _execute_subagent_core(
            agent_id=agent_id,
            agent_type=agent_type,
            prompt=prompt,
            provider=provider,
            model=model,
            context=context,
            agent_def=agent_def,
            run_mode="background",
        ):
            await _push_event_to_parent_session(root_chat_session_id, event, agent_id)

        logger.bind(
            module="task_runtime",
            agent_id=agent_id,
            agent_type=agent_type,
        ).info(f"后台代理执行完成: {agent_id}")

    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        _running_background_tasks.pop(agent_id, None)


async def stop_run(agent_id: str) -> Dict[str, Any]:
    """停止运行中的后台代理。"""
    session = await asyncio.to_thread(get_session, agent_id)
    if not session:
        return {"ok": False, "error": f"代理不存在: {agent_id}"}

    if session.state not in ("running", "queued", "waiting_user"):
        return {"ok": False, "error": f"代理 {agent_id} 当前状态为 {session.state}，无法停止"}

    # 尝试取消后台任务
    bg_task = _get_running_tasks().get(agent_id)
    if bg_task and not bg_task.done():
        bg_task.cancel()
        logger.bind(module="task_runtime", agent_id=agent_id).info(f"后台代理任务已取消: {agent_id}")

    await _update_session_record(agent_id, "stopped", last_error="被用户手动停止")

    save_transcript_entry(agent_id, {
        "event": "subagent_stop",
        "state": "stopped",
        "reason": "user_stopped",
    })

    return {"ok": True, "agent_id": agent_id, "status": "stopped"}

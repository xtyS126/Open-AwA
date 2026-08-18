"""
Task Runtime 外观层，对主 Agent 暴露统一的子代理操作入口。
所有方法设计为可在 executor._execute_tool_call 中直接调用。
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator, Dict, List, Optional

from loguru import logger

from .definitions import list_agent_types, get_agent_definition
from .registry import agent_registry
from .sessions import get_session, list_sessions, recover_orphaned_sessions, claim_session, release_session
from .runners import run_foreground, run_background, stop_run
from .serializers import read_transcript
from .message_bus import send_message, send_teammate_msg, check_mailbox, read_message
from .task_store import create_task, get_task, list_tasks, update_task, claim_task, sync_todo_snapshot
from core.hook_manager import hook_manager, HookName
from .permission_guard import permission_guard
from .team_manager import (
    create_team as _create_team,
    delete_team as _delete_team,
    add_teammate as _add_teammate,
    remove_teammate as _remove_teammate,
    list_teams as _list_teams,
    get_team as _get_team,
    get_mailbox,
    mark_message_read,
    update_teammate_state,
)


class TaskRuntimeFacade:
    """
    任务运行时统一入口，封装子代理派生、消息通信、任务清单与停止控制。
    实例化时自动回收超时 lease 的悬挂会话。
    """

    def __init__(self):
        self._initialized = False

    async def initialize(self) -> None:
        """初始化：加载 DB 代理定义、回收悬挂会话。"""
        if self._initialized:
            return

        def load_agent_definitions() -> int:
            from db.models import SessionLocal

            db = SessionLocal()
            try:
                return agent_registry.load_from_db(db)
            finally:
                db.close()

        defined_count = await asyncio.to_thread(load_agent_definitions)
        if defined_count:
            logger.bind(module="task_runtime").info(f"数据库代理定义已加载: {defined_count} 个")

        count = await asyncio.to_thread(recover_orphaned_sessions)
        if count:
            logger.bind(module="task_runtime").info(f"回收悬挂会话: {count} 个")
        self._initialized = True

    async def shutdown(self) -> None:
        """停机前完成度校验，触发 Stop 钩子。"""
        from datetime import datetime, timezone
        await hook_manager.trigger(HookName.STOP, data={
            "reason": "shutdown",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        logger.bind(module="task_runtime").info("任务运行时已停机")

    # ── Agent 能力 ──────────────────────────────────────────────

    async def spawn_agent(
        self,
        *,
        agent_type: str = "Explore",
        prompt: str = "",
        description: str = "",
        provider: Optional[str] = None,
        model: Optional[str] = None,
        background: bool = False,
        fork_mode: bool = False,
        force_foreground: bool = False,
        isolation: Optional[str] = None,
        parent_session_id: Optional[str] = None,
        root_chat_session_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        """
        派生子代理。
        前台模式返回 AsyncGenerator（SSE 事件流），后台模式返回 Dict（含 agent_id）。

        fork_mode 为 True 时以 Fork 模式启动子代理：克隆父 Agent 消息上下文，
        启动后立即返回 fork_started 事件并异步执行，不阻塞主 Agent。
        Fork 模式优先于 background（fork 分支内部已异步启动）。

        force_foreground 为 True 时忽略代理定义的 background_default，
        强制以前台模式执行并返回事件流；供编排层（如 subagents 委派）同步取回结果。

        isolation 为 None 时使用代理定义的 isolation_mode；否则覆写该值，
        供编排层将任务级隔离级别映射为隔离模式（如 "worktree"）。
        """
        agent_def = agent_registry.get(agent_type)
        if not agent_def:
            return {"ok": False, "error": f"未知代理类型: {agent_type}，可用类型: {agent_registry.list_types()}"}

        # PermissionGuard：校验代理类型的权限模式，并把过滤结果真正透传到执行上下文。
        # 此前仅打日志丢弃；现在 permission_mode 会经 execution_tool_runtime._check_tool_permission
        # 触发 PermissionGuard.evaluate 在子代理执行时真正拦截越权工具（如 plan 模式的写工具），
        # allowed_tools 白名单再由 _create_subagent_execution_bundle 按 AgentDefinition 精确计算。
        effective_context = dict(context or {})
        if agent_def.permission_mode in ("plan", "dont_ask"):
            allowed_tools = permission_guard.get_allowed_tools(agent_def.permission_mode)
            if allowed_tools:
                effective_context["allowed_tools"] = allowed_tools
                effective_context["permission_mode"] = agent_def.permission_mode
                logger.bind(
                    module="task_runtime",
                    agent_type=agent_type,
                    permission_mode=agent_def.permission_mode,
                ).debug(f"代理权限模式: {agent_def.permission_mode}，限制工具: {allowed_tools}")

        # background 参数优先；若未显式指定，使用代理定义的 background_default。
        # Fork 模式优先：fork 分支内部已异步启动（create_task），无需再走 run_background
        # force_foreground：编排层需要同步取回执行结果时强制前台模式，忽略 background_default
        use_background = (
            (background or agent_def.background_default)
            and not fork_mode
            and not force_foreground
        )
        if use_background:
            return await run_background(
                agent_type=agent_type,
                prompt=prompt,
                description=description,
                provider=provider,
                model=model,
                parent_session_id=parent_session_id,
                root_chat_session_id=root_chat_session_id,
                context=effective_context,
                isolation_mode=isolation,
            )
        else:
            return run_foreground(
                agent_type=agent_type,
                prompt=prompt,
                description=description,
                provider=provider,
                model=model,
                parent_session_id=parent_session_id,
                root_chat_session_id=root_chat_session_id,
                context=effective_context,
                fork_mode=fork_mode,
                isolation_mode=isolation,
            )

    # ── SendMessage 能力 ─────────────────────────────────────────

    async def send_message(self, to: str, message: str) -> Dict[str, Any]:
        """向代理发送消息（恢复/继续）。"""
        return await asyncio.to_thread(send_message, to, message)

    # ── TaskStop 能力 ────────────────────────────────────────────

    async def stop_agent(self, agent_id: str) -> Dict[str, Any]:
        """停止运行中的代理。"""
        return await stop_run(agent_id)

    # ── 查询能力 ─────────────────────────────────────────────────

    async def list_agents(
        self,
        *,
        parent_session_id: Optional[str] = None,
        state: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """列出代理会话。"""
        sessions = await asyncio.to_thread(
            list_sessions, parent_session_id=parent_session_id, state=state
        )
        return [
            {
                "agent_id": s.agent_id,
                "agent_type": s.agent_type,
                "state": s.state,
                "run_mode": s.run_mode,
                "summary": s.summary,
                "last_error": s.last_error,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "ended_at": s.ended_at.isoformat() if s.ended_at else None,
            }
            for s in sessions
        ]

    async def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """获取单个代理详情。"""
        s = await asyncio.to_thread(get_session, agent_id)
        if not s:
            return None
        return {
            "agent_id": s.agent_id,
            "agent_type": s.agent_type,
            "parent_session_id": s.parent_session_id,
            "root_chat_session_id": s.root_chat_session_id,
            "state": s.state,
            "run_mode": s.run_mode,
            "isolation_mode": s.isolation_mode,
            "transcript_path": s.transcript_path,
            "summary": s.summary,
            "last_error": s.last_error,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        }

    async def get_transcript(self, agent_id: str) -> list:
        """获取代理的 transcript 记录。"""
        return await asyncio.to_thread(read_transcript, agent_id)

    async def list_agent_types(self) -> List[Dict[str, Any]]:
        """列出可用代理类型。"""
        return [
            {
                "name": name,
                "description": agent_registry.get(name).description if agent_registry.get(name) else "",
            }
            for name in agent_registry.list_types()
        ]

    async def save_agent_definition(self, definition: Dict[str, Any]) -> Dict[str, Any]:
        """持久化保存用户自定义代理定义。"""
        from db.models import SessionLocal
        from .definitions import AgentDefinition

        agent_def = AgentDefinition(
            name=definition.get("name", ""),
            scope=definition.get("scope", "user"),
            description=definition.get("description", ""),
            system_prompt=definition.get("system_prompt", ""),
            tools=definition.get("tools", []),
            disallowed_tools=definition.get("disallowed_tools", []),
            model=definition.get("model"),
            permission_mode=definition.get("permission_mode", "default"),
            memory_mode=definition.get("memory_mode", "none"),
            background_default=definition.get("background_default", False),
            isolation_mode=definition.get("isolation_mode", "inherit"),
            color=definition.get("color", ""),
            metadata=definition.get("metadata", {}),
        )

        def save_definition() -> bool:
            db = SessionLocal()
            try:
                return agent_registry.save_to_db(db, agent_def)
            finally:
                db.close()

        ok = await asyncio.to_thread(save_definition)
        return {"ok": ok, "name": agent_def.name}

    async def delete_agent_definition(self, name: str) -> Dict[str, Any]:
        """删除用户自定义代理定义。"""
        from db.models import SessionLocal
        def delete_definition() -> bool:
            db = SessionLocal()
            try:
                return agent_registry.delete_from_db(db, name)
            finally:
                db.close()

        ok = await asyncio.to_thread(delete_definition)
        return {"ok": ok, "name": name}

    # ── 任务清单能力（Phase 1 基础 CRUD）────────────────────────

    async def create_task_item(
        self,
        *,
        list_id: Optional[str] = None,
        subject: str = "",
        description: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
        owner_agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建任务清单项。"""
        from db.models import SessionLocal
        def create_task_record() -> Dict[str, Any]:
            db = SessionLocal()
            try:
                task = create_task(
                    db,
                    list_id=list_id,
                    subject=subject,
                    description=description,
                    dependencies=dependencies,
                    owner_agent_id=owner_agent_id,
                )
                return {
                    "ok": True,
                    "task_id": task.task_id,
                    "subject": task.subject,
                    "status": task.status,
                }
            finally:
                db.close()

        result = await asyncio.to_thread(create_task_record)
        # TaskCreated 钩子：任务创建时校验命名/描述/依赖合法性
        await hook_manager.trigger(HookName.TASK_CREATED, data={
            "task_id": result["task_id"],
            "subject": subject,
            "description": description,
            "list_id": list_id,
            "dependencies": dependencies or [],
        })
        return result

    async def get_task_item(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务项。"""
        t = await asyncio.to_thread(get_task, task_id)
        if not t:
            return None
        return {
            "task_id": t.task_id,
            "list_id": t.list_id,
            "subject": t.subject,
            "description": t.description,
            "status": t.status,
            "dependencies": t.dependencies_json,
            "owner_agent_id": t.owner_agent_id,
            "result_summary": t.result_summary,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        }

    async def list_task_items(
        self,
        *,
        list_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """列出任务项。"""
        tasks = await asyncio.to_thread(list_tasks, list_id=list_id, status=status)
        return [
            {
                "task_id": t.task_id,
                "list_id": t.list_id,
                "subject": t.subject,
                "status": t.status,
                "owner_agent_id": t.owner_agent_id,
            }
            for t in tasks
        ]

    async def update_task_item(
        self,
        task_id: str,
        *,
        status: Optional[str] = None,
        subject: Optional[str] = None,
        owner_agent_id: Optional[str] = None,
        result_summary: Optional[str] = None,
    ) -> Dict[str, Any]:
        """更新任务项。"""
        from db.models import SessionLocal
        def update_task_record() -> Dict[str, Any]:
            db = SessionLocal()
            try:
                task = update_task(
                    db,
                    task_id,
                    status=status,
                    subject=subject,
                    owner_agent_id=owner_agent_id,
                    result_summary=result_summary,
                )
                if not task:
                    return {"ok": False, "error": f"任务不存在: {task_id}"}
                return {"ok": True, "task_id": task.task_id, "status": task.status}
            finally:
                db.close()

        return await asyncio.to_thread(update_task_record)

    # ── 任务领取能力 ─────────────────────────────────────────────

    async def claim_task_item(self, task_id: str, agent_id: str) -> Dict[str, Any]:
        """事务性领取一个待执行任务。"""
        from db.models import SessionLocal

        def claim_task_record() -> Dict[str, Any]:
            db = SessionLocal()
            try:
                task = claim_task(db, task_id, agent_id)
                if not task:
                    return {"ok": False, "error": f"任务 {task_id} 无法领取（可能已被领取或依赖未满足）"}
                return {
                    "ok": True,
                    "task_id": task.task_id,
                    "status": task.status,
                    "owner_agent_id": task.owner_agent_id,
                }
            finally:
                db.close()

        return await asyncio.to_thread(claim_task_record)

    async def sync_todo_snapshot(
        self,
        *,
        list_id: Optional[str] = None,
        todos: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """同步 todo 快照（非交互模式简化入口）。"""
        from db.models import SessionLocal

        def sync_snapshot() -> Dict[str, Any]:
            db = SessionLocal()
            try:
                return sync_todo_snapshot(db, list_id=list_id, todos=todos)
            finally:
                db.close()

        return await asyncio.to_thread(sync_snapshot)

    # ── 会话租约能力 ─────────────────────────────────────────────

    async def claim_session_lease(
        self,
        agent_id: str,
        lease_owner: str,
        lease_duration_seconds: int = 300,
    ) -> Dict[str, Any]:
        """领取代理会话租约。"""
        from db.models import SessionLocal

        def claim_lease() -> Dict[str, Any]:
            db = SessionLocal()
            try:
                session = claim_session(db, agent_id, lease_owner, lease_duration_seconds)
                if not session:
                    return {"ok": False, "error": f"无法领取租约: {agent_id}"}
                return {"ok": True, "agent_id": agent_id, "lease_owner": lease_owner}
            finally:
                db.close()

        return await asyncio.to_thread(claim_lease)

    async def release_session_lease(self, agent_id: str, lease_owner: str) -> Dict[str, Any]:
        """释放代理会话租约。"""
        from db.models import SessionLocal

        def release_lease() -> Dict[str, Any]:
            db = SessionLocal()
            try:
                success = release_session(db, agent_id, lease_owner)
                return {"ok": success, "agent_id": agent_id}
            finally:
                db.close()

        return await asyncio.to_thread(release_lease)

    # ── 钩子注册能力 ─────────────────────────────────────────────

    def register_hook(self, plugin_id: str, event_type: str, handler) -> None:
        """注册生命周期钩子处理函数，供插件调用。"""
        hook_manager.register(plugin_id, event_type, handler)

    # ── 团队管理能力（Phase 4）──────────────────────────────────

    async def create_team(
        self,
        *,
        lead_agent_id: str,
        name: str = "",
        teammate_agent_ids: Optional[List[Dict[str, str]]] = None,
        task_list_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建代理团队，lead 作为团队负责人。"""
        return await asyncio.to_thread(
            _create_team,
            lead_agent_id=lead_agent_id,
            name=name,
            teammate_agent_ids=teammate_agent_ids,
            task_list_id=task_list_id,
        )

    async def delete_team(self, team_id: str) -> Dict[str, Any]:
        """删除团队并清理成员与消息。"""
        return await asyncio.to_thread(_delete_team, team_id)

    async def add_teammate(self, team_id: str, agent_id: str, name: str = "") -> Dict[str, Any]:
        """向团队添加成员。"""
        return await asyncio.to_thread(_add_teammate, team_id, agent_id, name)

    async def remove_teammate(self, team_id: str, agent_id: str) -> Dict[str, Any]:
        """从团队移除成员。"""
        return await asyncio.to_thread(_remove_teammate, team_id, agent_id)

    async def send_teammate_message(
        self,
        from_agent_id: str,
        to_agent_id: str,
        message: str,
        team_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """向队友发送消息。"""
        return await asyncio.to_thread(
            send_teammate_msg, from_agent_id, to_agent_id, message, team_id
        )

    async def list_teams(self, state: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出团队列表。"""
        return await asyncio.to_thread(_list_teams, state=state)

    async def get_team(self, team_id: str) -> Optional[Dict[str, Any]]:
        """获取单个团队详情。"""
        return await asyncio.to_thread(_get_team, team_id)

    async def get_mailbox(self, agent_id: str, unread_only: bool = False) -> List[Dict[str, Any]]:
        """获取代理的邮箱消息。"""
        return await asyncio.to_thread(get_mailbox, agent_id, unread_only=unread_only)

    async def read_message(self, message_id: str) -> Dict[str, Any]:
        """标记消息为已读。"""
        return await asyncio.to_thread(mark_message_read, message_id)

    async def update_teammate_state(self, team_id: str, agent_id: str, new_state: str) -> Dict[str, Any]:
        """更新团队成员状态。"""
        return await asyncio.to_thread(update_teammate_state, team_id, agent_id, new_state)


# 模块级单例
task_runtime = TaskRuntimeFacade()


# 保持向后兼容的模块级别名
# 新代码应使用 get_agent_lifecycle().get_task_runtime()
def _get_task_runtime():
    """从 AgentLifecycle 获取 TaskRuntime（支持测试隔离）"""
    from core.agent_lifecycle import get_agent_lifecycle
    return get_agent_lifecycle().get_task_runtime()

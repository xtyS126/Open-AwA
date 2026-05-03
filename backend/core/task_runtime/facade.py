"""
Task Runtime 外观层，对主 Agent 暴露统一的子代理操作入口。
所有方法设计为可在 executor._execute_tool_call 中直接调用。
"""

from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List, Optional

from loguru import logger

from .definitions import list_agent_types, get_agent_definition
from .registry import agent_registry
from .sessions import get_session, list_sessions, recover_orphaned_sessions, claim_session, release_session
from .runners import run_foreground, run_background, stop_run
from .serializers import read_transcript
from .message_bus import send_message, send_teammate_msg, check_mailbox, read_message
from .task_store import create_task, get_task, list_tasks, update_task, claim_task, sync_todo_snapshot
from .hook_dispatcher import hook_dispatcher, HookEventType, HOOK_TASK_CREATED, HOOK_STOP
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

        from db.models import SessionLocal
        db = SessionLocal()
        try:
            defined_count = agent_registry.load_from_db(db)
            if defined_count:
                logger.bind(module="task_runtime").info(f"数据库代理定义已加载: {defined_count} 个")
        finally:
            db.close()

        count = recover_orphaned_sessions()
        if count:
            logger.bind(module="task_runtime").info(f"回收悬挂会话: {count} 个")
        self._initialized = True

    async def shutdown(self) -> None:
        """停机前完成度校验，触发 Stop 钩子。"""
        from datetime import datetime, timezone
        await hook_dispatcher.dispatch(HOOK_STOP, {
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
        model: Optional[str] = None,
        background: bool = False,
        isolation: str = "inherit",
        parent_session_id: Optional[str] = None,
        root_chat_session_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        """
        派生子代理。
        前台模式返回 AsyncGenerator（SSE 事件流），后台模式返回 Dict（含 agent_id）。
        """
        agent_def = agent_registry.get(agent_type)
        if not agent_def:
            return {"ok": False, "error": f"未知代理类型: {agent_type}，可用类型: {agent_registry.list_types()}"}

        # PermissionGuard：校验代理类型的权限模式
        if agent_def.permission_mode in ("plan",):
            allowed_tools = permission_guard.get_allowed_tools(agent_def.permission_mode)
            if allowed_tools:
                logger.bind(
                    module="task_runtime",
                    agent_type=agent_type,
                    permission_mode=agent_def.permission_mode,
                ).debug(f"代理权限模式: {agent_def.permission_mode}，限制工具: {allowed_tools}")

        # background 参数优先；若未显式指定，使用代理定义的 background_default
        use_background = background or agent_def.background_default
        if use_background:
            return await run_background(
                agent_type=agent_type,
                prompt=prompt,
                description=description,
                model=model,
                parent_session_id=parent_session_id,
                root_chat_session_id=root_chat_session_id,
                context=context,
            )
        else:
            return run_foreground(
                agent_type=agent_type,
                prompt=prompt,
                description=description,
                model=model,
                parent_session_id=parent_session_id,
                root_chat_session_id=root_chat_session_id,
                context=context,
            )

    # ── SendMessage 能力 ─────────────────────────────────────────

    async def send_message(self, to: str, message: str) -> Dict[str, Any]:
        """向代理发送消息（恢复/继续）。"""
        return send_message(to, message)

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
        sessions = list_sessions(parent_session_id=parent_session_id, state=state)
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
        s = get_session(agent_id)
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
        return read_transcript(agent_id)

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

        db = SessionLocal()
        try:
            ok = agent_registry.save_to_db(db, agent_def)
            return {"ok": ok, "name": agent_def.name}
        finally:
            db.close()

    async def delete_agent_definition(self, name: str) -> Dict[str, Any]:
        """删除用户自定义代理定义。"""
        from db.models import SessionLocal
        db = SessionLocal()
        try:
            ok = agent_registry.delete_from_db(db, name)
            return {"ok": ok, "name": name}
        finally:
            db.close()

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

            # TaskCreated 钩子：任务创建时校验命名/描述/依赖合法性
            await hook_dispatcher.dispatch(HOOK_TASK_CREATED, {
                "task_id": task.task_id,
                "subject": subject,
                "description": description,
                "list_id": list_id,
                "dependencies": dependencies or [],
            })

            return {
                "ok": True,
                "task_id": task.task_id,
                "subject": task.subject,
                "status": task.status,
            }
        finally:
            db.close()

    async def get_task_item(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务项。"""
        t = get_task(task_id)
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
        tasks = list_tasks(list_id=list_id, status=status)
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
        db = SessionLocal()
        try:
            t = update_task(
                db,
                task_id,
                status=status,
                subject=subject,
                owner_agent_id=owner_agent_id,
                result_summary=result_summary,
            )
            if not t:
                return {"ok": False, "error": f"任务不存在: {task_id}"}
            return {"ok": True, "task_id": t.task_id, "status": t.status}
        finally:
            db.close()

    # ── 任务领取能力 ─────────────────────────────────────────────

    async def claim_task_item(self, task_id: str, agent_id: str) -> Dict[str, Any]:
        """事务性领取一个待执行任务。"""
        from db.models import SessionLocal
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

    async def sync_todo_snapshot(
        self,
        *,
        list_id: Optional[str] = None,
        todos: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """同步 todo 快照（非交互模式简化入口）。"""
        from db.models import SessionLocal
        db = SessionLocal()
        try:
            result = sync_todo_snapshot(db, list_id=list_id, todos=todos)
            return result
        finally:
            db.close()

    # ── 会话租约能力 ─────────────────────────────────────────────

    async def claim_session_lease(
        self,
        agent_id: str,
        lease_owner: str,
        lease_duration_seconds: int = 300,
    ) -> Dict[str, Any]:
        """领取代理会话租约。"""
        from db.models import SessionLocal
        db = SessionLocal()
        try:
            session = claim_session(db, agent_id, lease_owner, lease_duration_seconds)
            if not session:
                return {"ok": False, "error": f"无法领取租约: {agent_id}"}
            return {"ok": True, "agent_id": agent_id, "lease_owner": lease_owner}
        finally:
            db.close()

    async def release_session_lease(self, agent_id: str, lease_owner: str) -> Dict[str, Any]:
        """释放代理会话租约。"""
        from db.models import SessionLocal
        db = SessionLocal()
        try:
            success = release_session(db, agent_id, lease_owner)
            return {"ok": success, "agent_id": agent_id}
        finally:
            db.close()

    # ── 钩子注册能力 ─────────────────────────────────────────────

    def register_hook(self, event_type: HookEventType, handler) -> None:
        """注册生命周期钩子处理函数，供插件调用。"""
        hook_dispatcher.register(event_type, handler)

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
        return _create_team(
            lead_agent_id=lead_agent_id,
            name=name,
            teammate_agent_ids=teammate_agent_ids,
            task_list_id=task_list_id,
        )

    async def delete_team(self, team_id: str) -> Dict[str, Any]:
        """删除团队并清理成员与消息。"""
        return _delete_team(team_id)

    async def add_teammate(self, team_id: str, agent_id: str, name: str = "") -> Dict[str, Any]:
        """向团队添加成员。"""
        return _add_teammate(team_id, agent_id, name)

    async def remove_teammate(self, team_id: str, agent_id: str) -> Dict[str, Any]:
        """从团队移除成员。"""
        return _remove_teammate(team_id, agent_id)

    async def send_teammate_message(
        self,
        from_agent_id: str,
        to_agent_id: str,
        message: str,
        team_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """向队友发送消息。"""
        return send_teammate_msg(from_agent_id, to_agent_id, message, team_id)

    async def list_teams(self, state: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出团队列表。"""
        return _list_teams(state=state)

    async def get_team(self, team_id: str) -> Optional[Dict[str, Any]]:
        """获取单个团队详情。"""
        return _get_team(team_id)

    async def get_mailbox(self, agent_id: str, unread_only: bool = False) -> List[Dict[str, Any]]:
        """获取代理的邮箱消息。"""
        return get_mailbox(agent_id, unread_only=unread_only)

    async def read_message(self, message_id: str) -> Dict[str, Any]:
        """标记消息为已读。"""
        return mark_message_read(message_id)

    async def update_teammate_state(self, team_id: str, agent_id: str, new_state: str) -> Dict[str, Any]:
        """更新团队成员状态。"""
        return update_teammate_state(team_id, agent_id, new_state)


# 模块级单例
task_runtime = TaskRuntimeFacade()

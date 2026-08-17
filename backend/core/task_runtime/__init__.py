"""
任务委派运行时模块，提供子代理派生、会话管理、任务清单与消息总线能力。
参考 Claude Code Agent/TaskCreate/SendMessage 语义设计。
"""

from .facade import TaskRuntimeFacade, task_runtime
from .registry import AgentDefinitionRegistry, agent_registry
from .permission_guard import PermissionGuard, PermissionDecision, permission_guard
from .worktree_manager import WorktreeManager, WorktreeInfo, worktree_manager
from .team_manager import (
    create_team,
    delete_team,
    add_teammate,
    remove_teammate,
    list_teams,
    get_team,
    send_teammate_message,
    get_mailbox,
    mark_message_read,
    update_teammate_state,
    validate_team_transition,
)

__all__ = [
    "TaskRuntimeFacade",
    "task_runtime",
    "AgentDefinitionRegistry",
    "agent_registry",
    "PermissionGuard",
    "PermissionDecision",
    "permission_guard",
    "WorktreeManager",
    "WorktreeInfo",
    "worktree_manager",
    "create_team",
    "delete_team",
    "add_teammate",
    "remove_teammate",
    "list_teams",
    "get_team",
    "send_teammate_message",
    "get_mailbox",
    "mark_message_read",
    "update_teammate_state",
    "validate_team_transition",
]

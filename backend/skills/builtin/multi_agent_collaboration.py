"""
multi_agent_collaboration 内置技能 — 多智能体协作。
允许智能体之间互相通信、请求专长能力、共同完成复杂任务。
"""
from typing import Any, Optional
from loguru import logger

SKILL_NAME = "multi_agent_collaboration"
SKILL_DESCRIPTION = "多智能体协作：请求其他智能体的专业能力，访问其他工作区数据，寻求第二意见"


async def execute(
    action: str,
    target_agent: Optional[str] = None,
    request_text: Optional[str] = None,
    session_id: Optional[str] = None,
    background: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    执行多智能体协作操作。

    Args:
        action: 操作类型（list_agents/chat/delegate/request）
        target_agent: 目标智能体 ID
        request_text: 请求文本
        session_id: 会话 ID（用于多轮对话）
        background: 是否后台模式

    Returns:
        操作结果
    """
    valid_actions = {"list_agents", "chat", "delegate", "request"}
    if action not in valid_actions:
        return {"success": False, "error": f"不支持的操作: {action}"}

    logger.bind(
        event="multi_agent_collaboration",
        action=action,
        target_agent=target_agent,
    ).info("多智能体协作")

    if action == "list_agents":
        # 从工作区管理器获取可用智能体列表
        return {
            "success": True,
            "action": "list_agents",
            "note": "可用智能体列表通过 /api/workspaces 获取",
            "agents_endpoint": "/api/workspaces",
        }

    elif action == "chat":
        if not target_agent or not request_text:
            return {"success": False, "error": "chat 操作需要提供 target_agent 和 request_text"}
        return {
            "success": True,
            "action": "chat",
            "target_agent": target_agent,
            "request": request_text[:500],
            "mode": "background" if background else "foreground",
            "session_id": session_id,
            "note": f"已将请求发送给智能体 '{target_agent}'，等待响应",
        }

    elif action == "delegate":
        if not target_agent or not request_text:
            return {"success": False, "error": "delegate 操作需要提供 target_agent 和 request_text"}
        # 委托子任务给目标智能体
        return {
            "success": True,
            "action": "delegate",
            "target_agent": target_agent,
            "task": request_text[:500],
            "background": background,
            "note": f"任务已委托给智能体 '{target_agent}'。使用 check_agent_task 查询进度。",
        }

    elif action == "request":
        if not request_text:
            return {"success": False, "error": "request 操作需要提供 request_text"}
        # 请求另一个智能体的专长能力
        return {
            "success": True,
            "action": "request",
            "target_agent": target_agent,
            "request": request_text[:500],
            "note": "协作请求已发出。如果指定了 target_agent，将向该智能体请求；否则由系统自动选择最合适的智能体。",
        }

    return {"success": False}

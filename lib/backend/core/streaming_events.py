"""
流式事件构造器，供 core 领域层与 api 接口层共用。
所有函数为纯函数，无副作用。
"""

from typing import Dict, Any


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


def emit_subagent_start_event(
    agent_id: str,
    agent_type: str,
    description: str = "",
    run_mode: str = "",
) -> Dict[str, Any]:
    """子代理启动事件，通知前端有新代理开始执行。"""
    return {
        "type": "subagent_start",
        "agent_id": agent_id,
        "agent_type": agent_type,
        "description": description,
        "run_mode": run_mode,
        "chunk_type": "subagent_start",
    }


def emit_subagent_stop_event(
    agent_id: str,
    state: str,
    summary: str = "",
    agent_type: str = "",
    run_mode: str = "",
) -> Dict[str, Any]:
    """子代理完成/失败事件，通知前端代理已结束。"""
    return {
        "type": "subagent_stop",
        "agent_id": agent_id,
        "agent_type": agent_type,
        "state": state,
        "summary": summary,
        "run_mode": run_mode,
        "chunk_type": "subagent_stop",
    }


def emit_agent_message_event(agent_id: str, message: str, agent_type: str = "") -> Dict[str, Any]:
    """代理消息事件，用于子代理摘要回传主线程。"""
    return {
        "type": "agent_message",
        "agent_id": agent_id,
        "agent_type": agent_type,
        "message": message,
        "chunk_type": "agent_message",
    }


def emit_task_created_event(task_data: Dict[str, Any]) -> Dict[str, Any]:
    """任务创建事件，通知前端有新任务项加入共享清单。"""
    return {
        "type": "task_created",
        "chunk_type": "task_created",
        "task": task_data,
    }


def emit_task_updated_event(task_data: Dict[str, Any]) -> Dict[str, Any]:
    """任务状态更新事件，通知前端任务状态变更。"""
    return {
        "type": "task_updated",
        "chunk_type": "task_updated",
        "task": task_data,
    }


def emit_task_stopped_event(task_id: str, status: str, summary: str = "") -> Dict[str, Any]:
    """任务停止事件，通知前端任务已被取消/停止。"""
    return {
        "type": "task_stopped",
        "chunk_type": "task_stopped",
        "task_id": task_id,
        "status": status,
        "summary": summary,
    }


def emit_team_event(team_data: Dict[str, Any]) -> Dict[str, Any]:
    """团队事件，通知前端团队创建、成员变更或清理。"""
    return {
        "type": "team_event",
        "chunk_type": "team_event",
        "team": team_data,
    }


def emit_ask_user_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    """ask_user 事件，向前端下发交互式问题卡片。

    前端收到后渲染 AskUserCard 组件，用户回答通过
    POST /api/chat/ask-user/reply 提交，由 PendingAskUser 解除 future 阻塞。
    """
    return {
        "type": "ask_user",
        "chunk_type": "ask_user",
        "ask_user": payload,
    }

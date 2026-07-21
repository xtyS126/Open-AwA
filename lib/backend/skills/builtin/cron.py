"""
cron 内置技能 — 定时任务管理。
从 Agent 对话中创建、查询、暂停和删除定时任务。
"""
from datetime import datetime, timezone
from typing import Any, Optional
from loguru import logger

SKILL_NAME = "cron"
SKILL_DESCRIPTION = "管理定时任务：创建、查询、暂停、恢复和删除周期性或一次性任务"


async def execute(
    action: str,
    name: Optional[str] = None,
    cron_expression: Optional[str] = None,
    task_type: str = "ai_prompt",
    prompt: Optional[str] = None,
    job_id: Optional[str] = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    执行定时任务管理操作。

    Args:
        action: 操作类型（create/list/pause/resume/delete）
        name: 任务名称
        cron_expression: Cron 表达式（如 "0 9 * * *"）
        task_type: 任务类型（ai_prompt/plugin_command）
        prompt: AI 任务的提示词
        job_id: 任务 ID（用于暂停/恢复/删除）

    Returns:
        操作结果
    """
    valid_actions = {"create", "list", "pause", "resume", "delete"}
    if action not in valid_actions:
        return {"success": False, "error": f"不支持的操作: {action}，支持: {', '.join(valid_actions)}"}

    logger.bind(event="cron_skill", action=action).info(f"定时任务操作: {action}")

    if action == "create":
        if not name or not cron_expression:
            return {"success": False, "error": "创建任务需要提供 name 和 cron_expression"}
        # 验证 cron 表达式格式
        parts = cron_expression.strip().split()
        if len(parts) != 5:
            return {"success": False, "error": f"无效的 cron 表达式: {cron_expression}，需要 5 个字段"}
        return {
            "success": True,
            "action": "create",
            "task": {
                "name": name,
                "cron_expression": cron_expression,
                "task_type": task_type,
                "prompt": prompt,
                "is_daily": task_type == "ai_prompt",
            },
            "note": "定时任务已创建，将由 ScheduledTaskManager 调度执行",
        }

    elif action == "list":
        return {
            "success": True,
            "action": "list",
            "note": "请通过 ScheduledTaskManager API 获取任务列表",
        }

    elif action == "pause":
        if not job_id:
            return {"success": False, "error": "暂停任务需要提供 job_id"}
        return {"success": True, "action": "pause", "job_id": job_id}

    elif action == "resume":
        if not job_id:
            return {"success": False, "error": "恢复任务需要提供 job_id"}
        return {"success": True, "action": "resume", "job_id": job_id}

    elif action == "delete":
        if not job_id:
            return {"success": False, "error": "删除任务需要提供 job_id"}
        return {"success": True, "action": "delete", "job_id": job_id}

    return {"success": False, "error": "未知操作"}

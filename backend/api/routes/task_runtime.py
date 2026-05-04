"""
任务运行时 API 路由，提供代理会话查询、停止与 transcript 读取接口。
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger

from api.dependencies import get_current_user
from core.task_runtime import task_runtime

router = APIRouter(prefix="/api/task-runtime", tags=["task-runtime"])


def _raise_not_found(detail: str) -> None:
    """将不存在资源统一转换为标准 404 HTTP 错误。"""
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _raise_not_found_from_result(result: Dict[str, Any]) -> None:
    """将底层返回中的“不存在”错误语义提升为标准 404。"""
    error = result.get("error")
    if result.get("ok") is False and isinstance(error, str) and "不存在" in error:
        _raise_not_found(error)


@router.on_event("startup")
async def startup():
    """路由启动时初始化任务运行时（回收悬挂会话）。"""
    await task_runtime.initialize()
    logger.bind(module="task_runtime_api").info("任务运行时路由已启动")


@router.get("/agents")
async def list_agents(
    state: Optional[str] = Query(None, description="按状态过滤: running/completed/failed/stopped"),
    agent_type: Optional[str] = Query(None, description="按代理类型过滤"),
    _current_user=Depends(get_current_user),
):
    """列出活跃与历史代理会话。"""
    result = await task_runtime.list_agents(state=state)
    if agent_type:
        result = [a for a in result if a.get("agent_type") == agent_type]
    return {"agents": result, "total": len(result)}


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str, _current_user=Depends(get_current_user)):
    """获取单个代理会话详情。"""
    agent = await task_runtime.get_agent(agent_id)
    if not agent:
        _raise_not_found(f"代理不存在: {agent_id}")
    return {"agent": agent}


@router.post("/agents/{agent_id}/stop")
async def stop_agent(agent_id: str, _current_user=Depends(get_current_user)):
    """停止运行中的后台代理。"""
    result = await task_runtime.stop_agent(agent_id)
    _raise_not_found_from_result(result)
    return result


@router.get("/agents/{agent_id}/transcript")
async def get_agent_transcript(agent_id: str, _current_user=Depends(get_current_user)):
    """获取代理的完整执行 transcript。"""
    agent = await task_runtime.get_agent(agent_id)
    if not agent:
        _raise_not_found(f"代理不存在: {agent_id}")
    transcript = await task_runtime.get_transcript(agent_id)
    return {"agent_id": agent_id, "transcript": transcript, "entry_count": len(transcript)}


@router.get("/agent-types")
async def list_agent_types(_current_user=Depends(get_current_user)):
    """列出所有可用代理类型。"""
    result = await task_runtime.list_agent_types()
    return {"agent_types": result}


@router.get("/tasks")
async def list_tasks(
    list_id: Optional[str] = Query(None, description="按清单 ID 过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    _current_user=Depends(get_current_user),
):
    """列出共享任务清单中的任务项。"""
    result = await task_runtime.list_task_items(list_id=list_id, status=status)
    return {"tasks": result, "total": len(result)}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, _current_user=Depends(get_current_user)):
    """获取单个任务项详情。"""
    task = await task_runtime.get_task_item(task_id)
    if not task:
        _raise_not_found(f"任务不存在: {task_id}")
    return {"task": task}


@router.post("/tasks/{task_id}/claim")
async def claim_task(
    task_id: str,
    agent_id: str = Query(..., description="领取任务的代理 ID"),
    _current_user=Depends(get_current_user),
):
    """事务性领取一个待执行的任务项。"""
    result = await task_runtime.claim_task_item(task_id=task_id, agent_id=agent_id)
    _raise_not_found_from_result(result)
    return result


@router.post("/tasks/{task_id}/stop")
async def stop_task(task_id: str, _current_user=Depends(get_current_user)):
    """取消/停止一个任务项（仅限非终态）。"""
    result = await task_runtime.update_task_item(task_id, status="cancelled")
    _raise_not_found_from_result(result)
    return result


# ── 团队管理端点（Phase 4）────────────────────────────────────

@router.get("/teams")
async def list_teams(
    state: Optional[str] = Query(None, description="按状态过滤: active/cleaning/stopped/failed"),
    _current_user=Depends(get_current_user),
):
    """列出所有代理团队。"""
    result = await task_runtime.list_teams(state=state)
    return {"teams": result, "total": len(result)}


@router.get("/teams/{team_id}")
async def get_team(team_id: str, _current_user=Depends(get_current_user)):
    """获取单个团队详情。"""
    team = await task_runtime.get_team(team_id)
    if not team:
        _raise_not_found(f"团队不存在: {team_id}")
    return {"team": team}


@router.post("/teams")
async def create_team(
    lead_agent_id: str = Query(..., description="团队负责人 agent_id"),
    name: str = Query("", description="团队名称"),
    task_list_id: Optional[str] = Query(None, description="共享任务清单 ID"),
    _current_user=Depends(get_current_user),
):
    """创建代理团队。"""
    result = await task_runtime.create_team(
        lead_agent_id=lead_agent_id,
        name=name,
        task_list_id=task_list_id,
    )
    return result


@router.delete("/teams/{team_id}")
async def delete_team(team_id: str, _current_user=Depends(get_current_user)):
    """删除代理团队。"""
    result = await task_runtime.delete_team(team_id)
    _raise_not_found_from_result(result)
    return result


@router.post("/teams/{team_id}/members")
async def add_teammate(
    team_id: str,
    agent_id: str = Query(..., description="要添加的代理 ID"),
    name: str = Query("", description="成员名称"),
    _current_user=Depends(get_current_user),
):
    """向团队添加成员。"""
    result = await task_runtime.add_teammate(team_id, agent_id, name)
    _raise_not_found_from_result(result)
    return result


@router.delete("/teams/{team_id}/members/{agent_id}")
async def remove_teammate(team_id: str, agent_id: str, _current_user=Depends(get_current_user)):
    """从团队移除成员。"""
    result = await task_runtime.remove_teammate(team_id, agent_id)
    _raise_not_found_from_result(result)
    return result


@router.patch("/teams/{team_id}/members/{agent_id}/state")
async def update_teammate_state(
    team_id: str,
    agent_id: str,
    new_state: str = Query(..., description="新状态: active/idle/stopped"),
    _current_user=Depends(get_current_user),
):
    """更新团队成员状态。"""
    result = await task_runtime.update_teammate_state(team_id, agent_id, new_state)
    _raise_not_found_from_result(result)
    return result


@router.get("/mailbox/{agent_id}")
async def get_mailbox(
    agent_id: str,
    unread_only: bool = Query(False, description="是否仅获取未读消息"),
    _current_user=Depends(get_current_user),
):
    """获取代理的邮箱消息。"""
    messages = await task_runtime.get_mailbox(agent_id, unread_only=unread_only)
    return {"agent_id": agent_id, "messages": messages, "total": len(messages)}


@router.post("/mailbox/{message_id}/read")
async def read_message(message_id: str, _current_user=Depends(get_current_user)):
    """标记消息为已读。"""
    result = await task_runtime.read_message(message_id)
    _raise_not_found_from_result(result)
    return result


@router.post("/messages")
async def send_teammate_message(
    from_agent_id: str = Query(..., description="发送方 agent_id"),
    to_agent_id: str = Query(..., description="接收方 agent_id"),
    message: str = Query(..., description="消息内容"),
    team_id: Optional[str] = Query(None, description="所属团队 ID"),
    _current_user=Depends(get_current_user),
):
    """向队友发送消息。"""
    result = await task_runtime.send_teammate_message(
        from_agent_id=from_agent_id,
        to_agent_id=to_agent_id,
        message=message,
        team_id=team_id,
    )
    return result

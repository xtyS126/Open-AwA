"""
定时任务路由，提供一次性任务的创建、查询、更新、取消与执行历史接口。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from api.schemas import (
    ScheduledTaskCreate,
    ScheduledTaskExecutionResponse,
    ScheduledTaskResponse,
    ScheduledTaskUpdate,
)
from db.models import ScheduledTask, ScheduledTaskExecution, get_db


router = APIRouter(prefix="/scheduled-tasks", tags=["ScheduledTasks"])

UPDATABLE_TASK_STATUSES = {"pending"}
CANCELLABLE_TASK_STATUSES = {"pending"}


def _normalize_optional_text(value: Optional[str]) -> Optional[str]:
    """
    将空字符串统一归一化为 None，避免数据库中保存无意义空值。
    """
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _get_task_or_404(db: Session, task_id: int, user_id: str) -> ScheduledTask:
    """
    查询当前用户的定时任务，不存在时抛出 404。
    """
    task = (
        db.query(ScheduledTask)
        .filter(ScheduledTask.id == task_id, ScheduledTask.user_id == user_id)
        .first()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    return task


def _require_non_empty_text(value: str, field_name: str) -> str:
    """
    拒绝仅包含空白字符的输入，避免产生无效任务标题或提示词。
    """
    normalized = value.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail=f"{field_name} cannot be empty")
    return normalized


def _ensure_task_status_allowed(task: ScheduledTask, allowed_statuses: set[str], action: str) -> None:
    """
    使用白名单方式校验任务状态，避免状态扩展后遗漏边界判断。
    """
    if task.status in allowed_statuses:
        return

    allowed_status_text = " or ".join(sorted(allowed_statuses))
    raise HTTPException(
        status_code=400,
        detail=f"Only {allowed_status_text} scheduled tasks can be {action}",
    )


@router.get("", response_model=List[ScheduledTaskResponse])
async def list_scheduled_tasks(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user_id = str(current_user.id)
    query = db.query(ScheduledTask).filter(ScheduledTask.user_id == user_id)
    if status:
        query = query.filter(ScheduledTask.status == status)

    return (
        query.order_by(ScheduledTask.scheduled_at.asc(), ScheduledTask.id.desc())
        .limit(limit)
        .all()
    )


@router.get("/executions", response_model=List[ScheduledTaskExecutionResponse])
async def list_scheduled_task_executions(
    task_id: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user_id = str(current_user.id)
    query = db.query(ScheduledTaskExecution).filter(ScheduledTaskExecution.user_id == user_id)
    if task_id is not None:
        query = query.filter(ScheduledTaskExecution.task_id == task_id)

    return (
        query.order_by(ScheduledTaskExecution.started_at.desc(), ScheduledTaskExecution.id.desc())
        .limit(limit)
        .all()
    )


@router.post("", response_model=ScheduledTaskResponse)
async def create_scheduled_task(
    request: ScheduledTaskCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    title = _require_non_empty_text(request.title, "title")
    prompt = _require_non_empty_text(request.prompt, "prompt")

    task = ScheduledTask(
        user_id=str(current_user.id),
        title=title,
        prompt=prompt,
        scheduled_at=request.scheduled_at,
        provider=_normalize_optional_text(request.provider),
        model=_normalize_optional_text(request.model),
        status="pending",
        task_metadata={"kind": "prompt_once"},
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.get("/{task_id}", response_model=ScheduledTaskResponse)
async def get_scheduled_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return _get_task_or_404(db, task_id, str(current_user.id))


@router.put("/{task_id}", response_model=ScheduledTaskResponse)
async def update_scheduled_task(
    task_id: int,
    request: ScheduledTaskUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    task = _get_task_or_404(db, task_id, str(current_user.id))
    _ensure_task_status_allowed(task, UPDATABLE_TASK_STATUSES, "updated")

    if request.title is not None:
        task.title = _require_non_empty_text(request.title, "title")
    if request.prompt is not None:
        task.prompt = _require_non_empty_text(request.prompt, "prompt")
    if request.scheduled_at is not None:
        task.scheduled_at = request.scheduled_at
    if request.provider is not None:
        task.provider = _normalize_optional_text(request.provider)
    if request.model is not None:
        task.model = _normalize_optional_text(request.model)

    db.commit()
    db.refresh(task)
    return task


@router.delete("/{task_id}")
async def cancel_scheduled_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    task = _get_task_or_404(db, task_id, str(current_user.id))
    _ensure_task_status_allowed(task, CANCELLABLE_TASK_STATUSES, "cancelled")

    now = datetime.now(timezone.utc)
    task.status = "cancelled"
    task.cancelled_at = now
    task.completed_at = now
    task.last_error_message = None
    db.commit()

    return {"message": "Scheduled task cancelled successfully"}
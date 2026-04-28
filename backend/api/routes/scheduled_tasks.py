"""
定时任务路由，提供一次性任务和每日重复任务的创建、查询、更新、取消与执行历史接口。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


def _build_cron_expression(weekdays: str, daily_time: str) -> str:
    """
    根据选中的星期和每日时间构建 cron 表达式。
    weekdays: 逗号分隔的数字（0=周日, 1=周一, ... 6=周六）
    daily_time: HH:MM 格式
    返回 cron 表达式：分 时 * * 星期
    """
    parts = daily_time.split(":")
    hour = int(parts[0])
    minute = int(parts[1])
    return f"{minute} {hour} * * {weekdays}"


def _calculate_next_execution(cron_expression: str, from_time: Optional[datetime] = None) -> Optional[datetime]:
    """
    根据 cron 表达式计算下一次执行时间。
    使用简单的日期遍历实现，最多向前查找 14 天。
    """
    if not cron_expression or not cron_expression.strip():
        return None
    parts = cron_expression.strip().split()
    if len(parts) != 5:
        return None
    try:
        target_minute = int(parts[0])
        target_hour = int(parts[1])
        target_weekdays = set(int(d) for d in parts[4].split(","))
    except (ValueError, IndexError):
        return None

    now = from_time or datetime.now(timezone.utc)
    # 从当前时间后一分钟开始查找
    check = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    check = check.replace(hour=target_hour, minute=target_minute)

    for _ in range(14):  # 最多查找 14 天
        weekday = (check.weekday() + 1) % 7  # Python weekday(): 0=周一, 转为 cron: 0=周日
        if weekday in target_weekdays and check > now:
            return check
        check += timedelta(days=1)

    return None


def _set_task_daily_fields(task: ScheduledTask, request) -> None:
    """将请求中的每日任务字段同步到模型实例。"""
    if request.is_daily is not None:
        task.is_daily = request.is_daily
    if request.cron_expression is not None:
        task.cron_expression = _normalize_optional_text(request.cron_expression)
    if request.weekdays is not None:
        task.weekdays = _normalize_optional_text(request.weekdays)
    if request.daily_time is not None:
        task.daily_time = _normalize_optional_text(request.daily_time)


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

    # 处理每日执行模式：生成 cron 表达式
    cron_expr = _normalize_optional_text(request.cron_expression)
    if request.is_daily and not cron_expr:
        if not request.weekdays or not request.daily_time:
            raise HTTPException(status_code=400, detail="每日执行任务必须选择至少一天和指定时间")
        cron_expr = _build_cron_expression(request.weekdays, request.daily_time)

    task = ScheduledTask(
        user_id=str(current_user.id),
        title=title,
        prompt=prompt,
        scheduled_at=request.scheduled_at,
        provider=_normalize_optional_text(request.provider),
        model=_normalize_optional_text(request.model),
        status="pending",
        is_daily=bool(request.is_daily),
        cron_expression=_normalize_optional_text(cron_expr or request.cron_expression),
        weekdays=_normalize_optional_text(request.weekdays),
        daily_time=_normalize_optional_text(request.daily_time),
        task_metadata={"kind": "daily" if request.is_daily else "prompt_once"},
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # 计算并附加 next_execution_at
    next_exec = _calculate_next_execution(task.cron_expression) if task.cron_expression else None
    task_dict = ScheduledTaskResponse.from_orm(task).dict()
    task_dict["next_execution_at"] = next_exec.isoformat() if next_exec else task.scheduled_at.isoformat()
    return task_dict


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

    # 处理每日任务字段
    _set_task_daily_fields(task, request)
    if request.is_daily:
        task.task_metadata["kind"] = "daily"
        if request.weekdays and request.daily_time:
            task.cron_expression = _build_cron_expression(request.weekdays, request.daily_time)

    db.commit()
    db.refresh(task)

    next_exec = _calculate_next_execution(task.cron_expression) if task.cron_expression else None
    task_dict = ScheduledTaskResponse.from_orm(task).dict()
    task_dict["next_execution_at"] = next_exec.isoformat() if next_exec else task.scheduled_at.isoformat()
    return task_dict


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
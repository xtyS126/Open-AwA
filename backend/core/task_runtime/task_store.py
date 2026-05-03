"""
共享任务清单存储层，提供 TaskCreate/TaskGet/TaskList/TaskUpdate 的基础 CRUD 操作。
Phase 2 扩展了任务状态机校验、依赖验证与事务性领取（claim）逻辑。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from loguru import logger
from sqlalchemy.orm import Session

from db.models import SessionLocal, TaskItem, TaskEvent

# 合法的任务状态转换
VALID_TASK_TRANSITIONS: Dict[str, Set[str]] = {
    "pending": {"running", "cancelled"},
    "blocked": {"pending", "cancelled"},
    "running": {"completed", "failed", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}


def _generate_task_id() -> str:
    return f"tsk_{uuid.uuid4().hex[:12]}"


def validate_task_transition(current_state: str, new_state: str) -> bool:
    """校验任务状态转换是否合法。"""
    allowed = VALID_TASK_TRANSITIONS.get(current_state, set())
    return new_state in allowed


def _write_task_event(
    db: Session,
    event_type: str,
    entity_id: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    """写入任务审计事件到 task_events 表。"""
    event = TaskEvent(
        event_type=event_type,
        entity_type="task_item",
        entity_id=entity_id,
        payload_json=payload or {},
        created_at=datetime.now(timezone.utc),
    )
    db.add(event)
    db.flush()


def validate_dependencies(db: Session, task_id: str) -> List[str]:
    """
    检查任务的所有直接依赖是否已处于 completed 状态。
    返回未满足的依赖 task_id 列表，空列表表示全部满足。
    """
    task = db.query(TaskItem).filter(TaskItem.task_id == task_id).first()
    if not task:
        return []

    deps = task.dependencies_json.get("items", []) if task.dependencies_json else []
    if not deps:
        return []

    unmet = []
    for dep_id in deps:
        dep_task = db.query(TaskItem).filter(TaskItem.task_id == dep_id).first()
        if not dep_task or dep_task.status != "completed":
            unmet.append(dep_id)

    if unmet:
        logger.bind(
            module="task_runtime",
            task_id=task_id,
            unmet_deps=unmet,
        ).debug(f"任务依赖未满足: {task_id}")
    return unmet


def create_task(
    db: Session,
    *,
    list_id: Optional[str] = None,
    subject: str = "",
    description: Optional[str] = None,
    dependencies: Optional[List[str]] = None,
    owner_agent_id: Optional[str] = None,
) -> TaskItem:
    """创建新的任务清单项。"""
    task_id = _generate_task_id()
    now = datetime.now(timezone.utc)

    task = TaskItem(
        task_id=task_id,
        list_id=list_id,
        subject=subject,
        description=description,
        status="pending",
        dependencies_json={"items": dependencies or []},
        owner_agent_id=owner_agent_id,
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    db.flush()

    _write_task_event(db, "task.created", task_id, {
        "subject": subject,
        "list_id": list_id,
        "dependencies": dependencies or [],
    })

    db.commit()
    db.refresh(task)
    logger.bind(module="task_runtime", task_id=task_id, subject=subject).debug(f"任务已创建: {task_id}")
    return task


def get_task(task_id: str) -> Optional[TaskItem]:
    """按 task_id 获取任务项。"""
    db: Session = SessionLocal()
    try:
        return db.query(TaskItem).filter(TaskItem.task_id == task_id).first()
    finally:
        db.close()


def list_tasks(
    *,
    list_id: Optional[str] = None,
    status: Optional[str] = None,
    owner_agent_id: Optional[str] = None,
    limit: int = 50,
) -> List[TaskItem]:
    """列出任务项，支持按清单、状态、归属过滤。"""
    db: Session = SessionLocal()
    try:
        q = db.query(TaskItem)
        if list_id:
            q = q.filter(TaskItem.list_id == list_id)
        if status:
            q = q.filter(TaskItem.status == status)
        if owner_agent_id:
            q = q.filter(TaskItem.owner_agent_id == owner_agent_id)
        return q.order_by(TaskItem.created_at.desc()).limit(limit).all()
    finally:
        db.close()


def update_task(
    db: Session,
    task_id: str,
    *,
    status: Optional[str] = None,
    subject: Optional[str] = None,
    description: Optional[str] = None,
    owner_agent_id: Optional[str] = None,
    result_summary: Optional[str] = None,
) -> Optional[TaskItem]:
    """更新任务项字段，含状态机校验。"""
    task = db.query(TaskItem).filter(TaskItem.task_id == task_id).first()
    if not task:
        logger.bind(module="task_runtime", task_id=task_id).warning(f"任务不存在: {task_id}")
        return None

    if status is not None:
        if not validate_task_transition(task.status, status):
            logger.bind(
                module="task_runtime",
                task_id=task_id,
                current_status=task.status,
                new_status=status,
            ).warning(f"非法的任务状态转换: {task.status} -> {status}")
            return None

        # 转换为 running 前校验依赖
        if status == "running":
            unmet = validate_dependencies(db, task_id)
            if unmet:
                logger.bind(
                    module="task_runtime",
                    task_id=task_id,
                    unmet_deps=unmet,
                ).warning(f"任务依赖未满足，无法启动: {task_id}")
                return None

        task.status = status
        if status in ("completed", "failed", "cancelled"):
            task.completed_at = datetime.now(timezone.utc)
    if subject is not None:
        task.subject = subject
    if description is not None:
        task.description = description
    if owner_agent_id is not None:
        task.owner_agent_id = owner_agent_id
    if result_summary is not None:
        task.result_summary = result_summary

    task.updated_at = datetime.now(timezone.utc)

    _write_task_event(db, "task.updated", task_id, {
        "new_status": status,
        "owner_agent_id": owner_agent_id,
    })

    db.commit()
    db.refresh(task)
    return task


def claim_task(db: Session, task_id: str, agent_id: str) -> Optional[TaskItem]:
    """
    事务性领取一个待执行任务。
    使用 with db.begin() 事务模式保证并发安全。
    返回领取的 TaskItem，若已被领取或依赖未满足则返回 None。
    """
    # 提交已有的隐式事务，避免 autobegin 冲突
    if db._transaction is not None:
        db.commit()
    with db.begin():
        task = db.query(TaskItem).filter(
            TaskItem.task_id == task_id,
            TaskItem.status == "pending",
        ).first()
        if not task:
            logger.bind(
                module="task_runtime",
                task_id=task_id,
            ).debug(f"任务领取失败（不存在或非 pending）: {task_id}")
            return None

        # 校验依赖
        unmet = validate_dependencies(db, task_id)
        if unmet:
            task.status = "blocked"
            task.updated_at = datetime.now(timezone.utc)
            _write_task_event(db, "task.blocked", task_id, {
                "unmet_dependencies": unmet,
            })
            logger.bind(
                module="task_runtime",
                task_id=task_id,
                unmet_deps=unmet,
            ).info(f"任务依赖未满足，置为 blocked: {task_id}")
            return None

        now = datetime.now(timezone.utc)
        task.status = "running"
        task.owner_agent_id = agent_id
        task.started_at = now
        task.updated_at = now

        _write_task_event(db, "task.claimed", task_id, {
            "owner_agent_id": agent_id,
        })

    db.refresh(task)
    logger.bind(
        module="task_runtime",
        task_id=task_id,
        agent_id=agent_id,
    ).info(f"任务已领取: {task_id} -> {agent_id}")
    return task


def sync_todo_snapshot(
    db: Session,
    *,
    list_id: Optional[str] = None,
    todos: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    同步 todo 快照：对比现有任务清单，新增/更新/移除 todo 项。
    非交互模式的简化入口，对应 Claude Code 的 TodoWrite 工具。
    todos: [{"subject": "...", "status": "pending|completed", "description": "..."}, ...]
    """
    existing = db.query(TaskItem).filter(TaskItem.list_id == list_id).all()
    existing_map: Dict[str, TaskItem] = {t.subject: t for t in existing}

    created = 0
    updated = 0
    removed = 0
    incoming_subjects = {t.get("subject", "") for t in todos}

    for todo in todos:
        subject = todo.get("subject", "")
        if not subject:
            continue
        desc = todo.get("description")
        status = todo.get("status", "pending")

        if status not in ("pending", "completed", "running", "cancelled"):
            status = "pending"

        if subject in existing_map:
            task = existing_map[subject]
            if task.status != status:
                task.status = status
                task.updated_at = datetime.now(timezone.utc)
                if status == "completed":
                    task.completed_at = datetime.now(timezone.utc)
                updated += 1
        else:
            task = TaskItem(
                task_id=_generate_task_id(),
                list_id=list_id,
                subject=subject,
                description=desc,
                status=status,
                dependencies_json={"items": []},
            )
            db.add(task)
            created += 1

    # 移除不在传入快照中的未完成任务
    for subject, task in existing_map.items():
        if subject not in incoming_subjects and task.status not in ("completed", "cancelled"):
            task.status = "cancelled"
            task.updated_at = datetime.now(timezone.utc)
            removed += 1

    db.commit()

    logger.bind(
        module="task_runtime",
        list_id=list_id,
        created=created,
        updated=updated,
        removed=removed,
    ).debug(f"Todo 快照同步完成: +{created} ~{updated} -{removed}")

    return {"ok": True, "created": created, "updated": updated, "removed": removed}

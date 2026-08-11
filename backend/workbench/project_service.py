"""工作台项目 CRUD、上下文与统一根解析领域服务。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models.workbench import WorkbenchContext, WorkbenchProject
from workbench.errors import ProjectDisabled, ProjectNotFound, ProjectRootConflict, ProjectRootInvalid
from workbench.path_policy import WorkbenchPathPolicy


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_display_name(display_name: str) -> str:
    """统一项目显示名，拒绝空白、超长和控制字符。"""
    if not isinstance(display_name, str):
        raise ProjectRootInvalid("工作台项目名称无效")
    normalized = display_name.strip()
    if not normalized or len(normalized) > 200:
        raise ProjectRootInvalid("工作台项目名称长度必须为 1 至 200 个字符")
    if any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in normalized):
        raise ProjectRootInvalid("工作台项目名称不能包含控制字符")
    return normalized


class WorkbenchProjectService:
    """用单次所有权查询管理项目，并在每次消费前重验路径。"""

    def __init__(self, db: Session, path_policy: WorkbenchPathPolicy) -> None:
        self.db = db
        self.path_policy = path_policy

    def list_projects(self, *, user_id: str) -> list[WorkbenchProject]:
        statement = (
            select(WorkbenchProject)
            .where(WorkbenchProject.user_id == str(user_id))
            .order_by(
                WorkbenchProject.is_enabled.desc(),
                WorkbenchProject.last_opened_at.desc().nullslast(),
                WorkbenchProject.updated_at.desc(),
            )
        )
        return list(self.db.scalars(statement))

    def get_owned_project(
        self,
        *,
        user_id: str,
        project_id: str,
        require_enabled: bool = False,
    ) -> WorkbenchProject:
        statement = select(WorkbenchProject).where(
            WorkbenchProject.id == str(project_id),
            WorkbenchProject.user_id == str(user_id),
        )
        project = self.db.scalar(statement)
        if project is None:
            raise ProjectNotFound()
        if require_enabled and not project.is_enabled:
            raise ProjectDisabled()
        return project

    def register_project(
        self,
        *,
        user_id: str,
        user_role: str,
        display_name: str,
        root: str,
    ) -> WorkbenchProject:
        normalized_name = _normalize_display_name(display_name)
        registered_root, canonical_root = self.path_policy.canonicalize_registration(
            root,
            user_id=str(user_id),
            user_role=user_role,
        )
        existing = self.db.scalar(
            select(WorkbenchProject.id).where(
                WorkbenchProject.user_id == str(user_id),
                WorkbenchProject.canonical_root == canonical_root,
            )
        )
        if existing is not None:
            raise ProjectRootConflict()

        project = WorkbenchProject(
            user_id=str(user_id),
            display_name=normalized_name,
            registered_root=registered_root,
            canonical_root=canonical_root,
        )
        self.db.add(project)
        try:
            self.db.flush()
        except IntegrityError as exc:
            self.db.rollback()
            raise ProjectRootConflict() from exc
        return project

    def resolve_project_root(
        self,
        *,
        user_id: str,
        user_role: str,
        project_id: str,
    ) -> Path:
        project = self.get_owned_project(
            user_id=user_id,
            project_id=project_id,
            require_enabled=True,
        )
        return self.path_policy.resolve_registered_root(
            project.registered_root,
            project.canonical_root,
            user_id=str(user_id),
            user_role=user_role,
        )

    def update_project(
        self,
        *,
        user_id: str,
        project_id: str,
        display_name: Optional[str],
        is_enabled: Optional[bool],
    ) -> WorkbenchProject:
        project = self.get_owned_project(user_id=user_id, project_id=project_id)
        if display_name is not None:
            project.display_name = _normalize_display_name(display_name)
        if is_enabled is not None:
            project.is_enabled = is_enabled
            if not is_enabled:
                self._clear_context_if_selected(user_id=str(user_id), project_id=project.id)
        project.updated_at = _utc_now()
        self.db.flush()
        return project

    def get_context(self, *, user_id: str) -> tuple[Optional[WorkbenchContext], Optional[WorkbenchProject]]:
        context = self.db.get(WorkbenchContext, str(user_id))
        if context is None or context.current_project_id is None:
            return context, None
        try:
            project = self.get_owned_project(
                user_id=user_id,
                project_id=context.current_project_id,
            )
        except ProjectNotFound:
            context.current_project_id = None
            context.updated_at = _utc_now()
            self.db.flush()
            return context, None
        if not project.is_enabled:
            context.current_project_id = None
            context.updated_at = _utc_now()
            self.db.flush()
            return context, None
        return context, project

    def set_current_project(
        self,
        *,
        user_id: str,
        user_role: str,
        project_id: Optional[str],
    ) -> tuple[WorkbenchContext, Optional[WorkbenchProject]]:
        now = _utc_now()
        project: Optional[WorkbenchProject] = None
        if project_id is not None:
            project = self.get_owned_project(
                user_id=user_id,
                project_id=project_id,
                require_enabled=True,
            )
            self.path_policy.resolve_registered_root(
                project.registered_root,
                project.canonical_root,
                user_id=str(user_id),
                user_role=user_role,
            )
            project.last_opened_at = now
            project.updated_at = now

        context = self.db.get(WorkbenchContext, str(user_id))
        if context is None:
            context = WorkbenchContext(user_id=str(user_id))
            self.db.add(context)
        context.current_project_id = project.id if project is not None else None
        context.updated_at = now
        self.db.flush()
        return context, project

    def delete_project(self, *, user_id: str, project_id: str) -> None:
        project = self.get_owned_project(user_id=user_id, project_id=project_id)
        self._clear_context_if_selected(user_id=str(user_id), project_id=project.id)
        self.db.delete(project)
        self.db.flush()

    def _clear_context_if_selected(self, *, user_id: str, project_id: str) -> None:
        context = self.db.get(WorkbenchContext, user_id)
        if context is None or context.current_project_id != project_id:
            return
        context.current_project_id = None
        context.updated_at = _utc_now()


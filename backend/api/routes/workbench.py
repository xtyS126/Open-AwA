"""工作台项目、当前项目上下文与运行时占用查询 API。"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import NoReturn, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from loguru import logger
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from api.schemas import (
    WorkbenchContextResponse,
    WorkbenchContextUpdate,
    WorkbenchProjectCreate,
    WorkbenchProjectListResponse,
    WorkbenchProjectResponse,
    WorkbenchProjectUpdate,
    WorkbenchRuntimeResourceResponse,
    WorkbenchRuntimeResourcesResponse,
)
from config.settings import settings
from db.models import User, get_db
from workbench.errors import (
    ProjectDisabled,
    ProjectInUse,
    ProjectNotFound,
    ProjectRootChanged,
    ProjectRootConflict,
    ProjectRootForbidden,
    ProjectRootInvalid,
    WorkbenchError,
)
from workbench.path_policy import WorkbenchPathPolicy
from workbench.project_service import WorkbenchProjectService
from workbench.runtime_registry import WorkbenchRuntimeRegistry, runtime_registry


router = APIRouter(prefix="/api/workbench", tags=["workbench"])


def get_workbench_path_policy() -> WorkbenchPathPolicy:
    """按当前稳定设置构建路径策略；非法安全配置直接阻止请求。"""
    return WorkbenchPathPolicy.from_settings(settings)


def get_workbench_runtime_registry() -> WorkbenchRuntimeRegistry:
    return runtime_registry


def _detail(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _raise_http_error(exc: WorkbenchError) -> NoReturn:
    status_code = status.HTTP_409_CONFLICT
    if isinstance(exc, ProjectNotFound):
        status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, ProjectRootForbidden):
        status_code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, ProjectRootInvalid):
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(
        exc,
        (ProjectDisabled, ProjectRootChanged, ProjectRootConflict, ProjectInUse),
    ):
        status_code = status.HTTP_409_CONFLICT
    raise HTTPException(
        status_code=status_code,
        detail=_detail(exc.code, exc.message),
    ) from exc


def _project_response(project) -> WorkbenchProjectResponse:
    return WorkbenchProjectResponse.model_validate(project)


def _etag_for(updated_at: Optional[datetime]) -> str:
    raw_value = updated_at.isoformat() if updated_at is not None else "none"
    digest = hashlib.sha256(raw_value.encode("utf-8")).hexdigest()
    return f'"{digest}"'


def _check_if_match(if_match: Optional[str], updated_at: Optional[datetime]) -> None:
    if if_match is None:
        return
    if if_match != _etag_for(updated_at):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_detail("workbench_context_conflict", "工作台上下文已被其他窗口更新"),
        )


@router.get("/projects", response_model=WorkbenchProjectListResponse)
async def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    path_policy: WorkbenchPathPolicy = Depends(get_workbench_path_policy),
) -> WorkbenchProjectListResponse:
    service = WorkbenchProjectService(db, path_policy)
    projects = service.list_projects(user_id=str(current_user.id))
    return WorkbenchProjectListResponse(items=[_project_response(project) for project in projects])


@router.post(
    "/projects",
    response_model=WorkbenchProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project(
    body: WorkbenchProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    path_policy: WorkbenchPathPolicy = Depends(get_workbench_path_policy),
) -> WorkbenchProjectResponse:
    service = WorkbenchProjectService(db, path_policy)
    try:
        project = service.register_project(
            user_id=str(current_user.id),
            user_role=str(current_user.role),
            display_name=body.display_name,
            root=body.root,
        )
        db.commit()
        db.refresh(project)
    except WorkbenchError as exc:
        db.rollback()
        _raise_http_error(exc)
    logger.bind(
        event="workbench_project_registered",
        user_id=str(current_user.id),
        project_id=project.id,
    ).info("已登记工作台项目")
    return _project_response(project)


@router.get("/projects/{project_id}", response_model=WorkbenchProjectResponse)
async def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    path_policy: WorkbenchPathPolicy = Depends(get_workbench_path_policy),
) -> WorkbenchProjectResponse:
    service = WorkbenchProjectService(db, path_policy)
    try:
        project = service.get_owned_project(user_id=str(current_user.id), project_id=project_id)
    except WorkbenchError as exc:
        _raise_http_error(exc)
    return _project_response(project)


@router.patch("/projects/{project_id}", response_model=WorkbenchProjectResponse)
async def update_project(
    project_id: str,
    body: WorkbenchProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    path_policy: WorkbenchPathPolicy = Depends(get_workbench_path_policy),
    registry: WorkbenchRuntimeRegistry = Depends(get_workbench_runtime_registry),
) -> WorkbenchProjectResponse:
    service = WorkbenchProjectService(db, path_policy)
    try:
        if body.is_enabled is False:
            async with registry.exclusive(str(current_user.id), project_id) as guard:
                guard.assert_not_in_use()
                project = service.update_project(
                    user_id=str(current_user.id),
                    project_id=project_id,
                    display_name=body.display_name,
                    is_enabled=body.is_enabled,
                )
                db.commit()
        else:
            project = service.update_project(
                user_id=str(current_user.id),
                project_id=project_id,
                display_name=body.display_name,
                is_enabled=body.is_enabled,
            )
            db.commit()
        db.refresh(project)
    except WorkbenchError as exc:
        db.rollback()
        _raise_http_error(exc)
    return _project_response(project)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    path_policy: WorkbenchPathPolicy = Depends(get_workbench_path_policy),
    registry: WorkbenchRuntimeRegistry = Depends(get_workbench_runtime_registry),
) -> Response:
    service = WorkbenchProjectService(db, path_policy)
    try:
        async with registry.exclusive(str(current_user.id), project_id) as guard:
            guard.assert_not_in_use()
            service.delete_project(user_id=str(current_user.id), project_id=project_id)
            db.commit()
    except WorkbenchError as exc:
        db.rollback()
        _raise_http_error(exc)
    logger.bind(
        event="workbench_project_deleted",
        user_id=str(current_user.id),
        project_id=project_id,
    ).info("已删除工作台项目登记")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/context", response_model=WorkbenchContextResponse)
async def get_context(
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    path_policy: WorkbenchPathPolicy = Depends(get_workbench_path_policy),
) -> WorkbenchContextResponse:
    service = WorkbenchProjectService(db, path_policy)
    context, project = service.get_context(user_id=str(current_user.id))
    if context is not None and db.dirty:
        db.commit()
    updated_at = context.updated_at if context is not None else None
    response.headers["ETag"] = _etag_for(updated_at)
    return WorkbenchContextResponse(
        project=_project_response(project) if project is not None else None,
        updated_at=updated_at,
    )


@router.patch("/context", response_model=WorkbenchContextResponse)
async def update_context(
    body: WorkbenchContextUpdate,
    response: Response,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    path_policy: WorkbenchPathPolicy = Depends(get_workbench_path_policy),
) -> WorkbenchContextResponse:
    service = WorkbenchProjectService(db, path_policy)
    current_context, _current_project = service.get_context(user_id=str(current_user.id))
    _check_if_match(if_match, current_context.updated_at if current_context is not None else None)
    try:
        context, project = service.set_current_project(
            user_id=str(current_user.id),
            user_role=str(current_user.role),
            project_id=body.project_id,
        )
        db.commit()
        db.refresh(context)
        if project is not None:
            db.refresh(project)
    except WorkbenchError as exc:
        db.rollback()
        _raise_http_error(exc)
    response.headers["ETag"] = _etag_for(context.updated_at)
    logger.bind(
        event="workbench_context_updated",
        user_id=str(current_user.id),
        project_id=project.id if project is not None else None,
    ).info("已更新工作台当前项目")
    return WorkbenchContextResponse(
        project=_project_response(project) if project is not None else None,
        updated_at=context.updated_at,
    )


@router.get(
    "/projects/{project_id}/runtime-resources",
    response_model=WorkbenchRuntimeResourcesResponse,
)
async def list_runtime_resources(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    path_policy: WorkbenchPathPolicy = Depends(get_workbench_path_policy),
    registry: WorkbenchRuntimeRegistry = Depends(get_workbench_runtime_registry),
) -> WorkbenchRuntimeResourcesResponse:
    service = WorkbenchProjectService(db, path_policy)
    try:
        service.get_owned_project(user_id=str(current_user.id), project_id=project_id)
    except WorkbenchError as exc:
        _raise_http_error(exc)
    resources = await registry.list_active(str(current_user.id), project_id)
    return WorkbenchRuntimeResourcesResponse(
        items=[
            WorkbenchRuntimeResourceResponse(
                resource_type=resource.resource_type.value,
                resource_id=resource.resource_id,
            )
            for resource in resources
        ]
    )


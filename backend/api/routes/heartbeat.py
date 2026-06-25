"""
心跳 API 路由 — 提供工作空间心跳配置管理和手动触发接口。
"""
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from core.heartbeat.engine import get_heartbeat_registry, HeartbeatEngine
from db.models import get_db, User

router = APIRouter(prefix="/api/workspaces", tags=["Heartbeat"])

# 工作空间 ID 仅允许字母、数字、连字符和下划线，防止路径遍历
_WORKSPACE_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{1,100}$')


class HeartbeatConfigUpdateRequest(BaseModel):
    """心跳配置更新请求体。"""

    enabled: Optional[bool] = Field(default=None, description="是否启用心跳")
    interval_seconds: Optional[int] = Field(default=None, ge=1, le=86400, description="心跳间隔（秒）")
    prompt: Optional[str] = Field(default=None, max_length=10000, description="心跳提示词")
    # 允许额外的配置字段，兼容引擎动态配置
    model_config = {"extra": "allow"}


class HeartbeatFileUpdateRequest(BaseModel):
    """HEARTBEAT.md 文件更新请求体。"""

    content: str = Field(default="", max_length=100000, description="HEARTBEAT.md 文件内容")


def _validate_workspace_id(workspace_id: str) -> None:
    """校验工作空间 ID 格式，防止路径遍历和注入攻击。"""
    if not _WORKSPACE_ID_RE.match(workspace_id):
        raise HTTPException(status_code=400, detail="工作空间 ID 包含非法字符")


def _ensure_engine(workspace_id: str) -> HeartbeatEngine:
    """获取或创建工作空间的心跳引擎。"""
    _validate_workspace_id(workspace_id)
    registry = get_heartbeat_registry()
    return registry.get(workspace_id)


@router.get("/{workspace_id}/heartbeat", summary="获取工作空间的心跳配置")
async def get_heartbeat_config(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
):
    """获取指定工作空间的心跳配置。"""
    engine = _ensure_engine(workspace_id)
    return {"success": True, "config": engine.get_config()}


@router.put("/{workspace_id}/heartbeat", summary="更新工作空间的心跳配置")
async def update_heartbeat_config(
    workspace_id: str,
    body: HeartbeatConfigUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    """更新指定工作空间的心跳配置。"""
    engine = _ensure_engine(workspace_id)
    engine.configure(body.model_dump(exclude_none=True))
    return {"success": True, "config": engine.get_config()}


@router.post("/{workspace_id}/heartbeat/test", summary="手动触发一次心跳")
async def test_heartbeat(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
):
    """手动触发一次心跳检查（测试用）。"""
    engine = _ensure_engine(workspace_id)
    engine.configure({"enabled": True})  # 临时启用以测试
    result = await engine.run()
    return result


@router.put("/{workspace_id}/heartbeat/file", summary="更新 HEARTBEAT.md 内容")
async def update_heartbeat_file(
    workspace_id: str,
    body: HeartbeatFileUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    """更新工作空间的 HEARTBEAT.md 内容。"""
    engine = _ensure_engine(workspace_id)
    engine.update_heartbeat_file(body.content)
    return {"success": True, "message": "HEARTBEAT.md 已更新"}

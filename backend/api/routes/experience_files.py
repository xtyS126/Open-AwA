"""
后端接口路由模块，负责接收请求、校验输入并协调业务层返回统一响应。
这些路由函数通常是前端或外部调用与后端内部能力之间的第一层行为边界。
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import get_current_user


router = APIRouter(prefix="/experience-files", tags=["ExperienceFiles"])
_ALLOWED_EXTENSIONS = {".md", ".markdown"}


class ExperienceFileSummary(BaseModel):
    """
    封装与ExperienceFileSummary相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    file_name: str
    title: str
    updated_at: datetime
    size: int
    summary: str


class ExperienceFileDetail(BaseModel):
    """
    封装与ExperienceFileDetail相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    file_name: str
    title: str
    updated_at: datetime
    size: int
    content: str


class ExperienceFileSaveRequest(BaseModel):
    """
    封装与ExperienceFileSaveRequest相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    content: str


class ExperienceFileSaveResponse(BaseModel):
    """
    封装与ExperienceFileSaveResponse相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    file_name: str
    updated_at: datetime
    size: int


def _get_memory_skill_dir(user_id: int) -> Path:
    """
    返回指定用户的经验文件目录。
    安全：按 user_id 隔离存储，防止跨用户读写他人经验文件（IDOR 修复）。
    """
    memory_skill_dir = Path(__file__).resolve().parents[3] / "memory_skill" / str(user_id)
    memory_skill_dir.mkdir(parents=True, exist_ok=True)
    return memory_skill_dir


def _resolve_safe_markdown_path(file_name: str, user_id: int) -> Path:
    """
    解析并校验经验文件路径，确保：
    1. 文件名不包含路径分隔符（防路径穿越）
    2. 扩展名为 .md 或 .markdown
    3. 解析后路径必须仍在当前用户的专属目录内
    """
    if not file_name:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    if Path(file_name).name != file_name:
        raise HTTPException(status_code=400, detail="非法文件路径")

    extension = Path(file_name).suffix.lower()
    if extension not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="仅允许 .md 或 .markdown 文件")

    base_dir = _get_memory_skill_dir(user_id).resolve()
    target = (base_dir / file_name).resolve()
    if base_dir != target.parent:
        raise HTTPException(status_code=400, detail="非法文件路径")

    return target


def _extract_title(content: str, fallback: str) -> str:
    """
    处理extract、title相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title
    return fallback


def _extract_summary(content: str) -> str:
    """
    处理extract、summary相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return stripped[:160]
    return ""


def _list_experience_files_sync(user_id: int) -> list[ExperienceFileSummary]:
    """同步列出用户经验文件，供 to_thread 包装调用。"""
    base_dir = _get_memory_skill_dir(user_id)
    results: list[ExperienceFileSummary] = []

    for file_path in base_dir.iterdir():
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in _ALLOWED_EXTENSIONS:
            continue

        stat = file_path.stat()
        updated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        content = file_path.read_text(encoding="utf-8")
        results.append(
            ExperienceFileSummary(
                file_name=file_path.name,
                title=_extract_title(content, file_path.stem),
                updated_at=updated_at,
                size=stat.st_size,
                summary=_extract_summary(content),
            )
        )

    results.sort(key=lambda item: item.updated_at, reverse=True)
    return results


@router.get("", response_model=List[ExperienceFileSummary])
async def list_experience_files(current_user=Depends(get_current_user)):
    """
    列出当前用户专属的经验文件。
    安全：仅返回当前用户目录下的文件，按 user_id 隔离。
    """
    # 同步文件 I/O 包装为 to_thread，避免阻塞事件循环
    return await asyncio.to_thread(_list_experience_files_sync, current_user.id)


def _read_experience_file_sync(file_name: str, user_id: int) -> ExperienceFileDetail:
    """同步读取经验文件详情，供 to_thread 包装调用。"""
    file_path = _resolve_safe_markdown_path(file_name, user_id)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="经验文件不存在")

    stat = file_path.stat()
    updated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    content = file_path.read_text(encoding="utf-8")

    return ExperienceFileDetail(
        file_name=file_path.name,
        title=_extract_title(content, file_path.stem),
        updated_at=updated_at,
        size=stat.st_size,
        content=content,
    )


@router.get("/{file_name}", response_model=ExperienceFileDetail)
async def get_experience_file_detail(file_name: str, current_user=Depends(get_current_user)):
    """
    获取当前用户专属的经验文件详情。
    安全：仅允许访问当前用户目录下的文件。
    """
    # 同步文件 I/O 包装为 to_thread，避免阻塞事件循环
    return await asyncio.to_thread(_read_experience_file_sync, file_name, current_user.id)


def _write_experience_file_sync(file_name: str, content: str, user_id: int) -> ExperienceFileSaveResponse:
    """同步写入经验文件，供 to_thread 包装调用。"""
    file_path = _resolve_safe_markdown_path(file_name, user_id)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="经验文件不存在")

    file_path.write_text(content, encoding="utf-8")
    stat = file_path.stat()
    updated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

    return ExperienceFileSaveResponse(
        file_name=file_path.name,
        updated_at=updated_at,
        size=stat.st_size,
    )


@router.put("/{file_name}", response_model=ExperienceFileSaveResponse)
async def save_experience_file(file_name: str, payload: ExperienceFileSaveRequest, current_user=Depends(get_current_user)):
    """
    保存当前用户专属的经验文件。
    安全：仅允许写入当前用户目录下的文件。
    """
    # 同步文件 I/O 包装为 to_thread，避免阻塞事件循环
    return await asyncio.to_thread(
        _write_experience_file_sync, file_name, payload.content, current_user.id
    )

"""
后端接口路由模块，负责接收请求、校验输入并协调业务层返回统一响应。
这些路由函数通常是前端或外部调用与后端内部能力之间的第一层行为边界。
"""

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


def _get_memory_skill_dir() -> Path:
    """
    处理get、memory、skill、dir相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    memory_skill_dir = Path(__file__).resolve().parents[3] / "memory_skill"
    memory_skill_dir.mkdir(parents=True, exist_ok=True)
    return memory_skill_dir


def _resolve_safe_markdown_path(file_name: str) -> Path:
    """
    处理resolve、safe、markdown、path相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    if not file_name:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    if Path(file_name).name != file_name:
        raise HTTPException(status_code=400, detail="非法文件路径")

    extension = Path(file_name).suffix.lower()
    if extension not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="仅允许 .md 或 .markdown 文件")

    base_dir = _get_memory_skill_dir().resolve()
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


@router.get("", response_model=List[ExperienceFileSummary])
async def list_experience_files(current_user=Depends(get_current_user)):
    """
    列出experience、files相关内容，便于调用方查看、筛选或批量处理。
    返回结果通常会被页面展示、审计流程或后续操作复用。
    """
    base_dir = _get_memory_skill_dir()
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


@router.get("/{file_name}", response_model=ExperienceFileDetail)
async def get_experience_file_detail(file_name: str, current_user=Depends(get_current_user)):
    """
    获取experience、file、detail相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    file_path = _resolve_safe_markdown_path(file_name)
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


@router.put("/{file_name}", response_model=ExperienceFileSaveResponse)
async def save_experience_file(file_name: str, payload: ExperienceFileSaveRequest, current_user=Depends(get_current_user)):
    """
    保存experience、file相关数据到持久化存储。
    实现过程往往伴随序列化、写入、事务提交或异常回滚等步骤。
    """
    file_path = _resolve_safe_markdown_path(file_name)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="经验文件不存在")

    file_path.write_text(payload.content, encoding="utf-8")
    stat = file_path.stat()
    updated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

    return ExperienceFileSaveResponse(
        file_name=file_path.name,
        updated_at=updated_at,
        size=stat.st_size,
    )

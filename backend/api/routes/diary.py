"""
日记相关 API 路由。
提供日记生成、列表和读取端点，供前端或命令行调用。
"""

import asyncio
import os
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from api.services.diary_writer import (
    collect_diary_materials,
    generate_diary_content,
    get_logical_day,
    list_diaries,
    read_diary,
    resolve_diary_dir,
    save_diary,
)
from db.models import get_db, User

router = APIRouter(prefix="/diary", tags=["diary"])

# 日期格式校验：YYYY-MM-DD，防止任意字符串构造路径或注入
_DIARY_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ──────────────────────────────────────────────
# 响应模型
# ──────────────────────────────────────────────

class DiaryGenerateResponse(BaseModel):
    """日记生成响应模型"""
    success: bool
    file_path: Optional[str] = None
    content: Optional[str] = None
    logical_date: Optional[str] = None
    error: Optional[str] = None


class DiaryListResponse(BaseModel):
    """日记列表响应模型"""
    success: bool
    diaries: list = Field(default_factory=list)
    count: int = 0


class DiaryReadResponse(BaseModel):
    """日记读取响应模型"""
    success: bool
    date: str = ""
    content: str = ""


# ──────────────────────────────────────────────
# API 端点
# ──────────────────────────────────────────────

@router.post(
    "/generate",
    response_model=DiaryGenerateResponse,
    summary="触发日记生成",
    description="按逻辑日（凌晨4点日界线）收集当天对话摘要，调用 LLM 生成第一人称私人日记。",
)
async def generate_diary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    触发日记生成。
    按逻辑日收集当天所有对话摘要，调用 LLM 生成日记并持久化到文件系统。
    """
    # 计算逻辑日范围
    logical_date, range_start, range_end = get_logical_day()

    # 收集对话素材（同步 DB 查询包装为 to_thread，避免阻塞事件循环）
    materials = await asyncio.to_thread(
        collect_diary_materials,
        db=db,
        range_start=range_start,
        range_end=range_end,
        user_id=current_user.id,
    )

    if not materials:
        logger.bind(
            event="diary_no_materials",
            module="diary",
            logical_date=logical_date,
        ).info("今天还没有对话记录，没什么可写的")
        return DiaryGenerateResponse(
            success=False,
            error="今天还没有对话记录，没什么可写的",
            logical_date=logical_date,
        )

    # 获取人格描述（读取 SOUL.md，同步文件 I/O 包装为 to_thread）
    personality = await asyncio.to_thread(_load_soul_content)

    # 获取用户名和 Agent 名
    user_name = current_user.username or current_user.nickname or "用户"
    agent_name = "Open-AwA"

    # 调用 LLM 生成日记
    try:
        content = await generate_diary_content(
            personality=personality,
            memory="",
            materials=materials,
            user_name=user_name,
            agent_name=agent_name,
            logical_date=logical_date,
        )
    except Exception as e:
        logger.bind(
            event="diary_generation_failed",
            module="diary",
            logical_date=logical_date,
            error=str(e),
        ).error(f"日记生成失败: {e}")
        raise HTTPException(status_code=500, detail="日记生成失败，请稍后重试")

    # 确定工作目录并保存日记（同步文件 I/O 包装为 to_thread）
    workspace_dir = os.getenv("WORKSPACE_DIR", os.getcwd())
    diary_dir = resolve_diary_dir(workspace_dir)
    result = await asyncio.to_thread(save_diary, diary_dir, logical_date, content)

    logger.bind(
        event="diary_generated",
        module="diary",
        logical_date=logical_date,
        file_path=result["file_path"],
    ).info("日记生成成功")

    return DiaryGenerateResponse(
        success=True,
        file_path=result["file_path"],
        content=result["content"],
        logical_date=result["logical_date"],
    )


@router.get(
    "/list",
    response_model=DiaryListResponse,
    summary="列出所有日记",
    description="返回所有已生成日记文件的列表。",
)
async def list_diary_entries(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """
    列出当前用户的所有已生成日记文件。
    """
    workspace_dir = os.getenv("WORKSPACE_DIR", os.getcwd())
    # 同步文件 I/O 包装为 to_thread，避免阻塞事件循环
    diaries = await asyncio.to_thread(list_diaries, workspace_dir)
    return DiaryListResponse(
        success=True,
        diaries=diaries,
        count=len(diaries),
    )


@router.get(
    "/{date}",
    response_model=DiaryReadResponse,
    summary="获取指定日期日记",
    description="按日期字符串（如 2026-05-16）读取对应的日记内容。",
)
async def get_diary(date: str, current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """
    获取当前用户指定日期的日记内容。
    日期格式：YYYY-MM-DD。
    """
    # 严格校验日期格式，防止任意字符串注入路径或绕过逻辑日期边界
    if not _DIARY_DATE_PATTERN.match(date):
        raise HTTPException(status_code=400, detail="日期格式非法，要求 YYYY-MM-DD")
    # 进一步校验真实日期有效性（如 2026-13-45 应被拒绝）
    try:
        from datetime import datetime as _dt
        _dt.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="日期无效，请提供真实存在的日期")

    workspace_dir = os.getenv("WORKSPACE_DIR", os.getcwd())
    # 同步文件 I/O 包装为 to_thread，避免阻塞事件循环
    content = await asyncio.to_thread(read_diary, workspace_dir, date)
    if content is None:
        raise HTTPException(status_code=404, detail=f"没有找到 {date} 的日记")
    return DiaryReadResponse(
        success=True,
        date=date,
        content=content,
    )


# ──────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────

def _load_soul_content() -> str:
    """
    读取项目根目录的 SOUL.md 文件，作为 Agent 人格描述。
    文件不存在时返回默认人格提示。
    """
    # 先尝试相对 backend 目录往上一级（项目根目录）
    possible_paths = [
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "SOUL.md"),
        os.path.join(os.getcwd(), "SOUL.md"),
        os.path.join(os.getenv("WORKSPACE_DIR", os.getcwd()), "SOUL.md"),
    ]
    for path in possible_paths:
        try:
            resolved = os.path.abspath(path)
            if os.path.isfile(resolved):
                with open(resolved, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        return content
        except OSError:
            continue

    # 默认人格描述
    return "你是一个善解人意的 AI 助手，正在写今天的私人日记。你喜欢用温暖、自然的语气表达自己。"

"""
P3 Chain-of-Thought 推理审计 API 路由模块。

提供：
- 问题复杂度评估（自动选择推理深度）
- 推理审计记录查询与统计
- 推理内容导出

路由前缀: /api/cot
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from api.schemas import (
    ComplexityAssessRequest,
    ComplexityAssessResponse,
    ReasoningAuditListResponse,
    ReasoningAuditResponse,
    ReasoningAuditStatsResponse,
    ReasoningExportResponse,
)
from core.cot_complexity import get_complexity_assessor
from core.reasoning_audit import get_audit_manager
from db.models import User, get_db


router = APIRouter(prefix="/api/cot", tags=["ChainOfThought"])


# -------- 复杂度评估 --------


@router.post("/complexity/assess", response_model=ComplexityAssessResponse)
async def assess_complexity(
    body: ComplexityAssessRequest,
    current_user: User = Depends(get_current_user),
):
    """
    评估用户输入的问题复杂度，返回推荐推理深度。

    评估依据：
    - 代码块/数学公式检测
    - 关键词匹配（编程/数学/逻辑等高复杂度关键词）
    - 输入长度
    - 问题类型（多问号、URL 等）

    用户可使用返回的 thinking_depth 作为 build_thinking_params 的输入，
    也可手动覆盖（0-5）。
    """
    assessor = get_complexity_assessor()
    result = assessor.assess(body.user_input)
    return ComplexityAssessResponse(**result)


# -------- 推理审计查询 --------


@router.get("/audits", response_model=ReasoningAuditListResponse)
async def list_reasoning_audits(
    session_id: Optional[str] = Query(None, description="筛选会话 ID"),
    user_id: Optional[str] = Query(None, description="筛选用户 ID"),
    complexity: Optional[str] = Query(None, description="筛选复杂度: simple/moderate/complex"),
    success: Optional[bool] = Query(None, description="筛选是否成功"),
    start_time: Optional[str] = Query(None, description="开始时间 ISO 格式"),
    end_time: Optional[str] = Query(None, description="结束时间 ISO 格式"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询推理审计记录列表，支持分页和多维度筛选。"""
    manager = get_audit_manager(db)

    start_dt = None
    end_dt = None
    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time)
        except ValueError:
            raise HTTPException(status_code=400, detail="start_time 格式无效")
    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time)
        except ValueError:
            raise HTTPException(status_code=400, detail="end_time 格式无效")

    result = manager.list_audits(
        session_id=session_id,
        user_id=user_id,
        complexity=complexity,
        success=success,
        start_time=start_dt,
        end_time=end_dt,
        page=page,
        page_size=page_size,
    )
    return ReasoningAuditListResponse(
        audits=[ReasoningAuditResponse(**a) for a in result["audits"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.get("/audits/{audit_id}", response_model=ReasoningAuditResponse)
async def get_reasoning_audit(
    audit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取指定推理审计记录详情。"""
    manager = get_audit_manager(db)
    audit = manager.get_audit(audit_id)
    if not audit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"审计记录 {audit_id} 不存在",
        )
    return ReasoningAuditResponse(**audit)


@router.get("/audits/stats", response_model=ReasoningAuditStatsResponse)
async def get_reasoning_audit_stats(
    user_id: Optional[str] = Query(None, description="筛选用户 ID"),
    start_time: Optional[str] = Query(None, description="开始时间 ISO 格式"),
    end_time: Optional[str] = Query(None, description="结束时间 ISO 格式"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取推理审计统计信息。"""
    manager = get_audit_manager(db)

    start_dt = None
    end_dt = None
    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time)
        except ValueError:
            raise HTTPException(status_code=400, detail="start_time 格式无效")
    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time)
        except ValueError:
            raise HTTPException(status_code=400, detail="end_time 格式无效")

    stats = manager.get_stats(
        user_id=user_id,
        start_time=start_dt,
        end_time=end_dt,
    )
    return ReasoningAuditStatsResponse(**stats)


# -------- 推理内容导出 --------


@router.get("/export/{session_id}", response_model=ReasoningExportResponse)
async def export_reasoning_content(
    session_id: str,
    format: str = Query("json", description="导出格式: json/markdown"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    导出指定会话的推理内容。

    关联 short_term_memory 表获取 reasoning_content 字段，
    同时关联 reasoning_audits 表获取审计元数据（复杂度、深度、耗时等）。
    """
    # 格式白名单校验，防止无效输入
    if format not in ("json", "markdown"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的导出格式: {format}，仅支持 json/markdown",
        )
    manager = get_audit_manager(db)
    result = manager.export_reasoning_content(session_id=session_id, format=format)
    return ReasoningExportResponse(**result)

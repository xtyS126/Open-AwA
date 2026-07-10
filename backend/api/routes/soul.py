"""
Soul Engine 相关 REST API。
提供用户画像的获取、编辑、探针管理和画像初始化功能。
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from loguru import logger

from api.dependencies import get_current_user, get_db
from config.settings import settings
from db.models import InterestProbe, User, UserProfileOverride
from soul.engine import SoulEngine

router = APIRouter(prefix="/api/soul", tags=["soul"])

# 全局 SoulEngine 实例（模块级缓存，后续可从 app.state 获取）
_soul_engine: Optional[SoulEngine] = None


def _get_soul_engine(request: Request) -> SoulEngine:
    """
    获取 SoulEngine 实例。
    优先从 app.state 获取，否则使用模块级缓存。
    """
    global _soul_engine
    engine = getattr(request.app.state, "soul_engine", None)
    if engine is not None:
        return engine
    if _soul_engine is None:
        _soul_engine = SoulEngine()
    return _soul_engine


# -------- Pydantic Schemas --------

class LayerDataResponse(BaseModel):
    """单层画像数据响应"""
    description: str = ""
    structured_data: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0


class ApiResponse(BaseModel):
    """统一 API 响应格式"""
    success: bool
    data: Any = None
    message: str = ""


class ProfileOverrideRequest(BaseModel):
    """画像覆盖层编辑请求"""
    layer_name: str = Field(..., description="层级名称：surface / interest / role / values / core")
    field: str = Field(..., description="字段名称：description / structured_data / confidence")
    value: Any = Field(..., description="覆盖值")


class ProbeResponse(BaseModel):
    """兴趣探针响应"""
    id: int
    user_id: str
    hypothesis: str
    reasoning: Optional[Dict[str, Any]] = None
    status: str
    probe_question: Optional[str] = None
    created_at: datetime
    responded_at: Optional[datetime] = None

    class Config:
        """Pydantic 配置：启用 ORM 模式，支持从数据库对象直接构建响应模型。"""
        from_attributes = True


class ProbeRespondRequest(BaseModel):
    """探针确认/拒绝请求"""
    probe_id: int = Field(..., description="探针 ID")
    response: str = Field(..., description="响应类型：confirmed 或 rejected")


# -------- 路由 --------

@router.get("/profile", response_model=ApiResponse)
async def get_profile(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    获取当前用户的五层画像（洋葱模型）。
    返回 surface / interest / role / values / core 五层数据。
    """
    engine = _get_soul_engine(request)
    profile = engine.get_profile(str(current_user.id), db)

    if profile is None:
        return ApiResponse(
            success=True,
            data=None,
            message="画像尚未建立",
        )

    return ApiResponse(
        success=True,
        data=profile.to_dict(),
        message="获取画像成功",
    )


@router.post("/profile/refresh", response_model=ApiResponse)
async def refresh_profile(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    内部接口：强制刷新用户画像。
    仅 AI 调用，用户不可主动触发。

    通过请求头 X-Internal-Token 或 API Key 鉴权（简化实现：仅校验当前登录用户，
    但前端不暴露此接口按钮）。
    """
    from plugins.user_profile_builtin.coordinator import get_coordinator

    user_id = str(current_user.id)
    coordinator = get_coordinator()
    result = await coordinator.maybe_extract(user_id, db, force=True)

    return ApiResponse(
        success=True,
        data=result,
        message="画像刷新已触发" if result else "画像刷新未触发（可能正在提取中）",
    )


@router.post("/overrides", response_model=ApiResponse)
async def save_overrides(
    override: ProfileOverrideRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    手动编辑画像覆盖层，保存到数据库。
    覆盖层优先级高于 AI 推断，实现"用户编辑 ⊕ AI 画像"的合并逻辑。
    """
    user_id = str(current_user.id)

    # 查找或创建覆盖层记录
    db_override = db.query(UserProfileOverride).filter(
        UserProfileOverride.user_id == user_id
    ).first()

    if db_override is None:
        db_override = UserProfileOverride(
            user_id=user_id,
            overrides={},
        )
        db.add(db_override)

    # 更新覆盖层
    overrides = dict(db_override.overrides) if db_override.overrides else {}
    if override.layer_name not in overrides:
        overrides[override.layer_name] = {}
    overrides[override.layer_name][override.field] = override.value
    db_override.overrides = overrides
    db_override.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(db_override)

    logger.bind(
        user_id=user_id,
        layer_name=override.layer_name,
        field=override.field,
    ).info("画像覆盖层已更新")

    return ApiResponse(
        success=True,
        data=db_override.overrides,
        message="覆盖层更新成功",
    )


@router.get("/probes", response_model=ApiResponse)
async def get_probes(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    获取当前用户待确认的兴趣探针。
    返回 status=pending 的探针列表，供前端展示苏格拉底式提问。
    """
    probes = db.query(InterestProbe).filter(
        InterestProbe.user_id == str(current_user.id),
        InterestProbe.status == "pending",
    ).order_by(InterestProbe.created_at.desc()).all()

    probe_responses = [ProbeResponse.model_validate(p) for p in probes]

    return ApiResponse(
        success=True,
        data=probe_responses,
        message=f"获取到 {len(probes)} 个待确认探针",
    )


@router.post("/probe/respond", response_model=ApiResponse)
async def respond_to_probe(
    req: ProbeRespondRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    确认或拒绝兴趣探针。
    确认后写入正式画像，拒绝后标记为已拒绝。
    """
    if req.response not in ("confirmed", "rejected"):
        raise HTTPException(status_code=400, detail="响应类型必须为 confirmed 或 rejected")

    probe = db.query(InterestProbe).filter(
        InterestProbe.id == req.probe_id,
        InterestProbe.user_id == str(current_user.id),
    ).first()

    if probe is None:
        raise HTTPException(status_code=404, detail="探针不存在或不属于当前用户")

    if probe.status != "pending":
        raise HTTPException(status_code=400, detail="该探针已被处理")

    probe.status = req.response
    probe.responded_at = datetime.now(timezone.utc)

    # 联动 ProfileFact：confirmed 提升置信度，rejected 标记失效
    # InterestProbe 无 fact_id 字段，从 reasoning JSON 提取
    reasoning = probe.reasoning or {}
    fact_id = reasoning.get("fact_id")
    if fact_id:
        from db.models import ProfileFact
        fact = db.query(ProfileFact).filter(
            ProfileFact.id == fact_id,
            ProfileFact.user_id == str(current_user.id),
        ).first()
        if fact:
            if req.response == "confirmed":
                # 用户确认后提升置信度至 0.9（接近明确声明）
                fact.confidence = 0.9
            elif req.response == "rejected":
                # 用户拒绝后标记事实为非活跃，不再参与画像推断
                fact.is_active = False

    db.commit()
    db.refresh(probe)

    logger.bind(
        user_id=str(current_user.id),
        probe_id=req.probe_id,
        response=req.response,
    ).info("探针已处理")

    return ApiResponse(
        success=True,
        data=ProbeResponse.model_validate(probe).model_dump(),
        message="探针已确认" if req.response == "confirmed" else "探针已拒绝",
    )


@router.post("/init", response_model=ApiResponse)
async def init_profile(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    初始化用户画像，创建空画像（如果尚未存在）。
    画像已存在时直接返回现有画像。
    """
    engine = _get_soul_engine(request)
    user_id = str(current_user.id)

    existing = engine.get_profile(user_id, db)
    if existing is not None:
        return ApiResponse(
            success=True,
            data=existing.to_dict(),
            message="画像已存在",
        )

    profile = engine.get_or_create_profile(user_id, db)

    logger.bind(user_id=user_id).info("用户画像已初始化")

    return ApiResponse(
        success=True,
        data=profile.to_dict(),
        message="画像初始化成功",
    )
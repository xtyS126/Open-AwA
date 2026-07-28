"""
Soul Engine 相关 REST API。
提供用户画像的获取、编辑、探针管理和画像初始化功能。
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
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


def clear_soul_engine_cache(user_id: str) -> None:
    """
    清除 SoulEngine 内存缓存中指定用户的画像（公共接口）。

    供 user_profile.py 的 CRUD 端点在桥接成功后调用，确保下次 GET /api/soul/profile
    从数据库重新加载最新画像，而非返回旧的内存缓存。

    Args:
        user_id: 用户 ID（字符串形式）
    """
    global _soul_engine
    # 优先清除模块级单例缓存（当前 main.py 未在 app.state 注册 soul_engine）
    if _soul_engine is not None:
        _soul_engine.clear_profile(user_id, db=None)


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

    # 桥接触发点：覆盖层变更后清除 SoulEngine 内存缓存
    # overrides 不修改 ProfileFact，无需重建 OnionProfile；
    # 但需清除内存缓存 _profiles，让下次 get_profile 重新从数据库
    # 加载原始 AI 画像并应用新覆盖层（Task 3 的 _apply_overrides 已实现）
    # 注意：传入 db=None 仅清除内存缓存，不删除数据库中的 OnionProfile 记录
    engine = _get_soul_engine(request)
    engine.clear_profile(user_id, db=None)

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
    user_id = str(current_user.id)

    # 延迟导入协调器与 ProfileFact，避免模块级循环依赖
    from db.models import ProfileFact
    from plugins.user_profile_builtin.coordinator import get_coordinator

    coordinator = get_coordinator()

    # 事务统一：探针响应（ProfileFact 修改）+ OnionProfile 桥接重建
    # 收敛到同一事务，commit=False 让 _persist_onion_profile 仅 flush 不 commit，
    # 由本端点统一 db.commit()；任一步骤失败则 db.rollback() 保证一致性
    try:
        # 增量重建所需的 changed_facts（仅在 ProfileFact 命中时构建）
        changed_facts: Optional[List[Dict[str, Any]]] = None

        if fact_id:
            fact = db.query(ProfileFact).filter(
                ProfileFact.id == fact_id,
                ProfileFact.user_id == user_id,
            ).first()
            if fact:
                if req.response == "confirmed":
                    # 用户确认后提升置信度至 0.9（接近明确声明）
                    fact.confidence = 0.9
                    # 增量重建：fact 被更新，action=update
                    changed_facts = [{
                        "category": fact.category,
                        "fact_key": fact.fact_key,
                        "fact_value": fact.fact_value,
                        "action": "update",
                    }]
                elif req.response == "rejected":
                    # 用户拒绝后标记事实为非活跃，不再参与画像推断
                    fact.is_active = False
                    # 增量重建：fact 被软删（is_active=False），action=delete
                    changed_facts = [{
                        "category": fact.category,
                        "fact_key": fact.fact_key,
                        "fact_value": fact.fact_value,
                        "action": "delete",
                    }]

        # 桥接 ProfileFact → OnionProfile 增量重建
        # commit=False：与探针响应收敛到同一事务，由本端点统一 commit/rollback
        # changed_facts 为 None 时（未命中 fact_id）跳过桥接，不影响探针响应主流程
        if changed_facts is not None:
            coordinator._persist_onion_profile(
                db, user_id, changed_facts=changed_facts, commit=False
            )

        db.commit()
        db.refresh(probe)
        # 清除 SoulEngine 内存缓存，确保下次 GET /api/soul/profile 读取最新画像
        clear_soul_engine_cache(user_id)
    except SQLAlchemyError as exc:
        # 数据库异常：回滚事务，保证 ProfileFact 与 OnionProfile 一致性
        logger.bind(
            user_id=user_id,
            probe_id=req.probe_id,
            response=req.response,
        ).opt(exception=True).error(f"探针响应事务失败(数据库错误)，已回滚: {exc}")
        db.rollback()
        raise HTTPException(status_code=500, detail="探针响应处理失败")
    except Exception as exc:
        # 兜底捕获：不静默吞异常，记录完整堆栈后回滚
        logger.bind(
            user_id=user_id,
            probe_id=req.probe_id,
            response=req.response,
        ).opt(exception=True).error(f"探针响应处理失败，已回滚: {exc}")
        db.rollback()
        raise HTTPException(status_code=500, detail="探针响应处理失败")

    logger.bind(
        user_id=user_id,
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
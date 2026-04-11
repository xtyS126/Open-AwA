"""
微信绑定管理路由，负责微信绑定状态的增删改查及连接参数配置。
与 skills.py 中的扫码登录路由配合使用，提供完整的微信集成管理能力。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from loguru import logger

from db.models import get_db, WeixinBinding
from api.dependencies import get_current_user
from config.settings import settings


router = APIRouter(prefix="/api/weixin", tags=["Weixin"])


class WeixinBindingResponse(BaseModel):
    """微信绑定状态响应模型"""
    id: Optional[int] = None
    user_id: str = ""
    weixin_account_id: str = ""
    base_url: str = ""
    bot_type: str = ""
    channel_version: str = ""
    binding_status: str = "unbound"
    weixin_user_id: str = ""

    class Config:
        from_attributes = True


class WeixinBindingCreate(BaseModel):
    """创建或更新微信绑定的请求模型"""
    weixin_account_id: str
    token: str
    base_url: Optional[str] = None
    bot_type: Optional[str] = None
    channel_version: Optional[str] = None
    binding_status: Optional[str] = "bound"
    weixin_user_id: Optional[str] = ""


class WeixinConfigUpdate(BaseModel):
    """更新微信连接参数的请求模型"""
    bot_type: Optional[str] = None
    channel_version: Optional[str] = None
    base_url: Optional[str] = None


class WeixinConfigResponse(BaseModel):
    """微信连接参数响应模型"""
    base_url: str = ""
    bot_type: str = ""
    channel_version: str = ""
    weixin_default_base_url: str = ""
    weixin_default_bot_type: str = ""
    weixin_default_channel_version: str = ""
    session_timeout_seconds: int = 3600
    token_refresh_enabled: bool = True


@router.get("/binding", response_model=WeixinBindingResponse)
async def get_binding(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """获取当前用户的微信绑定状态"""
    binding = db.query(WeixinBinding).filter(
        WeixinBinding.user_id == str(current_user.id)
    ).first()
    if not binding:
        return WeixinBindingResponse(user_id=str(current_user.id))
    return WeixinBindingResponse(
        id=binding.id,
        user_id=binding.user_id,
        weixin_account_id=binding.weixin_account_id or "",
        base_url=binding.base_url or "",
        bot_type=binding.bot_type or "",
        channel_version=binding.channel_version or "",
        binding_status=binding.binding_status or "unbound",
        weixin_user_id=binding.weixin_user_id or "",
    )


@router.post("/binding", response_model=WeixinBindingResponse)
async def save_binding(
    payload: WeixinBindingCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """保存或更新当前用户的微信绑定信息"""
    user_id = str(current_user.id)
    binding = db.query(WeixinBinding).filter(
        WeixinBinding.user_id == user_id
    ).first()
    effective_base_url = payload.base_url or settings.WEIXIN_DEFAULT_BASE_URL
    effective_bot_type = payload.bot_type or settings.WEIXIN_DEFAULT_BOT_TYPE
    effective_channel_version = payload.channel_version or settings.WEIXIN_DEFAULT_CHANNEL_VERSION

    if binding:
        binding.weixin_account_id = payload.weixin_account_id
        binding.token = payload.token
        binding.base_url = effective_base_url
        binding.bot_type = effective_bot_type
        binding.channel_version = effective_channel_version
        binding.binding_status = payload.binding_status or "bound"
        binding.weixin_user_id = payload.weixin_user_id or ""
    else:
        binding = WeixinBinding(
            user_id=user_id,
            weixin_account_id=payload.weixin_account_id,
            token=payload.token,
            base_url=effective_base_url,
            bot_type=effective_bot_type,
            channel_version=effective_channel_version,
            binding_status=payload.binding_status or "bound",
            weixin_user_id=payload.weixin_user_id or "",
        )
        db.add(binding)
    db.commit()
    db.refresh(binding)
    logger.info(f"[weixin] 用户 {user_id} 绑定已保存, account_id={payload.weixin_account_id}, status={binding.binding_status}")
    return WeixinBindingResponse(
        id=binding.id,
        user_id=binding.user_id,
        weixin_account_id=binding.weixin_account_id or "",
        base_url=binding.base_url or "",
        bot_type=binding.bot_type or "",
        channel_version=binding.channel_version or "",
        binding_status=binding.binding_status or "unbound",
        weixin_user_id=binding.weixin_user_id or "",
    )


@router.delete("/binding")
async def delete_binding(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """解除当前用户的微信绑定"""
    user_id = str(current_user.id)
    binding = db.query(WeixinBinding).filter(
        WeixinBinding.user_id == user_id
    ).first()
    if not binding:
        raise HTTPException(status_code=404, detail="未找到微信绑定记录")
    db.delete(binding)
    db.commit()
    logger.info(f"[weixin] 用户 {user_id} 已解除微信绑定")
    return {"message": "微信绑定已解除"}


@router.get("/config", response_model=WeixinConfigResponse)
async def get_weixin_params(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """获取当前用户的微信连接参数，合并绑定记录与全局默认值"""
    binding = db.query(WeixinBinding).filter(
        WeixinBinding.user_id == str(current_user.id)
    ).first()
    return WeixinConfigResponse(
        base_url=(binding.base_url if binding else "") or settings.WEIXIN_DEFAULT_BASE_URL,
        bot_type=(binding.bot_type if binding else "") or settings.WEIXIN_DEFAULT_BOT_TYPE,
        channel_version=(binding.channel_version if binding else "") or settings.WEIXIN_DEFAULT_CHANNEL_VERSION,
        weixin_default_base_url=settings.WEIXIN_DEFAULT_BASE_URL,
        weixin_default_bot_type=settings.WEIXIN_DEFAULT_BOT_TYPE,
        weixin_default_channel_version=settings.WEIXIN_DEFAULT_CHANNEL_VERSION,
        session_timeout_seconds=settings.WEIXIN_SESSION_TIMEOUT_SECONDS,
        token_refresh_enabled=settings.WEIXIN_TOKEN_REFRESH_ENABLED,
    )


@router.put("/config", response_model=WeixinConfigResponse)
async def update_weixin_params(
    payload: WeixinConfigUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """更新当前用户的微信连接参数（bot_type, channel_version, base_url）"""
    user_id = str(current_user.id)
    binding = db.query(WeixinBinding).filter(
        WeixinBinding.user_id == user_id
    ).first()
    if not binding:
        raise HTTPException(status_code=404, detail="请先绑定微信账号后再修改连接参数")
    if payload.bot_type is not None:
        binding.bot_type = payload.bot_type
    if payload.channel_version is not None:
        binding.channel_version = payload.channel_version
    if payload.base_url is not None:
        binding.base_url = payload.base_url
    db.commit()
    db.refresh(binding)
    logger.info(f"[weixin] 用户 {user_id} 连接参数已更新, bot_type={binding.bot_type}, channel_version={binding.channel_version}")
    return WeixinConfigResponse(
        base_url=binding.base_url or settings.WEIXIN_DEFAULT_BASE_URL,
        bot_type=binding.bot_type or settings.WEIXIN_DEFAULT_BOT_TYPE,
        channel_version=binding.channel_version or settings.WEIXIN_DEFAULT_CHANNEL_VERSION,
        weixin_default_base_url=settings.WEIXIN_DEFAULT_BASE_URL,
        weixin_default_bot_type=settings.WEIXIN_DEFAULT_BOT_TYPE,
        weixin_default_channel_version=settings.WEIXIN_DEFAULT_CHANNEL_VERSION,
        session_timeout_seconds=settings.WEIXIN_SESSION_TIMEOUT_SECONDS,
        token_refresh_enabled=settings.WEIXIN_TOKEN_REFRESH_ENABLED,
    )

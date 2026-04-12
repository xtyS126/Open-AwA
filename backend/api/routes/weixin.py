"""
微信绑定管理路由，负责微信绑定状态的增删改查及连接参数配置。
与 skills.py 中的扫码登录路由配合使用，提供完整的微信集成管理能力。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from api.services.weixin_auto_reply import WeixinAutoReplyService
from config.security import decrypt_secret_value, encrypt_secret_value
from config.settings import settings
from db.models import WeixinBinding, get_db
from skills.weixin_skill_adapter import WeixinSkillAdapter


router = APIRouter(prefix="/api/weixin", tags=["Weixin"])
_AUTO_REPLY_MANAGER = WeixinAutoReplyService()


def _get_auto_reply_manager() -> WeixinAutoReplyService:
    """集中管理自动回复单例，便于测试时替换。"""
    return _AUTO_REPLY_MANAGER


class WeixinBindingResponse(BaseModel):
    """微信绑定状态响应模型"""
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    user_id: str = ""
    weixin_account_id: str = ""
    base_url: str = ""
    bot_type: str = ""
    channel_version: str = ""
    binding_status: str = "unbound"
    weixin_user_id: str = ""


class WeixinBindingCreate(BaseModel):
    """创建或更新微信绑定的请求模型"""
    model_config = ConfigDict(str_strip_whitespace=True)

    weixin_account_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    token: str = Field(..., min_length=8, max_length=512)
    base_url: Optional[str] = Field(default=None, max_length=512)
    bot_type: Optional[str] = Field(default=None, max_length=32)
    channel_version: Optional[str] = Field(default=None, max_length=32)
    binding_status: Optional[str] = "bound"
    weixin_user_id: Optional[str] = Field(default="", max_length=128)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: Optional[str]) -> Optional[str]:
        if value in {None, ""}:
            return value
        normalized = str(value).strip()
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("base_url 必须以 http:// 或 https:// 开头")
        return normalized.rstrip("/")


class WeixinConfigUpdate(BaseModel):
    """更新微信连接参数的请求模型"""
    model_config = ConfigDict(str_strip_whitespace=True)

    bot_type: Optional[str] = Field(default=None, max_length=32)
    channel_version: Optional[str] = Field(default=None, max_length=32)
    base_url: Optional[str] = Field(default=None, max_length=512)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: Optional[str]) -> Optional[str]:
        if value in {None, ""}:
            return value
        normalized = str(value).strip()
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("base_url 必须以 http:// 或 https:// 开头")
        return normalized.rstrip("/")


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
    adapter = WeixinSkillAdapter()
    binding = db.query(WeixinBinding).filter(
        WeixinBinding.user_id == user_id
    ).first()
    previous_account_id = binding.weixin_account_id if binding else ""
    effective_base_url = payload.base_url or settings.WEIXIN_DEFAULT_BASE_URL
    effective_bot_type = payload.bot_type or settings.WEIXIN_DEFAULT_BOT_TYPE
    effective_channel_version = payload.channel_version or settings.WEIXIN_DEFAULT_CHANNEL_VERSION

    if binding:
        binding.weixin_account_id = payload.weixin_account_id
        binding.token = encrypt_secret_value(payload.token)
        binding.base_url = effective_base_url
        binding.bot_type = effective_bot_type
        binding.channel_version = effective_channel_version
        binding.binding_status = payload.binding_status or "bound"
        binding.weixin_user_id = payload.weixin_user_id or ""
    else:
        binding = WeixinBinding(
            user_id=user_id,
            weixin_account_id=payload.weixin_account_id,
            token=encrypt_secret_value(payload.token),
            base_url=effective_base_url,
            bot_type=effective_bot_type,
            channel_version=effective_channel_version,
            binding_status=payload.binding_status or "bound",
            weixin_user_id=payload.weixin_user_id or "",
        )
        db.add(binding)
    db.commit()
    db.refresh(binding)
    if previous_account_id and previous_account_id != binding.weixin_account_id:
        # 账号切换后必须清理旧账号的游标和幂等状态，避免把历史消息带到新账号。
        adapter.clear_account_state(previous_account_id)
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
    adapter = WeixinSkillAdapter()
    manager = _get_auto_reply_manager()
    binding = db.query(WeixinBinding).filter(
        WeixinBinding.user_id == user_id
    ).first()
    if not binding:
        raise HTTPException(status_code=404, detail="未找到微信绑定记录")
    account_id = binding.weixin_account_id or ""
    db.delete(binding)
    db.commit()
    await manager.stop(user_id)
    if account_id:
        adapter.clear_account_state(account_id)
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


@router.get("/auto-reply/status")
async def get_auto_reply_status(current_user=Depends(get_current_user)):
    """获取当前用户微信自动回复运行状态。"""
    manager = _get_auto_reply_manager()
    return manager.get_status(str(current_user.id))


@router.post("/auto-reply/start")
async def start_auto_reply(current_user=Depends(get_current_user)):
    """启动当前用户的微信自动回复后台轮询。"""
    manager = _get_auto_reply_manager()
    try:
        return await manager.start(str(current_user.id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/auto-reply/stop")
async def stop_auto_reply(current_user=Depends(get_current_user)):
    """停止当前用户的微信自动回复后台轮询。"""
    manager = _get_auto_reply_manager()
    return await manager.stop(str(current_user.id))


@router.post("/auto-reply/restart")
async def restart_auto_reply(current_user=Depends(get_current_user)):
    """重启当前用户的微信自动回复后台轮询。"""
    manager = _get_auto_reply_manager()
    try:
        return await manager.restart(str(current_user.id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/auto-reply/process-once")
async def process_auto_reply_once(current_user=Depends(get_current_user)):
    """
    手动执行一次轮询，便于诊断、测试和观察最近一次处理结果。
    """
    manager = _get_auto_reply_manager()
    try:
        return await manager.process_once(str(current_user.id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

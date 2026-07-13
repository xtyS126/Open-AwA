"""
微信绑定管理路由，负责微信绑定状态的增删改查及连接参数配置。
与 skills.py 中的扫码登录路由配合使用，提供完整的微信集成管理能力。

v2: 新增微信对话历史查询端点，实现跨渠道上下文可视化。
v3: 新增 WebSocket 实时消息推送端点与多媒体消息查询接口。
"""

import asyncio
import json
import os
import re
import tempfile
import httpx
from pathlib import Path
from typing import Any, Dict, Optional, List
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from api.security.ws_auth import extract_token_from_subprotocol, validate_ws_origin
from api.services.weixin_auto_reply import (
    WeixinAutoReplyService,
    get_auto_reply_manager,
    get_event_bus,
    _AUTO_REPLY_MANAGER,
    DEFAULT_CROSS_CHANNEL_CONTEXT_TURNS,
)
from config.security import decode_access_token, decrypt_secret_value, encrypt_secret_value
from config.settings import settings
from db.models import ModelConfiguration, ProviderCredential, SessionLocal, ShortTermMemory, Skill, User, WeixinBinding, WeixinAutoReplyRule, WeixinMediaAsset, get_db
from core.weixin_utils import (
    normalize_binding_status as _normalize_binding_status,
    deserialize_skill_config as _deserialize_skill_config,
)
from skills.weixin_skill_adapter import (
    WeixinAdapterError,
    WeixinRuntimeConfig,
    WeixinSkillAdapter,
    load_binding as _load_weixin_binding,
)


router = APIRouter(prefix="/api/weixin", tags=["Weixin"])
_WEIXIN_SKILL_NAME = "weixin_dispatch"

# 多媒体上传安全配置
_MULTIMEDIA_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
_MULTIMEDIA_ALLOWED_MIME_TYPES: Dict[str, str] = {
    "image/jpeg": "image",
    "image/png": "image",
    "image/gif": "image",
    "audio/amr": "voice",
    "audio/mp3": "voice",
    "audio/mpeg": "voice",
    "video/mp4": "video",
    "application/pdf": "file",
}
_MULTIMEDIA_ALLOWED_MEDIA_TYPES = {"image", "voice", "video", "file"}


def _parse_multimedia_metadata(content: str) -> Dict[str, Any]:
    """
    从多媒体消息文本描述中解析元数据字段。

    build_multimedia_description 生成的文本格式示例：
    - [图片消息] URL: https://... 格式: jpg
    - [语音消息] 时长: 3000 毫秒 格式: amr
    - [文件消息] 文件名: doc.pdf 大小: 2048 字节
    - [视频消息] URL: https://... 时长: 10000 毫秒 格式: mp4

    返回字典包含 media_id/file_url/file_name/file_size/duration_ms/media_format，
    无法解析的字段保持空值。
    """
    result: Dict[str, Any] = {
        "media_id": "",
        "file_url": "",
        "file_name": "",
        "file_size": 0,
        "duration_ms": 0,
        "media_format": "",
    }
    if not content:
        return result

    url_match = re.search(r"URL:\s*(\S+)", content)
    if url_match:
        result["file_url"] = url_match.group(1)

    name_match = re.search(r"文件名:\s*(\S+)", content)
    if name_match:
        result["file_name"] = name_match.group(1)

    size_match = re.search(r"大小:\s*(\d+)\s*字节", content)
    if size_match:
        try:
            result["file_size"] = int(size_match.group(1))
        except ValueError:
            result["file_size"] = 0

    duration_match = re.search(r"时长:\s*(\d+)\s*毫秒", content)
    if duration_match:
        try:
            result["duration_ms"] = int(duration_match.group(1))
        except ValueError:
            result["duration_ms"] = 0

    format_match = re.search(r"格式:\s*(\S+)", content)
    if format_match:
        result["media_format"] = format_match.group(1)

    media_id_match = re.search(r"media_id[:\s]+(\S+)", content, re.IGNORECASE)
    if media_id_match:
        result["media_id"] = media_id_match.group(1)

    return result


def _sanitize_upload_filename(filename: str) -> str:
    """
    清理上传文件名，防止路径穿越攻击。
    仅保留文件名部分，移除目录分隔符和特殊字符。
    """
    if not filename:
        return "upload.bin"
    # 取 basename 防止路径穿越
    safe_name = os.path.basename(filename)
    # 移除潜在的危险字符
    safe_name = re.sub(r"[^\w.\-]", "_", safe_name)
    if not safe_name or safe_name in {".", ".."}:
        return "upload.bin"
    return safe_name


def _recover_binding_from_skill_config(db: Session, app_user_id: str) -> Optional[WeixinBinding]:
    """兼容历史数据：当 weixin_bindings 缺失时，尝试从 skills.weixin 配置回填。"""
    skill = db.query(Skill).filter(Skill.name == _WEIXIN_SKILL_NAME).first()
    if not skill:
        return None

    config = _deserialize_skill_config(skill.config)
    weixin_config = config.get("weixin", {}) if isinstance(config.get("weixin"), dict) else {}

    account_id = str(weixin_config.get("account_id") or "").strip()
    token = decrypt_secret_value(str(weixin_config.get("token") or "")).strip()
    base_url = str(weixin_config.get("base_url") or settings.WEIXIN_DEFAULT_BASE_URL).strip() or settings.WEIXIN_DEFAULT_BASE_URL
    bot_type = str(weixin_config.get("bot_type") or settings.WEIXIN_DEFAULT_BOT_TYPE).strip() or settings.WEIXIN_DEFAULT_BOT_TYPE
    channel_version = str(weixin_config.get("channel_version") or settings.WEIXIN_DEFAULT_CHANNEL_VERSION).strip() or settings.WEIXIN_DEFAULT_CHANNEL_VERSION
    weixin_user_id = str(weixin_config.get("user_id") or "").strip()
    binding_status = _normalize_binding_status(weixin_config.get("binding_status"), weixin_user_id)

    if not account_id or not token:
        return None

    binding = WeixinBinding(
        user_id=app_user_id,
        weixin_account_id=account_id,
        token=encrypt_secret_value(token),
        base_url=base_url,
        bot_type=bot_type,
        channel_version=channel_version,
        binding_status=binding_status,
        weixin_user_id=weixin_user_id,
    )
    db.add(binding)
    db.commit()
    db.refresh(binding)
    logger.info(f"[weixin] 用户 {app_user_id} 的绑定记录已从 skills 配置自动恢复")
    return binding


def _ensure_binding_exists(db: Session, app_user_id: str) -> Optional[WeixinBinding]:
    binding = db.query(WeixinBinding).filter(WeixinBinding.user_id == app_user_id).first()
    if binding:
        return binding
    return _recover_binding_from_skill_config(db, app_user_id)


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
    auto_start_reply: Optional[bool] = None

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
    auto_start_reply: bool = False


@router.get("/binding", response_model=WeixinBindingResponse)
async def get_binding(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """获取当前用户的微信绑定状态"""
    binding = _ensure_binding_exists(db, str(current_user.id))
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
) -> Dict[str, Any]:
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
) -> Dict[str, Any]:
    """解除当前用户的微信绑定"""
    user_id = str(current_user.id)
    adapter = WeixinSkillAdapter()
    manager = get_auto_reply_manager()
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
) -> Dict[str, Any]:
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
) -> Dict[str, Any]:
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
    if payload.auto_start_reply is not None:
        binding.auto_start_reply = payload.auto_start_reply
    db.commit()
    db.refresh(binding)
    logger.info(f"[weixin] 用户 {user_id} 连接参数已更新, bot_type={binding.bot_type}, channel_version={binding.channel_version}, auto_start_reply={binding.auto_start_reply}")
    return WeixinConfigResponse(
        base_url=binding.base_url or settings.WEIXIN_DEFAULT_BASE_URL,
        bot_type=binding.bot_type or settings.WEIXIN_DEFAULT_BOT_TYPE,
        channel_version=binding.channel_version or settings.WEIXIN_DEFAULT_CHANNEL_VERSION,
        weixin_default_base_url=settings.WEIXIN_DEFAULT_BASE_URL,
        weixin_default_bot_type=settings.WEIXIN_DEFAULT_BOT_TYPE,
        weixin_default_channel_version=settings.WEIXIN_DEFAULT_CHANNEL_VERSION,
        session_timeout_seconds=settings.WEIXIN_SESSION_TIMEOUT_SECONDS,
        token_refresh_enabled=settings.WEIXIN_TOKEN_REFRESH_ENABLED,
        auto_start_reply=binding.auto_start_reply,
    )


@router.get("/auto-reply/status")
async def get_auto_reply_status(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """获取当前用户微信自动回复运行状态。"""
    _ensure_binding_exists(db, str(current_user.id))
    manager = get_auto_reply_manager()
    return manager.get_status(str(current_user.id))


@router.post("/auto-reply/start")
async def start_auto_reply(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """启动当前用户的微信自动回复后台轮询。"""
    _ensure_binding_exists(db, str(current_user.id))
    manager = get_auto_reply_manager()
    try:
        return await manager.start(str(current_user.id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/auto-reply/stop")
async def stop_auto_reply(current_user=Depends(get_current_user)) -> Dict[str, Any]:
    """停止当前用户的微信自动回复后台轮询。"""
    manager = get_auto_reply_manager()
    return await manager.stop(str(current_user.id))


@router.post("/auto-reply/restart")
async def restart_auto_reply(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """重启当前用户的微信自动回复后台轮询。"""
    _ensure_binding_exists(db, str(current_user.id))
    manager = get_auto_reply_manager()
    try:
        return await manager.restart(str(current_user.id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/auto-reply/process-once")
async def process_auto_reply_once(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """
    手动执行一次轮询，便于诊断、测试和观察最近一次处理结果。
    """
    _ensure_binding_exists(db, str(current_user.id))
    manager = get_auto_reply_manager()
    try:
        return await manager.process_once(str(current_user.id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/auto-reply/diagnostics")
async def get_auto_reply_diagnostics(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """
    返回自动回复诊断信息：绑定状态、回调地址有效性、adapter 健康检查。
    """
    user_id = str(current_user.id)
    binding = db.query(WeixinBinding).filter(
        WeixinBinding.user_id == user_id
    ).first()

    if not binding:
        return {
            "binding_valid": False,
            "binding_status": "unbound",
            "callback_reachable": False,
            "health_check": None,
            "diagnostics_message": "未找到微信绑定记录，请先完成绑定",
        }

    adapter = WeixinSkillAdapter()
    from skills.weixin_skill_adapter import load_binding as _load_binding
    runtime = _load_binding(db, user_id)
    health = adapter.check_health(runtime) if runtime else {"ok": False, "issues": ["runtime 加载失败"]}

    return {
        "binding_valid": bool(binding.weixin_account_id and binding.token),
        "binding_status": binding.binding_status or "unknown",
        "account_id": binding.weixin_account_id or "",
        "base_url": binding.base_url or "",
        "callback_reachable": health.get("ok", False),
        "health_check": health,
        "diagnostics_message": "诊断完成" if health.get("ok") else "检测到配置问题，请查看 health_check 详情",
    }


class WeixinAutoReplyRuleCreate(BaseModel):
    """创建微信自动回复规则的请求模型"""
    rule_name: str = Field(..., min_length=1, max_length=100)
    match_type: str = Field(default="keyword", pattern=r"^(keyword|regex)$")
    match_pattern: str = Field(..., min_length=1, max_length=500)
    reply_content: str = Field(..., min_length=1, max_length=4000)
    is_active: bool = Field(default=True)
    priority: int = Field(default=0)


class WeixinAutoReplyRuleUpdate(BaseModel):
    """更新微信自动回复规则的请求模型"""
    rule_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    match_type: Optional[str] = Field(default=None, pattern=r"^(keyword|regex)$")
    match_pattern: Optional[str] = Field(default=None, min_length=1, max_length=500)
    reply_content: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    is_active: Optional[bool] = None
    priority: Optional[int] = None


class WeixinAutoReplyRuleResponse(BaseModel):
    """微信自动回复规则响应模型"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    rule_name: str
    match_type: str
    match_pattern: str
    reply_content: str
    is_active: bool
    priority: int
    created_at: datetime
    updated_at: datetime


@router.get("/auto-reply/rules", response_model=List[WeixinAutoReplyRuleResponse])
async def list_auto_reply_rules(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """获取当前用户的所有微信自动回复规则"""
    rules = db.query(WeixinAutoReplyRule).filter(
        WeixinAutoReplyRule.user_id == str(current_user.id)
    ).order_by(WeixinAutoReplyRule.priority.desc(), WeixinAutoReplyRule.created_at.desc()).all()
    return rules


@router.post("/auto-reply/rules", response_model=WeixinAutoReplyRuleResponse)
async def create_auto_reply_rule(
    payload: WeixinAutoReplyRuleCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """创建新的微信自动回复规则"""
    rule = WeixinAutoReplyRule(
        user_id=str(current_user.id),
        rule_name=payload.rule_name,
        match_type=payload.match_type,
        match_pattern=payload.match_pattern,
        reply_content=payload.reply_content,
        is_active=payload.is_active,
        priority=payload.priority,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/auto-reply/rules/{rule_id}", response_model=WeixinAutoReplyRuleResponse)
async def update_auto_reply_rule(
    rule_id: int,
    payload: WeixinAutoReplyRuleUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """更新微信自动回复规则"""
    rule = db.query(WeixinAutoReplyRule).filter(
        WeixinAutoReplyRule.id == rule_id,
        WeixinAutoReplyRule.user_id == str(current_user.id)
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="未找到该规则")

    if payload.rule_name is not None:
        rule.rule_name = payload.rule_name
    if payload.match_type is not None:
        rule.match_type = payload.match_type
    if payload.match_pattern is not None:
        rule.match_pattern = payload.match_pattern
    if payload.reply_content is not None:
        rule.reply_content = payload.reply_content
    if payload.is_active is not None:
        rule.is_active = payload.is_active
    if payload.priority is not None:
        rule.priority = payload.priority

    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/auto-reply/rules/{rule_id}")
async def delete_auto_reply_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """删除微信自动回复规则"""
    rule = db.query(WeixinAutoReplyRule).filter(
        WeixinAutoReplyRule.id == rule_id,
        WeixinAutoReplyRule.user_id == str(current_user.id)
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="未找到该规则")

    db.delete(rule)
    db.commit()
    return {"message": "规则已删除"}


# ──────────────────────────────────────────────
#  跨渠道对话上下文 API
# ──────────────────────────────────────────────

class WeixinConversationSummary(BaseModel):
    """微信对话会话摘要"""
    session_id: str
    from_user_id: str = ""
    weixin_account_id: str = ""
    last_message: str = ""
    last_message_at: str = ""
    total_turns: int = 0
    unread_count: int = 0


class WeixinConversationMessage(BaseModel):
    """微信对话消息"""
    role: str
    content: str
    timestamp: str = ""


@router.get("/conversations", response_model=List[WeixinConversationSummary])
async def list_weixin_conversations(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100),
) -> Dict[str, Any]:
    """
    列出当前用户的所有微信对话会话摘要。
    聚合 ShortTermMemory 中 weixin:auto: 前缀的 session，按最近活跃排序。
    """
    user_id = str(current_user.id)
    try:
        # 查询所有微信渠道的短时记忆记录
        all_sessions = (
            db.query(ShortTermMemory)
            .filter(
                ShortTermMemory.session_id.like("weixin:auto:%"),
                ShortTermMemory.workspace_id == "default",
            )
            .order_by(ShortTermMemory.timestamp.desc())
            .limit(limit * 50)
            .all()
        )
    except Exception as exc:
        logger.warning(f"[weixin] 查询微信会话列表失败，降级返回空列表：{exc}", exc_info=exc)
        return []

    # 按 session_id 聚合
    sessions: Dict[str, Dict[str, Any]] = {}
    for mem in all_sessions:
        sid = mem.session_id or ""
        if sid not in sessions:
            # 解析 session_id: weixin:auto:{account_id}:{from_user_id}
            parts = sid.replace("weixin:auto:", "").split(":", 1)
            sessions[sid] = {
                "session_id": sid,
                "weixin_account_id": parts[0] if len(parts) > 0 else "",
                "from_user_id": parts[1] if len(parts) > 1 else "",
                "last_message": str(mem.content or "")[:120],
                "last_message_at": (mem.timestamp.isoformat() if mem.timestamp else ""),
                "total_turns": 0,
                "unread_count": 0,
            }
        sessions[sid]["total_turns"] += 1

    return [
        WeixinConversationSummary(**summary)
        for summary in list(sessions.values())[:limit]
    ]


@router.get("/conversations/{session_id:path}", response_model=List[WeixinConversationMessage])
async def get_weixin_conversation(
    session_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=200),
) -> Dict[str, Any]:
    """
    获取指定微信对话会话的完整消息历史。

    session_id 格式: weixin:auto:{account_id}:{from_user_id}
    """
    if not session_id.startswith("weixin:auto:"):
        raise HTTPException(status_code=400, detail="无效的微信会话 ID")

    try:
        messages = (
            db.query(ShortTermMemory)
            .filter(
                ShortTermMemory.session_id == session_id,
                ShortTermMemory.workspace_id == "default",
            )
            .order_by(ShortTermMemory.timestamp.asc())
            .limit(limit)
            .all()
        )
    except Exception as exc:
        logger.error(f"[weixin] 查询对话历史失败: {exc}")
        raise HTTPException(status_code=500, detail="查询对话历史失败")

    return [
        WeixinConversationMessage(
            role=mem.role or "unknown",
            content=str(mem.content or "")[:1000],
            timestamp=mem.timestamp.isoformat() if mem.timestamp else "",
        )
        for mem in messages
    ]


@router.get("/cross-channel/context")
async def get_cross_channel_context(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    limit: int = Query(default=DEFAULT_CROSS_CHANNEL_CONTEXT_TURNS, ge=1, le=50),
) -> Dict[str, Any]:
    """
    获取跨渠道上下文预览：主用户 Web UI 最近对话 + 所有微信对话会话列表。
    用于诊断和可视化 AI 在生成微信回复时的上下文来源。
    """
    user_id = str(current_user.id)
    manager = get_auto_reply_manager()

    # 主用户 Web UI 最近对话（排除微信渠道）
    web_conversations = manager._load_main_user_recent_conversations(db, user_id, max_turns=limit)

    # 微信对话会话列表
    try:
        weixin_memories = (
            db.query(ShortTermMemory)
            .filter(
                ShortTermMemory.session_id.like("weixin:auto:%"),
                ShortTermMemory.workspace_id == "default",
            )
            .order_by(ShortTermMemory.timestamp.desc())
            .limit(limit * 20)
            .all()
        )
    except Exception as exc:
        logger.warning(f"[weixin] 查询微信记忆失败，降级为空列表：{exc}", exc_info=exc)
        weixin_memories = []

    weixin_sessions: Dict[str, Dict[str, Any]] = {}
    for mem in weixin_memories:
        sid = mem.session_id or ""
        if sid not in weixin_sessions:
            parts = sid.replace("weixin:auto:", "").split(":", 1)
            weixin_sessions[sid] = {
                "session_id": sid,
                "from_user_id": parts[1] if len(parts) > 1 else "",
                "last_message": str(mem.content or "")[:120],
                "last_at": mem.timestamp.isoformat() if mem.timestamp else "",
                "message_count": 0,
            }
        weixin_sessions[sid]["message_count"] += 1

    return {
        "user_id": user_id,
        "web_context_turns": len(web_conversations),
        "web_context": [
            {"role": msg["role"], "preview": str(msg["content"])[:200]}
            for msg in web_conversations[-10:]
        ],
        "weixin_sessions_count": len(weixin_sessions),
        "weixin_sessions": list(weixin_sessions.values())[:limit],
    }


# ──────────────────────────────────────────────
#  多媒体消息查询
# ──────────────────────────────────────────────

class WeixinMultimediaMessageResponse(BaseModel):
    """微信多媒体消息响应模型"""
    message_id: str = ""
    from_user_id: str = ""
    message_type: str = ""
    text: str = ""
    media_type: str = ""
    media_id: str = ""
    file_url: str = ""
    file_name: str = ""
    file_size: int = 0
    duration_ms: int = 0
    media_format: str = ""
    timestamp: str = ""


@router.get("/multimedia/recent", response_model=List[WeixinMultimediaMessageResponse])
async def list_recent_multimedia(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100),
    media_type: Optional[str] = Query(default=None, pattern=r"^(image|voice|file|video)$"),
) -> Dict[str, Any]:
    """
    列出当前用户最近的微信多媒体消息。

    通过扫描 ShortTermMemory 中 weixin:auto: 前缀的元数据，
    返回包含多媒体描述的最近消息。可选 media_type 过滤特定类型。
    """
    user_id = str(current_user.id)
    try:
        memories = (
            db.query(ShortTermMemory)
            .filter(
                ShortTermMemory.session_id.like("weixin:auto:%"),
                ShortTermMemory.workspace_id == "default",
            )
            .order_by(ShortTermMemory.timestamp.desc())
            .limit(limit * 10)
            .all()
        )
    except Exception as exc:
        logger.error(f"[weixin] 查询多媒体消息失败: {exc}")
        raise HTTPException(status_code=500, detail="查询多媒体消息失败")

    results: List[WeixinMultimediaMessageResponse] = []
    for mem in memories:
        content_str = str(mem.content or "")
        # 多媒体消息内容以 [图片消息]/[语音消息]/[文件消息]/[视频消息] 标记开头
        media_marker_map = {
            "image": "[图片消息]",
            "voice": "[语音消息]",
            "file": "[文件消息]",
            "video": "[视频消息]",
        }
        detected_type = ""
        for mtype, marker in media_marker_map.items():
            if marker in content_str:
                detected_type = mtype
                break
        if not detected_type:
            continue
        if media_type and detected_type != media_type:
            continue

        # 解析 session_id 提取 from_user_id
        sid = mem.session_id or ""
        parts = sid.replace("weixin:auto:", "").split(":", 1)
        from_user_id = parts[1] if len(parts) > 1 else ""

        # 从消息文本描述中提取 media_id/file_url/file_size/duration_ms 等元数据
        metadata = _parse_multimedia_metadata(content_str)

        results.append(
            WeixinMultimediaMessageResponse(
                message_id=f"{sid}:{mem.id}",
                from_user_id=from_user_id,
                message_type=detected_type,
                text=content_str[:500],
                media_type=detected_type,
                media_id=metadata.get("media_id", ""),
                file_url=metadata.get("file_url", ""),
                file_name=metadata.get("file_name", ""),
                file_size=int(metadata.get("file_size", 0) or 0),
                duration_ms=int(metadata.get("duration_ms", 0) or 0),
                media_format=metadata.get("media_format", ""),
                timestamp=mem.timestamp.isoformat() if mem.timestamp else "",
            )
        )
        if len(results) >= limit:
            break

    return results


@router.get("/multimedia/{message_id}")
async def get_multimedia_detail(
    message_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """
    获取指定多媒体消息的详细信息。

    message_id 格式: {session_id}:{memory_id}
    """
    if ":" not in message_id:
        raise HTTPException(status_code=400, detail="无效的消息 ID 格式")

    parts = message_id.rsplit(":", 1)
    session_id, memory_id_str = parts[0], parts[1]
    try:
        memory_id = int(memory_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的消息 ID 格式")

    try:
        memory = db.query(ShortTermMemory).filter(
            ShortTermMemory.id == memory_id,
            ShortTermMemory.session_id == session_id,
        ).first()
    except Exception as exc:
        logger.error(f"[weixin] 查询多媒体详情失败: {exc}")
        raise HTTPException(status_code=500, detail="查询多媒体详情失败")

    if not memory:
        raise HTTPException(status_code=404, detail="未找到指定的多媒体消息")

    return {
        "message_id": message_id,
        "session_id": session_id,
        "content": str(memory.content or ""),
        "role": memory.role or "",
        "timestamp": memory.timestamp.isoformat() if memory.timestamp else "",
        "reasoning_content": str(memory.reasoning_content or "") if memory.reasoning_content else "",
        "tool_events": memory.tool_events if memory.tool_events else [],
    }


class WeixinMultimediaSendResponse(BaseModel):
    """微信多媒体发送结果响应模型"""
    success: bool
    media_type: str
    media_id: str
    to_user: str
    file_name: str
    file_size: int
    upload_result: Dict[str, Any] = {}
    send_result: Dict[str, Any] = {}


class WeixinMediaAssetResponse(BaseModel):
    """微信媒体资产响应，绝不包含 CDN 参数和 AES 密钥。"""
    message_id: str
    media_type: str
    media_format: str = ""
    transcript: str = ""
    transcript_status: str
    created_at: str


def _is_audio_transcription_model(config: ModelConfiguration) -> bool:
    """根据模型模态标记或模型名识别兼容 OpenAI 转写协议的音频模型。"""
    try:
        modalities = json.loads(config.input_modality or "[]")
    except json.JSONDecodeError:
        modalities = []
    normalized_modalities = {str(item).strip().lower() for item in modalities} if isinstance(modalities, list) else set()
    return "audio" in normalized_modalities or "whisper" in str(config.model or "").lower()


def _find_transcription_configuration(db: Session) -> tuple[ModelConfiguration, ProviderCredential]:
    """查找当前用户配置中可用的音频转写模型及其凭据。"""
    configurations = db.query(ModelConfiguration).filter(ModelConfiguration.is_active.is_(True)).all()
    for config in configurations:
        if not _is_audio_transcription_model(config):
            continue
        credential = None
        if config.credential_id:
            credential = db.query(ProviderCredential).filter(
                ProviderCredential.id == config.credential_id,
                ProviderCredential.is_active.is_(True),
            ).first()
        if credential is None:
            credential = db.query(ProviderCredential).filter(
                ProviderCredential.provider == config.provider,
                ProviderCredential.is_active.is_(True),
            ).first()
        if credential and credential.api_key and (credential.api_endpoint or config.api_endpoint):
            return config, credential
    raise HTTPException(status_code=409, detail="未配置可用的音频转写模型，请在模型设置中启用输入模态包含 audio 的模型")


@router.get("/multimedia/assets/recent", response_model=List[WeixinMediaAssetResponse])
async def list_recent_multimedia_assets(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=100),
    media_type: Optional[str] = Query(default=None, pattern=r"^(image|voice|file|video)$"),
) -> List[WeixinMediaAssetResponse]:
    """列出可安全下载或转写的当前用户微信媒体资产。"""
    query = db.query(WeixinMediaAsset).filter(WeixinMediaAsset.user_id == str(current_user.id))
    if media_type:
        query = query.filter(WeixinMediaAsset.media_type == media_type)
    assets = query.order_by(WeixinMediaAsset.created_at.desc()).limit(limit).all()
    return [
        WeixinMediaAssetResponse(
            message_id=asset.message_id,
            media_type=asset.media_type,
            media_format=asset.media_format or "",
            transcript=asset.transcript or "",
            transcript_status=asset.transcript_status or "pending",
            created_at=asset.created_at.isoformat() if asset.created_at else "",
        )
        for asset in assets
    ]


@router.get("/multimedia/assets/{message_id}/download")
async def download_multimedia_asset(
    message_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Response:
    """下载当前用户的微信媒体资产，CDN 参数和 AES 密钥不会返回给客户端。"""
    asset = db.query(WeixinMediaAsset).filter(
        WeixinMediaAsset.message_id == message_id,
        WeixinMediaAsset.user_id == str(current_user.id),
    ).first()
    if asset is None:
        raise HTTPException(status_code=404, detail="多媒体资产不存在")
    try:
        content = await WeixinSkillAdapter().download_media(
            decrypt_secret_value(asset.encrypted_query_param),
            decrypt_secret_value(asset.encrypted_aes_key),
        )
    except WeixinAdapterError as exc:
        logger.warning(f"[weixin] 下载多媒体资产失败: asset={asset.id}, code={exc.code}")
        raise HTTPException(status_code=502, detail=f"下载多媒体资产失败: {exc.message}")

    media_type = asset.media_type or "file"
    media_format = asset.media_format or "bin"
    content_type = {
        "image": f"image/{media_format}",
        "voice": "application/octet-stream",
        "video": f"video/{media_format}",
    }.get(media_type, "application/octet-stream")
    return Response(content=content, media_type=content_type)


@router.post("/multimedia/assets/{message_id}/transcribe", response_model=WeixinMediaAssetResponse)
async def transcribe_multimedia_asset(
    message_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> WeixinMediaAssetResponse:
    """使用用户已配置的音频模型转写其微信语音资产。"""
    asset = db.query(WeixinMediaAsset).filter(
        WeixinMediaAsset.message_id == message_id,
        WeixinMediaAsset.user_id == str(current_user.id),
    ).first()
    if asset is None:
        raise HTTPException(status_code=404, detail="多媒体资产不存在")
    if asset.media_type != "voice":
        raise HTTPException(status_code=400, detail="仅语音媒体支持转写")

    config, credential = _find_transcription_configuration(db)
    asset.transcript_status = "processing"
    db.commit()
    try:
        audio_content = await WeixinSkillAdapter().download_media(
            decrypt_secret_value(asset.encrypted_query_param),
            decrypt_secret_value(asset.encrypted_aes_key),
        )
        endpoint = str(credential.api_endpoint or config.api_endpoint).rstrip("/")
        if endpoint.endswith("/v1"):
            endpoint = f"{endpoint}/audio/transcriptions"
        else:
            endpoint = f"{endpoint}/v1/audio/transcriptions"
        extension = (asset.media_format or "amr").strip().lstrip(".") or "amr"
        headers = {"Authorization": f"Bearer {decrypt_secret_value(credential.api_key)}"}
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                endpoint,
                headers=headers,
                data={"model": config.model},
                files={"file": (f"weixin_voice.{extension}", audio_content, "application/octet-stream")},
            )
        if response.status_code >= 400:
            raise ValueError(f"转写服务返回 HTTP {response.status_code}")
        response_data = response.json()
        transcript = str(response_data.get("text") or "").strip()
        if not transcript:
            raise ValueError("转写服务未返回 text 字段")
        asset.transcript = transcript
        asset.transcript_status = "completed"
        db.commit()
    except (WeixinAdapterError, httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
        db.rollback()
        asset = db.query(WeixinMediaAsset).filter(WeixinMediaAsset.id == asset.id).first()
        if asset is not None:
            asset.transcript_status = "failed"
            db.commit()
        logger.warning(f"[weixin] 语音转写失败: asset={message_id}, error={type(exc).__name__}")
        raise HTTPException(status_code=502, detail="语音转写失败，请检查音频模型配置和服务可用性") from exc

    return WeixinMediaAssetResponse(
        message_id=asset.message_id,
        media_type=asset.media_type,
        media_format=asset.media_format or "",
        transcript=asset.transcript or "",
        transcript_status=asset.transcript_status,
        created_at=asset.created_at.isoformat() if asset.created_at else "",
    )


@router.post("/multimedia/send", response_model=WeixinMultimediaSendResponse)
async def send_multimedia(
    to_user: str = Form(..., min_length=1, max_length=128),
    media_type: str = Form(..., pattern=r"^(image|voice|video|file)$"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """
    上传并发送微信多媒体消息。

    接收文件上传 + 目标用户 + 消息类型，执行以下流程：
    1. 安全校验：文件大小限制 50MB、MIME 类型白名单、文件名路径穿越防护
    2. 将上传文件保存到临时目录
    3. 调用 upload_media 上传临时素材获取 media_id
    4. 调用对应的 send_xxx_message 发送多媒体消息
    5. 清理临时文件并返回发送结果
    """
    user_id = str(current_user.id)

    # 校验 media_type 与 MIME 类型白名单
    content_type = str(file.content_type or "").lower()
    if content_type not in _MULTIMEDIA_ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {content_type or '未知'}，允许的类型: {', '.join(sorted(_MULTIMEDIA_ALLOWED_MIME_TYPES.keys()))}",
        )
    mime_inferred_type = _MULTIMEDIA_ALLOWED_MIME_TYPES[content_type]
    if media_type != mime_inferred_type:
        raise HTTPException(
            status_code=400,
            detail=f"media_type={media_type} 与文件 MIME 类型 {content_type} 不匹配，应为 {mime_inferred_type}",
        )

    # 读取文件内容并校验大小
    try:
        file_bytes = await file.read()
    except Exception as exc:
        logger.error(f"[weixin] 读取上传文件失败: user={user_id}, error={exc}")
        raise HTTPException(status_code=400, detail="读取上传文件失败")
    file_size = len(file_bytes)
    if file_size == 0:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if file_size > _MULTIMEDIA_MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"文件大小 {file_size} 字节超过限制 {_MULTIMEDIA_MAX_FILE_SIZE} 字节 (50MB)",
        )

    # 清理文件名，防止路径穿越
    safe_filename = _sanitize_upload_filename(file.filename or "")

    # 加载微信绑定配置
    binding = _ensure_binding_exists(db, user_id)
    if not binding:
        raise HTTPException(status_code=400, detail="未找到微信绑定记录，请先绑定微信账号")
    runtime = _load_weixin_binding(db, user_id)
    if not runtime or not runtime.token:
        raise HTTPException(status_code=400, detail="微信绑定配置无效，token 为空")

    adapter = WeixinSkillAdapter()

    # 保存到临时文件
    temp_file_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{safe_filename}", prefix="weixin_upload_") as temp_file:
            temp_file.write(file_bytes)
            temp_file_path = temp_file.name

        # 上传临时素材
        try:
            upload_result = await adapter.upload_media(
                config=runtime,
                media_type=media_type,
                file_path=temp_file_path,
                to_user_id=to_user,
            )
        except WeixinAdapterError as exc:
            logger.warning(f"[weixin] 上传多媒体素材失败: user={user_id}, code={exc.code}, msg={exc.message}")
            raise HTTPException(status_code=502, detail=f"上传素材失败: {exc.message}")

        media_id = str(upload_result.get("media_id") or "")

        # 根据类型调用对应的发送方法
        try:
            if media_type == "image":
                send_result = await adapter.send_image_message(runtime, to_user, upload_result)
            elif media_type == "voice":
                send_result = await adapter.send_voice_message(runtime, to_user, upload_result)
            elif media_type == "video":
                send_result = await adapter.send_video_message(runtime, to_user, upload_result)
            else:
                send_result = await adapter.send_file_message(runtime, to_user, upload_result)
        except WeixinAdapterError as exc:
            logger.warning(f"[weixin] 发送多媒体消息失败: user={user_id}, code={exc.code}, msg={exc.message}")
            raise HTTPException(status_code=502, detail=f"发送多媒体消息失败: {exc.message}")

        logger.info(
            f"[weixin] 多媒体消息发送成功: user={user_id}, to={to_user}, type={media_type}, "
            f"file={safe_filename}, size={file_size}, media_id={media_id}"
        )
        return WeixinMultimediaSendResponse(
            success=True,
            media_type=media_type,
            media_id=media_id,
            to_user=to_user,
            file_name=safe_filename,
            file_size=file_size,
            upload_result=upload_result,
            send_result=send_result,
        )
    finally:
        # 清理临时文件
        if temp_file_path:
            try:
                os.remove(temp_file_path)
            except OSError as exc:
                # 临时文件清理失败不应影响主流程，但需记录便于排查磁盘问题
                logger.debug(f"[weixin] 临时文件清理失败：{temp_file_path}, error={exc}")


# ──────────────────────────────────────────────
#  WebSocket 实时消息推送
# ──────────────────────────────────────────────

async def _ws_authenticate(token: str) -> Optional[str]:
    """WebSocket 鉴权：解析 token 并返回 user_id，失败返回 None。"""
    if not token:
        return None
    payload = decode_access_token(token)
    if payload is None:
        return None
    username = payload.get("sub")
    if not isinstance(username, str):
        return None

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if user is None or user.role == "disabled":
            return None
        return str(user.id)
    except Exception as exc:
        # 用户查找失败可能由 DB 异常引起，记录日志便于排查
        logger.warning(f"[weixin] 通过用户名解析用户 ID 失败，username={username}: {exc}", exc_info=exc)
        return None
    finally:
        db.close()


@router.websocket("/ws")
async def weixin_ws_endpoint(websocket: WebSocket):
    """
    微信实时消息推送 WebSocket 端点。

    鉴权方式（SEC-16）：通过 Sec-WebSocket-Protocol 子协议头传递 `bearer.<token>`，
    不再从 URL query 读取，避免 token 泄露到 access log / Referer / 浏览器历史。
    鉴权通过后订阅事件总线，将新消息事件实时推送给前端。

    推送事件格式：
    {
        "event": "new_message",
        "message_id": "...",
        "from_user_id": "...",
        "text": "...",
        "message_type": "...",
        "multimedia": {...} | null,
        "timestamp": "..."
    }
    """
    # CSWSH 防护：握手前校验 Origin，禁止跨站 WebSocket 连接
    request_origin = websocket.headers.get("origin")
    if not validate_ws_origin(request_origin or ""):
        # 握手阶段未 accept，直接 close 不会被浏览器看到，但能阻断恶意连接
        await websocket.close(code=4003, reason="Origin not allowed")
        return

    # SEC-16: 从子协议头读取 token，避免 URL 泄露
    # 共享层返回 (token, subprotocol) 元组；微信端点不回显子协议（见下方 accept 注释），
    # 因此丢弃 subprotocol，仅取 token
    token, _subprotocol = extract_token_from_subprotocol(websocket)
    if not token:
        await websocket.close(code=4001, reason="Missing authentication token")
        return

    user_id = await _ws_authenticate(token)
    if user_id is None:
        await websocket.close(code=4002, reason="Invalid or expired token")
        return

    # 不回显子协议：RFC 6455 规定服务器可以选择不返回 Sec-WebSocket-Protocol 头，
    # 此时浏览器仍会接受连接。避免在响应头中再次携带 token。
    await websocket.accept()
    event_bus = get_event_bus()
    queue = await event_bus.subscribe(user_id)

    logger.bind(
        event="weixin_ws_connected",
        module="weixin.ws",
        user_id=user_id,
    ).info("微信 WebSocket 连接已建立")

    try:
        await websocket.send_json({"event": "connected", "user_id": user_id})

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                # 发送心跳保活
                await websocket.send_json({"event": "ping", "timestamp": datetime.now(timezone.utc).isoformat()})
    except WebSocketDisconnect:
        logger.bind(
            event="weixin_ws_disconnected",
            module="weixin.ws",
            user_id=user_id,
        ).info("微信 WebSocket 连接已断开")
    except Exception as exc:
        logger.bind(
            event="weixin_ws_error",
            module="weixin.ws",
            user_id=user_id,
            error_type=type(exc).__name__,
        ).warning(f"微信 WebSocket 异常: {exc}")
    finally:
        await event_bus.unsubscribe(user_id, queue)

"""
微信绑定管理路由，负责微信绑定状态的增删改查及连接参数配置。
与 skills.py 中的扫码登录路由配合使用，提供完整的微信集成管理能力。

v2: 新增微信对话历史查询端点，实现跨渠道上下文可视化。
v3: 新增 WebSocket 实时消息推送端点与多媒体消息查询接口。
"""

import asyncio
import json
from typing import Any, Dict, Optional, List
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from api.services.weixin_auto_reply import (
    WeixinAutoReplyService,
    get_auto_reply_manager,
    get_event_bus,
    _AUTO_REPLY_MANAGER,
    DEFAULT_CROSS_CHANNEL_CONTEXT_TURNS,
)
from config.security import decode_access_token, decrypt_secret_value, encrypt_secret_value
from config.settings import settings
from db.models import SessionLocal, ShortTermMemory, Skill, User, WeixinBinding, WeixinAutoReplyRule, get_db
from core.weixin_utils import (
    normalize_binding_status as _normalize_binding_status,
    deserialize_skill_config as _deserialize_skill_config,
)
from skills.weixin_skill_adapter import WeixinSkillAdapter


router = APIRouter(prefix="/api/weixin", tags=["Weixin"])
_WEIXIN_SKILL_NAME = "weixin_dispatch"


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
):
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
):
    """获取当前用户微信自动回复运行状态。"""
    _ensure_binding_exists(db, str(current_user.id))
    manager = get_auto_reply_manager()
    return manager.get_status(str(current_user.id))


@router.post("/auto-reply/start")
async def start_auto_reply(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """启动当前用户的微信自动回复后台轮询。"""
    _ensure_binding_exists(db, str(current_user.id))
    manager = get_auto_reply_manager()
    try:
        return await manager.start(str(current_user.id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/auto-reply/stop")
async def stop_auto_reply(current_user=Depends(get_current_user)):
    """停止当前用户的微信自动回复后台轮询。"""
    manager = get_auto_reply_manager()
    return await manager.stop(str(current_user.id))


@router.post("/auto-reply/restart")
async def restart_auto_reply(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
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
):
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
):
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
):
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
):
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
):
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
):
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
):
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
    except Exception:
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
):
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
):
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
    except Exception:
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
):
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

        results.append(
            WeixinMultimediaMessageResponse(
                message_id=f"{sid}:{mem.id}",
                from_user_id=from_user_id,
                message_type=detected_type,
                text=content_str[:500],
                media_type=detected_type,
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
):
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
    except Exception:
        return None
    finally:
        db.close()


@router.websocket("/ws")
async def weixin_ws_endpoint(
    websocket: WebSocket,
    token: str = Query(default=""),
):
    """
    微信实时消息推送 WebSocket 端点。

    鉴权方式：通过 query 参数 `token` 传递 JWT。
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
    if not token:
        await websocket.close(code=4001, reason="Missing authentication token")
        return

    user_id = await _ws_authenticate(token)
    if user_id is None:
        await websocket.close(code=4002, reason="Invalid or expired token")
        return

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
        await event_bus.unsubscribe(user_id)

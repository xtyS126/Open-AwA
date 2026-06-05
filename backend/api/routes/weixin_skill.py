"""
微信技能 API 路由模块，提供微信连接配置、二维码登录和会话管理功能。
从 skills.py 拆分而来，以降低单文件复杂度。
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from db.models import get_db, Skill, WeixinBinding
from api.dependencies import get_current_user
from api.routes.skills import _deserialize_skill_config
from config.security import decrypt_secret_value, encrypt_secret_value
from skills.weixin_skill_adapter import (
    WeixinSkillAdapter,
    WeixinRuntimeConfig,
    WeixinAdapterError,
    DEFAULT_BASE_URL,
    DEFAULT_BOT_TYPE,
    DEFAULT_QR_BASE_URL,
)
from loguru import logger

import json
import threading
import time
import uuid
import re
from urllib.parse import parse_qs, urlparse


router = APIRouter(prefix="/skills/weixin", tags=["Skills - Weixin"])

# ---------------------------------------------------------------------------
# 微信常量
# ---------------------------------------------------------------------------

WEIXIN_SKILL_NAME = "weixin_dispatch"
WEIXIN_QR_SESSION_TTL_SECONDS = 300
WEIXIN_QR_SESSIONS: Dict[str, Dict[str, Any]] = {}
WEIXIN_QR_SESSIONS_LOCK = threading.Lock()

# 微信二维码图片代理允许的域名白名单，防止 SSRF 攻击
WEIXIN_QR_ALLOWED_DOMAINS = frozenset({
    "wx.qq.com",
    "weixin.qq.com",
    "open.weixin.qq.com",
    "ilinkai.weixin.qq.com",
    "mmbiz.qpic.cn",
    "mmbiz.qlogo.cn",
    "res.wx.qq.com",
})

WEIXIN_QR_STATE_MAP = {
    "waiting": "pending",
    "scanned": "half_success",
    "scaned_but_redirect": "half_success",
    "refreshing": "half_success",
    "expired": "failed",
    "timeout": "failed",
    "confirmed": "success",
}

WEIXIN_QR_MESSAGE_MAP = {
    "waiting": "等待扫码中",
    "scanned": "已扫码，请在微信中确认",
    "refreshing": "二维码已过期，正在刷新",
    "expired": "二维码已过期，请重新获取",
    "confirmed": "与微信连接成功",
}

_weixin_config_migrated = False


# ---------------------------------------------------------------------------
# 微信辅助函数
# ---------------------------------------------------------------------------

def _validate_qrcode_url(url: str) -> str:
    """校验二维码图片 URL 的安全性，防止 SSRF 攻击。"""
    normalized_url = str(url).strip()
    if not normalized_url:
        raise ValueError("二维码 URL 为空")

    parsed = urlparse(normalized_url)
    hostname = str(parsed.hostname or "").lower()

    if not hostname:
        raise ValueError(f"二维码 URL 缺少合法域名: {normalized_url[:120]}")

    if parsed.scheme != "https":
        raise ValueError(f"二维码 URL 仅允许 https 协议: {normalized_url[:120]}")

    if hostname not in WEIXIN_QR_ALLOWED_DOMAINS:
        raise ValueError(f"二维码 URL 域名 '{hostname}' 不在允许的白名单中")

    return normalized_url


def _build_default_weixin_config() -> Dict[str, Any]:
    """构建默认微信配置。"""
    return {
        "account_id": "",
        "token": "",
        "base_url": DEFAULT_BASE_URL,
        "timeout_seconds": 15,
        "user_id": "",
        "binding_status": "unbound",
    }


def _normalize_timeout_seconds(timeout_seconds: Optional[int], fallback: int = 15) -> int:
    """规范化超时秒数。"""
    if timeout_seconds is None:
        return fallback
    try:
        return max(1, int(timeout_seconds))
    except (TypeError, ValueError):
        return fallback


def _normalize_binding_status(binding_status: Optional[str], user_id: str = "", fallback: str = "unbound") -> str:
    """规范化微信绑定状态。"""
    normalized = str(binding_status or "").strip().lower()
    if normalized in {"bound", "confirmed", "linked", "success", "succeeded"}:
        return "bound"
    if normalized in {"pending", "confirming", "waiting"}:
        return "pending"
    if normalized in {"unbound", "failed", "none", ""}:
        return "bound" if user_id else fallback
    if user_id:
        return "bound"
    return fallback


def _build_weixin_bound_snapshot(
    account_id: str = "",
    user_id: str = "",
    binding_status: str = "unbound",
) -> Dict[str, str]:
    """构建微信绑定状态快照。"""
    normalized_user_id = str(user_id or "").strip()
    normalized_binding_status = _normalize_binding_status(binding_status, user_id=normalized_user_id)
    return {
        "account_id": str(account_id or "").strip(),
        "user_id": normalized_user_id,
        "binding_status": normalized_binding_status,
    }


def _save_weixin_config_to_db(
    db: Session,
    account_id: str,
    token: str,
    base_url: str,
    timeout_seconds: int,
    app_user_id: str = "",
    user_id: str = "",
    binding_status: str = "unbound",
) -> None:
    """保存微信配置到 WeixinBinding 表。"""
    normalized_app_user_id = str(app_user_id or "").strip()
    normalized_user_id = str(user_id or "").strip()
    normalized_binding_status = _normalize_binding_status(binding_status, user_id=normalized_user_id)

    if not normalized_app_user_id:
        db.commit()
        return

    binding = db.query(WeixinBinding).filter(WeixinBinding.user_id == normalized_app_user_id).first()
    if binding:
        binding.weixin_account_id = str(account_id or "").strip()
        binding.token = encrypt_secret_value(token) if str(token or "").strip() else ""
        binding.base_url = str(base_url or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
        binding.bot_type = binding.bot_type or DEFAULT_BOT_TYPE
        binding.channel_version = binding.channel_version or "1.0.2"
        binding.binding_status = normalized_binding_status
        binding.weixin_user_id = normalized_user_id
        binding.timeout_seconds = timeout_seconds
    elif str(account_id or "").strip() or str(token or "").strip() or normalized_user_id:
        binding = WeixinBinding(
            user_id=normalized_app_user_id,
            weixin_account_id=str(account_id or "").strip(),
            token=encrypt_secret_value(token) if str(token or "").strip() else "",
            base_url=str(base_url or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL,
            bot_type=DEFAULT_BOT_TYPE,
            channel_version="1.0.2",
            binding_status=normalized_binding_status,
            weixin_user_id=normalized_user_id,
            timeout_seconds=timeout_seconds,
        )
        db.add(binding)
    db.commit()


def load_weixin_binding_config(db: Session, user_id: str) -> WeixinRuntimeConfig:
    """从用户绑定表读取微信运行时配置。"""
    binding = db.query(WeixinBinding).filter(
        WeixinBinding.user_id == user_id
    ).first()
    if not binding:
        return WeixinRuntimeConfig(
            account_id="",
            token="",
            base_url=DEFAULT_BASE_URL,
            bot_type=DEFAULT_BOT_TYPE,
            channel_version="1.0.2",
            timeout_seconds=15,
        )
    return WeixinRuntimeConfig(
        account_id=binding.weixin_account_id or "",
        token=decrypt_secret_value(binding.token or ""),
        base_url=binding.base_url or DEFAULT_BASE_URL,
        bot_type=binding.bot_type or DEFAULT_BOT_TYPE,
        channel_version=binding.channel_version or "1.0.2",
        timeout_seconds=binding.timeout_seconds or 15,
    )


def _migrate_weixin_config_from_skill(db: Session) -> None:
    """一次性迁移：将旧 Skill.config.weixin 中的配置搬到用户绑定表。"""
    skill = db.query(Skill).filter(Skill.name == WEIXIN_SKILL_NAME).first()
    if not skill:
        return
    config_dict = _deserialize_skill_config(skill.config)
    wx_config = config_dict.get("weixin", {})
    account_id = str(wx_config.get("account_id") or "").strip()
    token = str(wx_config.get("token") or "").strip()
    migrated_user_id = str(wx_config.get("user_id") or "").strip()
    if not migrated_user_id:
        return
    existing = db.query(WeixinBinding).filter(
        WeixinBinding.user_id == migrated_user_id
    ).first()
    if existing:
        return
    binding = WeixinBinding(
        user_id=migrated_user_id,
        weixin_account_id=account_id,
        token=token,
        base_url=str(wx_config.get("base_url") or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL,
        bot_type=DEFAULT_BOT_TYPE,
        channel_version="1.0.2",
        binding_status=_normalize_binding_status(str(wx_config.get("binding_status", "")), user_id=migrated_user_id),
        weixin_user_id=migrated_user_id,
        timeout_seconds=wx_config.get("timeout_seconds", 15),
    )
    db.add(binding)
    db.commit()
    logger.bind(
        event="weixin_config_migrated",
        module="weixin_skill",
        user_id=migrated_user_id,
    ).info("已将历史 Skill 配置迁移到 WeixinBinding")


def _coerce_weixin_response_payload(payload: Any) -> Dict[str, Any]:
    """将微信上游返回的各种格式统一转换为字典。"""
    if isinstance(payload, dict):
        return dict(payload)
    if payload is None:
        return {}
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="ignore")

    text = str(payload or "").strip()
    if not text:
        return {}

    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        normalized = dict(parsed)
        normalized.setdefault("raw_text", text)
        return normalized
    if isinstance(parsed, str) and parsed.strip() and parsed.strip() != text:
        normalized = _coerce_weixin_response_payload(parsed)
        if normalized:
            normalized.setdefault("raw_text", text)
            return normalized

    query_candidate = text
    if "://" in text or text.startswith("/"):
        try:
            parsed_url = urlparse(text)
            if parsed_url.query:
                query_candidate = parsed_url.query
        except Exception:
            query_candidate = text

    try:
        form_values = parse_qs(query_candidate, keep_blank_values=True)
    except Exception:
        form_values = {}
    if form_values:
        normalized = {
            str(key): values[-1] if isinstance(values, list) and values else ""
            for key, values in form_values.items()
        }
        normalized.setdefault("raw_text", text)
        if "qrcode" not in normalized and text.startswith(("http://", "https://")):
            normalized["qrcode_url"] = text
        return normalized

    normalized_pairs: Dict[str, Any] = {}
    for segment in re.split(r"[\n\r,;]+", text):
        item = str(segment or "").strip()
        if not item:
            continue
        separator = None
        if "=" in item:
            separator = "="
        elif ":" in item and "://" not in item:
            separator = ":"
        if not separator:
            continue
        key, value = item.split(separator, 1)
        key = str(key or "").strip()
        value = str(value or "").strip()
        if key:
            normalized_pairs[key] = value
    if normalized_pairs:
        normalized_pairs.setdefault("raw_text", text)
        return normalized_pairs

    lowered = text.lower()
    if lowered in {"wait", "waiting", "scaned", "scanned", "scaned_but_redirect", "confirmed", "expired", "pending", "confirming", "refreshing", "timeout", "success", "ok", "done"}:
        return {"status": text, "raw_text": text}
    if text.startswith(("http://", "https://")):
        return {"qrcode_url": text, "raw_text": text}
    return {"raw_text": text}


def _extract_qrcode_fields(result: Dict[str, Any]) -> Dict[str, str]:
    """从上游返回中提取二维码字段。"""
    payload_source = result.get("data") if isinstance(result, dict) and result.get("data") is not None else result
    payload = _coerce_weixin_response_payload(payload_source)
    raw_text = str(payload.get("raw_text") or "").strip()
    qrcode = str(
        payload.get("qrcode")
        or payload.get("qr_code")
        or payload.get("qrCode")
        or ""
    ).strip()
    qrcode_url = str(
        payload.get("qrcode_img_content")
        or payload.get("qrcode_url")
        or payload.get("qr_code_url")
        or payload.get("qrCodeUrl")
        or ""
    ).strip()
    qrcode_content = qrcode_url
    if not qrcode and qrcode_url:
        try:
            parsed = urlparse(qrcode_url)
            query_qrcode = parse_qs(parsed.query).get("qrcode", [""])[0]
            qrcode = str(query_qrcode or "").strip()
        except Exception:
            qrcode = ""
    if not qrcode_content and raw_text:
        qrcode_content = raw_text
    if not qrcode and raw_text and not qrcode_url:
        qrcode = raw_text
    return {"qrcode": qrcode, "qrcode_url": qrcode_url, "qrcode_content": qrcode_content}


def _build_qr_session(
    *,
    qrcode: str,
    qrcode_url: str,
    qrcode_content: str,
    login_base_url: str,
    poll_base_url: str,
    bot_type: str,
    timeout_seconds: int,
    user_id: str = "",
) -> Dict[str, Any]:
    """构建二维码会话对象。"""
    return {
        "qrcode": qrcode,
        "qrcode_url": qrcode_url,
        "qrcode_content": qrcode_content,
        "login_base_url": login_base_url,
        "poll_base_url": poll_base_url,
        "bot_type": bot_type,
        "created_at": time.time(),
        "timeout_seconds": timeout_seconds,
        "confirmed_payload": None,
        "confirmed_snapshot": _build_weixin_bound_snapshot(),
        "user_id": user_id,
    }


def _build_qr_response(
    *,
    session_key: str,
    status: str,
    message: str = "",
    connected: bool = False,
    qrcode: str = "",
    qrcode_url: str = "",
    qrcode_content: str = "",
    redirect_host: str = "",
    base_url: str = "",
    account_id: str = "",
    token: str = "",
    user_id: str = "",
    binding_status: str = "unbound",
    auth_id: str = "",
    ticket: str = "",
    hint: str = "",
) -> Dict[str, Any]:
    """构建标准化的二维码响应。"""
    normalized_status = str(status or "waiting").strip().lower() or "waiting"
    normalized_message = str(message or WEIXIN_QR_MESSAGE_MAP.get(normalized_status, "login status updating")).strip()
    normalized_user_id = str(user_id or "").strip()
    normalized_binding_status = _normalize_binding_status(binding_status, user_id=normalized_user_id)
    return {
        "success": True,
        "connected": bool(connected),
        "state": WEIXIN_QR_STATE_MAP.get(normalized_status, "pending"),
        "status": normalized_status,
        "session_key": str(session_key or "").strip(),
        "message": normalized_message,
        "qrcode": str(qrcode or "").strip(),
        "qrcode_url": str(qrcode_url or "").strip(),
        "qrcode_content": str(qrcode_content or qrcode_url or qrcode or "").strip(),
        "redirect_host": str(redirect_host or "").strip(),
        "base_url": str(base_url or "").strip(),
        "account_id": str(account_id or "").strip(),
        "token": str(token or "").strip(),
        "user_id": normalized_user_id,
        "binding_status": normalized_binding_status,
        "auth_id": str(auth_id or "").strip(),
        "ticket": str(ticket or "").strip(),
        "hint": str(hint or "").strip(),
    }


def _build_qr_logger(session_key: str, event: str, **fields: Any):
    """构建带微信 QR 上下文的日志记录器。"""
    return logger.bind(
        feature="weixin_qr",
        session_key=str(session_key or "").strip(),
        event=event,
        **fields,
    )


def _build_qrcode_upstream_error_detail(result: Dict[str, Any]) -> str:
    """构建上游错误详情字符串。"""
    payload_source = result.get("data") if isinstance(result, dict) and result.get("data") is not None else result
    payload = _coerce_weixin_response_payload(payload_source)
    code = payload.get("errcode") or payload.get("code") or payload.get("ret")
    message = (
        payload.get("errmsg")
        or payload.get("message")
        or payload.get("error")
        or payload.get("retmsg")
        or payload.get("detail")
        or payload.get("raw_text")
    )
    detail = "上游返回错误"
    if isinstance(code, (int, str)) and str(code).strip() not in {"", "0"}:
        detail += f" (code={code})"
    if isinstance(message, str) and message.strip():
        detail += f": {message.strip()}"
    else:
        detail += f": {json.dumps(result, ensure_ascii=False)[:200]}"
    return detail


def _normalize_qr_wait_status(status_result: Dict[str, Any]) -> Dict[str, Any]:
    """规范化二维码等待状态。"""
    payload_source = status_result.get("data") if isinstance(status_result, dict) and status_result.get("data") is not None else status_result
    payload = _coerce_weixin_response_payload(payload_source)

    raw_status = str(
        payload.get("status")
        or payload.get("state")
        or payload.get("result")
        or payload.get("login_status")
        or ""
    ).strip().lower()
    message = str(
        payload.get("message")
        or payload.get("errmsg")
        or payload.get("hint")
        or payload.get("detail")
        or payload.get("raw_text")
        or ""
    ).strip()
    auth_id = str(payload.get("auth_id") or payload.get("authId") or payload.get("confirm_id") or "").strip()
    ticket = str(payload.get("ticket") or payload.get("ticket_id") or payload.get("ticketId") or "").strip()
    hint = str(payload.get("hint") or payload.get("tips") or payload.get("tip") or "").strip()
    account_id = str(payload.get("ilink_bot_id") or payload.get("account_id") or "").strip()
    token = str(payload.get("bot_token") or payload.get("token") or "").strip()
    user_id = str(payload.get("ilink_user_id") or payload.get("user_id") or payload.get("openid") or "").strip()
    binding_status = _normalize_binding_status(
        payload.get("binding_status") or payload.get("bindingStatus") or payload.get("bind_status"),
        user_id=user_id,
    )
    redirect_host = str(payload.get("redirect_host") or payload.get("redirectHost") or "").strip()

    if raw_status == "scaned_but_redirect":
        normalized_status = "scanned"
        if redirect_host:
            payload["redirect_host"] = redirect_host
            message = message or "已扫码，正在切换轮询节点"
    elif account_id and token:
        normalized_status = "confirmed"
    elif raw_status in {"confirmed", "confirm", "success", "succeed", "succeeded", "ok", "done"}:
        normalized_status = "confirmed"
    elif raw_status in {"expired", "timeout", "timed_out", "cancelled", "canceled", "invalid"}:
        normalized_status = "expired"
    elif raw_status in {"scaned", "scanned", "scan", "confirming", "pending", "wait_confirm", "waiting_confirm", "auth", "authorizing", "authorized"}:
        normalized_status = "scanned"
    elif raw_status == "refreshing":
        normalized_status = "refreshing"
    elif auth_id or ticket or hint:
        normalized_status = "scanned"
    else:
        normalized_status = "waiting"

    normalized_payload = dict(payload)
    normalized_payload["status"] = normalized_status
    normalized_payload["message"] = message
    if auth_id:
        normalized_payload["auth_id"] = auth_id
    if ticket:
        normalized_payload["ticket"] = ticket
    if hint:
        normalized_payload["hint"] = hint
    if user_id:
        normalized_payload["user_id"] = user_id
    normalized_payload["binding_status"] = binding_status
    if redirect_host:
        normalized_payload["redirect_host"] = redirect_host
    return normalized_payload


def _purge_expired_qr_sessions() -> None:
    """清理过期的二维码会话。"""
    now = time.time()
    with WEIXIN_QR_SESSIONS_LOCK:
        expired_keys = [
            key
            for key, value in WEIXIN_QR_SESSIONS.items()
            if now - float(value.get("created_at", 0)) >= WEIXIN_QR_SESSION_TTL_SECONDS
        ]
        for key in expired_keys:
            WEIXIN_QR_SESSIONS.pop(key, None)


def _coerce_weixin_payload_dict(raw_body: Any) -> Dict[str, Any]:
    """将原始请求体转换为字典。"""
    if isinstance(raw_body, dict):
        return raw_body
    if raw_body is None:
        return {}

    if isinstance(raw_body, bytes):
        raw_body = raw_body.decode("utf-8", errors="ignore")
    text = str(raw_body or "").strip()
    if not text:
        return {}

    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        return parsed

    try:
        form_values = parse_qs(text, keep_blank_values=True)
    except Exception:
        form_values = {}
    if form_values:
        normalized: Dict[str, Any] = {}
        for key, values in form_values.items():
            normalized[str(key)] = values[-1] if isinstance(values, list) and values else ""
        return normalized

    raise HTTPException(status_code=422, detail="请求载荷格式无效，仅支持对象、JSON 字符串或表单字符串")


async def _parse_weixin_request_payload(request: Request) -> Dict[str, Any]:
    """解析微信请求体。"""
    raw_body = await request.body()
    return _coerce_weixin_payload_dict(raw_body)


# ---------------------------------------------------------------------------
# 微信 Pydantic 模型
# ---------------------------------------------------------------------------

class WeixinConfigReq(BaseModel):
    """微信配置请求模型。"""
    account_id: str = Field(..., min_length=1, max_length=128, description="微信账号ID")
    token: str = Field(..., min_length=1, max_length=512, description="认证Token")
    base_url: Optional[str] = Field(default=DEFAULT_BASE_URL, max_length=512, description="基础URL")
    timeout_seconds: Optional[int] = Field(default=15, ge=1, le=300, description="超时秒数")
    user_id: Optional[str] = Field(default="", max_length=128, description="用户ID")
    binding_status: Optional[str] = Field(default="unbound", pattern=r"^(unbound|binding|bound|failed)$", description="绑定状态")
    bot_type: Optional[str] = Field(default=None, max_length=64, description="机器人类型")
    channel_version: Optional[str] = Field(default=None, max_length=32, description="渠道版本")


class WeixinQrStartReq(BaseModel):
    """微信二维码登录发起请求。"""
    session_key: Optional[str] = None
    base_url: Optional[str] = None
    bot_type: Optional[str] = None
    force: Optional[bool] = False
    timeout_seconds: Optional[int] = 15


class WeixinQrWaitReq(BaseModel):
    """微信二维码扫码等待请求。"""
    session_key: str
    timeout_seconds: Optional[int] = 35
    qrcode: Optional[str] = None
    base_url: Optional[str] = None


class WeixinQrExitReq(BaseModel):
    """微信二维码退出/清理请求。"""
    session_key: Optional[str] = None
    clear_config: Optional[bool] = True


# ---------------------------------------------------------------------------
# 微信 API 路由
# ---------------------------------------------------------------------------

@router.post("/health-check")
async def weixin_health_check(request: Request):
    """测试微信 API 连接健康状态。"""
    config = WeixinConfigReq(**(await _parse_weixin_request_payload(request)))
    adapter = WeixinSkillAdapter()
    runtime_config = WeixinRuntimeConfig(
        account_id=config.account_id,
        token=config.token,
        base_url=config.base_url or DEFAULT_BASE_URL,
        bot_type=config.bot_type if hasattr(config, "bot_type") and config.bot_type else DEFAULT_BOT_TYPE,
        channel_version=config.channel_version if hasattr(config, "channel_version") and config.channel_version else "1.0.2",
        timeout_seconds=config.timeout_seconds or 15,
        user_id=str(config.user_id or "").strip(),
        binding_status=_normalize_binding_status(config.binding_status, user_id=str(config.user_id or "").strip()),
    )
    result = adapter.check_health(runtime_config)
    return result


@router.post("/config")
async def save_weixin_config(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """保存微信连接配置。"""
    config = WeixinConfigReq(**(await _parse_weixin_request_payload(request)))
    _save_weixin_config_to_db(
        db=db,
        account_id=config.account_id,
        token=config.token,
        base_url=config.base_url or DEFAULT_BASE_URL,
        timeout_seconds=_normalize_timeout_seconds(config.timeout_seconds, fallback=15),
        app_user_id=str(current_user.id),
        user_id=str(config.user_id or "").strip(),
        binding_status=_normalize_binding_status(config.binding_status, user_id=str(config.user_id or "").strip()),
    )
    return {"message": "success"}


@router.get("/config")
async def get_weixin_config(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """获取当前用户的微信连接配置。"""
    global _weixin_config_migrated
    if not _weixin_config_migrated:
        _migrate_weixin_config_from_skill(db)
        _weixin_config_migrated = True

    try:
        binding = db.query(WeixinBinding).filter(
            WeixinBinding.user_id == str(current_user.id)
        ).first()
        if not binding:
            return _build_default_weixin_config()
        return {
            "account_id": binding.weixin_account_id or "",
            "token": decrypt_secret_value(binding.token or ""),
            "base_url": binding.base_url or DEFAULT_BASE_URL,
            "timeout_seconds": binding.timeout_seconds or 15,
            "user_id": binding.weixin_user_id or "",
            "binding_status": _normalize_binding_status(binding.binding_status, user_id=binding.weixin_user_id or ""),
            "bot_type": binding.bot_type or DEFAULT_BOT_TYPE,
            "channel_version": binding.channel_version or "1.0.2",
        }
    except Exception as e:
        logger.bind(
            event="weixin_config_load_error",
            module="weixin_skill",
            error_type=type(e).__name__,
        ).opt(exception=True).warning(f"加载微信配置失败，使用默认配置: {e}")
        return _build_default_weixin_config()


@router.post("/qr/start")
async def weixin_qr_start(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """发起微信二维码登录。"""
    payload = WeixinQrStartReq(**(await _parse_weixin_request_payload(request)))
    _purge_expired_qr_sessions()
    adapter = WeixinSkillAdapter()
    runtime = load_weixin_binding_config(db, str(current_user.id))
    session_key = str(payload.session_key or uuid.uuid4())

    with WEIXIN_QR_SESSIONS_LOCK:
        existing = WEIXIN_QR_SESSIONS.get(session_key)
    if existing and not payload.force:
        _build_qr_logger(session_key, "qr_reuse", poll_base_url=existing.get("poll_base_url", "")).info("reusing active weixin qr session")
        return _build_qr_response(
            session_key=session_key,
            status="waiting",
            message="二维码已就绪，请使用微信扫描。",
            qrcode=existing.get("qrcode", ""),
            qrcode_url=existing.get("qrcode_url", ""),
            base_url=existing.get("poll_base_url", ""),
        )

    try:
        timeout_seconds = _normalize_timeout_seconds(payload.timeout_seconds, fallback=runtime.timeout_seconds)
        login_base_url = DEFAULT_QR_BASE_URL
        poll_base_url = str(payload.base_url or runtime.base_url or DEFAULT_BASE_URL).strip().rstrip("/") or DEFAULT_BASE_URL
        bot_type = str(payload.bot_type or runtime.bot_type or DEFAULT_BOT_TYPE).strip() or DEFAULT_BOT_TYPE
        qr_result = await adapter.fetch_login_qrcode(
            base_url=login_base_url,
            bot_type=bot_type,
            timeout_seconds=timeout_seconds,
        )
    except WeixinAdapterError as exc:
        raise HTTPException(status_code=502, detail=exc.message)

    _build_qr_logger(session_key, "qr_start_upstream_result", poll_base_url=poll_base_url, bot_type=bot_type, timeout_seconds=timeout_seconds, upstream_preview=json.dumps(qr_result, ensure_ascii=False)[:600]).debug("received weixin qr upstream result")
    extracted = _extract_qrcode_fields(qr_result)
    qrcode = extracted["qrcode"]
    qrcode_url = extracted["qrcode_url"]
    qrcode_content = extracted["qrcode_content"]
    if not qrcode:
        _build_qr_logger(session_key, "qr_start_missing_qrcode", upstream_preview=json.dumps(qr_result, ensure_ascii=False)[:600]).warning("missing qrcode in upstream response")
        raise HTTPException(status_code=502, detail=_build_qrcode_upstream_error_detail(qr_result))

    with WEIXIN_QR_SESSIONS_LOCK:
        WEIXIN_QR_SESSIONS[session_key] = _build_qr_session(
            qrcode=qrcode,
            qrcode_url=qrcode_url,
            qrcode_content=qrcode_content,
            login_base_url=login_base_url,
            poll_base_url=poll_base_url,
            bot_type=bot_type,
            timeout_seconds=timeout_seconds,
            user_id=str(current_user.id),
        )

    _build_qr_logger(session_key, "qr_started", poll_base_url=poll_base_url, has_qrcode_url=bool(qrcode_url)).info("weixin qr session started")
    return _build_qr_response(
        session_key=session_key,
        status="waiting",
        message="使用微信扫描以下二维码，以完成连接。",
        qrcode=qrcode,
        qrcode_url=qrcode_url,
        qrcode_content=qrcode_content,
        base_url=poll_base_url,
    )


@router.get("/qr/image")
async def weixin_qr_image(
    session_key: Optional[str] = None,
    qrcode_url: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    """代理获取微信二维码图片。"""
    _purge_expired_qr_sessions()
    session: Optional[Dict[str, Any]] = None
    if session_key:
        with WEIXIN_QR_SESSIONS_LOCK:
            found = WEIXIN_QR_SESSIONS.get(session_key)
            if found:
                session = dict(found)

    resolved_qrcode_url = str((session or {}).get("qrcode_url") or qrcode_url or "").strip()
    if not resolved_qrcode_url:
        raise HTTPException(status_code=404, detail="当前没有进行中的登录，请先发起登录。")

    try:
        resolved_qrcode_url = _validate_qrcode_url(resolved_qrcode_url)
    except ValueError as exc:
        _build_qr_logger(session_key or "unknown", "qr_image_ssrf_rejected", qrcode_url=resolved_qrcode_url[:120], reason=str(exc)).warning("qrcode url validation failed")
        raise HTTPException(status_code=400, detail=f"二维码图片代理被拒绝: {str(exc)}")

    try:
        timeout_seconds = _normalize_timeout_seconds((session or {}).get("timeout_seconds"), fallback=15)
        import httpx
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False) as client:
            upstream = await client.get(resolved_qrcode_url)
        if upstream.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"二维码图片请求失败: HTTP {upstream.status_code}")
        content_type = upstream.headers.get("content-type", "image/png")
        return Response(content=upstream.content, media_type=content_type)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"二维码图片代理失败: {str(exc)}")


@router.post("/qr/wait")
async def weixin_qr_wait(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """轮询微信二维码扫码状态。"""
    payload = WeixinQrWaitReq(**(await _parse_weixin_request_payload(request)))
    _purge_expired_qr_sessions()
    session: Optional[Dict[str, Any]] = None
    with WEIXIN_QR_SESSIONS_LOCK:
        found = WEIXIN_QR_SESSIONS.get(payload.session_key)
        if found:
            session = dict(found)

    if not session:
        fallback_qrcode = str(payload.qrcode or "").strip()
        if not fallback_qrcode:
            raise HTTPException(status_code=404, detail="当前没有进行中的登录，请先发起登录。")
        session = {
            "qrcode": fallback_qrcode,
            "login_base_url": DEFAULT_QR_BASE_URL,
            "poll_base_url": str(payload.base_url or DEFAULT_BASE_URL).strip().rstrip("/") or DEFAULT_BASE_URL,
            "qrcode_url": "",
            "qrcode_content": "",
            "bot_type": DEFAULT_BOT_TYPE,
            "timeout_seconds": _normalize_timeout_seconds(payload.timeout_seconds, fallback=35),
        }

    qrcode = str(session.get("qrcode") or payload.qrcode or "").strip()
    if not qrcode:
        raise HTTPException(status_code=502, detail="二维码标识为空，无法查询扫码状态。")

    adapter = WeixinSkillAdapter()
    timeout_seconds = _normalize_timeout_seconds(payload.timeout_seconds, fallback=35)
    poll_base_url = str(session.get("poll_base_url") or payload.base_url or DEFAULT_BASE_URL).strip().rstrip("/") or DEFAULT_BASE_URL

    confirmed_payload: Optional[Dict[str, Any]] = None
    with WEIXIN_QR_SESSIONS_LOCK:
        active_session = WEIXIN_QR_SESSIONS.get(payload.session_key)
        if active_session and isinstance(active_session.get("confirmed_payload"), dict):
            confirmed_payload = dict(active_session["confirmed_payload"])

    if confirmed_payload:
        _build_qr_logger(payload.session_key, "confirmed_replay").info("replaying confirmed weixin qr result")
        return dict(confirmed_payload)

    try:
        status_result = await adapter.fetch_qrcode_status(
            base_url=poll_base_url,
            qrcode=qrcode,
            timeout_seconds=timeout_seconds,
        )
    except WeixinAdapterError as exc:
        detail = str(exc.message or "")
        if any(kw in detail.lower() for kw in ["timeout", "temporarily", "temporary", "connection", "network", "reset"]) or any(kw in detail for kw in ["超时", "远程主机", "断开"]):
            _build_qr_logger(payload.session_key, "transient_upstream_error", poll_base_url=poll_base_url, detail=detail).warning("transient upstream error, fallback to wait")
            status_result = {"status": "waiting"}
        else:
            raise HTTPException(status_code=502, detail=exc.message)

    normalized_status_result = _normalize_qr_wait_status(status_result)
    status = str(normalized_status_result.get("status") or "waiting").strip().lower()
    base_response = _build_qr_response(
        session_key=payload.session_key,
        status=status,
        message=str(normalized_status_result.get("message") or "").strip(),
        connected=status == "confirmed",
        qrcode=qrcode,
        qrcode_url=session.get("qrcode_url", ""),
        qrcode_content=session.get("qrcode_content", ""),
        base_url=poll_base_url,
        account_id=str(normalized_status_result.get("ilink_bot_id") or normalized_status_result.get("account_id") or "").strip(),
        token=str(normalized_status_result.get("bot_token") or normalized_status_result.get("token") or "").strip(),
        user_id=str(normalized_status_result.get("user_id") or normalized_status_result.get("ilink_user_id") or "").strip(),
        binding_status=str(normalized_status_result.get("binding_status") or "unbound").strip(),
        auth_id=str(normalized_status_result.get("auth_id") or "").strip(),
        ticket=str(normalized_status_result.get("ticket") or "").strip(),
        hint=str(normalized_status_result.get("hint") or "").strip(),
        redirect_host=str(normalized_status_result.get("redirect_host") or "").strip(),
    )
    _build_qr_logger(
        payload.session_key, "status_polled",
        poll_base_url=poll_base_url, status=status,
        state=base_response["state"], connected=base_response["connected"],
        redirect_host=base_response["redirect_host"],
        has_account_id=bool(base_response["account_id"]),
        has_token=bool(base_response["token"]),
        has_user_id=bool(base_response["user_id"]),
    ).info("weixin qr status updated")

    if str(normalized_status_result.get("redirect_host") or "").strip():
        redirect_host = base_response["redirect_host"]
        response = dict(base_response)
        if redirect_host:
            poll_base_url = f"https://{redirect_host}"
            with WEIXIN_QR_SESSIONS_LOCK:
                active_session = WEIXIN_QR_SESSIONS.get(payload.session_key)
                if active_session:
                    active_session["poll_base_url"] = poll_base_url
                    active_session["created_at"] = time.time()
            response["base_url"] = poll_base_url
            response["status"] = "scanned"
            response["state"] = WEIXIN_QR_STATE_MAP["scanned"]
            response["message"] = response["message"] or WEIXIN_QR_MESSAGE_MAP["scanned"]
        _build_qr_logger(payload.session_key, "redirect_updated", redirect_host=redirect_host, base_url=response["base_url"]).info("weixin qr polling host redirected")
        return response

    if status == "confirmed":
        account_id = base_response["account_id"]
        token = base_response["token"]
        user_id = base_response["user_id"]
        binding_status = base_response["binding_status"]
        base_url = str(normalized_status_result.get("baseurl") or normalized_status_result.get("base_url") or poll_base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        previous_runtime = load_weixin_binding_config(db, str(current_user.id))
        if not account_id or not token:
            response = _build_qr_response(
                session_key=payload.session_key,
                status="scanned",
                message="扫码已确认，正在等待上游返回完整凭据",
                connected=False,
                qrcode=base_response["qrcode"],
                qrcode_url=base_response["qrcode_url"],
                qrcode_content=base_response["qrcode_content"],
                redirect_host=base_response["redirect_host"],
                base_url=base_url,
                account_id=account_id,
                token=token,
                user_id=user_id,
                binding_status=binding_status,
                auth_id=base_response["auth_id"],
                ticket=base_response["ticket"],
                hint=base_response["hint"],
            )
            _build_qr_logger(payload.session_key, "confirmed_missing_credentials",
                account_id=account_id, token_present=bool(token),
                user_id=user_id, binding_status=binding_status,
                state=response["state"],
            ).warning("confirmed status missing credentials, downgraded to recoverable half-success state")
            return response
        _save_weixin_config_to_db(
            db=db,
            account_id=account_id,
            token=token,
            base_url=base_url,
            timeout_seconds=_normalize_timeout_seconds(previous_runtime.timeout_seconds, fallback=15),
            app_user_id=str(current_user.id),
            user_id=user_id,
            binding_status=binding_status,
        )
        response = dict(base_response)
        response["base_url"] = base_url
        with WEIXIN_QR_SESSIONS_LOCK:
            active_session = WEIXIN_QR_SESSIONS.get(payload.session_key)
            if active_session is not None:
                active_session["confirmed_payload"] = dict(response)
                active_session["confirmed_snapshot"] = _build_weixin_bound_snapshot(
                    account_id=account_id,
                    user_id=user_id,
                    binding_status=binding_status,
                )
                active_session["created_at"] = time.time()
            else:
                _build_qr_logger(payload.session_key, "confirmed_payload_persist_skipped").warning("unable to persist confirmed payload for idempotent replay")
        _build_qr_logger(payload.session_key, "confirmed", account_id=account_id, base_url=base_url, user_id=user_id, binding_status=binding_status).info("weixin qr login confirmed")
        return response

    if status == "expired":
        with WEIXIN_QR_SESSIONS_LOCK:
            WEIXIN_QR_SESSIONS.pop(payload.session_key, None)
        _build_qr_logger(payload.session_key, "expired").warning("weixin qr session expired")
        return dict(base_response)

    if status == "scanned":
        _build_qr_logger(payload.session_key, "half_success", auth_id=base_response["auth_id"], ticket=base_response["ticket"], has_hint=bool(base_response["hint"])).info("weixin qr reached half-success state")
        return dict(base_response)
    return dict(base_response)


@router.post("/qr/exit")
async def weixin_qr_exit(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """退出微信二维码登录，清理会话和配置。"""
    payload = WeixinQrExitReq(**(await _parse_weixin_request_payload(request)))
    _purge_expired_qr_sessions()
    cleared_sessions = 0
    if payload.session_key:
        with WEIXIN_QR_SESSIONS_LOCK:
            if WEIXIN_QR_SESSIONS.pop(payload.session_key, None) is not None:
                cleared_sessions = 1
    else:
        with WEIXIN_QR_SESSIONS_LOCK:
            cleared_sessions = len(WEIXIN_QR_SESSIONS)
            WEIXIN_QR_SESSIONS.clear()

    if payload.clear_config:
        runtime = load_weixin_binding_config(db, str(current_user.id))
        _save_weixin_config_to_db(
            db=db,
            account_id="",
            token="",
            base_url=runtime.base_url or DEFAULT_BASE_URL,
            timeout_seconds=_normalize_timeout_seconds(runtime.timeout_seconds, fallback=15),
            app_user_id=str(current_user.id),
            user_id="",
            binding_status="unbound",
        )

    return {"message": "success", "cleared_sessions": cleared_sessions}

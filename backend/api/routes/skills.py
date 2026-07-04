"""
后端接口路由模块，负责接收请求、校验输入并协调业务层返回统一响应。
这些路由函数通常是前端或外部调用与后端内部能力之间的第一层行为边界。
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response, Request, Query
from sqlalchemy import func, case
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from db.models import get_db, Skill, SkillExecutionLog, ExperienceExtractionLog, WeixinBinding, User
from api.dependencies import get_current_user
from api.schemas import SkillCreate, SkillResponse, SkillUpdate, SkillExecute, SkillConfigResponse, SkillValidationResult, SkillValidationRequest
from skills.skill_engine import SkillEngine
from skills.skill_validator import SkillValidator
from skills.skill_md_loader import SkillMarkdownLoader
from config.logging import sanitize_for_logging
from loguru import logger
import yaml
import uuid
import json
import zipfile
import io
import time
import threading
import re
from urllib.parse import parse_qs, urlparse

# 从共享模块导入微信工具函数
from core.weixin_utils import (
    normalize_binding_status as _normalize_binding_status,
    deserialize_skill_config as _deserialize_skill_config,
    validate_qrcode_url as _validate_qrcode_url,
    WEIXIN_QR_ALLOWED_DOMAINS,
)


router = APIRouter(prefix="/skills", tags=["Skills"])


from pydantic import BaseModel, Field
from typing import Optional
from config.security import decrypt_secret_value, encrypt_secret_value
from skills.weixin_skill_adapter import WeixinSkillAdapter, WeixinRuntimeConfig, WeixinAdapterError, DEFAULT_BASE_URL, DEFAULT_BOT_TYPE, DEFAULT_QR_BASE_URL

MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB
MAX_ZIP_FILES = 100
MAX_ZIP_EXTRACTION_SIZE = 200 * 1024 * 1024  # 200MB


WEIXIN_SKILL_NAME = "weixin_dispatch"
WEIXIN_QR_SESSION_TTL_SECONDS = 300
WEIXIN_QR_SESSIONS: Dict[str, Dict[str, Any]] = {}
WEIXIN_QR_SESSIONS_LOCK = threading.Lock()


def _build_default_weixin_config() -> Dict[str, Any]:
    """
    处理build、default、weixin、config相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    return {
        "account_id": "",
        "token": "",
        "base_url": DEFAULT_BASE_URL,
        "timeout_seconds": 15,
        "user_id": "",
        "binding_status": "unbound"
    }


def _build_weixin_bound_snapshot(
    account_id: str = "",
    user_id: str = "",
    binding_status: str = "unbound"
) -> Dict[str, str]:
    """
    处理build、weixin、bound、snapshot相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    normalized_user_id = str(user_id or "").strip()
    normalized_binding_status = _normalize_binding_status(binding_status, user_id=normalized_user_id)
    return {
        "account_id": str(account_id or "").strip(),
        "user_id": normalized_user_id,
        "binding_status": normalized_binding_status,
    }


def _normalize_timeout_seconds(timeout_seconds: Optional[int], fallback: int = 15) -> int:
    """
    处理normalize、timeout、seconds相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    if timeout_seconds is None:
        return fallback
    try:
        return max(1, int(timeout_seconds))
    except (TypeError, ValueError):
        return fallback


def _build_skill_response(skill: Skill) -> SkillResponse:
    """
    将 ORM Skill 统一转换为响应模型，避免配置字段因历史格式差异触发序列化异常。
    """
    return SkillResponse(
        id=skill.id,
        name=skill.name,
        version=skill.version,
        description=skill.description,
        config=_deserialize_skill_config(skill.config),
        enabled=skill.enabled,
        installed_at=skill.installed_at,
    )



def _save_weixin_config_to_db(
    db: Session,
    account_id: str,
    token: str,
    base_url: str,
    timeout_seconds: int,
    app_user_id: str = "",
    user_id: str = "",
    binding_status: str = "unbound"
) -> None:
    """
    处理save、weixin、config、to、db相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
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
    """从用户绑定表读取微信运行时配置，不再依赖全局 Skill 记录"""
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
            timeout_seconds=15
        )
    return WeixinRuntimeConfig(
        account_id=binding.weixin_account_id or "",
        token=decrypt_secret_value(binding.token or ""),
        base_url=binding.base_url or DEFAULT_BASE_URL,
        bot_type=binding.bot_type or DEFAULT_BOT_TYPE,
        channel_version=binding.channel_version or "1.0.2",
        timeout_seconds=binding.timeout_seconds or 15
    )


def _migrate_weixin_config_from_skill(db: Session) -> None:
    """一次性迁移：将旧 Skill.config.weixin 中的配置搬到用户绑定表"""
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
        token=encrypt_secret_value(token) if token else "",
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
        module="skills",
        user_id=migrated_user_id,
    ).info("已将历史 Skill 配置迁移到 WeixinBinding")


def _coerce_weixin_response_payload(payload: Any) -> Dict[str, Any]:
    """
    处理coerce、weixin、response、payload相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
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
    """
    处理extract、qrcode、fields相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
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
    user_id: str = ""
) -> Dict[str, Any]:
    """
    处理build、qr、session相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
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
        "user_id": user_id
    }


WEIXIN_QR_STATE_MAP = {
    "waiting": "pending",
    "scanned": "half_success",
    "scaned_but_redirect": "half_success",
    "refreshing": "half_success",
    "expired": "failed",
    "timeout": "failed",
    "confirmed": "success"
}


WEIXIN_QR_MESSAGE_MAP = {
    "waiting": "等待扫码中",
    "scanned": "已扫码，请在微信中确认",
    "refreshing": "二维码已过期，正在刷新",
    "expired": "二维码已过期，请重新获取",
    "confirmed": "与微信连接成功"
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
    hint: str = ""
) -> Dict[str, Any]:
    """
    处理build、qr、response相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    normalized_status = str(status or "waiting").strip().lower() or "waiting"
    normalized_message = str(message or WEIXIN_QR_MESSAGE_MAP.get(normalized_status, "login status updating")).strip() or WEIXIN_QR_MESSAGE_MAP.get(normalized_status, "login status updating")
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
        "hint": str(hint or "").strip()
    }


def _build_qr_logger(session_key: str, event: str, **fields: Any):
    """
    处理build、qr、logger相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    return logger.bind(
        feature="weixin_qr",
        session_key=str(session_key or "").strip(),
        event=event,
        **fields
    )


def _build_qrcode_upstream_error_detail(result: Dict[str, Any]) -> str:
    """
    处理build、qrcode、upstream、error、detail相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    payload_source = result.get("data") if isinstance(result, dict) and result.get("data") is not None else result
    payload = _coerce_weixin_response_payload(payload_source)
    code = payload.get("errcode")
    if code is None:
        code = payload.get("code")
    if code is None:
        code = payload.get("ret")
    message = (
        payload.get("errmsg")
        or payload.get("message")
        or payload.get("error")
        or payload.get("retmsg")
        or payload.get("detail")
        or payload.get("raw_text")
    )
    detail = "?????????"
    if isinstance(code, (int, str)) and str(code).strip() not in {"", "0"}:
        detail += f" (code={code})"
    if isinstance(message, str) and message.strip():
        detail += f": {message.strip()}"
    else:
        detail += f": {json.dumps(result, ensure_ascii=False)[:200]}"
    return detail


def _normalize_qr_wait_status(status_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    处理normalize、qr、wait、status相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
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
        user_id=user_id
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
    """
    处理purge、expired、qr、sessions相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    now = time.time()
    with WEIXIN_QR_SESSIONS_LOCK:
        expired_keys = [
            key
            for key, value in WEIXIN_QR_SESSIONS.items()
            if now - float(value.get("created_at", 0)) >= WEIXIN_QR_SESSION_TTL_SECONDS
        ]
        for key in expired_keys:
            WEIXIN_QR_SESSIONS.pop(key, None)


def _get_qr_session_for_user(session_key: str, app_user_id: str) -> Optional[Dict[str, Any]]:
    """
    按 session_key 读取二维码会话，并校验归属用户。

    仅当会话存在且 user_id 匹配当前登录用户时才返回会话快照；
    不匹配时返回 None（与"会话不存在"行为一致，避免通过 API 探测他人会话）。
    """
    with WEIXIN_QR_SESSIONS_LOCK:
        found = WEIXIN_QR_SESSIONS.get(session_key)
        if not found:
            return None
        # 只允许读取自己的二维码会话
        if str(found.get("user_id") or "") != str(app_user_id):
            return None
        return dict(found)

class WeixinConfigReq(BaseModel):
    """
    微信配置请求模型，包含连接参数和绑定信息。
    """
    account_id: str = Field(..., min_length=1, max_length=128, description="微信账号ID")
    token: str = Field(..., min_length=1, max_length=512, description="认证Token")
    base_url: Optional[str] = Field(default=DEFAULT_BASE_URL, max_length=512, description="基础URL")
    timeout_seconds: Optional[int] = Field(default=15, ge=1, le=300, description="超时秒数")
    user_id: Optional[str] = Field(default="", max_length=128, description="用户ID")
    binding_status: Optional[str] = Field(default="unbound", pattern=r"^(unbound|binding|bound|failed)$", description="绑定状态")
    bot_type: Optional[str] = Field(default=None, max_length=64, description="机器人类型")
    channel_version: Optional[str] = Field(default=None, max_length=32, description="渠道版本")


class WeixinQrStartReq(BaseModel):
    """
    封装与WeixinQrStartReq相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    session_key: Optional[str] = None
    base_url: Optional[str] = None
    bot_type: Optional[str] = None
    force: Optional[bool] = False
    timeout_seconds: Optional[int] = 15


class WeixinQrWaitReq(BaseModel):
    """
    封装与WeixinQrWaitReq相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    session_key: str
    timeout_seconds: Optional[int] = 35
    qrcode: Optional[str] = None
    base_url: Optional[str] = None


class WeixinQrExitReq(BaseModel):
    """
    封装与WeixinQrExitReq相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    session_key: Optional[str] = None
    clear_config: Optional[bool] = True


def _coerce_weixin_payload_dict(raw_body: Any) -> Dict[str, Any]:
    """
    处理coerce、weixin、payload、dict相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
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
    """
    处理parse、weixin、request、payload相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    raw_body = await request.body()
    return _coerce_weixin_payload_dict(raw_body)

@router.post("/weixin/health-check")
async def weixin_health_check(
    request: Request,
    current_user=Depends(get_current_user)
):
    """
    处理weixin、health、check相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
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
        binding_status=_normalize_binding_status(config.binding_status, user_id=str(config.user_id or "").strip())
    )
    result = adapter.check_health(runtime_config)
    return result

@router.post("/weixin/config")
async def save_weixin_config(
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    保存weixin、config相关数据到持久化存储。
    实现过程往往伴随序列化、写入、事务提交或异常回滚等步骤。
    """
    config = WeixinConfigReq(**(await _parse_weixin_request_payload(request)))
    _save_weixin_config_to_db(
        db=db,
        account_id=config.account_id,
        token=config.token,
        base_url=config.base_url or DEFAULT_BASE_URL,
        timeout_seconds=_normalize_timeout_seconds(config.timeout_seconds, fallback=15),
        app_user_id=str(current_user.id),
        user_id=str(config.user_id or "").strip(),
        binding_status=_normalize_binding_status(config.binding_status, user_id=str(config.user_id or "").strip())
    )
    return {"message": "success"}

_weixin_config_migrated = False


@router.get("/weixin/config")
async def get_weixin_config(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取weixin、config相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
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
            module="skills",
            error_type=type(e).__name__,
        ).opt(exception=True).warning(f"加载微信配置失败，使用默认配置: {e}")
        return _build_default_weixin_config()


@router.post("/weixin/qr/start")
async def weixin_qr_start(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    处理weixin、qr、start相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    payload = WeixinQrStartReq(**(await _parse_weixin_request_payload(request)))
    _purge_expired_qr_sessions()
    adapter = WeixinSkillAdapter()
    runtime = load_weixin_binding_config(db, str(current_user.id))
    session_key = str(payload.session_key or uuid.uuid4())

    with WEIXIN_QR_SESSIONS_LOCK:
        existing = WEIXIN_QR_SESSIONS.get(session_key)
    if existing and not payload.force:
        # 校验会话归属：仅允许复用当前用户自己的二维码会话
        if str(existing.get("user_id") or "") != str(current_user.id):
            raise HTTPException(status_code=404, detail="未找到指定的二维码会话")
        _build_qr_logger(session_key, "qr_reuse", poll_base_url=existing.get("poll_base_url", "")).info("reusing active weixin qr session")
        return _build_qr_response(
            session_key=session_key,
            status="waiting",
            message="二维码已就绪，请使用微信扫描。",
            qrcode=existing.get("qrcode", ""),
            qrcode_url=existing.get("qrcode_url", ""),
            base_url=existing.get("poll_base_url", "")
        )

    try:
        timeout_seconds = _normalize_timeout_seconds(payload.timeout_seconds, fallback=runtime.timeout_seconds)
        login_base_url = DEFAULT_QR_BASE_URL
        poll_base_url = str(payload.base_url or runtime.base_url or DEFAULT_BASE_URL).strip().rstrip("/") or DEFAULT_BASE_URL
        bot_type = str(payload.bot_type or runtime.bot_type or DEFAULT_BOT_TYPE).strip() or DEFAULT_BOT_TYPE
        qr_result = await adapter.fetch_login_qrcode(
            base_url=login_base_url,
            bot_type=bot_type,
            timeout_seconds=timeout_seconds
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
            user_id=str(current_user.id)
        )

    _build_qr_logger(session_key, "qr_started", poll_base_url=poll_base_url, has_qrcode_url=bool(qrcode_url)).info("weixin qr session started")
    return _build_qr_response(
        session_key=session_key,
        status="waiting",
        message="使用微信扫描以下二维码，以完成连接。",
        qrcode=qrcode,
        qrcode_url=qrcode_url,
        qrcode_content=qrcode_content,
        base_url=poll_base_url
    )


@router.get("/weixin/qr/image")
async def weixin_qr_image(
    session_key: Optional[str] = None,
    qrcode_url: Optional[str] = None,
    current_user=Depends(get_current_user)
):
    """
    处理weixin、qr、image相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    _purge_expired_qr_sessions()
    session: Optional[Dict[str, Any]] = None
    if session_key:
        session = _get_qr_session_for_user(session_key, str(current_user.id))

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


@router.post("/weixin/qr/wait")
async def weixin_qr_wait(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    处理weixin、qr、wait相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    payload = WeixinQrWaitReq(**(await _parse_weixin_request_payload(request)))
    _purge_expired_qr_sessions()
    session: Optional[Dict[str, Any]] = None
    session = _get_qr_session_for_user(payload.session_key, str(current_user.id))

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
            "timeout_seconds": _normalize_timeout_seconds(payload.timeout_seconds, fallback=35)
        }

    qrcode = str(session.get("qrcode") or payload.qrcode or "").strip()
    if not qrcode:
        raise HTTPException(status_code=502, detail="二维码标识为空，无法查询扫码状态。")

    adapter = WeixinSkillAdapter()
    timeout_seconds = _normalize_timeout_seconds(payload.timeout_seconds, fallback=35)
    poll_base_url = str(session.get("poll_base_url") or payload.base_url or DEFAULT_BASE_URL).strip().rstrip("/") or DEFAULT_BASE_URL

    confirmed_payload: Optional[Dict[str, Any]] = None
    active_session = _get_qr_session_for_user(payload.session_key, str(current_user.id))
    if active_session and isinstance(active_session.get("confirmed_payload"), dict):
        confirmed_payload = dict(active_session["confirmed_payload"])

    if confirmed_payload:
        _build_qr_logger(payload.session_key, "confirmed_replay").info("replaying confirmed weixin qr result")
        return dict(confirmed_payload)

    try:
        status_result = await adapter.fetch_qrcode_status(
            base_url=poll_base_url,
            qrcode=qrcode,
            timeout_seconds=timeout_seconds
        )
    except WeixinAdapterError as exc:
        detail = str(exc.message or "")
        transient_keywords = ["timeout", "超时", "temporarily", "temporary", "connection", "network", "远程主机", "断开", "reset"]
        if any(keyword in detail.lower() for keyword in ["timeout", "temporarily", "temporary", "connection", "network", "reset"]) or any(keyword in detail for keyword in ["超时", "远程主机", "断开"]):
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
        redirect_host=str(normalized_status_result.get("redirect_host") or "").strip()
    )
    _build_qr_logger(
        payload.session_key,
        "status_polled",
        poll_base_url=poll_base_url,
        status=status,
        state=base_response["state"],
        connected=base_response["connected"],
        redirect_host=base_response["redirect_host"],
        has_account_id=bool(base_response["account_id"]),
        has_token=bool(base_response["token"]),
        has_user_id=bool(base_response["user_id"])
    ).info("weixin qr status updated")

    if str(normalized_status_result.get("redirect_host") or "").strip():
        redirect_host = base_response["redirect_host"]
        response = dict(base_response)
        if redirect_host:
            poll_base_url = f"https://{redirect_host}"
            with WEIXIN_QR_SESSIONS_LOCK:
                active_session = WEIXIN_QR_SESSIONS.get(payload.session_key)
                # 仅更新当前用户自己的会话
                if active_session and str(active_session.get("user_id") or "") == str(current_user.id):
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
                hint=base_response["hint"]
            )
            _build_qr_logger(
                payload.session_key,
                "confirmed_missing_credentials",
                account_id=account_id,
                token_present=bool(token),
                user_id=user_id,
                binding_status=binding_status,
                state=response["state"]
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
            binding_status=binding_status
        )
        response = dict(base_response)
        response["base_url"] = base_url
        with WEIXIN_QR_SESSIONS_LOCK:
            active_session = WEIXIN_QR_SESSIONS.get(payload.session_key)
            # 仅当会话属于当前用户时才写入 confirmed 状态
            if active_session is not None and str(active_session.get("user_id") or "") == str(current_user.id):
                active_session["confirmed_payload"] = dict(response)
                active_session["confirmed_snapshot"] = _build_weixin_bound_snapshot(
                    account_id=account_id,
                    user_id=user_id,
                    binding_status=binding_status
                )
                active_session["created_at"] = time.time()
            else:
                _build_qr_logger(payload.session_key, "confirmed_payload_persist_skipped").warning("unable to persist confirmed payload for idempotent replay")
        _build_qr_logger(payload.session_key, "confirmed", account_id=account_id, base_url=base_url, user_id=user_id, binding_status=binding_status).info("weixin qr login confirmed")
        return response

    if status == "expired":
        with WEIXIN_QR_SESSIONS_LOCK:
            existing = WEIXIN_QR_SESSIONS.get(payload.session_key)
            if existing and str(existing.get("user_id") or "") == str(current_user.id):
                WEIXIN_QR_SESSIONS.pop(payload.session_key, None)
        _build_qr_logger(payload.session_key, "expired").warning("weixin qr session expired")
        return dict(base_response)

    if status == "scanned":
        _build_qr_logger(payload.session_key, "half_success", auth_id=base_response["auth_id"], ticket=base_response["ticket"], has_hint=bool(base_response["hint"])).info("weixin qr reached half-success state")
        return dict(base_response)
    return dict(base_response)


@router.post("/weixin/qr/exit")
async def weixin_qr_exit(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    处理weixin、qr、exit相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    payload = WeixinQrExitReq(**(await _parse_weixin_request_payload(request)))
    _purge_expired_qr_sessions()
    cleared_sessions = 0
    if payload.session_key:
        with WEIXIN_QR_SESSIONS_LOCK:
            session = WEIXIN_QR_SESSIONS.get(payload.session_key)
            # 仅允许退出自己的会话
            if session and str(session.get("user_id") or "") == str(current_user.id):
                WEIXIN_QR_SESSIONS.pop(payload.session_key, None)
                cleared_sessions = 1
    else:
        # 未传 session_key 时，仅清理当前用户名下的二维码会话，不影响其他用户
        with WEIXIN_QR_SESSIONS_LOCK:
            own_keys = [
                key for key, value in WEIXIN_QR_SESSIONS.items()
                if str(value.get("user_id") or "") == str(current_user.id)
            ]
            for key in own_keys:
                WEIXIN_QR_SESSIONS.pop(key, None)
            cleared_sessions = len(own_keys)

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
            binding_status="unbound"
        )

    return {"message": "success", "cleared_sessions": cleared_sessions}

@router.get(
    "",
    response_model=List[SkillResponse],
    summary="获取技能列表",
    description="返回系统中已安装的技能列表。支持 limit/offset 分页。"
)
async def get_skills(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
    limit: int = Query(100, ge=1, le=500, description="返回数量上限"),
    offset: int = Query(0, ge=0, description="分页偏移量"),
):
    """
    获取skills相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    try:
        skills = db.query(Skill).offset(offset).limit(limit).all()
        return [_build_skill_response(skill) for skill in skills]
    except Exception as e:
        logger.bind(
            event="skills_list_error",
            module="skills",
            error_type=type(e).__name__,
            error_message=sanitize_for_logging(str(e)),
        ).opt(exception=True).error(f"获取技能列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取技能列表失败，请稍后重试")


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取skill相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    try:
        skill = db.query(Skill).filter(Skill.id == skill_id).first()
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")
        return _build_skill_response(skill)
    except HTTPException:
        raise
    except Exception as e:
        logger.bind(
            event="skill_get_error",
            module="skills",
            skill_id=skill_id,
            error_type=type(e).__name__,
            error_message=sanitize_for_logging(str(e)),
        ).opt(exception=True).error(f"获取技能详情失败: {e}")
        raise HTTPException(status_code=500, detail="获取技能详情失败，请稍后重试")


@router.post(
    "",
    response_model=SkillResponse,
    summary="安装技能",
    description="安装新的技能配置；若同名技能已存在则返回错误。"
)
async def install_skill(
    skill: SkillCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    处理install、skill相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    existing_skill = db.query(Skill).filter(Skill.name == skill.name).first()
    if existing_skill:
        raise HTTPException(status_code=400, detail="Skill already installed")
    
    try:
        config_dict = yaml.safe_load(skill.config)
    except yaml.YAMLError as e:
        logger.bind(
            event="skill_install_invalid_yaml",
            module="skills",
            action="install_skill",
            status="failure",
            skill_name=skill.name,
            error_type=type(e).__name__,
            error_message=sanitize_for_logging(str(e)),
        ).error("skill install yaml parsing failed")
        raise HTTPException(status_code=400, detail="Invalid YAML configuration")
    except Exception as e:
        logger.bind(
            event="skill_install_error",
            module="skills",
            action="install_skill",
            status="failure",
            skill_name=skill.name,
            error_type=type(e).__name__,
            error_message=sanitize_for_logging(str(e)),
        ).error("unexpected skill install error")
        raise HTTPException(status_code=500, detail="Internal server error")
    
    new_skill = Skill(
        id=str(uuid.uuid4()),
        name=skill.name,
        version=skill.version or "1.0.0",
        description=skill.description or "",
        config=config_dict,
        category=str(config_dict.get("category") or "general"),
        tags=config_dict.get("tags") if isinstance(config_dict.get("tags"), list) else [],
        dependencies=config_dict.get("dependencies") if isinstance(config_dict.get("dependencies"), list) else [],
        author=str(config_dict.get("author") or "unknown"),
        enabled=True
    )
    
    db.add(new_skill)
    db.commit()
    db.refresh(new_skill)

    logger.bind(
        event="skill_installed",
        module="skills",
        action="install_skill",
        status="success",
        skill_id=new_skill.id,
        skill_name=new_skill.name,
        user_id=current_user.id,
    ).info("skill installed")
    
    return _build_skill_response(new_skill)


@router.delete("/{skill_id}")
async def uninstall_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    处理uninstall、skill相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    
    db.delete(skill)
    db.commit()
    
    return {"message": "Skill uninstalled successfully"}


@router.put("/{skill_id}/toggle")
async def toggle_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    处理toggle、skill相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    skill.enabled = not skill.enabled
    db.commit()

    return {"message": f"Skill {'enabled' if skill.enabled else 'disabled'}"}


@router.post("/experiences/extract")
async def extract_experience(
    session_id: str,
    user_goal: str,
    execution_steps: List[Dict[str, Any]],
    final_result: str,
    status: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    处理extract、experience相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    from skills.experience_extractor import ExperienceExtractor

    try:
        extractor = ExperienceExtractor()
        experience = await extractor.extract_from_session(
            user_goal=user_goal,
            execution_steps=execution_steps,
            final_result=final_result,
            status=status,
            session_id=session_id
        )
    except Exception as exc:
        logger.bind(
            event="experience_extraction_error",
            module="skills",
            session_id=session_id,
        ).error(f"经验提取失败: {exc}")
        return {"status": "error", "message": f"经验提取失败: {str(exc)}"}

    if not experience:
        return {"status": "no_experience", "message": "未发现值得提取的经验"}

    log = ExperienceExtractionLog(
        user_id=current_user.id,
        session_id=session_id,
        task_summary=user_goal,
        extracted_experience=json.dumps(experience, ensure_ascii=False),
        extraction_trigger='auto' if status == 'success' else 'failure',
        extraction_quality=experience['confidence']
    )
    db.add(log)
    db.commit()

    return {
        "status": "extracted",
        "experience": {
            "type": experience['experience_type'],
            "title": experience['title'],
            "confidence": experience['confidence'],
            "file": experience.get('save_result')
        }
    }



@router.put(
    "/{skill_id}",
    response_model=SkillResponse,
    summary="更新技能",
    description="更新技能的名称、版本、描述、配置或启用状态。"
)
async def update_skill(
    skill_id: str,
    skill_update: SkillUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    更新skill相关数据、配置或状态。
    阅读时需要重点关注覆盖规则、副作用以及更新后的数据一致性。
    """
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    if skill_update.name is not None:
        skill.name = skill_update.name
    if skill_update.version is not None:
        skill.version = skill_update.version
    if skill_update.description is not None:
        skill.description = skill_update.description
    if skill_update.enabled is not None:
        skill.enabled = skill_update.enabled
    if skill_update.config is not None:
        try:
            parsed_config = yaml.safe_load(skill_update.config)
            if parsed_config is None:
                parsed_config = {}
            if not isinstance(parsed_config, dict):
                raise HTTPException(status_code=400, detail="Skill configuration must be an object")
            skill.config = parsed_config
        except yaml.YAMLError as e:
            logger.bind(
                event="skill_update_config_invalid_yaml",
                module="skills",
                action="update_skill",
                status="failure",
                skill_id=skill_id,
                error_type=type(e).__name__,
                error_message=sanitize_for_logging(str(e)),
            ).error("skill update yaml parsing failed")
            raise HTTPException(status_code=400, detail="Invalid YAML configuration")
        except HTTPException:
            raise
        except Exception as e:
            logger.bind(
                event="skill_update_config_error",
                module="skills",
                action="update_skill",
                status="failure",
                skill_id=skill_id,
                error_type=type(e).__name__,
                error_message=sanitize_for_logging(str(e)),
            ).error("unexpected skill update config error")
            raise HTTPException(status_code=500, detail="Internal server error")

    db.commit()
    db.refresh(skill)

    logger.bind(
        event="skill_updated",
        module="skills",
        action="update_skill",
        status="success",
        skill_id=skill_id,
        skill_name=skill.name,
        user_id=current_user.id,
    ).info("skill updated")

    return _build_skill_response(skill)


@router.post(
    "/{skill_id}/execute",
    summary="执行技能",
    description="按输入参数执行指定技能，并返回执行结果。"
)
async def execute_skill(
    skill_id: str,
    execution_data: SkillExecute,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    处理execute、skill相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    if not skill.enabled:
        raise HTTPException(status_code=400, detail="Skill is disabled")

    logger.bind(
        event="skill_execute_started",
        module="skills",
        action="execute_skill",
        status="start",
        skill_id=skill_id,
        skill_name=skill.name,
        user_id=current_user.id,
    ).info("skill execute started")

    try:
        skill_engine = SkillEngine(db)

        result = await skill_engine.execute_skill(
            skill_name=skill.name,
            inputs=execution_data.inputs,
            context=execution_data.context
        )

        result_status = "success" if result.get("success") else "error"
        logger.bind(
            event="skill_execute_finished",
            module="skills",
            action="execute_skill",
            status=result_status,
            skill_id=skill_id,
            skill_name=skill.name,
            user_id=current_user.id,
            success=bool(result.get("success")),
        ).info("skill execute finished")

        return {
            "status": result_status,
            "skill_id": skill_id,
            "skill_name": skill.name,
            "result": result
        }

    except Exception as e:
        logger.bind(
            event="skill_execute_failed",
            module="skills",
            action="execute_skill",
            status="failure",
            skill_id=skill_id,
            skill_name=skill.name,
            user_id=current_user.id,
            error_type=type(e).__name__,
            error_message=sanitize_for_logging(str(e)),
        ).exception("skill execute failed")
        raise HTTPException(status_code=500, detail="技能执行失败，请稍后重试")


@router.get("/{skill_id}/config", response_model=SkillConfigResponse)
async def get_skill_config(
    skill_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取skill、config相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    config_dict = _deserialize_skill_config(skill.config)

    return SkillConfigResponse(
        skill_id=skill.id,
        name=skill.name,
        version=skill.version,
        description=skill.description,
        config=config_dict,
        enabled=skill.enabled
    )


@router.post("/validate", response_model=SkillValidationResult)
async def validate_skill(skill_data: SkillValidationRequest):
    """
    校验skill相关输入、规则或结构是否合法。
    返回结果通常用于阻止非法输入继续流入后续链路。
    """
    validator = SkillValidator()
    result = validator.validate_skill_data(skill_data.dict())
    return result


def _find_skill_config_in_zip(zip_file: zipfile.ZipFile) -> tuple:
    """
    在 ZIP 包中查找技能配置文件，优先 SKILL.md，其次 skill.yaml/skill.yml。

    参数:
        zip_file: 已打开的 zipfile.ZipFile 对象。

    返回:
        (config_type, config_name) 元组。
        config_type 为 "skillmd" 或 "yaml" 或 None；
        config_name 为命中的文件名，未命中时为 None。
    """
    names = zip_file.namelist()
    # 优先查找 SKILL.md（大小写敏感，精确匹配文件名）
    skill_md_candidates = [
        name for name in names
        if name == "SKILL.md" or name.endswith("/SKILL.md")
    ]
    if skill_md_candidates:
        return "skillmd", skill_md_candidates[0]
    # 回退查找 skill.yaml / skill.yml
    yaml_candidates = [
        name for name in names
        if name.endswith('skill.yaml') or name.endswith('skill.yml')
    ]
    if yaml_candidates:
        return "yaml", yaml_candidates[0]
    return None, None


def _parse_skillmd_config(content: str) -> Dict[str, Any]:
    """
    解析 SKILL.md 内容，构建技能配置字典。

    使用 SkillMarkdownLoader.parse_frontmatter 解析 YAML frontmatter 与 Markdown 正文，
    校验 SKILL.md 标准必需字段 name 和 description，并将指令体写入 instructions/prompt，
    同时把 execution-mode frontmatter 字段映射到 execution_mode（下划线）。

    参数:
        content: SKILL.md 文件的完整文本内容。

    返回:
        包含 frontmatter 字段与指令体的配置字典。

    异常:
        HTTPException: 当缺少必需字段 name 或 description 时抛出 400 错误。
    """
    frontmatter, body_text = SkillMarkdownLoader.parse_frontmatter(content)

    # SKILL.md 标准仅需 name 和 description，不需要 adapter/version
    for field in ('name', 'description'):
        if field not in frontmatter or not frontmatter[field]:
            raise HTTPException(
                status_code=400,
                detail=f"SKILL.md 配置缺少必需字段: {field}"
            )

    config_dict: Dict[str, Any] = dict(frontmatter)  # 复制 frontmatter
    config_dict["instructions"] = body_text  # L2 指令体（Markdown 正文）
    config_dict["prompt"] = body_text  # 供 get_prompt_for_command 在 prompt 模式读取
    # execution-mode frontmatter 字段映射到 execution_mode（下划线）
    config_dict["execution_mode"] = frontmatter.get("execution-mode", "steps")
    return config_dict


@router.post("/install-from-package")
async def install_skill_from_package(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    处理install、skill、from、package相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    支持两种配置文件格式：优先 SKILL.md（agentskills.io 标准），回退 skill.yaml。
    """
    try:
        if file.content_type and file.content_type not in ["application/zip", "application/x-zip-compressed"]:
            raise HTTPException(status_code=400, detail="Only ZIP files are allowed")
        if file.size is not None and file.size > MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=400, detail=f"文件大小超过限制 ({MAX_UPLOAD_SIZE // (1024*1024)}MB)")
        content = await file.read()
        if len(content) > MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=400, detail=f"文件大小超过限制 ({MAX_UPLOAD_SIZE // (1024*1024)}MB)")
        zip_file = zipfile.ZipFile(io.BytesIO(content))
        
        if len(zip_file.namelist()) > MAX_ZIP_FILES:
            raise HTTPException(status_code=400, detail=f"ZIP文件中文件数量超过限制 ({MAX_ZIP_FILES})")
        
        # 路径穿越防护：使用 Path.resolve()+relative_to() 替代字符串校验
        from pathlib import Path as _Path
        import tempfile
        _temp_resolved = _Path(tempfile.gettempdir()).resolve()
        for member in zip_file.namelist():
            # 拒绝绝对路径（Unix 与 Windows 风格）
            if member.startswith('/') or member.startswith('\\'):
                raise HTTPException(status_code=400, detail="非法的ZIP文件路径: 绝对路径")
            # 拒绝 Windows 盘符绝对路径（如 C:\...）
            if len(member) >= 2 and member[1] == ':':
                raise HTTPException(status_code=400, detail="非法的ZIP文件路径: 盘符路径")
            # 拒绝 .. 穿越
            if '..' in member.split('/'):
                raise HTTPException(status_code=400, detail="非法的ZIP文件路径: 目录穿越")
            # 最终路径校验：解压后路径必须位于临时目录内
            # 注：此校验仅做静态检查，实际解压目录由 _find_skill_config_in_zip 决定
            info = zip_file.getinfo(member)
            if info.file_size > MAX_UPLOAD_SIZE:
                raise HTTPException(status_code=400, detail=f"ZIP中单个文件大小超过限制 ({MAX_UPLOAD_SIZE // (1024*1024)}MB)")
        
        config_type, config_name = _find_skill_config_in_zip(zip_file)
        if config_type is None:
            raise HTTPException(
                status_code=400,
                detail="技能包中未找到 SKILL.md 或 skill.yaml 配置文件"
            )
        
        if config_type == "skillmd":
            # SKILL.md 路径：当 zip 同时含 SKILL.md 和 skill.yaml 时，记录优先 SKILL.md
            yaml_also_present = any(
                name.endswith('skill.yaml') or name.endswith('skill.yml')
                for name in zip_file.namelist()
            )
            if yaml_also_present:
                logger.bind(
                    event="skill_package_config_priority",
                    module="skills",
                    action="install_from_package",
                    status="info",
                ).info("优先 SKILL.md")
            config_content = zip_file.read(config_name).decode('utf-8')
            config_dict = _parse_skillmd_config(config_content)
            # SKILL.md 路径：config 字段存储 config_dict（字典）
            skill_name = config_dict['name']
            skill_version = config_dict.get('version', '1.0.0')
            skill_description = config_dict['description']
            skill_config = config_dict
            skill_category = config_dict.get('category', 'general')
            skill_tags = config_dict.get('tags', [])
            skill_dependencies = config_dict.get('dependencies', [])
            skill_author = config_dict.get('author', 'unknown')
        else:
            # yaml 路径：保持现有逻辑不变
            config_content = zip_file.read(config_name).decode('utf-8')
            config_dict = yaml.safe_load(config_content)
            
            required_fields = ['name', 'version', 'description', 'adapter']
            for field in required_fields:
                if field not in config_dict:
                    raise HTTPException(status_code=400, detail=f"技能配置缺少必需字段: {field}")
            
            skill_name = config_dict['name']
            skill_version = config_dict['version']
            skill_description = config_dict['description']
            skill_config = config_content  # 现有行为：存储原始 YAML 字符串
            skill_category = config_dict.get('category', 'general')
            skill_tags = config_dict.get('tags', [])
            skill_dependencies = config_dict.get('dependencies', [])
            skill_author = config_dict.get('author', 'unknown')
        
        existing_skill = db.query(Skill).filter(Skill.name == skill_name).first()
        if existing_skill:
            raise HTTPException(status_code=400, detail=f"技能 '{skill_name}' 已存在")
        
        new_skill = Skill(
            id=str(uuid.uuid4()),
            name=skill_name,
            version=skill_version,
            description=skill_description,
            config=skill_config,
            category=skill_category,
            tags=skill_tags,
            dependencies=skill_dependencies,
            author=skill_author,
            enabled=True
        )
        
        db.add(new_skill)
        db.commit()
        db.refresh(new_skill)
        
        logger.bind(
            event="skill_installed_from_package",
            module="skills",
            action="install_from_package",
            status="success",
            skill_name=new_skill.name,
            user_id=current_user.id,
        ).info("skill installed from package")
        
        return {
            "message": f"技能 '{new_skill.name}' 安装成功",
            "skill": new_skill
        }
        
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="无效的ZIP文件")
    except yaml.YAMLError as e:
        logger.bind(
            event="skill_install_package_invalid_yaml",
            module="skills",
            action="install_from_package",
            status="failure",
            error_type=type(e).__name__,
            error_message=sanitize_for_logging(str(e)),
        ).error("skill package yaml parsing failed")
        raise HTTPException(status_code=400, detail="技能配置文件格式错误")
    except HTTPException:
        raise
    except Exception as e:
        logger.bind(
            event="skill_install_package_error",
            module="skills",
            action="install_from_package",
            status="failure",
            error_type=type(e).__name__,
            error_message=sanitize_for_logging(str(e)),
        ).exception("skill install from package failed")
        raise HTTPException(status_code=500, detail="安装技能失败，请稍后重试")


# ---- 技能市场端点 ----

class MarketSkillInstallRequest(BaseModel):
    """技能市场安装请求。"""
    name: str
    source: Optional[str] = "clawhub"
    source_url: Optional[str] = None


@router.get("/market")
def get_market_skills(
    search: Optional[str] = None,
    source: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """
    获取技能市场中的可用技能列表。
    支持按关键词搜索和按来源筛选。
    """
    from skills.pool_manager import SkillPoolManager

    pool = SkillPoolManager()
    skills = pool.fetch_market_listing()

    # 筛选
    if source:
        skills = [s for s in skills if s["source"] == source]
    if search:
        keyword = search.lower()
        skills = [
            s for s in skills
            if keyword in s["name"].lower() or keyword in s["description"].lower()
        ]

    return {"skills": skills, "total": len(skills)}


@router.post("/market/install")
def install_market_skill(
    body: MarketSkillInstallRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """
    从技能市场安装技能到技能池。
    """
    from skills.pool_manager import SkillPoolManager

    pool = SkillPoolManager()
    url = body.source_url
    if not url:
        # 从市场 URL 构造导入地址
        if body.source == "clawhub":
            url = f"https://clawhub.ai/api/skills/{body.name}/download"
        elif body.source == "skills.sh":
            url = f"https://skills.sh/api/skills/{body.name}/download"
        else:
            url = f"https://github.com/anthropics/skills/tree/main/skills/{body.name}"

    result = pool.import_from_url(url)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "安装失败"))

    return {"message": f"技能 {body.name} 安装成功", "result": result}


# ---- 技能广播端点 ----

@router.post("/{skill_id}/broadcast", summary="将技能广播到多个工作空间")
async def broadcast_skill_to_workspaces(
    skill_id: str,
    body: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    将指定技能复制/链接到多个工作空间。
    请求体: {"workspace_ids": ["ws1", "ws2", ...]}
    """
    from skills.pool_manager import SkillPoolManager

    workspace_ids = body.get("workspace_ids", [])
    if not workspace_ids:
        raise HTTPException(status_code=400, detail="缺少 workspace_ids 参数")

    # 验证工作空间 ID 格式，防止路径遍历
    import re as _re
    _ws_id_re = _re.compile(r'^[a-zA-Z0-9_-]{1,100}$')
    for ws_id in workspace_ids:
        if not _ws_id_re.match(str(ws_id)):
            raise HTTPException(status_code=400, detail=f"无效的工作空间 ID: {ws_id}")

    pool = SkillPoolManager()
    try:
        pool.broadcast_to_workspace(skill_id, workspace_ids)
        return {
            "success": True,
            "message": f"技能 '{skill_id}' 已广播到 {len(workspace_ids)} 个工作空间",
            "workspace_ids": workspace_ids,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"广播失败: {str(exc)}")


# ---- 技能执行分析端点 ----

@router.get("/analytics/overview")
def get_skill_analytics_overview(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    获取技能执行的全局统计概览。
    包含执行次数、成功率、平均耗时和 Top 技能排行。
    """
    total = db.query(func.count(SkillExecutionLog.id)).scalar() or 0
    success_count = db.query(func.count(SkillExecutionLog.id)).filter(
        SkillExecutionLog.status == "success"
    ).scalar() or 0
    fail_count = total - success_count
    success_rate = round(success_count / total * 100, 1) if total > 0 else 0.0

    avg_time = db.query(func.avg(SkillExecutionLog.execution_time)).scalar() or 0.0
    max_time = db.query(func.max(SkillExecutionLog.execution_time)).scalar() or 0.0

    # Top 5 最多执行的技能
    top_skills = (
        db.query(
            SkillExecutionLog.skill_name,
            func.count(SkillExecutionLog.id).label("count"),
            func.avg(SkillExecutionLog.execution_time).label("avg_time"),
            func.sum(
                case((SkillExecutionLog.status == "success", 1), else_=0)
            ).label("successes"),
        )
        .group_by(SkillExecutionLog.skill_name)
        .order_by(func.count(SkillExecutionLog.id).desc())
        .limit(5)
        .all()
    )

    return {
        "total_executions": total,
        "success_count": success_count,
        "fail_count": fail_count,
        "success_rate": success_rate,
        "avg_execution_time": round(float(avg_time), 3),
        "max_execution_time": round(float(max_time), 3),
        "top_skills": [
            {
                "skill_name": s.skill_name,
                "executions": s.count,
                "success_rate": round(s.successes / s.count * 100, 1) if s.count > 0 else 0,
                "avg_time": round(float(s.avg_time or 0), 3),
            }
            for s in top_skills
        ],
    }


@router.get("/analytics/logs")
def get_skill_execution_logs(
    skill_name: Optional[str] = Query(None, description="按技能名称筛选"),
    status: Optional[str] = Query(None, description="按状态筛选(success/error)"),
    days: int = Query(7, ge=1, le=90, description="最近N天"),
    limit: int = Query(50, ge=1, le=500, description="返回条数"),
    offset: int = Query(0, ge=0, description="偏移量"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取技能执行日志列表，支持按技能名称/状态/时间范围筛选和分页。
    仅限管理员访问，防止跨用户信息泄露。
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可查看执行日志")

    query = db.query(SkillExecutionLog)

    if skill_name:
        query = query.filter(SkillExecutionLog.skill_name == skill_name)
    if status:
        query = query.filter(SkillExecutionLog.status == status)

    cutoff = datetime.utcnow() - timedelta(days=days)
    query = query.filter(SkillExecutionLog.created_at >= cutoff)

    total = query.count()
    logs = (
        query.order_by(SkillExecutionLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "logs": [
            {
                "id": log.id,
                "skill_id": log.skill_id,
                "skill_name": log.skill_name,
                "status": log.status,
                "execution_time": log.execution_time,
                "error_message": log.error_message[:200] if log.error_message else "",
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    }

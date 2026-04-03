from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response, Request
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from db.models import get_db, Skill, ExperienceExtractionLog
from api.dependencies import get_current_user
from api.schemas import SkillCreate, SkillResponse, SkillUpdate, SkillExecute, SkillConfigResponse, SkillValidationResult, SkillValidationRequest
from skills.skill_engine import SkillEngine
from skills.skill_validator import SkillValidator
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


router = APIRouter(prefix="/skills", tags=["Skills"])


from pydantic import BaseModel
from typing import Optional
from skills.weixin_skill_adapter import WeixinSkillAdapter, WeixinRuntimeConfig, WeixinAdapterError, DEFAULT_BASE_URL, DEFAULT_BOT_TYPE, DEFAULT_QR_BASE_URL


WEIXIN_SKILL_NAME = "weixin_dispatch"
WEIXIN_QR_SESSION_TTL_SECONDS = 300
WEIXIN_QR_SESSIONS: Dict[str, Dict[str, Any]] = {}
WEIXIN_QR_SESSIONS_LOCK = threading.Lock()


def _build_default_weixin_config() -> Dict[str, Any]:
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
    normalized_user_id = str(user_id or "").strip()
    normalized_binding_status = _normalize_binding_status(binding_status, user_id=normalized_user_id)
    return {
        "account_id": str(account_id or "").strip(),
        "user_id": normalized_user_id,
        "binding_status": normalized_binding_status,
    }


def _normalize_timeout_seconds(timeout_seconds: Optional[int], fallback: int = 15) -> int:
    if timeout_seconds is None:
        return fallback
    try:
        return max(1, int(timeout_seconds))
    except (TypeError, ValueError):
        return fallback


def _normalize_binding_status(binding_status: Optional[str], user_id: str = "", fallback: str = "unbound") -> str:
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


def _load_weixin_skill_config_dict(db: Session) -> Dict[str, Any]:
    skill = db.query(Skill).filter(Skill.name == WEIXIN_SKILL_NAME).first()
    if not skill:
        return {}
    try:
        loaded = yaml.safe_load(skill.config)
    except Exception:
        return {}
    if isinstance(loaded, dict):
        return loaded
    return {}


def _build_weixin_config_payload(
    account_id: str,
    token: str,
    base_url: str,
    timeout_seconds: int,
    user_id: str = "",
    binding_status: str = "unbound"
) -> Dict[str, Any]:
    return {
        "name": WEIXIN_SKILL_NAME,
        "version": "1.0.0",
        "description": "Weixin Clawbot communication skill",
        "adapter": "weixin",
        "weixin": {
            "account_id": account_id,
            "token": token,
            "base_url": base_url,
            "timeout_seconds": timeout_seconds,
            "user_id": user_id,
            "binding_status": _normalize_binding_status(binding_status, user_id=user_id)
        }
    }


def _save_weixin_config_to_db(
    db: Session,
    account_id: str,
    token: str,
    base_url: str,
    timeout_seconds: int,
    user_id: str = "",
    binding_status: str = "unbound"
) -> None:
    skill = db.query(Skill).filter(Skill.name == WEIXIN_SKILL_NAME).first()
    config_yaml = yaml.dump(
        _build_weixin_config_payload(
            account_id=account_id,
            token=token,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            user_id=user_id,
            binding_status=binding_status
        )
    )
    if skill:
        skill.config = config_yaml
    else:
        skill = Skill(
            id=str(uuid.uuid4()),
            name=WEIXIN_SKILL_NAME,
            version="1.0.0",
            description="Weixin Clawbot communication skill",
            config=config_yaml,
            category="general",
            tags="[]",
            dependencies="[]",
            author="system",
            enabled=True
        )
        db.add(skill)
    db.commit()


def _build_runtime_config_from_db(db: Session) -> WeixinRuntimeConfig:
    adapter = WeixinSkillAdapter()
    config_dict = _load_weixin_skill_config_dict(db)
    if config_dict:
        runtime = adapter.map_skill_config(config_dict)
        if runtime.base_url:
            return runtime
    return WeixinRuntimeConfig(
        account_id="",
        token="",
        base_url=DEFAULT_BASE_URL,
        bot_type=DEFAULT_BOT_TYPE,
        channel_version="1.0.2",
        timeout_seconds=15,
        plugin_root=adapter.default_plugin_root,
        require_node=False,
        min_node_major=22
    )


def _coerce_weixin_response_payload(payload: Any) -> Dict[str, Any]:
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
    if lowered in {"wait", "scaned", "scanned", "scaned_but_redirect", "confirmed", "expired", "pending", "confirming", "timeout", "success", "ok", "done"}:
        return {"status": text, "raw_text": text}
    if text.startswith(("http://", "https://")):
        return {"qrcode_url": text, "raw_text": text}
    return {"raw_text": text}


def _extract_qrcode_fields(result: Dict[str, Any]) -> Dict[str, str]:
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
    if not qrcode and qrcode_url:
        try:
            parsed = urlparse(qrcode_url)
            query_qrcode = parse_qs(parsed.query).get("qrcode", [""])[0]
            qrcode = str(query_qrcode or "").strip()
        except Exception:
            qrcode = ""
    if not qrcode and raw_text and not qrcode_url:
        qrcode = raw_text
    return {"qrcode": qrcode, "qrcode_url": qrcode_url}


def _build_qr_session(
    *,
    qrcode: str,
    qrcode_url: str,
    login_base_url: str,
    poll_base_url: str,
    bot_type: str,
    timeout_seconds: int
) -> Dict[str, Any]:
    return {
        "qrcode": qrcode,
        "qrcode_url": qrcode_url,
        "login_base_url": login_base_url,
        "poll_base_url": poll_base_url,
        "bot_type": bot_type,
        "created_at": time.time(),
        "timeout_seconds": timeout_seconds,
        "confirmed_payload": None,
        "confirmed_snapshot": _build_weixin_bound_snapshot()
    }


WEIXIN_QR_STATE_MAP = {
    "wait": "pending",
    "scaned": "half_success",
    "scaned_but_redirect": "half_success",
    "expired": "failed",
    "confirmed": "success"
}


WEIXIN_QR_MESSAGE_MAP = {
    "wait": "等待扫码中",
    "scaned": "已扫码，请在微信中确认",
    "scaned_but_redirect": "已扫码，正在切换轮询节点",
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
    normalized_status = str(status or "wait").strip().lower() or "wait"
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
    return logger.bind(
        feature="weixin_qr",
        session_key=str(session_key or "").strip(),
        event=event,
        **fields
    )


def _build_qrcode_upstream_error_detail(result: Dict[str, Any]) -> str:
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
        normalized_status = "scaned_but_redirect"
    elif account_id and token:
        normalized_status = "confirmed"
    elif raw_status in {"confirmed", "confirm", "success", "succeed", "succeeded", "ok", "done"}:
        normalized_status = "confirmed"
    elif raw_status in {"expired", "timeout", "timed_out", "cancelled", "canceled", "invalid"}:
        normalized_status = "expired"
    elif raw_status in {"scaned", "scanned", "scan", "confirming", "pending", "wait_confirm", "waiting_confirm", "auth", "authorizing", "authorized"}:
        normalized_status = "scaned"
    elif auth_id or ticket or hint:
        normalized_status = "scaned"
    else:
        normalized_status = "wait"

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
    now = time.time()
    with WEIXIN_QR_SESSIONS_LOCK:
        expired_keys = [
            key
            for key, value in WEIXIN_QR_SESSIONS.items()
            if now - float(value.get("created_at", 0)) >= WEIXIN_QR_SESSION_TTL_SECONDS
        ]
        for key in expired_keys:
            WEIXIN_QR_SESSIONS.pop(key, None)

class WeixinConfigReq(BaseModel):
    account_id: str
    token: str
    base_url: Optional[str] = DEFAULT_BASE_URL
    timeout_seconds: Optional[int] = 15
    user_id: Optional[str] = ""
    binding_status: Optional[str] = "unbound"


class WeixinQrStartReq(BaseModel):
    session_key: Optional[str] = None
    base_url: Optional[str] = None
    bot_type: Optional[str] = None
    force: Optional[bool] = False
    timeout_seconds: Optional[int] = 15


class WeixinQrWaitReq(BaseModel):
    session_key: str
    timeout_seconds: Optional[int] = 35
    qrcode: Optional[str] = None
    base_url: Optional[str] = None


class WeixinQrExitReq(BaseModel):
    session_key: Optional[str] = None
    clear_config: Optional[bool] = True


def _coerce_weixin_payload_dict(raw_body: Any) -> Dict[str, Any]:
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
    raw_body = await request.body()
    return _coerce_weixin_payload_dict(raw_body)

@router.post("/weixin/health-check")
async def weixin_health_check(request: Request):
    config = WeixinConfigReq(**(await _parse_weixin_request_payload(request)))
    adapter = WeixinSkillAdapter()
    runtime_config = WeixinRuntimeConfig(
        account_id=config.account_id,
        token=config.token,
        base_url=config.base_url or DEFAULT_BASE_URL,
        bot_type="3",
        channel_version="1.0.2",
        timeout_seconds=config.timeout_seconds or 15,
        plugin_root=adapter.default_plugin_root,
        require_node=True,
        min_node_major=22
    )
    result = adapter.check_health(runtime_config)
    return result

@router.post("/weixin/config")
async def save_weixin_config(
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    config = WeixinConfigReq(**(await _parse_weixin_request_payload(request)))
    _save_weixin_config_to_db(
        db=db,
        account_id=config.account_id,
        token=config.token,
        base_url=config.base_url or DEFAULT_BASE_URL,
        timeout_seconds=_normalize_timeout_seconds(config.timeout_seconds, fallback=15),
        user_id=str(config.user_id or "").strip(),
        binding_status=_normalize_binding_status(config.binding_status, user_id=str(config.user_id or "").strip())
    )
    return {"message": "success"}

@router.get("/weixin/config")
async def get_weixin_config(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    skill = db.query(Skill).filter(Skill.name == WEIXIN_SKILL_NAME).first()
    if not skill:
        return _build_default_weixin_config()
    
    try:
        config_dict = yaml.safe_load(skill.config)
        wx_config = config_dict.get("weixin", {})
        user_id = str(wx_config.get("user_id", "") or "").strip()
        return {
            "account_id": wx_config.get("account_id", ""),
            "token": wx_config.get("token", ""),
            "base_url": wx_config.get("base_url", DEFAULT_BASE_URL),
            "timeout_seconds": wx_config.get("timeout_seconds", 15),
            "user_id": user_id,
            "binding_status": _normalize_binding_status(wx_config.get("binding_status"), user_id=user_id)
        }
    except:
        return _build_default_weixin_config()


@router.post("/weixin/qr/start")
async def weixin_qr_start(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    payload = WeixinQrStartReq(**(await _parse_weixin_request_payload(request)))
    _purge_expired_qr_sessions()
    adapter = WeixinSkillAdapter()
    runtime = _build_runtime_config_from_db(db)
    session_key = str(payload.session_key or runtime.account_id or uuid.uuid4())

    with WEIXIN_QR_SESSIONS_LOCK:
        existing = WEIXIN_QR_SESSIONS.get(session_key)
    if existing and not payload.force:
        _build_qr_logger(session_key, "qr_reuse", poll_base_url=existing.get("poll_base_url", "")).info("reusing active weixin qr session")
        return _build_qr_response(
            session_key=session_key,
            status="wait",
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
    if not qrcode:
        _build_qr_logger(session_key, "qr_start_missing_qrcode", upstream_preview=json.dumps(qr_result, ensure_ascii=False)[:600]).warning("missing qrcode in upstream response")
        raise HTTPException(status_code=502, detail=_build_qrcode_upstream_error_detail(qr_result))

    with WEIXIN_QR_SESSIONS_LOCK:
        WEIXIN_QR_SESSIONS[session_key] = _build_qr_session(
            qrcode=qrcode,
            qrcode_url=qrcode_url,
            login_base_url=login_base_url,
            poll_base_url=poll_base_url,
            bot_type=bot_type,
            timeout_seconds=timeout_seconds
        )

    _build_qr_logger(session_key, "qr_started", poll_base_url=poll_base_url, has_qrcode_url=bool(qrcode_url)).info("weixin qr session started")
    return _build_qr_response(
        session_key=session_key,
        status="wait",
        message="使用微信扫描以下二维码，以完成连接。",
        qrcode=qrcode,
        qrcode_url=qrcode_url,
        base_url=poll_base_url
    )


@router.get("/weixin/qr/image")
async def weixin_qr_image(
    session_key: Optional[str] = None,
    qrcode_url: Optional[str] = None,
    current_user=Depends(get_current_user)
):
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
        timeout_seconds = _normalize_timeout_seconds((session or {}).get("timeout_seconds"), fallback=15)
        import httpx
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
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
            timeout_seconds=timeout_seconds
        )
    except WeixinAdapterError as exc:
        detail = str(exc.message or "")
        transient_keywords = ["timeout", "超时", "temporarily", "temporary", "connection", "network", "远程主机", "断开", "reset"]
        if any(keyword in detail.lower() for keyword in ["timeout", "temporarily", "temporary", "connection", "network", "reset"]) or any(keyword in detail for keyword in ["超时", "远程主机", "断开"]):
            _build_qr_logger(payload.session_key, "transient_upstream_error", poll_base_url=poll_base_url, detail=detail).warning("transient upstream error, fallback to wait")
            status_result = {"status": "wait"}
        else:
            raise HTTPException(status_code=502, detail=exc.message)

    normalized_status_result = _normalize_qr_wait_status(status_result)
    status = str(normalized_status_result.get("status") or "wait").strip().lower()
    base_response = _build_qr_response(
        session_key=payload.session_key,
        status=status,
        message=str(normalized_status_result.get("message") or "").strip(),
        connected=status == "confirmed",
        qrcode=qrcode,
        qrcode_url=session.get("qrcode_url", ""),
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

    if status == "scaned_but_redirect":
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
        _build_qr_logger(payload.session_key, "redirect_updated", redirect_host=redirect_host, base_url=response["base_url"]).info("weixin qr polling host redirected")
        return response

    if status == "confirmed":
        account_id = base_response["account_id"]
        token = base_response["token"]
        user_id = base_response["user_id"]
        binding_status = base_response["binding_status"]
        base_url = str(normalized_status_result.get("baseurl") or normalized_status_result.get("base_url") or poll_base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        previous_runtime = _build_runtime_config_from_db(db)
        if not account_id or not token:
            response = _build_qr_response(
                session_key=payload.session_key,
                status="scaned",
                message="扫码已确认，正在等待上游返回完整凭据",
                connected=False,
                qrcode=base_response["qrcode"],
                qrcode_url=base_response["qrcode_url"],
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
            user_id=user_id,
            binding_status=binding_status
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
                    binding_status=binding_status
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

    if status == "scaned":
        _build_qr_logger(payload.session_key, "half_success", auth_id=base_response["auth_id"], ticket=base_response["ticket"], has_hint=bool(base_response["hint"])).info("weixin qr reached half-success state")
        return dict(base_response)
    return dict(base_response)


@router.post("/weixin/qr/exit")
async def weixin_qr_exit(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
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
        runtime = _build_runtime_config_from_db(db)
        _save_weixin_config_to_db(
            db=db,
            account_id="",
            token="",
            base_url=runtime.base_url or DEFAULT_BASE_URL,
            timeout_seconds=_normalize_timeout_seconds(runtime.timeout_seconds, fallback=15),
            user_id="",
            binding_status="unbound"
        )

    return {"message": "success", "cleared_sessions": cleared_sessions}

@router.get(
    "",
    response_model=List[SkillResponse],
    summary="获取技能列表",
    description="返回系统中已安装的技能列表。"
)
async def get_skills(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    skills = db.query(Skill).all()
    return skills


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


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
        version=skill.version,
        description=skill.description,
        config=yaml.dump(config_dict),
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
    
    return new_skill


@router.delete("/{skill_id}")
async def uninstall_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
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
    """从会话中提取经验"""
    from skills.experience_extractor import ExperienceExtractor

    extractor = ExperienceExtractor()
    experience = await extractor.extract_from_session(
        user_goal=user_goal,
        execution_steps=execution_steps,
        final_result=final_result,
        status=status,
        session_id=session_id
    )

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
            yaml.safe_load(skill_update.config)
            skill.config = skill_update.config
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

    return skill


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
        raise HTTPException(status_code=500, detail=f"Skill execution failed: {str(e)}")


@router.get("/{skill_id}/config", response_model=SkillConfigResponse)
async def get_skill_config(
    skill_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    try:
        config_dict = yaml.safe_load(skill.config)
    except yaml.YAMLError as e:
        logger.bind(
            event="skill_get_config_invalid_yaml",
            module="skills",
            action="get_skill_config",
            status="failure",
            skill_id=skill_id,
            error_type=type(e).__name__,
            error_message=sanitize_for_logging(str(e)),
        ).error("get skill config yaml parsing failed")
        raise HTTPException(status_code=500, detail="Failed to parse skill configuration")
    except Exception as e:
        logger.bind(
            event="skill_get_config_error",
            module="skills",
            action="get_skill_config",
            status="failure",
            skill_id=skill_id,
            error_type=type(e).__name__,
            error_message=sanitize_for_logging(str(e)),
        ).error("unexpected get skill config error")
        raise HTTPException(status_code=500, detail="Internal server error")

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
    validator = SkillValidator()
    result = validator.validate_skill_data(skill_data.dict())
    return result


@router.post("/install-from-package")
async def install_skill_from_package(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """从ZIP包安装技能"""
    try:
        content = await file.read()
        zip_file = zipfile.ZipFile(io.BytesIO(content))
        
        config_files = [name for name in zip_file.namelist() if name.endswith('skill.yaml') or name.endswith('skill.yml')]
        if not config_files:
            raise HTTPException(status_code=400, detail="技能包中未找到skill.yaml配置文件")
        
        config_content = zip_file.read(config_files[0]).decode('utf-8')
        config_dict = yaml.safe_load(config_content)
        
        required_fields = ['name', 'version', 'description', 'adapter']
        for field in required_fields:
            if field not in config_dict:
                raise HTTPException(status_code=400, detail=f"技能配置缺少必需字段: {field}")
        
        existing_skill = db.query(Skill).filter(Skill.name == config_dict['name']).first()
        if existing_skill:
            raise HTTPException(status_code=400, detail=f"技能 '{config_dict['name']}' 已存在")
        
        new_skill = Skill(
            id=str(uuid.uuid4()),
            name=config_dict['name'],
            version=config_dict['version'],
            description=config_dict['description'],
            config=config_content,
            category=config_dict.get('category', 'general'),
            tags=json.dumps(config_dict.get('tags', [])),
            dependencies=json.dumps(config_dict.get('dependencies', [])),
            author=config_dict.get('author', 'unknown'),
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
        raise HTTPException(status_code=500, detail=f"安装技能失败: {str(e)}")

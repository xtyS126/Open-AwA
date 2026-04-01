from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from db.models import get_db, Skill, ExperienceExtractionLog
from api.dependencies import get_current_user
from api.schemas import SkillCreate, SkillResponse, SkillUpdate, SkillExecute, SkillConfigResponse, SkillValidationResult, SkillValidationRequest
from skills.skill_engine import SkillEngine
from skills.skill_validator import SkillValidator
from loguru import logger
import yaml
import uuid
import json
import zipfile
import io
import time
import threading
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
        "timeout_seconds": 15
    }


def _normalize_timeout_seconds(timeout_seconds: Optional[int], fallback: int = 15) -> int:
    if timeout_seconds is None:
        return fallback
    try:
        return max(1, int(timeout_seconds))
    except (TypeError, ValueError):
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
    timeout_seconds: int
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
            "timeout_seconds": timeout_seconds
        }
    }


def _save_weixin_config_to_db(
    db: Session,
    account_id: str,
    token: str,
    base_url: str,
    timeout_seconds: int
) -> None:
    skill = db.query(Skill).filter(Skill.name == WEIXIN_SKILL_NAME).first()
    config_yaml = yaml.dump(
        _build_weixin_config_payload(
            account_id=account_id,
            token=token,
            base_url=base_url,
            timeout_seconds=timeout_seconds
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


def _extract_qrcode_fields(result: Dict[str, Any]) -> Dict[str, str]:
    payload = result.get("data") if isinstance(result.get("data"), dict) else result
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
        "timeout_seconds": timeout_seconds
    }


def _build_qrcode_upstream_error_detail(result: Dict[str, Any]) -> str:
    payload = result.get("data") if isinstance(result.get("data"), dict) else result
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
    )
    detail = "二维码接口返回异常"
    if isinstance(code, (int, str)) and str(code).strip() not in {"", "0"}:
        detail += f" (code={code})"
    if isinstance(message, str) and message.strip():
        detail += f": {message.strip()}"
    else:
        detail += f": {json.dumps(result, ensure_ascii=False)[:200]}"
    return detail



def _normalize_qr_wait_status(status_result: Dict[str, Any]) -> Dict[str, Any]:
    payload = status_result.get("data") if isinstance(status_result.get("data"), dict) else status_result
    if not isinstance(payload, dict):
        payload = {"raw_text": str(payload or "")}

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

@router.post("/weixin/health-check")
async def weixin_health_check(config: WeixinConfigReq):
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
    config: WeixinConfigReq,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    _save_weixin_config_to_db(
        db=db,
        account_id=config.account_id,
        token=config.token,
        base_url=config.base_url or DEFAULT_BASE_URL,
        timeout_seconds=_normalize_timeout_seconds(config.timeout_seconds, fallback=15)
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
        return {
            "account_id": wx_config.get("account_id", ""),
            "token": wx_config.get("token", ""),
            "base_url": wx_config.get("base_url", DEFAULT_BASE_URL),
            "timeout_seconds": wx_config.get("timeout_seconds", 15)
        }
    except:
        return _build_default_weixin_config()


@router.post("/weixin/qr/start")
async def weixin_qr_start(
    payload: WeixinQrStartReq,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    _purge_expired_qr_sessions()
    adapter = WeixinSkillAdapter()
    runtime = _build_runtime_config_from_db(db)
    session_key = str(payload.session_key or runtime.account_id or uuid.uuid4())

    with WEIXIN_QR_SESSIONS_LOCK:
        existing = WEIXIN_QR_SESSIONS.get(session_key)
    if existing and not payload.force:
        return {
            "message": "二维码已就绪，请使用微信扫描。",
            "session_key": session_key,
            "status": "wait",
            "qrcode": existing.get("qrcode", ""),
            "qrcode_url": existing.get("qrcode_url", "")
        }

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

    logger.debug(f"[weixin_qr_start] upstream raw result: {json.dumps(qr_result, ensure_ascii=False)[:600]}")
    extracted = _extract_qrcode_fields(qr_result)
    qrcode = extracted["qrcode"]
    qrcode_url = extracted["qrcode_url"]
    if not qrcode:
        logger.warning(f"[weixin_qr_start] qrcode field empty, upstream result: {qr_result}")
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

    return {
        "message": "使用微信扫描以下二维码，以完成连接。",
        "session_key": session_key,
        "status": "wait",
        "qrcode": qrcode,
        "qrcode_url": qrcode_url
    }


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
    payload: WeixinQrWaitReq,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
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
            logger.warning(f"[weixin_qr_wait] transient upstream error fallback to wait: {detail}")
            status_result = {"status": "wait"}
        else:
            raise HTTPException(status_code=502, detail=exc.message)

    normalized_status_result = _normalize_qr_wait_status(status_result)
    status = str(normalized_status_result.get("status") or "wait").strip().lower()
    message_map = {
        "wait": "等待扫码中",
        "scaned": "已扫码，请在微信中确认",
        "scaned_but_redirect": "已扫码，正在切换轮询节点",
        "expired": "二维码已过期，请重新获取",
        "confirmed": "与微信连接成功"
    }

    response: Dict[str, Any] = {
        "connected": status == "confirmed",
        "session_key": payload.session_key,
        "status": status,
        "message": str(normalized_status_result.get("message") or message_map.get(status, "login status updating")).strip() or message_map.get(status, "login status updating")
    }

    if status == "scaned_but_redirect":
        redirect_host = str(normalized_status_result.get("redirect_host") or "").strip()
        if redirect_host:
            poll_base_url = f"https://{redirect_host}"
            with WEIXIN_QR_SESSIONS_LOCK:
                active_session = WEIXIN_QR_SESSIONS.get(payload.session_key)
                if active_session:
                    active_session["poll_base_url"] = poll_base_url
                    active_session["created_at"] = time.time()
            response["redirect_host"] = redirect_host
            response["base_url"] = poll_base_url
        return response

    if status == "confirmed":
        account_id = str(normalized_status_result.get("ilink_bot_id") or normalized_status_result.get("account_id") or "").strip()
        token = str(normalized_status_result.get("bot_token") or normalized_status_result.get("token") or "").strip()
        base_url = str(normalized_status_result.get("baseurl") or normalized_status_result.get("base_url") or poll_base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        previous_runtime = _build_runtime_config_from_db(db)
        if account_id and token:
            _save_weixin_config_to_db(
                db=db,
                account_id=account_id,
                token=token,
                base_url=base_url,
                timeout_seconds=_normalize_timeout_seconds(previous_runtime.timeout_seconds, fallback=15)
            )
        response.update({
            "account_id": account_id,
            "token": token,
            "base_url": base_url
        })
        with WEIXIN_QR_SESSIONS_LOCK:
            WEIXIN_QR_SESSIONS.pop(payload.session_key, None)
        return response

    if status == "expired":
        with WEIXIN_QR_SESSIONS_LOCK:
            WEIXIN_QR_SESSIONS.pop(payload.session_key, None)
        return response

    if status == "scaned":
        response["qrcode_url"] = session.get("qrcode_url", "")
        auth_id = str(normalized_status_result.get("auth_id") or "").strip()
        ticket = str(normalized_status_result.get("ticket") or "").strip()
        hint = str(normalized_status_result.get("hint") or "").strip()
        if auth_id:
            response["auth_id"] = auth_id
        if ticket:
            response["ticket"] = ticket
        if hint:
            response["hint"] = hint
    return response


@router.post("/weixin/qr/exit")
async def weixin_qr_exit(
    payload: WeixinQrExitReq,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
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
            timeout_seconds=_normalize_timeout_seconds(runtime.timeout_seconds, fallback=15)
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
        logger.error(f"YAML parsing error in skill config: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid YAML configuration")
    except Exception as e:
        logger.error(f"Unexpected error parsing skill config: {str(e)}")
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
            logger.error(f"YAML parsing error in skill update: {str(e)}")
            raise HTTPException(status_code=400, detail="Invalid YAML configuration")
        except Exception as e:
            logger.error(f"Unexpected error parsing skill update: {str(e)}")
            raise HTTPException(status_code=500, detail="Internal server error")

    db.commit()
    db.refresh(skill)

    logger.info(f"Skill '{skill_id}' updated by user '{current_user.username}'")

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

    try:
        skill_engine = SkillEngine(db)

        result = await skill_engine.execute_skill(
            skill_name=skill.name,
            inputs=execution_data.inputs,
            context=execution_data.context
        )

        logger.info(f"Skill '{skill.name}' executed by user '{current_user.username}'")

        return {
            "status": "success" if result.get("success") else "error",
            "skill_id": skill_id,
            "skill_name": skill.name,
            "result": result
        }

    except Exception as e:
        logger.error(f"Error executing skill '{skill.name}': {str(e)}")
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
        logger.error(f"YAML parsing error getting skill config: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to parse skill configuration")
    except Exception as e:
        logger.error(f"Unexpected error getting skill config: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return SkillConfigResponse(
        skill_id=skill.id,
        name=skill.name,
        version=skill.version,
        description=skill.description,
        config=config_dict,
        enabled=skill.enabled,
        installed_at=skill.installed_at
    )


@router.post(
    "/validate",
    response_model=SkillValidationResult,
    summary="校验技能配置",
    description="校验上传或输入的技能 YAML 配置是否合法。"
)
async def validate_skill(
    validation_request: SkillValidationRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    try:
        yaml.safe_load(validation_request.yaml_content)
    except yaml.YAMLError as e:
        return SkillValidationResult(
            valid=False,
            errors=[f"Invalid YAML format: {str(e)}"],
            warnings=[]
        )

    try:
        config = yaml.safe_load(validation_request.yaml_content)

        if not isinstance(config, dict):
            return SkillValidationResult(
                valid=False,
                errors=["Configuration must be a dictionary"],
                warnings=[]
            )

        validator = SkillValidator()
        result = validator.validate_skill_config(config)

        return SkillValidationResult(
            valid=result.valid,
            errors=result.errors,
            warnings=result.warnings,
            skill_name=config.get("name"),
            version=config.get("version")
        )

    except Exception as e:
        logger.error(f"Error validating skill configuration: {str(e)}")
        return SkillValidationResult(
            valid=False,
            errors=[f"Validation error: {str(e)}"],
            warnings=[]
        )

@router.post("/parse-upload")
async def parse_skill_upload(
    file: UploadFile = File(...),
    current_user = Depends(get_current_user)
):
    content = await file.read()
    filename = file.filename
    
    skill_content = ""
    
    if not filename or filename.endswith('.zip') or filename.endswith('.skill'):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                if 'SKILL.md' in z.namelist():
                    skill_content = z.read('SKILL.md').decode('utf-8')
                else:
                    md_files = [f for f in z.namelist() if f.endswith('.md')]
                    if md_files:
                        skill_content = z.read(md_files[0]).decode('utf-8')
                    else:
                        raise HTTPException(status_code=400, detail="No SKILL.md found in the archive")
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid zip file")
    elif filename and (filename.endswith('.md') or filename.endswith('.yaml') or filename.endswith('.yml')):
        skill_content = content.decode('utf-8')
    else:
        raise HTTPException(status_code=400, detail="Unsupported file format")
        
    name = (filename or "").split('.')[0]
    description = ""
    instructions = skill_content
    
    try:
        if skill_content.startswith('---'):
            parts = skill_content.split('---', 2)
            if len(parts) >= 3:
                frontmatter = yaml.safe_load(parts[1])
                name = frontmatter.get('name', name)
                description = frontmatter.get('description', description)
                instructions = parts[2].strip()
        else:
            data = yaml.safe_load(skill_content)
            if isinstance(data, dict):
                name = data.get('name', name)
                description = data.get('description', description)
                instructions = data.get('instructions', skill_content)
    except Exception:
        pass
        
    return {
        "name": name,
        "description": description,
        "instructions": instructions
    }

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger


DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
DEFAULT_QR_BASE_URL = DEFAULT_BASE_URL
DEFAULT_BOT_TYPE = "3"
DEFAULT_CHANNEL_VERSION = "1.0.2"
SESSION_EXPIRED_ERRCODE = -14
SESSION_PAUSE_DURATION_SECONDS = 60 * 60

_SESSION_PAUSE_UNTIL: Dict[str, float] = {}


class WeixinAdapterError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        suggestions: Optional[List[str]] = None
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.suggestions = suggestions or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "suggestions": self.suggestions
        }


@dataclass
class WeixinRuntimeConfig:
    account_id: str
    token: str
    base_url: str
    bot_type: str
    channel_version: str
    timeout_seconds: int
    plugin_root: str
    require_node: bool
    min_node_major: int
    user_id: str = ""
    binding_status: str = "unbound"


class WeixinSkillAdapter:
    def __init__(self, project_root: Optional[str] = None):
        resolved_root = project_root or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.project_root = resolved_root
        self.default_plugin_root = os.path.join(resolved_root, "插件", "openclaw-weixin")
        self.state_root = os.path.join(resolved_root, ".openawa", "weixin")

    def is_weixin_skill(self, skill_config: Dict[str, Any]) -> bool:
        adapter = str(skill_config.get("adapter", "")).strip().lower()
        skill_type = str(skill_config.get("type", "")).strip().lower()
        runtime_adapter = str(skill_config.get("runtime", {}).get("adapter", "")).strip().lower()
        candidates = {adapter, skill_type, runtime_adapter}
        return "weixin" in candidates or "openclaw-weixin" in candidates

    def map_skill_config(self, skill_config: Dict[str, Any]) -> WeixinRuntimeConfig:
        section = skill_config.get("weixin")
        if not isinstance(section, dict):
            section = {}
        runtime = skill_config.get("runtime")
        if not isinstance(runtime, dict):
            runtime = {}

        account_id = self._pick_value(section, runtime, "account_id", "accountId")
        token = self._pick_value(section, runtime, "token")
        base_url = self._pick_value(section, runtime, "base_url", "baseUrl") or DEFAULT_BASE_URL
        bot_type = str(self._pick_value(section, runtime, "bot_type", "botType") or DEFAULT_BOT_TYPE)
        channel_version = str(self._pick_value(section, runtime, "channel_version", "channelVersion") or DEFAULT_CHANNEL_VERSION)
        timeout_raw = self._pick_value(section, runtime, "timeout_seconds", "timeoutSeconds")
        plugin_root = self._pick_value(section, runtime, "plugin_root", "pluginRoot") or self.default_plugin_root
        require_node_raw = self._pick_value(section, runtime, "require_node", "requireNode")
        min_node_major_raw = self._pick_value(section, runtime, "min_node_major", "minNodeMajor")
        user_id = self._pick_value(section, runtime, "user_id", "userId")
        binding_status_raw = self._pick_value(section, runtime, "binding_status", "bindingStatus")

        try:
            timeout_seconds = int(timeout_raw) if timeout_raw is not None else 15
        except (TypeError, ValueError):
            timeout_seconds = 15
        timeout_seconds = max(5, timeout_seconds)

        require_node = True if require_node_raw is None else bool(require_node_raw)

        try:
            min_node_major = int(min_node_major_raw) if min_node_major_raw is not None else 22
        except (TypeError, ValueError):
            min_node_major = 22

        normalized_user_id = str(user_id or "").strip()
        normalized_binding_status = self._normalize_binding_status(binding_status_raw, normalized_user_id)

        return WeixinRuntimeConfig(
            account_id=str(account_id or "").strip(),
            token=str(token or "").strip(),
            base_url=str(base_url).strip().rstrip("/"),
            bot_type=bot_type,
            channel_version=channel_version,
            timeout_seconds=timeout_seconds,
            plugin_root=str(plugin_root).strip(),
            require_node=require_node,
            min_node_major=min_node_major,
            user_id=normalized_user_id,
            binding_status=normalized_binding_status
        )

    def check_health(self, config: WeixinRuntimeConfig) -> Dict[str, Any]:
        issues: List[str] = []
        suggestions: List[str] = []
        node_path = shutil.which("node")
        node_version = ""

        if config.require_node:
            if not node_path:
                issues.append("缺少 Node.js 运行时")
                suggestions.append("安装 Node.js 22 或更高版本并确保 node 在 PATH 中")
            else:
                node_version = self._read_node_version(node_path)
                if node_version:
                    major = self._parse_node_major(node_version)
                    if major is None or major < config.min_node_major:
                        issues.append(f"Node.js 版本过低: {node_version}")
                        suggestions.append(f"升级 Node.js 到 {config.min_node_major}+")
                else:
                    issues.append("无法读取 Node.js 版本")
                    suggestions.append("确认 node 命令可执行且具备读取版本权限")

        plugin_root_exists = bool(config.plugin_root) and os.path.isdir(config.plugin_root)
        if not plugin_root_exists:
            issues.append(f"weixin 插件目录不存在: {config.plugin_root}")
            suggestions.append("确认仓库包含 插件/openclaw-weixin 目录或在 skill 配置中指定 plugin_root")

        return {
            "ok": len(issues) == 0,
            "issues": issues,
            "suggestions": suggestions,
            "diagnostics": {
                "node_path": node_path,
                "node_version": node_version,
                "plugin_root": config.plugin_root,
                "plugin_root_exists": plugin_root_exists,
                "base_url": config.base_url,
                "account_id": config.account_id,
                "state_root": self.state_root,
                "session_paused": self._is_session_paused(config.account_id),
                "user_id": config.user_id,
                "binding_status": config.binding_status,
                "binding_ready": self._is_binding_ready(config),
            }
        }

    async def execute(
        self,
        skill_name: str,
        skill_config: Dict[str, Any],
        inputs: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        started = time.time()
        runtime = self.map_skill_config(skill_config)
        action = str(inputs.get("action") or inputs.get("operation") or "health_check").strip().lower()
        payload = self._normalize_payload(inputs)

        try:
            health = self.check_health(runtime)
            if not health["ok"]:
                raise WeixinAdapterError(
                    code="WEIXIN_DEPENDENCY_MISSING",
                    message="weixin 运行环境校验失败",
                    details={"issues": health["issues"], "diagnostics": health["diagnostics"]},
                    suggestions=health["suggestions"]
                )

            if action == "health_check":
                return self._success_result(
                    action=action,
                    started=started,
                    runtime=runtime,
                    data={"health": health}
                )

            missing_fields = self._validate_runtime_fields(runtime, required=["account_id", "token"])
            if missing_fields:
                raise WeixinAdapterError(
                    code="WEIXIN_CONFIG_MISSING_FIELDS",
                    message="weixin skill 配置不完整",
                    details={"missing_fields": missing_fields},
                    suggestions=["补齐 weixin.account_id 与 weixin.token 配置字段"]
                )

            self._assert_session_active(runtime.account_id)

            if action == "send_message":
                result = await self._send_message(runtime, payload)
            elif action == "get_updates":
                result = await self._get_updates(runtime, payload)
            else:
                raise WeixinAdapterError(
                    code="WEIXIN_UNSUPPORTED_ACTION",
                    message=f"不支持的 weixin 操作: {action}",
                    details={"supported_actions": ["health_check", "send_message", "get_updates"]},
                    suggestions=["将 inputs.action 设置为 health_check、send_message 或 get_updates"]
                )

            return self._success_result(
                action=action,
                started=started,
                runtime=runtime,
                data=result
            )
        except WeixinAdapterError as exc:
            logger.warning(f"Weixin adapter execution failed for skill={skill_name}, action={action}, code={exc.code}")
            return self._error_result(action=action, started=started, runtime=runtime, error=exc)
        except Exception as exc:
            logger.error(f"Weixin adapter unexpected error for skill={skill_name}, action={action}: {exc}")
            wrapped = WeixinAdapterError(
                code="WEIXIN_INTERNAL_ERROR",
                message="weixin 适配执行发生未预期错误",
                details={"exception": type(exc).__name__, "error": str(exc)},
                suggestions=["检查 skill 配置与网络连通性后重试"]
            )
            return self._error_result(action=action, started=started, runtime=runtime, error=wrapped)

    async def _send_message(self, config: WeixinRuntimeConfig, payload: Dict[str, Any]) -> Dict[str, Any]:
        to_user_id = str(payload.get("to_user_id") or payload.get("toUserId") or "").strip()
        text = str(payload.get("text") or "").strip()
        context_token = str(payload.get("context_token") or payload.get("contextToken") or "").strip()
        client_id = str(payload.get("client_id") or payload.get("clientId") or f"openawa-{int(time.time() * 1000)}")

        if not context_token and to_user_id and config.account_id:
            context_token = self._get_context_token(config.account_id, to_user_id)

        missing = []
        if not to_user_id:
            missing.append("to_user_id")
        if not text:
            missing.append("text")
        if not context_token:
            missing.append("context_token")
        if missing:
            raise WeixinAdapterError(
                code="WEIXIN_INPUT_MISSING_FIELDS",
                message="发送消息参数不完整",
                details={"missing_fields": missing},
                suggestions=["在 inputs.payload 中提供 to_user_id、text、context_token，或先执行 get_updates 建立上下文缓存"]
            )

        request_body = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": client_id,
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token,
                "item_list": [
                    {
                        "type": 1,
                        "text_item": {"text": text}
                    }
                ]
            }
        }
        response = await self._api_post(config=config, endpoint="ilink/bot/sendmessage", body=request_body)
        return {
            "request": {"to_user_id": to_user_id, "client_id": client_id, "context_token": context_token},
            "response": response,
            "state": {"context_token_source": "cache" if not payload.get("context_token") and not payload.get("contextToken") else "payload"}
        }

    async def _get_updates(self, config: WeixinRuntimeConfig, payload: Dict[str, Any]) -> Dict[str, Any]:
        incoming_buf = str(payload.get("get_updates_buf") or payload.get("getUpdatesBuf") or "").strip()
        persisted_buf = self._load_get_updates_buf(config.account_id)
        get_updates_buf = incoming_buf or persisted_buf or ""
        request_body = {"get_updates_buf": get_updates_buf}
        response = await self._api_post(config=config, endpoint="ilink/bot/getupdates", body=request_body, timeout_seconds=38)

        errcode = response.get("errcode")
        ret = response.get("ret")
        if errcode == SESSION_EXPIRED_ERRCODE or ret == SESSION_EXPIRED_ERRCODE:
            self._pause_session(config.account_id)

        next_buf = str(response.get("get_updates_buf") or "").strip()
        if next_buf:
            self._save_get_updates_buf(config.account_id, next_buf)

        stored_context_tokens = 0
        for item in response.get("msgs") or []:
            if not isinstance(item, dict):
                continue
            from_user_id = str(item.get("from_user_id") or "").strip()
            context_token = str(item.get("context_token") or "").strip()
            if from_user_id and context_token:
                self._set_context_token(config.account_id, from_user_id, context_token)
                stored_context_tokens += 1

        return {
            "request": request_body,
            "response": response,
            "state": {
                "used_get_updates_buf": get_updates_buf,
                "saved_get_updates_buf": next_buf,
                "stored_context_token_count": stored_context_tokens,
            }
        }

    async def fetch_login_qrcode(
        self,
        base_url: str,
        bot_type: str = DEFAULT_BOT_TYPE,
        timeout_seconds: int = 15
    ) -> Dict[str, Any]:
        return await self._api_get(
            base_url=DEFAULT_QR_BASE_URL,
            endpoint="ilink/bot/get_bot_qrcode",
            params={"bot_type": bot_type},
            timeout_seconds=max(1, min(int(timeout_seconds), 5))
        )

    async def fetch_qrcode_status(
        self,
        base_url: str,
        qrcode: str,
        timeout_seconds: int = 35
    ) -> Dict[str, Any]:
        poll_base_url = str(base_url or DEFAULT_QR_BASE_URL).strip().rstrip("/") or DEFAULT_QR_BASE_URL
        return await self._api_get(
            base_url=poll_base_url,
            endpoint="ilink/bot/get_qrcode_status",
            params={"qrcode": qrcode},
            timeout_seconds=max(1, int(timeout_seconds)),
            extra_headers={"iLink-App-ClientVersion": "1"}
        )

    async def _api_post(
        self,
        config: WeixinRuntimeConfig,
        endpoint: str,
        body: Dict[str, Any],
        timeout_seconds: Optional[int] = None
    ) -> Dict[str, Any]:
        payload = dict(body)
        payload["base_info"] = {"channel_version": config.channel_version}
        url = f"{config.base_url}/{endpoint.lstrip('/')}"
        timeout_value = timeout_seconds or config.timeout_seconds

        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "Authorization": f"Bearer {config.token}",
            "X-WECHAT-UIN": self._build_random_wechat_uin(),
            "iLink-App-ClientVersion": "1",
        }

        try:
            async with httpx.AsyncClient(timeout=timeout_value) as client:
                response = await client.post(url, json=payload, headers=headers)
            content_type = response.headers.get("content-type", "")
            if response.status_code >= 400:
                raise WeixinAdapterError(
                    code="WEIXIN_UPSTREAM_HTTP_ERROR",
                    message=f"上游请求失败: HTTP {response.status_code}",
                    details={"endpoint": endpoint, "status_code": response.status_code, "response_text": response.text[:500]},
                    suggestions=["检查 token 是否有效、base_url 是否正确，或稍后重试"]
                )
            if "application/json" in content_type.lower():
                return response.json()
            raw = response.text.strip()
            if raw.startswith("{") or raw.startswith("["):
                try:
                    return json.loads(raw)
                except Exception:
                    pass
            return {"raw_text": raw}
        except WeixinAdapterError:
            raise
        except httpx.TimeoutException:
            raise WeixinAdapterError(
                code="WEIXIN_TIMEOUT",
                message="weixin 上游请求超时",
                details={"endpoint": endpoint, "timeout_seconds": timeout_value},
                suggestions=["提高 timeout_seconds 或检查网络连通性"]
            )
        except httpx.HTTPError as exc:
            raise WeixinAdapterError(
                code="WEIXIN_HTTP_ERROR",
                message="weixin 上游请求异常",
                details={"endpoint": endpoint, "error": str(exc)},
                suggestions=["检查网络、代理和证书配置"]
            )

    async def _api_get(
        self,
        base_url: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        timeout_seconds: int = 15,
        extra_headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        normalized_base_url = str(base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        url = f"{normalized_base_url}/{endpoint.lstrip('/')}"
        headers: Dict[str, str] = {}
        if extra_headers:
            headers.update(extra_headers)

        logger.debug(f"[weixin _api_get] GET {url} params={params}")
        try:
            async with httpx.AsyncClient(timeout=max(1, int(timeout_seconds))) as client:
                response = await client.get(url, params=params, headers=headers)
            content_type = response.headers.get("content-type", "")
            logger.debug(
                f"[weixin _api_get] {endpoint} status={response.status_code} "
                f"content-type={content_type!r} body={response.text[:500]!r}"
            )
            if response.status_code >= 400:
                raise WeixinAdapterError(
                    code="WEIXIN_UPSTREAM_HTTP_ERROR",
                    message=f"上游请求失败: HTTP {response.status_code}",
                    details={
                        "endpoint": endpoint,
                        "status_code": response.status_code,
                        "response_text": response.text[:500]
                    },
                    suggestions=["检查 base_url 是否正确，或稍后重试"]
                )
            if "application/json" in content_type.lower():
                return response.json()
            raw = response.text.strip()
            if raw.startswith("{") or raw.startswith("["):
                try:
                    return json.loads(raw)
                except Exception:
                    pass
            return {"raw_text": raw}
        except WeixinAdapterError:
            raise
        except httpx.TimeoutException:
            if endpoint.strip().lower() == "ilink/bot/get_qrcode_status":
                logger.debug(f"[weixin _api_get] {endpoint} client timeout after {timeout_seconds}s, fallback to wait")
                return {"status": "wait"}
            raise WeixinAdapterError(
                code="WEIXIN_TIMEOUT",
                message="weixin 上游请求超时",
                details={"endpoint": endpoint, "timeout_seconds": timeout_seconds},
                suggestions=["提高 timeout_seconds 或检查网络连通性"]
            )
        except httpx.HTTPError as exc:
            raise WeixinAdapterError(
                code="WEIXIN_HTTP_ERROR",
                message="weixin 上游请求异常",
                details={"endpoint": endpoint, "error": str(exc)},
                suggestions=["检查网络、代理和证书配置"]
            )

    def _success_result(
        self,
        action: str,
        started: float,
        runtime: WeixinRuntimeConfig,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            "success": True,
            "adapter": "weixin",
            "action": action,
            "error": None,
            "outputs": {
                "adapter": "weixin",
                "action": action,
                "data": data,
                "meta": {
                    "duration_seconds": round(time.time() - started, 6),
                    "account_id": runtime.account_id,
                    "base_url": runtime.base_url,
                    "user_id": runtime.user_id,
                    "binding_status": runtime.binding_status,
                    "binding_ready": self._is_binding_ready(runtime)
                }
            }
        }

    def _error_result(
        self,
        action: str,
        started: float,
        runtime: WeixinRuntimeConfig,
        error: WeixinAdapterError
    ) -> Dict[str, Any]:
        return {
            "success": False,
            "adapter": "weixin",
            "action": action,
            "error": error.to_dict(),
            "outputs": {
                "adapter": "weixin",
                "action": action,
                "data": {},
                "meta": {
                    "duration_seconds": round(time.time() - started, 6),
                    "account_id": runtime.account_id,
                    "base_url": runtime.base_url,
                    "user_id": runtime.user_id,
                    "binding_status": runtime.binding_status,
                    "binding_ready": self._is_binding_ready(runtime)
                }
            }
        }

    def _normalize_payload(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        payload = inputs.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        merged = dict(payload)
        for key, value in inputs.items():
            if key in {"action", "operation", "payload"}:
                continue
            merged[key] = value
        return merged

    def _validate_runtime_fields(self, config: WeixinRuntimeConfig, required: List[str]) -> List[str]:
        missing: List[str] = []
        for field in required:
            value = getattr(config, field, "")
            if not isinstance(value, str) or not value.strip():
                missing.append(field)
        return missing

    def _accounts_state_dir(self) -> str:
        path = os.path.join(self.state_root, "accounts")
        os.makedirs(path, exist_ok=True)
        return path

    def _sync_buf_file_path(self, account_id: str) -> str:
        safe_account_id = self._sanitize_account_id(account_id)
        return os.path.join(self._accounts_state_dir(), f"{safe_account_id}.sync.json")

    def _context_tokens_file_path(self, account_id: str) -> str:
        safe_account_id = self._sanitize_account_id(account_id)
        return os.path.join(self._accounts_state_dir(), f"{safe_account_id}.context-tokens.json")

    def _load_get_updates_buf(self, account_id: str) -> str:
        data = self._read_json_file(self._sync_buf_file_path(account_id))
        value = data.get("get_updates_buf")
        return str(value).strip() if isinstance(value, str) else ""

    def _save_get_updates_buf(self, account_id: str, get_updates_buf: str) -> None:
        self._write_json_file(self._sync_buf_file_path(account_id), {"get_updates_buf": get_updates_buf})

    def _get_context_token(self, account_id: str, user_id: str) -> str:
        data = self._read_json_file(self._context_tokens_file_path(account_id))
        value = data.get(user_id)
        return str(value).strip() if isinstance(value, str) else ""

    def _set_context_token(self, account_id: str, user_id: str, token: str) -> None:
        file_path = self._context_tokens_file_path(account_id)
        data = self._read_json_file(file_path)
        data[user_id] = token
        self._write_json_file(file_path, data)

    def _pause_session(self, account_id: str) -> None:
        _SESSION_PAUSE_UNTIL[account_id] = time.time() + SESSION_PAUSE_DURATION_SECONDS

    def _is_session_paused(self, account_id: str) -> bool:
        if not account_id:
            return False
        until = _SESSION_PAUSE_UNTIL.get(account_id)
        if until is None:
            return False
        if until <= time.time():
            _SESSION_PAUSE_UNTIL.pop(account_id, None)
            return False
        return True

    def _remaining_pause_seconds(self, account_id: str) -> int:
        if not self._is_session_paused(account_id):
            return 0
        return max(0, int(_SESSION_PAUSE_UNTIL.get(account_id, 0) - time.time()))

    def _assert_session_active(self, account_id: str) -> None:
        if not self._is_session_paused(account_id):
            return
        remaining_seconds = self._remaining_pause_seconds(account_id)
        raise WeixinAdapterError(
            code="WEIXIN_SESSION_PAUSED",
            message="weixin 会话已暂停，请稍后再试",
            details={"account_id": account_id, "remaining_seconds": remaining_seconds, "errcode": SESSION_EXPIRED_ERRCODE},
            suggestions=["重新扫码登录或等待暂停窗口结束后重试"]
        )

    @staticmethod
    def _normalize_binding_status(binding_status: Optional[str], user_id: str = "") -> str:
        normalized = str(binding_status or "").strip().lower()
        if normalized in {"bound", "confirmed", "linked", "success", "succeeded"}:
            return "bound"
        if normalized in {"pending", "confirming", "waiting"}:
            return "pending"
        if user_id:
            return "bound"
        return "unbound"

    def _is_binding_ready(self, config: WeixinRuntimeConfig) -> bool:
        return self._normalize_binding_status(config.binding_status, config.user_id) == "bound"

    @staticmethod
    def _sanitize_account_id(account_id: str) -> str:
        safe = str(account_id or "default").strip() or "default"
        return safe.replace("/", "-").replace("\\", "-").replace(":", "-").replace("@", "-")

    @staticmethod
    def _read_json_file(file_path: str) -> Dict[str, Any]:
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
        except FileNotFoundError:
            return {}
        except Exception as exc:
            logger.warning(f"Failed to read weixin state file {file_path}: {exc}")
        return {}

    @staticmethod
    def _write_json_file(file_path: str, data: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)

    @staticmethod
    def _pick_value(primary: Dict[str, Any], fallback: Dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in primary and primary[key] is not None:
                return primary[key]
        for key in keys:
            if key in fallback and fallback[key] is not None:
                return fallback[key]
        return None

    @staticmethod
    def _build_random_wechat_uin() -> str:
        raw = str(int.from_bytes(os.urandom(4), byteorder="big", signed=False))
        return base64.b64encode(raw.encode("utf-8")).decode("utf-8")

    @staticmethod
    def _read_node_version(node_path: str) -> str:
        try:
            proc = subprocess.run(
                [node_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False
            )
            version = (proc.stdout or proc.stderr or "").strip()
            return version.lstrip("v")
        except Exception:
            return ""

    @staticmethod
    def _parse_node_major(version: str) -> Optional[int]:
        if not version:
            return None
        try:
            return int(version.split(".")[0])
        except (TypeError, ValueError, IndexError):
            return None

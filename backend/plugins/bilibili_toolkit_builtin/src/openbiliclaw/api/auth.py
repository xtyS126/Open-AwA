"""LAN 密码门禁的 FastAPI 胶水层。

将 :mod:`openbiliclaw.auth_core` 中的标准库原语接入 Starlette 的
请求/响应：auth 中间件、``/api/auth/*`` 路由、cookie 与 CSRF 处理、
登录失败限流，以及启动时对会话密钥与密码指纹的对账。

参见 ``docs/plans/2026-05-30-web-password-auth-design.md``。
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI  # noqa: TC002 - FastAPI needs runtime annotations for routes.
from starlette.requests import (
    Request,  # noqa: TC002 - FastAPI needs runtime annotations for routes.
)
from starlette.responses import JSONResponse, Response

from openbiliclaw import auth_core
from openbiliclaw.auth_core import COOKIE_NAME, CSRF_HEADER

if TYPE_CHECKING:
    from starlette.requests import HTTPConnection

    from openbiliclaw.config import ApiAuthConfig
    from openbiliclaw.storage.database import Database

GateGetter = Callable[[], "AuthGate"]

logger = logging.getLogger(__name__)

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# 具有真实副作用的 GET 端点（认领+锁定源任务；引导写入推荐历史；
# 调度一个待处理的 chat-turn 完成任务）。它们需要像不安全方法一样做 CSRF。
# 自定义 `X-OBC-Auth` 头是完整的 CSRF 防御（在 allow_origins=["*"] 下，
# 带凭证的跨源请求无法设置该头）；SPA 在每次 fetch 都发送它。img/WS
# 不会命中这些路径。参见 review r2#2 / r3#2。
_CSRF_GET_EXACT = frozenset(
    {
        "/api/sources/xhs/next-task",
        "/api/sources/dy/next-task",
        "/api/sources/yt/next-task",
        "/api/sources/zhihu/next-task",
        "/api/recommendations",
    }
)
_CSRF_GET_PREFIXES = ("/api/chat/turns/",)  # GET /api/chat/turns/{id} 恢复一个待处理的 turn
_NEVER_EXPIRE_MAX_AGE = 10 * 365 * 24 * 3600  # ~10 年用于"记住登录"


def _auth_env_overrides() -> list[str]:
    # 当任意 auth 环境变量被设置时，auth 由 env 管理，配置文件编辑
    # （包括 local admin 端点）在重启后不会生效 —— 参见 CLI 守卫。
    # 规范化的变量列表放在 config loader 中，使守卫始终匹配真实的
    # override 覆盖面（每个字段，不仅仅是 password）。
    from openbiliclaw.config import API_AUTH_ENV_VARS

    return [name for name in API_AUTH_ENV_VARS if (os.environ.get(name) or "").strip()]


def _is_mutating_get(path: str) -> bool:
    return path in _CSRF_GET_EXACT or any(path.startswith(p) for p in _CSRF_GET_PREFIXES)


class _RateLimiter:
    """内存中按 IP 的登录失败限流器（重启后重置）。"""

    def __init__(self, *, max_failures: int = 5, window: int = 900, lockout: int = 900) -> None:
        self._max = max_failures
        self._window = window
        self._lockout = lockout
        self._failures: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}

    def is_locked(self, key: str, *, now: float | None = None) -> bool:
        moment = time.time() if now is None else now
        until = self._locked_until.get(key)
        if until is None:
            return False
        if moment >= until:
            self._locked_until.pop(key, None)
            self._failures.pop(key, None)
            return False
        return True

    def record_failure(self, key: str, *, now: float | None = None) -> None:
        moment = time.time() if now is None else now
        events = [t for t in self._failures.get(key, []) if moment - t < self._window]
        events.append(moment)
        self._failures[key] = events
        if len(events) >= self._max:
            self._locked_until[key] = moment + self._lockout

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
        self._locked_until.pop(key, None)


class AuthGate:
    """持有实时 auth 配置 + 数据库，并响应每个请求的 auth 问题。"""

    def __init__(self, auth: ApiAuthConfig, database: Database | None) -> None:
        self.auth = auth
        self.database = database
        self.rate = _RateLimiter()
        # 启动指纹对账失败时，无法保证一个密码变更被撤销，
        # 因此在成功对账之前对所有 token auth 采取失败即关闭策略
        # （loopback 仍然绕过）。参见 §4.7 / review r1#2。
        self.reconcile_ok = True

    # ── 请求内省 ──────────────────────────────────────────

    def resolve_client(self, request: HTTPConnection) -> tuple[str | None, bool]:
        peer = request.client.host if request.client else ""
        try:
            xff_values = request.headers.getlist("x-forwarded-for")
        except AttributeError:  # pragma: no cover - non-starlette headers
            single = request.headers.get("x-forwarded-for")
            xff_values = [single] if single else []
        has_fwd = auth_core.header_present(request.headers)
        return auth_core.resolve_client_ip(
            peer,
            xff_values=xff_values,
            has_forward_header=has_fwd,
            trusted_proxies=self.auth.trusted_proxies,
        )

    def is_trusted_local(self, request: HTTPConnection) -> bool:
        if not self.auth.trust_loopback:
            return False
        client_ip, local = self.resolve_client(request)
        if not auth_core.is_trusted_local(client_ip, local):
            return False
        # 仅 loopback peer 不够：用户的浏览器可能被恶意页面驱动向
        # http://127.0.0.1 发起跨源请求，否则会继承本地绕过（localhost
        # CSRF / DNS rebinding）。仅对非跨源浏览器调用方授予绕过：
        # 无 Origin（CLI/curl/非浏览器）、本地 web UI 自身（同源）、
        # 浏览器扩展、或显式允许列表中的 origin。参见 review r7。
        return self._origin_safe_for_local(request)

    def _origin_safe_for_local(self, request: HTTPConnection) -> bool:
        origin = request.headers.get("origin")
        # 一个真实的浏览器扩展（主要的本地客户端）仅凭其 origin scheme 即可信
        # —— 网页无法伪造 chrome-extension origin。
        if origin and (
            origin.startswith("chrome-extension://") or origin.startswith("moz-extension://")
        ):
            return True
        # 注意：allowed_bearer_origins 故意不被视为 trusted-local。
        # 它们是通过 bearer *token* 认证的跨源场景；授予它们无 token 的
        # 本地绕过会让它们无需会话即可访问 /api/auth/admin（管理 gate）。
        # 它们仍然通过 token 路径工作（pick_token）。参见 review r1#1 (admin)。
        # Fetch Metadata：真实浏览器即使省略 Origin 也会暴露跨源意图
        # （no-cors 子资源如
        # `<img src="http://127.0.0.1:8420/api/sources/xhs/next-task">`）。
        # 对跨站 / 跨源同站的浏览器请求拒绝本地绕过，防止恶意页面驱动
        # 无 Origin 的 loopback 状态变更。CLI/curl 不发送 Sec-Fetch-*
        # （不受影响）；扩展使用上面的 chrome-extension Origin 分支。
        # 参见 review r9。
        if request.headers.get("sec-fetch-site") in ("cross-site", "same-site"):
            return False
        eff = self.effective(request)
        # DNS-rebinding 防御：rebound 浏览器（Host: evil.example → 127.0.0.1）
        # 直接连接，因此当 peer 本身是 loopback 时，无 Origin / 同源豁免
        # 额外要求一个规范化的 loopback Host。当客户端通过配置的可信
        # proxy 解析（peer 是 proxy 而非 loopback）时，proxy 配置是信任锚
        # 且 rebinding 不适用，因此 Host（外部代理名）不要求是 loopback。
        peer_host = request.client.host if request.client else None
        peer_is_loopback = auth_core.is_loopback_host(peer_host)
        if peer_is_loopback and (eff is None or not auth_core.is_loopback_host(eff[1])):
            return False
        if not origin:
            return True  # CLI/curl/非浏览器，或同源 GET
        parsed = auth_core.parse_origin(origin)
        return parsed is not None and auth_core.same_origin(parsed, eff)

    def effective(self, request: HTTPConnection) -> tuple[str, str, int] | None:
        peer = request.client.host if request.client else ""
        return auth_core.effective_scheme_host(
            url_scheme=request.url.scheme,
            host_header=request.headers.get("host"),
            xf_proto=request.headers.get("x-forwarded-proto"),
            xf_host=request.headers.get("x-forwarded-host"),
            peer=peer,
            trusted_proxies=self.auth.trusted_proxies,
        )

    def pick_token(self, request: HTTPConnection) -> tuple[bool, str | None]:
        """返回 ``(used_cookie, token)``。Bearer/query 仅对允许的 origin 有效。"""
        cookie = request.cookies.get(COOKIE_NAME)
        if cookie:
            return True, cookie
        origin = request.headers.get("origin")
        if auth_core.origin_allowed_for_bearer(origin, self.auth.allowed_bearer_origins):
            authz = request.headers.get("authorization", "")
            if authz.lower().startswith("bearer "):
                return False, authz[7:].strip() or None
            qp = request.query_params.get("token")
            if qp:
                return False, qp
        return False, None

    def current_epoch(self) -> int:
        if self.database is None:
            raise RuntimeError("auth gate has no database")
        return self.database.get_auth_epoch()

    def token_valid(self, token: str | None) -> bool:
        if not token:
            return False
        if not self.reconcile_ok:
            return False  # 撤销状态未验证 → 失败即关闭
        epoch = self.current_epoch()  # 可能 raise -> 调用方失败即关闭
        return auth_core.verify_token(token, self.auth.session_secret, current_epoch=epoch)

    def csrf_ok(self, request: Request, *, require_origin: bool = True) -> bool:
        # 自定义头是核心防御（跨源带凭证请求无法设置它）。对不安全方法，
        # 我们*额外*钉住 Origin==Host（Origin 在这里可靠出现）；GET 请求
        # 同源时可能合法地省略 Origin，因此仅靠该头来放行。
        if request.headers.get(CSRF_HEADER) is None:
            return False
        if require_origin:
            parsed = auth_core.parse_origin(request.headers.get("origin"))
            if not auth_core.same_origin(parsed, self.effective(request)):
                return False
        return True


# ── cookie 辅助函数 ──────────────────────────────────────────────────────────


def _set_session_cookie(resp: Response, token: str, *, ttl_hours: int, secure: bool) -> None:
    max_age = ttl_hours * 3600 if ttl_hours > 0 else _NEVER_EXPIRE_MAX_AGE
    resp.set_cookie(
        COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        path="/",
        secure=secure,
    )


def _clear_session_cookie(resp: Response) -> None:
    resp.set_cookie(COOKIE_NAME, "", max_age=0, httponly=True, samesite="lax", path="/")


def _is_secure(gate: AuthGate, request: Request) -> bool:
    eff = gate.effective(request)
    return eff is not None and eff[0] == "https"


# ── 白名单（始终公开的路径） ─────────────────────────────────────────


def _is_public(request: Request) -> bool:
    """即使启用 auth 也绕过 gate 的路径（§4.2）。"""
    path = request.url.path
    method = request.method.upper()
    if method == "OPTIONS":
        return True
    if not path.startswith("/api"):
        return True  # 静态 SPA 壳、"/"、favicon 等
    if path == "/api/health":
        return True
    if path in ("/api/auth/status", "/api/auth/login"):
        return True
    if path == "/api/autostart-status":
        return True
    if path == "/api/autostart/apply":
        return True
    # guided-init 状态可被远端读取（can_manage 标记仅本地）；
    # 写端点（init / init/cancel）也在白名单中，但其 handler 通过
    # is_trusted_local 自我 gate（gui-init spec §2）。
    if path in ("/api/init-status", "/api/init", "/api/init/cancel"):
        return True
    # gate 管理绕过中间件，以便其 handler 自行强制 trusted-local，
    # 并对每个非本地调用方（远端或跨源 loopback）返回特定的
    # 403 local_only，而不是会泄露是否提交了 token 的通用 401。
    # handler 即 gate。
    if path == "/api/auth/admin":
        return True
    # 普通登出是公开 + 幂等的；全局撤销（?all=true）则不是。
    return bool(path == "/api/auth/logout" and request.query_params.get("all") != "true")


# ── 中间件 ──────────────────────────────────────────────────────────────


def make_auth_middleware(get_gate: GateGetter) -> Any:
    """构建 ASGI http 中间件分发闭包。"""

    async def auth_guard(request: Request, call_next: Any) -> Any:
        gate: AuthGate = get_gate()
        if not gate.auth.enabled:
            return await call_next(request)
        if _is_public(request):
            return await call_next(request)
        if gate.is_trusted_local(request):
            return await call_next(request)

        used_cookie, token = gate.pick_token(request)
        try:
            valid = gate.token_valid(token)
        except Exception:  # DB 不可用 -> 失败即关闭
            logger.warning("auth: epoch read failed; failing closed", exc_info=True)
            return _unauthorized(clear_cookie=False)
        if not valid:
            return _unauthorized(clear_cookie=used_cookie)

        method = request.method.upper()
        is_unsafe = method in _UNSAFE_METHODS
        if (
            used_cookie
            and (is_unsafe or _is_mutating_get(request.url.path))
            and not gate.csrf_ok(request, require_origin=is_unsafe)
        ):
            return _forbidden_csrf()
        return await call_next(request)

    return auth_guard


def authorize_websocket(gate: AuthGate, websocket: Any) -> bool:
    """授权一个 WebSocket 握手（http 中间件不覆盖 ws）。

    必须在 ``websocket.accept()`` *之前* 调用。镜像 HTTP gate 并额外
    做一次同源（CSWSH）检查，因为浏览器无法在 WebSocket 握手上设置
    自定义头。WebSocket 暴露与 gate 读取相同的 ``client`` / ``headers`` /
    ``cookies`` / ``query_params`` / ``url`` 属性。
    """
    if not gate.auth.enabled:
        return True
    if gate.is_trusted_local(websocket):
        return True
    # CSWSH 防御：Origin 必须同源或属于允许的 bearer origin 列表。
    origin = websocket.headers.get("origin")
    parsed = auth_core.parse_origin(origin)
    same = auth_core.same_origin(parsed, gate.effective(websocket))
    allowed_bearer = auth_core.origin_allowed_for_bearer(origin, gate.auth.allowed_bearer_origins)
    if not (same or allowed_bearer):
        return False
    _used_cookie, token = gate.pick_token(websocket)
    try:
        return gate.token_valid(token)
    except Exception:
        logger.warning("auth: websocket epoch read failed; failing closed", exc_info=True)
        return False


def _cors_echo(resp: JSONResponse) -> JSONResponse:
    # 中间件短路运行在 CORSMiddleware 之外；回显一个宽松的头，
    # 使跨源桌面客户端可以读取状态码。
    resp.headers.setdefault("Access-Control-Allow-Origin", "*")
    return resp


def _unauthorized(*, clear_cookie: bool) -> JSONResponse:
    resp = JSONResponse({"error": "auth_required"}, status_code=401)
    if clear_cookie:
        _clear_session_cookie(resp)
    return _cors_echo(resp)


def _forbidden_csrf() -> JSONResponse:
    return _cors_echo(JSONResponse({"error": "csrf"}, status_code=403))


# ── 路由 ──────────────────────────────────────────────────────────────────


def register_auth_routes(app: FastAPI, get_gate: GateGetter) -> None:
    """在 FastAPI app 上注册 ``/api/auth/{status,login,logout}``。"""

    @app.get("/api/auth/status")
    async def auth_status(request: Request) -> JSONResponse:
        gate: AuthGate = get_gate()
        env_managed = bool(_auth_env_overrides())
        local = gate.is_trusted_local(request)
        # can_manage：仅 trusted-local 调用方（扩展/本地 UI/CLI）可通过
        # /api/auth/admin 切换 gate，且 env-managed 时不允许。
        can_manage = local and not env_managed
        if not gate.auth.enabled:
            return JSONResponse(
                {
                    "enabled": False,
                    "authenticated": True,
                    "trust_loopback": gate.auth.trust_loopback,
                    "env_managed": env_managed,
                    "can_manage": can_manage,
                }
            )
        authenticated = local
        if not authenticated:
            _used, token = gate.pick_token(request)
            try:
                authenticated = gate.token_valid(token)
            except Exception:
                authenticated = False
        return JSONResponse(
            {
                "enabled": True,
                "authenticated": authenticated,
                "trust_loopback": gate.auth.trust_loopback,
                "env_managed": env_managed,
                "can_manage": can_manage,
            }
        )

    @app.post("/api/auth/login")
    async def auth_login(request: Request) -> JSONResponse:
        gate: AuthGate = get_gate()
        if not gate.auth.enabled:
            return JSONResponse({"ok": False, "error": "auth_disabled"}, status_code=400)
        client_ip, _local = gate.resolve_client(request)
        rate_key = client_ip or (request.client.host if request.client else "unknown")
        if gate.rate.is_locked(rate_key):
            return JSONResponse({"ok": False, "error": "locked"}, status_code=429)
        try:
            body = await request.json()
        except Exception:
            body = {}
        password = str(body.get("password", "")) if isinstance(body, dict) else ""
        if not gate.auth.password_hash or not auth_core.verify_password(
            password, gate.auth.password_hash
        ):
            gate.rate.record_failure(rate_key)
            return JSONResponse({"ok": False}, status_code=401)
        gate.rate.reset(rate_key)

        try:
            epoch = gate.current_epoch()
        except Exception:
            return JSONResponse({"ok": False, "error": "unavailable"}, status_code=503)
        ttl = gate.auth.session_ttl_hours
        origin = request.headers.get("origin")
        req_origin = auth_core.parse_origin(origin)
        eff = gate.effective(request)
        # 服务端根据 Origin 决定模式；客户端无法主动请求 token。
        is_same = req_origin is None or auth_core.same_origin(req_origin, eff)
        if is_same:
            token = auth_core.sign_token(gate.auth.session_secret, epoch=epoch, ttl_hours=ttl)
            resp = JSONResponse({"ok": True})
            _set_session_cookie(resp, token, ttl_hours=ttl, secure=_is_secure(gate, request))
            return resp
        # 跨源 → bearer 模式（仅在白名单中且 TTL 有限）
        if not auth_core.origin_allowed_for_bearer(origin, gate.auth.allowed_bearer_origins):
            return JSONResponse({"ok": False, "error": "origin_forbidden"}, status_code=403)
        if ttl <= 0:
            return JSONResponse({"ok": False, "error": "bearer_requires_ttl"}, status_code=400)
        token = auth_core.sign_token(gate.auth.session_secret, epoch=epoch, ttl_hours=ttl)
        return JSONResponse(
            {"ok": True, "token": token, "expires_at": auth_core.token_expires_at(token)}
        )

    @app.post("/api/auth/logout")
    async def auth_logout(request: Request) -> JSONResponse:
        gate: AuthGate = get_gate()
        resp = JSONResponse({"ok": True})
        _clear_session_cookie(resp)
        if request.query_params.get("all") == "true" and gate.database is not None:
            # 全局撤销；中间件已在此要求一个有效会话
            try:
                gate.database.bump_auth_epoch()
            except Exception:
                logger.warning("auth: logout-all bump failed", exc_info=True)
                return JSONResponse({"ok": False, "error": "unavailable"}, status_code=503)
        return resp


# ── 启动对账 ──────────────────────────────────────────────────────────────────


def ensure_session_secret(auth: ApiAuthConfig) -> bool:
    """首次启用时生成 session secret。如果发生变更则返回 True。"""
    if auth.enabled and not auth.session_secret.strip():
        auth.session_secret = secrets.token_urlsafe(32)
        return True
    return False


def reconcile_password_fingerprint(gate: AuthGate, *, plain: str | None) -> None:
    """若自上次启动以来密码已变更，则提升撤销 epoch（§4.7）。"""
    auth = gate.auth
    if not (auth.enabled and auth.password_hash.strip() and auth.session_secret.strip()):
        return
    if gate.database is None:
        return
    fingerprint = auth_core.password_fingerprint(
        auth.session_secret, plain=plain, password_hash=auth.password_hash
    )
    try:
        bumped = gate.database.reconcile_password_fingerprint(fingerprint)
        gate.reconcile_ok = True
        if bumped:
            logger.info("auth: password change detected, revoked existing sessions")
    except Exception:
        # 无法确认/撤销一个可能的密码变更 → 在下次干净对账之前
        # 对所有 token auth 失败即关闭（loopback 仍可用）。
        gate.reconcile_ok = False
        logger.warning(
            "auth: fingerprint reconcile failed; token auth disabled until next "
            "successful reconcile (restart after fixing the data dir)",
            exc_info=True,
        )

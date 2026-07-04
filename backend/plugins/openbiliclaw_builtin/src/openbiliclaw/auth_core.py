"""局域网密码门禁的标准库原语。

本模块刻意保持零依赖（仅使用 Python 标准库），以便同时被 ``config.py``（必须保持
低层级以避免与 ``openbiliclaw.api`` 产生导入循环）和 ``api/auth.py`` 中的 FastAPI
胶水代码导入。

依据 ``docs/plans/2026-05-30-web-password-auth-design.md`` 实现：

* scrypt 密码哈希 / 恒定时间校验（§4.5）
* HMAC 签名的无状态会话令牌，携带 ``iat`` / ``ep`` / 可选的
  ``exp``（§4.4）
* 基于凭据材料派生的稳定密码指纹，**绝不**使用加盐哈希（§4.7，v7 修复）
* 感知反向代理的真实客户端 IP 解析（§4.1/§6），以及一个统一的
  ``effective_origin`` / ``same_origin`` 契约，被 CSRF、WebSocket、
  bearer 模式和 ``Secure`` cookie 决策复用（§4.9）
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

COOKIE_NAME = "obc_session"
CSRF_HEADER = "x-obc-auth"

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SCRYPT_MAXMEM = 64 * 1024 * 1024

_TOKEN_VERSION = 1


# ── base64url 辅助函数 ───────────────────────────────────────────────────────


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


# ── 密码哈希（scrypt） ───────────────────────────────────────────────────────


def hash_password(plain: str) -> str:
    """使用 scrypt + 随机盐对密码进行哈希。

    返回 ``scrypt$<n>$<r>$<p>$<b64salt>$<b64dk>``。盐是随机的，因此
    同样的明文每次调用都会产生不同的字符串——调用方绝不能从该值派生
    稳定性指纹（参见 :func:`password_fingerprint`）。
    """
    import os

    salt = os.urandom(16)
    dk = hashlib.scrypt(
        plain.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
        maxmem=_SCRYPT_MAXMEM,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64u_encode(salt)}${_b64u_encode(dk)}"


def verify_password(plain: str, stored: str) -> bool:
    """以恒定时间校验 ``plain`` 是否匹配已存储的 scrypt 字符串。"""
    try:
        scheme, n_s, r_s, p_s, salt_s, dk_s = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    try:
        n, r, p = int(n_s), int(r_s), int(p_s)
        salt = _b64u_decode(salt_s)
        expected = _b64u_decode(dk_s)
    except (ValueError, TypeError):
        return False
    try:
        actual = hashlib.scrypt(
            plain.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
            maxmem=_SCRYPT_MAXMEM,
        )
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(actual, expected)


# ── 密码指纹（跨重启稳定；§4.7 v7） ──────────────────────────────────────────


def password_fingerprint(session_secret: str, *, plain: str | None, password_hash: str) -> str:
    """*凭据*的稳定指纹，用于检测密码变更。

    关键点：该指纹由明文（若可用）或用户提供的哈希字符串计算而来——
    **而非**新加盐的 scrypt 哈希——因此未变更的密码在每次重启时
    产生相同指纹，绝不会错误地吊销会话（评审 r6 修复）。
    """
    material = "pw:" + plain if plain else "ph:" + password_hash
    digest = hmac.new(
        session_secret.encode("utf-8"), material.encode("utf-8"), hashlib.sha256
    ).digest()
    return _b64u_encode(digest)


# ── 无状态签名会话令牌（§4.4） ──────────────────────────────────────────────


def _sign(secret: str, payload_b64: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return _b64u_encode(mac)


def sign_token(
    secret: str,
    *,
    epoch: int,
    ttl_hours: int = 0,
    now: int | None = None,
) -> str:
    """生成签名令牌。``ttl_hours <= 0`` → 无 ``exp``（永不过期）。"""
    issued = int(time.time()) if now is None else now
    payload: dict[str, int] = {"v": _TOKEN_VERSION, "iat": issued, "ep": epoch}
    if ttl_hours > 0:
        payload["exp"] = issued + ttl_hours * 3600
    payload_b64 = _b64u_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return f"{payload_b64}.{_sign(secret, payload_b64)}"


def token_expires_at(token: str) -> int | None:
    """返回（已信任）令牌的 ``exp``，若不存在则返回 ``None``。"""
    try:
        payload_b64 = token.split(".", 1)[0]
        payload = json.loads(_b64u_decode(payload_b64))
        exp = payload.get("exp")
        return int(exp) if isinstance(exp, int) else None
    except (ValueError, TypeError, KeyError):
        return None


def verify_token(
    token: str,
    secret: str,
    *,
    current_epoch: int,
    now: int | None = None,
) -> bool:
    """在 MAC 上以恒定时间校验签名、过期时间和吊销纪元。"""
    if not token or not secret:
        return False
    try:
        payload_b64, sig = token.split(".", 1)
    except ValueError:
        return False
    if not hmac.compare_digest(sig, _sign(secret, payload_b64)):
        return False
    try:
        payload = json.loads(_b64u_decode(payload_b64))
    except (ValueError, TypeError):
        return False
    if not isinstance(payload, dict) or payload.get("v") != _TOKEN_VERSION:
        return False
    moment = int(time.time()) if now is None else now
    exp = payload.get("exp")
    if exp is not None and (not isinstance(exp, int) or moment >= exp):
        return False
    ep = payload.get("ep")
    return not (not isinstance(ep, int) or ep < current_epoch)


# ── IP / 代理处理（§4.1, §6） ──────────────────────────────────────────────

_LOOPBACK = frozenset({"127.0.0.1", "::1"})
_FORWARD_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded")


def is_loopback_host(host: str | None) -> bool:
    """判断 Host/host 值是否为规范的回环名。

    用于针对 DNS 重绑定攻击保护回环旁路：攻击者页面
    ``http://evil.example:8420`` 重绑定到 127.0.0.1，否则对本地后端
    看起来会"同源"。仅 ``localhost`` / 回环 IP 符合条件。
    """
    if not host:
        return False
    if host.strip().lower() == "localhost":
        return True
    ip = norm_ip(host)
    if ip is None:
        return False
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


def norm_ip(value: str | None) -> str | None:
    """规范化 IP 字面量（去除方括号/端口/区域标识）；非法则返回 ``None``。"""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    # [::1]:port  或  [::1]
    if text.startswith("["):
        end = text.find("]")
        if end == -1:
            return None
        text = text[1:end]
    elif text.count(":") == 1:
        # ipv4:port
        text = text.split(":", 1)[0]
    if "%" in text:  # IPv6 区域标识
        text = text.split("%", 1)[0]
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return None


def _trusted_set(trusted_proxies: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for item in trusted_proxies:
        normalized = norm_ip(item)
        if normalized is not None:
            out.add(normalized)
    return out


def resolve_client_ip(
    peer: str,
    *,
    xff_values: list[str],
    has_forward_header: bool,
    trusted_proxies: Iterable[str],
) -> tuple[str | None, bool]:
    """解析真实客户端 IP，失败时安全收敛。

    返回 ``(client_ip, trustworthy_local)``。仅当请求确实源自本地主机
    （直接或通过已配置的、报告回环客户端的可信代理）时，
    ``trustworthy_local`` 才为 ``True``。
    """
    peer_n = norm_ip(peer)
    if not has_forward_header:
        return peer_n, True
    trusted = _trusted_set(trusted_proxies)
    if peer_n is None or peer_n not in trusted:
        # 来自非可信 peer 的 forwarded 头 → 视为远程
        return peer_n, False
    chain: list[str] = []
    for value in xff_values:
        for part in value.split(","):
            normalized = norm_ip(part)
            if normalized is None:
                return peer_n, False  # 格式错误 → 安全收敛，不抛异常
            chain.append(normalized)
    if not chain:
        return peer_n, False
    # 从右至左：跳过可信跳，第一个不可信的就是真实客户端
    real: str | None = None
    for ip in reversed(chain):
        if ip in trusted:
            continue
        real = ip
        break
    if real is None or real in trusted:
        return peer_n, False
    return real, True


def is_trusted_local(client_ip: str | None, trustworthy_local: bool) -> bool:
    return trustworthy_local and client_ip is not None and client_ip in _LOOPBACK


# ── origin / scheme 规范化（§4.9） ────────────────────────────────────────────

_DEFAULT_PORT = {"http": 80, "https": 443, "ws": 80, "wss": 443}


def _split_host_port(host: str | None, scheme: str) -> tuple[str, int] | None:
    if not host:
        return None
    text = host.strip()
    if not text:
        return None
    if text.startswith("["):  # [ipv6](:port)?
        end = text.find("]")
        if end == -1:
            return None
        hostname = text[1:end].lower()
        rest = text[end + 1 :]
        port_str = rest[1:] if rest.startswith(":") else ""
    elif text.count(":") == 1:
        hostname, port_str = text.split(":", 1)
        hostname = hostname.lower()
    else:
        hostname, port_str = text.lower(), ""
    if port_str:
        try:
            port = int(port_str)
        except ValueError:
            return None
    else:
        port = _DEFAULT_PORT.get(scheme, 0)
    return hostname, port


def _http_scheme(scheme: str) -> str:
    # 将 ws/wss 收敛为 http/https 以便同源比较
    s = scheme.lower()
    if s in ("ws", "http"):
        return "http"
    if s in ("wss", "https"):
        return "https"
    return s


def effective_scheme_host(
    *,
    url_scheme: str,
    host_header: str | None,
    xf_proto: str | None,
    xf_host: str | None,
    peer: str,
    trusted_proxies: Iterable[str],
) -> tuple[str, str, int] | None:
    """计算外部生效的 ``(scheme, host, port)``。

    仅当直连 peer 是已配置的可信代理时（与 §4.1 一致），才采纳 forwarded 的
    scheme/host，因此来自不可信客户端的伪造 ``X-Forwarded-Proto`` 无法
    影响 ``Secure`` 或同源决策。
    """
    peer_n = norm_ip(peer)
    trusted = _trusted_set(trusted_proxies)
    if peer_n is not None and peer_n in trusted:
        scheme = (xf_proto.split(",")[0].strip() if xf_proto else "") or url_scheme
        host = xf_host or host_header
    else:
        scheme, host = url_scheme, host_header
    hp = _split_host_port(host, _http_scheme(scheme))
    if hp is None:
        return None
    return _http_scheme(scheme), hp[0], hp[1]


def parse_origin(origin: str | None) -> tuple[str, str, int] | None:
    """将 ``Origin`` 头解析为 ``(scheme, host, port)``；不存在/opaque 则返回 ``None``。"""
    if not origin:
        return None
    text = origin.strip()
    if text.lower() == "null" or "://" not in text:
        return None
    scheme, _, rest = text.partition("://")
    hp = _split_host_port(rest, _http_scheme(scheme))
    if hp is None:
        return None
    return _http_scheme(scheme), hp[0], hp[1]


def same_origin(
    origin: tuple[str, str, int] | None, effective: tuple[str, str, int] | None
) -> bool:
    """仅当具体的 Origin 与生效的 scheme+host+port 完全匹配时返回 True。"""
    if origin is None or effective is None:
        return False
    return origin == effective


def origin_string(parts: tuple[str, str, int] | None) -> str | None:
    """将 ``(scheme, host, port)`` 渲染为 ``scheme://host[:port]``（默认端口省略）。"""
    if parts is None:
        return None
    scheme, host, port = parts
    bracket = host if ":" not in host else f"[{host}]"
    if port == _DEFAULT_PORT.get(scheme, 0):
        return f"{scheme}://{bracket}"
    return f"{scheme}://{bracket}:{port}"


def origin_allowed_for_bearer(origin: str | None, allowed: Iterable[str]) -> bool:
    """判断请求 Origin 是否在 bearer 允许列表中（规范化后比较）。"""
    parsed = parse_origin(origin)
    if parsed is None:
        return False
    target = origin_string(parsed)
    return any(origin_string(parse_origin(entry)) == target for entry in allowed)


def header_present(headers: Mapping[str, str], names: Iterable[str] = _FORWARD_HEADERS) -> bool:
    lowered = {k.lower() for k in headers}
    return any(name in lowered for name in names)

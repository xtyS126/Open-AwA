"""
WebSocket 鉴权共享层。

抽取自 api/routes/chat.py / terminal.py / weixin.py 三处重复实现的：
- extract_token_from_subprotocol: 从 Sec-WebSocket-Protocol 子协议头提取 bearer token
- validate_ws_origin: 校验 WebSocket Origin 是否在白名单内（防 CSWSH）

设计约束：
- main 模块在加载时会注册路由，路由模块反向引用 main 中的 ALLOWED_ORIGINS /
  ALLOW_LAN_ORIGIN_REGEX 会形成循环导入。本模块在函数体内延迟导入 main，避免模块加载期循环。
- WebSocket accept() 必须在客户端请求 subprotocol 时 echo 回去（RFC 6455），
  因此 extract_token_from_subprotocol 同时返回 token 与 subprotocol 标识，
  调用方在 accept 时把 subprotocol 原样回显。
- token 必须从 Sec-WebSocket-Protocol 子协议头读取，不得走 URL query
  （避免泄露到 access log / Referer / 浏览器历史）。
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from fastapi import WebSocket
from loguru import logger


def extract_token_from_subprotocol(websocket: WebSocket) -> Tuple[Optional[str], Optional[str]]:
    """
    从 Sec-WebSocket-Protocol 子协议头提取 bearer token。

    子协议格式：bearer.<token>

    Returns:
        (token, subprotocol) 元组。token 为 None 表示未找到；
        subprotocol 为需要回显的子协议标识（浏览器要求 accept 时回显，否则拒绝连接）。
    """
    protocol_header = websocket.headers.get("sec-websocket-protocol", "")
    if not protocol_header:
        return (None, None)
    for proto in protocol_header.split(","):
        proto = proto.strip()
        if proto.startswith("bearer."):
            token = proto[len("bearer."):]
            return (token, proto)
    return (None, None)


def validate_ws_origin(origin: str) -> bool:
    """
    校验 WebSocket Origin 是否在白名单内，防 CSWSH 跨站 WebSocket 劫持。

    判定顺序：
    1. 空 origin 直接拒绝
    2. 开发环境本地地址（localhost / 127.0.0.1）允许
    3. main.py 中 ALLOWED_ORIGINS 白名单允许
    4. main.py 中 ALLOW_LAN_ORIGIN_REGEX（LAN 模式私有网段）允许
    5. 其余一律拒绝

    Note:
        main 模块在加载期会注册路由，本函数延迟导入 main 以避免循环依赖。
        main 不可用时（如单元测试中未加载 main），仅依赖开发环境白名单放行。
    """
    if not origin:
        return False

    # 开发环境默认白名单（前端 Vite 端口 5173 + 后端 8000）
    dev_origins = {
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    }
    if origin in dev_origins:
        return True

    # 检查 main.py 中配置的 ALLOWED_ORIGINS 白名单
    try:
        from main import ALLOWED_ORIGINS
        if origin in ALLOWED_ORIGINS:
            return True
    except ImportError:
        pass

    # 检查 LAN 模式（允许私有网段 IP）
    try:
        from main import ALLOW_LAN_ORIGIN_REGEX
        if ALLOW_LAN_ORIGIN_REGEX is not None and re.match(ALLOW_LAN_ORIGIN_REGEX, origin):
            return True
    except ImportError:
        pass

    logger.bind(event="ws_origin_rejected", module="ws_auth", origin=origin).warning(
        f"WebSocket origin rejected: {origin}"
    )
    return False


def resolve_ws_user_by_name(username: str) -> Optional[object]:
    """
    WebSocket 鉴权专用：按用户名查询 User（独立短生命周期会话）。

    Returns:
        User 对象；未找到返回 None
    """
    from db.models import SessionLocal, User

    with SessionLocal() as db:
        return db.query(User).filter(User.username == username).first()


def resolve_ws_user_from_token(token: Optional[str]) -> Optional[object]:
    """
    WebSocket 鉴权专用：统一解析 token 为 User，支持 API Key 与 JWT 两种路径。

    与 api/dependencies.py 的 get_current_user 保持一致的鉴权顺序：
      1. API Key 路径：token 与 settings.OPENAWA_API_KEY 完全匹配时返回 owner 用户
      2. JWT 路径：decode_access_token 解析 sub 后查 User 表

    设计动机：APP/登录页仅支持 API Key 认证，浏览器无 access_token Cookie；
    若 WS 鉴权只接受 JWT，会让 API Key 登录用户无法建立 WS 连接
    （终端 PTY 等场景表现为连接被 4002 拒绝后前端无限重连，拖垮渲染线程）。

    Args:
        token: 从 Sec-WebSocket-Protocol 子协议或 query 参数提取的原始 token

    Returns:
        认证成功返回 User 对象；token 无效/用户不存在/用户被禁用时返回 None
    """
    if not token:
        return None

    from api.dependencies import _normalize_request_token, _get_owner_from_settings
    from config.security import decode_access_token
    from config.settings import settings
    import secrets as _secrets

    normalized = _normalize_request_token(token)
    if normalized is None:
        return None

    api_key = settings.OPENAWA_API_KEY.get_secret_value()
    # 路径 1: API Key 认证（与 get_current_user 路径 1 对齐）
    if api_key and _secrets.compare_digest(normalized, api_key):
        owner = _get_owner_from_settings()
        if owner is not None:
            return owner
        # owner 加载失败时降级到 JWT 路径，保证鉴权不静默失败

    # 路径 2: JWT Bearer 认证
    payload = decode_access_token(normalized)
    if payload is None:
        return None

    username = payload.get("sub")
    if not isinstance(username, str):
        return None

    user = resolve_ws_user_by_name(username)
    if user is None:
        return None
    # 禁用状态的用户视为无效凭证（与 _resolve_jwt_user 对齐）
    if user.role == "disabled":
        return None
    return user

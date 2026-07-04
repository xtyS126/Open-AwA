"""X (Twitter) 持久化 Cookie 辅助工具，用于服务端 Cookie 回放式发现。

与 :mod:`openbiliclaw.sources.douyin_auth` 对应：浏览器扩展保持
``data/x_cookie.json`` 最新；密钥永不写入 config.toml。
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# 服务端 Cookie 回放同时需要会话令牌（auth_token）和 CSRF 令牌（ct0）——
# 缺少任意一个，twitter-cli 会立即返回 401。
X_REQUIRED_COOKIE_NAMES = ("auth_token", "ct0")

_X_COOKIE_FILENAME = "x_cookie.json"


class XCookieManager:
    """将用户的 X (Twitter) Cookie 头存储在 config.toml 之外。"""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._cookie_path = data_dir / _X_COOKIE_FILENAME

    @property
    def cookie_path(self) -> Path:
        return self._cookie_path

    def set_cookie(self, cookie: str, *, source: str = "unknown") -> None:
        normalized = cookie.strip()
        self._data_dir.mkdir(parents=True, exist_ok=True)
        with open(self._cookie_path, "w", encoding="utf-8") as f:
            json.dump(
                {"cookie": normalized, "source": source.strip() or "unknown"},
                f,
                ensure_ascii=False,
            )

    def load_cookie(self) -> str:
        if not self._cookie_path.exists():
            return ""
        with open(self._cookie_path, encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            return ""
        return str(payload.get("cookie", "") or "").strip()


def resolve_x_cookie(*, data_dir: Path, cookie_env: str = "OPENBILICLAW_X_COOKIE") -> str:
    """为服务端发现解析 X (Twitter) Cookie 头。

    环境变量是调试用的显式覆盖，而浏览器扩展为日常使用保持
    ``data/x_cookie.json`` 最新。环境变量始终优先于持久化文件
    （与 ``resolve_douyin_cookie`` 一致）。
    """
    env_cookie = os.environ.get(cookie_env, "").strip()
    if env_cookie:
        return env_cookie
    return XCookieManager(data_dir).load_cookie()

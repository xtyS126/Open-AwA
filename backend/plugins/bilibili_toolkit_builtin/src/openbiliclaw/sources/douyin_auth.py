"""直连 Cookie 发现所用的抖音 Cookie 持久化辅助函数。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class DouyinCookieRecord:
    """存储的抖音 Cookie 头及其轻量来源信息。"""

    cookie: str
    source: str = "unknown"


class DouyinCookieManager:
    """将用户抖音 Cookie 头存储在 config.toml 之外。"""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._cookie_path = data_dir / "douyin_cookie.json"

    @property
    def cookie_path(self) -> Path:
        return self._cookie_path

    def set_cookie(self, cookie: str, *, source: str = "unknown") -> None:
        normalized = cookie.strip()
        self._data_dir.mkdir(parents=True, exist_ok=True)
        with open(self._cookie_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "cookie": normalized,
                    "source": source.strip() or "unknown",
                },
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

    def load_record(self) -> DouyinCookieRecord | None:
        if not self._cookie_path.exists():
            return None
        with open(self._cookie_path, encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            return None
        cookie = str(payload.get("cookie", "") or "").strip()
        if not cookie:
            return None
        return DouyinCookieRecord(
            cookie=cookie,
            source=str(payload.get("source", "") or "unknown").strip() or "unknown",
        )

    def clear_cookie(self) -> None:
        if self._cookie_path.exists():
            self._cookie_path.unlink()


def resolve_douyin_cookie(
    *,
    data_dir: Path,
    cookie_env: str = "OPENBILICLAW_DOUYIN_COOKIE",
) -> str:
    """解析直连发现所用的抖音 Cookie。

    环境变量仍作为调试用的显式覆盖项，
    而浏览器扩展可在日常使用中保持 ``data/douyin_cookie.json`` 最新。
    """
    env_cookie = os.environ.get(cookie_env, "").strip()
    if env_cookie:
        return env_cookie
    return DouyinCookieManager(data_dir).load_cookie()

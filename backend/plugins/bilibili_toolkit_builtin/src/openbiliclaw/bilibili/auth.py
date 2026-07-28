"""Bilibili 的认证与 cookie 管理。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from .api import NavInfo

logger = logging.getLogger(__name__)


class SupportsNavClient(Protocol):
    """AuthManager 使用的 API 客户端协议。"""

    async def get_nav_info(self) -> NavInfo: ...

    async def close(self) -> None: ...


@dataclass
class AuthStatus:
    """用于 CLI 和 services 的结构化认证状态。"""

    has_cookie: bool
    authenticated: bool
    cookie_path: Path
    username: str = ""
    user_id: int = 0
    message: str = ""


class AuthManager:
    """管理 Bilibili 认证状态。

    支持：
    - 基于 cookie 的认证（来自浏览器）
    - 无登录模式（功能受限）
    """

    def __init__(
        self,
        data_dir: Path,
        *,
        api_client_factory: Callable[[str], SupportsNavClient] | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._cookie_path = data_dir / "bilibili_cookie.json"
        self._cookie: str = ""
        self._api_client_factory = api_client_factory or self._default_api_client_factory

    @property
    def is_authenticated(self) -> bool:
        """是否持有有效的认证 cookie。"""
        return bool(self._cookie)

    @property
    def cookie(self) -> str:
        """当前 cookie 字符串。"""
        return self._cookie

    def set_cookie(self, cookie: str) -> None:
        """设置并持久化认证 cookie。

        Args:
            cookie: 来自浏览器的 cookie 字符串。
        """
        self._cookie = cookie.strip()
        self._save_cookie()
        logger.info("Cookie set and saved.")

    def load_cookie(self) -> str:
        """从磁盘加载持久化的 cookie。

        Returns:
            cookie 字符串，未找到时返回空字符串。
        """
        if self._cookie_path.exists():
            # encoding="utf-8" 与 save_cookie() 保持一致 —— Bilibili cookie
            # 是 ASCII，因此该 bug 在生产环境不会触发，但平台默认编码在
            # Windows GBK 下，如果未来 cookie 字段携带非 ASCII 字符，
            # 仍有 UnicodeDecodeError 风险。
            with open(self._cookie_path, encoding="utf-8") as f:
                data = json.load(f)
                self._cookie = data.get("cookie", "")
                logger.info("Cookie loaded from disk.")
        return self._cookie

    async def validate_cookie(self, cookie: str) -> AuthStatus:
        """针对 Bilibili nav 端点校验 cookie 字符串。"""
        normalized_cookie = cookie.strip()
        if not normalized_cookie:
            return AuthStatus(
                has_cookie=False,
                authenticated=False,
                cookie_path=self._cookie_path,
                message="未提供有效的 Cookie。",
            )

        client = self._api_client_factory(normalized_cookie)
        try:
            nav = await client.get_nav_info()
        except Exception as exc:
            logger.warning("Cookie validation failed: %s", exc)
            return AuthStatus(
                has_cookie=True,
                authenticated=False,
                cookie_path=self._cookie_path,
                message=str(exc),
            )
        finally:
            await client.close()

        if not nav.is_login:
            return AuthStatus(
                has_cookie=True,
                authenticated=False,
                cookie_path=self._cookie_path,
                message="当前 Cookie 未登录或已失效。",
            )

        return AuthStatus(
            has_cookie=True,
            authenticated=True,
            cookie_path=self._cookie_path,
            username=nav.uname,
            user_id=nav.mid,
            message="Cookie 验证成功。",
        )

    async def get_status(self) -> AuthStatus:
        """获取当前持久化的认证状态。"""
        cookie = self.load_cookie()
        if not cookie.strip():
            return AuthStatus(
                has_cookie=False,
                authenticated=False,
                cookie_path=self._cookie_path,
                message="未配置 B 站 Cookie。",
            )
        return await self.validate_cookie(cookie)

    def _save_cookie(self) -> None:
        """将 cookie 持久化到磁盘。始终使用 UTF-8 —— 见 load_cookie()。"""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        with open(self._cookie_path, "w", encoding="utf-8") as f:
            json.dump({"cookie": self._cookie}, f)

    def clear_cookie(self) -> None:
        """清除已存储的 cookie。"""
        self._cookie = ""
        if self._cookie_path.exists():
            self._cookie_path.unlink()
        logger.info("Cookie cleared.")

    @staticmethod
    def _default_api_client_factory(cookie: str) -> SupportsNavClient:
        """创建默认的 Bilibili API 客户端。"""
        from .api import BilibiliAPIClient

        return BilibiliAPIClient(cookie=cookie)


def resolve_runtime_cookie(*, data_dir: Path, configured_cookie: str) -> str:
    """解析运行时命令使用的 cookie。

    命令应优先使用显式配置的 cookie，但透明地回退到之前由
    `auth login` 保存的 cookie。
    """
    normalized_cookie = configured_cookie.strip()
    if normalized_cookie:
        return normalized_cookie
    return AuthManager(data_dir).load_cookie().strip()

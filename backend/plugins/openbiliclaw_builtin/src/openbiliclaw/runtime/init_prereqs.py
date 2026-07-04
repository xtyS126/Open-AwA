"""引导式初始化的带缓存前置探测（gui-init 规范 §3，方案 C1）。

这些探测供 ``GET /api/init-status`` 的 ``prerequisites`` 块使用。所有
探测都带 TTL 缓存 + 单次并发，避免轮询 UI 反复打 chat provider 或
Bilibili（仅 validate_cookie 一次就要约 30 秒）。绑定到
RuntimeContext，并懒读取 ``ctx.llm_registry`` / ``ctx.config``。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from openbiliclaw.bilibili.auth import AuthManager

logger = logging.getLogger(__name__)

# 严格就绪判定：前置条件只有在真实探测请求成功时才视为 "ok"。
# 成功时缓存更久；失败/超时缓存更短，使刚启动（或刚完成冷模型加载）
# 的服务能在几秒内变绿，而不是在完整的成功 TTL 内一直保持红。
# 超时设得足够宽以覆盖 Ollama 冷加载，但仍会失败（而不是乐观地通过）
# 当服务始终无应答时。
_CHAT_OK_TTL = 30.0
_CHAT_FAIL_TTL = 8.0
_CHAT_PROBE_TIMEOUT = 15.0
_BILI_OK_TTL = 60.0
_BILI_FAIL_TTL = 10.0
_BILI_PROBE_TIMEOUT = 12.0

_PLATFORM_SOURCE_FIELDS = ("bilibili", "xiaohongshu", "douyin", "youtube", "twitter")


class InitPrereqs:
    """绑定到 RuntimeContext 的 TTL 缓存前置探测。"""

    def __init__(self, ctx: Any) -> None:
        self._ctx = ctx
        self._chat_value = False
        self._chat_at = float("-inf")
        self._chat_lock = asyncio.Lock()
        self._bili_value = "checking"
        self._bili_at = float("-inf")
        self._bili_lock = asyncio.Lock()

    async def chat_ready(self) -> bool:
        """默认 chat provider 当前是否能 *正常* 完成。

        已构建 registry 是必要非充分条件（配置了 Ollama 但模型从未
        拉取过，调用时会 404），所以这里做一次真实的 ``health_check``
        （一次极小 completion）——带缓存、单次并发，并在冷加载超时时
        乐观返回（与 embedding 就绪判定一致）。
        """
        registry = getattr(self._ctx, "llm_registry", None)
        if registry is None:
            return False
        ttl = _CHAT_OK_TTL if self._chat_value else _CHAT_FAIL_TTL
        if time.monotonic() - self._chat_at < ttl:
            return self._chat_value
        async with self._chat_lock:
            ttl = _CHAT_OK_TTL if self._chat_value else _CHAT_FAIL_TTL
            if time.monotonic() - self._chat_at < ttl:
                return self._chat_value
            try:
                provider = registry.get()  # 默认 chat provider
                ready = bool(
                    await asyncio.wait_for(provider.health_check(), timeout=_CHAT_PROBE_TIMEOUT)
                )
            except TimeoutError:
                # 严格：前置条件必须确认真实请求成功。超时意味着我们
                # 无法在（宽裕、容忍冷加载的）窗口内确认 provider
                # 应答 → 报告未就绪，避免 checklist 给未经验证的 chat
                # 服务亮绿灯。
                logger.debug("Chat readiness probe timed out; reporting not ready")
                ready = False
            except Exception:
                logger.debug("Chat readiness probe errored", exc_info=True)
                ready = False
            self._chat_value = ready
            self._chat_at = time.monotonic()
            return ready

    async def bilibili_check(self) -> str:
        """针对配置的 B 站 cookie 返回 ``ok`` / ``failed`` / ``checking``。

        真实校验（validate_cookie 会请求 B 站 nav），但带 TTL 缓存，
        避免轮询反复做约 30 秒的往返：成功缓存 60 秒，失败缓存 10 秒。
        """
        cfg = getattr(self._ctx, "config", None)
        cookie = ""
        if cfg is not None:
            cookie = str(getattr(getattr(cfg, "bilibili", None), "cookie", "") or "").strip()
        if cfg is None or not cookie:
            return "failed"

        ttl = _BILI_OK_TTL if self._bili_value == "ok" else _BILI_FAIL_TTL
        if self._bili_value != "checking" and time.monotonic() - self._bili_at < ttl:
            return self._bili_value

        async with self._bili_lock:
            ttl = _BILI_OK_TTL if self._bili_value == "ok" else _BILI_FAIL_TTL
            if self._bili_value != "checking" and time.monotonic() - self._bili_at < ttl:
                return self._bili_value
            try:
                manager = AuthManager(data_dir=cfg.data_path)
                status = await asyncio.wait_for(
                    manager.validate_cookie(cookie), timeout=_BILI_PROBE_TIMEOUT
                )
                self._bili_value = "ok" if status.authenticated else "failed"
            except Exception:
                logger.debug("Bilibili cookie probe errored/timed out", exc_info=True)
                self._bili_value = "failed"
            self._bili_at = time.monotonic()
            return self._bili_value

    def enabled_platforms(self) -> list[str]:
        """配置中当前启用的平台源族。"""
        sources = getattr(getattr(self._ctx, "config", None), "sources", None)
        if sources is None:
            return []
        return [
            name
            for name in _PLATFORM_SOURCE_FIELDS
            if getattr(getattr(sources, name, None), "enabled", False)
        ]

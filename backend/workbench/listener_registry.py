"""工作台预览 listener 归属验证器注册表。"""

from __future__ import annotations

import inspect
from threading import RLock
from typing import Awaitable, Callable

from loguru import logger

from workbench.preview_lease import PreviewSessionKind


ListenerVerifier = Callable[
    [str, str, PreviewSessionKind, str, int],
    Awaitable[bool] | bool,
]


class PreviewListenerVerifierRegistry:
    """按会话类型分发 listener 归属验证，未注册或异常时拒绝。"""

    def __init__(self) -> None:
        self._verifiers: dict[PreviewSessionKind, ListenerVerifier] = {}
        self._lock = RLock()

    def register(
        self,
        session_kind: PreviewSessionKind,
        verifier: ListenerVerifier,
    ) -> None:
        """注册指定会话类型的唯一验证器。"""
        with self._lock:
            self._verifiers[session_kind] = verifier

    def unregister(
        self,
        session_kind: PreviewSessionKind,
        verifier: ListenerVerifier | None = None,
    ) -> None:
        """注销验证器；传入实例时只移除仍匹配的注册。"""
        with self._lock:
            current = self._verifiers.get(session_kind)
            if current is None or (verifier is not None and current is not verifier):
                return
            self._verifiers.pop(session_kind, None)

    async def verify(
        self,
        user_id: str,
        project_id: str,
        session_kind: PreviewSessionKind,
        session_id: str,
        port: int,
    ) -> bool:
        """调用已注册验证器，所有缺失、异常和非真值结果均按拒绝处理。"""
        with self._lock:
            verifier = self._verifiers.get(session_kind)
        if verifier is None:
            return False
        try:
            result = verifier(user_id, project_id, session_kind, session_id, port)
            if inspect.isawaitable(result):
                result = await result
            return result is True
        except Exception:
            logger.bind(
                event="preview_listener_verification_failed",
                session_kind=session_kind.value,
            ).opt(exception=True).warning("预览 listener 归属验证失败，已拒绝请求")
            return False


listener_verifier_registry = PreviewListenerVerifierRegistry()


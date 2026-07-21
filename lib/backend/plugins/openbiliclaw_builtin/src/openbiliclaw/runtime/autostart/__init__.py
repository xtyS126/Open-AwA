"""用户级开机自启注册。"""

from __future__ import annotations

import sys

from openbiliclaw import docker_runtime

from .base import AutostartManager, AutostartStatus


def _unsupported_reason() -> str:
    if docker_runtime.is_running_in_container():
        return "unsupported_docker_runtime"
    return "unsupported_platform"


def get_manager() -> AutostartManager | None:
    """返回当前平台的管理器；不支持时返回 ``None``。"""
    if docker_runtime.is_running_in_container():
        return None

    try:
        if sys.platform == "darwin":
            from .macos import MacOSLaunchAgentManager

            return MacOSLaunchAgentManager()
        if sys.platform == "win32":
            from .windows import WindowsRunManager

            return WindowsRunManager()
        if sys.platform.startswith("linux"):
            from .linux import LinuxXdgAutostartManager

            return LinuxXdgAutostartManager()
    except ModuleNotFoundError:
        return None
    return None


def is_supported() -> bool:
    """返回当前运行时是否支持管理用户自启。"""
    return get_manager() is not None


def register(config: object) -> None:
    """注册当前平台的自启项。"""
    manager = get_manager()
    if manager is None:
        raise RuntimeError(_unsupported_reason())
    manager.register(config)  # type: ignore[arg-type]


def unregister() -> None:
    """移除当前平台的自启项。"""
    manager = get_manager()
    if manager is None:
        raise RuntimeError(_unsupported_reason())
    manager.unregister()


def status() -> AutostartStatus:
    """返回当前平台的自启状态。"""
    manager = get_manager()
    if manager is None:
        return AutostartStatus(
            supported=False,
            registered=False,
            platform=sys.platform,
            mechanism="none",
            reason=_unsupported_reason(),
        )
    return AutostartStatus(
        supported=True,
        registered=manager.is_registered(),
        platform=sys.platform,
        mechanism=manager.mechanism,
        reason="none",
    )


__all__ = [
    "AutostartManager",
    "AutostartStatus",
    "get_manager",
    "is_supported",
    "register",
    "status",
    "unregister",
]

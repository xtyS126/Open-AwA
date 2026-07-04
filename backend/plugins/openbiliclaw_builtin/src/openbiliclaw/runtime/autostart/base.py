"""开机自启管理器的通用契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path

    from openbiliclaw.config import Config


@dataclass(frozen=True)
class LaunchSpec:
    """操作系统自启项所用的、解析后的后端启动命令。"""

    argv: list[str]
    working_dir: Path
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AutostartStatus:
    """当前的自启支持情况与注册状态。"""

    supported: bool
    registered: bool
    platform: str
    mechanism: str
    reason: str = "none"
    detail: str = ""


class AutostartManager(Protocol):
    """按平台区分的用户级自启管理器。"""

    mechanism: str

    def register(self, config: Config) -> None:
        """注册后端在用户下次登录时启动。"""

    def unregister(self) -> None:
        """移除用户级的自启注册。"""

    def is_registered(self) -> bool:
        """返回平台自启项当前是否已存在。"""

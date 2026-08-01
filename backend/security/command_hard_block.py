"""
系统级危险命令硬阻断策略。

该模块是 ACP、沙箱和终端入口的单一真相源。命中规则时必须直接拒绝，
不得降级为普通审批，也不得受“工作区命令不受限”配置影响。
"""

from __future__ import annotations

import re


HARD_BLOCKED_COMMAND_SUBSTRINGS = (
    "rm -rf /",
    "sudo rm -rf",
    "mkfs",
    "dd if=",
)

_HARD_BLOCKED_COMMAND_PATTERNS = (
    re.compile(r"\brm\s+-rf\s+/", re.IGNORECASE),
    re.compile(r"\bsudo\s+rm\s+-rf\b", re.IGNORECASE),
    re.compile(r"\bmkfs(?:\.[a-z0-9_-]+)?\b", re.IGNORECASE),
    re.compile(r"\bdd\s+if\s*=", re.IGNORECASE),
)


def is_hard_blocked_command(command: str) -> bool:
    """判断命令是否命中不可绕过的系统级硬阻断规则。"""
    return any(pattern.search(command) for pattern in _HARD_BLOCKED_COMMAND_PATTERNS)


__all__ = [
    "HARD_BLOCKED_COMMAND_SUBSTRINGS",
    "is_hard_blocked_command",
]

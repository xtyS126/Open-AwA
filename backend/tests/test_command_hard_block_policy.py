"""
命令硬阻断策略的一致性回归测试。

确保 ACP、沙箱与终端入口共享同一套不可绕过的系统级危险命令判定。
"""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "sudo rm -rf /var/log",
        "mkfs.ext4 /dev/sda",
        "dd if=/dev/zero of=/dev/sda bs=1M",
    ],
)
def test_shared_policy_blocks_system_destructive_commands(command: str) -> None:
    """共享策略必须拒绝四类系统级破坏命令。"""
    spec = importlib.util.find_spec("security.command_hard_block")
    assert spec is not None, "缺少统一的 security.command_hard_block 策略模块"

    policy = importlib.import_module("security.command_hard_block")
    assert policy.is_hard_blocked_command(command) is True


def test_command_entrypoints_delegate_to_shared_policy() -> None:
    """执行入口不得继续维护本地硬阻断字面量。"""
    backend_root = Path(__file__).resolve().parents[1]
    entrypoints = (
        backend_root / "acp_host" / "permissions.py",
        backend_root / "security" / "sandbox.py",
        backend_root / "core" / "builtin_tools" / "terminal_executor.py",
        backend_root / "api" / "routes" / "terminal.py",
    )

    for entrypoint in entrypoints:
        source = entrypoint.read_text(encoding="utf-8-sig")
        assert "security.command_hard_block" in source, (
            f"{entrypoint.relative_to(backend_root)} 未委托统一硬阻断策略"
        )

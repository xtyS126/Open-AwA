"""
硬底线检查器：定义自主模式下永远禁止的操作。

无论配置如何，以下操作始终被拒绝：
- 系统破坏命令
- 敏感系统路径访问
- 修改自身配置文件
- 提权操作

自主模式下被拒操作直接返回错误，绝不阻塞等待用户确认。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from core.autonomous.config import AutonomousConfig

# ──── 系统破坏命令模式 ──────────────────────────────────────────
# 这些命令在任何模式下都被禁止
_SYSTEM_DESTROY_PATTERNS: list[re.Pattern] = [
    re.compile(r'\brm\s+-rf\s+/'),          # rm -rf /
    re.compile(r'\brm\s+-rf\s+/\*'),         # rm -rf /*
    re.compile(r'\bdel\s+/s\s+/q\s+\\.*'),  # Windows del /s /q C:\*
    re.compile(r'\bformat\b'),               # 格式化磁盘
    re.compile(r'\bmkfs\.'),                 # 创建文件系统
    re.compile(r'\bdd\s+.*of=/dev/'),        # 直接写入块设备
    re.compile(r'\bshutdown\b'),             # 关机
    re.compile(r'\breboot\b'),               # 重启
    re.compile(r'\bhalt\b'),                 # 停机
    re.compile(r'\bsudo\b'),                 # sudo 提权
    re.compile(r'\bsu\s'),                   # su 切换用户
    re.compile(r'\bchmod\s+777\s+/'),        # chmod 777 根路径
    re.compile(r':\(\)\s*\{\s*:\|\:&\s*\}\s*;\s*:'),  # Fork 炸弹
]

# ──── 敏感系统路径（读写均拒绝） ────────────────────────────────
_SENSITIVE_SYSTEM_PATHS: frozenset = frozenset({
    "/etc/shadow",
    "/etc/passwd",
    "/etc/sudoers",
    "/etc/sudoers.d",
    "/etc/ssh",
    "/proc",
    "/sys",
    "/boot",
    "/root/.ssh",
})

# ──── 受保护的自身配置文件（可以读取，禁止修改/删除） ──────────
_PROTECTED_SELF_PATTERNS: list[str] = [
    ".env",
    ".env.local",
    ".env.production",
    "CLAUDE.md",
    "AGENTS.md",
    ".claude/",
    "config/settings.py",
    "config/security.py",
    "scripts/code-audit.ps1",
]


class HardDenyChecker:
    """硬底线检查器。

    在自主模式下，所有工具执行前需通过此检查器的校验。
    被拒操作立即返回明确的错误信息，不创建 PermissionRequest。
    """

    def __init__(self, config: AutonomousConfig):
        self._config = config
        # 从工作区路径推导受保护文件列表
        ws_root = Path(config.workspace_root) if config.workspace_root else None
        self._protected_files: list[Path] = []
        if ws_root and ws_root.exists():
            for pattern in _PROTECTED_SELF_PATTERNS:
                # 仅检查工作区内的匹配文件
                for matched in ws_root.glob(f"**/{pattern}"):
                    self._protected_files.append(matched.resolve())
                # 也直接检查 pattern 本身
                candidate = ws_root / pattern
                if candidate.exists():
                    self._protected_files.append(candidate.resolve())

    def check_command(self, command: str) -> Tuple[bool, str]:
        """检查命令是否在系统破坏黑名单中。

        Returns:
            (is_safe, error_message) — safe 时 error_message 为空字符串
        """
        if not command or not isinstance(command, str):
            return True, ""

        lower_cmd = command.lower().strip()

        for pattern in _SYSTEM_DESTROY_PATTERNS:
            if pattern.search(lower_cmd):
                logger.warning(f"[硬底线] 拒绝执行危险命令: {command[:120]}")
                return False, (
                    f"硬底线拒绝: 命令 '{command[:80]}...' 匹配了禁止模式 "
                    f"'{pattern.pattern}'。此命令在任何模式下均不可执行。"
                )

        return True, ""

    def check_path(self, target_path: str) -> Tuple[bool, str]:
        """检查路径是否为敏感系统路径。

        注意：此方法仅检查是否为系统敏感路径，
        工作区边界检查由 WorkspaceBoundary 负责。

        同时检查原始路径和解析后路径，防止 Windows 平台下
        /etc/shadow 解析为 C:/etc/shadow 绕过检查。

        Returns:
            (is_safe, error_message)
        """
        if not target_path:
            return True, ""

        # 标准化路径用于比较
        normalized = target_path.replace("\\", "/").rstrip("/")

        try:
            resolved = str(Path(target_path).resolve()).replace("\\", "/").rstrip("/")
        except (OSError, ValueError):
            resolved = normalized  # 无法解析时使用原始路径

        # 检查敏感系统路径（同时匹配原始路径和解析后路径）
        for sensitive in _SENSITIVE_SYSTEM_PATHS:
            sensitive_norm = sensitive.replace("\\", "/").rstrip("/")
            if (normalized == sensitive_norm
                    or normalized.startswith(sensitive_norm + "/")
                    or resolved == sensitive_norm
                    or resolved.startswith(sensitive_norm + "/")):
                logger.warning(f"[硬底线] 拒绝访问敏感路径: {target_path}")
                return False, (
                    f"硬底线拒绝: 路径 '{target_path}' 指向受保护的系统目录 "
                    f"'{sensitive}'。访问此路径在任何模式下均被禁止。"
                )

        return True, ""

    def check_protected_config(self, target_path: str) -> Tuple[bool, str]:
        """检查目标路径是否为受保护的自身配置文件。

        读取操作允许，但修改/删除操作拒绝。

        Returns:
            (is_safe, error_message) — 允许修改时返回 True
        """
        if not target_path:
            return True, ""

        try:
            resolved = Path(target_path).resolve()
        except (OSError, ValueError):
            return True, ""

        for protected in self._protected_files:
            try:
                if resolved == protected or protected in resolved.parents:
                    logger.warning(f"[硬底线] 拒绝修改受保护配置: {resolved}")
                    return False, (
                        f"硬底线拒绝: 文件 '{target_path}' 是受保护的配置文件。"
                        f"在自主模式下不允许修改环境变量或系统配置。"
                    )
            except (OSError, ValueError):
                continue

        return True, ""

    def check_all(self, action: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """一站式硬底线检查。

        Args:
            action: 操作类型（如 'execute_command'、'write_file'）
            params: 操作参数

        Returns:
            None 表示全部通过，dict 表示拒绝原因
        """
        # 检查命令
        command = str(params.get("command") or params.get("cmd") or "")
        if command:
            safe, reason = self.check_command(command)
            if not safe:
                return {
                    "ok": False,
                    "error": reason,
                    "denied_by": "hard_deny",
                    "recoverable": False,
                    "suggestion": "该操作在任何模式下均被禁止，请寻找替代方案。",
                }

        # 检查路径
        path = str(params.get("path") or params.get("file") or params.get("target") or "")
        if path:
            # 系统敏感路径
            safe, reason = self.check_path(path)
            if not safe:
                return {
                    "ok": False,
                    "error": reason,
                    "denied_by": "hard_deny",
                    "recoverable": False,
                    "suggestion": "请将操作限定在工作区目录内。",
                }

            # 受保护的自身配置（写入操作时检查）
            write_actions = {"write_file", "delete_file", "edit", "run_command", "execute"}
            if any(a in action for a in write_actions):
                safe, reason = self.check_protected_config(path)
                if not safe:
                    return {
                        "ok": False,
                        "error": reason,
                        "denied_by": "hard_deny",
                        "recoverable": False,
                        "suggestion": "环境变量和系统配置文件不允许被修改。",
                    }

        return None


# 全局默认实例（在 AutonomousModeManager 初始化时创建）
_default_checker: Optional[HardDenyChecker] = None


def get_hard_deny_checker() -> Optional[HardDenyChecker]:
    """获取当前 HardDenyChecker 实例。未初始化时返回 None。"""
    return _default_checker


def set_hard_deny_checker(checker: HardDenyChecker) -> None:
    """设置全局 HardDenyChecker 实例。"""
    global _default_checker
    _default_checker = checker

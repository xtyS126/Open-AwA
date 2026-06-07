"""
工作区边界校验模块。

确保自主模式下所有文件操作限制在 WORKSPACE 根目录内，
防止路径穿越和符号链接越界。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from loguru import logger

from core.autonomous.config import AutonomousConfig


class WorkspaceBoundary:
    """工作区边界校验器。

    拒绝所有尝试越界的文件操作，包括：
    - 绝对路径指向工作区外
    - ../ 序列穿越工作区边界
    - 符号链接指向工作区外
    """

    def __init__(self, config: AutonomousConfig):
        if not config.workspace_root:
            raise ValueError("工作区根路径未配置")
        self._root = Path(config.workspace_root).resolve()
        if not self._root.exists():
            raise ValueError(f"工作区路径不存在: {self._root}")
        if not self._root.is_dir():
            raise ValueError(f"工作区路径不是目录: {self._root}")
        logger.info(f"工作区边界已设置: {self._root}")

    @property
    def root(self) -> Path:
        """返回工作区根路径。"""
        return self._root

    def check(self, target_path: str) -> Tuple[bool, str]:
        """检查目标路径是否在工作区边界内。

        支持相对路径（相对于工作区根）和绝对路径。

        Returns:
            (is_inside, error_message) — 越界时 is_inside=False 并包含原因
        """
        if not target_path:
            return True, ""

        try:
            # 相对路径相对于工作区根解析
            path = Path(target_path)
            if not path.is_absolute():
                resolved = (self._root / path).resolve()
            else:
                resolved = path.resolve()

            # 检查是否在工作区根目录内
            try:
                resolved.relative_to(self._root)
                return True, ""
            except ValueError:
                logger.warning(f"[工作区边界] 越界访问被拒绝: {resolved} (工作区: {self._root})")
                return False, (
                    f"工作区边界拒绝: 路径 '{target_path}' 解析后 '{resolved}' "
                    f"在工作区根目录 '{self._root}' 之外。"
                    f"请将文件操作限定在工作区范围内。"
                )
        except (OSError, ValueError) as e:
            logger.warning(f"[工作区边界] 路径解析失败: {target_path}: {e}")
            return False, f"工作区边界拒绝: 路径 '{target_path}' 无法解析: {e}"

    def check_symlink(self, target_path: str) -> Tuple[bool, str]:
        """检查路径（如果是符号链接）的最终目标是否在工作区内。

        对符号链接进行二次校验，防止通过符号链接越界。
        """
        if not target_path:
            return True, ""

        try:
            path = Path(target_path)
            if not path.is_absolute():
                path = (self._root / path)
            resolved = path.resolve()

            # 如果是符号链接，检查目标
            if path.is_symlink():
                try:
                    resolved.relative_to(self._root)
                except ValueError:
                    logger.warning(
                        f"[工作区边界] 符号链接越界被拒绝: {target_path} -> {resolved}"
                    )
                    return False, (
                        f"工作区边界拒绝: 符号链接 '{target_path}' 指向 "
                        f"工作区外的目标 '{resolved}'。"
                    )

            return True, ""
        except (OSError, ValueError) as e:
            return False, f"工作区边界拒绝: 符号链接检查失败 '{target_path}': {e}"

    def check_all(self, path_value: str) -> Optional[Dict[str, Any]]:
        """一站式检查路径是否在工作区内。

        Returns:
            None 表示通过，dict 表示拒绝原因
        """
        if not path_value:
            return None

        # 基本边界检查
        inside, reason = self.check(path_value)
        if not inside:
            return {
                "ok": False,
                "error": reason,
                "denied_by": "workspace",
                "recoverable": True,
                "suggestion": (
                    f"请将文件操作限定在工作区目录内。"
                    f"工作区根路径: {self._root}"
                ),
            }

        # 符号链接检查
        inside, reason = self.check_symlink(path_value)
        if not inside:
            return {
                "ok": False,
                "error": reason,
                "denied_by": "workspace",
                "recoverable": True,
                "suggestion": "请确保符号链接指向工作区内的目标。",
            }

        return None


# 全局默认实例
_default_boundary: Optional[WorkspaceBoundary] = None


def get_workspace_boundary() -> Optional[WorkspaceBoundary]:
    """获取当前 WorkspaceBoundary 实例。"""
    return _default_boundary


def set_workspace_boundary(boundary: WorkspaceBoundary) -> None:
    """设置全局 WorkspaceBoundary 实例。"""
    global _default_boundary
    _default_boundary = boundary

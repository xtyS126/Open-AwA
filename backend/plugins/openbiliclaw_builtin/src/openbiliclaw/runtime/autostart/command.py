"""解析 OS 自启项使用的后端启动命令。"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from openbiliclaw.config import _project_root

from .base import LaunchSpec

if TYPE_CHECKING:
    from openbiliclaw.config import Config


def _path_with_ollama() -> str:
    path_value = os.environ.get("PATH", "")
    parts = [part for part in path_value.split(os.pathsep) if part]
    ollama = shutil.which("ollama")
    if ollama:
        ollama_dir = str(Path(ollama).resolve().parent)
        if ollama_dir not in parts:
            parts.insert(0, ollama_dir)
    return os.pathsep.join(parts)


def build_launch_spec(config: Config) -> LaunchSpec:
    """构建嵌入 OS 自启项的稳定后端命令。"""
    del config  # 保留签名以备配置驱动字段扩展，便于管理器统一调用。
    working_dir = _project_root()
    return LaunchSpec(
        argv=[sys.executable, "-m", "openbiliclaw.cli", "start"],
        working_dir=working_dir,
        env={
            "OPENBILICLAW_PROJECT_ROOT": str(working_dir),
            "PATH": _path_with_ollama(),
        },
    )


def resolve_pythonw(executable: str | Path | None = None) -> Path:
    """若 ``executable`` 旁存在 pythonw.exe 则返回它，否则返回原可执行文件。"""
    python = Path(executable) if executable is not None else Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    return pythonw if pythonw.exists() else python

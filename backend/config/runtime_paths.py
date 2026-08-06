"""项目运行时目录的统一解析。"""

from __future__ import annotations

import os
from pathlib import Path


# __file__ = backend/config/runtime_paths.py，parents[2] 为项目根目录。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"
VAR_DIR = PROJECT_ROOT / "var"
DATA_DIR = VAR_DIR / "data"
LOG_DIR = VAR_DIR / "logs"
WORKSPACE_DIR = VAR_DIR / "workspace"
PLUGINS_DATA_DIR = VAR_DIR / "plugins"
PETS_DATA_DIR = VAR_DIR / "pets"
STATE_DIR = VAR_DIR / "state"
UPLOADS_DIR = DATA_DIR / "uploads"
TOOL_OUTPUTS_DIR = UPLOADS_DIR / "tool_outputs"
DOWNLOADS_DIR = DATA_DIR / "downloads"
# APP 更新包部署目录：release-apk 脚本构建后在此放置 manifest.json + APK
APK_DIR = VAR_DIR / "apk"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"


def get_workspace_dir() -> Path:
    """返回工作区目录，并兼容显式的环境变量覆盖。"""
    configured_path = os.getenv("WORKSPACE_DIR", "").strip()
    if configured_path:
        return Path(configured_path).expanduser().resolve()
    return WORKSPACE_DIR


def ensure_runtime_directories() -> None:
    """创建应用需要的运行时目录。"""
    for runtime_dir in (
        VAR_DIR,
        DATA_DIR,
        LOG_DIR,
        get_workspace_dir(),
        PLUGINS_DATA_DIR,
        PETS_DATA_DIR,
        STATE_DIR,
        UPLOADS_DIR,
        TOOL_OUTPUTS_DIR,
        DOWNLOADS_DIR,
        TRANSCRIPTS_DIR,
        APK_DIR,
    ):
        runtime_dir.mkdir(parents=True, exist_ok=True)

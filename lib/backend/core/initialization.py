"""
首次部署检测模块。

通过 `{DATA_DIR}/.initialized` 标记文件标识系统是否已完成首次部署初始化，
避免每次启动重复执行 `ensure_*` 系列写入操作。

公共函数：
- `get_initialized_marker_path()`：解析标记文件路径（按 INITIALIZED_MARKER_PATH → DATA_DIR → var/data 优先级）
- `is_initialized()`：仅检查标记文件存在性，不读取文件内容
- `get_initialization_status()`：返回完整状态字典（含 initialized_at / version / steps_completed）
- `mark_initialized(steps_completed)`：原子写入标记文件（先写 .tmp 再 os.replace）
- `reset_initialization()`：删除标记文件，不存在时静默返回
- `has_any_user(db_session)`：检查数据库是否已有任意用户（仅 count() > 0，不读取字段值）
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from db.models import User


INITIALIZED_MARKER_FILENAME: str = ".initialized"
"""标记文件名，固定为 .initialized。"""

INITIALIZATION_VERSION: int = 1
"""标记文件 schema 版本，未来升级时递增。"""

_DEFAULT_MARKER_DIR: Path = Path("var/data")
"""标记文件默认目录（相对路径，相对于进程 CWD）。"""


def get_initialized_marker_path() -> Path:
    """返回标记文件路径。

    解析优先级：
    1. `INITIALIZED_MARKER_PATH` 环境变量（绝对路径，Docker 用）
    2. `DATA_DIR` 环境变量 + `.initialized`
    3. `var/data/.initialized`（相对路径，相对于进程 CWD）

    Returns:
        标记文件 Path 对象。
    """
    explicit = os.getenv("INITIALIZED_MARKER_PATH", "").strip()
    if explicit:
        return Path(explicit)

    data_dir = os.getenv("DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir) / INITIALIZED_MARKER_FILENAME

    return _DEFAULT_MARKER_DIR / INITIALIZED_MARKER_FILENAME


def is_initialized() -> bool:
    """检查系统是否已初始化。

    检查标记文件存在性并验证 JSON 合法性：
    - 文件不存在：返回 False
    - 文件存在且为合法 JSON：返回 True
    - 文件存在但 JSON 损坏：返回 False（记录 WARNING，不删除文件）

    Returns:
        True 表示系统已完成首次部署初始化；False 表示未初始化或标记文件损坏。
    """
    marker_path = get_initialized_marker_path()
    if not marker_path.exists():
        return False

    try:
        text = marker_path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        logger.bind(
            event="initialized_marker_corrupt",
            module="core.initialization",
            marker_path=str(marker_path),
            error_type=type(exc).__name__,
            error_message=str(exc),
        ).warning(f"初始化标记文件损坏，视为未初始化（不删除文件）: {marker_path}")
        return False

    if not isinstance(data, dict):
        logger.bind(
            event="initialized_marker_corrupt",
            module="core.initialization",
            marker_path=str(marker_path),
            error_type="InvalidSchema",
        ).warning(f"初始化标记文件结构非法（非 dict），视为未初始化: {marker_path}")
        return False

    return True


def get_initialization_status() -> dict[str, Any]:
    """返回初始化状态完整字典。

    文件不存在时返回未初始化结构；文件存在但 JSON 损坏时记录 WARNING 日志并返回未初始化结构（不删除文件，保留供人工排查）。

    Returns:
        {
            "initialized": bool,
            "initialized_at": str | None,  # ISO 8601，未初始化时为 None
            "version": int | None,         # 1 或 None
            "steps_completed": list[str]   # 空数组或步骤列表
        }
    """
    not_initialized: dict[str, Any] = {
        "initialized": False,
        "initialized_at": None,
        "version": None,
        "steps_completed": [],
    }

    marker_path = get_initialized_marker_path()
    if not marker_path.exists():
        return not_initialized

    try:
        text = marker_path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        logger.bind(
            event="initialized_marker_corrupt",
            module="core.initialization",
            marker_path=str(marker_path),
            error_type=type(exc).__name__,
            error_message=str(exc),
        ).warning(f"初始化标记文件损坏，视为未初始化（不删除文件）: {marker_path}")
        return not_initialized

    if not isinstance(data, dict):
        logger.bind(
            event="initialized_marker_corrupt",
            module="core.initialization",
            marker_path=str(marker_path),
            error_type="InvalidSchema",
        ).warning(f"初始化标记文件结构非法（非 dict），视为未初始化: {marker_path}")
        return not_initialized

    initialized_at = data.get("initialized_at")
    version = data.get("version")
    steps = data.get("steps_completed", [])

    if not isinstance(steps, list):
        steps = []

    return {
        "initialized": True,
        "initialized_at": initialized_at,
        "version": version,
        "steps_completed": list(steps),
    }


def mark_initialized(steps_completed: list[str]) -> None:
    """原子写入标记文件。

    流程：
    1. 调用 `Path.parent.mkdir(parents=True, exist_ok=True)` 确保目录存在
    2. 构造字典 `{"initialized_at": ISO 8601, "version": 1, "steps_completed": [...]}`
    3. 写入 `<marker>.tmp` 临时文件（json.dump + indent=2 + ensure_ascii=False）
    4. 调用 `os.replace(tmp_path, marker_path)` 原子替换
    5. `try/finally` 确保失败时清理 `.tmp` 残留

    Args:
        steps_completed: 已完成的步骤名称列表。

    Raises:
        OSError: 文件系统错误（如磁盘满、权限不足）。
    """
    marker_path = get_initialized_marker_path()
    marker_path.parent.mkdir(parents=True, exist_ok=True)

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "initialized_at": now_iso,
        "version": INITIALIZATION_VERSION,
        "steps_completed": list(steps_completed),
    }

    tmp_path = marker_path.with_suffix(marker_path.suffix + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, marker_path)
    except OSError:
        # 失败时清理 .tmp 残留，避免下次启动误读
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError as cleanup_exc:
                logger.bind(
                    event="marker_tmp_cleanup_failed",
                    module="core.initialization",
                    tmp_path=str(tmp_path),
                ).warning(f"清理标记临时文件失败: {cleanup_exc}")
        raise

    logger.bind(
        event="initialized_marker_written",
        module="core.initialization",
        marker_path=str(marker_path),
        steps_count=len(steps_completed),
    ).info(f"初始化标记文件已写入: {marker_path}")


def reset_initialization() -> None:
    """删除标记文件。不存在时静默返回。"""
    marker_path = get_initialized_marker_path()
    try:
        marker_path.unlink(missing_ok=True)
        logger.bind(
            event="initialized_marker_reset",
            module="core.initialization",
            marker_path=str(marker_path),
        ).info(f"初始化标记文件已删除: {marker_path}")
    except OSError as exc:
        logger.bind(
            event="initialized_marker_reset_failed",
            module="core.initialization",
            marker_path=str(marker_path),
            error_type=type(exc).__name__,
            error_message=str(exc),
        ).warning(f"删除初始化标记文件失败: {exc}")


def has_any_user(db_session: Session) -> bool:
    """检查数据库是否已有任意用户。

    仅执行 `count() > 0` 查询，不读取字段值，不修改数据库。

    Args:
        db_session: SQLAlchemy 会话实例。

    Returns:
        True 表示 `users` 表有至少一条记录；False 表示表为空。

    Raises:
        sqlalchemy.exc.SQLAlchemyError: 数据库连接失败时透传（不包装）。
    """
    return db_session.query(User).count() > 0

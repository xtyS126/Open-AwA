"""访问密钥生成与持久化工具模块。

本模块提供密钥生成、.env.local 读写、文件权限收紧等纯工具函数，
供 `bin/generate_api_key.py`（CLI 入口）与 `core/bootstrap.py`（启动初始化）
共享调用，避免代码重复。

路径常量（BACKEND_DIR / ENV_LOCAL / KEY_NAME）由调用方自行管理；
本模块仅提供无状态的纯函数。
"""

import logging
import re
import secrets
import stat
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 密钥配置项名称（写入 .env.local 时的 key 名）
KEY_NAME = "OPENAWA_API_KEY"


def generate_key() -> str:
    """生成带 sk- 前缀的 43 字符随机密钥。"""
    return "sk-" + secrets.token_urlsafe(32)


def restrict_permissions(path: Path) -> None:
    """将文件权限设为仅 owner 可读写（Unix: 0o600, Windows: 隐藏文件）。

    参数:
        path: 目标文件路径

    说明:
        Windows 下 chmod 行为有限，失败时仅记录 WARNING 不抛异常
    """
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError as exc:
        logger.warning("设置文件权限失败（Windows 下可忽略）: %s", exc)


# 保留私有别名，兼容 core/bootstrap.py 原有调用约定
_restrict_permissions = restrict_permissions


def read_existing_key(env_local_path: Path) -> Optional[str]:
    """从指定 .env.local 文件读取现有 OPENAWA_API_KEY，不存在则返回 None。

    参数:
        env_local_path: .env.local 文件路径
    """
    if not env_local_path.exists():
        return None
    content = env_local_path.read_text(encoding="utf-8")
    match = re.search(rf"^{KEY_NAME}=(.+)$", content, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return None


def persist_key(new_key: str, env_local_path: Path) -> None:
    """将密钥写入指定 .env.local（替换已有行或追加），并设置仅 owner 可读写权限。

    参数:
        new_key: 新生成的密钥字符串
        env_local_path: .env.local 文件路径
    """
    if env_local_path.exists() and env_local_path.stat().st_size > 0:
        content = env_local_path.read_text(encoding="utf-8")
        if re.search(rf"^{KEY_NAME}=", content, re.MULTILINE):
            content = re.sub(
                rf"^{KEY_NAME}=.*$",
                f"{KEY_NAME}={new_key}",
                content,
                flags=re.MULTILINE,
            )
            env_local_path.write_text(content, encoding="utf-8")
            restrict_permissions(env_local_path)
        else:
            with open(env_local_path, "a", encoding="utf-8") as f:
                f.write(f"\n{KEY_NAME}={new_key}\n")
            restrict_permissions(env_local_path)
    else:
        env_local_path.parent.mkdir(parents=True, exist_ok=True)
        env_local_path.write_text(f"{KEY_NAME}={new_key}\n", encoding="utf-8")
        restrict_permissions(env_local_path)

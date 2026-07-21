"""
终端/子进程环境变量安全过滤模块。

将敏感密钥（JWT_SECRET_KEY/ENCRYPTION_KEY/DATABASE_URL/API_KEY 等）从子进程环境变量中剔除，
防止任意已登录用户通过终端或 PTY 执行 `printenv`、`env`、`echo $VAR` 等命令读取敏感信息。

本模块与 acp_host/service.py 中的 _build_safe_env 保持一致逻辑，
但独立导出供 terminal/pty_session 等模块复用，避免循环依赖。
"""

from __future__ import annotations

import os
from typing import Dict


# 敏感环境变量键名（精确匹配，命中即过滤不传递给子进程）
SENSITIVE_ENV_KEYS = {
    "SECRET_KEY", "JWT_SECRET_KEY", "CSRF_SECRET_KEY", "ENCRYPTION_KEY",
    "DATABASE_URL", "DATABASE_PASSWORD",
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
    "DEEPSEEK_API_KEY", "OPENAWA_API_KEY",
}

# 敏感环境变量子串（键名大写后包含任一即过滤）
SENSITIVE_ENV_SUBSTRINGS = ("SECRET", "TOKEN", "PASSWORD", "API_KEY", "PRIVATE_KEY")


def build_safe_env(extra_env: Dict[str, str] | None = None) -> Dict[str, str]:
    """
    构建安全的子进程环境变量，过滤敏感键避免泄露给终端/PTY 子进程。

    终端和 PTY 子进程会执行用户命令，可通过 env/printenv/echo $VAR 等读取环境变量。
    本函数过滤掉含密钥的变量，仅保留运行所需的基础变量。

    Args:
        extra_env: 需要额外注入的环境变量（优先级最高，覆盖父进程值）。

    Returns:
        过滤后的安全环境变量字典。
    """
    safe_env: Dict[str, str] = {}
    for key, value in os.environ.items():
        # 精确匹配黑名单
        if key in SENSITIVE_ENV_KEYS:
            continue
        # 子串匹配（键名大写后检查）
        key_upper = key.upper()
        if any(s in key_upper for s in SENSITIVE_ENV_SUBSTRINGS):
            continue
        safe_env[key] = value

    # 应用额外注入的环境变量（覆盖优先级最高）
    if extra_env:
        safe_env.update(extra_env)

    # 确保必要的基础变量存在
    safe_env.setdefault("PATH", os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"))
    if "HOME" in os.environ:
        safe_env.setdefault("HOME", os.environ["HOME"])
    safe_env.setdefault("TERM", "xterm-256color")

    return safe_env

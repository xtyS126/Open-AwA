"""autostart API、CLI 与启动期自愈逻辑共用的护栏。"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from openbiliclaw.config import load_config

if TYPE_CHECKING:
    from openbiliclaw.config import Config

_PROJECT_ROOT_ENV = "OPENBILICLAW_PROJECT_ROOT"
_PROVIDER_CREDENTIAL_ENVS = ("GOOGLE_API_KEY", "GEMINI_API_KEY")


def _env_is_set(key: str) -> bool:
    return bool(os.environ.get(key, "").strip())


def active_env_managed_inputs(config: Config) -> list[str]:
    """返回登录会话自启项会丢失的、当前生效的环境变量键。"""
    managed: set[str] = set()
    for key in os.environ:
        if key.startswith("OPENBILICLAW_") and key != _PROJECT_ROOT_ENV and _env_is_set(key):
            managed.add(key)

    for key in _PROVIDER_CREDENTIAL_ENVS:
        if _env_is_set(key):
            managed.add(key)

    douyin_cookie_env = str(config.sources.douyin.cookie_env).strip()
    if douyin_cookie_env and _env_is_set(douyin_cookie_env):
        managed.add(douyin_cookie_env)

    return sorted(managed)


def autostart_shadowed(intended: bool) -> bool:
    """返回生效配置是否与刚写入的意图不一致。"""
    return load_config().autostart.enabled != intended

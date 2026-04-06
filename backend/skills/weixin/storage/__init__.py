"""
状态持久化模块
提供游标、context_token等状态的存储与读取
"""

from backend.skills.weixin.storage.state import (
    StateManager,
    load_get_updates_buf,
    save_get_updates_buf,
    get_context_token,
    set_context_token,
)

__all__ = [
    "StateManager",
    "load_get_updates_buf",
    "save_get_updates_buf",
    "get_context_token",
    "set_context_token",
]

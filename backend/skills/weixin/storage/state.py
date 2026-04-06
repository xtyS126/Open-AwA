"""
状态持久化模块
提供游标、context_token等状态的存储与读取
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict

from loguru import logger

from backend.skills.weixin.config import SESSION_PAUSE_DURATION_SECONDS, SESSION_EXPIRED_ERRCODE
from backend.skills.weixin.utils.helpers import (
    sanitize_account_id,
    read_json_file,
    write_json_file,
)

_SESSION_PAUSE_UNTIL: Dict[str, float] = {}


class StateManager:
    """
    状态管理器类
    管理微信适配器的状态持久化
    
    属性:
        state_root: 状态文件根目录
    """
    
    def __init__(self, state_root: str):
        """
        初始化状态管理器
        
        参数:
            state_root: 状态文件根目录
        """
        self.state_root = state_root
        self._accounts_state_dir: Optional[str] = None

    @property
    def accounts_state_dir(self) -> str:
        """
        获取账号状态目录路径，如果不存在则创建
        
        返回:
            账号状态目录的绝对路径
        """
        if self._accounts_state_dir is None:
            path = os.path.join(self.state_root, "accounts")
            os.makedirs(path, exist_ok=True)
            self._accounts_state_dir = path
        return self._accounts_state_dir

    def sync_buf_file_path(self, account_id: str) -> str:
        """
        获取同步游标文件路径
        
        参数:
            account_id: 账号ID
            
        返回:
            同步游标文件的绝对路径
        """
        safe_account_id = sanitize_account_id(account_id)
        return os.path.join(self.accounts_state_dir, f"{safe_account_id}.sync.json")

    def context_tokens_file_path(self, account_id: str) -> str:
        """
        获取上下文令牌文件路径
        
        参数:
            account_id: 账号ID
            
        返回:
            上下文令牌文件的绝对路径
        """
        safe_account_id = sanitize_account_id(account_id)
        return os.path.join(self.accounts_state_dir, f"{safe_account_id}.context-tokens.json")

    def load_get_updates_buf(self, account_id: str) -> str:
        """
        加载getUpdates游标
        
        参数:
            account_id: 账号ID
            
        返回:
            游标字符串，如果不存在则返回空字符串
        """
        data = read_json_file(self.sync_buf_file_path(account_id))
        value = data.get("get_updates_buf")
        return str(value).strip() if isinstance(value, str) else ""

    def save_get_updates_buf(self, account_id: str, get_updates_buf: str) -> None:
        """
        保存getUpdates游标
        
        参数:
            account_id: 账号ID
            get_updates_buf: 游标字符串
        """
        write_json_file(self.sync_buf_file_path(account_id), {"get_updates_buf": get_updates_buf})

    def get_context_token(self, account_id: str, user_id: str) -> str:
        """
        获取上下文令牌
        
        参数:
            account_id: 账号ID
            user_id: 用户ID
            
        返回:
            上下文令牌字符串，如果不存在则返回空字符串
        """
        data = read_json_file(self.context_tokens_file_path(account_id))
        value = data.get(user_id)
        return str(value).strip() if isinstance(value, str) else ""

    def set_context_token(self, account_id: str, user_id: str, token: str) -> None:
        """
        设置上下文令牌
        
        参数:
            account_id: 账号ID
            user_id: 用户ID
            token: 上下文令牌
        """
        file_path = self.context_tokens_file_path(account_id)
        data = read_json_file(file_path)
        data[user_id] = token
        write_json_file(file_path, data)

    def pause_session(self, account_id: str) -> None:
        """
        暂停会话
        
        参数:
            account_id: 账号ID
        """
        _SESSION_PAUSE_UNTIL[account_id] = time.time() + SESSION_PAUSE_DURATION_SECONDS

    def is_session_paused(self, account_id: str) -> bool:
        """
        检查会话是否暂停
        
        参数:
            account_id: 账号ID
            
        返回:
            如果会话暂停则返回True，否则返回False
        """
        if not account_id:
            return False
        until = _SESSION_PAUSE_UNTIL.get(account_id)
        if until is None:
            return False
        if until <= time.time():
            _SESSION_PAUSE_UNTIL.pop(account_id, None)
            return False
        return True

    def remaining_pause_seconds(self, account_id: str) -> int:
        """
        获取剩余暂停时间
        
        参数:
            account_id: 账号ID
            
        返回:
            剩余暂停秒数，如果未暂停则返回0
        """
        if not self.is_session_paused(account_id):
            return 0
        return max(0, int(_SESSION_PAUSE_UNTIL.get(account_id, 0) - time.time()))


def load_get_updates_buf(state_root: str, account_id: str) -> str:
    """
    加载getUpdates游标的便捷函数
    
    参数:
        state_root: 状态文件根目录
        account_id: 账号ID
        
    返回:
        游标字符串
    """
    manager = StateManager(state_root)
    return manager.load_get_updates_buf(account_id)


def save_get_updates_buf(state_root: str, account_id: str, get_updates_buf: str) -> None:
    """
    保存getUpdates游标的便捷函数
    
    参数:
        state_root: 状态文件根目录
        account_id: 账号ID
        get_updates_buf: 游标字符串
    """
    manager = StateManager(state_root)
    manager.save_get_updates_buf(account_id, get_updates_buf)


def get_context_token(state_root: str, account_id: str, user_id: str) -> str:
    """
    获取上下文令牌的便捷函数
    
    参数:
        state_root: 状态文件根目录
        account_id: 账号ID
        user_id: 用户ID
        
    返回:
        上下文令牌字符串
    """
    manager = StateManager(state_root)
    return manager.get_context_token(account_id, user_id)


def set_context_token(state_root: str, account_id: str, user_id: str, token: str) -> None:
    """
    设置上下文令牌的便捷函数
    
    参数:
        state_root: 状态文件根目录
        account_id: 账号ID
        user_id: 用户ID
        token: 上下文令牌
    """
    manager = StateManager(state_root)
    manager.set_context_token(account_id, user_id, token)

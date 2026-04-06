"""
消息处理主流程模块
提供消息轮询和处理的核心逻辑
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from loguru import logger

from skills.weixin.config import WeixinRuntimeConfig, SESSION_EXPIRED_ERRCODE
from skills.weixin.errors import WeixinAdapterError
from skills.weixin.api.client import api_post
from skills.weixin.messaging.inbound import (
    parse_messages_from_response,
    extract_context_tokens,
)
from skills.weixin.storage.state import StateManager
from skills.weixin.utils.helpers import normalize_binding_status


async def poll_updates(
    config: WeixinRuntimeConfig,
    state_manager: StateManager,
    cursor: str = ""
) -> Dict[str, Any]:
    """
    轮询获取新消息
    
    参数:
        config: 运行时配置
        state_manager: 状态管理器
        cursor: 游标字符串，可选
        
    返回:
        包含请求、响应和状态信息的字典
    """
    persisted_buf = state_manager.load_get_updates_buf(config.account_id)
    get_updates_buf = cursor or persisted_buf or ""
    request_body = {"get_updates_buf": get_updates_buf}
    
    response = await api_post(
        config=config,
        endpoint="ilink/bot/getupdates",
        body=request_body,
        timeout_seconds=38
    )
    
    errcode = response.get("errcode")
    ret = response.get("ret")
    if errcode == SESSION_EXPIRED_ERRCODE or ret == SESSION_EXPIRED_ERRCODE:
        state_manager.pause_session(config.account_id)
    
    next_buf = str(response.get("get_updates_buf") or "").strip()
    if next_buf:
        state_manager.save_get_updates_buf(config.account_id, next_buf)
    
    context_tokens = extract_context_tokens(response)
    stored_context_tokens = 0
    for user_id, token in context_tokens.items():
        state_manager.set_context_token(config.account_id, user_id, token)
        stored_context_tokens += 1
    
    return {
        "request": request_body,
        "response": response,
        "cursor": next_buf,
        "state": {
            "used_get_updates_buf": get_updates_buf,
            "saved_get_updates_buf": next_buf,
            "stored_context_token_count": stored_context_tokens,
        }
    }


async def process_message(
    config: WeixinRuntimeConfig,
    state_manager: StateManager,
    payload: Dict[str, Any]
) -> Dict[str, Any]:
    """
    处理消息轮询请求
    
    参数:
        config: 运行时配置
        state_manager: 状态管理器
        payload: 请求参数
        
    返回:
        处理结果字典
    """
    incoming_buf = str(
        payload.get("get_updates_buf")
        or payload.get("getUpdatesBuf")
        or payload.get("cursor")
        or ""
    ).strip()
    
    return await poll_updates(config, state_manager, incoming_buf)


def check_session_active(state_manager: StateManager, account_id: str) -> None:
    """
    检查会话是否活跃
    
    参数:
        state_manager: 状态管理器
        account_id: 账号ID
        
    抛出:
        WeixinAdapterError: 当会话暂停时
    """
    if not state_manager.is_session_paused(account_id):
        return
    
    remaining_seconds = state_manager.remaining_pause_seconds(account_id)
    raise WeixinAdapterError.session_paused(account_id, remaining_seconds)


def build_success_result(
    action: str,
    started: float,
    config: WeixinRuntimeConfig,
    data: Dict[str, Any],
    state_manager: StateManager
) -> Dict[str, Any]:
    """
    构建成功结果
    
    参数:
        action: 操作名称
        started: 开始时间戳
        config: 运行时配置
        data: 结果数据
        state_manager: 状态管理器
        
    返回:
        成功结果字典
    """
    return {
        "success": True,
        "adapter": "weixin",
        "action": action,
        "error": None,
        "outputs": {
            "adapter": "weixin",
            "action": action,
            "data": data,
            "meta": {
                "duration_seconds": round(time.time() - started, 6),
                "account_id": config.account_id,
                "base_url": config.base_url,
                "user_id": config.user_id,
                "binding_status": config.binding_status,
                "binding_ready": normalize_binding_status(config.binding_status, config.user_id) == "bound"
            }
        }
    }


def build_error_result(
    action: str,
    started: float,
    config: WeixinRuntimeConfig,
    error: WeixinAdapterError
) -> Dict[str, Any]:
    """
    构建错误结果
    
    参数:
        action: 操作名称
        started: 开始时间戳
        config: 运行时配置
        error: 错误实例
        
    返回:
        错误结果字典
    """
    return {
        "success": False,
        "adapter": "weixin",
        "action": action,
        "error": error.to_dict(),
        "outputs": {
            "adapter": "weixin",
            "action": action,
            "data": {},
            "meta": {
                "duration_seconds": round(time.time() - started, 6),
                "account_id": config.account_id,
                "base_url": config.base_url,
                "user_id": config.user_id,
                "binding_status": config.binding_status,
                "binding_ready": normalize_binding_status(config.binding_status, config.user_id) == "bound"
            }
        }
    }

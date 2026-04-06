"""
出站消息发送模块
提供发送消息到微信的功能
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from skills.weixin.config import WeixinRuntimeConfig
from skills.weixin.errors import WeixinAdapterError
from skills.weixin.api.client import api_post


def build_text_message_request(
    to_user_id: str,
    text: str,
    context_token: str,
    client_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    构建文本消息请求体
    
    参数:
        to_user_id: 接收者用户ID
        text: 文本内容
        context_token: 上下文令牌
        client_id: 客户端ID，可选
        
    返回:
        请求体字典
    """
    if client_id is None:
        client_id = f"ilink-{uuid.uuid4().hex[:8]}"
    
    return {
        "msg": {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": client_id,
            "message_type": 2,
            "message_state": 2,
            "context_token": context_token,
            "item_list": [
                {
                    "type": 1,
                    "text_item": {"text": text}
                }
            ]
        }
    }


async def send_text_message(
    config: WeixinRuntimeConfig,
    to_user_id: str,
    text: str,
    context_token: str,
    client_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    发送文本消息
    
    参数:
        config: 运行时配置
        to_user_id: 接收者用户ID
        text: 文本内容
        context_token: 上下文令牌
        client_id: 客户端ID，可选
        
    返回:
        包含请求和响应信息的字典
        
    抛出:
        WeixinAdapterError: 当发送失败时
    """
    if not to_user_id:
        raise WeixinAdapterError.input_missing_fields(["to_user_id"])
    if not text:
        raise WeixinAdapterError.input_missing_fields(["text"])
    if not context_token:
        raise WeixinAdapterError.input_missing_fields(["context_token"])
    
    if client_id is None:
        client_id = f"ilink-{uuid.uuid4().hex[:8]}"
    
    request_body = build_text_message_request(to_user_id, text, context_token, client_id)
    response = await api_post(config=config, endpoint="ilink/bot/sendmessage", body=request_body)
    
    return {
        "request": {
            "to_user_id": to_user_id,
            "client_id": client_id,
            "context_token": context_token,
            "text": text
        },
        "response": response,
        "state": {
            "context_token_source": "provided"
        }
    }


async def send_message_with_cached_token(
    config: WeixinRuntimeConfig,
    to_user_id: str,
    text: str,
    context_token: str,
    client_id: Optional[str] = None,
    token_from_cache: bool = False
) -> Dict[str, Any]:
    """
    发送文本消息（支持缓存令牌标记）
    
    参数:
        config: 运行时配置
        to_user_id: 接收者用户ID
        text: 文本内容
        context_token: 上下文令牌
        client_id: 客户端ID，可选
        token_from_cache: 令牌是否来自缓存
        
    返回:
        包含请求和响应信息的字典
    """
    result = await send_text_message(config, to_user_id, text, context_token, client_id)
    result["state"]["context_token_source"] = "cache" if token_from_cache else "payload"
    return result


def validate_send_message_params(
    to_user_id: Optional[str],
    text: Optional[str],
    context_token: Optional[str]
) -> None:
    """
    验证发送消息参数
    
    参数:
        to_user_id: 接收者用户ID
        text: 文本内容
        context_token: 上下文令牌
        
    抛出:
        WeixinAdapterError: 当参数缺失时
    """
    missing: list = []
    if not to_user_id or not str(to_user_id).strip():
        missing.append("to_user_id")
    if not text or not str(text).strip():
        missing.append("text")
    if not context_token or not str(context_token).strip():
        missing.append("context_token")
    
    if missing:
        raise WeixinAdapterError.input_missing_fields(missing)

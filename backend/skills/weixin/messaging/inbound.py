"""
入站消息解析模块
提供从微信API响应中解析消息的功能
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from dataclasses import dataclass


@dataclass
class InboundMessage:
    """
    入站消息数据类
    封装从微信接收的消息信息
    
    属性:
        seq: 消息序列号
        message_id: 消息唯一ID
        from_user_id: 发送者ID
        to_user_id: 接收者ID
        create_time_ms: 创建时间戳（毫秒）
        session_id: 会话ID
        message_type: 消息类型（1=USER, 2=BOT）
        message_state: 消息状态（0=NEW, 1=GENERATING, 2=FINISH）
        context_token: 会话上下文令牌
        text: 消息文本内容
        raw: 原始消息字典
    """
    seq: int = 0
    message_id: int = 0
    from_user_id: str = ""
    to_user_id: str = ""
    create_time_ms: int = 0
    session_id: str = ""
    message_type: int = 1
    message_state: int = 0
    context_token: str = ""
    text: str = ""
    raw: Dict[str, Any] = None

    def __post_init__(self):
        if self.raw is None:
            self.raw = {}


def parse_inbound_message(msg_data: Dict[str, Any]) -> InboundMessage:
    """
    解析单条入站消息
    
    参数:
        msg_data: 原始消息字典
        
    返回:
        InboundMessage实例
    """
    seq = int(msg_data.get("seq") or 0)
    message_id = int(msg_data.get("message_id") or 0)
    from_user_id = str(msg_data.get("from_user_id") or "").strip()
    to_user_id = str(msg_data.get("to_user_id") or "").strip()
    create_time_ms = int(msg_data.get("create_time_ms") or 0)
    session_id = str(msg_data.get("session_id") or "").strip()
    message_type = int(msg_data.get("message_type") or 1)
    message_state = int(msg_data.get("message_state") or 0)
    context_token = str(msg_data.get("context_token") or "").strip()
    
    text = extract_text_from_item_list(msg_data.get("item_list"))
    
    return InboundMessage(
        seq=seq,
        message_id=message_id,
        from_user_id=from_user_id,
        to_user_id=to_user_id,
        create_time_ms=create_time_ms,
        session_id=session_id,
        message_type=message_type,
        message_state=message_state,
        context_token=context_token,
        text=text,
        raw=msg_data,
    )


def extract_text_from_item_list(item_list: Optional[List[Dict[str, Any]]]) -> str:
    """
    从消息项列表中提取文本内容
    
    参数:
        item_list: 消息项列表
        
    返回:
        提取的文本内容
    """
    if not isinstance(item_list, list):
        return ""
    
    for item in item_list:
        if not isinstance(item, dict):
            continue
        
        item_type = item.get("type")
        
        if item_type == 1:
            text_item = item.get("text_item")
            if isinstance(text_item, dict):
                text = text_item.get("text")
                if isinstance(text, str):
                    return text
        
        if item_type == 3:
            voice_item = item.get("voice_item")
            if isinstance(voice_item, dict):
                text = voice_item.get("text")
                if isinstance(text, str) and text:
                    return text
    
    return ""


def parse_messages_from_response(response: Dict[str, Any]) -> List[InboundMessage]:
    """
    从API响应中解析所有消息
    
    参数:
        response: API响应字典
        
    返回:
        InboundMessage列表
    """
    messages: List[InboundMessage] = []
    msgs = response.get("msgs")
    
    if not isinstance(msgs, list):
        return messages
    
    for msg_data in msgs:
        if not isinstance(msg_data, dict):
            continue
        messages.append(parse_inbound_message(msg_data))
    
    return messages


def extract_context_tokens(response: Dict[str, Any]) -> Dict[str, str]:
    """
    从API响应中提取所有上下文令牌
    
    参数:
        response: API响应字典
        
    返回:
        用户ID到上下文令牌的映射字典
    """
    tokens: Dict[str, str] = {}
    msgs = response.get("msgs")
    
    if not isinstance(msgs, list):
        return tokens
    
    for item in msgs:
        if not isinstance(item, dict):
            continue
        from_user_id = str(item.get("from_user_id") or "").strip()
        context_token = str(item.get("context_token") or "").strip()
        if from_user_id and context_token:
            tokens[from_user_id] = context_token
    
    return tokens

"""
消息处理模块
提供入站消息解析、出站消息发送、消息处理主流程
"""

from backend.skills.weixin.messaging.inbound import parse_inbound_message
from backend.skills.weixin.messaging.outbound import send_text_message
from backend.skills.weixin.messaging.process import process_message

__all__ = [
    "parse_inbound_message",
    "send_text_message",
    "process_message",
]

"""
测试工具库模块，提供 LLM API 消息格式的测试数据工厂。

与 tests/factories/ 区别：
- tests/factories/ 面向数据库模型实例（含 session_id、timestamp 等字段）
- tests/harness/ 面向 LLM API 消息格式（role/content/tool_calls/tool_call_id）
"""

from .message_factory import (
    create_test_user_message,
    create_test_assistant_message,
    create_test_tool_use_message,
    create_test_conversation,
)

__all__ = [
    "create_test_user_message",
    "create_test_assistant_message",
    "create_test_tool_use_message",
    "create_test_conversation",
]

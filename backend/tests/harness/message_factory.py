"""
LLM API 消息测试数据工厂。

提供纯函数生成 OpenAI/Anthropic 风格的消息字典，用于测试用例的标准化数据构造。
所有工厂函数均为纯函数，每次调用返回全新的字典对象，避免测试间数据污染。

消息格式说明：
- user 消息: {"role": "user", "content": str, "id": str}
- assistant 消息: {"role": "assistant", "content": str, "tool_calls": [...], "id": str}
- tool 消息: {"role": "tool", "tool_call_id": str, "name": str, "content": str, "id": str}
"""

import uuid
from typing import Any, Dict, List, Optional


def create_test_user_message(
    content: str = "Hello",
    message_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    创建 user 角色消息字典。

    参数：
        content: 消息文本内容，默认 "Hello"
        message_id: 消息 ID，未指定时自动生成 UUID

    返回：
        {"role": "user", "content": content, "id": message_id or uuid4()}
    """
    return {
        "role": "user",
        "content": content,
        "id": message_id or str(uuid.uuid4()),
    }


def create_test_assistant_message(
    content: str = "Hi there",
    message_id: Optional[str] = None,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    创建 assistant 角色消息字典，支持携带 tool_calls。

    参数：
        content: 消息文本内容，默认 "Hi there"
        message_id: 消息 ID，未指定时自动生成 UUID
        tool_calls: 工具调用列表，None 表示无工具调用。
                    格式遵循 OpenAI tool_calls 规范：
                    [{"id": "call_xxx", "type": "function",
                      "function": {"name": "tool_name", "arguments": "{...}"}}]

    返回：
        当 tool_calls 为 None 时：
            {"role": "assistant", "content": content, "id": ...}
        当 tool_calls 不为 None 时：
            {"role": "assistant", "content": content, "tool_calls": tool_calls, "id": ...}
    """
    message: Dict[str, Any] = {
        "role": "assistant",
        "content": content,
        "id": message_id or str(uuid.uuid4()),
    }
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return message


def create_test_tool_use_message(
    tool_call_id: str = "call_123",
    tool_name: str = "read_file",
    result: str = "file content",
    message_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    创建 tool 角色消息字典，表示工具执行结果。

    参数：
        tool_call_id: 对应 assistant 消息中 tool_calls 的 id，默认 "call_123"
        tool_name: 工具名称，默认 "read_file"
        result: 工具执行结果文本，默认 "file content"
        message_id: 消息 ID，未指定时自动生成 UUID

    返回：
        {"role": "tool", "tool_call_id": tool_call_id,
         "name": tool_name, "content": result, "id": ...}
    """
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "name": tool_name,
        "content": result,
        "id": message_id or str(uuid.uuid4()),
    }


def create_test_conversation(
    messages: Optional[List[Dict[str, Any]]] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    构造完整的多轮测试会话。

    当 messages 为 None 时，生成一个默认的多轮对话场景：
    1. user: "Hello"
    2. assistant: "Hi there"
    3. user: "Read file /tmp/test.txt"
    4. assistant: 发起 read_file 工具调用（tool_call_id="call_123"）
    5. tool: 返回 "file content"（对应 call_123）
    6. assistant: "The file contains..."

    参数：
        messages: 自定义消息列表，None 时使用默认多轮对话
        session_id: 会话 ID，未指定时自动生成 UUID

    返回：
        {"session_id": session_id or uuid4(), "messages": messages}
    """
    if messages is None:
        messages = _build_default_conversation_messages()
    return {
        "session_id": session_id or str(uuid.uuid4()),
        "messages": messages,
    }


def _build_default_conversation_messages() -> List[Dict[str, Any]]:
    """
    构造默认多轮对话消息列表。

    包含一轮完整的工具调用闭环：
    user 提问 -> assistant 回复 -> user 请求读文件 ->
    assistant 发起工具调用 -> tool 返回结果 -> assistant 总结回复。

    返回：
        包含 6 条消息的列表
    """
    # 工具调用 id，需与 tool 结果消息的 tool_call_id 一致
    tool_call_id = "call_123"
    tool_name = "read_file"
    return [
        # 1. 用户打招呼
        create_test_user_message("Hello"),
        # 2. 助手回复
        create_test_assistant_message("Hi there"),
        # 3. 用户请求读取文件
        create_test_user_message("Read file /tmp/test.txt"),
        # 4. 助手发起 read_file 工具调用
        create_test_assistant_message(
            content="",
            tool_calls=[
                {
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": '{"path": "/tmp/test.txt"}',
                    },
                }
            ],
        ),
        # 5. 工具返回结果（tool_call_id 需与第 4 步一致）
        create_test_tool_use_message(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            result="file content",
        ),
        # 6. 助手基于工具结果给出总结
        create_test_assistant_message("The file contains..."),
    ]

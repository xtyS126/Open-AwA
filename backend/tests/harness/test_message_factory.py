"""
message_factory 工厂函数单元测试。

验证各工厂函数的返回结构、默认值、自定义参数及纯函数特性。
"""

from __future__ import annotations

import uuid

from .message_factory import (
    create_test_assistant_message,
    create_test_conversation,
    create_test_tool_use_message,
    create_test_user_message,
)


# ==================== user 消息测试 ====================


class TestCreateTestUserMessage:
    """create_test_user_message 工厂函数测试。"""

    def test_create_test_user_message(self) -> None:
        """验证 user 消息的默认结构。"""
        msg = create_test_user_message()

        assert msg["role"] == "user"
        assert msg["content"] == "Hello"
        assert "id" in msg
        # id 应为合法 UUID 字符串
        uuid.UUID(msg["id"])

    def test_create_test_user_message_custom_content(self) -> None:
        """验证自定义 content 参数。"""
        msg = create_test_user_message(content="自定义内容")

        assert msg["content"] == "自定义内容"

    def test_create_test_user_message_custom_id(self) -> None:
        """验证自定义 message_id 参数。"""
        msg = create_test_user_message(message_id="msg-001")

        assert msg["id"] == "msg-001"

    def test_create_test_user_message_returns_new_object(self) -> None:
        """验证纯函数特性：每次调用返回全新对象。"""
        msg1 = create_test_user_message()
        msg2 = create_test_user_message()

        assert msg1 is not msg2
        assert msg1["id"] != msg2["id"]


# ==================== assistant 消息测试 ====================


class TestCreateTestAssistantMessage:
    """create_test_assistant_message 工厂函数测试。"""

    def test_create_test_assistant_message(self) -> None:
        """验证 assistant 消息的默认结构（无 tool_calls）。"""
        msg = create_test_assistant_message()

        assert msg["role"] == "assistant"
        assert msg["content"] == "Hi there"
        assert "id" in msg
        # 无 tool_calls 时不包含该字段
        assert "tool_calls" not in msg
        uuid.UUID(msg["id"])

    def test_create_test_assistant_message_with_tool_calls(self) -> None:
        """验证带 tool_calls 的 assistant 消息结构。"""
        tool_calls = [
            {
                "id": "call_abc",
                "type": "function",
                "function": {
                    "name": "read_file",
                    "arguments": '{"path": "/tmp/test.txt"}',
                },
            }
        ]
        msg = create_test_assistant_message(
            content="", tool_calls=tool_calls
        )

        assert msg["role"] == "assistant"
        assert msg["content"] == ""
        assert msg["tool_calls"] == tool_calls
        assert "id" in msg

    def test_create_test_assistant_message_custom_id(self) -> None:
        """验证自定义 message_id 参数。"""
        msg = create_test_assistant_message(message_id="asst-001")

        assert msg["id"] == "asst-001"

    def test_create_test_assistant_message_returns_new_object(self) -> None:
        """验证纯函数特性：每次调用返回全新对象。"""
        msg1 = create_test_assistant_message()
        msg2 = create_test_assistant_message()

        assert msg1 is not msg2
        assert msg1["id"] != msg2["id"]


# ==================== tool 消息测试 ====================


class TestCreateTestToolUseMessage:
    """create_test_tool_use_message 工厂函数测试。"""

    def test_create_test_tool_use_message(self) -> None:
        """验证 tool 消息的默认结构。"""
        msg = create_test_tool_use_message()

        assert msg["role"] == "tool"
        assert msg["tool_call_id"] == "call_123"
        assert msg["name"] == "read_file"
        assert msg["content"] == "file content"
        assert "id" in msg
        uuid.UUID(msg["id"])

    def test_create_test_tool_use_message_custom_params(self) -> None:
        """验证自定义参数。"""
        msg = create_test_tool_use_message(
            tool_call_id="call_999",
            tool_name="web_search",
            result="搜索结果",
        )

        assert msg["tool_call_id"] == "call_999"
        assert msg["name"] == "web_search"
        assert msg["content"] == "搜索结果"

    def test_create_test_tool_use_message_custom_id(self) -> None:
        """验证自定义 message_id 参数。"""
        msg = create_test_tool_use_message(message_id="tool-001")

        assert msg["id"] == "tool-001"

    def test_create_test_tool_use_message_returns_new_object(self) -> None:
        """验证纯函数特性：每次调用返回全新对象。"""
        msg1 = create_test_tool_use_message()
        msg2 = create_test_tool_use_message()

        assert msg1 is not msg2
        assert msg1["id"] != msg2["id"]


# ==================== 会话构造测试 ====================


class TestCreateTestConversation:
    """create_test_conversation 工厂函数测试。"""

    def test_create_test_conversation_default(self) -> None:
        """验证默认多轮对话结构。"""
        conv = create_test_conversation()

        assert "session_id" in conv
        assert "messages" in conv
        uuid.UUID(conv["session_id"])

        messages = conv["messages"]
        # 默认 6 条消息
        assert len(messages) == 6
        # 验证消息角色序列
        roles = [m["role"] for m in messages]
        assert roles == [
            "user",
            "assistant",
            "user",
            "assistant",
            "tool",
            "assistant",
        ]
        # 验证关键内容
        assert messages[0]["content"] == "Hello"
        assert messages[1]["content"] == "Hi there"
        assert messages[2]["content"] == "Read file /tmp/test.txt"
        # 第 4 条 assistant 含 tool_calls
        assert "tool_calls" in messages[3]
        assert messages[3]["tool_calls"][0]["function"]["name"] == "read_file"
        # 第 5 条 tool 结果与第 4 条 tool_call_id 一致
        assert messages[4]["tool_call_id"] == messages[3]["tool_calls"][0]["id"]
        assert messages[4]["content"] == "file content"
        # 第 6 条 assistant 总结
        assert messages[5]["content"] == "The file contains..."

    def test_create_test_conversation_custom_messages(self) -> None:
        """验证自定义消息列表。"""
        custom_messages = [
            create_test_user_message("自定义问题"),
            create_test_assistant_message("自定义回复"),
        ]
        conv = create_test_conversation(messages=custom_messages)

        assert conv["messages"] is custom_messages
        assert len(conv["messages"]) == 2
        assert conv["messages"][0]["content"] == "自定义问题"

    def test_create_test_conversation_with_session_id(self) -> None:
        """验证自定义 session_id 参数。"""
        conv = create_test_conversation(session_id="session-abc-123")

        assert conv["session_id"] == "session-abc-123"

    def test_create_test_conversation_returns_new_object(self) -> None:
        """验证纯函数特性：每次调用返回全新对象和不同 session_id。"""
        conv1 = create_test_conversation()
        conv2 = create_test_conversation()

        assert conv1 is not conv2
        assert conv1["session_id"] != conv2["session_id"]
        # 默认消息列表也应是不同对象
        assert conv1["messages"] is not conv2["messages"]

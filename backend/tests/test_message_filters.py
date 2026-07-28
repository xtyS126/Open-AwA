"""
Resume 消息清洗过滤器单元测试。

覆盖三道过滤器的正常路径与异常路径：
1. filter_unresolved_tool_uses: 移除未完成的 tool_use 块
2. filter_orphaned_thinking_only_messages: 移除只含 thinking 的孤立消息
3. filter_whitespace_only_assistant_messages: 移除空白助手消息
4. apply_resume_filters: 验证三道过滤器依次应用
"""

from __future__ import annotations

from core.task_runtime.message_filters import (
    apply_resume_filters,
    filter_orphaned_thinking_only_messages,
    filter_unresolved_tool_uses,
    filter_whitespace_only_assistant_messages,
)
from harness.message_factory import (
    create_test_assistant_message,
    create_test_tool_use_message,
    create_test_user_message,
)


# -- filter_unresolved_tool_uses 测试 ---------------------------------


class TestFilterUnresolvedToolUses:
    """移除未完成 tool_use 块的测试。"""

    def test_filter_unresolved_tool_uses_removes_orphan(self) -> None:
        """assistant 含 tool_use 但无对应 tool 结果，应移除该 tool_use 项。"""
        messages = [
            create_test_user_message("请读取文件"),
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "让我读取文件"},
                    {
                        "type": "tool_use",
                        "id": "call_orphan",
                        "name": "read_file",
                        "input": {"path": "/tmp/test"},
                    },
                ],
            },
        ]

        result = filter_unresolved_tool_uses(messages)

        # user 消息保留
        assert len(result) == 2
        assert result[0]["role"] == "user"
        # assistant 消息保留，但 tool_use 项被移除
        assert result[1]["role"] == "assistant"
        assert len(result[1]["content"]) == 1
        assert result[1]["content"][0]["type"] == "text"

    def test_filter_unresolved_tool_uses_keeps_resolved(self) -> None:
        """assistant 含 tool_use 且有对应 tool 结果，应保留 tool_use 项。"""
        messages = [
            create_test_user_message("请读取文件"),
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "让我读取文件"},
                    {
                        "type": "tool_use",
                        "id": "call_123",
                        "name": "read_file",
                        "input": {"path": "/tmp/test"},
                    },
                ],
            },
            create_test_tool_use_message(
                tool_call_id="call_123", tool_name="read_file", result="file content"
            ),
        ]

        result = filter_unresolved_tool_uses(messages)

        # 三条消息全部保留
        assert len(result) == 3
        # assistant 消息的 tool_use 项保留
        assistant_msg = result[1]
        assert len(assistant_msg["content"]) == 2
        assert assistant_msg["content"][1]["type"] == "tool_use"
        assert assistant_msg["content"][1]["id"] == "call_123"

    def test_filter_unresolved_tool_uses_removes_empty_assistant(self) -> None:
        """移除 tool_use 后 content 为空，应移除整个 assistant 消息。"""
        messages = [
            create_test_user_message("请读取文件"),
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call_orphan",
                        "name": "read_file",
                        "input": {"path": "/tmp/test"},
                    },
                ],
            },
        ]

        result = filter_unresolved_tool_uses(messages)

        # 仅保留 user 消息，assistant 消息被整体移除
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_filter_unresolved_tool_uses_does_not_mutate_original(self) -> None:
        """过滤器应为纯函数，不修改原列表。"""
        original_messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call_orphan",
                        "name": "read_file",
                        "input": {"path": "/tmp/test"},
                    },
                ],
            },
        ]
        original_snapshot = [
            {
                "role": msg["role"],
                "content": list(msg["content"]),
            }
            for msg in original_messages
        ]

        filter_unresolved_tool_uses(original_messages)

        # 原列表内容不变
        assert original_messages[0]["role"] == original_snapshot[0]["role"]
        assert original_messages[0]["content"] == original_snapshot[0]["content"]

    def test_filter_unresolved_tool_uses_keeps_non_assistant_messages(self) -> None:
        """非 assistant 消息（user/tool/system）应原样保留。"""
        messages = [
            create_test_user_message("Hello"),
            {"role": "system", "content": "system prompt"},
            create_test_tool_use_message(tool_call_id="call_999", result="result"),
        ]

        result = filter_unresolved_tool_uses(messages)

        assert len(result) == 3
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "system"
        assert result[2]["role"] == "tool"

    def test_filter_unresolved_tool_uses_keeps_string_content(self) -> None:
        """assistant content 为字符串时应原样保留。"""
        messages = [
            create_test_assistant_message("纯文本回复"),
        ]

        result = filter_unresolved_tool_uses(messages)

        assert len(result) == 1
        assert result[0]["content"] == "纯文本回复"


# -- filter_orphaned_thinking_only_messages 测试 ---------------------


class TestFilterOrphanedThinkingOnly:
    """移除只含 thinking 的孤立 assistant 消息测试。"""

    def test_filter_orphaned_thinking_only_removes(self) -> None:
        """assistant 只有 thinking 块，应移除。"""
        messages = [
            create_test_user_message("你好"),
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "我应该回复用户"},
                ],
            },
        ]

        result = filter_orphaned_thinking_only_messages(messages)

        # 仅保留 user 消息
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_filter_orphaned_thinking_only_keeps_mixed(self) -> None:
        """assistant 含 thinking + text，应保留。"""
        messages = [
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "我应该回复用户"},
                    {"type": "text", "text": "你好"},
                ],
            },
        ]

        result = filter_orphaned_thinking_only_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert len(result[0]["content"]) == 2

    def test_filter_orphaned_thinking_only_removes_empty_string(self) -> None:
        """assistant content 为空字符串，应移除。"""
        messages = [
            create_test_assistant_message(""),
        ]

        result = filter_orphaned_thinking_only_messages(messages)

        assert len(result) == 0

    def test_filter_orphaned_thinking_only_keeps_non_empty_string(self) -> None:
        """assistant content 为非空字符串，应保留。"""
        messages = [
            create_test_assistant_message("实际回复"),
        ]

        result = filter_orphaned_thinking_only_messages(messages)

        assert len(result) == 1
        assert result[0]["content"] == "实际回复"

    def test_filter_orphaned_thinking_only_keeps_non_assistant(self) -> None:
        """非 assistant 消息应原样保留。"""
        messages = [
            create_test_user_message("你好"),
            {"role": "system", "content": "system"},
        ]

        result = filter_orphaned_thinking_only_messages(messages)

        assert len(result) == 2


# -- filter_whitespace_only_assistant_messages 测试 ------------------


class TestFilterWhitespaceOnlyAssistant:
    """移除空白 assistant 消息测试。"""

    def test_filter_whitespace_only_removes_empty_string(self) -> None:
        """assistant content 为空字符串，应移除。"""
        messages = [
            create_test_user_message("你好"),
            create_test_assistant_message(""),
        ]

        result = filter_whitespace_only_assistant_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_filter_whitespace_only_removes_whitespace_only(self) -> None:
        """assistant content 为纯空白字符串，应移除。"""
        messages = [
            create_test_assistant_message("   "),
        ]

        result = filter_whitespace_only_assistant_messages(messages)

        assert len(result) == 0

    def test_filter_whitespace_only_keeps_non_empty(self) -> None:
        """assistant content 有实际内容，应保留。"""
        messages = [
            create_test_assistant_message("实际回复"),
        ]

        result = filter_whitespace_only_assistant_messages(messages)

        assert len(result) == 1
        assert result[0]["content"] == "实际回复"

    def test_filter_whitespace_only_removes_whitespace_text_list(self) -> None:
        """assistant content 为列表且所有 text 项都是空白，应移除。"""
        messages = [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "   "},
                    {"type": "text", "text": "\t\n"},
                ],
            },
        ]

        result = filter_whitespace_only_assistant_messages(messages)

        assert len(result) == 0

    def test_filter_whitespace_only_keeps_mixed_list_with_tool_use(self) -> None:
        """assistant content 含 tool_use 项，应保留（非空白）。"""
        messages = [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "   "},
                    {
                        "type": "tool_use",
                        "id": "call_1",
                        "name": "read_file",
                        "input": {},
                    },
                ],
            },
        ]

        result = filter_whitespace_only_assistant_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "assistant"

    def test_filter_whitespace_only_keeps_non_assistant(self) -> None:
        """非 assistant 消息（含空白 user 消息）应原样保留。"""
        messages = [
            {"role": "user", "content": "   "},
            {"role": "system", "content": ""},
        ]

        result = filter_whitespace_only_assistant_messages(messages)

        assert len(result) == 2


# -- apply_resume_filters 测试 ---------------------------------------


class TestApplyResumeFilters:
    """三道过滤器组合应用测试。"""

    def test_apply_resume_filters_chains_all_three(self) -> None:
        """验证便捷函数依次应用三道过滤器。"""
        messages = [
            create_test_user_message("请读取文件"),
            # 1. 未完成的 tool_use（应被 filter_unresolved_tool_uses 移除 tool_use 项）
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "让我读取"},
                    {
                        "type": "tool_use",
                        "id": "call_orphan",
                        "name": "read_file",
                        "input": {"path": "/tmp/test"},
                    },
                ],
            },
            # 2. 只含 thinking 的孤立消息（应被 filter_orphaned_thinking_only_messages 移除）
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "我在思考"},
                ],
            },
            # 3. 空白助手消息（应被 filter_whitespace_only_assistant_messages 移除）
            create_test_assistant_message("   "),
            # 4. 正常助手消息（应保留）
            create_test_assistant_message("这是实际回复"),
        ]

        result = apply_resume_filters(messages)

        # 应保留：user 消息 + 第一条 assistant（移除 tool_use 后只剩 text）+ 最后一条 assistant
        assert len(result) == 3
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert len(result[1]["content"]) == 1
        assert result[1]["content"][0]["type"] == "text"
        assert result[1]["content"][0]["text"] == "让我读取"
        assert result[2]["role"] == "assistant"
        assert result[2]["content"] == "这是实际回复"

    def test_apply_resume_filters_empty_input(self) -> None:
        """空列表输入应返回空列表。"""
        result = apply_resume_filters([])
        assert result == []

    def test_apply_resume_filters_all_clean(self) -> None:
        """全部消息均干净时应原样保留（结构等价）。"""
        messages = [
            create_test_user_message("你好"),
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "思考中"},
                    {"type": "text", "text": "你好"},
                ],
            },
        ]

        result = apply_resume_filters(messages)

        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert len(result[1]["content"]) == 2

    def test_apply_resume_filters_does_not_mutate_original(self) -> None:
        """便捷函数不应修改原列表。"""
        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call_orphan",
                        "name": "read_file",
                        "input": {},
                    },
                ],
            },
        ]
        original_len = len(messages)
        original_content_len = len(messages[0]["content"])

        apply_resume_filters(messages)

        assert len(messages) == original_len
        assert len(messages[0]["content"]) == original_content_len

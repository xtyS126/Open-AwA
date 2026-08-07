"""
CompactionManager 单元测试。
测试上下文压缩、Token 估算、摘要生成、断路器保护。
"""

import pytest

from core.compaction_manager import (
    COMPACTABLE_TOOLS,
    CompactBoundaryMessage,
    CompactionManager,
    CompactionConfig,
    PreservedSegment,
    TokenEstimate,
    _estimate_message_tokens,
    _estimate_messages_tokens,
    _estimate_text_tokens,
    _estimate_tools_tokens,
    _estimate_total_tokens,
    create_compact_boundary_message,
    MAX_CONSECUTIVE_FAILURES,
)
from harness.message_factory import (
    create_test_assistant_message,
    create_test_tool_use_message,
    create_test_user_message,
)


class TestTokenEstimation:
    """统一 Token 估算测试（基于 TokenBudget.estimate_tokens）"""

    def test_estimate_text_empty(self):
        """空文本估算"""
        assert _estimate_text_tokens("") == 0

    def test_estimate_text_english(self):
        """英文文本估算：约 4 字符/token"""
        text = "This is a test message for token estimation."
        tokens = _estimate_text_tokens(text)
        assert tokens > 0
        # 英文约 4 字符/token
        expected = int(len(text) / 4)
        assert tokens == expected

    def test_estimate_text_chinese(self):
        """中文文本估算：约 1.5 字符/token"""
        text = "这是一条用于测试token估算的中文消息"
        tokens = _estimate_text_tokens(text)
        assert tokens > 0
        # 中文字符约 1.5 字符/token
        chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
        expected = int(chinese_chars / 1.5 + (len(text) - chinese_chars) / 4)
        assert tokens == expected

    def test_estimate_message_string_content(self):
        """字符串内容消息估算"""
        msg = create_test_user_message("Hello, how are you?")
        tokens = _estimate_message_tokens(msg)
        assert tokens == _estimate_text_tokens("Hello, how are you?")

    def test_estimate_message_multimodal_content(self):
        """多模态内容消息估算"""
        msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": "Hello"},
                {"type": "text", "text": "World"},
            ],
        }
        tokens = _estimate_message_tokens(msg)
        assert tokens == _estimate_text_tokens("Hello") + _estimate_text_tokens("World")

    def test_estimate_messages_list(self):
        """消息列表估算"""
        messages = [
            create_test_user_message("Hello, how are you?"),
            create_test_assistant_message("I'm doing well, thank you!"),
        ]
        total = _estimate_messages_tokens(messages)
        assert total == sum(_estimate_message_tokens(m) for m in messages)
        assert total > 0

    def test_estimate_tools(self):
        """工具定义估算"""
        tools = [{"type": "function", "function": {"name": "read", "description": "Read a file"}}]
        tokens = _estimate_tools_tokens(tools)
        assert tokens > 0

    def test_estimate_total_returns_breakdown(self):
        """完整请求估算返回分项明细"""
        result = _estimate_total_tokens(
            system_prompt="You are a helpful assistant.",
            messages=[{"role": "user", "content": "Hello, how are you today?"}],
            tools=[{"type": "function", "function": {"name": "read", "description": "Read a file"}}],
        )
        assert isinstance(result, TokenEstimate)
        assert result.total > 0
        assert result.system_tokens > 0
        assert result.messages_tokens > 0
        assert result.tools_tokens > 0
        assert result.total == result.system_tokens + result.messages_tokens + result.tools_tokens


class TestCompactionManager:
    """压缩管理器测试"""

    @pytest.fixture
    def compaction(self):
        """创建 CompactionManager 实例"""
        return CompactionManager(
            model_context_window=100_000,
            config=CompactionConfig(
                auto=True,
                buffer_tokens=10_000,
                keep_tokens=1_000,
            ),
        )

    def test_should_compact_no_messages(self, compaction):
        """空消息列表不需要压缩"""
        assert compaction.should_compact() is False

    def test_should_compact_small_context(self, compaction):
        """小上下文不需要压缩"""
        messages = [create_test_user_message("Hello!")]
        assert compaction.should_compact(messages=messages) is False

    def test_should_compact_large_context(self, compaction):
        """大上下文需要压缩"""
        # 创建超过窗口限制的消息
        large_text = "A" * 400_000  # 约 100k tokens
        messages = [{"role": "user", "content": large_text}]
        assert compaction.should_compact(messages=messages) is True

    def test_should_compact_disabled(self, compaction):
        """禁用自动压缩"""
        compaction.config.auto = False
        large_text = "A" * 400_000
        messages = [{"role": "user", "content": large_text}]
        assert compaction.should_compact(messages=messages) is False

    def test_select_messages(self, compaction):
        """消息分离测试"""
        messages = [
            create_test_user_message("Message 1: " + "hello " * 200),   # 大头消息
            create_test_assistant_message("Response 1: " + "ok " * 50),
            create_test_user_message("Message 2: how are you?"),
        ]
        head, recent = compaction.select_messages(messages)
        # 至少保留最后一条消息
        assert len(recent) >= 1
        # head + recent = 总消息数
        assert len(head) + len(recent) == len(messages)

    def test_serialize_message_user(self, compaction):
        """用户消息序列化"""
        msg = create_test_user_message("Hello, world!")
        result = compaction._serialize_message(msg)
        assert "[用户]" in result
        assert "Hello, world!" in result

    def test_serialize_message_assistant(self, compaction):
        """助手消息序列化"""
        msg = create_test_assistant_message("I can help with that.")
        result = compaction._serialize_message(msg)
        assert "[助手]" in result
        assert "I can help with that." in result

    def test_serialize_message_tool(self, compaction):
        """工具消息序列化"""
        msg = {"role": "tool", "content": "File contents here", "name": "read"}
        result = compaction._serialize_message(msg)
        assert "read" in result

    def test_truncate_output(self, compaction):
        """输出截断测试"""
        short = "Short output"
        assert compaction._truncate_output(short) == short

        long = "X" * 5000
        truncated = compaction._truncate_output(long)
        assert len(truncated) <= compaction.config.tool_output_max_chars + 10  # 加缓冲区
        assert "[已截断]" in truncated

    def test_build_summary_prompt_no_previous(self, compaction):
        """无前次摘要的 prompt 构建"""
        head = [{"role": "user", "content": "Old conversation"}]
        prompt = compaction.build_summary_prompt(head)
        assert "创建新的锚定摘要" in prompt
        assert "目标" in prompt
        assert "Old conversation" in prompt

    def test_build_summary_prompt_with_previous(self, compaction):
        """有前次摘要的 prompt 构建"""
        head = [{"role": "user", "content": "New question"}]
        previous = "## 目标\n- 之前的目标"
        prompt = compaction.build_summary_prompt(head, previous)
        assert "更新锚定摘要" in prompt
        assert previous in prompt

    def test_parse_compaction_sections(self, compaction):
        """摘要段落解析"""
        summary = """## 目标
- 完成权限系统开发

## 进度
### 已完成
- PermissionManager 已实现
- 单元测试已通过

### 进行中
- 前端组件开发

### 阻塞
- (无)

## 关键决策
- 采用三层优先级模型
"""
        sections = compaction.parse_compaction_sections(summary)
        assert "权限系统开发" in sections["目标"]
        assert "PermissionManager" in sections["已完成"]
        assert "前端组件" in sections["进行中"]
        # (无) 应该被过滤
        assert sections["阻塞"] == ""


class TestCompactionConfig:
    """压缩配置测试"""

    def test_default_config(self):
        """默认配置"""
        config = CompactionConfig()
        assert config.auto is True
        assert config.buffer_tokens == 20_000
        assert config.keep_tokens == 8_000

    def test_custom_config(self):
        """自定义配置"""
        config = CompactionConfig(
            auto=False,
            buffer_tokens=5_000,
            keep_tokens=2_000,
        )
        assert config.auto is False
        assert config.buffer_tokens == 5_000
        assert config.keep_tokens == 2_000


class TestCircuitBreaker:
    """断路器保护测试"""

    @pytest.fixture
    def small_compaction(self):
        """创建小窗口 CompactionManager 用于触发压缩。
        summary_output_tokens 必须小于 model_context_window，
        否则 generate_summary 的 prompt 大小检查会始终失败。
        """
        return CompactionManager(
            model_context_window=5000,
            config=CompactionConfig(
                auto=True,
                buffer_tokens=500,
                keep_tokens=3500,
                summary_output_tokens=500,
            ),
        )

    @pytest.fixture
    def large_messages(self):
        """创建足够大的消息列表以触发压缩（总 token 超过可用窗口）。
        使用多条中等大小消息，确保 head_messages 不会过大导致 prompt 超限。
        每条消息 1000 字符约 250 tokens，20 条共约 5000 tokens。
        """
        msg_text = "A" * 1000  # 约 250 tokens
        messages = []
        for i in range(20):
            role = "user" if i % 2 == 0 else "assistant"
            messages.append({"role": role, "content": msg_text})
        return messages

    def test_max_consecutive_failures_constant(self):
        """MAX_CONSECUTIVE_FAILURES 常量值为 3"""
        assert MAX_CONSECUTIVE_FAILURES == 3

    def test_initial_failure_count_is_zero(self, small_compaction):
        """初始失败计数为 0"""
        assert small_compaction._consecutive_failures == 0

    async def test_compact_increments_failures_on_summary_failure(
        self, small_compaction, large_messages
    ):
        """摘要生成失败时计数递增"""
        call_count = 0

        async def failing_llm_call(prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("LLM 服务不可用")

        small_compaction.set_llm_call(failing_llm_call)
        result = await small_compaction.compact(messages=large_messages)

        assert result["compacted"] is False
        assert small_compaction._consecutive_failures == 1
        assert call_count == 1
        # 摘要失败必须通过 error 字段显式可见
        assert result.get("error") is not None

    async def test_circuit_breaker_triggers_after_max_failures(
        self, small_compaction, large_messages
    ):
        """连续失败达上限后，后续调用应直接跳过压缩（不调用 LLM），且返回显式错误状态"""
        call_count = 0

        async def failing_llm_call(prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("LLM 服务不可用")

        small_compaction.set_llm_call(failing_llm_call)

        # 前 MAX_CONSECUTIVE_FAILURES 次调用：每次都失败，计数递增
        for i in range(MAX_CONSECUTIVE_FAILURES):
            result = await small_compaction.compact(messages=large_messages)
            assert result["compacted"] is False
            assert small_compaction._consecutive_failures == i + 1
            # 每次失败都必须返回显式错误字段
            assert result.get("error") is not None

        # 断路器应已触发
        assert small_compaction._consecutive_failures >= MAX_CONSECUTIVE_FAILURES
        assert call_count == MAX_CONSECUTIVE_FAILURES

        # 第 4 次调用：断路器触发，应跳过压缩，不调用 LLM
        result = await small_compaction.compact(messages=large_messages)
        assert result["compacted"] is False
        assert result["messages"] == large_messages
        # LLM 调用次数仍为 3（第 4 次未调用 LLM）
        assert call_count == MAX_CONSECUTIVE_FAILURES
        # 断路器跳过必须返回显式错误字段，禁止静默继续
        assert result.get("error") is not None
        assert "断路器" in result["error"]

    async def test_circuit_breaker_resets_on_success(
        self, small_compaction, large_messages
    ):
        """失败后成功应重置断路器计数"""
        call_count = 0

        async def flaky_llm_call(prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("LLM 服务不可用")
            # 第 3 次成功
            return "## 目标\n- 测试摘要"

        small_compaction.set_llm_call(flaky_llm_call)

        # 前 2 次失败
        await small_compaction.compact(messages=large_messages)
        assert small_compaction._consecutive_failures == 1
        await small_compaction.compact(messages=large_messages)
        assert small_compaction._consecutive_failures == 2

        # 第 3 次成功，计数应重置为 0
        result = await small_compaction.compact(messages=large_messages)
        assert result["compacted"] is True
        assert small_compaction._consecutive_failures == 0

        # 后续失败应从 0 开始重新计数
        async def failing_llm_call(prompt, **kwargs):
            raise RuntimeError("LLM 服务不可用")

        small_compaction.set_llm_call(failing_llm_call)
        await small_compaction.compact(messages=large_messages)
        assert small_compaction._consecutive_failures == 1

    async def test_circuit_breaker_skips_without_llm_call(
        self, small_compaction, large_messages
    ):
        """未配置 LLM 调用时，连续 compact 达上限后应触发断路器"""
        # 未设置 llm_call，generate_summary 会返回 None
        for i in range(MAX_CONSECUTIVE_FAILURES):
            result = await small_compaction.compact(messages=large_messages)
            assert result["compacted"] is False
            assert small_compaction._consecutive_failures == i + 1

        # 断路器触发后，应直接返回未压缩消息，且携带显式错误字段
        result = await small_compaction.compact(messages=large_messages)
        assert result["compacted"] is False
        assert result["messages"] == large_messages
        assert result.get("error") is not None


class TestMicroCompact:
    """MicroCompact 轻量级压缩测试"""

    @pytest.fixture
    def compaction(self):
        """创建 CompactionManager 实例"""
        return CompactionManager(
            model_context_window=100_000,
            config=CompactionConfig(
                auto=True,
                buffer_tokens=10_000,
                keep_tokens=1_000,
            ),
        )

    def test_micro_compact_replaces_old_tool_results(self, compaction):
        """旧工具输出被替换为清除标记"""
        # 8 条消息，tool 在 index 2，N=5，old 条件: 2 < 8-5=3，True
        messages = [
            create_test_user_message("q1"),
            create_test_assistant_message("a1"),
            create_test_tool_use_message(tool_call_id="call_1", tool_name="Read", result="old file content"),
            create_test_assistant_message("a2"),
            create_test_user_message("q2"),
            create_test_assistant_message("a3"),
            create_test_user_message("q3"),
            create_test_assistant_message("a4"),
        ]

        result = compaction.micro_compact(messages)

        # 旧工具输出应被替换
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["content"] == "[Old tool result content cleared]"

    def test_micro_compact_preserves_recent_tool_results(self, compaction):
        """最近工具输出保留"""
        # 5 条消息，tool 在 index 4，N=5，old 条件: 4 < 5-5=0，False
        messages = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
            {"role": "tool", "tool_call_id": "call_1", "name": "Read", "content": "recent file content"},
        ]

        result = compaction.micro_compact(messages)

        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["content"] == "recent file content"

    def test_micro_compact_does_not_modify_original(self, compaction):
        """不修改原列表"""
        original_content = "old file content"
        messages = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "tool", "tool_call_id": "call_1", "name": "Read", "content": original_content},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a3"},
            {"role": "user", "content": "q3"},
            {"role": "assistant", "content": "a4"},
        ]

        result = compaction.micro_compact(messages)

        # 原列表不应被修改
        original_tool_msgs = [m for m in messages if m.get("role") == "tool"]
        assert original_tool_msgs[0]["content"] == original_content
        # 结果列表应被修改
        result_tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert result_tool_msgs[0]["content"] == "[Old tool result content cleared]"

    def test_micro_compact_preserves_non_compactable_tools(self, compaction):
        """非 COMPACTABLE_TOOLS 的工具输出保留"""
        messages = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "tool", "tool_call_id": "call_1", "name": "CustomTool", "content": "custom output"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a3"},
            {"role": "user", "content": "q3"},
            {"role": "assistant", "content": "a4"},
        ]

        result = compaction.micro_compact(messages)

        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert tool_msgs[0]["content"] == "custom output"

    def test_micro_compact_empty_messages(self, compaction):
        """空消息列表返回空列表"""
        result = compaction.micro_compact([])
        assert result == []

    def test_micro_compact_preserves_non_tool_messages(self, compaction):
        """非 tool 消息保持不变"""
        messages = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "q3"},
            {"role": "assistant", "content": "a3"},
            {"role": "user", "content": "q4"},
            {"role": "assistant", "content": "a4"},
        ]

        result = compaction.micro_compact(messages)

        # 所有消息应保持原样
        assert len(result) == len(messages)
        for original, compacted in zip(messages, result):
            assert original == compacted

    def test_group_messages_by_api_round(self, compaction):
        """按 API 轮次分组：assistant 开始新组，tool 归入当前组"""
        messages = [
            create_test_user_message("q1"),
            create_test_assistant_message("a1"),
            create_test_tool_use_message(tool_call_id="c1", tool_name="Read", result="r1"),
            create_test_tool_use_message(tool_call_id="c2", tool_name="Grep", result="r2"),
            create_test_assistant_message("a2"),
            create_test_tool_use_message(tool_call_id="c3", tool_name="Edit", result="r3"),
        ]

        groups = compaction.group_messages_by_api_round(messages)

        # 3 组: [user], [assistant1, tool1, tool2], [assistant2, tool3]
        assert len(groups) == 3
        assert groups[0] == [messages[0]]
        assert groups[1] == [messages[1], messages[2], messages[3]]
        assert groups[2] == [messages[4], messages[5]]

    def test_group_messages_by_api_round_empty(self, compaction):
        """空消息列表分组返回空列表"""
        groups = compaction.group_messages_by_api_round([])
        assert groups == []

    def test_group_messages_by_api_round_only_user(self, compaction):
        """仅 user 消息时归入一组"""
        messages = [
            create_test_user_message("q1"),
            create_test_user_message("q2"),
        ]

        groups = compaction.group_messages_by_api_round(messages)

        assert len(groups) == 1
        assert groups[0] == messages


class TestCompactBoundary:
    """CompactBoundary 边界标记测试"""

    def test_compactable_tools_set(self):
        """COMPACTABLE_TOOLS 集合包含预期工具"""
        expected = {"Read", "Shell", "Grep", "Glob", "WebSearch", "Edit", "Write"}
        assert COMPACTABLE_TOOLS == expected

    def test_create_compact_boundary_message(self):
        """验证边界消息创建"""
        msg = create_compact_boundary_message(
            anchor_uuid="anchor-123",
            head_uuid="head-456",
            tail_uuid="tail-789",
        )
        assert msg["role"] == "system"
        content = msg["content"]
        assert "anchor-123" in content
        assert "head-456" in content
        assert "tail-789" in content

    def test_create_compact_boundary_message_is_dict(self):
        """边界消息返回 dict 类型"""
        msg = create_compact_boundary_message(
            anchor_uuid="a",
            head_uuid="b",
            tail_uuid="c",
        )
        assert isinstance(msg, dict)
        assert "role" in msg
        assert "content" in msg

    def test_preserved_segment_dataclass(self):
        """验证 PreservedSegment 数据类字段"""
        segment = PreservedSegment(
            anchor_uuid="anchor-123",
            head_uuid="head-456",
            tail_uuid="tail-789",
        )
        assert segment.anchor_uuid == "anchor-123"
        assert segment.head_uuid == "head-456"
        assert segment.tail_uuid == "tail-789"

    def test_compact_boundary_message_dataclass(self):
        """验证 CompactBoundaryMessage 数据类字段"""
        segment = PreservedSegment(
            anchor_uuid="anchor-123",
            head_uuid="head-456",
            tail_uuid="tail-789",
        )
        boundary = CompactBoundaryMessage(
            is_compact_boundary=True,
            preserved_segment=segment,
        )
        assert boundary.is_compact_boundary is True
        assert boundary.preserved_segment is segment

    def test_compact_boundary_message_defaults(self):
        """验证 CompactBoundaryMessage 默认值"""
        boundary = CompactBoundaryMessage()
        assert boundary.is_compact_boundary is True
        assert boundary.preserved_segment is None


class TestCompactWithMicroCompact:
    """compact 方法优先使用 MicroCompact 测试"""

    async def test_compact_prefers_micro_compact(self):
        """compact 优先使用 MicroCompact，避免调用 LLM"""
        compaction = CompactionManager(
            model_context_window=5000,
            config=CompactionConfig(
                auto=True,
                buffer_tokens=500,
                keep_tokens=1000,
                summary_output_tokens=500,
            ),
        )

        # 创建大工具输出消息（会触发 should_compact）
        large_tool_output = "X" * 20000  # 约 5000 tokens
        messages = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "tool", "tool_call_id": "call_1", "name": "Read", "content": large_tool_output},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a3"},
            {"role": "user", "content": "q3"},
            {"role": "assistant", "content": "a4"},
        ]
        # len = 8, tool at index 2, old 条件: 2 < 8-5=3, True

        # 设置 LLM 调用计数器
        call_count = 0

        async def llm_call(prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            return "should not be called"

        compaction.set_llm_call(llm_call)

        result = await compaction.compact(messages=messages)

        # MicroCompact 应该成功，不需要调用 LLM
        assert result["compacted"] is True
        assert call_count == 0
        # 旧工具输出应被替换
        tool_msgs = [m for m in result["messages"] if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["content"] == "[Old tool result content cleared]"

    async def test_compact_falls_back_to_full_compaction(self):
        """MicroCompact 不足时回退到全量压缩"""
        compaction = CompactionManager(
            model_context_window=5000,
            config=CompactionConfig(
                auto=True,
                buffer_tokens=500,
                keep_tokens=1000,
                summary_output_tokens=500,
            ),
        )

        # 创建大量非工具消息（MicroCompact 无法处理）
        msg_text = "A" * 1000  # 约 250 tokens
        messages = []
        for i in range(20):
            role = "user" if i % 2 == 0 else "assistant"
            messages.append({"role": role, "content": msg_text})

        call_count = 0

        async def llm_call(prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            return "## 目标\n- 测试摘要"

        compaction.set_llm_call(llm_call)

        result = await compaction.compact(messages=messages)

        # MicroCompact 无法降低 token，应回退到全量压缩
        assert result["compacted"] is True
        assert call_count == 1
        assert result["summary"] is not None

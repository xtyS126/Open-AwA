"""
CompactionManager 单元测试。
测试上下文压缩、Token 估算、摘要生成。
"""

import pytest

from core.compaction_manager import (
    CompactionManager,
    CompactionConfig,
    TokenEstimator,
    TokenEstimate,
)


class TestTokenEstimator:
    """Token 估算器测试"""

    def test_estimate_empty(self):
        """空文本估算"""
        assert TokenEstimator.estimate("") == 0
        assert TokenEstimator.estimate(None) == 0  # type: ignore

    def test_estimate_english(self):
        """英文文本估算"""
        text = "This is a test message for token estimation."
        tokens = TokenEstimator.estimate(text)
        assert tokens > 0
        # 简单验证：字符数 / 3.5 ≈ tokens
        expected = max(1, int(len(text) / 3.5))
        assert tokens == expected

    def test_estimate_chinese(self):
        """中文文本估算"""
        text = "这是一条用于测试 token 估算的中文消息。"
        tokens = TokenEstimator.estimate(text)
        assert tokens > 0

    def test_estimate_messages(self):
        """消息列表估算"""
        messages = [
            {"role": "user", "content": "Hello, how are you?"},
            {"role": "assistant", "content": "I'm doing well, thank you!"},
        ]
        total = TokenEstimator.estimate_messages(messages)
        assert total > 0

    def test_estimate_total(self):
        """完整请求估算"""
        result = TokenEstimator.estimate_total(
            system_prompt="You are a helpful assistant.",
            messages=[{"role": "user", "content": "Hi!"}],
            tools=[{"type": "function", "function": {"name": "read", "description": "Read a file"}}],
        )
        assert isinstance(result, TokenEstimate)
        assert result.total > 0
        assert result.system_tokens > 0
        assert result.messages_tokens > 0
        assert result.tools_tokens > 0


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
        messages = [{"role": "user", "content": "Hello!"}]
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
            {"role": "user", "content": "Message 1: " + "hello " * 200},   # 大头消息
            {"role": "assistant", "content": "Response 1: " + "ok " * 50},
            {"role": "user", "content": "Message 2: how are you?"},
        ]
        head, recent = compaction.select_messages(messages)
        # 至少保留最后一条消息
        assert len(recent) >= 1
        # head + recent = 总消息数
        assert len(head) + len(recent) == len(messages)

    def test_serialize_message_user(self, compaction):
        """用户消息序列化"""
        msg = {"role": "user", "content": "Hello, world!"}
        result = compaction._serialize_message(msg)
        assert "[用户]" in result
        assert "Hello, world!" in result

    def test_serialize_message_assistant(self, compaction):
        """助手消息序列化"""
        msg = {"role": "assistant", "content": "I can help with that."}
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

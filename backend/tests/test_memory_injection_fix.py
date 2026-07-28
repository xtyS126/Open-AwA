"""
记忆系统修复单元测试

覆盖范围：
1. ExecutionLayer._build_relevant_memories_system_prompt 格式化逻辑
2. ExecutionLayer._build_messages_with_history 是否注入 vector_retrieved_memories
3. FeedbackLayer._should_persist 同时检查 user_input 与 response
4. FeedbackLayer.update_memory 在用户输入含偏好关键词时的持久化行为
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.executor import ExecutionLayer
from core.feedback import FeedbackLayer, MemoryPersistenceError


# ====================================================================
# 1. ExecutionLayer._build_relevant_memories_system_prompt
# ====================================================================

class TestBuildRelevantMemoriesSystemPrompt:
    """测试相关长期记忆的 system prompt 格式化逻辑"""

    def setup_method(self):
        self.layer = ExecutionLayer()

    def test_empty_context_returns_empty_string(self):
        """context 不含 vector_retrieved_memories 时返回空串"""
        result = self.layer._build_relevant_memories_system_prompt({})
        assert result == ""

    def test_none_memories_returns_empty_string(self):
        """vector_retrieved_memories 为 None 时返回空串"""
        result = self.layer._build_relevant_memories_system_prompt({"vector_retrieved_memories": None})
        assert result == ""

    def test_empty_list_returns_empty_string(self):
        """空列表返回空串"""
        result = self.layer._build_relevant_memories_system_prompt({"vector_retrieved_memories": []})
        assert result == ""

    def test_single_memory_with_metadata(self):
        """单条记忆含 importance/confidence 时格式化正确"""
        memories = [
            {
                "id": 1,
                "content": "用户偏好：Python",
                "importance": 0.9,
                "confidence": 0.85,
                "quality_score": 0.8,
            }
        ]
        result = self.layer._build_relevant_memories_system_prompt({"vector_retrieved_memories": memories})
        assert "长期记忆" in result
        assert "用户偏好：Python" in result
        assert "重要度=0.90" in result
        assert "置信度=0.85" in result

    def test_multiple_memories_numbered(self):
        """多条记忆按序号 1/2/3 编号"""
        memories = [
            {"id": 1, "content": "记忆A", "importance": 0.9, "confidence": 0.8},
            {"id": 2, "content": "记忆B", "importance": 0.7, "confidence": 0.6},
        ]
        result = self.layer._build_relevant_memories_system_prompt({"vector_retrieved_memories": memories})
        assert "1. 记忆A" in result
        assert "2. 记忆B" in result

    def test_memory_without_metadata_omits_meta_text(self):
        """记忆不含 importance/confidence 时不显示元信息括号"""
        memories = [{"id": 1, "content": "纯文本记忆"}]
        result = self.layer._build_relevant_memories_system_prompt({"vector_retrieved_memories": memories})
        assert "纯文本记忆" in result
        assert "重要度" not in result
        assert "置信度" not in result

    def test_memory_with_empty_content_skipped(self):
        """空 content 的记忆被跳过"""
        memories = [
            {"id": 1, "content": "", "importance": 0.9},
            {"id": 2, "content": "有效记忆", "importance": 0.7},
        ]
        result = self.layer._build_relevant_memories_system_prompt({"vector_retrieved_memories": memories})
        assert "有效记忆" in result
        assert "1. " not in result.split("有效记忆")[0]  # 空内容不应作为序号1

    def test_non_dict_memory_skipped(self):
        """非字典类型的记忆条目被跳过"""
        memories = [
            "invalid_string",
            {"id": 1, "content": "有效记忆", "importance": 0.7},
        ]
        result = self.layer._build_relevant_memories_system_prompt({"vector_retrieved_memories": memories})
        assert "有效记忆" in result


# ====================================================================
# 2. ExecutionLayer._build_messages_with_history 注入验证
# ====================================================================

class TestBuildMessagesWithHistoryInjection:
    """验证 _build_messages_with_history 是否正确注入记忆到 messages"""

    def setup_method(self):
        self.layer = ExecutionLayer()

    def test_memories_injected_as_system_message(self):
        """含 vector_retrieved_memories 时应在 messages 中出现 system 消息"""
        context = {
            "vector_retrieved_memories": [
                {"id": 1, "content": "用户喜欢 Python", "importance": 0.9, "confidence": 0.8}
            ]
        }
        messages = self.layer._build_messages_with_history("查询", context)
        system_msgs = [m for m in messages if m.get("role") == "system"]
        assert any("用户喜欢 Python" in str(m.get("content", "")) for m in system_msgs)

    def test_no_memories_no_extra_system_message(self):
        """无 vector_retrieved_memories 时不注入记忆 system 消息"""
        context = {"conversation_history": []}
        messages = self.layer._build_messages_with_history("查询", context)
        # 没有 agent_capabilities 时也不应有 system 消息（除非有 auto_execution_results）
        system_msgs = [m for m in messages if m.get("role") == "system"]
        assert len(system_msgs) == 0

    def test_memories_position_before_history(self):
        """记忆 system 消息应在 capability system prompt 之后、conversation_history 之前"""
        context = {
            "agent_capabilities": {
                "skills_enabled": True,
                "skills": [{"name": "test_skill", "description": "测试技能"}],
                "plugins_enabled": False,
                "plugins": [],
            },
            "vector_retrieved_memories": [
                {"id": 1, "content": "用户偏好Python", "importance": 0.9, "confidence": 0.8}
            ],
            "conversation_history": [
                {"role": "user", "content": "历史用户消息"},
                {"role": "assistant", "content": "历史助手回复"},
            ],
        }
        messages = self.layer._build_messages_with_history("当前查询", context)

        # 找到记忆 system 消息的位置
        memory_idx = None
        for idx, msg in enumerate(messages):
            if msg.get("role") == "system" and "用户偏好Python" in str(msg.get("content", "")):
                memory_idx = idx
                break

        assert memory_idx is not None, "记忆 system 消息未找到"

        # 找到第一个 conversation_history 的位置
        history_idx = None
        for idx, msg in enumerate(messages):
            if msg.get("content") == "历史用户消息":
                history_idx = idx
                break

        assert history_idx is not None, "历史消息未找到"
        assert memory_idx < history_idx, f"记忆({memory_idx})应在历史({history_idx})之前"

    def test_user_query_always_present(self):
        """用户当前查询始终在 messages 末尾"""
        context = {
            "vector_retrieved_memories": [
                {"id": 1, "content": "记忆", "importance": 0.7}
            ]
        }
        messages = self.layer._build_messages_with_history("我的当前问题", context)
        last_msg = messages[-1]
        assert last_msg.get("role") == "user"
        assert last_msg.get("content") == "我的当前问题"


# ====================================================================
# 3. FeedbackLayer._should_persist
# ====================================================================

class TestShouldPersist:
    """测试 _should_persist 关键词检测覆盖 user_input 与 response"""

    def setup_method(self):
        self.feedback = FeedbackLayer()

    def test_response_with_remember_keyword(self):
        """response 含 remember 触发持久化"""
        assert self.feedback._should_persist("Please remember this preference") is True

    def test_response_with_chinese_keyword(self):
        """response 含中文"记住"触发持久化"""
        assert self.feedback._should_persist("好的，我记住了你的偏好") is True

    def test_user_input_with_preference_keyword(self):
        """user_input 含"偏好"触发持久化（核心修复点）"""
        assert self.feedback._should_persist("请记住我的偏好：我喜欢Python") is True

    def test_user_input_with_like_keyword(self):
        """user_input 含"喜欢"触发持久化（新增关键词）"""
        assert self.feedback._should_persist("我喜欢用Python编程") is True

    def test_user_input_with_dislike_keyword(self):
        """user_input 含"不喜欢"触发持久化"""
        assert self.feedback._should_persist("我不喜欢Java的冗长") is True

    def test_neutral_content_not_persist(self):
        """中性内容不触发持久化"""
        assert self.feedback._should_persist("今天天气不错") is False
        assert self.feedback._should_persist("Hello, how are you?") is False

    def test_english_preference_keyword(self):
        """英文 preference 关键词触发"""
        assert self.feedback._should_persist("My preference is Python") is True

    def test_favorite_keyword(self):
        """favorite 关键词触发"""
        assert self.feedback._should_persist("Python is my favorite language") is True


# ====================================================================
# 4. FeedbackLayer.update_memory 持久化行为
# ====================================================================

class TestUpdateMemoryPersistence:
    """测试 update_memory 在用户输入含偏好时的持久化行为"""

    def setup_method(self):
        self.feedback = FeedbackLayer()
        # 用 AsyncMock 替代 MemoryManager
        self.mock_memory_manager = MagicMock()
        self.mock_memory_manager._MAX_LONG_TERM_CONTENT_CHARS = 500
        self.mock_memory_manager.add_short_term_memory = AsyncMock()
        self.mock_memory_manager.append_to_last_assistant_memory = AsyncMock()
        self.mock_memory_manager.add_long_term_memory = AsyncMock()
        self.feedback.set_memory_manager(self.mock_memory_manager)

    def test_user_preference_triggers_long_term_memory(self):
        """用户输入含"偏好"时触发长期记忆写入，且内容优先使用 user_input"""
        asyncio.run(self.feedback.update_memory(
            user_input="请记住我的偏好：我喜欢Python",
            response="好的，我知道了",
            context={"user_id": "test_user", "session_id": "test_session"},
        ))

        # 验证长期记忆被调用
        assert self.mock_memory_manager.add_long_term_memory.called, "长期记忆应被调用"
        call_args = self.mock_memory_manager.add_long_term_memory.call_args
        content = call_args.kwargs.get("content") or (call_args.args[0] if call_args.args else None)
        # 用户输入含偏好关键词，content 应为 user_input 本身
        assert "请记住我的偏好" in content
        assert "我喜欢Python" in content

    def test_response_only_keyword_uses_dialog_format(self):
        """仅 response 含关键词时使用对话拼接格式"""
        asyncio.run(self.feedback.update_memory(
            user_input="今天的会议内容",
            response="我会记住这次会议的重要决定",
            context={"user_id": "test_user", "session_id": "test_session"},
        ))

        assert self.mock_memory_manager.add_long_term_memory.called
        call_args = self.mock_memory_manager.add_long_term_memory.call_args
        content = call_args.kwargs.get("content")
        # response 含关键词，使用对话拼接格式
        assert "User asked: 今天的会议内容" in content
        assert "Assistant responded:" in content

    def test_neutral_dialog_no_persistence(self):
        """中性对话不触发长期记忆写入"""
        asyncio.run(self.feedback.update_memory(
            user_input="今天天气如何",
            response="今天天气不错",
            context={"user_id": "test_user", "session_id": "test_session"},
        ))

        assert not self.mock_memory_manager.add_long_term_memory.called, "中性对话不应触发长期记忆"

    def test_short_term_memory_always_called(self):
        """短期记忆始终被调用（用户+助手两条）"""
        asyncio.run(self.feedback.update_memory(
            user_input="测试消息",
            response="测试回复",
            context={"user_id": "test_user", "session_id": "test_session"},
        ))

        assert self.mock_memory_manager.add_short_term_memory.call_count == 2

    def test_short_term_memory_failure_is_propagated(self):
        """关键记忆写入失败必须传播，避免用户在上下文丢失时无感知。"""
        self.mock_memory_manager.add_short_term_memory = AsyncMock(side_effect=OSError("disk full"))

        with pytest.raises(MemoryPersistenceError):
            asyncio.run(self.feedback.update_memory(
                user_input="测试消息",
                response="测试回复",
                context={"user_id": "test_user", "session_id": "test_session"},
            ))

    def test_disable_memory_update_flag_skips_all(self):
        """disable_memory_update=True 跳过所有记忆写入"""
        asyncio.run(self.feedback.update_memory(
            user_input="请记住我的偏好",
            response="好的",
            context={"user_id": "test_user", "session_id": "test_session", "disable_memory_update": True},
        ))

        assert not self.mock_memory_manager.add_long_term_memory.called
        assert not self.mock_memory_manager.add_short_term_memory.called

    def test_subagent_continuation_appends_reasoning_and_tool_events(self):
        """隐藏续写应把完整执行元数据合并到原助手消息。"""
        tool_events = [{"id": "subagent-1", "status": "completed"}]

        asyncio.run(self.feedback.update_memory(
            user_input="隐藏续写提示",
            response="## 最终答复",
            context={
                "user_id": "test_user",
                "session_id": "test_session",
                "continuation": {
                    "source": "subagent",
                    "merge_with_last_assistant": True,
                    "aggregated_context": "子代理最终输出",
                },
            },
            reasoning_content="续写思考",
            tool_events=tool_events,
        ))

        self.mock_memory_manager.append_to_last_assistant_memory.assert_awaited_once_with(
            session_id="test_session",
            content="## 最终答复",
            user_id="test_user",
            reasoning_content="续写思考",
            tool_events=[
                *tool_events,
                {
                    "id": "subagent-aggregation",
                    "kind": "subagent",
                    "name": "子代理汇总",
                    "status": "completed",
                    "detail": "子代理执行结果已汇总",
                    "subagent": {
                        "agentId": "subagent-aggregation",
                        "agentType": "汇总",
                        "runMode": "background",
                        "logs": "子代理最终输出",
                        "summary": "子代理最终输出",
                        "visible": True,
                    },
                },
            ],
        )

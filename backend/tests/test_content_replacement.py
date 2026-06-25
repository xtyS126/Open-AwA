"""
ContentReplacementState 单元测试：验证工具结果预算的三分区算法。

覆盖：
- ContentReplacementState 初始状态
- enforce_tool_result_budget 三分区算法（replaced/frozen/fresh）
- 预算充足时不替换、超预算时替换旧工具结果、保留最近结果
- 状态更新、不修改原列表、已替换保持替换
- clone_content_replacement_state 克隆独立性
- 边界场景（空消息列表、无工具消息）
"""

import pytest

from core.content_replacement import (
    ContentReplacementState,
    clone_content_replacement_state,
    enforce_tool_result_budget,
)
from core.context.token_budget import TokenBudget
from harness.message_factory import (
    create_test_assistant_message,
    create_test_tool_use_message,
    create_test_user_message,
)


# ==================== 初始状态测试 ====================


class TestContentReplacementStateInitial:
    """验证 ContentReplacementState 的初始状态。"""

    def test_content_replacement_state_initial(self):
        """新建的 ContentReplacementState 应有空的 seen_ids 和 replacements。"""
        state = ContentReplacementState()

        assert state.seen_ids == set()
        assert state.replacements == {}
        assert len(state.seen_ids) == 0
        assert len(state.replacements) == 0


# ==================== 预算充足测试 ====================


class TestEnforceBudgetNoReplacement:
    """验证预算充足时不替换工具结果。"""

    def test_enforce_budget_no_replacement_under_budget(self):
        """总 token 在预算内时，所有工具结果应保持原样。"""
        state = ContentReplacementState()
        messages = [
            create_test_user_message("请执行工具"),
            {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "test_tool", "arguments": "{}"}}]},
            create_test_tool_use_message(tool_call_id="call_1", tool_name="test_tool", result="工具结果1"),
            {"role": "assistant", "content": None, "tool_calls": [{"id": "call_2", "type": "function", "function": {"name": "test_tool", "arguments": "{}"}}]},
            create_test_tool_use_message(tool_call_id="call_2", tool_name="test_tool", result="工具结果2"),
        ]

        # 预算设为足够大的值
        result = enforce_tool_result_budget(messages, state, budget=10000)

        # 工具结果未被替换
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) == 2
        assert tool_msgs[0]["content"] == "工具结果1"
        assert tool_msgs[1]["content"] == "工具结果2"

        # 状态已更新 seen_ids
        assert "call_1" in state.seen_ids
        assert "call_2" in state.seen_ids
        # 无替换发生
        assert len(state.replacements) == 0


# ==================== 超预算替换测试 ====================


class TestEnforceBudgetReplacesOld:
    """验证超预算时替换旧工具结果。"""

    def test_enforce_budget_replaces_old_tool_results(self):
        """总 token 超过预算时，旧的工具结果应被替换为占位文本。"""
        state = ContentReplacementState()
        # 构造大量工具结果，使总 token 超过预算
        large_content = "A" * 200  # 约 50 tokens
        messages = [
            create_test_tool_use_message(tool_call_id="call_1", result=large_content),
            create_test_tool_use_message(tool_call_id="call_2", result=large_content),
            create_test_tool_use_message(tool_call_id="call_3", result=large_content),
            create_test_tool_use_message(tool_call_id="call_4", result=large_content),
        ]

        # 预算设为只能容纳最近 1 个工具结果（每个结果约 50 tokens）
        # budget=50 时，冻结区累积到 50 即达到预算，只冻结最近 1 条
        result = enforce_tool_result_budget(messages, state, budget=50)

        tool_msgs = [m for m in result if m.get("role") == "tool"]
        # 最近的工具结果（call_4）应保留
        assert tool_msgs[3]["content"] == large_content
        # 旧的工具结果应被替换
        assert tool_msgs[0]["content"] == "[Old tool result content cleared]"
        assert tool_msgs[1]["content"] == "[Old tool result content cleared]"
        assert tool_msgs[2]["content"] == "[Old tool result content cleared]"

        # 状态应记录替换
        assert "call_1" in state.replacements
        assert "call_2" in state.replacements
        assert "call_3" in state.replacements
        assert "call_4" not in state.replacements


# ==================== 保留最近结果测试 ====================


class TestEnforceBudgetPreservesRecent:
    """验证保留最近的工具结果。"""

    def test_enforce_budget_preserves_recent_results(self):
        """冻结区内的最近工具结果应被保留，不被替换。"""
        state = ContentReplacementState()
        content_recent = "最近的结果数据"
        content_old = "旧的结果数据" * 20
        messages = [
            create_test_tool_use_message(tool_call_id="old_1", result=content_old),
            create_test_tool_use_message(tool_call_id="old_2", result=content_old),
            create_test_tool_use_message(tool_call_id="recent_1", result=content_recent),
            create_test_tool_use_message(tool_call_id="recent_2", result=content_recent),
        ]

        # 预算设为能容纳最近 2 个工具结果
        token_budget = TokenBudget()
        recent_tokens = token_budget.estimate_tokens(content_recent) * 2
        result = enforce_tool_result_budget(messages, state, budget=recent_tokens)

        tool_msgs = [m for m in result if m.get("role") == "tool"]
        # 最近的 2 个工具结果应保留
        assert tool_msgs[2]["content"] == content_recent
        assert tool_msgs[3]["content"] == content_recent
        # 旧的工具结果应被替换
        assert tool_msgs[0]["content"] == "[Old tool result content cleared]"
        assert tool_msgs[1]["content"] == "[Old tool result content cleared]"


# ==================== 状态更新测试 ====================


class TestEnforceBudgetUpdatesState:
    """验证 enforce_tool_result_budget 更新 state。"""

    def test_enforce_budget_updates_state(self):
        """执行后 state.seen_ids 和 state.replacements 应正确更新。"""
        state = ContentReplacementState()
        messages = [
            create_test_tool_use_message(tool_call_id="call_1", result="A" * 200),
            create_test_tool_use_message(tool_call_id="call_2", result="B" * 200),
        ]

        enforce_tool_result_budget(messages, state, budget=50)

        # seen_ids 应包含所有 tool_call_id
        assert "call_1" in state.seen_ids
        assert "call_2" in state.seen_ids
        # 至少有一个被替换（旧的）
        assert len(state.replacements) >= 1


# ==================== 不修改原列表测试 ====================


class TestEnforceBudgetNoModifyOriginal:
    """验证不修改原消息列表。"""

    def test_enforce_budget_does_not_modify_original(self):
        """原消息列表的内容不应被修改。"""
        state = ContentReplacementState()
        original_content = "原始工具结果" * 30
        messages = [
            create_test_tool_use_message(tool_call_id="call_1", result=original_content),
            create_test_tool_use_message(tool_call_id="call_2", result=original_content),
        ]

        # 保存原始内容的深拷贝
        original_messages = [dict(m) for m in messages]

        enforce_tool_result_budget(messages, state, budget=10)

        # 原列表内容未被修改
        assert messages[0]["content"] == original_content
        assert messages[1]["content"] == original_content
        assert messages == original_messages


# ==================== 已替换保持替换测试 ====================


class TestEnforceBudgetReplacedStaysReplaced:
    """验证已替换的工具结果保持替换状态。"""

    def test_enforce_budget_replaced_stays_replaced(self):
        """已在 state.replacements 中的工具结果应保持替换状态。"""
        state = ContentReplacementState()
        # 预设已替换状态
        state.seen_ids.add("call_1")
        state.replacements["call_1"] = "[Old tool result content cleared]"

        messages = [
            create_test_tool_use_message(tool_call_id="call_1", result="原始内容" * 30),
            create_test_tool_use_message(tool_call_id="call_2", result="新内容"),
        ]

        # 预算充足，不需要替换
        result = enforce_tool_result_budget(messages, state, budget=10000)

        tool_msgs = [m for m in result if m.get("role") == "tool"]
        # call_1 应保持替换状态（内容为占位文本）
        assert tool_msgs[0]["content"] == "[Old tool result content cleared]"
        # call_2 应保持原样
        assert tool_msgs[1]["content"] == "新内容"


# ==================== 克隆独立性测试 ====================


class TestCloneContentReplacementState:
    """验证 clone_content_replacement_state 的克隆独立性。"""

    def test_clone_content_replacement_state(self):
        """克隆应创建包含相同数据的新状态。"""
        state = ContentReplacementState()
        state.seen_ids.add("call_1")
        state.seen_ids.add("call_2")
        state.replacements["call_1"] = "[Old tool result content cleared]"

        cloned = clone_content_replacement_state(state)

        # 克隆应包含相同数据
        assert cloned.seen_ids == state.seen_ids
        assert cloned.replacements == state.replacements
        # 但是不同的对象
        assert cloned is not state
        assert cloned.seen_ids is not state.seen_ids
        assert cloned.replacements is not state.replacements

    def test_clone_state_independent_modification(self):
        """克隆后对克隆状态的修改不应影响原状态。"""
        state = ContentReplacementState()
        state.seen_ids.add("call_1")
        state.replacements["call_1"] = "[Old tool result content cleared]"

        cloned = clone_content_replacement_state(state)

        # 修改克隆状态
        cloned.seen_ids.add("call_2")
        cloned.replacements["call_2"] = "[Old tool result content cleared]"

        # 原状态不应受影响
        assert "call_2" not in state.seen_ids
        assert "call_2" not in state.replacements
        assert state.seen_ids == {"call_1"}
        assert state.replacements == {"call_1": "[Old tool result content cleared]"}

        # 克隆状态应包含新数据
        assert "call_2" in cloned.seen_ids
        assert "call_2" in cloned.replacements


# ==================== 边界场景测试 ====================


class TestEnforceBudgetEdgeCases:
    """验证边界场景。"""

    def test_enforce_budget_empty_messages(self):
        """空消息列表应返回空列表，不修改状态。"""
        state = ContentReplacementState()
        result = enforce_tool_result_budget([], state, budget=100)

        assert result == []
        assert state.seen_ids == set()
        assert state.replacements == {}

    def test_enforce_budget_no_tool_messages(self):
        """无工具消息时应返回原消息的拷贝，不修改状态。"""
        state = ContentReplacementState()
        messages = [
            create_test_user_message("用户消息"),
            create_test_assistant_message("助手回复"),
        ]

        result = enforce_tool_result_budget(messages, state, budget=100)

        # 应返回相同内容的列表
        assert len(result) == 2
        assert result[0]["content"] == "用户消息"
        assert result[1]["content"] == "助手回复"
        # 状态不应被修改
        assert state.seen_ids == set()
        assert state.replacements == {}

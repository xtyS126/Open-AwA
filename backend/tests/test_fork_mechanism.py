"""
Task 13/15: Fork 机制上下文克隆与调用链测试。

覆盖范围：
1. build_forked_messages 上下文克隆与深拷贝独立性（含 FORK_PLACEHOLDER_RESULT 占位 tool_result 块）
2. FORK_PLACEHOLDER_RESULT 占位符常量
3. is_in_fork_child 防递归检测（外部状态标志 + 对话内容检测）
4. build_child_message 子任务消息构造（含防递归指令）
5. SubagentPolicy 的 allow_fork / max_fork_depth / can_fork 控制
6. facade.spawn_agent(fork_mode=True) -> run_foreground fork 分支调用链
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from core.subagent_policy import SubagentPolicy
from core.task_runtime import task_runtime
from core.task_runtime import facade as facade_module
from core.task_runtime.fork import (
    FORK_PLACEHOLDER_RESULT,
    build_child_message,
    build_forked_messages,
    is_in_fork_child,
)


# ──────────────────────────────────────────────
#  build_forked_messages 测试
# ──────────────────────────────────────────────

class TestBuildForkedMessages:
    """验证 Fork 上下文克隆逻辑。"""

    def test_build_forked_messages_clones_context(self):
        """验证克隆上下文返回与原内容等价的消息列表（字节一致前缀 + 占位块）。"""
        parent_context = {
            "messages": [
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": "你好，有什么可以帮您？"},
            ],
            "user_id": "u_001",
        }
        forked = build_forked_messages(parent_context)

        # 数量 = 父代消息数 + 1（末尾占位 tool_result 块）
        assert len(forked) == 3
        # 前缀保持字节一致
        assert forked[0] == parent_context["messages"][0]
        assert forked[1] == parent_context["messages"][1]
        # 末尾为占位 tool_result 块
        assert forked[2]["role"] == "tool"
        assert forked[2]["content"] == FORK_PLACEHOLDER_RESULT

    def test_build_forked_messages_deep_copy(self):
        """验证深拷贝独立性：修改克隆结果不影响原上下文。"""
        original_message = {
            "role": "user",
            "content": "原始内容",
            "metadata": {"tags": ["a", "b"]},
        }
        parent_context = {"messages": [original_message]}
        forked = build_forked_messages(parent_context)

        # 修改克隆后的消息
        forked[0]["content"] = "修改后内容"
        forked[0]["metadata"]["tags"].append("c")

        # 原上下文不受影响
        assert parent_context["messages"][0]["content"] == "原始内容"
        assert parent_context["messages"][0]["metadata"]["tags"] == ["a", "b"]

    def test_build_forked_messages_empty_context(self):
        """验证空上下文或缺失 messages 字段时返回空列表。"""
        assert build_forked_messages({}) == []
        # 空消息列表时仅返回占位 tool_result 块
        empty_forked = build_forked_messages({"messages": []})
        assert len(empty_forked) == 1
        assert empty_forked[0]["content"] == FORK_PLACEHOLDER_RESULT
        assert build_forked_messages({"other": "value"}) == []

    def test_build_forked_messages_invalid_input(self):
        """验证非字典输入返回空列表。"""
        assert build_forked_messages(None) == []  # type: ignore[arg-type]
        assert build_forked_messages("not a dict") == []  # type: ignore[arg-type]
        assert build_forked_messages(123) == []  # type: ignore[arg-type]

    def test_build_forked_messages_non_list_messages(self):
        """验证 messages 字段非列表时返回空列表。"""
        assert build_forked_messages({"messages": "not a list"}) == []
        assert build_forked_messages({"messages": {"key": "value"}}) == []

    def test_build_forked_messages_appends_placeholder_tool_result(self):
        """验证克隆消息末尾追加含 FORK_PLACEHOLDER_RESULT 的占位 tool_result 块。"""
        parent_context = {
            "messages": [
                {"role": "user", "content": "原始问题"},
            ]
        }
        forked = build_forked_messages(parent_context)

        assert len(forked) == 2
        placeholder = forked[-1]
        assert placeholder["role"] == "tool"
        assert placeholder["content"] == FORK_PLACEHOLDER_RESULT
        assert placeholder["tool_call_id"] == "fork_placeholder"
        # 字节一致前缀：父代消息保持不变
        assert forked[0] == parent_context["messages"][0]
        # 占位块独立于父代消息（深拷贝）
        assert forked[0] is not placeholder


# ──────────────────────────────────────────────
#  FORK_PLACEHOLDER_RESULT 常量测试
# ──────────────────────────────────────────────

class TestForkPlaceholderResult:
    """验证 Fork 占位符常量。"""

    def test_fork_placeholder_result_constant(self):
        """验证占位符常量值符合预期。"""
        assert FORK_PLACEHOLDER_RESULT == "[Fork placeholder - parent context will be injected]"
        assert isinstance(FORK_PLACEHOLDER_RESULT, str)
        assert len(FORK_PLACEHOLDER_RESULT) > 0


# ──────────────────────────────────────────────
#  is_in_fork_child 测试
# ──────────────────────────────────────────────

class TestIsInForkChild:
    """验证 Fork 子 Agent 防递归检测。"""

    def test_is_in_fork_child_true(self):
        """验证 is_fork_child=True 时检测为 Fork 子 Agent。"""
        context = {"is_fork_child": True, "messages": []}
        assert is_in_fork_child(context) is True

    def test_is_in_fork_child_false(self):
        """验证非 Fork 子 Agent（标志缺失或为 False）的检测。"""
        # 标志缺失
        assert is_in_fork_child({}) is False
        assert is_in_fork_child({"messages": []}) is False

        # 标志为 False
        assert is_in_fork_child({"is_fork_child": False}) is False

    def test_is_in_fork_child_invalid_input(self):
        """验证非字典输入返回 False。"""
        assert is_in_fork_child(None) is False  # type: ignore[arg-type]
        assert is_in_fork_child("string") is False  # type: ignore[arg-type]

    def test_is_in_fork_child_truthy_values(self):
        """验证 truthy 值被视为 Fork 子 Agent。"""
        assert is_in_fork_child({"is_fork_child": 1}) is True
        assert is_in_fork_child({"is_fork_child": "yes"}) is True

    def test_is_in_fork_child_detects_anti_recursion_directive_in_messages(self):
        """验证无外部标志但消息含防递归指令文本时检测为 Fork 子 Agent。"""
        context = {
            "messages": [
                {
                    "role": "user",
                    "content": "请分析这段代码\n\n你当前是 Fork 子 Agent，不允许再次启动 Fork 子 Agent",
                },
            ]
        }
        assert is_in_fork_child(context) is True

    def test_is_in_fork_child_detects_placeholder_in_messages(self):
        """验证无外部标志但消息含占位符结果文本时检测为 Fork 子 Agent。"""
        context = {
            "messages": [
                {
                    "role": "tool",
                    "tool_call_id": "fork_placeholder",
                    "content": FORK_PLACEHOLDER_RESULT,
                },
            ]
        }
        assert is_in_fork_child(context) is True

    def test_is_in_fork_child_ignores_plain_messages(self):
        """验证普通对话消息不会被误判为 Fork 子 Agent。"""
        context = {
            "messages": [
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": "你好，有什么可以帮您？"},
            ]
        }
        assert is_in_fork_child(context) is False

    def test_is_in_fork_child_non_string_content(self):
        """验证非字符串消息内容不会导致异常。"""
        context = {
            "messages": [
                {"role": "tool", "content": 123},
                {"role": "user"},
            ]
        }
        assert is_in_fork_child(context) is False


# ──────────────────────────────────────────────
#  build_child_message 测试
# ──────────────────────────────────────────────

class TestBuildChildMessage:
    """验证 Fork 子 Agent 首条消息构造。"""

    def test_build_child_message_contains_task(self):
        """验证子消息包含任务描述。"""
        task_description = "请分析这段代码的性能瓶颈"
        message = build_child_message(task_description)

        assert message["role"] == "user"
        assert task_description in message["content"]

    def test_build_child_message_contains_anti_recursion(self):
        """验证子消息包含防递归指令。"""
        message = build_child_message("任意任务")

        assert message["role"] == "user"
        # 防递归指令关键字
        assert "Fork 子 Agent" in message["content"]
        assert "不允许" in message["content"]
        assert "再次启动" in message["content"]

    def test_build_child_message_format(self):
        """验证消息格式符合 OpenAI 消息结构。"""
        message = build_child_message("测试任务")

        assert isinstance(message, dict)
        assert set(message.keys()) == {"role", "content"}
        assert message["role"] == "user"
        assert isinstance(message["content"], str)

    def test_build_child_message_empty_task(self):
        """验证空任务描述也能正常构造消息。"""
        message = build_child_message("")

        assert message["role"] == "user"
        assert "Fork 子 Agent" in message["content"]


# ──────────────────────────────────────────────
#  SubagentPolicy Fork 控制测试
# ──────────────────────────────────────────────

class TestSubagentPolicyFork:
    """验证 SubagentPolicy 的 Fork 控制字段。"""

    def test_subagent_policy_allow_fork_default(self):
        """验证默认策略不允许 Fork。"""
        policy = SubagentPolicy()

        assert policy.allow_fork is False
        assert policy.max_fork_depth == 2

    def test_subagent_policy_can_fork_within_depth(self):
        """验证深度内允许 Fork。"""
        policy = SubagentPolicy(allow_fork=True, max_fork_depth=3)

        # 深度 0、1、2 均允许（< 3）
        assert policy.can_fork(0) is True
        assert policy.can_fork(1) is True
        assert policy.can_fork(2) is True

    def test_subagent_policy_can_fork_exceeds_depth(self):
        """验证超深度拒绝 Fork。"""
        policy = SubagentPolicy(allow_fork=True, max_fork_depth=2)

        # 深度 2 已达到上限（不 < 2），拒绝
        assert policy.can_fork(2) is False
        assert policy.can_fork(3) is False
        assert policy.can_fork(100) is False

    def test_subagent_policy_can_fork_disabled(self):
        """验证 allow_fork=False 时任何深度都拒绝 Fork。"""
        policy = SubagentPolicy(allow_fork=False, max_fork_depth=5)

        assert policy.can_fork(0) is False
        assert policy.can_fork(1) is False

    def test_subagent_policy_max_fork_depth_validation(self):
        """验证 max_fork_depth 参数校验。"""
        # 小于 1 应抛出异常
        with pytest.raises(ValueError, match="max_fork_depth"):
            SubagentPolicy(max_fork_depth=0)

        with pytest.raises(ValueError, match="max_fork_depth"):
            SubagentPolicy(max_fork_depth=-1)

    def test_subagent_policy_to_dict_includes_fork_fields(self):
        """验证 to_dict 序列化包含 Fork 字段。"""
        policy = SubagentPolicy(allow_fork=True, max_fork_depth=4)
        d = policy.to_dict()

        assert d["allow_fork"] is True
        assert d["max_fork_depth"] == 4

    def test_subagent_policy_from_dict_includes_fork_fields(self):
        """验证 from_dict 反序列化包含 Fork 字段。"""
        data = {
            "allow_fork": True,
            "max_fork_depth": 5,
        }
        policy = SubagentPolicy.from_dict(data)

        assert policy.allow_fork is True
        assert policy.max_fork_depth == 5

    def test_subagent_policy_from_dict_defaults(self):
        """验证 from_dict 缺失 Fork 字段时使用默认值。"""
        policy = SubagentPolicy.from_dict({})

        assert policy.allow_fork is False
        assert policy.max_fork_depth == 2


# ──────────────────────────────────────────────
#  facade.spawn_agent Fork 调用链测试
# ──────────────────────────────────────────────

class TestForkSpawnChain:
    """验证 facade.spawn_agent(fork_mode=True) 打通到 run_foreground fork 分支。"""

    @pytest.mark.asyncio
    async def test_spawn_agent_fork_mode_forwards_to_run_foreground(self):
        """验证 fork_mode=True 时以 fork_mode 参数调用 run_foreground。"""
        with patch.object(
            facade_module, "run_foreground", new=AsyncMock()
        ) as mock_run_foreground:
            result = await task_runtime.spawn_agent(
                agent_type="Explore",
                prompt="分析代码库结构",
                description="代码调研",
                fork_mode=True,
            )
            # 消费 AsyncMock 生成的协程，避免 "coroutine was never awaited" 警告
            await result

        mock_run_foreground.assert_called_once()
        call_kwargs = mock_run_foreground.call_args.kwargs
        assert call_kwargs["fork_mode"] is True
        assert call_kwargs["agent_type"] == "Explore"
        assert call_kwargs["prompt"] == "分析代码库结构"
        # 前台 fork 分支返回 async generator，而非后台 dict
        assert not isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_spawn_agent_fork_mode_priority_over_background_default(self):
        """验证 fork_mode=True 时即使代理定义 background_default=True 也不走后台路径。"""
        # Explore 的 background_default=True，fork_mode=True 时应优先走前台 fork 分支
        with patch.object(
            facade_module, "run_background", new=AsyncMock()
        ) as mock_run_background, patch.object(
            facade_module, "run_foreground", new=AsyncMock()
        ) as mock_run_foreground:
            result = await task_runtime.spawn_agent(
                agent_type="Explore",
                prompt="调研任务",
                description="调研",
                fork_mode=True,
            )
            await result

        mock_run_background.assert_not_called()
        mock_run_foreground.assert_called_once()
        assert mock_run_foreground.call_args.kwargs["fork_mode"] is True

    @pytest.mark.asyncio
    async def test_spawn_agent_default_fork_mode_false(self):
        """验证默认 fork_mode=False 时按原逻辑走 background 分支（Explore 默认后台）。"""
        with patch.object(
            facade_module, "run_background", new=AsyncMock()
        ) as mock_run_background, patch.object(
            facade_module, "run_foreground", new=AsyncMock()
        ) as mock_run_foreground:
            result = await task_runtime.spawn_agent(
                agent_type="Explore",
                prompt="调研任务",
                description="调研",
            )
            # background 分支在 spawn_agent 内部已 await，返回值无需再消费

        # Explore 默认 background_default=True，未开启 fork_mode 时走后台
        mock_run_background.assert_called_once()
        mock_run_foreground.assert_not_called()

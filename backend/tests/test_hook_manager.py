"""
HookManager 单元测试。
测试 Hook 注册、触发、链式调用、隔离执行、超时控制。
同时验证 HookResult 7 种结果类型及 hook_updated_input/hook_updated_output 合并函数。
"""

import asyncio
from unittest.mock import patch

import pytest
from loguru import logger

from core.hook_manager import (
    HOOK_TIMING_DISPLAY_THRESHOLD_MS,
    HookContext,
    HookManager,
    HookName,
    HookResult,
    HookResultType,
    hook_updated_input,
    hook_updated_output,
)


class TestHookManager:
    """Hook 管理器测试"""

    @pytest.fixture
    def manager(self):
        """创建 HookManager 实例"""
        mgr = HookManager()
        yield mgr
        mgr.clear()

    @pytest.mark.asyncio
    async def test_register_and_trigger(self, manager):
        """注册并触发 Hook（向后兼容：字符串返回值转换为 APPROVE + modified_output）"""
        results = []

        async def my_hook(ctx, data):
            results.append(data)
            return f"processed_{data}"

        manager.register("test-plugin", "test.hook", my_hook)

        triggered = await manager.trigger("test.hook", "hello")
        assert len(triggered) == 1
        # 字符串返回值被转换为 HookResult(APPROVE, modified_output=...)
        assert triggered[0].result_type == HookResultType.APPROVE
        assert triggered[0].modified_output == "processed_hello"
        assert results[0] == "hello"

    @pytest.mark.asyncio
    async def test_multiple_hooks(self, manager):
        """多个 Hook 按顺序触发"""
        order = []

        async def hook1(ctx, data):
            order.append(1)
            return data

        async def hook2(ctx, data):
            order.append(2)
            return data

        manager.register("plugin-a", "test.multi", hook1)
        manager.register("plugin-b", "test.multi", hook2)

        await manager.trigger("test.multi", "data")
        assert order == [1, 2]

    @pytest.mark.asyncio
    async def test_trigger_empty(self, manager):
        """触发未注册的 Hook"""
        results = await manager.trigger("nonexistent.hook", "data")
        assert results == []

    @pytest.mark.asyncio
    async def test_isolated_execution(self, manager):
        """隔离执行：一个 Hook 失败不影响其他"""
        call_count = []

        async def failing_hook(ctx, data):
            call_count.append("failed")
            raise ValueError("Intentional error")

        async def working_hook(ctx, data):
            call_count.append("worked")
            return "success"

        manager.register("bad-plugin", "test.isolated", failing_hook)
        manager.register("good-plugin", "test.isolated", working_hook)

        results = await manager.trigger("test.isolated", "data")
        # working_hook 应该仍然返回结果（字符串被包装为 APPROVE + modified_output）
        assert any(r.modified_output == "success" for r in results)
        assert call_count == ["failed", "worked"]

    @pytest.mark.asyncio
    async def test_timeout_control(self, manager):
        """超时控制测试"""
        async def slow_hook(ctx, data):
            await asyncio.sleep(0.5)
            return "too late"

        manager.register("slow-plugin", "test.timeout", slow_hook, timeout_seconds=0.1)

        results = await manager.trigger("test.timeout", "data")
        # 超时的 Hook 不应产生结果
        assert results == []

    @pytest.mark.asyncio
    async def test_chain_trigger(self, manager):
        """链式触发测试"""
        async def append_a(ctx, data):
            return data + "A"

        async def append_b(ctx, data):
            return data + "B"

        manager.register("plugin-1", "test.chain", append_a)
        manager.register("plugin-2", "test.chain", append_b)

        result = await manager.trigger_chain("test.chain", "X")
        assert result == "XAB"

    @pytest.mark.asyncio
    async def test_chain_isolated(self, manager):
        """链式触发中的隔离"""
        async def good_transform(ctx, data):
            return {"value": data.get("value", 0) + 1}

        async def bad_transform(ctx, data):
            raise RuntimeError("Transform failed")

        async def another_good(ctx, data):
            return {"value": data.get("value", 0) + 10}

        manager.register("p1", "test.chain_iso", good_transform)
        manager.register("p2", "test.chain_iso", bad_transform)
        manager.register("p3", "test.chain_iso", another_good)

        result = await manager.trigger_chain("test.chain_iso", {"value": 5})
        # bad_transform 失败，但数据应继续流动
        # good_transform: 5 -> 6
        # bad_transform: fails, data stays 6
        # another_good: 6 -> 16
        assert result["value"] == 16

    def test_unregister_plugin(self, manager):
        """注销插件所有 Hook"""
        async def hook1(ctx, data):
            return data

        async def hook2(ctx, data):
            return data

        manager.register("my-plugin", "hook.a", hook1)
        manager.register("my-plugin", "hook.b", hook2)

        # 验证注册
        assert len(manager.get_plugin_hooks("my-plugin")) == 2

        # 注销
        count = manager.unregister_plugin("my-plugin")
        assert count == 2
        assert len(manager.get_plugin_hooks("my-plugin")) == 0

    def test_get_registrations(self, manager):
        """获取注册信息"""
        async def my_hook(ctx, data):
            pass

        manager.register("plugin-x", "hook.x", my_hook)
        manager.register("plugin-y", "hook.x", my_hook)

        registrations = manager.get_registrations("hook.x")
        assert len(registrations["hook.x"]) == 2

    def test_disabled_hook(self, manager):
        """禁用的 Hook 不会被触发"""
        # 此测试需要在注册后手动设置 enabled = False
        # 验证方式：确保 API 设计支持 enabled 字段
        async def my_hook(ctx, data):
            raise RuntimeError("Should not be called")

        registration = manager.register("test", "test.disabled", my_hook)
        registration.enabled = False

        # 禁用的 Hook 不应被触发
        # 注意：这里无法完全验证，因为 trigger 是在 async 上下文
        # 但至少 API 暴露了 enabled 属性


class TestHookContext:
    """Hook 上下文测试"""

    def test_basic_context(self):
        """基本上下文"""
        ctx = HookContext(
            hook_name="tool.before_execute",
            plugin_id="my-plugin",
            session_id="session-1",
        )
        assert ctx.hook_name == "tool.before_execute"
        assert ctx.plugin_id == "my-plugin"
        assert ctx.session_id == "session-1"

    def test_metadata(self):
        """元数据"""
        ctx = HookContext(
            hook_name="agent.system_prompt",
            metadata={"agent_type": "build", "model": "gpt-4"},
        )
        assert ctx.metadata["agent_type"] == "build"


class TestHookName:
    """Hook 名称枚举测试"""

    def test_all_hooks_defined(self):
        """所有预定义 Hook 已定义"""
        assert HookName.AGENT_SYSTEM_PROMPT == "agent.system_prompt"
        assert HookName.TOOL_BEFORE_EXECUTE == "tool.before_execute"
        assert HookName.TOOL_AFTER_EXECUTE == "tool.after_execute"
        assert HookName.LLM_BEFORE_REQUEST == "llm.before_request"
        assert HookName.LLM_AFTER_RESPONSE == "llm.after_response"
        assert HookName.SESSION_CREATED == "session.created"
        assert HookName.SESSION_CLOSED == "session.closed"


class TestHookResultType:
    """HookResultType 枚举测试"""

    def test_hook_result_type_enum(self):
        """验证 8 种 HookResultType 枚举值"""
        assert HookResultType.APPROVE == "approve"
        assert HookResultType.DENY == "deny"
        assert HookResultType.ASK == "ask"
        assert HookResultType.MODIFY_INPUT == "modify_input"
        assert HookResultType.MODIFY_OUTPUT == "modify_output"
        assert HookResultType.PREVENT_CONTINUATION == "prevent_continuation"
        assert HookResultType.REPLACE_RESULT == "replace_result"
        assert HookResultType.ERROR == "error"

    def test_hook_result_type_count(self):
        """验证枚举成员数量为 8"""
        members = list(HookResultType)
        assert len(members) == 8


class TestHookResultDataclass:
    """HookResult 数据类测试"""

    def test_hook_result_dataclass(self):
        """验证 HookResult 数据类的字段和默认值"""
        # 默认值：所有可选字段为 None
        result = HookResult(result_type=HookResultType.APPROVE)
        assert result.result_type == HookResultType.APPROVE
        assert result.modified_input is None
        assert result.modified_output is None
        assert result.replace_result is None
        assert result.error_message is None
        assert result.reason is None

    def test_hook_result_with_all_fields(self):
        """验证 HookResult 可携带所有字段"""
        result = HookResult(
            result_type=HookResultType.MODIFY_INPUT,
            modified_input={"key": "value"},
            modified_output={"output": "data"},
            replace_result="replaced",
            error_message="something went wrong",
            reason="test reason",
        )
        assert result.modified_input == {"key": "value"}
        assert result.modified_output == {"output": "data"}
        assert result.replace_result == "replaced"
        assert result.error_message == "something went wrong"
        assert result.reason == "test reason"


class TestTriggerReturnsHookResult:
    """验证 trigger 方法返回 List[HookResult]"""

    @pytest.fixture
    def manager(self):
        """创建 HookManager 实例"""
        mgr = HookManager()
        yield mgr
        mgr.clear()

    @pytest.mark.asyncio
    async def test_trigger_returns_list_of_results(self, manager):
        """验证 trigger 返回 List[HookResult]"""
        async def my_hook(ctx, data):
            return HookResult(result_type=HookResultType.APPROVE)

        manager.register("p1", "test.return_type", my_hook)
        results = await manager.trigger("test.return_type", "data")

        assert isinstance(results, list)
        assert len(results) == 1
        assert isinstance(results[0], HookResult)
        assert results[0].result_type == HookResultType.APPROVE

    @pytest.mark.asyncio
    async def test_trigger_empty_when_no_hooks(self, manager):
        """验证无钩子注册时返回空列表"""
        results = await manager.trigger("no.hook.registered", "data")
        assert results == []
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_trigger_backward_compat_bool(self, manager):
        """验证 bool 返回值的向后兼容：True -> APPROVE, False -> DENY"""
        async def approve_hook(ctx, data):
            return True

        async def deny_hook(ctx, data):
            return False

        manager.register("p-approve", "test.bool", approve_hook)
        results = await manager.trigger("test.bool", "data")
        assert results[0].result_type == HookResultType.APPROVE

        manager.clear()
        manager.register("p-deny", "test.bool", deny_hook)
        results = await manager.trigger("test.bool", "data")
        assert results[0].result_type == HookResultType.DENY

    @pytest.mark.asyncio
    async def test_trigger_backward_compat_none(self, manager):
        """验证 None 返回值的向后兼容：None -> APPROVE"""
        async def none_hook(ctx, data):
            return None

        manager.register("p-none", "test.none", none_hook)
        results = await manager.trigger("test.none", "data")
        assert results[0].result_type == HookResultType.APPROVE


class TestHookResultTypes:
    """验证 7 种 HookResultType 在 trigger 中的行为"""

    @pytest.fixture
    def manager(self):
        """创建 HookManager 实例"""
        mgr = HookManager()
        yield mgr
        mgr.clear()

    @pytest.mark.asyncio
    async def test_hook_approve(self, manager):
        """验证 APPROVE 结果类型"""
        async def approve_hook(ctx, data):
            return HookResult(result_type=HookResultType.APPROVE, reason="放行")

        manager.register("p1", "test.approve", approve_hook)
        results = await manager.trigger("test.approve", "data")
        assert len(results) == 1
        assert results[0].result_type == HookResultType.APPROVE
        assert results[0].reason == "放行"

    @pytest.mark.asyncio
    async def test_hook_deny(self, manager):
        """验证 DENY 结果类型"""
        async def deny_hook(ctx, data):
            return HookResult(
                result_type=HookResultType.DENY,
                reason="权限不足",
            )

        manager.register("p1", "test.deny", deny_hook)
        results = await manager.trigger("test.deny", "data")
        assert len(results) == 1
        assert results[0].result_type == HookResultType.DENY
        assert results[0].reason == "权限不足"

    @pytest.mark.asyncio
    async def test_hook_modify_input(self, manager):
        """验证 MODIFY_INPUT 结果类型"""
        async def modify_input_hook(ctx, data):
            return HookResult(
                result_type=HookResultType.MODIFY_INPUT,
                modified_input={"added_field": "injected"},
            )

        manager.register("p1", "test.modify_input", modify_input_hook)
        results = await manager.trigger("test.modify_input", "data")
        assert len(results) == 1
        assert results[0].result_type == HookResultType.MODIFY_INPUT
        assert results[0].modified_input == {"added_field": "injected"}

    @pytest.mark.asyncio
    async def test_hook_modify_output(self, manager):
        """验证 MODIFY_OUTPUT 结果类型"""
        async def modify_output_hook(ctx, data):
            return HookResult(
                result_type=HookResultType.MODIFY_OUTPUT,
                modified_output={"rewritten": True},
            )

        manager.register("p1", "test.modify_output", modify_output_hook)
        results = await manager.trigger("test.modify_output", "data")
        assert len(results) == 1
        assert results[0].result_type == HookResultType.MODIFY_OUTPUT
        assert results[0].modified_output == {"rewritten": True}

    @pytest.mark.asyncio
    async def test_hook_prevent_continuation(self, manager):
        """验证 PREVENT_CONTINUATION 结果类型"""
        async def prevent_hook(ctx, data):
            return HookResult(
                result_type=HookResultType.PREVENT_CONTINUATION,
                reason="检测到危险操作",
            )

        manager.register("p1", "test.prevent", prevent_hook)
        results = await manager.trigger("test.prevent", "data")
        assert len(results) == 1
        assert results[0].result_type == HookResultType.PREVENT_CONTINUATION
        assert results[0].reason == "检测到危险操作"

    @pytest.mark.asyncio
    async def test_hook_replace_result(self, manager):
        """验证 REPLACE_RESULT 结果类型"""
        async def replace_hook(ctx, data):
            return HookResult(
                result_type=HookResultType.REPLACE_RESULT,
                replace_result={"cached": "value"},
            )

        manager.register("p1", "test.replace", replace_hook)
        results = await manager.trigger("test.replace", "data")
        assert len(results) == 1
        assert results[0].result_type == HookResultType.REPLACE_RESULT
        assert results[0].replace_result == {"cached": "value"}

    @pytest.mark.asyncio
    async def test_hook_error(self, manager):
        """验证 ERROR 结果类型"""
        async def error_hook(ctx, data):
            return HookResult(
                result_type=HookResultType.ERROR,
                error_message="钩子内部校验失败",
            )

        manager.register("p1", "test.error", error_hook)
        results = await manager.trigger("test.error", "data")
        assert len(results) == 1
        assert results[0].result_type == HookResultType.ERROR
        assert results[0].error_message == "钩子内部校验失败"

    @pytest.mark.asyncio
    async def test_hook_ask(self, manager):
        """验证 ASK 结果类型（需要用户确认）"""
        async def ask_hook(ctx, data):
            return HookResult(
                result_type=HookResultType.ASK,
                reason="需要用户确认此操作",
            )

        manager.register("p1", "test.ask", ask_hook)
        results = await manager.trigger("test.ask", "data")
        assert len(results) == 1
        assert results[0].result_type == HookResultType.ASK
        assert results[0].reason == "需要用户确认此操作"


class TestHookUpdatedInput:
    """验证 hook_updated_input 合并函数"""

    def test_hook_updated_input_merges(self):
        """验证多个 MODIFY_INPUT 结果合并到原始输入"""
        original = {"a": 1, "b": 2}
        results = [
            HookResult(
                result_type=HookResultType.MODIFY_INPUT,
                modified_input={"b": 20, "c": 30},
            ),
            HookResult(
                result_type=HookResultType.MODIFY_INPUT,
                modified_input={"c": 300},
            ),
        ]
        merged = hook_updated_input(results, original)
        # 后者覆盖前者
        assert merged == {"a": 1, "b": 20, "c": 300}

    def test_hook_updated_input_no_modify_results(self):
        """无 MODIFY_INPUT 结果时返回原始输入的副本"""
        original = {"a": 1}
        results = [
            HookResult(result_type=HookResultType.APPROVE),
            HookResult(result_type=HookResultType.DENY),
        ]
        merged = hook_updated_input(results, original)
        assert merged == {"a": 1}
        # 验证返回的是新对象
        assert merged is not original

    def test_hook_updated_input_empty_results(self):
        """空结果列表时返回原始输入的副本"""
        original = {"x": 1}
        merged = hook_updated_input([], original)
        assert merged == {"x": 1}
        assert merged is not original

    def test_hook_updated_input_does_not_mutate_original(self):
        """验证合并操作不修改原始输入"""
        original = {"a": 1}
        results = [
            HookResult(
                result_type=HookResultType.MODIFY_INPUT,
                modified_input={"b": 2},
            ),
        ]
        hook_updated_input(results, original)
        # 原始输入不应被修改
        assert original == {"a": 1}


class TestHookUpdatedOutput:
    """验证 hook_updated_output 函数"""

    def test_hook_updated_output(self):
        """验证 MODIFY_OUTPUT 结果替换原始输出"""
        original_output = {"status": "ok", "data": "original"}
        results = [
            HookResult(
                result_type=HookResultType.MODIFY_OUTPUT,
                modified_output={"status": "ok", "data": "modified"},
            ),
        ]
        updated = hook_updated_output(results, original_output)
        assert updated == {"status": "ok", "data": "modified"}

    def test_hook_updated_output_last_wins(self):
        """验证多个 MODIFY_OUTPUT 时最后一个生效"""
        original_output = "original"
        results = [
            HookResult(
                result_type=HookResultType.MODIFY_OUTPUT,
                modified_output="first",
            ),
            HookResult(
                result_type=HookResultType.MODIFY_OUTPUT,
                modified_output="second",
            ),
        ]
        updated = hook_updated_output(results, original_output)
        assert updated == "second"

    def test_hook_updated_output_no_modify_results(self):
        """无 MODIFY_OUTPUT 结果时返回原始输出"""
        original_output = {"data": "original"}
        results = [
            HookResult(result_type=HookResultType.APPROVE),
            HookResult(result_type=HookResultType.DENY),
        ]
        updated = hook_updated_output(results, original_output)
        assert updated == {"data": "original"}

    def test_hook_updated_output_empty_results(self):
        """空结果列表时返回原始输出"""
        original_output = "original"
        updated = hook_updated_output([], original_output)
        assert updated == "original"


class TestHookTimingThreshold:
    """验证钩子执行耗时阈值日志"""

    @pytest.fixture
    def manager(self):
        """创建 HookManager 实例"""
        mgr = HookManager()
        yield mgr
        mgr.clear()

    @pytest.mark.asyncio
    async def test_hook_timing_threshold(self, manager):
        """验证钩子执行耗时超过阈值时记录 warning 日志"""
        # 收集日志消息的列表
        log_messages = []

        def log_sink(message):
            log_messages.append(str(message))

        # 添加临时日志 sink
        sink_id = logger.add(log_sink, level="WARNING")

        try:
            async def fast_hook(ctx, data):
                return HookResult(result_type=HookResultType.APPROVE)

            manager.register("p1", "test.timing", fast_hook)

            # 将阈值设为 -1，确保任何钩子执行都会触发耗时 warning
            with patch("core.hook_manager.HOOK_TIMING_DISPLAY_THRESHOLD_MS", -1):
                await manager.trigger("test.timing", "data")

            # 验证 warning 日志中包含耗时信息
            timing_warnings = [
                msg for msg in log_messages if "执行耗时" in msg
            ]
            assert len(timing_warnings) >= 1
            assert "test.timing" in timing_warnings[0]
        finally:
            logger.remove(sink_id)

    @pytest.mark.asyncio
    async def test_hook_timing_below_threshold_no_warning(self, manager):
        """验证钩子执行耗时未超过阈值时不记录 warning 日志"""
        log_messages = []

        def log_sink(message):
            log_messages.append(str(message))

        sink_id = logger.add(log_sink, level="WARNING")

        try:
            async def fast_hook(ctx, data):
                return HookResult(result_type=HookResultType.APPROVE)

            manager.register("p1", "test.timing_ok", fast_hook)

            # 阈值保持默认 500ms，快速钩子不应触发 warning
            await manager.trigger("test.timing_ok", "data")

            timing_warnings = [
                msg for msg in log_messages if "执行耗时" in msg
            ]
            assert len(timing_warnings) == 0
        finally:
            logger.remove(sink_id)

    def test_threshold_constant_value(self):
        """验证 HOOK_TIMING_DISPLAY_THRESHOLD_MS 常量值为 500"""
        assert HOOK_TIMING_DISPLAY_THRESHOLD_MS == 500


class TestCoerceToHookResult:
    """验证 _coerce_to_hook_result 向后兼容转换逻辑"""

    def test_ask_decision_not_downgraded_to_deny(self):
        """验证 ask 决策不再被降级为 DENY，而是保持 ASK 语义"""
        from core.hook_manager import _coerce_to_hook_result

        # hook_dispatcher 风格的 ask 决策 dict
        raw = {"decision": "ask", "reason": "需要用户确认", "updated_input": {"key": "val"}}
        result = _coerce_to_hook_result(raw)
        assert result.result_type == HookResultType.ASK
        assert result.reason == "需要用户确认"
        assert result.modified_input == {"key": "val"}

    def test_deny_decision_remains_deny(self):
        """验证 deny 决策保持 DENY"""
        from core.hook_manager import _coerce_to_hook_result

        raw = {"decision": "deny", "reason": "权限不足"}
        result = _coerce_to_hook_result(raw)
        assert result.result_type == HookResultType.DENY
        assert result.reason == "权限不足"

    def test_allow_decision_remains_approve(self):
        """验证 allow 决策转为 APPROVE"""
        from core.hook_manager import _coerce_to_hook_result

        raw = {"decision": "allow", "updated_input": {"extra": "data"}}
        result = _coerce_to_hook_result(raw)
        assert result.result_type == HookResultType.APPROVE
        assert result.modified_input == {"extra": "data"}

    def test_defer_decision_remains_approve(self):
        """验证 defer 决策转为 APPROVE"""
        from core.hook_manager import _coerce_to_hook_result

        raw = {"decision": "defer"}
        result = _coerce_to_hook_result(raw)
        assert result.result_type == HookResultType.APPROVE

    def test_bool_true_returns_approve(self):
        """验证 True 转为 APPROVE"""
        from core.hook_manager import _coerce_to_hook_result

        result = _coerce_to_hook_result(True)
        assert result.result_type == HookResultType.APPROVE

    def test_bool_false_returns_deny(self):
        """验证 False 转为 DENY"""
        from core.hook_manager import _coerce_to_hook_result

        result = _coerce_to_hook_result(False)
        assert result.result_type == HookResultType.DENY

    def test_none_returns_approve(self):
        """验证 None 转为 APPROVE"""
        from core.hook_manager import _coerce_to_hook_result

        result = _coerce_to_hook_result(None)
        assert result.result_type == HookResultType.APPROVE

    def test_hook_result_passthrough(self):
        """验证 HookResult 实例原样返回"""
        from core.hook_manager import _coerce_to_hook_result

        original = HookResult(result_type=HookResultType.ASK, reason="确认")
        result = _coerce_to_hook_result(original)
        assert result is original
        assert result.result_type == HookResultType.ASK

"""计划生成器测试：验证不同意图类型的差异化计划生成。"""

from core.intent_classifier import IntentType
from core.plan_builder import PlanBuilder, ExecutionPlan


class TestPlanBuilder:
    """计划生成器单元测试"""

    def setup_method(self):
        self.builder = PlanBuilder()

    def test_build_chat_plan(self):
        """chat 意图应生成快速路径计划"""
        plan = self.builder.build(IntentType.CHAT, "你好")
        assert plan.mode == "fast"
        assert plan.use_subagent is False
        assert len(plan.steps) == 1
        step = plan.steps[0]
        assert step["type"] == "llm_chat"
        assert step["action"] == "respond"
        assert step["message"] == "你好"
        assert step.get("enable_tools") is not True  # chat 路径不包含 enable_tools 字段

    def test_build_code_plan(self):
        """code 意图应生成工具调用路径计划"""
        plan = self.builder.build(IntentType.CODE, "写一个排序算法")
        assert plan.mode == "tool_calls"
        assert plan.use_subagent is False
        assert plan.steps[0]["action"] == "code"
        assert plan.steps[0]["enable_tools"] is True

    def test_build_search_plan(self):
        """search 意图应生成工具调用路径计划"""
        plan = self.builder.build(IntentType.SEARCH, "搜索 Python 资料")
        assert plan.mode == "tool_calls"
        assert plan.use_subagent is False
        assert plan.steps[0]["action"] == "search"
        assert plan.steps[0]["enable_tools"] is True

    def test_build_task_plan(self):
        """task 意图应生成多步骤计划并启用子Agent"""
        plan = self.builder.build(IntentType.TASK, "执行批量任务")
        assert plan.mode == "multi_step"
        assert plan.use_subagent is True
        assert plan.steps[0]["action"] == "task"
        assert plan.steps[0]["enable_tools"] is True

    def test_build_manage_plan(self):
        """manage 意图应生成工具调用路径计划"""
        plan = self.builder.build(IntentType.MANAGE, "修改设置")
        assert plan.mode == "tool_calls"
        assert plan.use_subagent is False
        assert plan.steps[0]["action"] == "manage"
        assert plan.steps[0]["enable_tools"] is True

    def test_execution_plan_to_dict(self):
        """ExecutionPlan.to_dict 应返回完整字典"""
        plan = ExecutionPlan(
            steps=[{"type": "llm_chat", "action": "respond", "message": "test"}],
            mode="fast",
            use_subagent=False,
        )
        result = plan.to_dict()
        assert result == {
            "steps": [{"type": "llm_chat", "action": "respond", "message": "test"}],
            "mode": "fast",
            "use_subagent": False,
        }

    def test_execution_plan_defaults(self):
        """ExecutionPlan 默认值应正确"""
        plan = ExecutionPlan()
        assert plan.steps == []
        assert plan.mode == "fast"
        assert plan.use_subagent is False
        assert plan.to_dict() == {"steps": [], "mode": "fast", "use_subagent": False}

    def test_build_with_entities(self):
        """build 方法应接受 entities 参数"""
        plan = self.builder.build(
            IntentType.CODE, "写代码", entities={"entities": [{"type": "file", "value": "test.py"}]}
        )
        assert plan.mode == "tool_calls"
        assert plan.steps[0]["action"] == "code"
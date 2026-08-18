"""
计划生成器：根据意图类型生成差异化的执行计划。
支持三种执行路径：快速路径（chat）、工具调用路径（code/search/manage）、多步骤子Agent路径（task）。
"""
from typing import List, Dict, Any

from .intent_classifier import IntentType


class ExecutionPlan:
    """执行计划"""

    def __init__(
        self,
        steps: List[Dict[str, Any]] = None,
        mode: str = "fast",
        use_subagent: bool = False,
    ):
        self.steps = steps or []
        self.mode = mode
        self.use_subagent = use_subagent

    def to_dict(self) -> Dict[str, Any]:
        return {
            "steps": self.steps,
            "mode": self.mode,
            "use_subagent": self.use_subagent,
        }


class PlanBuilder:
    """计划生成器：根据意图类型生成差异化计划。

    注意：当前流式路径由模型原生工具循环（StreamOrchestrator）驱动执行，
    本计划仅作为前端计划展示与意图分类结果，不驱动真实工具执行步骤。
    """

    def build(
        self,
        intent_type: IntentType,
        message: str,
        entities: Dict[str, Any] = None,
    ) -> ExecutionPlan:
        """根据意图类型生成执行计划"""
        if intent_type == IntentType.CHAT:
            return self._build_chat_plan(message)
        elif intent_type == IntentType.CODE:
            return self._build_code_plan(message, entities or {})
        elif intent_type == IntentType.SEARCH:
            return self._build_search_plan(message, entities or {})
        elif intent_type == IntentType.TASK:
            return self._build_task_plan(message, entities or {})
        elif intent_type == IntentType.MANAGE:
            return self._build_manage_plan(message, entities or {})
        else:
            return self._build_chat_plan(message)

    def _build_chat_plan(self, message: str) -> ExecutionPlan:
        """聊天意图：快速路径，不启用工具调用"""
        return ExecutionPlan(
            steps=[{"type": "llm_chat", "action": "respond", "message": message}],
            mode="fast",
            use_subagent=False,
        )

    def _build_code_plan(self, message: str, entities: Dict[str, Any]) -> ExecutionPlan:
        """编程意图：工具调用路径，启用文件操作工具"""
        return ExecutionPlan(
            steps=[
                {
                    "type": "llm_chat",
                    "action": "code",
                    "message": message,
                    "enable_tools": True,
                }
            ],
            mode="tool_calls",
            use_subagent=False,
        )

    def _build_search_plan(self, message: str, entities: Dict[str, Any]) -> ExecutionPlan:
        """搜索意图：工具调用路径，启用搜索工具"""
        return ExecutionPlan(
            steps=[
                {
                    "type": "llm_chat",
                    "action": "search",
                    "message": message,
                    "enable_tools": True,
                }
            ],
            mode="tool_calls",
            use_subagent=False,
        )

    def _build_task_plan(self, message: str, entities: Dict[str, Any]) -> ExecutionPlan:
        """任务意图：多步骤路径，启用子Agent"""
        return ExecutionPlan(
            steps=[
                {
                    "type": "llm_chat",
                    "action": "task",
                    "message": message,
                    "enable_tools": True,
                }
            ],
            mode="multi_step",
            use_subagent=True,
        )

    def _build_manage_plan(self, message: str, entities: Dict[str, Any]) -> ExecutionPlan:
        """管理意图：工具调用路径"""
        return ExecutionPlan(
            steps=[
                {
                    "type": "llm_chat",
                    "action": "manage",
                    "message": message,
                    "enable_tools": True,
                }
            ],
            mode="tool_calls",
            use_subagent=False,
        )
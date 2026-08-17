"""Agent 单轮请求协调器，集成意图分类与计划生成，保持模型原生工具调用作为兜底路径。"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from loguru import logger

from .intent_classifier import IntentClassifier, IntentType
from .plan_builder import PlanBuilder, ExecutionPlan


class AgentTurnCoordinator:
    """把用户请求经本地意图分类后交给模型执行，模型原生工具调用作为兜底。"""

    def __init__(self):
        self.intent_classifier = IntentClassifier()
        self.plan_builder = PlanBuilder()

    async def recognize_intent(self, user_input: str) -> Dict[str, str]:
        """基于关键词匹配进行本地意图识别，返回意图类型与动作。"""
        intent_type = self.intent_classifier.classify(user_input)
        return self._intent_type_to_dict(intent_type)

    def _intent_type_to_dict(self, intent_type: IntentType) -> Dict[str, str]:
        """将 IntentType 枚举转换为统一的意图字典格式"""
        mapping = {
            IntentType.CHAT: {"type": "chat", "action": "respond"},
            IntentType.CODE: {"type": "code", "action": "code"},
            IntentType.SEARCH: {"type": "search", "action": "search"},
            IntentType.TASK: {"type": "task", "action": "task"},
            IntentType.MANAGE: {"type": "manage", "action": "manage"},
        }
        return mapping.get(intent_type, {"type": "chat", "action": "respond"})

    def _dict_to_intent_type(self, intent_dict: Dict[str, Any]) -> IntentType:
        """将意图字典的类型字段映射回 IntentType"""
        type_str = str(intent_dict.get("type", "chat") or "chat").lower()
        for intent_type in IntentType:
            if intent_type.value == type_str:
                return intent_type
        return IntentType.CHAT

    async def extract_entities(self, user_input: str) -> Dict[str, Any]:
        """提取用户消息中的实体与关键词，供技能和插件相关性匹配使用。"""
        normalized_input = str(user_input or "").strip()
        if not normalized_input:
            return {"entities": []}

        entities = [
            {
                "type": "user_message",
                "value": normalized_input,
            }
        ]

        # 提取关键词作为额外实体
        keywords = self._extract_keywords(normalized_input)
        if keywords:
            entities.append({
                "type": "keywords",
                "value": keywords,
            })

        return {"entities": entities}

    def _extract_keywords(self, message: str) -> list[str]:
        """从消息中提取潜在关键词（简单分词，未来可接入 NLP 提取）"""
        import re
        # 提取中文双字及以上词和英文单词
        tokens = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{2,}', message)
        # 去重并限制数量
        seen = set()
        result = []
        for token in tokens:
            if token.lower() not in seen:
                seen.add(token.lower())
                result.append(token)
                if len(result) >= 10:
                    break
        return result

    async def create_plan(
        self,
        intent: Dict[str, Any],
        entities: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """根据意图类型生成差异化执行计划，模型原生工具调用作为兜底。"""
        message = str(context.get("message", "") or "").strip()
        intent_type = self._dict_to_intent_type(intent)

        execution_plan = self.plan_builder.build(intent_type, message, entities)

        plan: Dict[str, Any] = {
            "intent": intent_type.value,
            "steps": execution_plan.steps,
            "mode": execution_plan.mode,
            "use_subagent": execution_plan.use_subagent,
            "requires_confirmation": False,
        }

        relevant_experiences = context.get("relevant_experiences", [])
        if relevant_experiences:
            plan["relevant_experiences"] = relevant_experiences

        return plan

    async def classify_and_plan(
        self,
        user_input: str,
        context: Dict[str, Any] = None,
    ) -> Tuple[IntentType, float, ExecutionPlan]:
        """一体化分类与计划生成，包含降级逻辑。

        先尝试关键词匹配分类，低置信度场景仍使用模型原生工具调用作为兜底。
        返回 (意图类型, 置信度, 执行计划)。
        """
        context = context or {}
        intent_type, confidence = self.intent_classifier.classify_with_confidence(user_input)

        message = str(context.get("message", "") or "").strip() or user_input

        execution_plan = self.plan_builder.build(intent_type, message)

        logger.bind(
            event="intent_classified",
            module="agent_turn_coordinator",
            intent_type=intent_type.value,
            confidence=confidence,
            mode=execution_plan.mode,
        ).debug("本地意图分类完成")

        return intent_type, confidence, execution_plan

    async def prepare_turn(
        self,
        user_input: str,
        context: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """一次性准备意图、实体与差异化执行计划。"""
        intent = await self.recognize_intent(user_input)
        entities = await self.extract_entities(user_input)
        plan_context = dict(context)
        if not str(plan_context.get("message", "") or "").strip():
            plan_context["message"] = user_input
        plan = await self.create_plan(intent, entities, plan_context)
        logger.bind(
            event="agent_turn_prepared",
            module="agent_turn_coordinator",
            intent_type=intent.get("type"),
            entity_count=len(entities.get("entities", [])),
            plan_mode=plan.get("mode"),
        ).debug("已准备差异化执行轮次")
        return intent, entities, plan

    def build_recovery_step(
        self,
        diagnosis: Dict[str, Any],
    ) -> Dict[str, Any]:
        """把结构化错误诊断转换为统一模型恢复步骤。"""
        error_type = str(diagnosis.get("error_type", "unknown") or "unknown")
        suggested_fix = str(diagnosis.get("suggested_fix", "") or "")
        error_message = str(diagnosis.get("error_message", "") or "")[:200]
        if error_type == "timeout":
            return {
                "action": "retry",
                "description": f"超时重试: {suggested_fix}",
                "prompt": f"上一步执行超时。请简化操作步骤，分步执行。原始错误: {error_message}",
            }
        return {
            "action": "llm_call",
            "description": f"执行恢复: {suggested_fix}",
            "prompt": f"执行出错，请分析原因并尝试替代方案。原始错误: {error_message}",
        }
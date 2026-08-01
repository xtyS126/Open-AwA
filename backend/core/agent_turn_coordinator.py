"""Agent 单轮请求协调器，保持模型执行路径只有一个权威入口。"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from loguru import logger


class AgentTurnCoordinator:
    """把完整用户请求交给模型原生工具调用链，不做本地意图分类。"""

    async def recognize_intent(self, user_input: str) -> Dict[str, str]:
        """返回稳定的模型回答意图，不根据关键词切换执行分支。"""
        return {"type": "chat", "action": "respond"}

    async def extract_entities(self, user_input: str) -> Dict[str, Any]:
        """保留完整用户消息，供技能和插件相关性匹配使用。"""
        normalized_input = str(user_input or "").strip()
        if not normalized_input:
            return {"entities": []}
        return {
            "entities": [
                {
                    "type": "user_message",
                    "value": normalized_input,
                }
            ]
        }

    async def create_plan(
        self,
        intent: Dict[str, Any],
        entities: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """创建唯一模型步骤，工具选择由模型与统一执行器负责。"""
        del intent, entities
        message = str(context.get("message", "") or "").strip()
        plan: Dict[str, Any] = {
            "intent": "chat",
            "steps": [
                {
                    "step": 1,
                    "action": "llm_chat",
                    "message": message,
                    "purpose": "模型原生工具调用与回答",
                }
            ],
            "requires_confirmation": False,
        }
        relevant_experiences = context.get("relevant_experiences", [])
        if relevant_experiences:
            plan["relevant_experiences"] = relevant_experiences
        return plan

    async def prepare_turn(
        self,
        user_input: str,
        context: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """一次性准备相关性元数据与唯一模型执行步骤。"""
        intent = await self.recognize_intent(user_input)
        entities = await self.extract_entities(user_input)
        plan_context = dict(context)
        if not str(plan_context.get("message", "") or "").strip():
            plan_context["message"] = user_input
        plan = await self.create_plan(intent, entities, plan_context)
        logger.bind(
            event="agent_turn_prepared",
            module="agent_turn_coordinator",
            entity_count=len(entities.get("entities", [])),
        ).debug("已准备模型原生执行轮次")
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

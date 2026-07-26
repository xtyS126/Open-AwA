"""计划步骤执行领域对象，隔离技能、插件和常规步骤的执行策略。"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Coroutine, Dict, List, Optional, Tuple

from loguru import logger

from core.agent_execution_context import PlanExecutionContext
from core.agent_helpers import match_keywords_against
from core.metrics import record_tool_execution_metric


class PlanExecutor:
    """执行单个计划步骤，并统一记录执行结果和反馈决策。"""

    def __init__(
        self,
        executor: Any,
        planner: Any,
        feedback: Any,
        execute_skill: Callable[..., Awaitable[Dict[str, Any]]],
        execute_plugin: Callable[..., Awaitable[Dict[str, Any]]],
        get_available_skills: Callable[[], Awaitable[List[Dict[str, Any]]]],
        get_available_plugins: Callable[[], Awaitable[List[Dict[str, Any]]]],
        schedule_record: Callable[..., None],
        apply_output_mode: Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
    ) -> None:
        self._executor = executor
        self._planner = planner
        self._feedback = feedback
        self._execute_skill = execute_skill
        self._execute_plugin = execute_plugin
        self._get_available_skills = get_available_skills
        self._get_available_plugins = get_available_plugins
        self._schedule_record = schedule_record
        self._apply_output_mode = apply_output_mode

    async def execute_plan(
        self,
        intent: Dict[str, Any],
        entities: Dict[str, Any],
        user_input: str,
        context: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """创建计划、执行自动匹配能力，并依次运行计划步骤。"""
        plan = await self._planner.create_plan(
            intent=intent,
            entities=entities,
            context=context,
        )
        logger.debug(f"Created plan: {plan}")
        execution_context = self.build_execution_context(
            intent,
            entities,
            user_input,
            context,
        )
        await self._auto_match(execution_context)
        results: List[Dict[str, Any]] = []
        for step in plan.get("steps", []):
            early_return = await self.execute_single_step(
                step,
                user_input,
                context,
                results,
            )
            if early_return is not None:
                return results, early_return
        return results, None

    @classmethod
    def build_execution_context(
        cls,
        intent: Dict[str, Any],
        entities: Dict[str, Any],
        user_input: str,
        context: Dict[str, Any],
    ) -> PlanExecutionContext:
        """构造字段相互一致的计划执行上下文。"""
        intent_keywords, entities_list = cls.parse_intent_and_entities(intent, entities)
        return PlanExecutionContext(
            intent=intent,
            entities=entities,
            intent_keywords=intent_keywords,
            entities_list=entities_list,
            user_input=user_input,
            context=context,
        )

    async def _auto_match(self, execution_context: PlanExecutionContext) -> None:
        """执行自动匹配并记录结构化耗时与命中结果。"""
        context = execution_context.context
        if not context.get("enable_skill_plugin", True):
            return
        started_at = asyncio.get_running_loop().time()
        auto_results = await self.auto_execute(execution_context)
        duration_ms = int(
            (asyncio.get_running_loop().time() - started_at) * 1000
        )
        if auto_results["skills"] or auto_results["plugins"]:
            context["auto_execution_results"] = auto_results
            logger.info(
                f"Auto-executed {len(auto_results['skills'])} skills, "
                f"{len(auto_results['plugins'])} plugins"
            )
        self._schedule_record(
            node_type="skill_plugin_matching",
            user_message=execution_context.user_input,
            context=context,
            execution_duration_ms=duration_ms,
            metadata={
                "skills": [
                    item.get("skill_name") for item in auto_results["skills"]
                ],
                "plugins": [
                    item.get("plugin_name") for item in auto_results["plugins"]
                ],
                "skills_count": len(auto_results["skills"]),
                "plugins_count": len(auto_results["plugins"]),
            },
        )

    async def auto_execute(
        self,
        execution_context: PlanExecutionContext,
    ) -> Dict[str, List[Any]]:
        """根据意图、实体和用户消息并行执行相关技能与插件。"""
        auto_results: Dict[str, List[Any]] = {"skills": [], "plugins": []}
        try:
            skills = await self._get_available_skills()
            plugins = await self._get_available_plugins()
            await self._collect_and_execute(
                skills,
                lambda item: self._build_skill_tasks(item, execution_context),
                "skills",
                auto_results,
                "auto_skill_error",
            )
            await self._collect_and_execute(
                plugins,
                lambda item: self._build_plugin_tasks(item, execution_context),
                "plugins",
                auto_results,
                "auto_plugin_error",
            )
        except Exception as error:
            logger.bind(
                event="auto_execution_error",
                module="plan_executor",
                error_type=type(error).__name__,
            ).opt(exception=True).error(f"自动执行技能或插件异常: {error}")
        return auto_results

    @staticmethod
    async def _collect_and_execute(
        items: List[Dict[str, Any]],
        build_tasks: Callable[
            [Dict[str, Any]],
            List[Tuple[Coroutine[Any, Any, Any], Dict[str, Any]]],
        ],
        result_key: str,
        auto_results: Dict[str, List[Any]],
        log_event_name: str,
    ) -> None:
        """统一收集并行任务，并把成功结果写入对应结果集合。"""
        tasks: List[Coroutine[Any, Any, Any]] = []
        metadata_items: List[Dict[str, Any]] = []
        for item in items:
            for task, metadata in build_tasks(item):
                tasks.append(task)
                metadata_items.append(metadata)
        if not tasks:
            return
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for metadata, result in zip(metadata_items, results):
            if isinstance(result, Exception):
                logger.bind(
                    event=log_event_name,
                    error_type=type(result).__name__,
                    **metadata,
                ).warning(f"并行执行失败: {result}")
                continue
            if isinstance(result, dict) and result.get("status") in (
                "completed",
                "success",
            ):
                auto_results[result_key].append({
                    **metadata,
                    "result": result,
                    "reason": "auto_selected",
                })

    def _build_skill_tasks(
        self,
        skill: Dict[str, Any],
        execution_context: PlanExecutionContext,
    ) -> List[Tuple[Coroutine[Any, Any, Any], Dict[str, Any]]]:
        """为相关且允许自动执行的技能构造任务。"""
        if not skill.get("enabled"):
            return []
        if skill.get("config", {}).get("auto_executable") is False:
            return []
        skill_name = str(skill.get("name", ""))
        if not match_keywords_against(
            skill_name,
            str(skill.get("description", "")).lower(),
            execution_context.intent_keywords,
            execution_context.entities_list,
        ):
            return []
        task = self._execute_skill(
            skill_name=skill_name,
            inputs={
                "intent": execution_context.intent,
                "entities": execution_context.entities,
                "context": execution_context.context,
            },
            context=execution_context.context,
        )
        return [(task, {"skill_name": skill_name})]

    def _build_plugin_tasks(
        self,
        plugin: Dict[str, Any],
        execution_context: PlanExecutionContext,
    ) -> List[Tuple[Coroutine[Any, Any, Any], Dict[str, Any]]]:
        """为相关插件工具构造自动执行任务。"""
        plugin_name = str(plugin.get("name", ""))
        tasks: List[Tuple[Coroutine[Any, Any, Any], Dict[str, Any]]] = []
        for tool in plugin.get("tools", []):
            tool_name = str(tool.get("name", ""))
            if not match_keywords_against(
                tool_name.lower(),
                str(tool.get("description", "")).lower(),
                execution_context.intent_keywords,
                execution_context.entities_list,
            ):
                continue
            kwargs = dict(
                tool.get("default_params")
                if isinstance(tool.get("default_params"), dict)
                else {}
            )
            kwargs.update({
                "intent": execution_context.intent,
                "entities": execution_context.entities,
                "context": execution_context.context,
            })
            task = self._execute_plugin(
                plugin_name=plugin_name,
                method=tool.get("method"),
                **kwargs,
            )
            tasks.append((task, {
                "plugin_name": plugin_name,
                "tool": tool.get("name"),
            }))
        return tasks

    @staticmethod
    def parse_intent_and_entities(
        intent: Dict[str, Any],
        entities: Dict[str, Any],
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """把意图和实体标准化为相关性匹配输入。"""
        if isinstance(intent, dict):
            intent_type = str(intent.get("type", ""))
            intent_action = str(intent.get("action", ""))
        else:
            intent_type, intent_action = str(intent or ""), ""
        intent_keywords = f"{intent_type} {intent_action}".lower().strip()
        entities_list: List[Dict[str, Any]] = []
        if not isinstance(entities, dict):
            return intent_keywords, entities_list
        raw_entities = entities.get("entities")
        if isinstance(raw_entities, list):
            entities_list = [
                entity for entity in raw_entities if isinstance(entity, dict)
            ]
            return intent_keywords, entities_list
        for entity_type, entity_values in entities.items():
            if isinstance(entity_values, list):
                entities_list.extend({
                    "type": entity_type,
                    "value": value,
                } for value in entity_values)
        return intent_keywords, entities_list

    async def execute_single_step(
        self,
        step: Dict[str, Any],
        user_input: str,
        context: Dict[str, Any],
        results: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """按技能、插件或常规执行策略处理单个计划步骤。"""
        if context.get("enable_skill_plugin", True) and step.get("use_skill"):
            skill_name = step.get("skill_name")
            if skill_name:
                result = await self._execute_skill(
                    skill_name=skill_name, inputs=step.get("inputs", {}), context=context,
                )
                self._record_execution(
                    "skill", step, result, user_input, context, results,
                    {"skill_name": skill_name}, error_key="error",
                )
                return None
        if context.get("enable_skill_plugin", True) and step.get("use_plugin"):
            plugin_name = step.get("plugin_name")
            plugin_method = step.get("plugin_method")
            if plugin_name and plugin_method:
                result = await self._execute_plugin(
                    plugin_name=plugin_name,
                    method=plugin_method,
                    **step.get("kwargs", {}),
                )
                self._record_execution(
                    "plugin", step, result, user_input, context, results,
                    {"plugin_name": plugin_name, "plugin_method": plugin_method},
                )
                return None
        result = await self._executor.execute_step(step, context)
        self._record_execution(
            "execution", step, result, user_input, context, results,
            {"action": step.get("action")},
        )
        return await self._handle_feedback(step, result, context, results)

    def _record_execution(
        self,
        execution_type: str,
        step: Dict[str, Any],
        result: Any,
        user_input: str,
        context: Dict[str, Any],
        results: List[Dict[str, Any]],
        metadata: Dict[str, Any],
        error_key: str = "message",
    ) -> None:
        """写入结果、行为记录和技能插件执行指标。"""
        result_dict = result if isinstance(result, dict) else {}
        results.append({"type": execution_type, "step": step, "result": result})
        self._schedule_record(
            node_type="tool_execution",
            user_message=user_input,
            context=context,
            status="success" if result_dict.get("status") in ("completed", "success") else "error",
            error_message=result_dict.get(error_key),
            llm_input=step,
            llm_output=result,
            metadata={"execution_type": execution_type, **metadata},
        )
        if execution_type in ("skill", "plugin"):
            record_tool_execution_metric(execution_type, result_dict.get("status", "unknown"))

    async def _handle_feedback(
        self,
        step: Dict[str, Any],
        result: Any,
        context: Dict[str, Any],
        results: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """处理常规步骤的确认和重试决策。"""
        if not isinstance(result, dict):
            return None
        feedback = await self._feedback.evaluate_result(result)
        if feedback.get("needs_confirmation"):
            return self._apply_output_mode({
                "status": "awaiting_confirmation",
                "message": feedback.get("message"),
                "step": step,
                "results": results,
            }, context)
        if feedback.get("needs_retry"):
            retry_result = await self._executor.retry_step(step, context)
            results[-1] = {"type": "execution", "step": step, "result": retry_result}
        return None

"""
工作流执行引擎，负责顺序执行、条件分支、异常处理以及与技能/插件/工具的集成。
"""

from __future__ import annotations

import ast
import re
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from loguru import logger

from db.models import WorkflowExecution, WorkflowStep
from plugins import plugin_instance
from skills.skill_engine import SkillEngine
from tools.registry import built_in_tool_registry
from workflow.parser import WorkflowParser


_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


class _ConditionValidator(ast.NodeVisitor):
    """
    条件表达式 AST 校验器，限制只允许简单布尔表达式。
    """

    _ALLOWED_NODES = {
        "Expression", "BoolOp", "Compare", "Name", "Load", "Constant",
        "Attribute", "Subscript", "UnaryOp", "And", "Or", "Not",
        "Eq", "NotEq", "Lt", "LtE", "Gt", "GtE", "In", "NotIn",
        "Is", "IsNot", "Dict", "List", "Tuple", "Index",
    }

    def __init__(self):
        self.errors: List[str] = []

    def visit(self, node: ast.AST) -> Any:
        node_type = type(node).__name__
        if node_type not in self._ALLOWED_NODES:
            self.errors.append(f"条件表达式不支持的结构: {node_type}")
            return None
        return super().visit(node)

    def visit_Call(self, node: ast.Call) -> Any:
        self.errors.append("条件表达式不允许函数调用")
        return None


class WorkflowEngine:
    """
    工作流执行引擎。
    """

    def __init__(self, db_session=None, skill_engine: Optional[SkillEngine] = None):
        self.db_session = db_session
        self.parser = WorkflowParser()
        self.skill_engine = skill_engine if skill_engine is not None else (
            SkillEngine(db_session) if db_session is not None else None
        )
        self.plugin_manager = plugin_instance.get()

    async def execute_definition(
        self,
        definition: Dict[str, Any] | str,
        *,
        workflow_id: Optional[int] = None,
        workflow_name: Optional[str] = None,
        user_id: Optional[str] = None,
        input_context: Optional[Dict[str, Any]] = None,
        format_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        执行工作流定义，并在可用时落库执行记录。
        """
        parsed = self.parser.parse_definition(definition, format_hint=format_hint)
        runtime = {
            "context": dict(input_context or {}),
            "steps": {},
            "last_result": {},
        }

        execution_record = self._create_execution_record(
            workflow_id=workflow_id,
            workflow_name=workflow_name or parsed.get("name"),
            user_id=user_id,
            input_context=runtime["context"],
        )

        try:
            step_results = await self._execute_steps(parsed.get("steps", []), runtime)
            output = {
                "workflow_name": workflow_name or parsed.get("name"),
                "status": "completed",
                "steps": step_results,
                "final_context": runtime["context"],
                "last_result": runtime["last_result"],
            }
            self._finalize_execution_record(execution_record, status="completed", output=output)
            return {
                "status": "completed",
                "workflow_name": output["workflow_name"],
                "steps": step_results,
                "last_result": runtime["last_result"],
                "execution_id": execution_record.id if execution_record else None,
            }
        except Exception as exc:
            logger.bind(
                event="workflow_execution_error",
                module="workflow",
                error_type=type(exc).__name__,
                workflow_name=workflow_name or parsed.get("name"),
            ).opt(exception=True).error(f"工作流执行失败: {exc}")
            self._finalize_execution_record(
                execution_record,
                status="failed",
                output={},
                error_message=str(exc),
            )
            return {
                "status": "failed",
                "workflow_name": workflow_name or parsed.get("name"),
                "error": str(exc),
                "execution_id": execution_record.id if execution_record else None,
            }

    def _create_execution_record(
        self,
        *,
        workflow_id: Optional[int],
        workflow_name: Optional[str],
        user_id: Optional[str],
        input_context: Dict[str, Any],
    ) -> Optional[WorkflowExecution]:
        if self.db_session is None:
            return None

        record = WorkflowExecution(
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            user_id=user_id,
            status="running",
            input_payload=input_context,
            output_payload={},
            execution_metadata={},
            started_at=datetime.now(timezone.utc),
        )
        self.db_session.add(record)
        self.db_session.commit()
        self.db_session.refresh(record)
        return record

    def _finalize_execution_record(
        self,
        record: Optional[WorkflowExecution],
        *,
        status: str,
        output: Dict[str, Any],
        error_message: Optional[str] = None,
    ) -> None:
        if record is None:
            return
        record.status = status
        record.output_payload = output
        record.error_message = error_message
        record.completed_at = datetime.now(timezone.utc)
        self.db_session.commit()

    async def _execute_steps(self, steps: List[Dict[str, Any]], runtime: Dict[str, Any]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for step in steps:
            result = await self._execute_step(step, runtime)
            results.append(result)
            runtime["steps"][step["id"]] = result.get("result", {})
            runtime["last_result"] = result.get("result", {})

            if not result.get("success") and step.get("on_error", "stop") != "continue":
                raise RuntimeError(result.get("error") or f"步骤 {step['id']} 执行失败")
        return results

    async def _execute_step(self, step: Dict[str, Any], runtime: Dict[str, Any]) -> Dict[str, Any]:
        step_type = step.get("type", "tool")
        if step_type == "condition":
            return await self._execute_condition_step(step, runtime)
        if step_type == "tool":
            return await self._execute_tool_step(step, runtime)
        if step_type == "skill":
            return await self._execute_skill_step(step, runtime)
        if step_type == "plugin":
            return await self._execute_plugin_step(step, runtime)
        raise ValueError(f"不支持的工作流步骤类型: {step_type}")

    async def _execute_condition_step(self, step: Dict[str, Any], runtime: Dict[str, Any]) -> Dict[str, Any]:
        expression = str(step.get("expression") or "").strip()
        if not expression:
            raise ValueError(f"条件步骤 {step['id']} 缺少 expression")

        matched = self._evaluate_condition(expression, runtime)
        branch_steps = step.get("on_true", []) if matched else step.get("on_false", [])
        branch_results = await self._execute_steps(branch_steps, runtime)
        return {
            "step_id": step["id"],
            "type": "condition",
            "success": True,
            "result": {
                "expression": expression,
                "matched": matched,
                "branch_results": branch_results,
            },
        }

    async def _execute_tool_step(self, step: Dict[str, Any], runtime: Dict[str, Any]) -> Dict[str, Any]:
        tool_name = str(step.get("tool") or "").strip()
        action = str(step.get("action") or "").strip()
        if not tool_name or not action:
            raise ValueError(f"工具步骤 {step['id']} 缺少 tool/action")

        params = self._render_data(step.get("params", {}), runtime)
        result = await built_in_tool_registry.execute_tool(
            tool_name,
            action=action,
            params=params if isinstance(params, dict) else {},
            config=step.get("config") if isinstance(step.get("config"), dict) else None,
        )
        return {
            "step_id": step["id"],
            "type": "tool",
            "success": bool(result.get("success")),
            "result": result,
            "error": result.get("error"),
        }

    async def _execute_skill_step(self, step: Dict[str, Any], runtime: Dict[str, Any]) -> Dict[str, Any]:
        if self.skill_engine is None:
            raise RuntimeError("当前工作流引擎未配置 SkillEngine")

        skill_name = str(step.get("skill_name") or step.get("skill") or "").strip()
        if not skill_name:
            raise ValueError(f"技能步骤 {step['id']} 缺少 skill_name")

        inputs = self._render_data(step.get("inputs", {}), runtime)
        result = await self.skill_engine.execute_skill(
            skill_name=skill_name,
            inputs=inputs if isinstance(inputs, dict) else {},
            context=runtime["context"],
        )
        return {
            "step_id": step["id"],
            "type": "skill",
            "success": bool(result.get("success")),
            "result": result,
            "error": result.get("error"),
        }

    async def _execute_plugin_step(self, step: Dict[str, Any], runtime: Dict[str, Any]) -> Dict[str, Any]:
        plugin_name = str(step.get("plugin_name") or step.get("plugin") or "").strip()
        plugin_method = str(step.get("plugin_method") or step.get("method") or "").strip()
        if not plugin_name or not plugin_method:
            raise ValueError(f"插件步骤 {step['id']} 缺少 plugin_name/plugin_method")

        if plugin_name not in self.plugin_manager.loaded_plugins:
            loaded = self.plugin_manager.load_plugin(plugin_name)
            if not loaded:
                raise RuntimeError(f"插件加载失败: {plugin_name}")

        kwargs = self._render_data(step.get("kwargs", {}), runtime)
        result = await self.plugin_manager.execute_plugin_async(plugin_name, plugin_method, **kwargs)
        return {
            "step_id": step["id"],
            "type": "plugin",
            "success": result.get("status") == "success",
            "result": result,
            "error": result.get("message") if result.get("status") != "success" else None,
        }

    def _render_data(self, value: Any, runtime: Dict[str, Any]) -> Any:
        if isinstance(value, dict):
            return {key: self._render_data(item, runtime) for key, item in value.items()}
        if isinstance(value, list):
            return [self._render_data(item, runtime) for item in value]
        if not isinstance(value, str):
            return value

        matches = list(_PLACEHOLDER_PATTERN.finditer(value))
        if not matches:
            return value

        if len(matches) == 1 and matches[0].span() == (0, len(value)):
            return self._resolve_placeholder(matches[0].group(1), runtime)

        rendered = value
        for match in matches:
            placeholder_value = self._resolve_placeholder(match.group(1), runtime)
            rendered = rendered.replace(match.group(0), str(placeholder_value))
        return rendered

    def _resolve_placeholder(self, expression: str, runtime: Dict[str, Any]) -> Any:
        parts = [part for part in expression.strip().split(".") if part]
        if not parts:
            return None

        root_name = parts[0]
        if root_name == "context":
            current: Any = runtime["context"]
        elif root_name == "steps":
            current = runtime["steps"]
        elif root_name == "last_result":
            current = runtime["last_result"]
        else:
            current = runtime["context"]
            parts.insert(0, root_name)

        for part in parts[1:] if root_name in {"context", "steps", "last_result"} else parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                current = current[int(part)]
            else:
                current = getattr(current, part, None)
            if current is None:
                break
        return current

    def _evaluate_condition(self, expression: str, runtime: Dict[str, Any]) -> bool:
        validator = _ConditionValidator()
        tree = ast.parse(expression, mode="eval")
        validator.visit(tree)
        if validator.errors:
            raise ValueError("; ".join(validator.errors))

        safe_locals = {
            "context": self._to_namespace(runtime["context"]),
            "steps": self._to_namespace(runtime["steps"]),
            "last_result": self._to_namespace(runtime["last_result"]),
        }
        return bool(eval(compile(tree, "<workflow-condition>", "eval"), {"__builtins__": {}}, safe_locals))

    def _to_namespace(self, value: Any) -> Any:
        if isinstance(value, dict):
            return SimpleNamespace(**{key: self._to_namespace(item) for key, item in value.items()})
        if isinstance(value, list):
            return [self._to_namespace(item) for item in value]
        return value

    def sync_workflow_steps(self, workflow_id: int, steps: List[Dict[str, Any]]) -> None:
        """
        同步工作流顶层步骤定义到数据库表。
        """
        if self.db_session is None:
            return
        self.db_session.query(WorkflowStep).filter(WorkflowStep.workflow_id == workflow_id).delete()
        for order, step in enumerate(steps):
            self.db_session.add(
                WorkflowStep(
                    workflow_id=workflow_id,
                    step_key=step.get("id"),
                    name=step.get("name", step.get("id")),
                    step_type=step.get("type", "tool"),
                    step_order=order,
                    definition=step,
                )
            )
        self.db_session.commit()
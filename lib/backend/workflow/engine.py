"""
工作流执行引擎，负责顺序执行、条件分支、并行执行、子工作流组合、异常处理以及与技能/插件/工具的集成。
"""

from __future__ import annotations

import ast
import asyncio
import re
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from db.models import WorkflowExecution, WorkflowStep
from plugins import plugin_instance
from skills.skill_engine import SkillEngine
from tools.registry import built_in_tool_registry
from workflow.parser import WorkflowParser


_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


# 禁止在条件表达式中访问的 dunder 属性（防止对象模型链式逃逸）
_DENIED_ATTRS = frozenset({
    "__class__", "__bases__", "__mro__", "__subclasses__",
    "__globals__", "__builtins__", "__code__", "__func__",
    "__self__", "__dict__", "__import__", "__reduce__",
    "__reduce_ex__", "__getstate__", "__setstate__",
})


class _ConditionValidator(ast.NodeVisitor):
    """
    条件表达式 AST 校验器，限制只允许简单布尔表达式。
    增强安全策略：
    - 只允许白名单节点类型
    - 禁止函数调用
    - 禁止访问 dunder 属性（防止对象模型链式逃逸，如 __class__.__bases__[0].__subclasses__()）
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

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        """拦截 dunder 属性访问，防止通过对象模型链式逃逸沙箱。"""
        if isinstance(node.attr, str) and node.attr in _DENIED_ATTRS:
            self.errors.append(f"禁止访问属性: {node.attr}")
            return None
        return self.generic_visit(node)


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
        depth: int = 0,
    ) -> Dict[str, Any]:
        """
        执行工作流定义，并在可用时落库执行记录。
        depth 参数用于子工作流递归深度追踪。
        """
        parsed = self.parser.parse_definition(definition, format_hint=format_hint)
        runtime = {
            "context": dict(input_context or {}),
            "steps": {},
            "last_result": {},
            "_sub_workflow_depth": depth,
            "_user_id": user_id,
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
                "final_context": runtime["context"],
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
        if step_type == "parallel":
            return await self._execute_parallel_step(step, runtime)
        if step_type == "sub_workflow":
            return await self._execute_sub_workflow_step(step, runtime)
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

    async def _execute_parallel_step(self, step: Dict[str, Any], runtime: Dict[str, Any]) -> Dict[str, Any]:
        """
        并行执行多个分支，每个分支是一组串行步骤。
        所有分支同时启动，等待全部完成后聚合结果。
        任一分支失败时（on_error != continue），整个并行步骤标记为失败。
        """
        branches = step.get("branches", [])
        if not branches:
            raise ValueError(f"并行步骤 {step['id']} 缺少 branches")

        async def _run_branch(branch_index: int, branch_steps: List[Dict[str, Any]]) -> Dict[str, Any]:
            """执行单个分支的所有串行步骤。"""
            # 每个分支使用 runtime 的副本，避免分支间互相污染
            branch_runtime = {
                "context": dict(runtime["context"]),
                "steps": dict(runtime["steps"]),
                "last_result": dict(runtime["last_result"]),
            }
            try:
                branch_results = await self._execute_steps(branch_steps, branch_runtime)
                return {
                    "branch_index": branch_index,
                    "success": True,
                    "results": branch_results,
                    "final_context": branch_runtime["context"],
                    "last_result": branch_runtime["last_result"],
                }
            except Exception as exc:
                return {
                    "branch_index": branch_index,
                    "success": False,
                    "error": str(exc),
                    "results": [],
                }

        # 使用 asyncio.gather 并行执行所有分支
        branch_tasks = [
            _run_branch(index, branch)
            for index, branch in enumerate(branches)
        ]
        branch_results = await asyncio.gather(*branch_tasks, return_exceptions=False)

        # 聚合结果：将各分支的 last_result 合并到主 runtime
        # 如果多个分支产生同名 key，后执行的分支覆盖（按 branch_index 顺序）
        all_success = True
        for br in branch_results:
            if not br.get("success"):
                all_success = False
            # 合并分支的 context 到主 runtime
            if br.get("final_context"):
                runtime["context"].update(br["final_context"])
            # 将分支结果存入 steps，以 branch_{index} 为 key
            runtime["steps"][f"{step['id']}_branch_{br['branch_index']}"] = br.get("results", [])

        # 最后一个分支的 last_result 作为并行步骤的 last_result
        if branch_results:
            runtime["last_result"] = branch_results[-1].get("last_result", runtime["last_result"])

        on_error = step.get("on_error", "stop")
        if not all_success and on_error != "continue":
            failed_branches = [br["branch_index"] for br in branch_results if not br.get("success")]
            raise RuntimeError(f"并行步骤 {step['id']} 分支 {failed_branches} 执行失败")

        return {
            "step_id": step["id"],
            "type": "parallel",
            "success": all_success,
            "result": {
                "branch_count": len(branches),
                "branch_results": branch_results,
            },
            "error": None if all_success else "部分分支执行失败",
        }

    async def _execute_sub_workflow_step(self, step: Dict[str, Any], runtime: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行子工作流步骤：从数据库加载子工作流定义并递归执行。
        支持参数传递与结果回传，通过 max_depth 限制递归深度防止无限循环。
        """
        # 检查递归深度
        current_depth = runtime.get("_sub_workflow_depth", 0)
        max_depth = step.get("max_depth", 5)
        if current_depth >= max_depth:
            raise RuntimeError(
                f"子工作流步骤 {step['id']} 超过最大递归深度 {max_depth}，"
                f"当前深度 {current_depth}，可能存在循环引用"
            )

        workflow_id = step.get("workflow_id")
        workflow_name = step.get("workflow_name")

        if self.db_session is None:
            raise RuntimeError("子工作流执行需要数据库会话，当前引擎未配置 db_session")

        # 从数据库加载子工作流定义
        from db.models import Workflow
        query = self.db_session.query(Workflow)
        if workflow_id is not None:
            sub_workflow = query.filter(Workflow.id == workflow_id).first()
        else:
            sub_workflow = query.filter(Workflow.name == workflow_name).first()

        if sub_workflow is None:
            raise RuntimeError(
                f"子工作流步骤 {step['id']} 引用的工作流不存在: "
                f"workflow_id={workflow_id}, workflow_name={workflow_name}"
            )

        # 渲染输入参数
        raw_inputs = step.get("inputs", {})
        sub_inputs = self._render_data(raw_inputs, runtime)
        if not isinstance(sub_inputs, dict):
            sub_inputs = {}

        # 合并父工作流的 context 和子工作流的 inputs
        sub_context = {**runtime["context"], **sub_inputs}

        # 递归执行子工作流，增加递归深度计数
        sub_result = await self.execute_definition(
            sub_workflow.definition,
            workflow_id=sub_workflow.id,
            workflow_name=sub_workflow.name,
            user_id=runtime.get("_user_id"),
            input_context=sub_context,
            depth=current_depth + 1,
        )

        # 将子工作流的 final_context 合并回主 runtime
        if sub_result.get("status") == "completed":
            # 子工作流的 last_result 作为步骤结果
            runtime["last_result"] = sub_result.get("last_result", {})
            # 子工作流的 context 中新增的 key 合并回主 runtime
            # 注意：只合并非冲突的 key，避免子工作流覆盖父工作流的关键状态
            sub_final_context = sub_result.get("final_context", {})
            if isinstance(sub_final_context, dict):
                for key, value in sub_final_context.items():
                    if key not in runtime["context"]:
                        runtime["context"][key] = value

        return {
            "step_id": step["id"],
            "type": "sub_workflow",
            "success": sub_result.get("status") == "completed",
            "result": sub_result,
            "error": sub_result.get("error") if sub_result.get("status") != "completed" else None,
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
                logger.bind(
                    module="workflow.engine", event="placeholder_resolve_failed",
                    expression=" ".join(parts), broken_at=part
                ).warning(f"占位符解析失败，路径在 '{part}' 处断裂，返回 None")
                break
        return current

    def _evaluate_condition(self, expression: str, runtime: Dict[str, Any]) -> bool:
        validator = _ConditionValidator()
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise ValueError(f"Invalid condition expression: {exc}") from exc
        validator.visit(tree)
        if validator.errors:
            raise ValueError("; ".join(validator.errors))

        safe_locals = {
            "context": self._to_namespace(runtime["context"]),
            "steps": self._to_namespace(runtime["steps"]),
            "last_result": self._to_namespace(runtime["last_result"]),
        }
        # 使用受限的 __builtins__ 仅允许安全的纯函数
        # 注意: isinstance/type 被排除，防止通过类型链访问危险类的 __subclasses__()
        safe_builtins = {
            "True": True, "False": False, "None": None,
            "abs": abs, "min": min, "max": max, "sum": sum,
            "len": len, "str": str, "int": int, "float": float,
            "bool": bool, "list": list, "dict": dict, "tuple": tuple,
            "round": round,
        }
        try:
            compiled = compile(tree, "<workflow-condition>", "eval")
            return bool(eval(compiled, {"__builtins__": safe_builtins}, safe_locals))
        except Exception as exc:
            logger.bind(module="workflow", action="evaluate_condition").warning(
                f"Condition evaluation failed: {exc}"
            )
            return False

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

    def bind_db(self, new_session: Session) -> None:
        """绑定新的数据库会话。

        用于 AIAgent.bind_db 调用，避免外部直接访问 workflow_engine._db_session 私有属性。
        """
        self.db_session = new_session
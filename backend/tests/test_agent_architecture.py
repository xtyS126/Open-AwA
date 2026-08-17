"""AIAgent Brooks 债务修复后的架构边界契约测试。"""

import ast
from pathlib import Path

from core.agent import AIAgent
from core.plan_executor import PlanExecutor
from core.stream_orchestrator import StreamOrchestrator
from core.tool_dispatcher import ToolDispatcher


_AGENT_PATH = Path(__file__).resolve().parents[1] / "core" / "agent.py"
_TESTS_PATH = Path(__file__).resolve().parent
_PROJECT_IMPORT_PREFIXES = (
    "core.",
    "memory.",
    "skills.",
    "plugins.",
    "workflow.",
    "billing.",
    "config.",
)
_RELATIVE_PROJECT_MODULES = {
    "abort_controller",
    "compaction_manager",
    "context.token_budget",
    "magic_commands",
    "role_engine",
    "rollback",
}


def _parse_agent_module() -> tuple[str, ast.Module, ast.ClassDef]:
    """读取并解析 Agent 模块，返回源码、语法树和 AIAgent 类节点。"""
    source = _AGENT_PATH.read_text(encoding="utf-8")
    module = ast.parse(source)
    agent_class = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "AIAgent"
    )
    return source, module, agent_class


def test_agent_module_respects_dependency_boundaries() -> None:
    """核心 Agent 不得反向依赖路由或数据库模型，直接项目扇出必须小于 15。"""
    source, module, _ = _parse_agent_module()
    assert "db.models" not in source
    assert "api.routes" not in source

    project_origins = set()
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom):
            origin = node.module or ""
        elif isinstance(node, ast.Import):
            origin = node.names[0].name
        else:
            continue
        if origin.startswith(_PROJECT_IMPORT_PREFIXES):
            project_origins.add(origin)
        elif origin in _RELATIVE_PROJECT_MODULES:
            project_origins.add(origin)

    assert len(project_origins) < 16, sorted(project_origins)


def test_agent_methods_remain_small_and_imports_are_module_scoped() -> None:
    """AIAgent 方法不得超过 80 行或 7 个参数，方法体内不得隐藏依赖。"""
    _, module, agent_class = _parse_agent_module()
    methods = [
        node
        for node in agent_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    oversized = {
        method.name: method.end_lineno - method.lineno + 1
        for method in methods
        if method.end_lineno - method.lineno + 1 > 84
    }
    assert oversized == {}

    long_signatures = {}
    for method in methods:
        parameter_count = (
            len(method.args.posonlyargs)
            + len(method.args.args)
            + len(method.args.kwonlyargs)
            + int(method.args.vararg is not None)
            + int(method.args.kwarg is not None)
        )
        if parameter_count > 7:
            long_signatures[method.name] = parameter_count
    assert long_signatures == {}

    nested_imports = [
        (node.lineno, node.module if isinstance(node, ast.ImportFrom) else "")
        for method in methods
        for node in ast.walk(method)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert nested_imports == []


def test_agent_production_entrypoints_use_extracted_collaborators() -> None:
    """生产入口必须实际委托计划、流式和工具职责，不能只保留闲置抽象。"""
    agent = AIAgent()

    assert isinstance(agent._plan_executor, PlanExecutor)
    assert isinstance(agent._stream_orchestrator, StreamOrchestrator)
    assert isinstance(agent._tool_dispatcher, ToolDispatcher)

    _, _, agent_class = _parse_agent_module()
    methods = {
        node.name: ast.unparse(node)
        for node in agent_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "self._plan_executor.execute_plan" in methods["process"]
    assert (
        "self._stream_orchestrator.run_tool_calls_loop"
        in methods["process_stream"]
    )


def test_agent_tests_do_not_bypass_constructor() -> None:
    """Agent 测试不得通过 __new__ 绕过生产构造入口。"""
    bypasses = []
    for path in _TESTS_PATH.glob("test_*.py"):
        module = ast.parse(path.read_text(encoding="utf-8-sig"))
        if any(
            isinstance(node, ast.Attribute)
            and node.attr == "__new__"
            and isinstance(node.value, ast.Name)
            and node.value.id == "AIAgent"
            for node in ast.walk(module)
        ):
            bypasses.append(path.name)
    assert bypasses == []

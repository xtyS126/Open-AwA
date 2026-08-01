"""执行器兼容门面的架构门禁。"""

from __future__ import annotations

import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = BACKEND_ROOT / "core"
FACADE_PATH = CORE_ROOT / "executor.py"
COLLABORATOR_FILES = {
    "execution_configuration.py",
    "execution_model_runtime.py",
    "execution_tool_runtime.py",
    "execution_step_runtime.py",
}


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig"))


def test_executor_is_a_thin_compatibility_facade() -> None:
    """兼容门面只负责装配和代理，不再承载具体执行算法。"""
    source = FACADE_PATH.read_text(encoding="utf-8-sig")
    assert len(source.splitlines()) <= 420

    tree = ast.parse(source)
    execution_layer = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ExecutionLayer"
    )
    direct_methods = [
        node
        for node in execution_layer.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert direct_methods
    assert max(node.end_lineno - node.lineno + 1 for node in direct_methods) <= 40


def test_executor_collaborators_exist_and_do_not_import_facade() -> None:
    """具体职责位于单向依赖的协作者中，禁止形成反向依赖环。"""
    existing = {path.name for path in CORE_ROOT.glob("execution_*.py")}
    assert COLLABORATOR_FILES <= existing

    for filename in COLLABORATOR_FILES:
        path = CORE_ROOT / filename
        tree = _parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "core.executor"
            if isinstance(node, ast.Import):
                assert all(alias.name != "core.executor" for alias in node.names)


def test_executor_facade_composes_all_runtime_responsibilities() -> None:
    """门面必须显式组合配置、模型、工具和步骤四类职责。"""
    tree = _parse(FACADE_PATH)
    execution_layer = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ExecutionLayer"
    )
    bases = {
        base.id
        for base in execution_layer.bases
        if isinstance(base, ast.Name)
    }
    assert bases == {
        "ExecutionConfigurationMixin",
        "ExecutionModelRuntimeMixin",
        "ExecutionToolRuntimeMixin",
        "ExecutionStepRuntimeMixin",
    }

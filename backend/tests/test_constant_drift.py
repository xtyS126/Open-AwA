"""
常量漂移检测测试。

目的：检测跨文件常量不一致（常量漂移），作为回归测试防止未来修改时引入常量不一致。

检测范围：
1. SUMMARY_TEMPLATE：仅在 compaction_manager.py 定义，不在其他文件中复制
2. COMPACTABLE_TOOLS：引用一致性，仅在 compaction_manager.py 定义
3. MAX_CONSECUTIVE_FAILURES：常量值与定义位置
4. DENIAL_LIMITS：常量值与定义位置，permission_manager 应导入而非重定义
5. TOOL_DEFAULTS：常量值与定义位置
6. CHARS_PER_TOKEN：compaction_manager.py 无残留（Task 1 应已删除）
7. TokenBudget.estimate_tokens：方法存在且被 compaction_manager 使用
"""

import inspect
import re
from pathlib import Path
from typing import List

from core.compaction_manager import (
    COMPACTABLE_TOOLS,
    MAX_CONSECUTIVE_FAILURES,
    SUMMARY_TEMPLATE,
    _estimate_text_tokens,
    _token_budget,
)
from core.context.token_budget import TokenBudget
from core.denial_tracking import DENIAL_LIMITS
from core.tool_factory import TOOL_DEFAULTS


# backend 根目录（测试文件位于 backend/tests/ 下）
BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _collect_python_files(root: Path) -> List[Path]:
    """
    收集指定目录下所有 .py 文件（排除 __pycache__ 目录）。

    Args:
        root: 搜索根目录

    Returns:
        所有 .py 文件路径列表
    """
    python_files: List[Path] = []
    for path in root.rglob("*.py"):
        # 跳过 __pycache__ 目录下的缓存文件
        if "__pycache__" in path.parts:
            continue
        python_files.append(path)
    return python_files


def _find_constant_definitions(constant_name: str) -> List[Path]:
    """
    在 backend 下所有 .py 文件中搜索常量的模块级定义（赋值）。

    支持以下定义形式：
    - 无类型标注：CONSTANT_NAME = value
    - 带类型标注：CONSTANT_NAME: Type = value

    排除比较语句（如 CONSTANT_NAME == value）和 import 语句。

    Args:
        constant_name: 常量名

    Returns:
        包含常量定义的文件路径列表
    """
    # 匹配模块级定义：行首常量名，可选类型标注，然后 =（非 ==）
    # (?!=) 负向先行断言确保 = 后不跟 =，排除比较运算符
    pattern = rf"^{constant_name}(\s*:[^=]+)?\s*=(?!=)"
    regex = re.compile(pattern)
    matched_files: List[Path] = []
    for py_file in _collect_python_files(BACKEND_ROOT):
        try:
            text = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # 跳过无法读取的文件
            continue
        for line in text.splitlines():
            if regex.match(line):
                matched_files.append(py_file)
                break
    return matched_files


class TestSummaryTemplateDrift:
    """SUMMARY_TEMPLATE 常量漂移检测"""

    def test_summary_template_not_duplicated(self) -> None:
        """验证 SUMMARY_TEMPLATE 只在 compaction_manager.py 中定义，不在其他文件复制"""
        matched = _find_constant_definitions("SUMMARY_TEMPLATE")
        expected_file = BACKEND_ROOT / "core" / "compaction_manager.py"
        matched_names = [str(p.relative_to(BACKEND_ROOT)) for p in matched]
        assert len(matched) == 1, (
            f"SUMMARY_TEMPLATE 应仅在 compaction_manager.py 中定义，"
            f"实际定义文件: {matched_names}"
        )
        assert matched[0].resolve() == expected_file.resolve()

    def test_summary_template_content_nonempty(self) -> None:
        """验证 SUMMARY_TEMPLATE 内容非空且包含七段式必要段落"""
        assert SUMMARY_TEMPLATE, "SUMMARY_TEMPLATE 不应为空"
        # 七段式摘要模板的必要段落
        required_sections = [
            "目标",
            "约束与偏好",
            "进度",
            "关键决策",
            "下一步",
            "关键上下文",
            "相关文件",
        ]
        for section in required_sections:
            assert section in SUMMARY_TEMPLATE, (
                f"SUMMARY_TEMPLATE 应包含段落: {section}"
            )


class TestCompactableToolsDrift:
    """COMPACTABLE_TOOLS 常量漂移检测"""

    def test_compactable_tools_consistent(self) -> None:
        """验证 COMPACTABLE_TOOLS 引用一致，值与预期相符"""
        expected = {"Read", "Shell", "Grep", "Glob", "WebSearch", "Edit", "Write"}
        assert COMPACTABLE_TOOLS == expected, (
            f"COMPACTABLE_TOOLS 值应为 {expected}，实际为 {COMPACTABLE_TOOLS}"
        )

    def test_compactable_tools_only_defined_in_compaction_manager(self) -> None:
        """验证 COMPACTABLE_TOOLS 仅在 compaction_manager.py 定义，无跨文件重定义"""
        matched = _find_constant_definitions("COMPACTABLE_TOOLS")
        expected_file = BACKEND_ROOT / "core" / "compaction_manager.py"
        matched_names = [str(p.relative_to(BACKEND_ROOT)) for p in matched]
        assert len(matched) == 1, (
            f"COMPACTABLE_TOOLS 应仅在 compaction_manager.py 中定义，"
            f"实际定义文件: {matched_names}"
        )
        assert matched[0].resolve() == expected_file.resolve()


class TestMaxConsecutiveFailuresDrift:
    """MAX_CONSECUTIVE_FAILURES 常量漂移检测"""

    def test_max_consecutive_failures_constant(self) -> None:
        """验证 MAX_CONSECUTIVE_FAILURES 常量值为 3"""
        assert MAX_CONSECUTIVE_FAILURES == 3, (
            f"MAX_CONSECUTIVE_FAILURES 应为 3，实际为 {MAX_CONSECUTIVE_FAILURES}"
        )
        assert isinstance(MAX_CONSECUTIVE_FAILURES, int), (
            "MAX_CONSECUTIVE_FAILURES 应为 int 类型"
        )

    def test_max_consecutive_failures_only_defined_in_compaction_manager(self) -> None:
        """验证 MAX_CONSECUTIVE_FAILURES 定义位置已迁移到统一阈值配置"""
        matched = _find_constant_definitions("MAX_CONSECUTIVE_FAILURES")
        expected_file = BACKEND_ROOT / "config" / "thresholds.py"
        matched_names = [str(p.relative_to(BACKEND_ROOT)) for p in matched]
        assert len(matched) == 1, (
            f"MAX_CONSECUTIVE_FAILURES 应仅在 config/thresholds.py 中定义，"
            f"实际定义文件: {matched_names}"
        )
        assert matched[0].resolve() == expected_file.resolve()


class TestDenialLimitsDrift:
    """DENIAL_LIMITS 常量漂移检测"""

    def test_denial_limits_constant(self) -> None:
        """验证 DENIAL_LIMITS 常量值"""
        expected = {"max_consecutive": 3, "max_total": 20}
        assert DENIAL_LIMITS == expected, (
            f"DENIAL_LIMITS 应为 {expected}，实际为 {DENIAL_LIMITS}"
        )
        # 验证必需的键存在
        assert "max_consecutive" in DENIAL_LIMITS
        assert "max_total" in DENIAL_LIMITS

    def test_denial_limits_only_defined_in_denial_tracking(self) -> None:
        """验证 DENIAL_LIMITS 仅在 denial_tracking.py 定义"""
        matched = _find_constant_definitions("DENIAL_LIMITS")
        expected_file = BACKEND_ROOT / "core" / "denial_tracking.py"
        matched_names = [str(p.relative_to(BACKEND_ROOT)) for p in matched]
        assert len(matched) == 1, (
            f"DENIAL_LIMITS 应仅在 denial_tracking.py 中定义，"
            f"实际定义文件: {matched_names}"
        )
        assert matched[0].resolve() == expected_file.resolve()

    def test_denial_limits_imported_in_permission_manager(self) -> None:
        """验证 permission_manager.py 从 denial_tracking 导入 DENIAL_LIMITS（非重定义）"""
        perm_file = BACKEND_ROOT / "core" / "permission_manager.py"
        text = perm_file.read_text(encoding="utf-8")
        # 应存在从 core.denial_tracking 导入 DENIAL_LIMITS 的语句
        # 支持单行和多行括号形式的 import
        import_pattern = re.compile(
            r"from\s+core\.denial_tracking\s+import\s*\([^)]*DENIAL_LIMITS",
            re.DOTALL,
        )
        assert import_pattern.search(text), (
            "permission_manager.py 应从 core.denial_tracking 导入 DENIAL_LIMITS"
        )
        # 不应存在模块级重定义（排除 == 比较运算符）
        redefine_pattern = re.compile(r"^DENIAL_LIMITS(\s*:[^=]+)?\s*=(?!=)")
        assert not redefine_pattern.search(text), (
            "permission_manager.py 不应重定义 DENIAL_LIMITS"
        )


class TestToolDefaultsDrift:
    """TOOL_DEFAULTS 常量漂移检测"""

    def test_tool_defaults_constant(self) -> None:
        """验证 TOOL_DEFAULTS 常量值"""
        expected = {
            "is_concurrency_safe": False,
            "is_read_only": False,
            "is_destructive": False,
            "should_defer": False,
            "always_load": False,
            "max_result_size_chars": None,
            "interrupt_behavior": "cancel",
        }
        assert TOOL_DEFAULTS == expected, (
            f"TOOL_DEFAULTS 应为 {expected}，实际为 {TOOL_DEFAULTS}"
        )

    def test_tool_defaults_only_defined_in_tool_factory(self) -> None:
        """验证 TOOL_DEFAULTS 仅在 tool_factory.py 定义"""
        matched = _find_constant_definitions("TOOL_DEFAULTS")
        expected_file = BACKEND_ROOT / "core" / "tool_factory.py"
        matched_names = [str(p.relative_to(BACKEND_ROOT)) for p in matched]
        assert len(matched) == 1, (
            f"TOOL_DEFAULTS 应仅在 tool_factory.py 中定义，"
            f"实际定义文件: {matched_names}"
        )
        assert matched[0].resolve() == expected_file.resolve()


class TestTokenBudgetIntegration:
    """TokenBudget 与 compaction_manager 集成一致性检测"""

    def test_token_budget_estimate_tokens_exists(self) -> None:
        """验证 TokenBudget.estimate_tokens 方法存在且可调用"""
        assert hasattr(TokenBudget, "estimate_tokens"), (
            "TokenBudget 应定义 estimate_tokens 方法"
        )
        method = getattr(TokenBudget, "estimate_tokens")
        assert callable(method), "TokenBudget.estimate_tokens 应为可调用方法"

    def test_token_budget_estimate_tokens_heuristic(self) -> None:
        """验证 TokenBudget.estimate_tokens 使用中文 1.5 字符/token + 英文 4 字符/token"""
        source = inspect.getsource(TokenBudget.estimate_tokens)
        # 中文约 1.5 字符/token
        assert "1.5" in source, (
            "estimate_tokens 应使用中文 1.5 字符/token 启发式"
        )
        # 英文约 4 字符/token
        assert "/ 4" in source or "/ 4.0" in source, (
            "estimate_tokens 应使用英文 4 字符/token 启发式"
        )

    def test_no_chars_per_token_in_compaction_manager(self) -> None:
        """验证 compaction_manager.py 无 CHARS_PER_TOKEN 残留常量定义"""
        compaction_file = BACKEND_ROOT / "core" / "compaction_manager.py"
        text = compaction_file.read_text(encoding="utf-8")
        # 不应残留 CHARS_PER_TOKEN = 3.5 常量（Task 1 应已删除）
        assert "CHARS_PER_TOKEN = 3.5" not in text, (
            "compaction_manager.py 不应残留 CHARS_PER_TOKEN = 3.5 常量"
        )
        # 不应存在模块级 CHARS_PER_TOKEN 常量定义（支持可选类型标注，排除 ==）
        define_pattern = re.compile(r"^CHARS_PER_TOKEN(\s*:[^=]+)?\s*=(?!=)")
        assert not define_pattern.search(text), (
            "compaction_manager.py 不应定义模块级 CHARS_PER_TOKEN 常量"
        )

    def test_compaction_manager_uses_token_budget(self) -> None:
        """验证 compaction_manager.py 使用 TokenBudget.estimate_tokens 而非自定义估算逻辑"""
        compaction_file = BACKEND_ROOT / "core" / "compaction_manager.py"
        text = compaction_file.read_text(encoding="utf-8")
        # 应导入 TokenBudget
        assert "from core.context.token_budget import TokenBudget" in text, (
            "compaction_manager.py 应从 core.context.token_budget 导入 TokenBudget"
        )
        # 应创建 TokenBudget 实例
        assert "TokenBudget()" in text, (
            "compaction_manager.py 应创建 TokenBudget 实例"
        )

    def test_compaction_manager_estimate_text_tokens_delegates_to_token_budget(self) -> None:
        """验证 _estimate_text_tokens 委托给 TokenBudget.estimate_tokens"""
        # 模块级 _token_budget 应为 TokenBudget 实例
        assert isinstance(_token_budget, TokenBudget), (
            "_token_budget 应为 TokenBudget 实例"
        )
        # _estimate_text_tokens 源码应调用 _token_budget.estimate_tokens
        source = inspect.getsource(_estimate_text_tokens)
        assert "_token_budget.estimate_tokens" in source, (
            "_estimate_text_tokens 应委托给 _token_budget.estimate_tokens"
        )

    def test_estimate_text_tokens_matches_token_budget(self) -> None:
        """验证 compaction_manager 的 token 估算结果与 TokenBudget 完全一致"""
        budget = TokenBudget()
        # 中文文本
        cn_text = "这是一条用于测试token估算的中文消息"
        assert _estimate_text_tokens(cn_text) == budget.estimate_tokens(cn_text)
        # 英文文本
        en_text = "This is a test message for token estimation."
        assert _estimate_text_tokens(en_text) == budget.estimate_tokens(en_text)
        # 空文本
        assert _estimate_text_tokens("") == budget.estimate_tokens("") == 0

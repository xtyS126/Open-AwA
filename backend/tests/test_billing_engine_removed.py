"""验证 BillingEngine 已被正确废弃删除

覆盖场景：
1. billing 包可正常 import（无残留导入错误）
2. billing.__init__ 不再导出 BillingEngine 名称
3. billing.engine 模块已删除（import 抛 ModuleNotFoundError）
4. UsageTracker 替代方案可正常导入
5. main.app 可正常构造（验证无残留依赖）

依赖前提：
- backend/conftest.py 已将 backend/ 加入 sys.path，因此使用 `billing` 作为导入路径
- backend/tests/conftest.py 已设置 TESTING / DATABASE_URL 等环境变量
"""
from __future__ import annotations

import importlib

import pytest


def test_billing_package_imports_without_error():
    """billing 包应可正常 import，不因 engine.py 删除而产生残留导入错误。"""
    billing_module = importlib.import_module("billing")
    assert billing_module is not None
    # 模块文件应指向 __init__.py
    assert billing_module.__name__ == "billing"


def test_billing_init_does_not_export_billing_engine():
    """billing.__init__ 的 __all__ 与模块属性不应再包含 BillingEngine。"""
    billing_module = importlib.import_module("billing")
    assert "BillingEngine" not in getattr(billing_module, "__all__", [])
    assert not hasattr(billing_module, "BillingEngine")


def test_billing_engine_module_raises_module_not_found_error():
    """billing.engine 模块应已删除，import 时抛 ModuleNotFoundError。"""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("billing.engine")


def test_usage_tracker_still_importable_as_replacement():
    """UsageTracker 替代方案应可正常导入，且扩展类暴露 record_llm_call 方法。

    billing/__init__.py 导出 billing.tracker.UsageTracker（基类），
    Agent 流程计费入口的扩展类在 billing.usage_tracker.UsageTracker，
    通过 record_llm_call 方法替代原 BillingEngine 的计费扣减逻辑。
    """
    # 顶层导出（基类）应可用
    from billing import UsageTracker as BaseUsageTracker

    assert BaseUsageTracker is not None

    # 扩展类（含 record_llm_call）应可从 billing.usage_tracker 导入
    from billing.usage_tracker import UsageTracker as ExtendedUsageTracker

    assert ExtendedUsageTracker is not None
    # 确认扩展类暴露 record_llm_call 方法（替代 BillingEngine 的入口）
    assert hasattr(ExtendedUsageTracker, "record_llm_call")
    # 扩展类应继承基类
    assert issubclass(ExtendedUsageTracker, BaseUsageTracker)


def test_main_app_constructs_without_billing_engine_dependency():
    """main.app 应可正常构造，验证删除 BillingEngine 后无残留依赖。"""
    # 延迟导入 main，避免在测试收集阶段触发 lifespan
    import main

    app = getattr(main, "app", None)
    assert app is not None, "main.app 应存在且可访问"

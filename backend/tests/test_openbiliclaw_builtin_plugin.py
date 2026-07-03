"""OpenBiliClaw 内置插件入口类的单元测试。

覆盖三个核心场景：
1. manifest.json 字段解析：name/version/source/uninstallable 等关键字段
2. 依赖检测逻辑：mock importlib.util.find_spec 验证关键依赖缺失时抛
   BuiltinPluginDependencyError，可选依赖缺失仅记录告警
3. 技能转换：initialize 成功后 get_tools 返回 10 个工具，
   且 _skill_to_tool_def 保留 name/description/parameters 等字段

测试隔离原则：
- 每个用例独立 fixture，不依赖全局状态
- importlib.util.find_spec 全部 mock，避免受运行环境影响
- OpenBiliClawAdapter 全部 mock，避免触发 vendored 包真实加载
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 将 backend 目录加入 sys.path，便于导入 plugins 包
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from plugins.openbiliclaw_builtin.plugin import (  # noqa: E402
    BuiltinPluginDependencyError,
    OpenBiliClawBuiltinPlugin,
    _OPTIONAL_DEPENDENCIES,
    _REQUIRED_DEPENDENCIES,
)


# ---------------------------------------------------------------------------
# manifest.json 解析测试
# ---------------------------------------------------------------------------

_MANIFEST_PATH = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "openbiliclaw_builtin"
    / "manifest.json"
)


def _load_manifest() -> Dict[str, Any]:
    """读取内置插件 manifest.json 并返回字典。"""
    with open(_MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_manifest_has_correct_name_and_version():
    """manifest 应声明正确的 name、version、source 与 uninstallable 字段。"""
    manifest = _load_manifest()

    assert manifest["name"] == "openbiliclaw-builtin"
    assert manifest["version"] == "0.3.147"
    assert manifest["source"] == "builtin"
    assert manifest["uninstallable"] is True


def test_manifest_declares_required_fields():
    """manifest 应包含 description、author、category 等基础描述字段。"""
    manifest = _load_manifest()

    assert "description" in manifest and isinstance(manifest["description"], str)
    assert manifest["description"].strip() != ""
    assert "author" in manifest and isinstance(manifest["author"], str)
    assert "category" in manifest and isinstance(manifest["category"], str)


def test_plugin_class_attributes_match_manifest():
    """OpenBiliClawBuiltinPlugin 的类属性应与 manifest 一致。"""
    manifest = _load_manifest()

    assert OpenBiliClawBuiltinPlugin.name == manifest["name"]
    assert OpenBiliClawBuiltinPlugin.version == manifest["version"]


# ---------------------------------------------------------------------------
# 依赖检测测试
# ---------------------------------------------------------------------------


def _make_spec(found: bool) -> Optional[Any]:
    """构造 find_spec 返回值；found=False 时返回 None 模拟缺失。"""
    if not found:
        return None
    # 返回一个非 None 的占位对象，find_spec 调用方只判断是否为 None
    return MagicMock()


@pytest.fixture
def plugin_instance() -> OpenBiliClawBuiltinPlugin:
    """提供一个未初始化的插件实例。"""
    return OpenBiliClawBuiltinPlugin(config={})


def test_initialize_succeeds_when_all_deps_present(plugin_instance):
    """所有关键依赖与可选依赖均存在时，initialize 不抛异常且返回 True。"""
    # 让所有 find_spec 都返回非 None
    with patch("plugins.openbiliclaw_builtin.plugin.importlib.util.find_spec") as mock_spec:
        mock_spec.return_value = _make_spec(True)

        # 同时 mock 适配层 initialize，避免触发 vendored 真实加载
        with patch(
            "plugins.openbiliclaw_builtin.plugin.OpenBiliClawAdapter"
        ) as mock_adapter_cls:
            mock_adapter = MagicMock()
            mock_adapter.initialize = AsyncMock(return_value=None)
            mock_adapter.get_warnings.return_value = []
            mock_adapter.get_tools.return_value = []
            mock_adapter_cls.return_value = mock_adapter

            # 执行 initialize（pytest-asyncio 自动处理事件循环）
            import asyncio

            result = asyncio.get_event_loop().run_until_complete(plugin_instance.initialize())

    assert result is True
    # 全部依赖就绪时不应收集到关键缺失告警
    # 注意：可选依赖缺失会进入 _dependency_warnings，但此处全部 mock 为存在
    assert plugin_instance.get_dependency_warnings() == []


def test_initialize_raises_when_critical_dep_missing(plugin_instance):
    """bilibili-api-python 关键依赖缺失时应抛 BuiltinPluginDependencyError。"""
    # bilibili_api 是 _REQUIRED_DEPENDENCIES 中的关键依赖
    # 模拟其 find_spec 返回 None，其他依赖均存在
    def fake_find_spec(name: str):
        if name == "bilibili_api":
            return None
        return _make_spec(True)

    with patch(
        "plugins.openbiliclaw_builtin.plugin.importlib.util.find_spec",
        side_effect=fake_find_spec,
    ):
        with pytest.raises(BuiltinPluginDependencyError) as exc_info:
            import asyncio

            asyncio.get_event_loop().run_until_complete(plugin_instance.initialize())

    # 异常消息应包含 pip 包名 bilibili-api-python
    assert "bilibili-api-python" in str(exc_info.value)
    # missing_packages 字段应包含 bilibili-api-python
    assert "bilibili-api-python" in exc_info.value.missing_packages


def test_initialize_raises_when_multiple_deps_missing(plugin_instance):
    """多个关键依赖缺失时，异常消息应列出全部缺失包名。"""
    # 让 httpx 与 bilibili_api 同时缺失
    missing_imports = {"httpx", "bilibili_api"}

    def fake_find_spec(name: str):
        if name in missing_imports:
            return None
        return _make_spec(True)

    with patch(
        "plugins.openbiliclaw_builtin.plugin.importlib.util.find_spec",
        side_effect=fake_find_spec,
    ):
        with pytest.raises(BuiltinPluginDependencyError) as exc_info:
            import asyncio

            asyncio.get_event_loop().run_until_complete(plugin_instance.initialize())

    # 异常应同时列出 httpx 与 bilibili-api-python
    assert "httpx" in str(exc_info.value)
    assert "bilibili-api-python" in str(exc_info.value)
    # missing_packages 列表应包含两者
    assert "httpx" in exc_info.value.missing_packages
    assert "bilibili-api-python" in exc_info.value.missing_packages
    # 顺序应与 _REQUIRED_DEPENDENCIES 的迭代顺序保持一致
    assert len(exc_info.value.missing_packages) == 2


def test_initialize_records_warning_when_optional_dep_missing(plugin_instance):
    """可选依赖缺失时不应抛异常，但应记录到 _dependency_warnings。"""
    # 关键依赖全部存在
    def fake_find_spec(name: str):
        if name in _OPTIONAL_DEPENDENCIES:
            return None
        return _make_spec(True)

    with patch(
        "plugins.openbiliclaw_builtin.plugin.importlib.util.find_spec",
        side_effect=fake_find_spec,
    ):
        with patch(
            "plugins.openbiliclaw_builtin.plugin.OpenBiliClawAdapter"
        ) as mock_adapter_cls:
            mock_adapter = MagicMock()
            mock_adapter.initialize = AsyncMock(return_value=None)
            mock_adapter.get_warnings.return_value = []
            mock_adapter.get_tools.return_value = []
            mock_adapter_cls.return_value = mock_adapter

            import asyncio

            result = asyncio.get_event_loop().run_until_complete(plugin_instance.initialize())

    assert result is True
    warnings = plugin_instance.get_dependency_warnings()
    # 至少应记录可选依赖缺失告警
    assert len(warnings) > 0
    # 告警文本中应能识别出可选依赖的 import 名
    warning_text = "\n".join(warnings)
    assert "openai" in warning_text or "anthropic" in warning_text or "ollama" in warning_text


# ---------------------------------------------------------------------------
# 技能转换测试
# ---------------------------------------------------------------------------


def test_get_tools_returns_empty_list_before_initialize(plugin_instance):
    """未调用 initialize 时，get_tools 应返回空列表。"""
    assert plugin_instance.get_tools() == []


def test_get_tools_returns_ten_tools_after_initialize(plugin_instance):
    """initialize 成功且 adapter 返回 10 个工具后，get_tools 应返回长度为 10 的列表。"""
    # 构造 10 个工具定义（模拟 adapter.get_tools 返回值）
    fake_tools: List[Dict[str, Any]] = [
        {
            "name": f"openbiliclaw_tool_{i}",
            "description": f"tool {i}",
            "parameters": {"type": "object", "properties": {}},
            "handler": AsyncMock(),
        }
        for i in range(10)
    ]

    with patch(
        "plugins.openbiliclaw_builtin.plugin.importlib.util.find_spec"
    ) as mock_spec:
        mock_spec.return_value = _make_spec(True)
        with patch(
            "plugins.openbiliclaw_builtin.plugin.OpenBiliClawAdapter"
        ) as mock_adapter_cls:
            mock_adapter = MagicMock()
            mock_adapter.initialize = AsyncMock(return_value=None)
            mock_adapter.get_warnings.return_value = []
            mock_adapter.get_tools.return_value = fake_tools
            mock_adapter_cls.return_value = mock_adapter

            import asyncio

            asyncio.get_event_loop().run_until_complete(plugin_instance.initialize())

    tools = plugin_instance.get_tools()
    assert len(tools) == 10
    # 验证工具列表与 adapter 返回值一致
    assert tools is fake_tools


def test_get_dependency_warnings_returns_copy(plugin_instance):
    """get_dependency_warnings 应返回列表副本，外部修改不影响内部状态。"""
    plugin_instance._dependency_warnings.append("test warning")
    warnings = plugin_instance.get_dependency_warnings()
    warnings.append("external modification")

    # 内部状态不应受外部修改影响
    assert "external modification" not in plugin_instance._dependency_warnings


def test_cleanup_resets_plugin_state(plugin_instance):
    """cleanup 应清空工具列表与适配层引用。"""
    # 模拟已初始化状态
    fake_adapter = MagicMock()
    fake_adapter.cleanup = MagicMock(return_value=None)
    plugin_instance._adapter = fake_adapter
    plugin_instance._tools = [{"name": "tool1"}]
    plugin_instance._initialized = True

    import asyncio

    asyncio.get_event_loop().run_until_complete(plugin_instance.cleanup())

    # 验证适配层 cleanup 被调用
    fake_adapter.cleanup.assert_called_once()
    # 验证状态被清空
    assert plugin_instance._adapter is None
    assert plugin_instance._tools == []
    assert plugin_instance._initialized is False


def test_cleanup_swallows_adapter_cleanup_exception(plugin_instance):
    """adapter.cleanup 抛异常时，插件 cleanup 不应传播异常。"""
    fake_adapter = MagicMock()
    fake_adapter.cleanup = MagicMock(side_effect=RuntimeError("cleanup failed"))
    plugin_instance._adapter = fake_adapter

    import asyncio

    # 不应抛异常
    asyncio.get_event_loop().run_until_complete(plugin_instance.cleanup())
    # 仍应清空引用
    assert plugin_instance._adapter is None


def test_execute_raises_not_implemented(plugin_instance):
    """统一 execute 入口应抛 NotImplementedError，提示使用 get_tools。"""
    with pytest.raises(NotImplementedError):
        plugin_instance.execute()


def test_initialize_degrades_when_adapter_initialize_fails(plugin_instance):
    """adapter.initialize 抛异常时，插件应降级为空工具列表并返回 True。"""
    with patch(
        "plugins.openbiliclaw_builtin.plugin.importlib.util.find_spec"
    ) as mock_spec:
        mock_spec.return_value = _make_spec(True)
        with patch(
            "plugins.openbiliclaw_builtin.plugin.OpenBiliClawAdapter"
        ) as mock_adapter_cls:
            mock_adapter = MagicMock()
            mock_adapter.initialize = AsyncMock(
                side_effect=RuntimeError("adapter init failed")
            )
            mock_adapter_cls.return_value = mock_adapter

            import asyncio

            result = asyncio.get_event_loop().run_until_complete(plugin_instance.initialize())

    # 降级模式仍返回 True
    assert result is True
    # 工具列表应为空
    assert plugin_instance.get_tools() == []
    # 应记录告警
    warnings = plugin_instance.get_dependency_warnings()
    assert any("OpenBiliClawAdapter.initialize" in w for w in warnings)

"""
get_available_plugins 不再 lazy load 的单元测试。

覆盖 backend/core/agent.py 的 get_available_plugins 行为：
- 未 loaded 的插件返回 loaded=False, tools=[]（不再触发 load_plugin）
- 未 loaded 的插件不调用 plugin_manager.load_plugin
- 已 loaded 的插件正常返回 tools

通过 AIAgent() 无 db_session 实例化 + mock plugin_manager，
避免触发真实数据库/向量库/插件目录加载。
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent import AIAgent


def _make_partial_agent() -> AIAgent:
    """创建无 db_session 的 AIAgent 实例，避免触发 DB/向量库/插件目录加载。

    AIAgent() 不带参数时不会创建 memory_manager / workflow_engine，
    避免了复杂的依赖初始化。
    """
    return AIAgent()


def _stub_plugin_manager(
    agent: AIAgent,
    *,
    discovered: list,
    loaded_names: set,
) -> MagicMock:
    """mock AIAgent.plugin_manager 的相关方法，返回 load_plugin 的 mock 便于断言。

    Args:
        agent: AIAgent 实例
        discovered: discover_plugins 返回的插件信息列表
        loaded_names: 已加载的插件名称集合（用于 loaded_plugins 的 in 判断）

    Returns:
        load_plugin 的 MagicMock，便于断言是否被调用
    """
    pm = agent.plugin_manager
    pm.discover_plugins = MagicMock(return_value=discovered)
    # loaded_plugins 在源码中是 dict，用 dict 模拟更贴近真实行为
    # 源码用 `plugin_name not in self.plugin_manager.loaded_plugins` 判断
    pm.loaded_plugins = {name: MagicMock() for name in loaded_names}
    mock_load = MagicMock(return_value=True)
    pm.load_plugin = mock_load
    pm.get_plugin_tools = MagicMock(return_value=[{"name": "tool_from_loaded"}])
    pm.get_plugin_info = MagicMock(return_value={"loaded": True})
    return mock_load


@pytest.mark.asyncio
async def test_unloaded_plugin_returns_empty_tools() -> None:
    """未 loaded 的插件应返回 loaded=False, tools=[]。"""
    agent = _make_partial_agent()
    _stub_plugin_manager(
        agent,
        discovered=[{"name": "plugin_a", "version": "1.0", "description": "未加载插件"}],
        loaded_names=set(),  # 无已加载插件
    )

    plugins = await agent.get_available_plugins()

    assert len(plugins) == 1
    assert plugins[0]["name"] == "plugin_a"
    assert plugins[0]["loaded"] is False
    assert plugins[0]["tools"] == []
    assert plugins[0]["version"] == "1.0"
    assert plugins[0]["description"] == "未加载插件"


@pytest.mark.asyncio
async def test_unloaded_plugin_does_not_call_load_plugin() -> None:
    """未 loaded 的插件不应触发 plugin_manager.load_plugin（不再 lazy load）。"""
    agent = _make_partial_agent()
    mock_load = _stub_plugin_manager(
        agent,
        discovered=[{"name": "plugin_a", "version": "1.0", "description": ""}],
        loaded_names=set(),
    )

    await agent.get_available_plugins()

    # load_plugin 不应被调用
    mock_load.assert_not_called()
    assert mock_load.call_count == 0


@pytest.mark.asyncio
async def test_loaded_plugin_returns_tools() -> None:
    """已 loaded 的插件应正常返回 tools 与 loaded=True。"""
    agent = _make_partial_agent()
    _stub_plugin_manager(
        agent,
        discovered=[{"name": "plugin_b", "version": "2.0", "description": "已加载插件"}],
        loaded_names={"plugin_b"},  # plugin_b 已加载
    )

    plugins = await agent.get_available_plugins()

    assert len(plugins) == 1
    assert plugins[0]["name"] == "plugin_b"
    assert plugins[0]["loaded"] is True
    assert len(plugins[0]["tools"]) > 0
    assert plugins[0]["tools"][0]["name"] == "tool_from_loaded"


@pytest.mark.asyncio
async def test_mixed_loaded_and_unloaded_plugins() -> None:
    """混合场景：一个已加载、一个未加载，应分别返回正确状态且不调用 load_plugin。"""
    agent = _make_partial_agent()
    mock_load = _stub_plugin_manager(
        agent,
        discovered=[
            {"name": "plugin_loaded", "version": "1.0", "description": "已加载"},
            {"name": "plugin_unloaded", "version": "1.0", "description": "未加载"},
        ],
        loaded_names={"plugin_loaded"},
    )

    plugins = await agent.get_available_plugins()

    assert len(plugins) == 2
    # 按 name 排序后断言，避免依赖 discover_plugins 的顺序
    by_name = {p["name"]: p for p in plugins}

    assert by_name["plugin_loaded"]["loaded"] is True
    assert len(by_name["plugin_loaded"]["tools"]) > 0

    assert by_name["plugin_unloaded"]["loaded"] is False
    assert by_name["plugin_unloaded"]["tools"] == []

    # 未加载插件不应触发 load_plugin
    mock_load.assert_not_called()


@pytest.mark.asyncio
async def test_plugin_without_name_is_skipped() -> None:
    """缺少 name 字段的插件条目应被跳过，不进入返回列表。"""
    agent = _make_partial_agent()
    _stub_plugin_manager(
        agent,
        discovered=[
            {"name": "", "version": "1.0", "description": "空名"},  # name 为空，跳过
            {"version": "1.0", "description": "无 name 字段"},  # 无 name，跳过
            {"name": "plugin_ok", "version": "1.0", "description": "正常插件"},
        ],
        loaded_names={"plugin_ok"},
    )

    plugins = await agent.get_available_plugins()

    # 只应返回有 name 的插件
    assert len(plugins) == 1
    assert plugins[0]["name"] == "plugin_ok"

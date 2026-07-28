"""
PluginManager.discover_plugins 进程级缓存单元测试。

覆盖 backend/plugins/plugin_manager.py 的 discover_plugins 缓存逻辑：
- 首次调用执行 os.walk（_discover_plugins_in_directory）
- 第二次调用 mtime 不变时命中缓存
- mtime 变化时重新扫描
- invalidate_discover_cache 主动失效
- load_plugin 触发缓存失效

通过 tmp_path 隔离 plugins_dir，mock _discover_plugins_in_directory
返回固定列表，避免依赖真实插件文件扫描结果。
"""

import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.plugin_manager import PluginManager


@pytest.fixture
def plugin_manager(tmp_path: Path) -> PluginManager:
    """创建 plugins_dir 指向临时目录的 PluginManager。

    _discover_plugins_in_directory 被 mock 为返回固定列表，
    避免依赖真实文件扫描结果，同时保留缓存逻辑的真实执行。
    """
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    manager = PluginManager(plugins_dir=str(plugins_dir))

    # mock _discover_plugins_in_directory 返回固定列表
    # 使用 side_effect 而非 return_value，便于统计调用次数
    manager._discover_plugins_in_directory = MagicMock(
        return_value=[{"name": "stub_plugin", "version": "1.0.0"}]
    )
    return manager


def test_first_call_executes_discover(plugin_manager: PluginManager) -> None:
    """首次调用 discover_plugins 应执行 _discover_plugins_in_directory。"""
    result = plugin_manager.discover_plugins()

    assert plugin_manager._discover_plugins_in_directory.call_count == 1
    assert len(result) == 1
    assert result[0]["name"] == "stub_plugin"
    # 缓存应被填充
    assert plugin_manager._discover_cache is not None
    assert plugin_manager._discover_cache_mtime != 0.0


def test_second_call_with_same_mtime_hits_cache(plugin_manager: PluginManager) -> None:
    """mtime 不变时第二次调用应命中缓存，不重新扫描。"""
    plugin_manager.discover_plugins()
    assert plugin_manager._discover_plugins_in_directory.call_count == 1

    # 第二次调用，mtime 未变化
    result = plugin_manager.discover_plugins()

    # _discover_plugins_in_directory 不应再次被调用
    assert plugin_manager._discover_plugins_in_directory.call_count == 1
    assert len(result) == 1
    # 返回的应是缓存拷贝（不同对象，但内容一致）
    assert result == plugin_manager._discover_cache


def test_mtime_change_invalidates_cache(plugin_manager: PluginManager) -> None:
    """plugins_dir mtime 变化时应重新扫描。"""
    plugin_manager.discover_plugins()
    assert plugin_manager._discover_plugins_in_directory.call_count == 1

    # 模拟目录 mtime 变化：通过 os.stat 获取当前 mtime，然后修改 _discover_cache_mtime 为旧值
    current_mtime = os.stat(plugin_manager.plugins_dir).st_mtime
    plugin_manager._discover_cache_mtime = current_mtime - 1.0

    # 修改 mock 返回值，验证重新扫描后拿到新结果
    plugin_manager._discover_plugins_in_directory = MagicMock(
        return_value=[{"name": "new_plugin", "version": "2.0.0"}]
    )

    result = plugin_manager.discover_plugins()

    # 应重新调用 _discover_plugins_in_directory
    assert plugin_manager._discover_plugins_in_directory.call_count == 1
    assert result[0]["name"] == "new_plugin"
    # 缓存应被更新为新结果
    assert plugin_manager._discover_cache[0]["name"] == "new_plugin"


def test_invalidate_discover_cache_clears_cache(plugin_manager: PluginManager) -> None:
    """invalidate_discover_cache 应清空缓存，下次 discover_plugins 重新扫描。"""
    plugin_manager.discover_plugins()
    assert plugin_manager._discover_cache is not None

    plugin_manager.invalidate_discover_cache()

    assert plugin_manager._discover_cache is None
    assert plugin_manager._discover_cache_mtime == 0.0

    # 下次调用应重新扫描
    plugin_manager.discover_plugins()
    assert plugin_manager._discover_plugins_in_directory.call_count == 2


def test_load_plugin_invalidates_discover_cache(plugin_manager: PluginManager,
                                                tmp_path: Path) -> None:
    """load_plugin 后缓存应失效（通过 invalidate_discover_cache 间接调用）。"""
    # 先填充缓存
    plugin_manager.discover_plugins()
    assert plugin_manager._discover_cache is not None
    assert plugin_manager._discover_plugins_in_directory.call_count == 1

    # 创建一个最小可加载的插件文件
    plugin_file = tmp_path / "plugins" / "loadable_plugin.py"
    plugin_file.write_text(
        '"""可加载的最小测试插件。"""\n'
        'from plugins.base import BasePlugin\n\n'
        'class LoadablePlugin(BasePlugin):\n'
        '    name = "loadable_plugin"\n'
        '    version = "1.0.0"\n'
        '    description = "test"\n\n'
        '    def get_tools(self):\n'
        '        return []\n',
        encoding="utf-8",
    )

    # 真实加载插件文件（不走 mock）
    plugin_manager.load_plugin("loadable_plugin")

    # load_plugin 内部应调用 invalidate_discover_cache，缓存被清空
    # 缓存失效后 _discover_cache 应为 None
    assert plugin_manager._discover_cache is None

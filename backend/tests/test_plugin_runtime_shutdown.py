"""插件全局运行时关闭与单例释放回归测试。"""

import pytest

from main import _shutdown_plugin_system
from plugins import plugin_instance


class _FakePluginManager:
    """记录插件卸载顺序的轻量管理器。"""

    def __init__(self) -> None:
        self.loaded_plugins = {"first": object(), "second": object()}
        self.unloaded: list[str] = []

    def unload_plugin(self, plugin_name: str) -> bool:
        """记录卸载并移除对应插件。"""
        self.unloaded.append(plugin_name)
        self.loaded_plugins.pop(plugin_name, None)
        return True


@pytest.mark.asyncio
async def test_shutdown_unloads_plugins_and_resets_singleton() -> None:
    """应用关闭时应逆序卸载插件并释放全局管理器引用。"""
    manager = _FakePluginManager()
    plugin_instance.init(manager)

    await _shutdown_plugin_system()

    assert manager.unloaded == ["second", "first"]
    assert manager.loaded_plugins == {}
    assert plugin_instance.get_if_initialized() is None


@pytest.mark.asyncio
async def test_shutdown_without_initialized_manager_is_idempotent() -> None:
    """未初始化或重复关闭插件系统时不应创建默认管理器。"""
    plugin_instance.reset()

    await _shutdown_plugin_system()

    assert plugin_instance.get_if_initialized() is None

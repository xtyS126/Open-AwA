"""
后端测试模块，负责验证对应功能在正常、边界或异常场景下的行为是否符合预期。
保持测试注释清晰，有助于快速分辨各个用例所覆盖的场景。
"""

import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.plugin_manager import PluginManager


def _make_plugin_source(plugin_name: str) -> str:
    """
    处理make、plugin、source相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    class_name = ''.join(part.capitalize() for part in plugin_name.split('_')) + 'Plugin'
    return f'''from plugins.base_plugin import BasePlugin


class {class_name}(BasePlugin):
    name = "{plugin_name}"
    version = "1.0.0"
    description = "performance baseline plugin"

    def initialize(self):
        return True

    def execute(self, **kwargs):
        return kwargs
'''


def test_plugin_50_baseline_metrics(tmp_path: Path):
    """
    验证plugin、50、baseline、metrics相关场景的行为是否符合预期。
    通过断言结果可以帮助定位实现与预期行为之间的偏差。
    """
    total_plugins = 50
    for index in range(total_plugins):
        plugin_name = f"perf_plugin_{index:02d}"
        source = _make_plugin_source(plugin_name)
        (tmp_path / f"{plugin_name}.py").write_text(source, encoding="utf-8")

    manager = PluginManager(plugins_dir=str(tmp_path))

    tracemalloc.start()
    start_time = time.perf_counter()
    discovered = manager.discover_plugins()
    first_screen_ms = (time.perf_counter() - start_time) * 1000

    install_success_count = 0
    for plugin_info in discovered:
        if manager.load_plugin(plugin_info["name"]):
            install_success_count += 1

    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    memory_growth_mb = peak_bytes / (1024 * 1024)
    install_success_rate = install_success_count / total_plugins

    assert len(discovered) == total_plugins
    assert first_screen_ms < 1500
    assert memory_growth_mb < 30
    assert install_success_rate >= 0.99

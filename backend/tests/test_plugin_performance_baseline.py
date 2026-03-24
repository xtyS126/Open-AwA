import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.plugin_manager import PluginManager


def _make_plugin_source(plugin_name: str) -> str:
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

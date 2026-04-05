"""
后端测试模块，负责验证对应功能在正常、边界或异常场景下的行为是否符合预期。
保持测试注释清晰，有助于快速分辨各个用例所覆盖的场景。
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'plugins'))

import pytest
from plugin_logger import LogManager, PluginLogger


class TestPluginLogger:
    """
    封装与TestPluginLogger相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def test_default_level_is_debug(self):
        """
        验证default、level、is、debug相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        logger = PluginLogger(plugin_id="p1")
        assert logger.level == "DEBUG"

    def test_set_level_valid(self):
        """
        验证set、level、valid相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        logger = PluginLogger(plugin_id="p1")
        logger.level = "INFO"
        assert logger.level == "INFO"

    def test_set_level_case_insensitive(self):
        """
        验证set、level、case、insensitive相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        logger = PluginLogger(plugin_id="p1")
        logger.level = "warning"
        assert logger.level == "WARNING"

    def test_set_level_invalid_raises(self):
        """
        验证set、level、invalid、raises相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        logger = PluginLogger(plugin_id="p1")
        with pytest.raises(ValueError):
            logger.level = "VERBOSE"

    def test_log_debug_filtered_when_level_info(self):
        """
        验证log、debug、filtered、when、level、info相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        logger = PluginLogger(plugin_id="p1")
        logger.level = "INFO"
        logger.debug("should be filtered")
        entries = logger.get_entries()
        assert len(entries) == 0

    def test_log_info_passes_when_level_info(self):
        """
        验证log、info、passes、when、level、info相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        logger = PluginLogger(plugin_id="p1")
        logger.level = "INFO"
        logger.info("visible message")
        entries = logger.get_entries()
        assert len(entries) == 1
        assert entries[0]["message"] == "visible message"
        assert entries[0]["level"] == "INFO"

    def test_log_error_passes_when_level_info(self):
        """
        验证log、error、passes、when、level、info相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        logger = PluginLogger(plugin_id="p1")
        logger.level = "INFO"
        logger.error("error msg")
        entries = logger.get_entries()
        assert len(entries) == 1
        assert entries[0]["level"] == "ERROR"

    def test_all_log_methods(self):
        """
        验证all、log、methods相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        logger = PluginLogger(plugin_id="p1")
        logger.debug("d")
        logger.info("i")
        logger.warning("w")
        logger.error("e")
        logger.critical("c")
        entries = logger.get_entries()
        assert len(entries) == 5
        levels = [e["level"] for e in entries]
        assert levels == ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    def test_get_entries_with_level_filter(self):
        """
        验证get、entries、with、level、filter相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        logger = PluginLogger(plugin_id="p1")
        logger.debug("d")
        logger.info("i")
        logger.warning("w")
        logger.error("e")
        entries = logger.get_entries(level="WARNING")
        levels = {e["level"] for e in entries}
        assert "DEBUG" not in levels
        assert "INFO" not in levels
        assert "WARNING" in levels
        assert "ERROR" in levels

    def test_get_entries_limit_offset(self):
        """
        验证get、entries、limit、offset相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        logger = PluginLogger(plugin_id="p1")
        for i in range(10):
            logger.info(f"msg {i}")
        entries = logger.get_entries(limit=3, offset=2)
        assert len(entries) == 3
        assert entries[0]["message"] == "msg 2"

    def test_extra_kwargs_stored(self):
        """
        验证extra、kwargs、stored相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        logger = PluginLogger(plugin_id="p1")
        logger.info("hello", user="alice", count=5)
        entries = logger.get_entries()
        assert entries[0]["extra"] == {"user": "alice", "count": 5}

    def test_clear(self):
        """
        验证clear相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        logger = PluginLogger(plugin_id="p1")
        logger.info("msg")
        logger.clear()
        assert logger.get_entries() == []

    def test_maxlen_respected(self):
        """
        验证maxlen、respected相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        logger = PluginLogger(plugin_id="p1", max_entries=5)
        for i in range(10):
            logger.info(f"msg {i}")
        entries = logger.get_entries()
        assert len(entries) == 5
        assert entries[0]["message"] == "msg 5"

    def test_entry_has_required_fields(self):
        """
        验证entry、has、required、fields相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        logger = PluginLogger(plugin_id="p1")
        logger.info("test")
        entry = logger.get_entries()[0]
        assert "timestamp" in entry
        assert "level" in entry
        assert "message" in entry
        assert "plugin_id" in entry
        assert entry["plugin_id"] == "p1"


class TestLogManager:
    """
    封装与TestLogManager相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def setup_method(self):
        """
        处理setup、method相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        manager = LogManager()
        for pid in list(manager._loggers.keys()):
            manager.remove_logger(pid)

    def test_singleton(self):
        """
        验证singleton相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        m1 = LogManager()
        m2 = LogManager()
        assert m1 is m2

    def test_get_logger_creates_new(self):
        """
        验证get、logger、creates、new相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        manager = LogManager()
        logger = manager.get_logger("plugin-abc")
        assert isinstance(logger, PluginLogger)
        assert logger.plugin_id == "plugin-abc"

    def test_get_logger_same_instance(self):
        """
        验证get、logger、same、instance相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        manager = LogManager()
        l1 = manager.get_logger("plugin-x")
        l2 = manager.get_logger("plugin-x")
        assert l1 is l2

    def test_remove_logger(self):
        """
        验证remove、logger相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        manager = LogManager()
        manager.get_logger("plugin-rm")
        manager.remove_logger("plugin-rm")
        assert "plugin-rm" not in manager.list_plugin_ids()

    def test_list_plugin_ids(self):
        """
        验证list、plugin、ids相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        manager = LogManager()
        manager.get_logger("p-a")
        manager.get_logger("p-b")
        ids = manager.list_plugin_ids()
        assert "p-a" in ids
        assert "p-b" in ids

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'plugins'))

import pytest
from plugin_logger import LogManager, PluginLogger


class TestPluginLogger:
    def test_default_level_is_debug(self):
        logger = PluginLogger(plugin_id="p1")
        assert logger.level == "DEBUG"

    def test_set_level_valid(self):
        logger = PluginLogger(plugin_id="p1")
        logger.level = "INFO"
        assert logger.level == "INFO"

    def test_set_level_case_insensitive(self):
        logger = PluginLogger(plugin_id="p1")
        logger.level = "warning"
        assert logger.level == "WARNING"

    def test_set_level_invalid_raises(self):
        logger = PluginLogger(plugin_id="p1")
        with pytest.raises(ValueError):
            logger.level = "VERBOSE"

    def test_log_debug_filtered_when_level_info(self):
        logger = PluginLogger(plugin_id="p1")
        logger.level = "INFO"
        logger.debug("should be filtered")
        entries = logger.get_entries()
        assert len(entries) == 0

    def test_log_info_passes_when_level_info(self):
        logger = PluginLogger(plugin_id="p1")
        logger.level = "INFO"
        logger.info("visible message")
        entries = logger.get_entries()
        assert len(entries) == 1
        assert entries[0]["message"] == "visible message"
        assert entries[0]["level"] == "INFO"

    def test_log_error_passes_when_level_info(self):
        logger = PluginLogger(plugin_id="p1")
        logger.level = "INFO"
        logger.error("error msg")
        entries = logger.get_entries()
        assert len(entries) == 1
        assert entries[0]["level"] == "ERROR"

    def test_all_log_methods(self):
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
        logger = PluginLogger(plugin_id="p1")
        for i in range(10):
            logger.info(f"msg {i}")
        entries = logger.get_entries(limit=3, offset=2)
        assert len(entries) == 3
        assert entries[0]["message"] == "msg 2"

    def test_extra_kwargs_stored(self):
        logger = PluginLogger(plugin_id="p1")
        logger.info("hello", user="alice", count=5)
        entries = logger.get_entries()
        assert entries[0]["extra"] == {"user": "alice", "count": 5}

    def test_clear(self):
        logger = PluginLogger(plugin_id="p1")
        logger.info("msg")
        logger.clear()
        assert logger.get_entries() == []

    def test_maxlen_respected(self):
        logger = PluginLogger(plugin_id="p1", max_entries=5)
        for i in range(10):
            logger.info(f"msg {i}")
        entries = logger.get_entries()
        assert len(entries) == 5
        assert entries[0]["message"] == "msg 5"

    def test_entry_has_required_fields(self):
        logger = PluginLogger(plugin_id="p1")
        logger.info("test")
        entry = logger.get_entries()[0]
        assert "timestamp" in entry
        assert "level" in entry
        assert "message" in entry
        assert "plugin_id" in entry
        assert entry["plugin_id"] == "p1"


class TestLogManager:
    def setup_method(self):
        manager = LogManager()
        for pid in list(manager._loggers.keys()):
            manager.remove_logger(pid)

    def test_singleton(self):
        m1 = LogManager()
        m2 = LogManager()
        assert m1 is m2

    def test_get_logger_creates_new(self):
        manager = LogManager()
        logger = manager.get_logger("plugin-abc")
        assert isinstance(logger, PluginLogger)
        assert logger.plugin_id == "plugin-abc"

    def test_get_logger_same_instance(self):
        manager = LogManager()
        l1 = manager.get_logger("plugin-x")
        l2 = manager.get_logger("plugin-x")
        assert l1 is l2

    def test_remove_logger(self):
        manager = LogManager()
        manager.get_logger("plugin-rm")
        manager.remove_logger("plugin-rm")
        assert "plugin-rm" not in manager.list_plugin_ids()

    def test_list_plugin_ids(self):
        manager = LogManager()
        manager.get_logger("p-a")
        manager.get_logger("p-b")
        ids = manager.list_plugin_ids()
        assert "p-a" in ids
        assert "p-b" in ids

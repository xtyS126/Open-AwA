"""
测试统一阈值配置模块。
验证默认值正确性及环境变量覆盖机制。
"""
import os
from importlib import reload

import pytest

from config import thresholds


class TestThresholdsDefaults:
    """测试所有阈值的默认值"""

    def test_capabilities_cache_ttl_default(self):
        assert thresholds.CAPABILITIES_CACHE_TTL == 30.0

    def test_compaction_message_threshold_default(self):
        assert thresholds.COMPACTION_MESSAGE_THRESHOLD == 40

    def test_max_history_message_chars_default(self):
        assert thresholds.MAX_HISTORY_MESSAGE_CHARS == 5_000

    def test_summary_output_tokens_default(self):
        assert thresholds.SUMMARY_OUTPUT_TOKENS == 4_096

    def test_reserved_tokens_min_default(self):
        assert thresholds.RESERVED_TOKENS_MIN == 8_000

    def test_buffer_tokens_default(self):
        assert thresholds.BUFFER_TOKENS == 20_000

    def test_compaction_tool_output_max_chars_default(self):
        assert thresholds.COMPACTION_TOOL_OUTPUT_MAX_CHARS == 2_000

    def test_max_consecutive_failures_default(self):
        assert thresholds.MAX_CONSECUTIVE_FAILURES == 3

    def test_micro_compact_keep_recent_default(self):
        assert thresholds.MICRO_COMPACT_KEEP_RECENT == 5

    def test_max_tool_output_chars_default(self):
        assert thresholds.MAX_TOOL_OUTPUT_CHARS == 10_000

    def test_max_tool_result_chars_default(self):
        assert thresholds.MAX_TOOL_RESULT_CHARS == 8_000

    def test_max_tool_event_result_chars_default(self):
        assert thresholds.MAX_TOOL_EVENT_RESULT_CHARS == 2_000

    def test_stream_max_retries_default(self):
        assert thresholds.STREAM_MAX_RETRIES == 2

    def test_stream_chunk_timeout_seconds_default(self):
        assert thresholds.STREAM_CHUNK_TIMEOUT_SECONDS == 120.0

    def test_output_token_recovery_max_retries_default(self):
        assert thresholds.OUTPUT_TOKEN_RECOVERY_MAX_RETRIES == 3

    def test_output_token_recovery_threshold_default(self):
        assert thresholds.OUTPUT_TOKEN_RECOVERY_THRESHOLD == 64_000

    def test_hook_timeout_seconds_default(self):
        assert thresholds.HOOK_TIMEOUT_SECONDS == 30.0

    def test_hook_timing_display_threshold_ms_default(self):
        assert thresholds.HOOK_TIMING_DISPLAY_THRESHOLD_MS == 500


class TestThresholdsEnvOverride:
    """测试环境变量覆盖机制"""

    def test_env_override_int(self, monkeypatch):
        """OPENAWAS_COMPACTION_MESSAGE_THRESHOLD=100 应覆盖默认值 40"""
        monkeypatch.setenv("OPENAWAS_COMPACTION_MESSAGE_THRESHOLD", "100")
        reload(thresholds)
        try:
            assert thresholds.COMPACTION_MESSAGE_THRESHOLD == 100
        finally:
            monkeypatch.delenv("OPENAWAS_COMPACTION_MESSAGE_THRESHOLD", raising=False)
            reload(thresholds)

    def test_env_override_float(self, monkeypatch):
        """OPENAWAS_CAPABILITIES_CACHE_TTL=60.0 应覆盖默认值 30.0"""
        monkeypatch.setenv("OPENAWAS_CAPABILITIES_CACHE_TTL", "60.0")
        reload(thresholds)
        try:
            assert thresholds.CAPABILITIES_CACHE_TTL == 60.0
        finally:
            monkeypatch.delenv("OPENAWAS_CAPABILITIES_CACHE_TTL", raising=False)
            reload(thresholds)

    def test_env_override_hook_timeout(self, monkeypatch):
        """OPENAWAS_HOOK_TIMEOUT_SECONDS=10.0 应覆盖默认值 30.0"""
        monkeypatch.setenv("OPENAWAS_HOOK_TIMEOUT_SECONDS", "10.0")
        reload(thresholds)
        try:
            assert thresholds.HOOK_TIMEOUT_SECONDS == 10.0
        finally:
            monkeypatch.delenv("OPENAWAS_HOOK_TIMEOUT_SECONDS", raising=False)
            reload(thresholds)

    def test_env_override_stream_max_retries(self, monkeypatch):
        """OPENAWAS_STREAM_MAX_RETRIES=5 应覆盖默认值 2"""
        monkeypatch.setenv("OPENAWAS_STREAM_MAX_RETRIES", "5")
        reload(thresholds)
        try:
            assert thresholds.STREAM_MAX_RETRIES == 5
        finally:
            monkeypatch.delenv("OPENAWAS_STREAM_MAX_RETRIES", raising=False)
            reload(thresholds)


class TestThresholdsBackwardCompat:
    """测试向后兼容：各模块仍可正常导入阈值常量"""

    def test_compaction_manager_exports_max_consecutive_failures(self):
        from core.compaction_manager import MAX_CONSECUTIVE_FAILURES
        assert MAX_CONSECUTIVE_FAILURES == 3

    def test_compaction_manager_exports_config_defaults(self):
        from core.compaction_manager import CompactionConfig
        config = CompactionConfig()
        assert config.buffer_tokens == thresholds.BUFFER_TOKENS
        assert config.keep_tokens == thresholds.RESERVED_TOKENS_MIN
        assert config.summary_output_tokens == thresholds.SUMMARY_OUTPUT_TOKENS
        assert config.tool_output_max_chars == thresholds.COMPACTION_TOOL_OUTPUT_MAX_CHARS

    def test_agent_helpers_exports_thresholds(self):
        from core.agent_helpers import COMPACTION_MESSAGE_THRESHOLD, MAX_HISTORY_MESSAGE_CHARS
        assert COMPACTION_MESSAGE_THRESHOLD == thresholds.COMPACTION_MESSAGE_THRESHOLD
        assert MAX_HISTORY_MESSAGE_CHARS == thresholds.MAX_HISTORY_MESSAGE_CHARS

    def test_hook_manager_exports_thresholds(self):
        from core.hook_manager import HOOK_TIMING_DISPLAY_THRESHOLD_MS
        assert HOOK_TIMING_DISPLAY_THRESHOLD_MS == thresholds.HOOK_TIMING_DISPLAY_THRESHOLD_MS

    def test_execution_support_exports_thresholds(self):
        from core.execution_support import MAX_TOOL_EVENT_RESULT_CHARS, MAX_TOOL_RESULT_CHARS
        assert MAX_TOOL_RESULT_CHARS == thresholds.MAX_TOOL_RESULT_CHARS
        assert MAX_TOOL_EVENT_RESULT_CHARS == thresholds.MAX_TOOL_EVENT_RESULT_CHARS

    def test_tool_registry_exports_thresholds(self):
        from core.tool_registry import ToolRegistry
        assert ToolRegistry.MAX_OUTPUT_CHARS == thresholds.MAX_TOOL_OUTPUT_CHARS
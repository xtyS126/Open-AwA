"""
追踪日志器单元测试。
"""

import pytest
import tempfile
import json
import time
import threading
from pathlib import Path
from core.trace_logger import TraceLogger, TraceConfig, TraceLevel, TraceSpan, get_trace_logger, set_trace_logger


class TestTraceConfig:
    """追踪配置测试套件。"""

    def test_default_config(self):
        """测试默认配置。"""
        config = TraceConfig()
        assert Path(config.log_dir).name == "traces"
        assert "var" in Path(config.log_dir).parts
        assert config.min_level == TraceLevel.INFO
        assert config.enable_redaction is True
        assert config.max_message_length == 10000
        assert config.buffer_size == 100
        assert config.flush_interval_seconds == 5.0
        assert "password" in config.redacted_fields
        assert "token" in config.redacted_fields

    def test_custom_config(self):
        """测试自定义配置。"""
        config = TraceConfig(
            log_dir="/tmp/test_traces",
            min_level=TraceLevel.DEBUG,
            enable_redaction=False,
            max_message_length=5000,
            buffer_size=50,
            flush_interval_seconds=10.0,
        )
        assert config.log_dir == "/tmp/test_traces"
        assert config.min_level == TraceLevel.DEBUG
        assert config.enable_redaction is False
        assert config.max_message_length == 5000
        assert config.buffer_size == 50
        assert config.flush_interval_seconds == 10.0

    def test_config_validation_max_message_length(self):
        """测试 max_message_length 校验。"""
        with pytest.raises(ValueError, match="max_message_length"):
            TraceConfig(max_message_length=10)

    def test_config_validation_buffer_size(self):
        """测试 buffer_size 校验。"""
        with pytest.raises(ValueError, match="buffer_size"):
            TraceConfig(buffer_size=0)

    def test_config_validation_flush_interval(self):
        """测试 flush_interval_seconds 校验。"""
        with pytest.raises(ValueError, match="flush_interval_seconds"):
            TraceConfig(flush_interval_seconds=-1)


class TestTraceLogger:
    """追踪日志器测试套件。"""

    def test_initial_state(self):
        """测试初始状态。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TraceConfig(log_dir=tmpdir)
            logger = TraceLogger(config)
            assert logger._current_trace_id is None
            assert logger._current_span_id is None

    def test_generate_trace_id(self):
        """测试 TraceId 生成。"""
        logger = TraceLogger()
        trace_id = logger.generate_trace_id()
        assert trace_id is not None
        assert len(trace_id) == 36  # UUID 格式

        # 每次生成应该唯一
        trace_id2 = logger.generate_trace_id()
        assert trace_id != trace_id2

    def test_generate_span_id(self):
        """测试 SpanId 生成。"""
        logger = TraceLogger()
        span_id = logger.generate_span_id()
        assert span_id is not None
        assert len(span_id) == 8

    def test_set_and_clear_trace_context(self):
        """测试设置和清除追踪上下文。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TraceConfig(log_dir=tmpdir)
            logger = TraceLogger(config)

            logger.set_trace_context("trace-123", "span-456")
            assert logger._current_trace_id == "trace-123"
            assert logger._current_span_id == "span-456"

            logger.clear_trace_context()
            assert logger._current_trace_id is None
            assert logger._current_span_id is None

    def test_set_trace_context_auto_generates_span(self):
        """测试设置追踪上下文时自动生成 span_id。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TraceConfig(log_dir=tmpdir)
            logger = TraceLogger(config)

            logger.set_trace_context("trace-123")
            assert logger._current_trace_id == "trace-123"
            assert logger._current_span_id is not None
            assert len(logger._current_span_id) == 8

    def test_trace_context_manager(self):
        """测试追踪上下文管理器。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TraceConfig(log_dir=tmpdir)
            logger = TraceLogger(config)

            with logger.trace_context("my-trace") as ctx:
                assert ctx["trace_id"] == "my-trace"
                assert ctx["span_id"] is not None
                assert logger._current_trace_id == "my-trace"

            # 退出后应恢复为 None
            assert logger._current_trace_id is None

    def test_trace_context_manager_auto_generates_trace_id(self):
        """测试上下文管理器自动生成 trace_id。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TraceConfig(log_dir=tmpdir)
            logger = TraceLogger(config)

            with logger.trace_context() as ctx:
                assert ctx["trace_id"] is not None
                assert len(ctx["trace_id"]) == 36

    def test_trace_context_manager_restores_previous(self):
        """测试上下文管理器恢复之前的上下文。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TraceConfig(log_dir=tmpdir)
            logger = TraceLogger(config)

            logger.set_trace_context("outer-trace", "outer-span")

            with logger.trace_context("inner-trace") as ctx:
                assert logger._current_trace_id == "inner-trace"

            # 恢复外层上下文
            assert logger._current_trace_id == "outer-trace"
            assert logger._current_span_id == "outer-span"

            logger.clear_trace_context()

    def test_log_levels(self):
        """测试日志级别过滤。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TraceConfig(log_dir=tmpdir, min_level=TraceLevel.WARNING, buffer_size=1)
            logger = TraceLogger(config)

            # DEBUG 和 INFO 应该被过滤
            logger.debug("debug message")
            logger.info("info message")

            # WARNING 及以上应该被记录
            logger.warning("warning message")
            logger.error("error message")

            logger.flush()

            # 读取日志文件
            log_files = list(Path(tmpdir).glob("trace_*.jsonl"))
            assert len(log_files) == 1

            with open(log_files[0], "r", encoding="utf-8") as f:
                lines = f.readlines()
                # 只有 WARNING 和 ERROR 两条
                assert len(lines) == 2

                log1 = json.loads(lines[0])
                assert log1["level"] == "warning"

                log2 = json.loads(lines[1])
                assert log2["level"] == "error"

    def test_log_message_truncation(self):
        """测试消息截断。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TraceConfig(log_dir=tmpdir, max_message_length=100, buffer_size=1)
            logger = TraceLogger(config)

            long_message = "x" * 200
            logger.info(long_message)
            logger.flush()

            log_files = list(Path(tmpdir).glob("trace_*.jsonl"))
            with open(log_files[0], "r", encoding="utf-8") as f:
                entry = json.loads(f.readline())
                assert len(entry["message"]) == 100

    def test_sensitive_data_redaction(self):
        """测试敏感数据脱敏。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TraceConfig(log_dir=tmpdir, enable_redaction=True, buffer_size=1)
            logger = TraceLogger(config)

            logger.info("test", data={
                "username": "testuser",
                "password": "secret123",
                "api_key": "sk-123456",
                "token": "bearer_token_xyz",
            })
            logger.flush()

            log_files = list(Path(tmpdir).glob("trace_*.jsonl"))
            with open(log_files[0], "r", encoding="utf-8") as f:
                entry = json.loads(f.readline())
                assert entry["data"]["username"] == "testuser"
                assert entry["data"]["password"] == "***REDACTED***"
                assert entry["data"]["api_key"] == "***REDACTED***"
                assert entry["data"]["token"] == "***REDACTED***"

    def test_sensitive_data_redaction_disabled(self):
        """测试关闭脱敏功能。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TraceConfig(log_dir=tmpdir, enable_redaction=False, buffer_size=1)
            logger = TraceLogger(config)

            logger.info("test", data={"password": "secret123"})
            logger.flush()

            log_files = list(Path(tmpdir).glob("trace_*.jsonl"))
            with open(log_files[0], "r", encoding="utf-8") as f:
                entry = json.loads(f.readline())
                assert entry["data"]["password"] == "secret123"

    def test_nested_redaction(self):
        """测试嵌套字典脱敏。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TraceConfig(log_dir=tmpdir, enable_redaction=True, buffer_size=1)
            logger = TraceLogger(config)

            logger.info("test", data={
                "outer": "safe",
                "inner": {
                    "password": "nested_secret",
                    "safe_field": "safe_value",
                },
            })
            logger.flush()

            log_files = list(Path(tmpdir).glob("trace_*.jsonl"))
            with open(log_files[0], "r", encoding="utf-8") as f:
                entry = json.loads(f.readline())
                assert entry["data"]["outer"] == "safe"
                assert entry["data"]["inner"]["password"] == "***REDACTED***"
                assert entry["data"]["inner"]["safe_field"] == "safe_value"

    def test_convenience_methods(self):
        """测试便捷日志方法。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TraceConfig(log_dir=tmpdir, min_level=TraceLevel.DEBUG, buffer_size=10)
            logger = TraceLogger(config)

            logger.debug("debug msg")
            logger.info("info msg")
            logger.warning("warning msg")
            logger.error("error msg")
            logger.critical("critical msg")

            logger.flush()

            log_files = list(Path(tmpdir).glob("trace_*.jsonl"))
            with open(log_files[0], "r", encoding="utf-8") as f:
                lines = f.readlines()
                assert len(lines) == 5
                levels = [json.loads(line)["level"] for line in lines]
                assert levels == ["debug", "info", "warning", "error", "critical"]

    def test_log_with_kwargs(self):
        """测试通过 kwargs 传递额外字段。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TraceConfig(log_dir=tmpdir, buffer_size=1)
            logger = TraceLogger(config)

            logger.info("test", user_id="u123", action="login")
            logger.flush()

            log_files = list(Path(tmpdir).glob("trace_*.jsonl"))
            with open(log_files[0], "r", encoding="utf-8") as f:
                entry = json.loads(f.readline())
                assert entry["user_id"] == "u123"
                assert entry["action"] == "login"

    def test_concurrent_logging(self):
        """测试并发日志记录。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TraceConfig(log_dir=tmpdir, buffer_size=200)
            logger = TraceLogger(config)

            def log_worker(worker_id, count):
                for i in range(count):
                    logger.info(f"worker-{worker_id} msg-{i}")
                logger.flush()

            threads = []
            for i in range(5):
                t = threading.Thread(target=log_worker, args=(i, 10))
                threads.append(t)
                t.start()

            for t in threads:
                t.join()

            logger.flush()

            log_files = list(Path(tmpdir).glob("trace_*.jsonl"))
            assert len(log_files) == 1

            with open(log_files[0], "r", encoding="utf-8") as f:
                lines = f.readlines()
                # 5 个线程各 10 条
                assert len(lines) == 50


class TestTraceSpan:
    """追踪跨度测试套件。"""

    def test_trace_span_success(self):
        """测试成功操作的跨度记录。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TraceConfig(log_dir=tmpdir, buffer_size=10)
            logger = TraceLogger(config)

            with logger.trace_operation("test_op") as span:
                assert isinstance(span, TraceSpan)
                assert span.operation == "test_op"
                assert span.start_time is not None

            logger.flush()

            log_files = list(Path(tmpdir).glob("trace_*.jsonl"))
            with open(log_files[0], "r", encoding="utf-8") as f:
                lines = f.readlines()
                # 开始和结束各一条
                assert len(lines) == 2

                start_entry = json.loads(lines[0])
                assert "开始操作" in start_entry["message"]

                end_entry = json.loads(lines[1])
                assert "操作完成" in end_entry["message"]
                assert "duration_seconds" in end_entry["data"]

    def test_trace_span_error(self):
        """测试失败操作的跨度记录。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TraceConfig(log_dir=tmpdir, buffer_size=10)
            logger = TraceLogger(config)

            with pytest.raises(ValueError):
                with logger.trace_operation("failing_op"):
                    raise ValueError("test error")

            logger.flush()

            log_files = list(Path(tmpdir).glob("trace_*.jsonl"))
            with open(log_files[0], "r", encoding="utf-8") as f:
                lines = f.readlines()
                assert len(lines) == 2

                end_entry = json.loads(lines[1])
                assert "操作失败" in end_entry["message"]
                assert "test error" in end_entry["data"]["error"]


class TestGlobalTraceLogger:
    """全局追踪日志器测试套件。"""

    def test_get_trace_logger_creates_singleton(self):
        """测试获取全局日志器单例。"""
        import core.trace_logger as module
        # 重置全局状态
        module._global_logger = None

        logger1 = get_trace_logger()
        logger2 = get_trace_logger()
        assert logger1 is logger2

        # 清理
        module._global_logger = None

    def test_set_trace_logger(self):
        """测试设置全局日志器。"""
        import core.trace_logger as module
        module._global_logger = None

        custom_logger = TraceLogger()
        set_trace_logger(custom_logger)
        assert get_trace_logger() is custom_logger

        # 清理
        module._global_logger = None

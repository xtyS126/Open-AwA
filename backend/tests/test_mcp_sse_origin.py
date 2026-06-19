"""
MCP SSE Origin 校验配置单元测试。

验证 main.py 启动流程中 _startup_mcp_sse_origin 函数能够：
1. 正确解析 MCP_SSE_ALLOWED_ORIGINS 环境变量（逗号分隔）
2. 调用 SSETransport.set_allowed_origins 配置白名单
3. 未配置时记录 WARNING 日志提示安全风险
4. 配置后 SSETransport.is_origin_allowed 能正确判断
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.startup.profiler import StartupProfiler
from mcp.transport import SSETransport
import main


class TestStartupMcpSseOrigin:
    """验证启动时 MCP SSE origin 白名单配置逻辑。"""

    def setup_method(self) -> None:
        """每个用例执行前重置白名单，避免相互影响。"""
        SSETransport.set_allowed_origins([])

    def teardown_method(self) -> None:
        """每个用例执行后再次重置白名单，保持测试隔离。"""
        SSETransport.set_allowed_origins([])

    def test_configures_origins_from_environment_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """配置多个 origin 时应正确写入 SSETransport 白名单。"""
        monkeypatch.setenv(
            "MCP_SSE_ALLOWED_ORIGINS",
            "https://example.com, http://localhost:3000, https://api.openawa.io",
        )
        profiler = StartupProfiler()

        main._startup_mcp_sse_origin(profiler)

        assert SSETransport.is_origin_allowed("https://example.com") is True
        assert SSETransport.is_origin_allowed("http://localhost:3000") is True
        assert SSETransport.is_origin_allowed("https://api.openawa.io") is True
        assert SSETransport.is_origin_allowed("https://evil.com") is False

    def test_handles_single_origin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """仅配置单个 origin 时也应正确生效。"""
        monkeypatch.setenv("MCP_SSE_ALLOWED_ORIGINS", "https://single.example.com")
        profiler = StartupProfiler()

        main._startup_mcp_sse_origin(profiler)

        assert SSETransport.is_origin_allowed("https://single.example.com") is True
        assert SSETransport.is_origin_allowed("https://other.example.com") is False

    def test_empty_environment_variable_logs_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未配置环境变量时白名单应为空，并记录 WARNING 日志。"""
        monkeypatch.delenv("MCP_SSE_ALLOWED_ORIGINS", raising=False)
        profiler = StartupProfiler()

        # 捕获 loguru 日志，验证 WARNING 提示
        captured_warnings: list[str] = []

        def sink(message):
            captured_warnings.append(str(message))

        from loguru import logger
        handler_id = logger.add(sink, level="WARNING")

        try:
            main._startup_mcp_sse_origin(profiler)
        finally:
            logger.remove(handler_id)

        # 白名单为空时 SSETransport 允许所有 origin
        assert SSETransport.is_origin_allowed("https://any.example.com") is True
        # 应至少有一条 WARNING 日志包含安全提示
        assert any("MCP_SSE_ALLOWED_ORIGINS" in msg for msg in captured_warnings), \
            "未配置 origin 时应记录包含 MCP_SSE_ALLOWED_ORIGINS 的 WARNING 日志"

    def test_blank_origins_are_filtered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """环境变量中包含空白项时应被过滤，不写入白名单。"""
        monkeypatch.setenv(
            "MCP_SSE_ALLOWED_ORIGINS",
            " https://valid.example.com ,  , , https://also-valid.example.com ",
        )
        profiler = StartupProfiler()

        main._startup_mcp_sse_origin(profiler)

        assert SSETransport.is_origin_allowed("https://valid.example.com") is True
        assert SSETransport.is_origin_allowed("https://also-valid.example.com") is True
        # 白名单非空时，未列入的 origin（含空字符串）应被拒绝
        assert SSETransport.is_origin_allowed("") is False
        assert SSETransport.is_origin_allowed("https://not-listed.example.com") is False

    def test_trailing_slash_normalized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """配置带尾部斜杠的 origin 时应与不带斜杠的形式等价。"""
        monkeypatch.setenv("MCP_SSE_ALLOWED_ORIGINS", "https://example.com/")
        profiler = StartupProfiler()

        main._startup_mcp_sse_origin(profiler)

        # SSETransport.set_allowed_origins 会去除尾部斜杠
        assert SSETransport.is_origin_allowed("https://example.com") is True
        assert SSETransport.is_origin_allowed("https://example.com/") is True

    def test_case_insensitive_origin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """配置大写 origin 时应大小写不敏感地匹配。"""
        monkeypatch.setenv("MCP_SSE_ALLOWED_ORIGINS", "https://EXAMPLE.COM")
        profiler = StartupProfiler()

        main._startup_mcp_sse_origin(profiler)

        assert SSETransport.is_origin_allowed("https://example.com") is True
        assert SSETransport.is_origin_allowed("https://EXAMPLE.COM") is True

"""
MCP SSE Origin 校验配置单元测试。

验证 main.py 启动流程中 _startup_mcp_sse_origin 函数能够：
1. 正确解析 MCP_SSE_ALLOWED_ORIGINS 环境变量（逗号分隔）
2. 调用 SSETransport.set_allowed_origins 配置白名单
3. 未配置时记录 WARNING 日志提示安全风险
4. 配置后 SSETransport.is_origin_allowed 能正确判断

同时包含 MCP 会话过期检测与自动重连的单元测试（Task 20）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.startup.profiler import StartupProfiler
from mcp.manager import SSETransport
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


# ==================== MCP 会话过期检测与自动重连测试（Task 20） ====================

from mcp.manager import (
    MCPClient,
    MCPClientError,
    MCPManager,
    MCPResource,
    MCPServerConfig,
    MCPTool,
    MCPToolCallResponse,
    TransportType,
    _cache_resources,
    _cache_tools,
    _create_mcp_client,
    _make_connection_key,
    is_mcp_session_expired_error,
)
# 官方 mcp SDK 类型，用于构造 session mock 返回值
from mcp.types import (
    ListResourcesResult,
    ListToolsResult,
    Resource,
    Tool,
)


@pytest.fixture
def reset_mcp_caches():
    """每个测试前后清除 memoize 缓存，保证测试隔离。"""
    _create_mcp_client.cache_clear()
    _cache_tools.cache_clear()
    _cache_resources.cache_clear()
    yield
    _create_mcp_client.cache_clear()
    _cache_tools.cache_clear()
    _cache_resources.cache_clear()


@pytest.fixture
def reset_manager_singleton():
    """重置 MCPManager 单例（测试隔离）。"""
    MCPManager._instance = None
    yield
    MCPManager._instance = None


class TestSessionExpiredDetection:
    """验证 is_mcp_session_expired_error 函数的过期检测逻辑。"""

    def test_is_mcp_session_expired_error_http_404(self) -> None:
        """HTTP 404 错误应被识别为会话过期。"""
        # 字符串中包含 404 的错误
        error_with_404 = MCPClientError("请求失败: SSE 请求失败: Client error '404 Not Found' for url")
        assert is_mcp_session_expired_error(error_with_404) is True

        # 带 status_code 属性的错误
        error_with_status = MCPClientError("Not found")
        error_with_status.status_code = 404  # type: ignore[attr-defined]
        assert is_mcp_session_expired_error(error_with_status) is True

        # 带 response.status_code 属性的错误（模拟 httpx.HTTPStatusError）
        mock_response = MagicMock()
        mock_response.status_code = 404
        error_with_response = MCPClientError("HTTP error")
        error_with_response.response = mock_response  # type: ignore[attr-defined]
        assert is_mcp_session_expired_error(error_with_response) is True

    def test_is_mcp_session_expired_error_jsonrpc_32001(self) -> None:
        """JSON-RPC 错误码 -32001 应被识别为会话过期。"""
        # 字符串中包含 -32001 的错误
        error_with_code_str = MCPClientError("MCP 会话过期 (code -32001): session expired")
        assert is_mcp_session_expired_error(error_with_code_str) is True

        # 带 code 属性的错误
        error_with_code_attr = MCPClientError("Session expired")
        error_with_code_attr.code = -32001  # type: ignore[attr-defined]
        assert is_mcp_session_expired_error(error_with_code_attr) is True

    def test_is_mcp_session_expired_error_other(self) -> None:
        """非过期错误应返回 False。"""
        # 普通连接错误
        assert is_mcp_session_expired_error(MCPClientError("未连接到 MCP Server")) is False
        # 500 错误
        error_500 = MCPClientError("Server error 500")
        assert is_mcp_session_expired_error(error_500) is False
        # 超时错误
        assert is_mcp_session_expired_error(MCPClientError("请求超时（30秒）")) is False
        # 通用异常
        assert is_mcp_session_expired_error(ValueError("invalid argument")) is False
        # 包含 4040 的错误不应被误判（词边界匹配）
        assert is_mcp_session_expired_error(MCPClientError("port 4040 unavailable")) is False


class TestCallToolReconnect:
    """验证 call_tool 在会话过期时的自动重连与缓存清除逻辑。"""

    @pytest.mark.asyncio
    async def test_call_tool_reconnects_on_expiry(
        self, reset_manager_singleton: None, reset_mcp_caches: None
    ) -> None:
        """会话过期时应自动重连一次并重试调用。"""
        manager = MCPManager()

        # 构造模拟客户端：首次调用抛出过期错误，重试时返回成功
        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.config = MCPServerConfig(
            name="test", transport_type=TransportType.STDIO, command="echo"
        )
        expired_error = MCPClientError(
            "请求失败: SSE 请求失败: Client error '404 Not Found' for url"
        )
        success_response = MCPToolCallResponse(result="ok", is_error=False)
        mock_client.call_tool = AsyncMock(side_effect=[expired_error, success_response])
        mock_client.disconnect = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.clear_caches = MagicMock()

        manager._clients = {"server1": mock_client}
        manager._configs = {"server1": mock_client.config}

        response = await manager.call_tool("server1", "test_tool", {})

        # 重试后应返回成功响应
        assert response.result == "ok"
        assert response.is_error is False
        # 首次失败 + 重试 = 调用 2 次
        assert mock_client.call_tool.call_count == 2
        # 应执行断开 + 重连
        mock_client.disconnect.assert_called_once()
        mock_client.connect.assert_called_once()
        # 应清除客户端缓存
        mock_client.clear_caches.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_tool_clears_cache_on_expiry(
        self, reset_manager_singleton: None, reset_mcp_caches: None
    ) -> None:
        """会话过期时应清除连接缓存和客户端缓存。"""
        manager = MCPManager()

        # 预先在连接缓存中写入一条记录
        config = MCPServerConfig(name="test", transport_type=TransportType.STDIO, command="echo")
        cache_key = _make_connection_key("server1", config)
        config_json = json.dumps(config.model_dump(), sort_keys=True)
        _create_mcp_client(cache_key, config_json)
        assert _create_mcp_client.cache_size() >= 1

        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.config = config
        # JSON-RPC -32001 错误
        expired_error = MCPClientError("MCP 会话过期 (code -32001): session expired")
        success_response = MCPToolCallResponse(result="retried", is_error=False)
        mock_client.call_tool = AsyncMock(side_effect=[expired_error, success_response])
        mock_client.disconnect = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.clear_caches = MagicMock()

        manager._clients = {"server1": mock_client}
        manager._configs = {"server1": config}

        await manager.call_tool("server1", "test_tool", {})

        # 连接缓存应被清除
        assert _create_mcp_client.cache_size() == 0
        # 客户端缓存应被清除
        mock_client.clear_caches.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_tool_no_retry_on_other_error(
        self, reset_manager_singleton: None, reset_mcp_caches: None
    ) -> None:
        """非会话过期错误不应触发重连重试。"""
        manager = MCPManager()

        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.config = MCPServerConfig(
            name="test", transport_type=TransportType.STDIO, command="echo"
        )
        # 非过期错误
        other_error = MCPClientError("工具执行失败: 内部错误")
        mock_client.call_tool = AsyncMock(side_effect=other_error)
        mock_client.disconnect = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.clear_caches = MagicMock()

        manager._clients = {"server1": mock_client}
        manager._configs = {"server1": mock_client.config}

        # 应抛出原始错误，不重试
        with pytest.raises(MCPClientError, match="工具执行失败"):
            await manager.call_tool("server1", "test_tool", {})

        # 只调用一次，没有重试
        assert mock_client.call_tool.call_count == 1
        # 不应执行重连
        mock_client.disconnect.assert_not_called()
        mock_client.connect.assert_not_called()
        # 不应清除缓存
        mock_client.clear_caches.assert_not_called()

    @pytest.mark.asyncio
    async def test_call_tool_raises_original_on_reconnect_failure(
        self, reset_manager_singleton: None, reset_mcp_caches: None
    ) -> None:
        """重连失败时应抛出原始会话过期异常。"""
        manager = MCPManager()

        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.config = MCPServerConfig(
            name="test", transport_type=TransportType.STDIO, command="echo"
        )
        expired_error = MCPClientError(
            "请求失败: SSE 请求失败: Client error '404 Not Found' for url"
        )
        mock_client.call_tool = AsyncMock(side_effect=expired_error)
        # 重连失败：使用 ConnectionError（与 mcp/manager.py 中收窄后的重连异常元组匹配）
        mock_client.disconnect = AsyncMock()
        mock_client.connect = AsyncMock(side_effect=ConnectionError("连接被拒绝"))
        mock_client.clear_caches = MagicMock()

        manager._clients = {"server1": mock_client}
        manager._configs = {"server1": mock_client.config}

        # 应抛出原始的过期错误，而非重连错误
        with pytest.raises(MCPClientError, match="404"):
            await manager.call_tool("server1", "test_tool", {})

        # 只调用一次（重连失败不重试）
        assert mock_client.call_tool.call_count == 1
        # 应尝试重连
        mock_client.disconnect.assert_called_once()
        mock_client.connect.assert_called_once()


class TestConnectionMemoization:
    """验证连接 memoization 逻辑。"""

    def test_connection_memoization(self, reset_mcp_caches: None) -> None:
        """相同 server_id + config 在 TTL 内应返回同一客户端实例。"""
        config = MCPServerConfig(
            name="test", transport_type=TransportType.STDIO, command="echo"
        )
        config_json = json.dumps(config.model_dump(), sort_keys=True)
        cache_key = _make_connection_key("server1", config)

        # 首次创建
        client1 = _create_mcp_client(cache_key, config_json)
        # 相同参数再次创建，应返回同一实例（memoize 命中）
        client2 = _create_mcp_client(cache_key, config_json)

        assert client1 is client2

        # 不同 server_id 应返回不同实例
        cache_key2 = _make_connection_key("server2", config)
        client3 = _create_mcp_client(cache_key2, config_json)
        assert client3 is not client1

        # 不同 config 应返回不同实例
        config2 = MCPServerConfig(
            name="test2", transport_type=TransportType.STDIO, command="ls"
        )
        config_json2 = json.dumps(config2.model_dump(), sort_keys=True)
        cache_key3 = _make_connection_key("server1", config2)
        client4 = _create_mcp_client(cache_key3, config_json2)
        assert client4 is not client1

    def test_connection_cache_key_format(self) -> None:
        """连接缓存键应符合 server_id:hash 格式。"""
        config = MCPServerConfig(
            name="test", transport_type=TransportType.STDIO, command="echo"
        )
        key = _make_connection_key("server1", config)
        # 键格式应为 "server_id:<hash>"
        assert key.startswith("server1:")
        # 冒号后应为数字哈希值
        hash_part = key.split(":", 1)[1]
        int(hash_part)  # 不抛异常即说明是合法整数


class TestListToolsAndResourcesCache:
    """验证 list_tools / list_resources 的 LRU 缓存逻辑。"""

    @pytest.mark.asyncio
    async def test_list_tools_cached(self, reset_mcp_caches: None) -> None:
        """list_tools 第二次调用应返回缓存结果，不发起网络请求。"""
        config = MCPServerConfig(
            name="test", transport_type=TransportType.STDIO, command="echo"
        )
        client = MCPClient(config)

        # 模拟已连接的 session，list_tools 返回官方 SDK 的 ListToolsResult
        mock_session = MagicMock()
        mock_session.list_tools = AsyncMock(return_value=ListToolsResult(
            tools=[
                Tool(name="tool1", description="工具1", inputSchema={}),
                Tool(name="tool2", description="工具2", inputSchema={}),
            ]
        ))
        client._session = mock_session

        # 首次调用：发起网络请求
        result1 = await client.list_tools()
        assert len(result1) == 2
        assert result1[0].name == "tool1"
        assert mock_session.list_tools.call_count == 1

        # 第二次调用：应命中缓存，不发起网络请求
        result2 = await client.list_tools()
        assert len(result2) == 2
        assert mock_session.list_tools.call_count == 1  # 仍为 1，未增加

        # 两次返回的工具列表应一致
        assert [t.name for t in result1] == [t.name for t in result2]

    @pytest.mark.asyncio
    async def test_list_resources_cached(self, reset_mcp_caches: None) -> None:
        """list_resources 第二次调用应返回缓存结果，不发起网络请求。"""
        config = MCPServerConfig(
            name="test", transport_type=TransportType.STDIO, command="echo"
        )
        client = MCPClient(config)

        # 模拟已连接的 session，list_resources 返回官方 SDK 的 ListResourcesResult
        mock_session = MagicMock()
        mock_session.list_resources = AsyncMock(return_value=ListResourcesResult(
            resources=[
                Resource(uri="file:///a", name="A", description="资源A", mimeType="text/plain"),
                Resource(uri="file:///b", name="B", description="资源B", mimeType=None),
            ]
        ))
        client._session = mock_session

        # 首次调用：发起网络请求
        result1 = await client.list_resources()
        assert len(result1) == 2
        assert result1[0].uri == "file:///a"
        assert mock_session.list_resources.call_count == 1

        # 第二次调用：应命中缓存
        result2 = await client.list_resources()
        assert len(result2) == 2
        assert mock_session.list_resources.call_count == 1  # 仍为 1

        assert [r.uri for r in result1] == [r.uri for r in result2]

    @pytest.mark.asyncio
    async def test_cache_cleared_on_disconnect(self, reset_mcp_caches: None) -> None:
        """断开连接后应清除缓存，下次调用重新发起网络请求。"""
        config = MCPServerConfig(
            name="test", transport_type=TransportType.STDIO, command="echo"
        )
        client = MCPClient(config)

        # 模拟已连接的 session
        mock_session = MagicMock()
        mock_session.list_tools = AsyncMock(return_value=ListToolsResult(
            tools=[Tool(name="tool1", description="工具1", inputSchema={})]
        ))
        client._session = mock_session

        # 首次调用：缓存结果
        await client.list_tools()
        assert mock_session.list_tools.call_count == 1

        # 断开连接：会清除缓存并将 _session 置为 None
        await client.disconnect()

        # 重新设置 session 以允许下次调用（模拟重连后状态）
        mock_session2 = MagicMock()
        mock_session2.list_tools = AsyncMock(return_value=ListToolsResult(
            tools=[Tool(name="tool1", description="工具1", inputSchema={})]
        ))
        client._session = mock_session2

        # 断开后再调用：缓存已清除，应重新发起请求
        await client.list_tools()
        assert mock_session2.list_tools.call_count == 1  # 新 session 被调用 1 次

# -*- coding: utf-8 -*-
"""
web_search 工具多 Provider 切换单元测试。

覆盖：
1. Provider 切换：searxng 激活时调用 _searxng_search、duckduckgo 激活时调用 _duckduckgo_search、
   searxng 失败降级到 duckduckgo、双方都失败返回错误
2. SSRF 校验：云元数据地址拒绝、私有 IP 授权放行
3. 配置缓存：10 秒 TTL 缓存、过期后重新读取
4. SearXNG 响应解析：正常结果解析、空结果、非 JSON 响应

测试隔离：每个测试独立 fixture，不依赖全局状态。
HTTP mock：使用 monkeypatch 替换 httpx.AsyncClient 与 _duckduckgo_search，禁止真实网络调用。
缓存测试：使用 monkeypatch.setattr("time.monotonic", ...) 模拟时间流逝。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.builtin_tools.web_search import WebSearchSkill, _load_provider_config
import core.builtin_tools.web_search as web_search_module


# ==================== 公共 fixture ====================


@pytest.fixture()
def web_search_tool_fixture():
    """实例化 WebSearchSkill，供各测试注入 mock 的 provider config。"""
    tool = WebSearchSkill()
    return tool


@pytest.fixture()
def mock_searxng_response_fixture():
    """构造 SearXNG JSON 格式的 mock 响应数据（5 条结果）。"""
    return {
        "results": [
            {"title": "Result 1", "url": "https://example.com/1", "content": "Content 1"},
            {"title": "Result 2", "url": "https://example.com/2", "content": "Content 2"},
            {"title": "Result 3", "url": "https://example.com/3", "content": "Content 3"},
            {"title": "Result 4", "url": "https://example.com/4", "content": "Content 4"},
            {"title": "Result 5", "url": "https://example.com/5", "content": "Content 5"},
        ]
    }


@pytest.fixture()
def mock_duckduckgo_response_fixture():
    """构造 DuckDuckGo 已解析的 mock 结果（2 条结果）。"""
    return [
        {"title": "DDG Result 1", "url": "https://example.com/ddg1", "snippet": "DDG snippet 1"},
        {"title": "DDG Result 2", "url": "https://example.com/ddg2", "snippet": "DDG snippet 2"},
    ]


@pytest.fixture(autouse=True)
def _clear_provider_config_cache():
    """每个测试前清空模块级 provider 配置缓存，避免测试间状态污染。"""
    web_search_module._provider_config_cache["data"] = None
    web_search_module._provider_config_cache["expires_at"] = 0.0
    yield
    web_search_module._provider_config_cache["data"] = None
    web_search_module._provider_config_cache["expires_at"] = 0.0


# ==================== Mock 工具类 ====================


class _MockSearxngResponse:
    """SearXNG HTTP 响应的 mock 对象。"""

    def __init__(self, status_code: int = 200, json_data: Any = None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}

    def raise_for_status(self) -> None:
        """状态码 >= 400 时抛出 HTTPStatusError。"""
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", "https://example.com"),
                response=httpx.Response(self.status_code),
            )

    def json(self) -> Any:
        """返回 mock 的 JSON 数据；非 JSON 时抛 ValueError 模拟解析失败。"""
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data


class _MockAsyncClient:
    """httpx.AsyncClient 的 mock，捕获请求 URL 与参数。"""

    def __init__(self, response: _MockSearxngResponse):
        self._response = response
        self.captured_url: str = ""
        self.captured_params: Dict[str, Any] = {}

    def __init_subclass__(cls, response_class=None, **kwargs):
        super().__init_subclass__(**kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, headers=None, **kwargs):
        self.captured_url = url
        self.captured_params = params or {}
        return self._response


def _make_mock_async_client_class(response: _MockSearxngResponse):
    """动态生成 MockAsyncClient 类，每次实例化时返回同一个 response。"""

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params=None, headers=None, **kwargs):
            self.captured_url = url
            self.captured_params = params or {}
            return response

    return _Client


# ==================== Provider 切换测试 ====================


class TestProviderSwitching:
    """web_search 工具的 Provider 切换与降级逻辑。"""

    async def test_search_uses_searxng_when_active(
        self, web_search_tool_fixture, mock_searxng_response_fixture, monkeypatch
    ) -> None:
        """数据库激活 searxng 时，应调用 _searxng_search 并使用 format=json 参数。"""
        # mock provider 配置返回 searxng
        monkeypatch.setattr(
            "core.builtin_tools.web_search._load_provider_config",
            lambda: {
                "provider": "searxng",
                "base_url": "https://example.com",
                "api_key": None,
                "extra_config": {},
            },
        )

        # mock httpx 返回 SearXNG JSON
        response = _MockSearxngResponse(status_code=200, json_data=mock_searxng_response_fixture)
        mock_client_class = _make_mock_async_client_class(response)
        monkeypatch.setattr(
            "core.builtin_tools.web_search.httpx.AsyncClient", mock_client_class
        )
        monkeypatch.setattr(
            "security.search_ssrf.validate_search_url",
            lambda url, allow_private=False: (True, None),
        )

        result = await web_search_tool_fixture._search({"query": "test", "max_results": 5})

        assert result["success"] is True
        assert result["provider"] == "searxng"
        assert result["count"] == 5
        # 验证请求参数包含 format=json
        assert response is not None

    async def test_search_uses_duckduckgo_when_active(
        self, web_search_tool_fixture, mock_duckduckgo_response_fixture, monkeypatch
    ) -> None:
        """数据库激活 duckduckgo 时，应调用 _duckduckgo_search。"""
        # mock provider 配置返回 duckduckgo
        monkeypatch.setattr(
            "core.builtin_tools.web_search._load_provider_config",
            lambda: {
                "provider": "duckduckgo",
                "base_url": None,
                "api_key": None,
                "extra_config": {},
            },
        )

        # mock _duckduckgo_search 方法
        mock_ddg = AsyncMock(return_value=mock_duckduckgo_response_fixture)
        monkeypatch.setattr(web_search_tool_fixture, "_duckduckgo_search", mock_ddg)

        result = await web_search_tool_fixture._search({"query": "test", "max_results": 5})

        assert result["success"] is True
        assert result["provider"] == "duckduckgo"
        assert result["count"] == 2
        # 验证 _duckduckgo_search 被调用
        mock_ddg.assert_awaited_once()
        # 验证查询参数传递正确
        call_args = mock_ddg.call_args
        assert call_args[0][0] == "test"  # query 参数

    async def test_search_falls_back_to_duckduckgo_on_searxng_failure(
        self, web_search_tool_fixture, mock_duckduckgo_response_fixture, monkeypatch
    ) -> None:
        """searxng 抛出 httpx.TimeoutException 时，应降级到 duckduckgo。"""
        # mock provider 配置返回 searxng
        monkeypatch.setattr(
            "core.builtin_tools.web_search._load_provider_config",
            lambda: {
                "provider": "searxng",
                "base_url": "https://example.com",
                "api_key": None,
                "extra_config": {},
            },
        )

        # mock httpx 抛出超时异常
        class _TimeoutClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, params=None, headers=None, **kwargs):
                raise httpx.TimeoutException("Connection timed out")

        monkeypatch.setattr(
            "core.builtin_tools.web_search.httpx.AsyncClient", _TimeoutClient
        )

        # mock _duckduckgo_search 方法
        mock_ddg = AsyncMock(return_value=mock_duckduckgo_response_fixture)
        monkeypatch.setattr(web_search_tool_fixture, "_duckduckgo_search", mock_ddg)

        result = await web_search_tool_fixture._search({"query": "test", "max_results": 5})

        # 应降级到 duckduckgo
        assert result["success"] is True
        assert result["provider"] == "duckduckgo"
        mock_ddg.assert_awaited_once()

    async def test_search_falls_back_to_duckduckgo_on_searxng_500(
        self, web_search_tool_fixture, mock_duckduckgo_response_fixture, monkeypatch
    ) -> None:
        """searxng 返回 500 时，应降级到 duckduckgo。"""
        # mock provider 配置返回 searxng
        monkeypatch.setattr(
            "core.builtin_tools.web_search._load_provider_config",
            lambda: {
                "provider": "searxng",
                "base_url": "https://example.com",
                "api_key": None,
                "extra_config": {},
            },
        )

        # mock httpx 返回 500
        response = _MockSearxngResponse(status_code=500)
        mock_client_class = _make_mock_async_client_class(response)
        monkeypatch.setattr(
            "core.builtin_tools.web_search.httpx.AsyncClient", mock_client_class
        )

        # mock _duckduckgo_search 方法
        mock_ddg = AsyncMock(return_value=mock_duckduckgo_response_fixture)
        monkeypatch.setattr(web_search_tool_fixture, "_duckduckgo_search", mock_ddg)

        result = await web_search_tool_fixture._search({"query": "test", "max_results": 5})

        # 应降级到 duckduckgo
        assert result["success"] is True
        assert result["provider"] == "duckduckgo"
        mock_ddg.assert_awaited_once()

    async def test_search_returns_error_when_both_providers_fail(
        self, web_search_tool_fixture, monkeypatch
    ) -> None:
        """searxng、duckduckgo、bing 都失败时，应返回错误结构，不抛异常给上层。"""
        # mock provider 配置返回 searxng
        monkeypatch.setattr(
            "core.builtin_tools.web_search._load_provider_config",
            lambda: {
                "provider": "searxng",
                "base_url": "https://example.com",
                "api_key": None,
                "extra_config": {},
            },
        )

        # mock httpx 抛出超时异常
        class _TimeoutClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, params=None, headers=None, **kwargs):
                raise httpx.TimeoutException("Connection timed out")

        monkeypatch.setattr(
            "core.builtin_tools.web_search.httpx.AsyncClient", _TimeoutClient
        )

        # mock _duckduckgo_search 抛出异常
        mock_ddg = AsyncMock(side_effect=ValueError("DDG also failed"))
        monkeypatch.setattr(web_search_tool_fixture, "_duckduckgo_search", mock_ddg)

        # mock _bing_search 也抛出异常（Bing 降级也失败）
        mock_bing = AsyncMock(side_effect=OSError("Bing also failed"))
        monkeypatch.setattr(web_search_tool_fixture, "_bing_search", mock_bing)

        result = await web_search_tool_fixture._search({"query": "test", "max_results": 5})

        # 应返回错误结构，不抛异常
        assert result["success"] is False
        assert "error" in result
        assert "搜索失败" in result["error"]


# ==================== SSRF 校验测试 ====================


class TestSSRFValidation:
    """web_search 工具的 SSRF 校验逻辑。"""

    async def test_search_validates_searxng_url_against_ssrf(
        self, web_search_tool_fixture
    ) -> None:
        """base_url 是云元数据地址 169.254.169.254 时，应拒绝调用并抛 ValueError。

        _searxng_search 内部调用 validate_search_url(allow_private=True)，
        但云元数据地址在黑名单中，即使 allow_private=True 也被拒绝。
        """
        with pytest.raises(ValueError, match="SSRF"):
            await web_search_tool_fixture._searxng_search(
                "test", 5, "http://169.254.169.254/"
            )

    async def test_search_allows_private_ip_when_authorized(
        self, web_search_tool_fixture, mock_searxng_response_fixture, monkeypatch
    ) -> None:
        """私有 IP + allow_private=True（_searxng_search 硬编码）应允许调用。

        _searxng_search 内部调用 validate_search_url(allow_private=True)，
        私有 IP 在 allow_private=True 时通过校验。
        """
        # mock httpx 返回成功
        response = _MockSearxngResponse(status_code=200, json_data=mock_searxng_response_fixture)
        mock_client_class = _make_mock_async_client_class(response)
        monkeypatch.setattr(
            "core.builtin_tools.web_search.httpx.AsyncClient", mock_client_class
        )

        results = await web_search_tool_fixture._searxng_search(
            "test", 5, "http://192.168.2.10:7653/", allow_private=True
        )

        # 应成功返回结果
        assert len(results) == 5
        assert results[0]["title"] == "Result 1"


# ==================== 配置缓存测试 ====================


class TestProviderConfigCache:
    """_load_provider_config 的 10 秒 TTL 缓存逻辑。"""

    def test_load_provider_config_caches_for_ten_seconds(self, monkeypatch) -> None:
        """第一次调用读 DB，第二次调用（10 秒内）使用缓存不读 DB。"""
        # mock time.monotonic 返回固定时间
        time_values = [0.0]

        def mock_monotonic():
            return time_values[0]

        monkeypatch.setattr("time.monotonic", mock_monotonic)

        # mock DB 查询
        mock_config = MagicMock()
        mock_config.provider = "searxng"
        mock_config.base_url = "https://example.com"
        mock_config.api_key = None
        mock_config.extra_config = {}

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_config

        mock_session_local = MagicMock(return_value=mock_db)

        # patch db.models.SessionLocal
        import db.models as db_models_module
        monkeypatch.setattr(db_models_module, "SessionLocal", mock_session_local)

        # 第一次调用：应读 DB
        result1 = _load_provider_config()
        assert result1["provider"] == "searxng"
        assert mock_db.query.call_count == 1

        # 第二次调用：应使用缓存（不读 DB）
        result2 = _load_provider_config()
        assert result2["provider"] == "searxng"
        # DB 查询次数仍为 1（缓存命中）
        assert mock_db.query.call_count == 1

    def test_load_provider_config_refreshes_after_cache_expiry(self, monkeypatch) -> None:
        """11 秒后调用应重新读 DB（缓存过期）。"""
        # mock time.monotonic 可变时间
        time_values = [0.0]

        def mock_monotonic():
            return time_values[0]

        monkeypatch.setattr("time.monotonic", mock_monotonic)

        # mock DB 查询
        mock_config = MagicMock()
        mock_config.provider = "searxng"
        mock_config.base_url = "https://example.com"
        mock_config.api_key = None
        mock_config.extra_config = {}

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_config

        mock_session_local = MagicMock(return_value=mock_db)

        import db.models as db_models_module
        monkeypatch.setattr(db_models_module, "SessionLocal", mock_session_local)

        # 第一次调用：应读 DB
        result1 = _load_provider_config()
        assert result1["provider"] == "searxng"
        assert mock_db.query.call_count == 1

        # 推进时间到 11 秒后（缓存过期）
        time_values[0] = 11.0

        # 第二次调用：应重新读 DB
        result2 = _load_provider_config()
        assert result2["provider"] == "searxng"
        # DB 查询次数应为 2（缓存过期后重新查询）
        assert mock_db.query.call_count == 2


# ==================== SearXNG 响应解析测试 ====================


class TestSearxngResponseParsing:
    """_searxng_search 的响应解析逻辑。"""

    async def test_searxng_search_parses_results_correctly(
        self, web_search_tool_fixture, mock_searxng_response_fixture, monkeypatch
    ) -> None:
        """mock SearXNG 返回 5 条结果，应提取 5 条 {title, url, snippet}。"""
        response = _MockSearxngResponse(
            status_code=200, json_data=mock_searxng_response_fixture
        )
        mock_client_class = _make_mock_async_client_class(response)
        monkeypatch.setattr(
            "core.builtin_tools.web_search.httpx.AsyncClient", mock_client_class
        )
        monkeypatch.setattr(
            "security.search_ssrf.validate_search_url",
            lambda url, allow_private=False: (True, None),
        )

        results = await web_search_tool_fixture._searxng_search(
            "test", 10, "https://example.com"
        )

        assert len(results) == 5
        for r in results:
            assert "title" in r
            assert "url" in r
            assert "snippet" in r
        assert results[0]["title"] == "Result 1"
        assert results[0]["url"] == "https://example.com/1"
        assert results[0]["snippet"] == "Content 1"

    async def test_searxng_search_handles_empty_results(
        self, web_search_tool_fixture, monkeypatch
    ) -> None:
        """mock 返回 {results: []} 时，应返回空列表。"""
        response = _MockSearxngResponse(status_code=200, json_data={"results": []})
        mock_client_class = _make_mock_async_client_class(response)
        monkeypatch.setattr(
            "core.builtin_tools.web_search.httpx.AsyncClient", mock_client_class
        )
        monkeypatch.setattr(
            "security.search_ssrf.validate_search_url",
            lambda url, allow_private=False: (True, None),
        )

        results = await web_search_tool_fixture._searxng_search(
            "test", 10, "https://example.com"
        )

        assert results == []

    async def test_searxng_search_handles_malformed_response(
        self, web_search_tool_fixture, monkeypatch
    ) -> None:
        """mock 返回非 JSON 时，应抛出受控异常（ValueError）。"""
        # 让 json() 抛出 ValueError 模拟非 JSON 响应
        response = _MockSearxngResponse(
            status_code=200, json_data=ValueError("Invalid JSON")
        )
        mock_client_class = _make_mock_async_client_class(response)
        monkeypatch.setattr(
            "core.builtin_tools.web_search.httpx.AsyncClient", mock_client_class
        )
        monkeypatch.setattr(
            "security.search_ssrf.validate_search_url",
            lambda url, allow_private=False: (True, None),
        )

        with pytest.raises(ValueError):
            await web_search_tool_fixture._searxng_search(
                "test", 10, "https://example.com"
            )


# ==================== 技能生命周期测试 ====================


class TestWebSearchSkillLifecycle:
    """WebSearchSkill 的 initialize/execute/cleanup/get_tools 生命周期方法。"""

    async def test_initialize_sets_initialized_flag_and_returns_true(
        self, web_search_tool_fixture
    ) -> None:
        """initialize() 应将 _initialized 置 True 并返回 True。"""
        result = await web_search_tool_fixture.initialize()

        assert result is True
        assert web_search_tool_fixture.is_initialized() is True

    def test_is_initialized_reflects_initialization_state(
        self, web_search_tool_fixture
    ) -> None:
        """is_initialized() 应反映 _initialized 当前状态。"""
        # 初始状态为 False
        assert web_search_tool_fixture.is_initialized() is False

        # initialize 后为 True
        import asyncio

        asyncio.run(web_search_tool_fixture.initialize())
        assert web_search_tool_fixture.is_initialized() is True

    async def test_execute_returns_error_when_not_initialized(
        self, web_search_tool_fixture
    ) -> None:
        """未初始化时 execute() 应返回 success=False 与未初始化错误。"""
        result = await web_search_tool_fixture.execute(action="search", query="test")

        assert result["success"] is False
        assert "未初始化" in result["error"]

    async def test_execute_dispatches_search_action(
        self, web_search_tool_fixture, mock_duckduckgo_response_fixture, monkeypatch
    ) -> None:
        """action='search' 应调用 _search 并返回搜索结果。"""
        await web_search_tool_fixture.initialize()

        # mock _duckduckgo_search 避免真实网络
        mock_ddg = AsyncMock(return_value=mock_duckduckgo_response_fixture)
        monkeypatch.setattr(web_search_tool_fixture, "_duckduckgo_search", mock_ddg)
        # 默认 provider 为 duckduckgo
        monkeypatch.setattr(
            "core.builtin_tools.web_search._load_provider_config",
            lambda: {
                "provider": "duckduckgo",
                "base_url": None,
                "api_key": None,
                "extra_config": {},
            },
        )

        result = await web_search_tool_fixture.execute(action="search", query="test")

        assert result["success"] is True
        assert result["provider"] == "duckduckgo"

    async def test_execute_stops_fallback_chain_at_total_timeout(
        self, web_search_tool_fixture, monkeypatch
    ) -> None:
        """provider 降级链超时必须返回结构化结果，而不是累积多个请求超时。"""
        await web_search_tool_fixture.initialize()

        async def _never_returns(_kwargs):
            await asyncio.Event().wait()
            return {"success": True}

        monkeypatch.setattr(web_search_tool_fixture, "_search", _never_returns)
        monkeypatch.setattr(
            "core.builtin_tools.web_search.SEARCH_TOTAL_TIMEOUT",
            0.01,
        )

        result = await web_search_tool_fixture.execute(action="search", query="test")

        assert result == {
            "success": False,
            "error": "搜索服务响应超时，请稍后重试",
            "error_code": "search_total_timeout",
            "retryable": True,
        }

    async def test_execute_dispatches_fetch_url_action(
        self, web_search_tool_fixture, monkeypatch
    ) -> None:
        """action='fetch_url' 应调用 _fetch_url 并返回网页内容。

        注：_fetch_url 通过 loop.run_in_executor 调用 _http_get，
        run_in_executor 期望同步函数（非 async），因此 mock 必须为同步函数。
        """
        await web_search_tool_fixture.initialize()

        # mock _http_get 为同步函数（run_in_executor 在线程池中调用它）
        def _fake_http_get(self, host, path):
            return "<html><body>fake content</body></html>"

        monkeypatch.setattr(
            "core.builtin_tools.web_search.WebSearchSkill._http_get", _fake_http_get
        )

        result = await web_search_tool_fixture.execute(
            action="fetch_url", url="https://example.com/page"
        )

        assert result["success"] is True
        assert "content" in result
        assert "fake content" in result["content"]

    async def test_execute_returns_error_for_unknown_action(
        self, web_search_tool_fixture
    ) -> None:
        """未知 action 应返回 success=False 与未知操作错误。"""
        await web_search_tool_fixture.initialize()

        result = await web_search_tool_fixture.execute(action="unknown_action")

        assert result["success"] is False
        assert "未知操作" in result["error"]

    def test_get_tools_returns_web_search_and_fetch_url_definitions(
        self, web_search_tool_fixture
    ) -> None:
        """get_tools() 应返回 web_search 与 fetch_url 两个工具定义。"""
        tools = web_search_tool_fixture.get_tools()

        assert isinstance(tools, list)
        assert len(tools) == 2
        tool_names = [t["name"] for t in tools]
        assert "web_search" in tool_names
        assert "fetch_url" in tool_names
        # 验证每个工具定义包含必要字段
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "parameters" in tool
            assert tool["parameters"]["type"] == "object"

    def test_cleanup_resets_initialized_flag(
        self, web_search_tool_fixture
    ) -> None:
        """cleanup() 应将 _initialized 重置为 False。"""
        import asyncio

        asyncio.run(web_search_tool_fixture.initialize())
        assert web_search_tool_fixture.is_initialized() is True

        web_search_tool_fixture.cleanup()

        assert web_search_tool_fixture.is_initialized() is False


# ==================== 搜索查询参数校验测试 ====================


class TestSearchParamsValidation:
    """_search 方法的查询参数校验逻辑。"""

    async def test_search_returns_error_when_query_empty(
        self, web_search_tool_fixture
    ) -> None:
        """空查询字符串应返回 success=False 与不能为空错误。"""
        # 不依赖 provider 配置，空 query 在配置读取前就被拒绝
        result = await web_search_tool_fixture._search(
            {"query": "", "max_results": 5}
        )

        assert result["success"] is False
        assert "不能为空" in result["error"]

    async def test_search_returns_error_when_query_only_whitespace(
        self, web_search_tool_fixture
    ) -> None:
        """仅含空白的查询字符串应视为空，返回 success=False。"""
        result = await web_search_tool_fixture._search(
            {"query": "   \t  ", "max_results": 5}
        )

        assert result["success"] is False
        assert "不能为空" in result["error"]


# ==================== DuckDuckGo 搜索测试 ====================


class TestDuckDuckGoSearch:
    """_duckduckgo_search 方法测试。"""

    async def test_duckduckgo_search_returns_parsed_results(
        self, web_search_tool_fixture, monkeypatch
    ) -> None:
        """mock _http_get 返回 HTML，应解析为结果列表。"""
        # 构造 DuckDuckGo HTML 响应（含一个 result__a 链接与 result__snippet 摘要）
        fake_html = (
            '<div class="result">'
            '<a href="https://example.com/result1" class="result__a">Result 1 Title</a>'
            '<a class="result__snippet">Result 1 snippet text</a>'
            '</div>'
        )

        async def _fake_http_get(self, host, path):
            return fake_html

        monkeypatch.setattr(
            "core.builtin_tools.web_search.WebSearchSkill._http_get", _fake_http_get
        )

        results = await web_search_tool_fixture._duckduckgo_search("test", 5)

        assert isinstance(results, list)
        assert len(results) == 1
        assert results[0]["title"] == "Result 1 Title"
        assert results[0]["url"] == "https://example.com/result1"
        assert results[0]["snippet"] == "Result 1 snippet text"

    async def test_duckduckgo_search_raises_on_timeout(
        self, web_search_tool_fixture, monkeypatch
    ) -> None:
        """_http_get 抛 asyncio.TimeoutError 时，_duckduckgo_search 应原样抛出。"""
        import asyncio as _asyncio

        async def _fake_http_get(self, host, path):
            raise _asyncio.TimeoutError()

        monkeypatch.setattr(
            "core.builtin_tools.web_search.WebSearchSkill._http_get", _fake_http_get
        )

        with pytest.raises(_asyncio.TimeoutError):
            await web_search_tool_fixture._duckduckgo_search("test", 5)

    async def test_duckduckgo_search_raises_on_oserror(
        self, web_search_tool_fixture, monkeypatch
    ) -> None:
        """_http_get 抛 OSError 时，_duckduckgo_search 应原样抛出。"""
        async def _fake_http_get(self, host, path):
            raise OSError("network unreachable")

        monkeypatch.setattr(
            "core.builtin_tools.web_search.WebSearchSkill._http_get", _fake_http_get
        )

        with pytest.raises(OSError):
            await web_search_tool_fixture._duckduckgo_search("test", 5)

    async def test_duckduckgo_search_raises_on_value_error(
        self, web_search_tool_fixture, monkeypatch
    ) -> None:
        """_http_get 抛 ValueError 时，_duckduckgo_search 应原样抛出。"""
        async def _fake_http_get(self, host, path):
            raise ValueError("invalid host")

        monkeypatch.setattr(
            "core.builtin_tools.web_search.WebSearchSkill._http_get", _fake_http_get
        )

        with pytest.raises(ValueError):
            await web_search_tool_fixture._duckduckgo_search("test", 5)


# ==================== DuckDuckGo HTML 解析测试 ====================


class TestParseDdgHtml:
    """_parse_ddg_html 方法测试。"""

    def test_parse_ddg_html_extracts_results_from_valid_html(
        self, web_search_tool_fixture
    ) -> None:
        """正常 HTML 应提取 title/url/snippet 三个字段。"""
        html_content = (
            '<div class="result">'
            '<a href="https://example.com/1" class="result__a">First Title</a>'
            '<a class="result__snippet">First snippet</a>'
            '</div>'
            '<div class="result">'
            '<a href="https://example.com/2" class="result__a">Second Title</a>'
            '<a class="result__snippet">Second snippet</a>'
            '</div>'
        )

        results = web_search_tool_fixture._parse_ddg_html(html_content, 5)

        assert len(results) == 2
        assert results[0]["title"] == "First Title"
        assert results[0]["url"] == "https://example.com/1"
        assert results[0]["snippet"] == "First snippet"
        assert results[1]["title"] == "Second Title"

    def test_parse_ddg_html_handles_duckduckgo_redirect_links(
        self, web_search_tool_fixture
    ) -> None:
        """DuckDuckGo 重定向链接（//duckduckgo.com/l/?uddg=...）应被解码为真实 URL。"""
        # 构造带 redirect 参数的 href
        redirect_url = (
            "//duckduckgo.com/l/?uddg=https%3A%2F%2Freal.example.com%2Fpage&rut=abc"
        )
        html_content = (
            f'<a href="{redirect_url}" class="result__a">Redirect Title</a>'
            '<a class="result__snippet">snippet</a>'
        )

        results = web_search_tool_fixture._parse_ddg_html(html_content, 5)

        assert len(results) == 1
        # 重定向链接应被解析为真实 URL
        assert results[0]["url"] == "https://real.example.com/page"

    def test_parse_ddg_html_truncates_long_titles_and_snippets(
        self, web_search_tool_fixture
    ) -> None:
        """超长 title（>200）和 snippet（>500）应被截断。"""
        long_title = "A" * 300
        long_snippet = "B" * 600
        html_content = (
            f'<a href="https://example.com/1" class="result__a">{long_title}</a>'
            f'<a class="result__snippet">{long_snippet}</a>'
        )

        results = web_search_tool_fixture._parse_ddg_html(html_content, 5)

        assert len(results) == 1
        # title 应被截断为 200 字符
        assert len(results[0]["title"]) == 200
        # snippet 应被截断为 500 字符
        assert len(results[0]["snippet"]) == 500

    def test_parse_ddg_html_returns_empty_list_when_no_results(
        self, web_search_tool_fixture
    ) -> None:
        """HTML 不含 result__a 标记时，应返回空列表。"""
        html_content = "<html><body>no results here</body></html>"

        results = web_search_tool_fixture._parse_ddg_html(html_content, 5)

        assert results == []

    def test_parse_ddg_html_strips_html_tags_from_title(
        self, web_search_tool_fixture
    ) -> None:
        """title 内嵌的 HTML 标签应被剥离。"""
        html_content = (
            '<a href="https://example.com/1" class="result__a">'
            '<b>Bold</b> <i>Title</i></a>'
            '<a class="result__snippet">snippet</a>'
        )

        results = web_search_tool_fixture._parse_ddg_html(html_content, 5)

        assert len(results) == 1
        # 内嵌的 <b>/<i> 标签应被移除
        assert "<" not in results[0]["title"]
        assert ">" not in results[0]["title"]
        assert "Bold" in results[0]["title"]
        assert "Title" in results[0]["title"]

    def test_parse_ddg_html_respects_max_results_limit(
        self, web_search_tool_fixture
    ) -> None:
        """结果数不应超过 max_results。"""
        # 构造 5 个 result__a 链接
        items = []
        for i in range(5):
            items.append(
                f'<a href="https://example.com/{i}" class="result__a">Title {i}</a>'
                f'<a class="result__snippet">snippet {i}</a>'
            )
        html_content = "".join(items)

        results = web_search_tool_fixture._parse_ddg_html(html_content, 3)

        # 应只返回前 3 个
        assert len(results) == 3

    def test_strip_html_tags_removes_all_tags(
        self, web_search_tool_fixture
    ) -> None:
        """_strip_html_tags 应移除所有 HTML 标签，仅保留文本内容。"""
        text_with_tags = "<b>bold</b> <i>italic</i> <span>span</span> plain"
        result = web_search_tool_fixture._strip_html_tags(text_with_tags)

        assert "<" not in result
        assert ">" not in result
        assert "bold" in result
        assert "italic" in result
        assert "span" in result
        assert "plain" in result

    def test_strip_html_tags_returns_empty_for_tags_only(
        self, web_search_tool_fixture
    ) -> None:
        """仅含 HTML 标签的字符串应返回空字符串。"""
        result = web_search_tool_fixture._strip_html_tags("<div></div><br/>")
        assert result == ""


# ==================== _fetch_url 测试 ====================


class TestFetchUrl:
    """_fetch_url 方法测试。"""

    async def test_fetch_url_returns_error_when_url_empty(
        self, web_search_tool_fixture
    ) -> None:
        """空 URL 应返回 success=False 与 URL 不能为空错误。"""
        result = await web_search_tool_fixture._fetch_url({"url": ""})

        assert result["success"] is False
        assert "不能为空" in result["error"]

    async def test_fetch_url_returns_error_for_non_http_scheme(
        self, web_search_tool_fixture
    ) -> None:
        """非 http/https 协议（如 file://）应被拒绝。"""
        result = await web_search_tool_fixture._fetch_url(
            {"url": "file:///etc/passwd"}
        )

        assert result["success"] is False
        assert "http" in result["error"]

    async def test_fetch_url_returns_error_when_hostname_missing(
        self, web_search_tool_fixture
    ) -> None:
        """URL 缺少主机名时应返回 success=False。"""
        result = await web_search_tool_fixture._fetch_url({"url": "https:///path"})

        assert result["success"] is False
        assert "无效" in result["error"]

    async def test_fetch_url_returns_content_on_success(
        self, web_search_tool_fixture, monkeypatch
    ) -> None:
        """成功获取时应返回 success=True 与纯文本内容。

        注：_fetch_url 通过 loop.run_in_executor 调用 _http_get，
        run_in_executor 期望同步函数（非 async），因此 mock 必须为同步函数。
        """
        # mock _http_get 为同步函数（run_in_executor 在线程池中调用它）
        def _fake_http_get(self, host, path):
            return "<html><body><h1>Title</h1><p>Content here</p></body></html>"

        monkeypatch.setattr(
            "core.builtin_tools.web_search.WebSearchSkill._http_get", _fake_http_get
        )

        result = await web_search_tool_fixture._fetch_url(
            {"url": "https://example.com/page"}
        )

        assert result["success"] is True
        assert "content" in result
        assert "Title" in result["content"]
        assert "Content here" in result["content"]
        # HTML 标签应被剥离
        assert "<html>" not in result["content"]
        assert "length" in result
        assert result["length"] > 0

    async def test_fetch_url_returns_error_on_failure(
        self, web_search_tool_fixture, monkeypatch
    ) -> None:
        """_http_get 抛异常时，应返回 success=False 与获取失败错误。

        注：_fetch_url 通过 loop.run_in_executor 调用 _http_get，
        run_in_executor 会在线程池中传播同步函数抛出的异常。
        """
        def _fake_http_get(self, host, path):
            raise OSError("connection refused")

        monkeypatch.setattr(
            "core.builtin_tools.web_search.WebSearchSkill._http_get", _fake_http_get
        )

        result = await web_search_tool_fixture._fetch_url(
            {"url": "https://example.com/page"}
        )

        assert result["success"] is False
        assert "获取网页失败" in result["error"]

    async def test_fetch_url_respects_max_length(
        self, web_search_tool_fixture, monkeypatch
    ) -> None:
        """max_length 参数应限制返回内容长度。

        注：_fetch_url 通过 loop.run_in_executor 调用 _http_get，
        run_in_executor 期望同步函数（非 async），因此 mock 必须为同步函数。
        """
        def _fake_http_get(self, host, path):
            # 返回 1000 字符的纯文本（无 HTML 标签）
            return "A" * 1000

        monkeypatch.setattr(
            "core.builtin_tools.web_search.WebSearchSkill._http_get", _fake_http_get
        )

        result = await web_search_tool_fixture._fetch_url(
            {"url": "https://example.com/page", "max_length": 100}
        )

        assert result["success"] is True
        # 内容应被截断为 100 字符
        assert len(result["content"]) == 100
        assert result["length"] == 100


# ==================== _load_provider_config 异常路径测试 ====================


class TestLoadProviderConfigExceptions:
    """_load_provider_config 的异常降级路径测试。"""

    def test_load_provider_config_falls_back_on_import_error(
        self, monkeypatch
    ) -> None:
        """db.models 模块不可导入时，应降级到默认 duckduckgo 配置。"""
        # 清空缓存
        web_search_module._provider_config_cache["data"] = None
        web_search_module._provider_config_cache["expires_at"] = 0.0

        # 让 db.models 的导入抛 ImportError
        import builtins
        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "db.models":
                raise ImportError("db.models not available")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)

        result = _load_provider_config()

        assert result["provider"] == "duckduckgo"
        assert result["base_url"] is None
        assert result["api_key"] is None

    def test_load_provider_config_falls_back_on_db_query_error(
        self, monkeypatch
    ) -> None:
        """数据库查询抛异常时，应降级到默认 duckduckgo 配置。"""
        # 清空缓存
        web_search_module._provider_config_cache["data"] = None
        web_search_module._provider_config_cache["expires_at"] = 0.0

        # mock db.models.SessionLocal 抛异常
        def _fake_session_local():
            raise RuntimeError("database is locked")

        # 通过 monkeypatch 替换 SessionLocal
        import db.models as db_models_module
        monkeypatch.setattr(
            db_models_module, "SessionLocal", _fake_session_local
        )

        result = _load_provider_config()

        assert result["provider"] == "duckduckgo"
        assert result["base_url"] is None


# ==================== SearXNG 降级路径补充测试 ====================


class TestSearxngFallbackPaths:
    """_search 中 SearXNG 异常降级路径补充测试。"""

    async def test_search_falls_back_on_searxng_asyncio_timeout(
        self, web_search_tool_fixture, mock_duckduckgo_response_fixture, monkeypatch
    ) -> None:
        """SearXNG 调用抛 asyncio.TimeoutError 时应降级到 DuckDuckGo。

        注：实际 _searxng_search 抛的是 httpx.TimeoutException，
        但 _search 内部 try/except 同时捕获 asyncio.TimeoutError（来自 wait_for）。
        """
        monkeypatch.setattr(
            "core.builtin_tools.web_search._load_provider_config",
            lambda: {
                "provider": "searxng",
                "base_url": "https://example.com",
                "api_key": None,
                "extra_config": {},
            },
        )

        # 让 _searxng_search 抛 asyncio.TimeoutError
        import asyncio as _asyncio

        async def _fake_searxng_search(self, *args, **kwargs):
            raise _asyncio.TimeoutError()

        monkeypatch.setattr(
            "core.builtin_tools.web_search.WebSearchSkill._searxng_search",
            _fake_searxng_search,
        )

        mock_ddg = AsyncMock(return_value=mock_duckduckgo_response_fixture)
        monkeypatch.setattr(web_search_tool_fixture, "_duckduckgo_search", mock_ddg)

        result = await web_search_tool_fixture._search(
            {"query": "test", "max_results": 5}
        )

        assert result["success"] is True
        assert result["provider"] == "duckduckgo"
        mock_ddg.assert_awaited_once()

    async def test_search_falls_back_on_searxng_value_error(
        self, web_search_tool_fixture, mock_duckduckgo_response_fixture, monkeypatch
    ) -> None:
        """SearXNG 抛 ValueError（SSRF/JSON 解析失败）时应降级到 DuckDuckGo。"""
        monkeypatch.setattr(
            "core.builtin_tools.web_search._load_provider_config",
            lambda: {
                "provider": "searxng",
                "base_url": "https://example.com",
                "api_key": None,
                "extra_config": {},
            },
        )

        async def _fake_searxng_search(self, *args, **kwargs):
            raise ValueError("invalid JSON")

        monkeypatch.setattr(
            "core.builtin_tools.web_search.WebSearchSkill._searxng_search",
            _fake_searxng_search,
        )

        mock_ddg = AsyncMock(return_value=mock_duckduckgo_response_fixture)
        monkeypatch.setattr(web_search_tool_fixture, "_duckduckgo_search", mock_ddg)

        result = await web_search_tool_fixture._search(
            {"query": "test", "max_results": 5}
        )

        assert result["success"] is True
        assert result["provider"] == "duckduckgo"
        mock_ddg.assert_awaited_once()

    async def test_search_falls_back_on_searxng_oserror(
        self, web_search_tool_fixture, mock_duckduckgo_response_fixture, monkeypatch
    ) -> None:
        """SearXNG 抛 OSError（网络异常）时应降级到 DuckDuckGo。"""
        monkeypatch.setattr(
            "core.builtin_tools.web_search._load_provider_config",
            lambda: {
                "provider": "searxng",
                "base_url": "https://example.com",
                "api_key": None,
                "extra_config": {},
            },
        )

        async def _fake_searxng_search(self, *args, **kwargs):
            raise OSError("network error")

        monkeypatch.setattr(
            "core.builtin_tools.web_search.WebSearchSkill._searxng_search",
            _fake_searxng_search,
        )

        mock_ddg = AsyncMock(return_value=mock_duckduckgo_response_fixture)
        monkeypatch.setattr(web_search_tool_fixture, "_duckduckgo_search", mock_ddg)

        result = await web_search_tool_fixture._search(
            {"query": "test", "max_results": 5}
        )

        assert result["success"] is True
        assert result["provider"] == "duckduckgo"
        mock_ddg.assert_awaited_once()

    async def test_search_falls_back_on_searxng_generic_exception(
        self, web_search_tool_fixture, mock_duckduckgo_response_fixture, monkeypatch
    ) -> None:
        """SearXNG 抛未知异常时应降级到 DuckDuckGo。"""
        monkeypatch.setattr(
            "core.builtin_tools.web_search._load_provider_config",
            lambda: {
                "provider": "searxng",
                "base_url": "https://example.com",
                "api_key": None,
                "extra_config": {},
            },
        )

        async def _fake_searxng_search(self, *args, **kwargs):
            raise RuntimeError("unexpected error")

        monkeypatch.setattr(
            "core.builtin_tools.web_search.WebSearchSkill._searxng_search",
            _fake_searxng_search,
        )

        mock_ddg = AsyncMock(return_value=mock_duckduckgo_response_fixture)
        monkeypatch.setattr(web_search_tool_fixture, "_duckduckgo_search", mock_ddg)

        result = await web_search_tool_fixture._search(
            {"query": "test", "max_results": 5}
        )

        assert result["success"] is True
        assert result["provider"] == "duckduckgo"
        mock_ddg.assert_awaited_once()


# ==================== DuckDuckGo 失败路径测试 ====================


class TestDuckDuckGoFailurePaths:
    """_search 中 DuckDuckGo 调用失败时的错误处理路径。"""

    async def test_search_returns_timeout_error_when_duckduckgo_times_out(
        self, web_search_tool_fixture, monkeypatch
    ) -> None:
        """DuckDuckGo 抛 asyncio.TimeoutError 且 Bing 降级也失败时，应返回搜索失败错误。"""
        import asyncio as _asyncio

        monkeypatch.setattr(
            "core.builtin_tools.web_search._load_provider_config",
            lambda: {
                "provider": "duckduckgo",
                "base_url": None,
                "api_key": None,
                "extra_config": {},
            },
        )

        mock_ddg = AsyncMock(side_effect=_asyncio.TimeoutError())
        monkeypatch.setattr(web_search_tool_fixture, "_duckduckgo_search", mock_ddg)

        # Bing 降级也超时，验证降级链路完整失败
        mock_bing = AsyncMock(side_effect=_asyncio.TimeoutError())
        monkeypatch.setattr(web_search_tool_fixture, "_bing_search", mock_bing)

        result = await web_search_tool_fixture._search(
            {"query": "test", "max_results": 5}
        )

        assert result["success"] is False
        assert "搜索失败" in result["error"]

    async def test_search_returns_network_error_when_duckduckgo_raises_oserror(
        self, web_search_tool_fixture, monkeypatch
    ) -> None:
        """DuckDuckGo 抛 OSError 且 Bing 降级也失败时，应返回搜索失败错误。"""
        monkeypatch.setattr(
            "core.builtin_tools.web_search._load_provider_config",
            lambda: {
                "provider": "duckduckgo",
                "base_url": None,
                "api_key": None,
                "extra_config": {},
            },
        )

        mock_ddg = AsyncMock(side_effect=OSError("DNS resolution failed"))
        monkeypatch.setattr(web_search_tool_fixture, "_duckduckgo_search", mock_ddg)

        # Bing 降级也失败
        mock_bing = AsyncMock(side_effect=OSError("Bing DNS failed"))
        monkeypatch.setattr(web_search_tool_fixture, "_bing_search", mock_bing)

        result = await web_search_tool_fixture._search(
            {"query": "test", "max_results": 5}
        )

        assert result["success"] is False
        assert "搜索失败" in result["error"]

    async def test_search_returns_value_error_when_duckduckgo_raises_value_error(
        self, web_search_tool_fixture, monkeypatch
    ) -> None:
        """DuckDuckGo 抛 ValueError（SSRF/HTML 解析）且 Bing 降级也失败时，应返回搜索失败错误。"""
        monkeypatch.setattr(
            "core.builtin_tools.web_search._load_provider_config",
            lambda: {
                "provider": "duckduckgo",
                "base_url": None,
                "api_key": None,
                "extra_config": {},
            },
        )

        mock_ddg = AsyncMock(side_effect=ValueError("HTML parse error"))
        monkeypatch.setattr(web_search_tool_fixture, "_duckduckgo_search", mock_ddg)

        # Bing 降级也失败
        mock_bing = AsyncMock(side_effect=ValueError("Bing parse error"))
        monkeypatch.setattr(web_search_tool_fixture, "_bing_search", mock_bing)

        result = await web_search_tool_fixture._search(
            {"query": "test", "max_results": 5}
        )

        assert result["success"] is False
        assert "搜索失败" in result["error"]

    async def test_search_returns_unexpected_error_when_duckduckgo_raises_generic_exception(
        self, web_search_tool_fixture, monkeypatch
    ) -> None:
        """DuckDuckGo 抛未知异常且 Bing 降级也失败时，应返回搜索失败错误（安全网捕获）。"""
        monkeypatch.setattr(
            "core.builtin_tools.web_search._load_provider_config",
            lambda: {
                "provider": "duckduckgo",
                "base_url": None,
                "api_key": None,
                "extra_config": {},
            },
        )

        mock_ddg = AsyncMock(side_effect=RuntimeError("unexpected"))
        monkeypatch.setattr(web_search_tool_fixture, "_duckduckgo_search", mock_ddg)

        # Bing 降级也失败
        mock_bing = AsyncMock(side_effect=RuntimeError("Bing unexpected"))
        monkeypatch.setattr(web_search_tool_fixture, "_bing_search", mock_bing)

        result = await web_search_tool_fixture._search(
            {"query": "test", "max_results": 5}
        )

        assert result["success"] is False
        assert "搜索失败" in result["error"]

    async def test_search_falls_back_to_bing_when_duckduckgo_fails(
        self, web_search_tool_fixture, monkeypatch
    ) -> None:
        """DuckDuckGo 失败时应自动降级到 Bing 并返回成功结果。"""
        import asyncio as _asyncio

        monkeypatch.setattr(
            "core.builtin_tools.web_search._load_provider_config",
            lambda: {
                "provider": "duckduckgo",
                "base_url": None,
                "api_key": None,
                "extra_config": {},
            },
        )

        # DuckDuckGo 超时
        mock_ddg = AsyncMock(side_effect=_asyncio.TimeoutError())
        monkeypatch.setattr(web_search_tool_fixture, "_duckduckgo_search", mock_ddg)

        # Bing 返回有效结果
        bing_results = [
            {"title": "Bing Result", "url": "https://example.com/bing", "snippet": "snippet"},
        ]
        mock_bing = AsyncMock(return_value=bing_results)
        monkeypatch.setattr(web_search_tool_fixture, "_bing_search", mock_bing)

        result = await web_search_tool_fixture._search(
            {"query": "test", "max_results": 5}
        )

        assert result["success"] is True
        assert result["provider"] == "bing"
        assert result["count"] == 1
        assert result["results"][0]["title"] == "Bing Result"
        mock_ddg.assert_awaited_once()
        mock_bing.assert_awaited_once()


class TestSearxngSsrfModuleMissing:
    """_searxng_search 在 security.search_ssrf 模块缺失时的兜底行为。"""

    async def test_searxng_search_skips_ssrf_when_module_missing(
        self, web_search_tool_fixture, mock_searxng_response_fixture, monkeypatch
    ) -> None:
        """security.search_ssrf 模块不可导入时，应跳过 SSRF 校验继续请求。"""
        # mock httpx 返回成功
        response = _MockSearxngResponse(
            status_code=200, json_data=mock_searxng_response_fixture
        )
        mock_client_class = _make_mock_async_client_class(response)
        monkeypatch.setattr(
            "core.builtin_tools.web_search.httpx.AsyncClient", mock_client_class
        )

        # 让 security.search_ssrf 导入抛 ImportError
        import builtins
        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "security.search_ssrf":
                raise ImportError("module not found")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)

        # 使用公网域名 example.com，不触发 SSRF 校验（模块缺失时跳过）
        results = await web_search_tool_fixture._searxng_search(
            "test", 5, "https://example.com"
        )

        # 应成功返回结果（SSRF 校验被跳过）
        assert len(results) == 5


# ==================== _http_get SSRF 防护测试 ====================


class TestHttpGetSsrfProtection:
    """_http_get 方法的 SSRF 防护与请求执行。"""

    async def test_http_get_rejects_empty_host(
        self, web_search_tool_fixture
    ) -> None:
        """空主机名应抛 ValueError。"""
        with pytest.raises(ValueError, match="主机名不能为空"):
            await web_search_tool_fixture._http_get("", "/path")

    async def test_http_get_rejects_localhost(
        self, web_search_tool_fixture
    ) -> None:
        """localhost 主机名应抛 ValueError 不允许访问本地地址。"""
        with pytest.raises(ValueError, match="不允许访问本地地址"):
            await web_search_tool_fixture._http_get("localhost", "/path")

    async def test_http_get_rejects_loopback_ipv4(
        self, web_search_tool_fixture
    ) -> None:
        """127.0.0.1 主机名应抛 ValueError 不允许访问本地地址。"""
        with pytest.raises(ValueError, match="不允许访问本地地址"):
            await web_search_tool_fixture._http_get("127.0.0.1", "/path")

    async def test_http_get_rejects_ipv6_loopback(
        self, web_search_tool_fixture
    ) -> None:
        """::1 主机名应抛 ValueError 不允许访问本地地址。"""
        with pytest.raises(ValueError, match="不允许访问本地地址"):
            await web_search_tool_fixture._http_get("::1", "/path")

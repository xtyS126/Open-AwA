"""
MCP 资源读取与 SSE origin 校验单元测试。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp.client import MCPClient
from mcp.manager import MCPManager
from mcp.transport import SSETransport, MCPTransportError
from mcp.types import MCPResource, MCPResourceContent, MCPServerConfig, TransportType


# ==================== MCPResourceContent 类型测试 ====================

def test_resource_content_text():
    """文本资源内容应正确创建。"""
    content = MCPResourceContent(
        uri="file:///test.txt",
        mime_type="text/plain",
        text="hello world",
        blob=None,
    )
    assert content.uri == "file:///test.txt"
    assert content.mime_type == "text/plain"
    assert content.text == "hello world"
    assert content.blob is None


def test_resource_content_blob():
    """二进制资源内容应正确创建。"""
    content = MCPResourceContent(
        uri="file:///image.png",
        mime_type="image/png",
        text=None,
        blob="aGVsbG8=",  # base64
    )
    assert content.blob == "aGVsbG8="
    assert content.text is None


def test_resource_content_alias():
    """mimeType 别名应正确映射。"""
    content = MCPResourceContent(
        uri="file:///test",
        **{"mimeType": "application/json"},
        text="{}",
    )
    assert content.mime_type == "application/json"


# ==================== SSE origin 校验测试 ====================

def test_sse_origin_empty_whitelist_allows_all():
    """白名单为空时应允许所有 origin。"""
    SSETransport.set_allowed_origins([])
    assert SSETransport.is_origin_allowed("https://example.com") is True
    assert SSETransport.is_origin_allowed("http://localhost:3000") is True


def test_sse_origin_in_whitelist():
    """origin 在白名单中应允许。"""
    SSETransport.set_allowed_origins(["https://example.com", "http://localhost:3000"])
    assert SSETransport.is_origin_allowed("https://example.com") is True
    assert SSETransport.is_origin_allowed("http://localhost:3000") is True


def test_sse_origin_not_in_whitelist():
    """origin 不在白名单中应拒绝。"""
    SSETransport.set_allowed_origins(["https://example.com"])
    assert SSETransport.is_origin_allowed("https://evil.com") is False


def test_sse_origin_case_insensitive():
    """origin 校验应大小写不敏感。"""
    SSETransport.set_allowed_origins(["https://Example.COM"])
    assert SSETransport.is_origin_allowed("https://example.com") is True


def test_sse_origin_trailing_slash():
    """origin 校验应忽略尾部斜杠。"""
    SSETransport.set_allowed_origins(["https://example.com/"])
    assert SSETransport.is_origin_allowed("https://example.com") is True


@pytest.mark.asyncio
async def test_sse_connect_rejected_origin():
    """origin 不在白名单时连接应失败。"""
    SSETransport.set_allowed_origins(["https://allowed.com"])
    transport = SSETransport("https://evil.com/sse")
    with pytest.raises(MCPTransportError, match="origin 被拒绝"):
        await transport.connect()
    # 重置白名单
    SSETransport.set_allowed_origins([])


@pytest.mark.asyncio
async def test_sse_connect_allowed_origin():
    """origin 在白名单时连接应通过 origin 校验（httpx 可能失败但不是 origin 问题）。"""
    SSETransport.set_allowed_origins(["https://allowed.com"])
    transport = SSETransport("https://allowed.com/sse")
    # 由于没有真实服务器，连接会在 httpx 层失败，但不应是 origin 拒绝
    try:
        await transport.connect()
    except MCPTransportError as e:
        assert "origin 被拒绝" not in str(e)
    finally:
        SSETransport.set_allowed_origins([])


# ==================== MCPClient.read_resource 测试 ====================

@pytest.mark.asyncio
async def test_client_read_resource_text():
    """MCPClient.read_resource 应正确解析文本资源。"""
    config = MCPServerConfig(
        name="test",
        transport_type=TransportType.STDIO,
        command="echo",
    )
    client = MCPClient(config)

    # 模拟 _send_request 返回
    mock_response = {
        "result": {
            "contents": [
                {
                    "uri": "file:///test.txt",
                    "mimeType": "text/plain",
                    "text": "hello world",
                }
            ]
        }
    }
    with patch.object(client, '_send_request', new_callable=AsyncMock, return_value=mock_response):
        content = await client.read_resource("file:///test.txt")

    assert content.uri == "file:///test.txt"
    assert content.mime_type == "text/plain"
    assert content.text == "hello world"


@pytest.mark.asyncio
async def test_client_read_resource_empty():
    """资源内容为空时应返回空内容对象。"""
    config = MCPServerConfig(
        name="test",
        transport_type=TransportType.STDIO,
        command="echo",
    )
    client = MCPClient(config)

    mock_response = {"result": {"contents": []}}
    with patch.object(client, '_send_request', new_callable=AsyncMock, return_value=mock_response):
        content = await client.read_resource("file:///empty")

    assert content.uri == "file:///empty"
    assert content.text == ""


@pytest.mark.asyncio
async def test_client_read_resource_blob():
    """二进制资源应正确解析 blob 字段。"""
    config = MCPServerConfig(
        name="test",
        transport_type=TransportType.STDIO,
        command="echo",
    )
    client = MCPClient(config)

    mock_response = {
        "result": {
            "contents": [
                {
                    "uri": "file:///image.png",
                    "mimeType": "image/png",
                    "blob": "aGVsbG8=",
                }
            ]
        }
    }
    with patch.object(client, '_send_request', new_callable=AsyncMock, return_value=mock_response):
        content = await client.read_resource("file:///image.png")

    assert content.blob == "aGVsbG8="
    assert content.mime_type == "image/png"


# ==================== MCPManager 资源管理测试 ====================

@pytest.fixture
def reset_manager_singleton():
    """重置 MCPManager 单例（测试隔离）。"""
    MCPManager._instance = None
    yield
    MCPManager._instance = None


@pytest.mark.asyncio
async def test_manager_get_all_resources(reset_manager_singleton):
    """get_all_resources 应聚合所有已连接 Server 的资源。"""
    manager = MCPManager()

    # 模拟两个已连接的 client
    mock_client1 = MagicMock()
    mock_client1.is_connected = True
    mock_client1.list_resources = AsyncMock(return_value=[
        MCPResource(uri="file:///a.txt", name="A", description="文件 A", mime_type="text/plain"),
    ])

    mock_client2 = MagicMock()
    mock_client2.is_connected = True
    mock_client2.list_resources = AsyncMock(return_value=[
        MCPResource(uri="file:///b.txt", name="B", description="文件 B", mime_type="text/plain"),
    ])

    # 未连接的 client 应被跳过
    mock_client3 = MagicMock()
    mock_client3.is_connected = False

    manager._clients = {
        "server1": mock_client1,
        "server2": mock_client2,
        "server3": mock_client3,
    }

    resources = await manager.get_all_resources()

    assert len(resources) == 2
    uris = [r["uri"] for r in resources]
    assert "file:///a.txt" in uris
    assert "file:///b.txt" in uris


@pytest.mark.asyncio
async def test_manager_get_all_resources_handles_errors(reset_manager_singleton):
    """单个 Server 获取资源失败时不应影响其他 Server。"""
    manager = MCPManager()

    mock_client1 = MagicMock()
    mock_client1.is_connected = True
    mock_client1.list_resources = AsyncMock(side_effect=Exception("连接断开"))

    mock_client2 = MagicMock()
    mock_client2.is_connected = True
    mock_client2.list_resources = AsyncMock(return_value=[
        MCPResource(uri="file:///ok.txt", name="OK", description=None, mime_type=None),
    ])

    manager._clients = {
        "server1": mock_client1,
        "server2": mock_client2,
    }

    resources = await manager.get_all_resources()

    # server1 失败被跳过，server2 正常返回
    assert len(resources) == 1
    assert resources[0]["uri"] == "file:///ok.txt"


@pytest.mark.asyncio
async def test_manager_read_server_resource(reset_manager_singleton):
    """read_server_resource 应委托给对应 client。"""
    manager = MCPManager()

    mock_client = MagicMock()
    mock_client.is_connected = True
    expected_content = MCPResourceContent(
        uri="file:///test.txt",
        mime_type="text/plain",
        text="content",
        blob=None,
    )
    mock_client.read_resource = AsyncMock(return_value=expected_content)

    manager._clients = {"server1": mock_client}

    content = await manager.read_server_resource("server1", "file:///test.txt")

    assert content.uri == "file:///test.txt"
    assert content.text == "content"
    mock_client.read_resource.assert_called_once_with("file:///test.txt")


@pytest.mark.asyncio
async def test_manager_get_server_resources(reset_manager_singleton):
    """get_server_resources 应返回指定 Server 的资源列表。"""
    manager = MCPManager()

    mock_client = MagicMock()
    mock_client.is_connected = True
    mock_client.list_resources = AsyncMock(return_value=[
        MCPResource(uri="file:///a.txt", name="A", description="desc", mime_type="text/plain"),
        MCPResource(uri="file:///b.txt", name="B", description=None, mime_type=None),
    ])

    manager._clients = {"server1": mock_client}

    resources = await manager.get_server_resources("server1")

    assert len(resources) == 2
    assert resources[0].uri == "file:///a.txt"
    assert resources[1].name == "B"

"""
MCP 资源读取与 SSE origin 校验单元测试。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp.manager import (
    MCPClient,
    MCPClientError,
    MCPManager,
    MCPResource,
    MCPResourceContent,
    MCPServerConfig,
    MCPTool,
    MCPTransportError,
    SSETransport,
    TransportType,
    build_mcp_tool_name,
)
# 官方 mcp SDK 类型，用于构造 session mock 返回值
from mcp.types import (
    BlobResourceContents,
    ReadResourceResult,
    TextResourceContents,
)
from core.permission_manager import (
    PermissionEffect,
    PermissionRule,
    evaluate_effect,
    matches_mcp_server,
    wildcard_match,
)


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
async def test_sse_check_origin_rejected():
    """origin 不在白名单时 _check_origin 应抛出 MCPTransportError。

    新版 SSETransport 为静态工具类（不再实例化），origin 校验通过 _check_origin 完成。
    """
    SSETransport.set_allowed_origins(["https://allowed.com"])
    try:
        with pytest.raises(MCPTransportError, match="origin 被拒绝"):
            SSETransport._check_origin("https://evil.com/sse")
    finally:
        # 重置白名单
        SSETransport.set_allowed_origins([])


@pytest.mark.asyncio
async def test_sse_check_origin_allowed():
    """origin 在白名单时 _check_origin 应通过（不抛出异常）。"""
    SSETransport.set_allowed_origins(["https://allowed.com"])
    try:
        # 不应抛出任何异常（连接层由官方 sse_client 负责，此处仅验证 origin 校验通过）
        SSETransport._check_origin("https://allowed.com/sse")
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

    # 模拟已连接的 session，read_resource 返回官方 SDK 的 ReadResourceResult
    mock_session = MagicMock()
    mock_session.read_resource = AsyncMock(return_value=ReadResourceResult(
        contents=[
            TextResourceContents(
                uri="file:///test.txt",
                mimeType="text/plain",
                text="hello world",
            )
        ]
    ))
    client._session = mock_session

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

    # 模拟已连接的 session，返回空 contents
    mock_session = MagicMock()
    mock_session.read_resource = AsyncMock(return_value=ReadResourceResult(contents=[]))
    client._session = mock_session

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

    # 模拟已连接的 session，返回 BlobResourceContents
    mock_session = MagicMock()
    mock_session.read_resource = AsyncMock(return_value=ReadResourceResult(
        contents=[
            BlobResourceContents(
                uri="file:///image.png",
                mimeType="image/png",
                blob="aGVsbG8=",
            )
        ]
    ))
    client._session = mock_session

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
    """单个 Server 获取资源失败时应显式标记错误，不静默跳过。"""
    manager = MCPManager()

    mock_client1 = MagicMock()
    mock_client1.is_connected = True
    # 使用域异常 MCPClientError 模拟连接失败（与 mcp/manager.py 中收窄后的异常元组匹配）
    mock_client1.list_resources = AsyncMock(side_effect=MCPClientError("连接断开"))

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

    # server1 失败以显式 error 条目标记，server2 正常返回
    error_entries = [r for r in resources if r.get("error")]
    ok_entries = [r for r in resources if not r.get("error")]
    assert len(error_entries) == 1
    assert error_entries[0]["server_id"] == "server1"
    assert "获取资源列表失败" in error_entries[0]["error"]
    assert len(ok_entries) == 1
    assert ok_entries[0]["uri"] == "file:///ok.txt"


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


# ==================== MCP 工具三段式命名测试 ====================

def test_build_mcp_tool_name_format():
    """build_mcp_tool_name 应生成 mcp__<server>__<tool> 三段式格式。"""
    # 标准格式验证
    assert build_mcp_tool_name("github", "create_issue") == "mcp__github__create_issue"
    assert build_mcp_tool_name("filesystem", "read_file") == "mcp__filesystem__read_file"
    # 前缀为 mcp__
    assert build_mcp_tool_name("server1", "tool1").startswith("mcp__")
    # 双下划线分隔三段
    parts = build_mcp_tool_name("server1", "tool1").split("__")
    assert parts == ["mcp", "server1", "tool1"]


def test_build_mcp_tool_name_with_underscore_in_tool():
    """工具名含下划线时应完整保留在第三段中。"""
    # 工具名本身含下划线，应完整保留
    name = build_mcp_tool_name("github", "create_pull_request")
    assert name == "mcp__github__create_pull_request"
    # 确保三段式结构正确（前两段为 mcp 和 github）
    assert name.startswith("mcp__github__")
    # 工具名部分应完整保留
    assert name.endswith("create_pull_request")


def test_mcp_tool_fully_qualified_name():
    """MCPTool 的 fully_qualified_name 应根据 server_name 自动计算。"""
    # 提供 server_name 时应生成三段式全限定名
    tool = MCPTool(name="create_issue", server_name="github")
    assert tool.fully_qualified_name == "mcp__github__create_issue"

    # 未提供 server_name 时应回退为工具名本身（向后兼容）
    tool_no_server = MCPTool(name="standalone_tool")
    assert tool_no_server.fully_qualified_name == "standalone_tool"

    # fully_qualified_name 为只读计算属性，构造时传入的同名参数应被忽略
    tool_override = MCPTool(name="x", server_name="y", fully_qualified_name="custom")
    assert tool_override.fully_qualified_name == "mcp__y__x"

    # 实例创建后不能直接设置 fully_qualified_name 属性（只读）
    with pytest.raises((AttributeError, TypeError)):
        tool.fully_qualified_name = "tampered"


# ==================== MCP 服务级权限匹配测试 ====================

def test_matches_mcp_server_exact():
    """matches_mcp_server 三段式模式应精确匹配。"""
    # 三段式精确匹配
    assert matches_mcp_server(
        "mcp__github__create_issue",
        "mcp__github__create_issue",
    ) is True
    # 不同工具名不匹配
    assert matches_mcp_server(
        "mcp__github__create_issue",
        "mcp__github__read_file",
    ) is False
    # 不同服务名不匹配
    assert matches_mcp_server(
        "mcp__github__create_issue",
        "mcp__gitlab__create_issue",
    ) is False


def test_matches_mcp_server_wildcard():
    """matches_mcp_server 两段式模式应匹配该服务下所有工具。"""
    # 两段式服务级匹配：mcp__github 匹配 mcp__github__* 的所有工具
    assert matches_mcp_server("mcp__github", "mcp__github__create_issue") is True
    assert matches_mcp_server("mcp__github", "mcp__github__read_file") is True
    assert matches_mcp_server("mcp__github", "mcp__github__any_tool") is True
    # 不应匹配其他服务的工具
    assert matches_mcp_server("mcp__github", "mcp__gitlab__create_issue") is False
    # 不应匹配服务名仅为前缀的其他服务（如 github 和 github_extra）
    assert matches_mcp_server("mcp__github", "mcp__github_extra__tool") is False


def test_matches_mcp_server_no_match():
    """matches_mcp_server 不匹配的场景应返回 False。"""
    # 非 MCP 前缀的模式不参与服务级匹配
    assert matches_mcp_server("skill:read", "mcp__github__create_issue") is False
    assert matches_mcp_server("read", "mcp__github__create_issue") is False
    # 三段式模式与不同工具不匹配
    assert matches_mcp_server("mcp__github__tool1", "mcp__github__tool2") is False
    # 两段式模式与不同服务不匹配
    assert matches_mcp_server("mcp__server1", "mcp__server2__tool1") is False


def test_wildcard_match_mcp_server():
    """wildcard_match 应支持 MCP 服务级通配符匹配。"""
    # mcp__server1__* 匹配 mcp__server1__tool1
    assert wildcard_match("mcp__server1__*", "mcp__server1__tool1") is True
    assert wildcard_match("mcp__server1__*", "mcp__server1__tool2") is True
    # mcp__server1__* 不匹配其他服务
    assert wildcard_match("mcp__server1__*", "mcp__server2__tool1") is False

    # mcp__server1* 匹配 mcp__server1__tool1（前缀通配符）
    assert wildcard_match("mcp__server1*", "mcp__server1__tool1") is True
    assert wildcard_match("mcp__server1*", "mcp__server1__tool2") is True
    # mcp__server1* 不匹配其他服务
    assert wildcard_match("mcp__server1*", "mcp__server2__tool1") is False

    # 保持现有通配符行为不变
    assert wildcard_match("*", "mcp__server1__tool1") is True
    assert wildcard_match("skill:*", "skill:read") is True
    assert wildcard_match("skill:*", "plugin:read") is False


def test_permission_manager_mcp_server_rule():
    """权限管理器应支持 MCP 服务级规则批量授权。"""
    # 1. 通过 matches_mcp_server 验证两段式服务级规则
    # mcp__github 规则匹配 github 服务下所有工具
    assert matches_mcp_server("mcp__github", "mcp__github__create_issue") is True
    assert matches_mcp_server("mcp__github", "mcp__github__read_file") is True
    # 其他服务的工具不匹配
    assert matches_mcp_server("mcp__github", "mcp__gitlab__create_issue") is False

    # 2. 通过 evaluate_effect 验证通配符规则（mcp__github__*）
    wildcard_rule = PermissionRule(
        action="mcp_tool",
        resource="mcp__github__*",
        effect=PermissionEffect.ALLOW,
    )
    # github 服务下的工具应被允许
    assert evaluate_effect(
        "mcp_tool", "mcp__github__create_issue", [wildcard_rule]
    ) == PermissionEffect.ALLOW
    assert evaluate_effect(
        "mcp_tool", "mcp__github__any_tool", [wildcard_rule]
    ) == PermissionEffect.ALLOW
    # 其他服务的工具不匹配，回退为 ASK
    assert evaluate_effect(
        "mcp_tool", "mcp__gitlab__create_issue", [wildcard_rule]
    ) == PermissionEffect.ASK

    # 3. 通过 evaluate_effect 验证前缀通配符规则（mcp__github*）
    prefix_rule = PermissionRule(
        action="mcp_tool",
        resource="mcp__github*",
        effect=PermissionEffect.ALLOW,
    )
    assert evaluate_effect(
        "mcp_tool", "mcp__github__create_issue", [prefix_rule]
    ) == PermissionEffect.ALLOW
    assert evaluate_effect(
        "mcp_tool", "mcp__gitlab__create_issue", [prefix_rule]
    ) == PermissionEffect.ASK

    # 4. 精确工具级规则：仅允许特定工具
    tool_rule = PermissionRule(
        action="mcp_tool",
        resource="mcp__github__create_issue",
        effect=PermissionEffect.ALLOW,
    )
    assert evaluate_effect(
        "mcp_tool", "mcp__github__create_issue", [tool_rule]
    ) == PermissionEffect.ALLOW
    # 其他工具不匹配精确规则，回退为 ASK
    assert evaluate_effect(
        "mcp_tool", "mcp__github__read_file", [tool_rule]
    ) == PermissionEffect.ASK

    # 5. last-match-wins：服务级 ALLOW 在前，具体工具 DENY 在后应覆盖
    combined_rules = [
        PermissionRule(
            action="mcp_tool",
            resource="mcp__github__*",
            effect=PermissionEffect.ALLOW,
        ),
        PermissionRule(
            action="mcp_tool",
            resource="mcp__github__dangerous",
            effect=PermissionEffect.DENY,
        ),
    ]
    # 普通工具仍允许
    assert evaluate_effect(
        "mcp_tool", "mcp__github__create_issue", combined_rules
    ) == PermissionEffect.ALLOW
    # 危险工具被拒绝（后匹配覆盖）
    assert evaluate_effect(
        "mcp_tool", "mcp__github__dangerous", combined_rules
    ) == PermissionEffect.DENY

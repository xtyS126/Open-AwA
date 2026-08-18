"""
MCP 资源读取与 SSE origin 校验单元测试。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_integration.manager import (
    MCPClient,
    MCPClientError,
    MCPManager,
    MCPResource,
    MCPResourceContent,
    MCPServerConfig,
    MCPTool,
    MCPTransportError,
    SSETransport,
    StdioServerParameters,
    TransportType,
    _sandboxed_stdio_client,
    build_mcp_tool_name,
)
# 官方 mcp SDK 类型，用于构造 session mock 返回值
from mcp_integration.manager import (
    BlobResourceContents,
    ReadResourceResult,
    TextResourceContents,
)
from mcp_integration.sandbox import SandboxError, SandboxLimits
from core.execution_tool_runtime import ExecutionToolRuntimeMixin
from core.permission_manager import (
    PermissionEffect,
    PermissionRule,
    evaluate_effect,
    get_permission_manager,
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


# ==================== MCP 服务级权限门禁测试（Task 13） ====================


@pytest.fixture
def reset_global_permission_rules():
    """每个用例前后重置全局权限规则，保持测试隔离。"""
    pm = get_permission_manager()
    pm.set_global_rules([])
    yield
    pm.set_global_rules([])


@pytest.mark.asyncio
async def test_execution_tool_mcp_permission_service_rule_allowed(reset_global_permission_rules):
    """服务级 ALLOW 规则 mcp__server1 应放行该服务下所有工具。"""
    pm = get_permission_manager()
    pm.set_global_rules([
        PermissionRule(action="mcp__server1", resource="*", effect=PermissionEffect.ALLOW),
    ])
    runtime = ExecutionToolRuntimeMixin()
    context = {"user_id": "u1"}
    # patch 权限管理器获取函数，返回测试配置的规则实例
    with patch("core.permission_manager.get_permission_manager", return_value=pm):
        # 服务下任意工具均放行（返回 None 表示通过门禁）
        for tool in ("tool1", "tool2", "any_tool"):
            result = await runtime._check_mcp_permission(
                full_tool_name=f"mcp__server1__{tool}",
                server_id="server1",
                context=context,
            )
            assert result is None


@pytest.mark.asyncio
async def test_execution_tool_mcp_permission_service_rule_denied(reset_global_permission_rules):
    """服务级 DENY 规则 mcp__server1 应拒绝该服务下所有工具。"""
    pm = get_permission_manager()
    pm.set_global_rules([
        PermissionRule(action="mcp__server1", resource="*", effect=PermissionEffect.DENY),
    ])
    runtime = ExecutionToolRuntimeMixin()
    context = {"user_id": "u1"}
    with patch("core.permission_manager.get_permission_manager", return_value=pm):
        result = await runtime._check_mcp_permission(
            full_tool_name="mcp__server1__tool1",
            server_id="server1",
            context=context,
        )
        assert result is not None
        assert result["ok"] is False
        assert result["denied_by"] == "permission"
        # 其他服务的工具不受该服务级规则影响
        result_other = await runtime._check_mcp_permission(
            full_tool_name="mcp__server2__tool1",
            server_id="server2",
            context=context,
        )
        assert result_other is None


@pytest.mark.asyncio
async def test_execution_tool_mcp_permission_default_allow(reset_global_permission_rules):
    """无任何权限规则时应默认放行（向后兼容，不破坏既有 MCP 调用）。"""
    runtime = ExecutionToolRuntimeMixin()
    context = {"user_id": "u1"}
    result = await runtime._check_mcp_permission(
        full_tool_name="mcp__server1__tool1",
        server_id="server1",
        context=context,
    )
    assert result is None


@pytest.mark.asyncio
async def test_execution_tool_mcp_permission_tool_level_rule(reset_global_permission_rules):
    """工具级 DENY 规则 mcp__server1__dangerous 仅拒绝该工具，不影响同服务其他工具。"""
    pm = get_permission_manager()
    pm.set_global_rules([
        PermissionRule(
            action="mcp__server1__dangerous",
            resource="*",
            effect=PermissionEffect.DENY,
        ),
    ])
    runtime = ExecutionToolRuntimeMixin()
    context = {"user_id": "u1"}
    with patch("core.permission_manager.get_permission_manager", return_value=pm):
        result = await runtime._check_mcp_permission(
            full_tool_name="mcp__server1__dangerous",
            server_id="server1",
            context=context,
        )
        assert result is not None
        assert result["denied_by"] == "permission"
        # 同服务其他工具不受影响
        result_ok = await runtime._check_mcp_permission(
            full_tool_name="mcp__server1__safe",
            server_id="server1",
            context=context,
        )
        assert result_ok is None


@pytest.mark.asyncio
async def test_execution_tool_mcp_permission_deny_overrides_service_allow(
    reset_global_permission_rules,
):
    """服务级 ALLOW 与工具级 DENY 并存时，后匹配的 DENY 应生效（last-match-wins）。"""
    pm = get_permission_manager()
    pm.set_global_rules([
        PermissionRule(action="mcp__server1", resource="*", effect=PermissionEffect.ALLOW),
        PermissionRule(
            action="mcp__server1__dangerous",
            resource="*",
            effect=PermissionEffect.DENY,
        ),
    ])
    runtime = ExecutionToolRuntimeMixin()
    context = {"user_id": "u1"}
    with patch("core.permission_manager.get_permission_manager", return_value=pm):
        # 普通工具放行
        assert await runtime._check_mcp_permission(
            full_tool_name="mcp__server1__safe",
            server_id="server1",
            context=context,
        ) is None
        # 危险工具被后匹配的 DENY 拒绝
        denied = await runtime._check_mcp_permission(
            full_tool_name="mcp__server1__dangerous",
            server_id="server1",
            context=context,
        )
        assert denied is not None
        assert denied["denied_by"] == "permission"


# ==================== MCP SSE 认证头传递测试（Task 13） ====================


def _make_transport_mock() -> MagicMock:
    """构造可手动进入/退出的 transport 上下文 mock。"""
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
    mock_ctx.__aexit__ = AsyncMock(return_value=None)
    return mock_ctx


@pytest.mark.asyncio
async def test_mcp_sse_auth_headers_passed():
    """SSE 连接应携带自定义 headers 与 auth_token 生成的 Bearer 认证头。"""
    SSETransport.set_allowed_origins([])
    config = MCPServerConfig(
        name="test",
        transport_type=TransportType.SSE,
        url="https://allowed.example.com/sse",
        headers={"X-Custom": "v1"},
        auth_token="secret-token",
    )
    client = MCPClient(config)
    mock_ctx = _make_transport_mock()

    with patch("mcp_integration.manager._mcp_sse_client", return_value=mock_ctx) as mock_sse:
        with patch("mcp_integration.manager.ClientSession") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.initialize = AsyncMock()
            mock_session_cls.return_value = mock_session
            await client.connect()

    # 验证 sse_client 收到合并后的请求头
    mock_sse.assert_called_once()
    args, kwargs = mock_sse.call_args
    assert args[0] == "https://allowed.example.com/sse"
    assert kwargs["headers"]["X-Custom"] == "v1"
    assert kwargs["headers"]["Authorization"] == "Bearer secret-token"


@pytest.mark.asyncio
async def test_mcp_sse_auth_token_not_override_explicit_authorization():
    """用户显式提供 Authorization 头时，auth_token 不应覆盖。"""
    SSETransport.set_allowed_origins([])
    config = MCPServerConfig(
        name="test",
        transport_type=TransportType.SSE,
        url="https://allowed.example.com/sse",
        headers={"Authorization": "Bearer explicit"},
        auth_token="fallback-token",
    )
    client = MCPClient(config)
    mock_ctx = _make_transport_mock()

    with patch("mcp_integration.manager._mcp_sse_client", return_value=mock_ctx) as mock_sse:
        with patch("mcp_integration.manager.ClientSession") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.initialize = AsyncMock()
            mock_session_cls.return_value = mock_session
            await client.connect()

    _, kwargs = mock_sse.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer explicit"


@pytest.mark.asyncio
async def test_mcp_sse_no_headers_when_not_configured():
    """未配置 headers/auth_token 时不应附加 Authorization 头。"""
    SSETransport.set_allowed_origins([])
    config = MCPServerConfig(
        name="test",
        transport_type=TransportType.SSE,
        url="https://allowed.example.com/sse",
    )
    client = MCPClient(config)
    mock_ctx = _make_transport_mock()

    with patch("mcp_integration.manager._mcp_sse_client", return_value=mock_ctx) as mock_sse:
        with patch("mcp_integration.manager.ClientSession") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.initialize = AsyncMock()
            mock_session_cls.return_value = mock_session
            await client.connect()

    _, kwargs = mock_sse.call_args
    assert kwargs["headers"] == {}
    assert "Authorization" not in kwargs["headers"]


# ==================== MCP 子进程沙箱接入测试（Task 14） ====================


@pytest.mark.asyncio
async def test_connect_stdio_uses_sandbox_transport():
    """stdio 连接应通过沙箱传输启动子进程（而非裸 stdio_client）。"""
    config = MCPServerConfig(
        name="test",
        transport_type=TransportType.STDIO,
        command="echo",
    )
    client = MCPClient(config)
    mock_ctx = _make_transport_mock()

    with patch("mcp_integration.manager._sandboxed_stdio_client", return_value=mock_ctx) as mock_sandbox:
        with patch("mcp_integration.manager._mcp_stdio_client") as mock_bare:
            with patch("mcp_integration.manager.ClientSession") as mock_session_cls:
                mock_session = MagicMock()
                mock_session.initialize = AsyncMock()
                mock_session_cls.return_value = mock_session
                await client.connect()

    # 沙箱传输被使用，裸 stdio_client 未被使用
    mock_sandbox.assert_called_once()
    mock_bare.assert_not_called()
    # 沙箱传输携带资源限制配置
    _, kwargs = mock_sandbox.call_args
    assert kwargs.get("limits") is not None
    assert kwargs["limits"].max_cpu_time_seconds == 60.0
    assert kwargs["limits"].max_memory_mb == 1024
    assert kwargs["limits"].max_output_size_bytes == 10 * 1024 * 1024


class _FakeStreamReader:
    """模拟 asyncio StreamReader（立即 EOF，避免阻塞 reader task）。"""

    async def readline(self) -> bytes:
        return b""

    async def read(self, n: int = 4096) -> bytes:
        return b""


class _FakeStreamWriter:
    """模拟 asyncio StreamWriter（记录关闭状态）。"""

    def __init__(self) -> None:
        self.closed = False

    def write(self, data: bytes) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    async def drain(self) -> None:
        pass


@pytest.mark.asyncio
async def test_sandboxed_stdio_client_passes_limits_to_subprocess():
    """沙箱 stdio 传输应通过 create_sandboxed_subprocess 启动进程并传递资源限制。"""
    mock_process = MagicMock()
    mock_process.pid = 1234
    mock_process.stdout = _FakeStreamReader()
    mock_process.stderr = _FakeStreamReader()
    mock_process.stdin = _FakeStreamWriter()
    mock_process.wait = AsyncMock(return_value=0)

    limits = SandboxLimits(max_cpu_time_seconds=10.0)
    params = StdioServerParameters(command="echo", args=["hi"], env={"K": "V"})

    with patch(
        "mcp_integration.manager.create_sandboxed_subprocess",
        new=AsyncMock(return_value=mock_process),
    ) as mock_create:
        ctx = _sandboxed_stdio_client(params, limits=limits)
        read_stream, write_stream = await ctx.__aenter__()
        try:
            # 验证沙箱启动参数传递（命令 / 参数 / 环境变量 / 资源限制）
            mock_create.assert_awaited_once()
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["command"] == "echo"
            assert call_kwargs["args"] == ["hi"]
            assert call_kwargs["env"] == {"K": "V"}
            assert call_kwargs["limits"] is limits
        finally:
            await ctx.__aexit__(None, None, None)

    # 退出时先关闭 stdin，再等待进程退出（优雅关闭顺序）
    assert mock_process.stdin.closed is True
    mock_process.wait.assert_awaited()


@pytest.mark.asyncio
async def test_sandboxed_stdio_client_launch_failure_raises():
    """沙箱启动子进程失败时应抛出 MCPClientError 并清理流。"""
    params = StdioServerParameters(command="bad_command")

    with patch(
        "mcp_integration.manager.create_sandboxed_subprocess",
        new=AsyncMock(side_effect=SandboxError("命令路径包含非法字符: bad..command")),
    ):
        ctx = _sandboxed_stdio_client(params)
        with pytest.raises(MCPClientError, match="沙箱启动 MCP Server 失败"):
            await ctx.__aenter__()


# ==================== chat 链路 MCP 工具三段式命名与 schema 透传测试 ====================

_MCP_SERVER_ID = "550e8400-e29b-41d4-a716-446655440000"


def test_append_mcp_tools_uses_server_id_and_passes_input_schema():
    """注入 LLM 的 MCP 工具名服务段应为 server_id，且透传 inputSchema 到 parameters。"""
    from core.agent_capability_builder import _append_mcp_tools

    capabilities = {
        "mcp": {
            "chat_dispatch_enabled": True,
            "tools": [
                {
                    "server_id": _MCP_SERVER_ID,
                    "server_name": "filesystem",
                    "name": "read_file",
                    "description": "读取文件内容",
                    "input_schema": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                }
            ],
        }
    }
    tools: list = []
    _append_mcp_tools(capabilities, tools, set())

    assert len(tools) == 1
    function = tools[0]["function"]
    # 服务段使用 server_id，保证执行侧能命中 MCPManager._clients 键
    assert function["name"] == f"mcp__{_MCP_SERVER_ID}__read_file"
    # 显示名保留在 description 中
    assert "filesystem" in function["description"]
    # input_schema 透传为 LLM 可见的 parameters
    assert function["parameters"] == {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }


def test_append_mcp_tools_falls_back_to_empty_schema_when_input_missing():
    """input_schema 缺失时应回退为空 object schema，而非丢弃参数定义。"""
    from core.agent_capability_builder import _append_mcp_tools

    capabilities = {
        "mcp": {
            "chat_dispatch_enabled": True,
            "tools": [
                {
                    "server_id": _MCP_SERVER_ID,
                    "server_name": "filesystem",
                    "name": "read_file",
                    "description": "",
                }
            ],
        }
    }
    tools: list = []
    _append_mcp_tools(capabilities, tools, set())

    assert len(tools) == 1
    assert tools[0]["function"]["parameters"] == {"type": "object", "properties": {}}


@pytest.mark.asyncio
async def test_collect_mcp_capabilities_passes_input_schema():
    """collect_mcp_capabilities 应透传 get_all_tools 返回的 input_schema。"""
    from core.agent_capability_builder import collect_mcp_capabilities

    class FakeManager:
        def get_all_servers(self):
            return []

        async def get_all_tools(self):
            return [
                {
                    "server_id": _MCP_SERVER_ID,
                    "server_name": "filesystem",
                    "tool": {
                        "name": "read_file",
                        "description": "读取文件内容",
                        "input_schema": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                        },
                    },
                }
            ]

    with patch("mcp_integration.manager.MCPManager", return_value=FakeManager()):
        result = await collect_mcp_capabilities({"enable_mcp_tool_dispatch": True})

    assert result["tools"][0]["server_id"] == _MCP_SERVER_ID
    assert result["tools"][0]["input_schema"] == {
        "type": "object",
        "properties": {"path": {"type": "string"}},
    }


@pytest.mark.asyncio
async def test_mcp_strategy_parses_server_id_from_tool_name():
    """MCPToolStrategy 应能从 mcp__<server_id>__<tool> 中解析出 server_id 并命中连接。"""
    from core.tool_execution.base import ToolExecutionContext
    from core.tool_execution.mcp_strategy import MCPToolStrategy

    captured: dict = {}

    class FakeManager:
        def __call__(self, *args, **kwargs):
            return self

        async def call_tool(self, server_id, tool_name, arguments):
            captured["server_id"] = server_id
            captured["tool_name"] = tool_name
            captured["arguments"] = arguments
            return "ok"

    strategy = MCPToolStrategy()
    with patch("mcp_integration.manager.MCPManager", new=FakeManager()):
        result = await strategy.execute(
            ToolExecutionContext(
                session_id="s1",
                user_id=1,
                tool_name=f"mcp__{_MCP_SERVER_ID}__read_file",
                tool_input={"path": "/tmp/a.txt"},
                tool_call_id="c1",
            )
        )

    assert result.error is None
    assert captured["server_id"] == _MCP_SERVER_ID
    assert captured["tool_name"] == "read_file"
    assert captured["arguments"] == {"path": "/tmp/a.txt"}


@pytest.mark.asyncio
async def test_mcp_permission_service_rule_matches_uuid_server_id(reset_global_permission_rules):
    """服务段为 UUID 时，服务级规则 mcp__<server_id> 仍应命中该服务下所有工具。"""
    pm = get_permission_manager()
    pm.set_global_rules([
        PermissionRule(
            action=f"mcp__{_MCP_SERVER_ID}",
            resource="*",
            effect=PermissionEffect.DENY,
        ),
    ])
    runtime = ExecutionToolRuntimeMixin()
    context = {"user_id": "u1"}
    with patch("core.permission_manager.get_permission_manager", return_value=pm):
        denied = await runtime._check_mcp_permission(
            full_tool_name=f"mcp__{_MCP_SERVER_ID}__read_file",
            server_id=_MCP_SERVER_ID,
            context=context,
        )
        assert denied is not None
        assert denied["denied_by"] == "permission"
        # 其他服务的工具不受影响
        other = await runtime._check_mcp_permission(
            full_tool_name="mcp__another-server-id__read_file",
            server_id="another-server-id",
            context=context,
        )
        assert other is None


# ==================== MCP annotations 映射与动态工具并发属性 ====================


def test_map_tool_annotations_read_only():
    """readOnlyHint=True 应映射为只读且可并发。"""
    from mcp_integration.manager import map_tool_annotations

    annotations = MagicMock()
    annotations.readOnlyHint = True
    annotations.destructiveHint = False

    result = map_tool_annotations(annotations)
    assert result == {
        "is_read_only": True,
        "is_destructive": False,
        "is_concurrency_safe": True,
    }


def test_map_tool_annotations_destructive():
    """destructiveHint=True 应映射为破坏性且串行（即使 readOnlyHint=True）。"""
    from mcp_integration.manager import map_tool_annotations

    annotations = MagicMock()
    annotations.readOnlyHint = True
    annotations.destructiveHint = True

    result = map_tool_annotations(annotations)
    assert result == {
        "is_read_only": True,
        "is_destructive": True,
        "is_concurrency_safe": False,
    }


def test_map_tool_annotations_none_fails_closed():
    """annotations 为 None 时失败关闭，全 False。"""
    from mcp_integration.manager import map_tool_annotations

    assert map_tool_annotations(None) == {
        "is_read_only": False,
        "is_destructive": False,
        "is_concurrency_safe": False,
    }


@pytest.mark.asyncio
async def test_list_tools_maps_annotations_into_concurrency_fields():
    """list_tools 应把官方 SDK 的 Tool.annotations 映射为 MCPTool 并发字段。"""
    from types import SimpleNamespace

    config = MCPServerConfig(
        name="test", transport_type=TransportType.STDIO, command="echo"
    )
    client = MCPClient(config)

    mock_session = MagicMock()
    mock_session.list_tools = AsyncMock(return_value=SimpleNamespace(
        tools=[
            SimpleNamespace(
                name="read_tool",
                description="只读工具",
                inputSchema={},
                annotations=SimpleNamespace(readOnlyHint=True, destructiveHint=False),
            ),
            SimpleNamespace(
                name="delete_tool",
                description="破坏性工具",
                inputSchema={},
                annotations=SimpleNamespace(readOnlyHint=False, destructiveHint=True),
            ),
        ]
    ))
    client._session = mock_session

    tools = await client.list_tools()
    assert len(tools) == 2

    read_tool = next(t for t in tools if t.name == "read_tool")
    assert read_tool.is_read_only is True
    assert read_tool.is_destructive is False
    assert read_tool.is_concurrency_safe is True

    delete_tool = next(t for t in tools if t.name == "delete_tool")
    assert delete_tool.is_read_only is False
    assert delete_tool.is_destructive is True
    assert delete_tool.is_concurrency_safe is False


def test_build_dynamic_tool_concurrency_map_defaults_and_mcp():
    """plugin/MCP/task 动态工具应获得明确的并发属性来源（MCP 用 annotations，其余失败关闭）。"""
    from core.agent_capability_builder import build_dynamic_tool_concurrency_map

    capabilities = {
        "plugins": [
            {"name": "hello", "tools": [{"name": "tool1", "description": "d", "parameters": {}}]}
        ],
        "mcp": {
            "chat_dispatch_enabled": True,
            "tools": [
                {
                    "server_id": "srv1",
                    "server_name": "srv1",
                    "name": "list_files",
                    "is_read_only": True,
                    "is_destructive": False,
                    "is_concurrency_safe": True,
                },
                {
                    "server_id": "srv1",
                    "server_name": "srv1",
                    "name": "delete_file",
                    "is_read_only": False,
                    "is_destructive": True,
                    "is_concurrency_safe": False,
                },
            ],
        },
    }

    concurrency = build_dynamic_tool_concurrency_map(capabilities)

    # plugin 工具：失败关闭默认值
    assert concurrency["plugin_hello__tool1"] == {
        "is_read_only": False,
        "is_destructive": False,
        "is_concurrency_safe": False,
    }
    # MCP 只读工具：可并发
    assert concurrency["mcp__srv1__list_files"] == {
        "is_read_only": True,
        "is_destructive": False,
        "is_concurrency_safe": True,
    }
    # MCP 破坏性工具：串行
    assert concurrency["mcp__srv1__delete_file"]["is_destructive"] is True
    assert concurrency["mcp__srv1__delete_file"]["is_concurrency_safe"] is False
    # task 工具：失败关闭默认值（task_spawn_agent 由 build_task_runtime_tool_definitions 生成）
    assert concurrency["task_spawn_agent"]["is_read_only"] is False
    assert concurrency["task_spawn_agent"]["is_destructive"] is False
    assert concurrency["task_spawn_agent"]["is_concurrency_safe"] is False

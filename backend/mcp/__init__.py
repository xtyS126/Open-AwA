"""
MCP (Model Context Protocol) 模块初始化文件。
基于官方 mcp Python SDK，提供类型定义、客户端与管理器。

原 types.py / protocol.py / transport.py / client.py 四个文件已合并到 manager.py，
由官方 mcp SDK 的 ClientSession / stdio_client / sse_client 统一处理协议层与传输层。
"""

from mcp.config_store import MCPConfigStore
from mcp.manager import (
    MCPClient,
    MCPClientError,
    MCPManager,
    MCPMessage,
    MCPResource,
    MCPResourceContent,
    MCPServerConfig,
    MCPTool,
    MCPToolCallRequest,
    MCPToolCallResponse,
    MCPTransportError,
    SSETransport,
    TransportType,
    build_mcp_tool_name,
    is_mcp_session_expired_error,
)

__all__ = [
    "MCPTool",
    "MCPResource",
    "MCPResourceContent",
    "MCPServerConfig",
    "MCPToolCallRequest",
    "MCPToolCallResponse",
    "MCPMessage",
    "MCPClient",
    "MCPClientError",
    "MCPTransportError",
    "MCPConfigStore",
    "MCPManager",
    "SSETransport",
    "TransportType",
    "build_mcp_tool_name",
    "is_mcp_session_expired_error",
]

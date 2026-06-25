"""
MCP 协议类型定义模块，声明工具、资源、服务器配置及消息格式等数据结构。
所有类型均基于 Pydantic BaseModel，用于请求校验与序列化。
"""

from pydantic import BaseModel, ConfigDict, Field, computed_field
from typing import Optional, List, Dict, Any
from enum import Enum


# MCP 工具全限定名前缀，三段式格式 mcp__<server>__<tool>
MCP_TOOL_NAME_PREFIX = "mcp__"
MCP_TOOL_NAME_SEPARATOR = "__"


def build_mcp_tool_name(server: str, tool: str) -> str:
    """
    构建 MCP 工具的三段式全限定名。

    格式：mcp__<server>__<tool>（双下划线分隔）
    示例：build_mcp_tool_name("github", "create_issue") -> "mcp__github__create_issue"

    :param server: MCP Server 名称
    :param tool: 工具名称
    :return: 三段式全限定名
    :raises ValueError: server 或 tool 为空时抛出
    """
    if not server:
        raise ValueError("server 不能为空")
    if not tool:
        raise ValueError("tool 不能为空")
    return f"{MCP_TOOL_NAME_PREFIX}{server}{MCP_TOOL_NAME_SEPARATOR}{tool}"


class TransportType(str, Enum):
    """MCP 传输类型枚举"""
    STDIO = "stdio"
    SSE = "sse"


class MCPTool(BaseModel):
    """MCP 工具定义，描述远程 Server 提供的可调用工具"""
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., description="工具名称")
    description: Optional[str] = Field(None, description="工具描述")
    input_schema: Optional[Dict[str, Any]] = Field(None, alias="inputSchema", description="工具输入参数的 JSON Schema")
    server_name: Optional[str] = Field(None, description="所属 MCP Server 名称，用于生成全限定名")

    @computed_field  # type: ignore[misc]
    @property
    def fully_qualified_name(self) -> str:
        """
        工具全限定名（只读），格式 mcp__<server>__<tool>。

        当 server_name 已提供时返回三段式全限定名；
        否则回退为工具名本身，保证向后兼容。
        """
        if self.server_name:
            return build_mcp_tool_name(self.server_name, self.name)
        return self.name


class MCPResource(BaseModel):
    """MCP 资源定义，描述远程 Server 提供的可读资源"""
    model_config = ConfigDict(populate_by_name=True)

    uri: str = Field(..., description="资源唯一标识符")
    name: str = Field(..., description="资源名称")
    description: Optional[str] = Field(None, description="资源描述")
    mime_type: Optional[str] = Field(None, alias="mimeType", description="资源 MIME 类型")


class MCPResourceContent(BaseModel):
    """MCP 资源内容，包含读取资源后返回的实际数据"""
    model_config = ConfigDict(populate_by_name=True)

    uri: str = Field(..., description="资源唯一标识符")
    mime_type: Optional[str] = Field(None, alias="mimeType", description="资源 MIME 类型")
    text: Optional[str] = Field(None, description="文本内容（文本资源）")
    blob: Optional[str] = Field(None, description="Base64 编码的二进制内容（二进制资源）")


class MCPServerConfig(BaseModel):
    """MCP Server 连接配置"""
    name: str = Field(..., description="服务器显示名称")
    command: Optional[str] = Field(None, description="stdio 模式下的启动命令")
    args: Optional[List[str]] = Field(default_factory=list, description="启动命令参数")
    env: Optional[Dict[str, str]] = Field(default_factory=dict, description="环境变量")
    transport_type: TransportType = Field(default=TransportType.STDIO, description="传输类型")
    url: Optional[str] = Field(None, description="SSE 模式下的远程服务器地址")


class MCPToolCallRequest(BaseModel):
    """工具调用请求"""
    tool_name: str = Field(..., description="工具名称")
    arguments: Optional[Dict[str, Any]] = Field(default_factory=dict, description="调用参数")


class MCPToolCallResponse(BaseModel):
    """工具调用响应"""
    result: Any = Field(None, description="调用结果")
    is_error: bool = Field(False, description="是否为错误响应")


class MCPMessage(BaseModel):
    """JSON-RPC 2.0 消息格式"""
    jsonrpc: str = Field(default="2.0", description="JSON-RPC 版本")
    id: Optional[int] = Field(None, description="请求标识符")
    method: Optional[str] = Field(None, description="方法名称")
    params: Optional[Dict[str, Any]] = Field(None, description="方法参数")
    result: Optional[Any] = Field(None, description="响应结果")
    error: Optional[Dict[str, Any]] = Field(None, description="错误信息")

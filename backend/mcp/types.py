"""
MCP 协议类型定义模块，声明工具、资源、服务器配置及消息格式等数据结构。
所有类型均基于 Pydantic BaseModel，用于请求校验与序列化。
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum


class TransportType(str, Enum):
    """MCP 传输类型枚举"""
    STDIO = "stdio"
    SSE = "sse"


class MCPTool(BaseModel):
    """MCP 工具定义，描述远程 Server 提供的可调用工具"""
    name: str = Field(..., description="工具名称")
    description: Optional[str] = Field(None, description="工具描述")
    input_schema: Optional[Dict[str, Any]] = Field(None, alias="inputSchema", description="工具输入参数的 JSON Schema")

    class Config:
        populate_by_name = True


class MCPResource(BaseModel):
    """MCP 资源定义，描述远程 Server 提供的可读资源"""
    uri: str = Field(..., description="资源唯一标识符")
    name: str = Field(..., description="资源名称")
    description: Optional[str] = Field(None, description="资源描述")
    mime_type: Optional[str] = Field(None, alias="mimeType", description="资源 MIME 类型")

    class Config:
        populate_by_name = True


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

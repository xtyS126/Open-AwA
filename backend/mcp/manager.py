"""
MCP 管理器模块，负责管理多个 MCP Server 的连接生命周期。
采用单例模式，提供全局统一的 MCP Server 管理入口。
"""

import uuid
from typing import Any, Dict, List, Optional

from loguru import logger

from mcp.client import MCPClient, MCPClientError
from mcp.types import MCPServerConfig, MCPTool, MCPToolCallResponse


class MCPManager:
    """
    MCP 管理器，管理多个 MCP Server 的连接、工具发现与调用。
    使用单例模式确保全局唯一实例。
    """

    _instance: Optional["MCPManager"] = None

    def __new__(cls) -> "MCPManager":
        """单例模式：确保全局只有一个管理器实例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化管理器内部状态（仅首次创建时执行）"""
        if self._initialized:
            return
        self._clients: Dict[str, MCPClient] = {}
        self._configs: Dict[str, MCPServerConfig] = {}
        self._initialized = True
        logger.bind(module="mcp.manager", event="initialized").info("MCP 管理器已初始化")

    def add_server(self, config: MCPServerConfig, server_id: Optional[str] = None) -> str:
        """
        添加 MCP Server 配置。
        :param config: 服务器配置
        :param server_id: 可选的自定义 ID，未指定则自动生成
        :return: 分配的 server_id
        """
        if server_id is None:
            server_id = str(uuid.uuid4())
        self._configs[server_id] = config
        self._clients[server_id] = MCPClient(config)
        logger.bind(module="mcp.manager", event="server_added").info(
            f"添加 MCP Server: {config.name} (ID: {server_id})"
        )
        return server_id

    def remove_server(self, server_id: str) -> None:
        """
        移除 MCP Server 配置并断开连接。
        :param server_id: 服务器 ID
        """
        if server_id not in self._clients:
            raise MCPClientError(f"未找到 MCP Server: {server_id}")
        # 如果当前已连接则需要先在调用方 await disconnect
        self._clients.pop(server_id, None)
        self._configs.pop(server_id, None)
        logger.bind(module="mcp.manager", event="server_removed").info(
            f"已移除 MCP Server: {server_id}"
        )

    async def connect_server(self, server_id: str) -> None:
        """
        连接指定的 MCP Server。
        :param server_id: 服务器 ID
        """
        client = self._get_client(server_id)
        await client.connect()

    async def disconnect_server(self, server_id: str) -> None:
        """
        断开指定的 MCP Server 连接。
        :param server_id: 服务器 ID
        """
        client = self._get_client(server_id)
        await client.disconnect()

    async def get_all_tools(self) -> List[Dict[str, Any]]:
        """
        聚合所有已连接 Server 的工具列表。
        :return: 包含 server_id 信息的工具列表
        """
        all_tools: List[Dict[str, Any]] = []
        for server_id, client in self._clients.items():
            if client.is_connected:
                try:
                    tools = await client.list_tools()
                    for tool in tools:
                        all_tools.append({
                            "server_id": server_id,
                            "server_name": client.config.name,
                            "tool": tool.model_dump(),
                        })
                except MCPClientError as e:
                    logger.bind(module="mcp.manager", event="list_tools_error").warning(
                        f"获取 Server {server_id} 工具列表失败: {e}"
                    )
        return all_tools

    async def call_tool(
        self, server_id: str, tool_name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> MCPToolCallResponse:
        """
        调用指定 Server 上的工具。
        :param server_id: 服务器 ID
        :param tool_name: 工具名称
        :param arguments: 调用参数
        :return: 工具调用响应
        """
        client = self._get_client(server_id)
        if not client.is_connected:
            raise MCPClientError(f"MCP Server 未连接: {server_id}")
        return await client.call_tool(tool_name, arguments)

    async def get_server_tools(self, server_id: str) -> List[MCPTool]:
        """
        获取指定 Server 的工具列表。
        :param server_id: 服务器 ID
        :return: 工具列表
        """
        client = self._get_client(server_id)
        if not client.is_connected:
            raise MCPClientError(f"MCP Server 未连接: {server_id}")
        return await client.list_tools()

    def get_server_status(self, server_id: str) -> Dict[str, Any]:
        """
        获取指定 Server 的连接状态信息。
        :param server_id: 服务器 ID
        :return: 状态信息字典
        """
        client = self._get_client(server_id)
        config = self._configs.get(server_id)
        return {
            "server_id": server_id,
            "name": config.name if config else "unknown",
            "transport_type": config.transport_type.value if config else "unknown",
            "connected": client.is_connected,
            "tools_count": len(client.tools),
        }

    def get_all_servers(self) -> List[Dict[str, Any]]:
        """
        获取所有已配置的 Server 状态列表。
        :return: 服务器状态列表
        """
        servers = []
        for server_id in self._configs:
            servers.append(self.get_server_status(server_id))
        return servers

    def _get_client(self, server_id: str) -> MCPClient:
        """
        获取指定 ID 的客户端实例。
        :param server_id: 服务器 ID
        :return: MCPClient 实例
        :raises MCPClientError: 未找到对应 ID 的客户端
        """
        client = self._clients.get(server_id)
        if client is None:
            raise MCPClientError(f"未找到 MCP Server: {server_id}")
        return client

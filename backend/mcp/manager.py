"""
MCP 管理器模块，负责管理多个 MCP Server 的连接生命周期。
采用单例模式，提供全局统一的 MCP Server 管理入口。
"""

import threading
import uuid
from typing import Any, Dict, List, Optional

from loguru import logger

from mcp.client import MCPClient, MCPClientError
from mcp.types import MCPServerConfig, MCPTool, MCPToolCallResponse


class MCPManager:
    """
    MCP 管理器，管理多个 MCP Server 的连接、工具发现与调用。
    使用单例模式确保全局唯一实例，通过 threading.RLock 保证创建与初始化都线程安全。
    """

    _instance: Optional["MCPManager"] = None
    _instance_lock = threading.RLock()

    def __new__(cls) -> "MCPManager":
        """单例模式：使用双重检查减少无意义加锁，并确保只创建一次实例。"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化管理器内部状态（仅首次创建时执行）。"""
        if getattr(self, "_initialized", False):
            return

        with type(self)._instance_lock:
            if self._initialized:
                return

            self._lock = threading.Lock()
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
        with self._lock:
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
        with self._lock:
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
        # 创建字典快照，避免迭代期间并发修改导致 RuntimeError
        with self._lock:
            clients_snapshot = dict(self._clients)
        for server_id, client in clients_snapshot.items():
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
        # 创建快照避免并发修改
        with self._lock:
            config_ids = list(self._configs.keys())
        for server_id in config_ids:
            servers.append(self.get_server_status(server_id))
        return servers

    def is_server_connected(self, server_id: str) -> bool:
        """
        检查指定 Server 是否已连接。
        :param server_id: 服务器 ID
        :return: 是否已连接
        """
        with self._lock:
            client = self._clients.get(server_id)
        if client is None:
            return False
        return client.is_connected

    def _get_client(self, server_id: str) -> MCPClient:
        """
        获取指定 ID 的客户端实例。
        :param server_id: 服务器 ID
        :return: MCPClient 实例
        :raises MCPClientError: 未找到对应 ID 的客户端
        """
        with self._lock:
            client = self._clients.get(server_id)
        if client is None:
            raise MCPClientError(f"未找到 MCP Server: {server_id}")
        return client

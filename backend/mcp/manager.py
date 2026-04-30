"""
MCP 管理器模块，负责管理多个 MCP Server 的连接生命周期。
采用单例模式，提供全局统一的 MCP Server 管理入口。
支持配置持久化、热更新检测与版本回滚。
"""

import threading
import uuid
from typing import Any, Dict, List, Optional

from loguru import logger

from mcp.client import MCPClient, MCPClientError
from mcp.config_store import MCPConfigStore
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
            self._config_store = MCPConfigStore()
            self._initialized = True

        logger.bind(module="mcp.manager", event="initialized").info("MCP 管理器已初始化")
        # 启动时尝试从持久化配置恢复
        self._restore_from_persistent_config()

    def add_server(self, config: MCPServerConfig, server_id: Optional[str] = None) -> str:
        """
        添加 MCP Server 配置并持久化。
        :param config: 服务器配置
        :param server_id: 可选的自定义 ID，未指定则自动生成
        :return: 分配的 server_id
        """
        if server_id is None:
            server_id = str(uuid.uuid4())
        with self._lock:
            self._configs[server_id] = config
            self._clients[server_id] = MCPClient(config)
        # 持久化到配置文件
        self._config_store.set_server(server_id, config.model_dump())
        logger.bind(module="mcp.manager", event="server_added").info(
            f"添加 MCP Server: {config.name} (ID: {server_id})"
        )
        return server_id

    def remove_server(self, server_id: str) -> None:
        """
        移除 MCP Server 配置、断开连接并从持久化存储中删除。
        如果客户端已连接，会先尽力通过 cleanup_sync 清理子进程资源。
        :param server_id: 服务器 ID
        """
        with self._lock:
            if server_id not in self._clients:
                raise MCPClientError(f"未找到 MCP Server: {server_id}")
            client = self._clients.pop(server_id, None)
            self._configs.pop(server_id, None)
        # 尽力清理客户端持有的子进程资源
        if client is not None:
            client.cleanup_sync()
        # 从持久化存储中删除
        self._config_store.remove_server(server_id)
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

    def _restore_from_persistent_config(self) -> None:
        """启动时从持久化配置文件恢复 Server 配置（不自动连接）。"""
        try:
            saved_configs = self._config_store.load_all()
            if not saved_configs:
                return
            restored = 0
            for server_id, config_dict in saved_configs.items():
                if server_id in self._configs:
                    continue
                try:
                    config = MCPServerConfig(**config_dict)
                    with self._lock:
                        self._configs[server_id] = config
                        self._clients[server_id] = MCPClient(config)
                    restored += 1
                except Exception as exc:
                    logger.bind(
                        module="mcp.manager", event="restore_error", server_id=server_id
                    ).warning(f"恢复 MCP Server 配置失败: {exc}")
            if restored > 0:
                logger.bind(module="mcp.manager", event="restored").info(
                    f"从持久化配置恢复了 {restored} 个 MCP Server"
                )
        except Exception as exc:
            logger.bind(module="mcp.manager", event="restore_error").error(
                f"恢复持久化 MCP 配置时发生错误: {exc}"
            )

    def check_hot_reload(self) -> bool:
        """
        检测配置文件是否被外部修改，如果有变更则重新加载并同步内存状态。
        :return: 是否发生了热更新
        """
        new_configs = self._config_store.reload_if_changed()
        if new_configs is None:
            return False

        with self._lock:
            current_ids = set(self._configs.keys())
            new_ids = set(new_configs.keys())

            # 移除已删除的配置——先清理子进程资源再移除
            for removed_id in current_ids - new_ids:
                old_client = self._clients.pop(removed_id, None)
                self._configs.pop(removed_id, None)
                if old_client is not None:
                    old_client.cleanup_sync()
                logger.bind(module="mcp.manager", event="hot_reload_remove").info(
                    f"热更新：移除 Server {removed_id}"
                )

            # 添加新增或更新的配置
            for server_id, config_dict in new_configs.items():
                try:
                    config = MCPServerConfig(**config_dict)
                    if server_id not in self._configs:
                        self._configs[server_id] = config
                        self._clients[server_id] = MCPClient(config)
                        logger.bind(module="mcp.manager", event="hot_reload_add").info(
                            f"热更新：添加 Server {config.name} ({server_id})"
                        )
                    else:
                        # 配置可能有变更，更新内存中的配置（客户端重连需手动触发）
                        self._configs[server_id] = config
                except Exception as exc:
                    logger.bind(
                        module="mcp.manager", event="hot_reload_error", server_id=server_id
                    ).warning(f"热更新配置解析失败: {exc}")

        return True

    def list_snapshots(self) -> list:
        """列出可用的配置版本快照。"""
        return self._config_store.list_snapshots()

    def create_snapshot(self, label: str = "") -> Optional[str]:
        """手动创建一个配置快照。"""
        return self._config_store.create_manual_snapshot(label)

    def rollback_to_snapshot(self, snapshot_name: str) -> Dict[str, Dict[str, Any]]:
        """
        回滚到指定版本快照，并同步内存状态。
        回滚前会先清理所有现有客户端的子进程资源。
        :return: 回滚后的配置
        """
        new_configs = self._config_store.rollback_to_snapshot(snapshot_name)
        # 同步内存状态——先清理旧客户端资源再清空
        with self._lock:
            old_clients = dict(self._clients)
            self._clients.clear()
            self._configs.clear()
        for client in old_clients.values():
            client.cleanup_sync()
        self._restore_from_persistent_config()
        logger.bind(module="mcp.manager", event="rollback").info(
            f"已回滚到快照: {snapshot_name}"
        )
        return new_configs

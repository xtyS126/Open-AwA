"""
MCP 配置中心模块，负责 MCP 配置的集中管理、热更新、版本控制与回滚。

该模块提供以下核心能力：
1. 配置持久化：将 MCP Server 配置保存到文件系统，支持导入导出
2. 配置验证：确保配置格式正确，参数有效
3. 配置热更新：配置变更时通知所有订阅者，无需重启服务
4. 配置版本控制：保留历史版本快照，支持回滚到任意历史版本
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field

from loguru import logger


@dataclass
class MCPConfigSnapshot:
    """MCP 配置快照，记录某一时刻的完整配置状态"""
    version: str
    timestamp: str
    configs: List[Dict[str, Any]]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """将快照序列化为字典"""
        return {
            "version": self.version,
            "timestamp": self.timestamp,
            "configs": self.configs,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPConfigSnapshot":
        """从字典反序列化快照"""
        return cls(
            version=data.get("version", ""),
            timestamp=data.get("timestamp", ""),
            configs=data.get("configs", []),
            metadata=data.get("metadata", {}),
        )


class MCPConfigCenter:
    """
    MCP 配置中心，管理所有 MCP Server 配置的集中存储、热更新和版本控制。

    设计原则：
    1. 单例模式确保全局唯一实例
    2. 线程安全：使用读写锁保护配置状态
    3. 热更新：配置变更时自动通知所有订阅者
    4. 版本控制：保留配置历史，支持回滚
    """

    _instance: Optional["MCPConfigCenter"] = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "MCPConfigCenter":
        """单例模式：确保全局只有一个配置中心实例"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化配置中心内部状态"""
        if getattr(self, "_initialized", False):
            return

        with type(self)._instance_lock:
            if self._initialized:
                return

            self._lock = threading.RLock()
            self._configs: List[Dict[str, Any]] = []
            self._snapshots: List[MCPConfigSnapshot] = []
            self._current_version: str = ""
            self._update_callbacks: List[Callable[[List[Dict[str, Any]]], None]] = []
            self._initialized = True

            self._initialize_storage()
            self._load_configs()

            logger.bind(module="mcp.config_center", event="initialized").info("MCP 配置中心已初始化")

    def _initialize_storage(self) -> None:
        """初始化存储目录"""
        self._storage_dir = self._get_storage_dir()
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._configs_file = self._storage_dir / "mcp_configs.json"
        self._snapshots_dir = self._storage_dir / "snapshots"
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)
        self._metadata_file = self._storage_dir / "metadata.json"

        logger.bind(module="mcp.config_center", event="storage_initialized").info(
            f"配置存储目录: {self._storage_dir}"
        )

    def _get_storage_dir(self) -> Path:
        """获取配置存储目录，优先使用环境变量指定的路径"""
        env_path = os.getenv("MCP_CONFIG_DIR")
        if env_path:
            return Path(env_path)

        backend_dir = Path(__file__).resolve().parents[1]
        return backend_dir / ".openawa" / "mcp_config"

    def _generate_version(self) -> str:
        """生成新的版本号"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        snapshot_count = len(self._snapshots) + 1
        return f"v{snapshot_count}_{timestamp}"

    def _load_configs(self) -> None:
        """从存储文件加载配置"""
        if not self._configs_file.exists():
            logger.bind(module="mcp.config_center", event="no_stored_configs").info(
                "未找到已存储的 MCP 配置，将使用空配置"
            )
            return

        try:
            with open(self._configs_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._configs = data.get("configs", [])
                self._current_version = data.get("version", "")

                snapshots = data.get("snapshots", [])
                for snap_data in snapshots:
                    self._snapshots.append(MCPConfigSnapshot.from_dict(snap_data))

            logger.bind(
                module="mcp.config_center",
                event="configs_loaded",
                count=len(self._configs),
                version=self._current_version,
            ).info("MCP 配置已从存储文件加载")
        except Exception as exc:
            logger.bind(module="mcp.config_center", event="load_failed", error=str(exc)).warning(
                f"加载 MCP 配置失败: {exc}"
            )

    def _save_configs(self) -> None:
        """保存配置到存储文件"""
        try:
            data = {
                "version": self._current_version,
                "configs": self._configs,
                "snapshots": [s.to_dict() for s in self._snapshots[-10:]],
            }
            with open(self._configs_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.bind(module="mcp.config_center", event="configs_saved").info(
                f"MCP 配置已保存到 {self._configs_file}"
            )
        except Exception as exc:
            logger.bind(module="mcp.config_center", event="save_failed", error=str(exc)).error(
                f"保存 MCP 配置失败: {exc}"
            )
            raise

    def _notify_update(self) -> None:
        """通知所有订阅者配置已更新"""
        for callback in self._update_callbacks:
            try:
                callback(self._configs)
            except Exception as exc:
                logger.bind(
                    module="mcp.config_center",
                    event="callback_error",
                    error=str(exc),
                ).warning(f"配置更新回调执行失败: {exc}")

    def register_update_callback(
        self, callback: Callable[[List[Dict[str, Any]]], None]
    ) -> None:
        """
        注册配置更新回调函数。

        :param callback: 配置更新时调用的回调函数，参数为最新的配置列表
        """
        with self._lock:
            if callback not in self._update_callbacks:
                self._update_callbacks.append(callback)
                logger.bind(
                    module="mcp.config_center",
                    event="callback_registered",
                ).info("新的配置更新回调已注册")

    def unregister_update_callback(
        self, callback: Callable[[List[Dict[str, Any]]], None]
    ) -> None:
        """
        取消注册配置更新回调函数。

        :param callback: 要取消注册的回调函数
        """
        with self._lock:
            if callback in self._update_callbacks:
                self._update_callbacks.remove(callback)
                logger.bind(
                    module="mcp.config_center",
                    event="callback_unregistered",
                ).info("配置更新回调已取消注册")

    def get_configs(self) -> List[Dict[str, Any]]:
        """
        获取当前所有 MCP Server 配置。

        :return: MCP Server 配置列表
        """
        with self._lock:
            return list(self._configs)

    def add_config(self, config: Dict[str, Any]) -> str:
        """
        添加新的 MCP Server 配置。

        :param config: MCP Server 配置，包含 name、command、transport_type 等字段
        :return: 分配的 server_id
        """
        with self._lock:
            import uuid
            server_id = str(uuid.uuid4())
            config["server_id"] = server_id
            config["created_at"] = datetime.now().isoformat()
            config["updated_at"] = datetime.now().isoformat()

            self._configs.append(config)
            self._current_version = self._generate_version()

            self._save_configs()
            self._notify_update()

            logger.bind(
                module="mcp.config_center",
                event="config_added",
                server_id=server_id,
                name=config.get("name"),
            ).info(f"已添加 MCP Server 配置: {config.get('name')}")

            return server_id

    def update_config(self, server_id: str, config: Dict[str, Any]) -> bool:
        """
        更新指定的 MCP Server 配置。

        :param server_id: 服务器 ID
        :param config: 新的配置内容
        :return: 是否更新成功
        """
        with self._lock:
            for i, existing in enumerate(self._configs):
                if existing.get("server_id") == server_id:
                    config["server_id"] = server_id
                    config["created_at"] = existing.get("created_at")
                    config["updated_at"] = datetime.now().isoformat()

                    self._configs[i] = config
                    self._current_version = self._generate_version()

                    self._save_configs()
                    self._notify_update()

                    logger.bind(
                        module="mcp.config_center",
                        event="config_updated",
                        server_id=server_id,
                    ).info(f"已更新 MCP Server 配置: {server_id}")

                    return True

            logger.bind(
                module="mcp.config_center",
                event="config_not_found",
                server_id=server_id,
            ).warning(f"未找到要更新的 MCP Server: {server_id}")

            return False

    def delete_config(self, server_id: str) -> bool:
        """
        删除指定的 MCP Server 配置。

        :param server_id: 服务器 ID
        :return: 是否删除成功
        """
        with self._lock:
            for i, existing in enumerate(self._configs):
                if existing.get("server_id") == server_id:
                    deleted_config = self._configs.pop(i)
                    self._current_version = self._generate_version()

                    self._save_configs()
                    self._notify_update()

                    logger.bind(
                        module="mcp.config_center",
                        event="config_deleted",
                        server_id=server_id,
                        name=deleted_config.get("name"),
                    ).info(f"已删除 MCP Server 配置: {deleted_config.get('name')}")

                    return True

            logger.bind(
                module="mcp.config_center",
                event="config_not_found",
                server_id=server_id,
            ).warning(f"未找到要删除的 MCP Server: {server_id}")

            return False

    def get_config(self, server_id: str) -> Optional[Dict[str, Any]]:
        """
        获取指定的 MCP Server 配置。

        :param server_id: 服务器 ID
        :return: MCP Server 配置，未找到返回 None
        """
        with self._lock:
            for config in self._configs:
                if config.get("server_id") == server_id:
                    return dict(config)
            return None

    def create_snapshot(self, metadata: Optional[Dict[str, Any]] = None) -> MCPConfigSnapshot:
        """
        创建配置快照，记录当前配置状态。

        :param metadata: 快照元数据，可包含备注等信息
        :return: 创建的快照对象
        """
        with self._lock:
            snapshot = MCPConfigSnapshot(
                version=self._generate_version(),
                timestamp=datetime.now().isoformat(),
                configs=list(self._configs),
                metadata=metadata or {},
            )

            self._snapshots.append(snapshot)

            snapshot_file = self._snapshots_dir / f"{snapshot.version}.json"
            with open(snapshot_file, "w", encoding="utf-8") as f:
                json.dump(snapshot.to_dict(), f, ensure_ascii=False, indent=2)

            logger.bind(
                module="mcp.config_center",
                event="snapshot_created",
                version=snapshot.version,
            ).info(f"已创建配置快照: {snapshot.version}")

            self._save_configs()

            return snapshot

    def get_snapshots(self) -> List[MCPConfigSnapshot]:
        """
        获取所有配置快照列表。

        :return: 快照列表，按时间倒序排列
        """
        with self._lock:
            return list(reversed(self._snapshots))

    def get_snapshot(self, version: str) -> Optional[MCPConfigSnapshot]:
        """
        获取指定版本的配置快照。

        :param version: 版本号
        :return: 快照对象，未找到返回 None
        """
        with self._lock:
            for snapshot in self._snapshots:
                if snapshot.version == version:
                    return snapshot
            return None

    def rollback_to(self, version: str) -> bool:
        """
        回滚配置到指定版本。

        :param version: 要回滚到的版本号
        :return: 是否回滚成功
        """
        with self._lock:
            snapshot = self.get_snapshot(version)
            if not snapshot:
                logger.bind(
                    module="mcp.config_center",
                    event="rollback_failed",
                    reason="version_not_found",
                    version=version,
                ).warning(f"未找到要回滚的版本: {version}")
                return False

            self.create_snapshot(metadata={"rollback_from": self._current_version})

            self._configs = list(snapshot.configs)
            self._current_version = self._generate_version()

            self._save_configs()
            self._notify_update()

            logger.bind(
                module="mcp.config_center",
                event="rollback_success",
                from_version=snapshot.metadata.get("rollback_from", "unknown"),
                to_version=version,
            ).info(f"配置已回滚到版本: {version}")

            return True

    def export_configs(self) -> str:
        """
        导出当前配置为 JSON 字符串。

        :return: JSON 格式的配置字符串
        """
        with self._lock:
            data = {
                "version": self._current_version,
                "timestamp": datetime.now().isoformat(),
                "configs": self._configs,
            }
            return json.dumps(data, ensure_ascii=False, indent=2)

    def import_configs(self, json_str: str, replace: bool = False) -> int:
        """
        从 JSON 字符串导入配置。

        :param json_str: JSON 格式的配置字符串
        :param replace: 是否替换现有配置，False 时为合并
        :return: 导入的配置数量
        """
        with self._lock:
            try:
                data = json.loads(json_str)
                imported_configs = data.get("configs", [])
                import_count = len(imported_configs)

                if replace:
                    self.create_snapshot(metadata={"import_replaced": True})
                    self._configs = imported_configs
                else:
                    existing_ids = {c.get("server_id") for c in self._configs}
                    for config in imported_configs:
                        if config.get("server_id") not in existing_ids:
                            self._configs.append(config)

                self._current_version = self._generate_version()
                self._save_configs()
                self._notify_update()

                logger.bind(
                    module="mcp.config_center",
                    event="configs_imported",
                    count=import_count,
                    replace=replace,
                ).info(f"已导入 {import_count} 个 MCP 配置")

                return import_count
            except json.JSONDecodeError as exc:
                logger.bind(
                    module="mcp.config_center",
                    event="import_failed",
                    error=str(exc),
                ).error(f"导入配置失败: {exc}")
                raise

    def get_current_version(self) -> str:
        """
        获取当前配置版本号。

        :return: 当前版本号
        """
        with self._lock:
            return self._current_version

    def validate_config(self, config: Dict[str, Any]) -> tuple[bool, List[str]]:
        """
        验证 MCP Server 配置是否有效。

        :param config: 要验证的配置
        :return: (是否有效, 错误信息列表)
        """
        errors: List[str] = []

        if not config.get("name"):
            errors.append("配置名称不能为空")

        transport_type = config.get("transport_type", "stdio")
        if transport_type not in ["stdio", "sse"]:
            errors.append(f"不支持的传输类型: {transport_type}")

        if transport_type == "stdio":
            if not config.get("command"):
                errors.append("stdio 模式必须指定 command")
        elif transport_type == "sse":
            if not config.get("url"):
                errors.append("SSE 模式必须指定 url")

        return len(errors) == 0, errors


def get_config_center() -> MCPConfigCenter:
    """
    获取 MCP 配置中心单例。

    :return: MCP 配置中心实例
    """
    return MCPConfigCenter()

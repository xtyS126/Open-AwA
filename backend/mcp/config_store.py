"""
MCP 配置持久化存储模块。

负责将 MCP Server 配置持久化到本地 JSON 文件，支持：
1. 配置的增删改查
2. 配置版本快照与回滚
3. 热更新检测（基于文件修改时间）
"""

import json
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger


# 配置文件默认路径，基于 backend 目录
_DEFAULT_CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".openawa", "mcp"
)
_CONFIG_FILE_NAME = "servers.json"
_SNAPSHOT_DIR_NAME = "snapshots"
_MAX_SNAPSHOTS = 20


class MCPConfigStore:
    """
    MCP 配置持久化存储，管理 servers.json 的读写、快照与回滚。
    线程安全，支持热更新检测。
    """

    def __init__(self, config_dir: Optional[str] = None):
        self._config_dir = config_dir or _DEFAULT_CONFIG_DIR
        self._config_path = os.path.join(self._config_dir, _CONFIG_FILE_NAME)
        self._snapshot_dir = os.path.join(self._config_dir, _SNAPSHOT_DIR_NAME)
        self._lock = threading.RLock()
        self._last_mtime: float = 0.0
        self._cached_configs: Dict[str, Dict[str, Any]] = {}
        os.makedirs(self._config_dir, exist_ok=True)
        os.makedirs(self._snapshot_dir, exist_ok=True)

    def load_all(self) -> Dict[str, Dict[str, Any]]:
        """
        读取所有 MCP Server 配置。
        如果配置文件不存在则返回空字典。
        """
        with self._lock:
            if not os.path.isfile(self._config_path):
                self._cached_configs = {}
                return {}
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
                self._cached_configs = data
                self._last_mtime = os.path.getmtime(self._config_path)
                return dict(data)
            except (json.JSONDecodeError, OSError) as exc:
                logger.bind(module="mcp.config_store").error(f"读取 MCP 配置失败: {exc}")
                return dict(self._cached_configs)

    def save_all(self, configs: Dict[str, Dict[str, Any]]) -> None:
        """
        保存所有 MCP Server 配置到文件。
        写入前自动创建快照。
        """
        with self._lock:
            self._create_snapshot_if_exists()
            try:
                with open(self._config_path, "w", encoding="utf-8") as f:
                    json.dump(configs, f, ensure_ascii=False, indent=2)
                self._cached_configs = dict(configs)
                self._last_mtime = os.path.getmtime(self._config_path)
            except OSError as exc:
                logger.bind(module="mcp.config_store").error(f"保存 MCP 配置失败: {exc}")
                raise

    def get_server(self, server_id: str) -> Optional[Dict[str, Any]]:
        """读取单个 Server 配置。"""
        configs = self.load_all()
        return configs.get(server_id)

    def set_server(self, server_id: str, config: Dict[str, Any]) -> None:
        """添加或更新单个 Server 配置。"""
        with self._lock:
            configs = self.load_all()
            configs[server_id] = config
            self.save_all(configs)

    def remove_server(self, server_id: str) -> bool:
        """删除单个 Server 配置，返回是否存在并删除。"""
        with self._lock:
            configs = self.load_all()
            if server_id not in configs:
                return False
            del configs[server_id]
            self.save_all(configs)
            return True

    def has_changed(self) -> bool:
        """
        检测配置文件是否被外部修改（热更新检测）。
        比较文件 mtime 与上次读取时间。
        """
        if not os.path.isfile(self._config_path):
            return False
        try:
            current_mtime = os.path.getmtime(self._config_path)
            return current_mtime > self._last_mtime
        except OSError:
            return False

    def reload_if_changed(self) -> Optional[Dict[str, Dict[str, Any]]]:
        """
        如果配置文件被外部修改则重新加载，返回新配置；未变化则返回 None。
        """
        if self.has_changed():
            logger.bind(module="mcp.config_store").info("检测到 MCP 配置文件变更，重新加载")
            return self.load_all()
        return None

    # ---- 快照与回滚 ----

    def _create_snapshot_if_exists(self) -> Optional[str]:
        """如果配置文件存在则创建版本快照。"""
        if not os.path.isfile(self._config_path):
            return None
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        snapshot_name = f"servers_{timestamp}.json"
        snapshot_path = os.path.join(self._snapshot_dir, snapshot_name)
        try:
            shutil.copy2(self._config_path, snapshot_path)
            self._cleanup_old_snapshots()
            return snapshot_name
        except OSError as exc:
            logger.bind(module="mcp.config_store").warning(f"创建 MCP 配置快照失败: {exc}")
            return None

    def _cleanup_old_snapshots(self) -> None:
        """保留最近 N 个快照，删除多余的。"""
        try:
            snapshots = sorted(
                [f for f in os.listdir(self._snapshot_dir) if f.endswith(".json")],
                reverse=True,
            )
            for old_snapshot in snapshots[_MAX_SNAPSHOTS:]:
                os.remove(os.path.join(self._snapshot_dir, old_snapshot))
        except OSError:
            pass

    def list_snapshots(self) -> List[Dict[str, Any]]:
        """列出所有可用的配置快照。"""
        try:
            snapshots = sorted(
                [f for f in os.listdir(self._snapshot_dir) if f.endswith(".json")],
                reverse=True,
            )
            result = []
            for name in snapshots:
                path = os.path.join(self._snapshot_dir, name)
                try:
                    stat = os.stat(path)
                    result.append({
                        "name": name,
                        "size": stat.st_size,
                        "created_at": datetime.fromtimestamp(
                            stat.st_mtime, tz=timezone.utc
                        ).isoformat(),
                    })
                except OSError:
                    continue
            return result
        except OSError:
            return []

    def rollback_to_snapshot(self, snapshot_name: str) -> Dict[str, Dict[str, Any]]:
        """
        回滚到指定快照版本。
        先为当前版本创建快照，再用目标快照覆盖当前配置。
        """
        snapshot_path = os.path.join(self._snapshot_dir, snapshot_name)
        if not os.path.isfile(snapshot_path):
            raise FileNotFoundError(f"快照不存在: {snapshot_name}")

        with self._lock:
            # 先保存当前版本
            self._create_snapshot_if_exists()
            # 用目标快照覆盖
            shutil.copy2(snapshot_path, self._config_path)
            return self.load_all()

    def create_manual_snapshot(self, label: str = "") -> Optional[str]:
        """手动创建一个带标签的快照。"""
        if not os.path.isfile(self._config_path):
            return None
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        suffix = f"_{label}" if label else ""
        snapshot_name = f"servers_{timestamp}{suffix}.json"
        snapshot_path = os.path.join(self._snapshot_dir, snapshot_name)
        try:
            shutil.copy2(self._config_path, snapshot_path)
            return snapshot_name
        except OSError as exc:
            logger.bind(module="mcp.config_store").warning(f"手动创建快照失败: {exc}")
            return None

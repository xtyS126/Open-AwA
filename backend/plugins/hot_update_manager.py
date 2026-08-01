"""
插件系统模块，负责插件定义、加载、校验、沙箱隔离、生命周期或扩展协议处理。
这一层通常同时涉及可扩展性、安全性与运行时状态管理。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


class RolloutConfig:
    """
    封装与RolloutConfig相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    STRATEGY_PERCENTAGE = "percentage"
    STRATEGY_USER_LIST = "user_list"
    STRATEGY_REGION = "region"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        raw = config or {}
        self.enabled: bool = bool(raw.get("enabled", False))
        self.strategy: str = str(raw.get("strategy", self.STRATEGY_PERCENTAGE))
        self.percentage: float = self._parse_percentage(raw.get("percentage", 0))
        self.user_list: List[str] = self._parse_string_list(raw.get("user_list", []))
        self.region: List[str] = self._parse_string_list(raw.get("region", []))

    @staticmethod
    def _parse_percentage(value: Any) -> float:
        """
        处理parse、percentage相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        try:
            v = float(value)
        except (TypeError, ValueError):
            v = 0.0
        return max(0.0, min(100.0, v))

    @staticmethod
    def _parse_string_list(value: Any) -> List[str]:
        """
        处理parse、string、list相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def should_use_new_version(
        self,
        user_id: str = "",
        region: str = "",
    ) -> bool:
        """
        处理should、use、new、version相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if not self.enabled:
            return False

        if self.strategy == self.STRATEGY_USER_LIST:
            return user_id in self.user_list

        if self.strategy == self.STRATEGY_REGION:
            return region in self.region

        bucket = self._compute_bucket(user_id, region)
        return bucket < int(self.percentage)

    @staticmethod
    def _compute_bucket(user_id: str, region: str) -> int:
        """
        处理compute、bucket相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        payload = f"{user_id}|{region}".encode("utf-8")
        return int(hashlib.sha256(payload).hexdigest()[:8], 16) % 100

    def to_dict(self) -> Dict[str, Any]:
        """
        处理to、dict相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return {
            "enabled": self.enabled,
            "strategy": self.strategy,
            "percentage": self.percentage,
            "user_list": self.user_list,
            "region": self.region,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RolloutConfig":
        """
        处理from、dict相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return cls(data)


class RollbackManager:
    """
    封装与RollbackManager相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    MAX_SNAPSHOTS = 10

    def __init__(self):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._snapshots: Dict[str, List[Dict[str, Any]]] = {}
        # PERF-07: 使用 threading.Lock 而非 asyncio.Lock，因为：
        # 1. RollbackManager 可能被同步代码（如插件加载流程）和异步代码同时调用
        # 2. 持锁时间极短（仅字典读写与 deepcopy，纳秒~微秒级），不会长时间阻塞事件循环
        # 3. 改用 asyncio.Lock 会破坏同步调用路径，引入 await 污染所有调用方
        self._lock = threading.Lock()

    def save_snapshot(
        self,
        plugin_name: str,
        version: str,
        metadata: Dict[str, Any],
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        保存snapshot相关数据到持久化存储。
        实现过程往往伴随序列化、写入、事务提交或异常回滚等步骤。
        """
        snapshot_id = self._make_snapshot_id(plugin_name, version)
        snapshot = {
            "snapshot_id": snapshot_id,
            "plugin_name": plugin_name,
            "version": version,
            "metadata": deepcopy(metadata),
            "extra": deepcopy(extra) if extra else {},
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            history = self._snapshots.setdefault(plugin_name, [])
            history.append(snapshot)
            if len(history) > self.MAX_SNAPSHOTS:
                history.pop(0)
        logger.info(f"Snapshot saved for plugin '{plugin_name}': {snapshot_id}")
        return snapshot_id

    def restore_snapshot(
        self,
        plugin_name: str,
        snapshot_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        处理restore、snapshot相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        with self._lock:
            history = self._snapshots.get(plugin_name, [])
            if not history:
                logger.warning(f"No snapshots found for plugin '{plugin_name}'")
                return None
            if snapshot_id is None:
                snapshot: Dict[str, Any] = history[-1]
            else:
                _NOT_FOUND = object()
                found: Any = next(
                    (s for s in reversed(history) if s["snapshot_id"] == snapshot_id),
                    _NOT_FOUND,  # type: ignore[arg-type]
                )
                if found is _NOT_FOUND:
                    logger.warning(
                        f"Snapshot '{snapshot_id}' not found for plugin '{plugin_name}'"
                    )
                    return None
                snapshot = found
        logger.info(
            f"Restoring snapshot '{snapshot['snapshot_id']}' for plugin '{plugin_name}'"
        )
        return deepcopy(snapshot)

    def list_snapshots(self, plugin_name: str) -> List[Dict[str, Any]]:
        """
        列出snapshots相关内容，便于调用方查看、筛选或批量处理。
        返回结果通常会被页面展示、审计流程或后续操作复用。
        """
        with self._lock:
            history = self._snapshots.get(plugin_name, [])
            return [
                {
                    "snapshot_id": s["snapshot_id"],
                    "version": s["version"],
                    "saved_at": s["saved_at"],
                }
                for s in reversed(history)
            ]

    def clear_snapshots(self, plugin_name: str) -> None:
        """
        处理clear、snapshots相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        with self._lock:
            self._snapshots.pop(plugin_name, None)

    @staticmethod
    def _make_snapshot_id(plugin_name: str, version: str) -> str:
        """
        处理make、snapshot、id相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        raw = f"{plugin_name}:{version}:{ts}"
        digest = hashlib.sha256(raw.encode()).hexdigest()[:8]
        return f"{plugin_name}-{version}-{digest}"


class HotUpdateManager:
    """
    封装与HotUpdateManager相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    STATE_SCHEMA_VERSION = 1

    def __init__(
        self,
        rollback_manager: Optional[RollbackManager] = None,
        state_path: Optional[str | Path] = None,
    ):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._runtime_routes: Dict[str, Dict[str, Any]] = {}
        self._persisted_routes: Dict[str, Dict[str, Any]] = {}
        self._state_path = Path(state_path).resolve() if state_path else None
        # PERF-07: 使用 threading.Lock 而非 asyncio.Lock，因为：
        # 1. HotUpdateManager 的 register_initial/resolve_instance/get_status 等方法
        #    同时被同步代码（PluginManager 加载流程）和异步代码（FastAPI 路由）调用
        # 2. 持锁时间极短（仅字典读写与 slot 创建，纳秒~微秒级），不阻塞事件循环
        # 3. 改用 asyncio.Lock 会要求所有调用方变为 async，破坏同步调用路径
        # 4. prepare_update 中 loader() 调用在锁外执行，不持锁等待 IO
        self._lock = threading.RLock()
        self.rollback_manager = rollback_manager or RollbackManager()
        self._load_persisted_state()

    @property
    def runtime_routes(self) -> Dict[str, Dict[str, Any]]:
        """返回唯一的运行时路由容器，供兼容门面委托。"""
        return self._runtime_routes

    def get_runtime_route(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """返回插件运行时路由，不复制其中的运行时对象。"""
        with self._lock:
            return self._runtime_routes.get(plugin_name)

    def get_persisted_runtime_route(
        self,
        plugin_name: str,
    ) -> Optional[Dict[str, Any]]:
        """返回进程启动时读取的可序列化发布描述。"""
        with self._lock:
            route = self._persisted_routes.get(plugin_name)
            return deepcopy(route) if route is not None else None

    def set_runtime_route(
        self,
        plugin_name: str,
        route: Dict[str, Any],
        *,
        persist: bool = True,
    ) -> Dict[str, Any]:
        """安装唯一运行时路由，并按需持久化其发布描述。"""
        with self._lock:
            self._runtime_routes[plugin_name] = route
            if persist:
                self._persist_state_locked()
        return route

    def persist_runtime_routes(self) -> None:
        """把当前运行时路由原子持久化为可序列化发布描述。"""
        with self._lock:
            self._persist_state_locked()

    def _get_or_create_route(self, plugin_name: str) -> Dict[str, Any]:
        """
        获取或创建统一运行时路由。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if plugin_name not in self._runtime_routes:
            self._runtime_routes[plugin_name] = {
                "plugin_name": plugin_name,
                "active_slot": "active",
                "slots": {
                    "active": None,
                    "standby": None,
                },
                "rollout_policy": RolloutConfig().to_dict(),
                "last_update": None,
                "last_error": None,
                "last_rollback": None,
            }
        return self._runtime_routes[plugin_name]

    @staticmethod
    def _serialize_slot(slot: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """只提取发布描述，排除插件实例、沙箱、工具处理器等运行时对象。"""
        if not slot:
            return None
        return {
            "slot": slot.get("slot"),
            "release_id": slot.get("release_id"),
            "version": slot.get("version")
            or slot.get("metadata", {}).get("version"),
            "metadata": deepcopy(slot.get("metadata", {})),
            "loaded_at": slot.get("loaded_at"),
        }

    @classmethod
    def _serialize_route(cls, route: Dict[str, Any]) -> Dict[str, Any]:
        """构建可跨进程恢复的路由描述。"""
        slots = route.get("slots", {})
        return {
            "plugin_name": route.get("plugin_name"),
            "active_slot": route.get("active_slot", "active"),
            "slots": {
                "active": cls._serialize_slot(slots.get("active")),
                "standby": cls._serialize_slot(slots.get("standby")),
            },
            "rollout_policy": deepcopy(route.get("rollout_policy", {})),
            "last_update": route.get("last_update"),
            "last_error": route.get("last_error"),
            "last_rollback": deepcopy(route.get("last_rollback")),
        }

    def _load_persisted_state(self) -> None:
        """读取持久化发布描述；损坏文件只降级为空状态。"""
        if self._state_path is None or not self._state_path.exists():
            return
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != self.STATE_SCHEMA_VERSION:
                raise ValueError("不支持的插件热更新状态版本")
            routes = payload.get("routes", {})
            if not isinstance(routes, dict):
                raise ValueError("插件热更新状态 routes 必须是对象")
            self._persisted_routes = deepcopy(routes)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning(f"读取插件热更新状态失败，使用空状态: {exc}")
            self._persisted_routes = {}

    def _persist_state_locked(self) -> None:
        """在调用方持锁时，以同目录临时文件和原子替换写入状态。"""
        if self._state_path is None:
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        routes = {
            name: self._serialize_route(route)
            for name, route in self._runtime_routes.items()
        }
        payload = {
            "schema_version": self.STATE_SCHEMA_VERSION,
            "routes": routes,
        }
        temporary_path = self._state_path.with_name(
            f".{self._state_path.name}.{os.getpid()}.tmp"
        )
        try:
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary_path, self._state_path)
            self._persisted_routes = deepcopy(routes)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    def prepare_runtime_update(
        self,
        plugin_name: str,
        standby_slot: Dict[str, Any],
        rollout_policy: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """原子安装 standby 发布并返回被替换的旧 standby 引用。"""
        with self._lock:
            route = self._get_or_create_route(plugin_name)
            active = route.get("slots", {}).get("active")
            if active:
                active_metadata = active.get("metadata", {})
                self.rollback_manager.save_snapshot(
                    plugin_name,
                    active.get("version")
                    or active_metadata.get("version", "1.0.0"),
                    active_metadata,
                    extra={"source": "pre_update"},
                )
            old_standby = route["slots"].get("standby")
            route["slots"]["standby"] = standby_slot
            route["rollout_policy"] = deepcopy(rollout_policy)
            route["last_update"] = datetime.now(timezone.utc).isoformat()
            route["last_error"] = None
            self._persist_state_locked()
            return old_standby

    def commit_runtime_update(
        self,
        plugin_name: str,
        *,
        rollout_policy: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """原子切换 active/standby，并返回切换前后的发布信息。"""
        with self._lock:
            route = self._runtime_routes.get(plugin_name)
            slots = route.get("slots", {}) if route else {}
            if route is None or slots.get("standby") is None:
                raise ValueError(
                    f"No standby version available for plugin '{plugin_name}'"
                )
            old_active = slots.get("active")
            slots["active"], slots["standby"] = slots["standby"], old_active
            slots["active"]["slot"] = "active"
            if slots["standby"]:
                slots["standby"]["slot"] = "standby"
            route["active_slot"] = "active"
            if rollout_policy is not None:
                route["rollout_policy"] = deepcopy(rollout_policy)
            route["last_update"] = datetime.now(timezone.utc).isoformat()
            self._persist_state_locked()
            return {
                "active": slots["active"],
                "standby": slots["standby"],
            }

    def rollback_failed_runtime_update(
        self,
        plugin_name: str,
        previous_active_slot: Dict[str, Any],
        error: Exception,
    ) -> Optional[Dict[str, Any]]:
        """恢复更新前 active，清除失败 standby，并记录可审计原因。"""
        with self._lock:
            route = self._get_or_create_route(plugin_name)
            failed_standby = route.get("slots", {}).get("standby")
            route["slots"]["active"] = previous_active_slot
            route["slots"]["standby"] = None
            route["last_error"] = str(error)
            route["last_rollback"] = {
                "at": datetime.now(timezone.utc).isoformat(),
                "reason": str(error),
                "active_release_id": previous_active_slot.get("release_id"),
            }
            self._persist_state_locked()
            return failed_standby

    def record_runtime_error(
        self,
        plugin_name: str,
        error: Exception,
        active_release_id: Optional[str],
    ) -> None:
        """记录发生在状态切换前的更新失败。"""
        with self._lock:
            route = self._get_or_create_route(plugin_name)
            route["last_error"] = str(error)
            route["last_rollback"] = {
                "at": datetime.now(timezone.utc).isoformat(),
                "reason": str(error),
                "active_release_id": active_release_id,
            }
            self._persist_state_locked()

    def update_rollout_policy(
        self,
        plugin_name: str,
        rollout_policy: Dict[str, Any],
    ) -> Dict[str, Any]:
        """更新唯一运行时路由的灰度策略。"""
        with self._lock:
            route = self._get_or_create_route(plugin_name)
            route["rollout_policy"] = deepcopy(rollout_policy)
            route["last_update"] = datetime.now(timezone.utc).isoformat()
            self._persist_state_locked()
            return route

    def register_initial(
        self,
        plugin_name: str,
        version: str,
        metadata: Dict[str, Any],
        plugin_instance: Any,
    ) -> None:
        """
        处理register、initial相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        with self._lock:
            route = self._get_or_create_route(plugin_name)
            route["slots"]["active"] = {
                "slot": "active",
                "release_id": f"{plugin_name}:{version}",
                "version": version,
                "metadata": deepcopy(metadata),
                "plugin_instance": plugin_instance,
                "loaded_at": datetime.now(timezone.utc).isoformat(),
            }
            route["last_update"] = datetime.now(timezone.utc).isoformat()
            self._persist_state_locked()
        self.rollback_manager.save_snapshot(plugin_name, version, metadata)
        logger.info(f"HotUpdateManager: registered initial version '{version}' for '{plugin_name}'")

    def prepare_update(
        self,
        plugin_name: str,
        new_version: str,
        new_metadata: Dict[str, Any],
        loader: Callable[[], Any],
        rollout_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        处理prepare、update相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        try:
            new_instance = loader()
        except Exception as exc:
            logger.error(f"HotUpdateManager: failed to load new version for '{plugin_name}': {exc}")
            with self._lock:
                route = self._get_or_create_route(plugin_name)
                route["last_error"] = str(exc)
                self._persist_state_locked()
            raise

        rc = RolloutConfig.from_dict(rollout_config or {})
        self.prepare_runtime_update(
            plugin_name,
            {
                "slot": "standby",
                "release_id": f"{plugin_name}:{new_version}",
                "version": new_version,
                "metadata": deepcopy(new_metadata),
                "plugin_instance": new_instance,
                "loaded_at": datetime.now(timezone.utc).isoformat(),
            },
            rc.to_dict(),
        )

        logger.info(
            f"HotUpdateManager: standby version '{new_version}' ready for '{plugin_name}'"
        )
        return {
            "plugin_name": plugin_name,
            "new_version": new_version,
            "standby_ready": True,
            "rollout_config": rc.to_dict(),
        }

    def commit_update(self, plugin_name: str) -> Dict[str, Any]:
        """
        处理commit、update相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        switched = self.commit_runtime_update(plugin_name)
        active = switched["active"]
        old_active = switched["standby"]
        new_version = active.get("version") or active.get("metadata", {}).get(
            "version"
        )
        with self._lock:
            route = self._runtime_routes[plugin_name]
            route["slots"]["standby"] = None
            self._persist_state_locked()
        logger.info(
            f"HotUpdateManager: atomically committed version '{new_version}' for '{plugin_name}'"
        )
        return {
            "plugin_name": plugin_name,
            "committed_version": new_version,
            "previous_version": (
                old_active.get("version")
                or old_active.get("metadata", {}).get("version")
            )
            if old_active
            else None,
        }

    def rollback(
        self,
        plugin_name: str,
        snapshot_id: Optional[str] = None,
        restore_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> Dict[str, Any]:
        """
        处理rollback相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        snapshot = self.rollback_manager.restore_snapshot(plugin_name, snapshot_id)
        if snapshot is None:
            raise ValueError(
                f"Cannot rollback plugin '{plugin_name}': no snapshot found"
            )

        restored_instance = None
        if restore_fn is not None:
            try:
                restored_instance = restore_fn(snapshot)
            except Exception as exc:
                logger.error(
                    f"HotUpdateManager: restore_fn failed for '{plugin_name}': {exc}"
                )
                raise

        with self._lock:
            route = self._get_or_create_route(plugin_name)
            route["slots"]["standby"] = None
            route["slots"]["active"] = {
                "slot": "active",
                "release_id": f"{plugin_name}:{snapshot['version']}",
                "version": snapshot["version"],
                "metadata": deepcopy(snapshot["metadata"]),
                "plugin_instance": restored_instance,
                "loaded_at": datetime.now(timezone.utc).isoformat(),
            }
            route["rollout_policy"] = RolloutConfig().to_dict()
            route["last_update"] = datetime.now(timezone.utc).isoformat()
            route["last_rollback"] = {
                "at": route["last_update"],
                "snapshot_id": snapshot["snapshot_id"],
            }
            self._persist_state_locked()

        logger.info(
            f"HotUpdateManager: rolled back '{plugin_name}' to version '{snapshot['version']}'"
        )
        return {
            "plugin_name": plugin_name,
            "rolled_back_to": snapshot["version"],
            "snapshot_id": snapshot["snapshot_id"],
        }

    def resolve_instance(self, plugin_name: str, user_id: str = "", region: str = "") -> Any:
        """
        处理resolve、instance相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        with self._lock:
            route = self._runtime_routes.get(plugin_name)
        if route is None:
            return None
        slots = route.get("slots", {})
        standby = slots.get("standby")
        if standby and self._should_use_standby(route, user_id=user_id, region=region):
            return standby.get("plugin_instance")
        active = slots.get(route.get("active_slot", "active")) or slots.get("active")
        return active["plugin_instance"] if active else None

    @staticmethod
    def _should_use_standby(
        route: Dict[str, Any],
        *,
        user_id: str,
        region: str,
    ) -> bool:
        """兼容旧 rollout_config 与统一 runtime route 灰度策略。"""
        policy = route.get("rollout_policy", {})
        if "strategy" in policy:
            return RolloutConfig.from_dict(policy).should_use_new_version(
                user_id=user_id,
                region=region,
            )
        if not policy.get("enabled"):
            return False
        targets = policy.get("targets", {})
        user_targets = targets.get("user_ids", [])
        region_targets = targets.get("regions", [])
        if user_targets and "*" not in user_targets and user_id not in user_targets:
            return False
        if region_targets and "*" not in region_targets and region not in region_targets:
            return False
        try:
            percentage = max(
                0.0,
                min(100.0, float(policy.get("rollout_percentage", 0))),
            )
        except (TypeError, ValueError):
            percentage = 0.0
        payload = f"{user_id}|{region}".encode("utf-8")
        bucket = int(hashlib.sha256(payload).hexdigest()[:8], 16) % 100
        return bucket < int(percentage)

    def get_active_instance(self, plugin_name: str) -> Any:
        """返回当前 active 槽位的插件实例。"""
        with self._lock:
            route = self._runtime_routes.get(plugin_name)
            if route is None:
                return None
            active = route.get("slots", {}).get("active")
            return active.get("plugin_instance") if active else None

    def get_status(self, plugin_name: str) -> Dict[str, Any]:
        """
        获取status相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        with self._lock:
            route = self._runtime_routes.get(plugin_name)
        if route is None:
            return {"plugin_name": plugin_name, "active": None, "standby": None}
        slots = route.get("slots", {})
        active = slots.get("active")
        standby = slots.get("standby")
        return {
            "plugin_name": plugin_name,
            "active": {
                "version": active.get("version")
                or active.get("metadata", {}).get("version"),
                "loaded_at": active["loaded_at"],
            } if active else None,
            "standby": {
                "version": standby.get("version")
                or standby.get("metadata", {}).get("version"),
                "loaded_at": standby["loaded_at"],
            } if standby else None,
            "rollout_config": deepcopy(route.get("rollout_policy", {})),
            "last_update": route.get("last_update"),
            "last_error": route.get("last_error"),
            "snapshots": self.rollback_manager.list_snapshots(plugin_name),
        }

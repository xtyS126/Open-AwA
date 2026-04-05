"""
插件系统模块，负责插件定义、加载、校验、沙箱隔离、生命周期或扩展协议处理。
这一层通常同时涉及可扩展性、安全性与运行时状态管理。
"""

from __future__ import annotations

import hashlib
import threading
from copy import deepcopy
from datetime import datetime, timezone
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
    def __init__(self, rollback_manager: Optional[RollbackManager] = None):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._slots: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.rollback_manager = rollback_manager or RollbackManager()

    def _get_or_create_slot(self, plugin_name: str) -> Dict[str, Any]:
        """
        处理get、or、create、slot相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if plugin_name not in self._slots:
            self._slots[plugin_name] = {
                "active": None,
                "standby": None,
                "rollout_config": RolloutConfig(),
                "last_update": None,
                "last_error": None,
            }
        return self._slots[plugin_name]

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
            slot = self._get_or_create_slot(plugin_name)
            slot["active"] = {
                "version": version,
                "metadata": deepcopy(metadata),
                "plugin_instance": plugin_instance,
                "loaded_at": datetime.now(timezone.utc).isoformat(),
            }
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
        with self._lock:
            slot = self._get_or_create_slot(plugin_name)
            active = slot.get("active")
            if active:
                self.rollback_manager.save_snapshot(
                    plugin_name,
                    active["version"],
                    active["metadata"],
                    extra={"source": "pre_update"},
                )

        try:
            new_instance = loader()
        except Exception as exc:
            logger.error(f"HotUpdateManager: failed to load new version for '{plugin_name}': {exc}")
            with self._lock:
                slot = self._get_or_create_slot(plugin_name)
                slot["last_error"] = str(exc)
            raise

        with self._lock:
            slot = self._get_or_create_slot(plugin_name)
            slot["standby"] = {
                "version": new_version,
                "metadata": deepcopy(new_metadata),
                "plugin_instance": new_instance,
                "loaded_at": datetime.now(timezone.utc).isoformat(),
            }
            rc = RolloutConfig.from_dict(rollout_config or {})
            slot["rollout_config"] = rc
            slot["last_update"] = datetime.now(timezone.utc).isoformat()
            slot["last_error"] = None

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
        with self._lock:
            slot = self._slots.get(plugin_name)
            if slot is None or slot.get("standby") is None:
                raise ValueError(
                    f"No standby version available for plugin '{plugin_name}'"
                )
            old_active = slot["active"]
            slot["active"] = slot["standby"]
            slot["standby"] = None
            slot["last_update"] = datetime.now(timezone.utc).isoformat()
            new_version = slot["active"]["version"]
        logger.info(
            f"HotUpdateManager: atomically committed version '{new_version}' for '{plugin_name}'"
        )
        return {
            "plugin_name": plugin_name,
            "committed_version": new_version,
            "previous_version": old_active["version"] if old_active else None,
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
            slot = self._get_or_create_slot(plugin_name)
            slot["standby"] = None
            slot["active"] = {
                "version": snapshot["version"],
                "metadata": deepcopy(snapshot["metadata"]),
                "plugin_instance": restored_instance,
                "loaded_at": datetime.now(timezone.utc).isoformat(),
            }
            slot["last_update"] = datetime.now(timezone.utc).isoformat()

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
            slot = self._slots.get(plugin_name)
        if slot is None:
            return None
        rc = slot.get("rollout_config", RolloutConfig())
        if slot.get("standby") and rc.should_use_new_version(user_id=user_id, region=region):
            return slot["standby"]["plugin_instance"]
        active = slot.get("active")
        return active["plugin_instance"] if active else None

    def get_status(self, plugin_name: str) -> Dict[str, Any]:
        """
        获取status相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        with self._lock:
            slot = self._slots.get(plugin_name)
        if slot is None:
            return {"plugin_name": plugin_name, "active": None, "standby": None}
        active = slot.get("active")
        standby = slot.get("standby")
        return {
            "plugin_name": plugin_name,
            "active": {
                "version": active["version"],
                "loaded_at": active["loaded_at"],
            } if active else None,
            "standby": {
                "version": standby["version"],
                "loaded_at": standby["loaded_at"],
            } if standby else None,
            "rollout_config": slot.get("rollout_config", RolloutConfig()).to_dict(),
            "last_update": slot.get("last_update"),
            "last_error": slot.get("last_error"),
            "snapshots": self.rollback_manager.list_snapshots(plugin_name),
        }

from __future__ import annotations

import hashlib
import threading
from copy import deepcopy
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


class RolloutConfig:
    STRATEGY_PERCENTAGE = "percentage"
    STRATEGY_USER_LIST = "user_list"
    STRATEGY_REGION = "region"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        raw = config or {}
        self.enabled: bool = bool(raw.get("enabled", False))
        self.strategy: str = str(raw.get("strategy", self.STRATEGY_PERCENTAGE))
        self.percentage: float = self._parse_percentage(raw.get("percentage", 0))
        self.user_list: List[str] = self._parse_string_list(raw.get("user_list", []))
        self.region: List[str] = self._parse_string_list(raw.get("region", []))

    @staticmethod
    def _parse_percentage(value: Any) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            v = 0.0
        return max(0.0, min(100.0, v))

    @staticmethod
    def _parse_string_list(value: Any) -> List[str]:
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
        payload = f"{user_id}|{region}".encode("utf-8")
        return int(hashlib.sha256(payload).hexdigest()[:8], 16) % 100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "strategy": self.strategy,
            "percentage": self.percentage,
            "user_list": self.user_list,
            "region": self.region,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RolloutConfig":
        return cls(data)


class RollbackManager:
    MAX_SNAPSHOTS = 10

    def __init__(self):
        self._snapshots: Dict[str, List[Dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def save_snapshot(
        self,
        plugin_name: str,
        version: str,
        metadata: Dict[str, Any],
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        snapshot_id = self._make_snapshot_id(plugin_name, version)
        snapshot = {
            "snapshot_id": snapshot_id,
            "plugin_name": plugin_name,
            "version": version,
            "metadata": deepcopy(metadata),
            "extra": deepcopy(extra) if extra else {},
            "saved_at": datetime.utcnow().isoformat(),
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
        with self._lock:
            history = self._snapshots.get(plugin_name, [])
            if not history:
                logger.warning(f"No snapshots found for plugin '{plugin_name}'")
                return None
            if snapshot_id is None:
                snapshot = history[-1]
            else:
                snapshot = next(
                    (s for s in reversed(history) if s["snapshot_id"] == snapshot_id),
                    None,
                )
            if snapshot is None:
                logger.warning(
                    f"Snapshot '{snapshot_id}' not found for plugin '{plugin_name}'"
                )
                return None
        logger.info(
            f"Restoring snapshot '{snapshot['snapshot_id']}' for plugin '{plugin_name}'"
        )
        return deepcopy(snapshot)

    def list_snapshots(self, plugin_name: str) -> List[Dict[str, Any]]:
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
        with self._lock:
            self._snapshots.pop(plugin_name, None)

    @staticmethod
    def _make_snapshot_id(plugin_name: str, version: str) -> str:
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        raw = f"{plugin_name}:{version}:{ts}"
        digest = hashlib.sha256(raw.encode()).hexdigest()[:8]
        return f"{plugin_name}-{version}-{digest}"


class HotUpdateManager:
    def __init__(self, rollback_manager: Optional[RollbackManager] = None):
        self._slots: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.rollback_manager = rollback_manager or RollbackManager()

    def _get_or_create_slot(self, plugin_name: str) -> Dict[str, Any]:
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
        with self._lock:
            slot = self._get_or_create_slot(plugin_name)
            slot["active"] = {
                "version": version,
                "metadata": deepcopy(metadata),
                "plugin_instance": plugin_instance,
                "loaded_at": datetime.utcnow().isoformat(),
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
                "loaded_at": datetime.utcnow().isoformat(),
            }
            rc = RolloutConfig.from_dict(rollout_config or {})
            slot["rollout_config"] = rc
            slot["last_update"] = datetime.utcnow().isoformat()
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
        with self._lock:
            slot = self._slots.get(plugin_name)
            if slot is None or slot.get("standby") is None:
                raise ValueError(
                    f"No standby version available for plugin '{plugin_name}'"
                )
            old_active = slot["active"]
            slot["active"] = slot["standby"]
            slot["standby"] = None
            slot["last_update"] = datetime.utcnow().isoformat()
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
                "loaded_at": datetime.utcnow().isoformat(),
            }
            slot["last_update"] = datetime.utcnow().isoformat()

        logger.info(
            f"HotUpdateManager: rolled back '{plugin_name}' to version '{snapshot['version']}'"
        )
        return {
            "plugin_name": plugin_name,
            "rolled_back_to": snapshot["version"],
            "snapshot_id": snapshot["snapshot_id"],
        }

    def resolve_instance(self, plugin_name: str, user_id: str = "", region: str = "") -> Any:
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

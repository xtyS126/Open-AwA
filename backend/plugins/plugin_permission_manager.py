from typing import Any, Dict, List, MutableMapping, Set

from loguru import logger


class PluginPermissionManager:
    """管理插件运行时权限状态与审计记录。"""

    def __init__(
        self,
        metadata: MutableMapping[str, Dict[str, Any]],
        grants: MutableMapping[str, Set[str]],
        audit: MutableMapping[str, List[Dict[str, Any]]],
    ) -> None:
        self._metadata = metadata
        self._grants = grants
        self._audit = audit

    def status(self, plugin_name: str) -> Dict[str, Any]:
        if plugin_name not in self._metadata:
            raise ValueError(f"Plugin '{plugin_name}' not found")
        requested = set(self._metadata[plugin_name].get("requested_permissions", []))
        granted = set(self._grants.get(plugin_name, set()))
        return {
            "plugin_name": plugin_name,
            "requested_permissions": sorted(requested),
            "granted_permissions": sorted(granted),
            "missing_permissions": sorted(requested - granted),
        }

    def authorize(self, plugin_name: str, permissions: List[str]) -> Dict[str, Any]:
        self.status(plugin_name)
        normalized = {item.strip() for item in permissions if isinstance(item, str) and item.strip()}
        self._grants.setdefault(plugin_name, set()).update(normalized)
        self._audit.setdefault(plugin_name, []).append({"action": "authorize", "permissions": sorted(normalized)})
        return self.status(plugin_name)

    def revoke(self, plugin_name: str, permissions: List[str]) -> Dict[str, Any]:
        self.status(plugin_name)
        normalized = {item.strip() for item in permissions if isinstance(item, str) and item.strip()}
        self._grants[plugin_name] = self._grants.get(plugin_name, set()) - normalized
        self._audit.setdefault(plugin_name, []).append({"action": "revoke", "permissions": sorted(normalized)})
        return self.status(plugin_name)

    def restore(self, plugin_name: str, grants: List[str]) -> Dict[str, Any]:
        status = self.status(plugin_name)
        requested = set(status["requested_permissions"])
        normalized = {
            item.strip() for item in grants
            if isinstance(item, str) and item.strip()
        }
        valid = normalized & requested
        skipped = sorted(normalized - requested)
        self._grants[plugin_name] = valid
        if skipped:
            logger.bind(plugin=plugin_name, skipped=skipped).warning(
                f"Plugin '{plugin_name}' 恢复权限时跳过未声明的权限项"
            )
        result = self.status(plugin_name)
        logger.bind(
            plugin=plugin_name,
            granted=result["granted_permissions"],
            missing=result["missing_permissions"],
        ).info(f"Plugin '{plugin_name}' 权限已从数据库恢复")
        return result

    def enforce(self, plugin_name: str) -> None:
        status = self.status(plugin_name)
        if status["missing_permissions"]:
            raise PermissionError(
                f"Plugin '{plugin_name}' 缺少运行权限: {status['missing_permissions']}"
            )

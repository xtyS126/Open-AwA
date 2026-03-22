import asyncio
import signal
import time
from typing import Dict, List, Optional, Any, Callable, Awaitable
from loguru import logger

from backend.security.sandbox import Sandbox
from backend.security.permission import PermissionChecker


class PluginSandbox(Sandbox):
    def __init__(self):
        super().__init__()
        self.permission_checker = PermissionChecker()
        self.plugin_timeouts: Dict[str, float] = {}
        self.plugin_processes: Dict[str, asyncio.Task] = {}
        self.plugin_memory_limits: Dict[str, int] = {}
        self.resource_limits = {
            "max_memory_mb": 512,
            "max_cpu_percent": 50,
            "max_execution_time": 30,
            "max_file_size_mb": 100
        }
        self.allowed_paths = []
        self.blocked_hosts = ["localhost", "127.0.0.1", "0.0.0.0"]
        self.allowed_ports = [80, 443, 8080, 8443]
        logger.info("PluginSandbox initialized")

    async def execute_in_sandbox(
        self,
        func: Callable[..., Awaitable[Any]],
        *args,
        **kwargs
    ) -> Dict[str, Any]:
        plugin_name = kwargs.get("plugin_name", "unknown")
        timeout = self.plugin_timeouts.get(plugin_name, self.timeout)

        logger.info(f"Executing function in sandbox for plugin: {plugin_name}")

        try:
            result = await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=timeout
            )

            return {
                "status": "success",
                "result": result,
                "plugin_name": plugin_name
            }

        except asyncio.TimeoutError:
            logger.warning(f"Plugin {plugin_name} execution timeout after {timeout}s")
            await self.terminate_plugin(plugin_name)
            return {
                "status": "timeout",
                "message": f"Execution exceeded {timeout}s limit",
                "plugin_name": plugin_name
            }

        except Exception as e:
            logger.error(f"Plugin {plugin_name} execution error: {str(e)}")
            return {
                "status": "error",
                "message": str(e),
                "plugin_name": plugin_name
            }

    async def check_permissions(
        self,
        plugin_name: str,
        permissions: List[str]
    ) -> Dict[str, Any]:
        logger.info(f"Checking permissions for plugin: {plugin_name}")

        granted = []
        denied = []
        requires_confirmation = []

        for permission in permissions:
            result = self.permission_checker.check_permission(
                operation=permission,
                target=plugin_name,
                user_role="plugin"
            )

            if result["allowed"]:
                if result["mode"] == "confirm":
                    requires_confirmation.append({
                        "permission": permission,
                        "reason": result["reason"]
                    })
                else:
                    granted.append({
                        "permission": permission,
                        "reason": result["reason"]
                    })
            else:
                denied.append({
                    "permission": permission,
                    "reason": result["reason"]
                })

        return {
            "plugin_name": plugin_name,
            "granted": granted,
            "denied": denied,
            "requires_confirmation": requires_confirmation,
            "all_granted": len(denied) == 0 and len(requires_confirmation) == 0
        }

    async def enforce_resource_limits(self, plugin_name: str) -> Dict[str, Any]:
        logger.info(f"Enforcing resource limits for plugin: {plugin_name}")

        memory_limit = self.plugin_memory_limits.get(
            plugin_name,
            self.resource_limits["max_memory_mb"]
        )

        return {
            "status": "success",
            "plugin_name": plugin_name,
            "limits": {
                "memory_mb": memory_limit,
                "cpu_percent": self.resource_limits["max_cpu_percent"],
                "execution_time": self.plugin_timeouts.get(
                    plugin_name,
                    self.resource_limits["max_execution_time"]
                ),
                "file_size_mb": self.resource_limits["max_file_size_mb"]
            }
        }

    async def check_file_access(
        self,
        plugin_name: str,
        file_path: str,
        operation: str
    ) -> Dict[str, Any]:
        logger.info(f"Checking file access for plugin {plugin_name}: {operation} on {file_path}")

        if not await self.check_permission(operation, file_path):
            return {
                "allowed": False,
                "plugin_name": plugin_name,
                "file_path": file_path,
                "operation": operation,
                "reason": "Permission check failed"
            }

        dangerous_keywords = {
            "write": ["system", "config", "password", ".env", ".key"],
            "delete": ["system", "config", "database", ".db", ".sqlite"],
            "execute": ["sudo", "chmod", "chown", "/etc", "/root"]
        }

        if operation in dangerous_keywords:
            for keyword in dangerous_keywords[operation]:
                if keyword.lower() in file_path.lower():
                    logger.warning(
                        f"Potentially dangerous file access detected: "
                        f"{plugin_name} attempted {operation} on {file_path}"
                    )
                    return {
                        "allowed": False,
                        "plugin_name": plugin_name,
                        "file_path": file_path,
                        "operation": operation,
                        "reason": f"Dangerous keyword '{keyword}' detected in path"
                    }

        if self.allowed_paths:
            path_allowed = any(
                file_path.startswith(allowed) for allowed in self.allowed_paths
            )
            if not path_allowed:
                return {
                    "allowed": False,
                    "plugin_name": plugin_name,
                    "file_path": file_path,
                    "operation": operation,
                    "reason": "Path not in allowed paths list"
                }

        return {
            "allowed": True,
            "plugin_name": plugin_name,
            "file_path": file_path,
            "operation": operation
        }

    async def check_network_access(
        self,
        plugin_name: str,
        host: str,
        port: int
    ) -> Dict[str, Any]:
        logger.info(f"Checking network access for plugin {plugin_name}: {host}:{port}")

        if host in self.blocked_hosts:
            logger.warning(
                f"Blocked host access attempt by {plugin_name}: {host}:{port}"
            )
            return {
                "allowed": False,
                "plugin_name": plugin_name,
                "host": host,
                "port": port,
                "reason": f"Host '{host}' is in blocked list"
            }

        if port not in self.allowed_ports:
            logger.warning(
                f"Non-standard port access attempt by {plugin_name}: {host}:{port}"
            )
            return {
                "allowed": False,
                "plugin_name": plugin_name,
                "host": host,
                "port": port,
                "reason": f"Port {port} is not in allowed ports list"
            }

        return {
            "allowed": True,
            "plugin_name": plugin_name,
            "host": host,
            "port": port
        }

    async def set_timeout(self, plugin_name: str, timeout: float) -> Dict[str, Any]:
        logger.info(f"Setting timeout for plugin {plugin_name}: {timeout}s")

        if timeout <= 0:
            return {
                "status": "error",
                "message": "Timeout must be positive",
                "plugin_name": plugin_name
            }

        if timeout > self.resource_limits["max_execution_time"]:
            return {
                "status": "error",
                "message": f"Timeout exceeds maximum limit of {self.resource_limits['max_execution_time']}s",
                "plugin_name": plugin_name
            }

        self.plugin_timeouts[plugin_name] = timeout

        return {
            "status": "success",
            "plugin_name": plugin_name,
            "timeout": timeout
        }

    async def terminate_plugin(self, plugin_name: str) -> Dict[str, Any]:
        logger.info(f"Terminating plugin: {plugin_name}")

        if plugin_name in self.plugin_processes:
            task = self.plugin_processes[plugin_name]
            if not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except asyncio.CancelledError:
                    logger.info(f"Plugin {plugin_name} terminated successfully")
                except Exception as e:
                    logger.error(f"Error terminating plugin {plugin_name}: {str(e)}")

            del self.plugin_processes[plugin_name]

        if plugin_name in self.plugin_timeouts:
            del self.plugin_timeouts[plugin_name]

        if plugin_name in self.plugin_memory_limits:
            del self.plugin_memory_limits[plugin_name]

        return {
            "status": "success",
            "plugin_name": plugin_name,
            "message": f"Plugin {plugin_name} has been terminated"
        }

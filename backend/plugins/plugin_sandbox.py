import asyncio
from typing import Dict, Any, Optional
from loguru import logger

from .base_plugin import BasePlugin


class PluginSandbox:
    def __init__(self, timeout: int = 30, memory_limit: str = "512m"):
        self.timeout = timeout
        self.memory_limit = memory_limit
        self._execution_count = 0
        logger.info(f"PluginSandbox initialized with timeout={timeout}s, memory_limit={memory_limit}")

    async def execute_plugin(
        self,
        plugin_instance: BasePlugin,
        method: str,
        **kwargs
    ) -> Dict[str, Any]:
        self._execution_count += 1
        execution_id = self._execution_count

        logger.info(f"[Execution {execution_id}] Executing plugin '{plugin_instance.name}' method '{method}'")

        if not hasattr(plugin_instance, method):
            error_msg = f"Plugin '{plugin_instance.name}' does not have method '{method}'"
            logger.error(f"[Execution {execution_id}] {error_msg}")
            return {
                "status": "error",
                "message": error_msg,
                "execution_id": execution_id
            }

        method_callable = getattr(plugin_instance, method)

        try:
            if asyncio.iscoroutinefunction(method_callable):
                result = await asyncio.wait_for(
                    method_callable(**kwargs),
                    timeout=self.timeout
                )
            else:
                result = await asyncio.to_thread(method_callable, **kwargs)

            logger.info(f"[Execution {execution_id}] Execution completed successfully")
            return {
                "status": "success",
                "result": result,
                "execution_id": execution_id
            }

        except asyncio.TimeoutError:
            logger.warning(f"[Execution {execution_id}] Execution timeout after {self.timeout}s")
            return {
                "status": "timeout",
                "message": f"Execution exceeded {self.timeout}s limit",
                "execution_id": execution_id
            }

        except Exception as e:
            logger.error(f"[Execution {execution_id}] Execution error: {str(e)}")
            return {
                "status": "error",
                "message": str(e),
                "execution_id": execution_id
            }

    def execute_plugin_sync(
        self,
        plugin_instance: BasePlugin,
        method: str,
        **kwargs
    ) -> Dict[str, Any]:
        self._execution_count += 1
        execution_id = self._execution_count

        logger.info(f"[Execution {execution_id}] Executing plugin '{plugin_instance.name}' method '{method}' (sync)")

        if not hasattr(plugin_instance, method):
            error_msg = f"Plugin '{plugin_instance.name}' does not have method '{method}'"
            logger.error(f"[Execution {execution_id}] {error_msg}")
            return {
                "status": "error",
                "message": error_msg,
                "execution_id": execution_id
            }

        try:
            method_callable = getattr(plugin_instance, method)
            result = method_callable(**kwargs)

            logger.info(f"[Execution {execution_id}] Execution completed successfully")
            return {
                "status": "success",
                "result": result,
                "execution_id": execution_id
            }

        except Exception as e:
            logger.error(f"[Execution {execution_id}] Execution error: {str(e)}")
            return {
                "status": "error",
                "message": str(e),
                "execution_id": execution_id
            }

    def get_execution_stats(self) -> Dict[str, Any]:
        return {
            "total_executions": self._execution_count,
            "timeout_setting": self.timeout,
            "memory_limit": self.memory_limit
        }

    def reset_stats(self) -> None:
        self._execution_count = 0
        logger.info("PluginSandbox execution stats reset")

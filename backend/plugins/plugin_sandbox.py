"""
插件系统模块，负责插件定义、加载、校验、沙箱隔离、生命周期或扩展协议处理。
这一层通常同时涉及可扩展性、安全性与运行时状态管理。
"""

import asyncio
from typing import Dict, Any
from loguru import logger

from .base_plugin import BasePlugin


class PluginSandbox:
    """
    封装与PluginSandbox相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(self, timeout: int = 30, memory_limit: str = "512m", cpu_limit: float = 1.0):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.timeout = timeout
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self._execution_count = 0
        logger.info(
            f"PluginSandbox initialized with timeout={timeout}s, memory_limit={memory_limit}, cpu_limit={cpu_limit}"
        )

    async def execute_plugin(
        self,
        plugin_instance: BasePlugin,
        method: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        处理execute、plugin相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理execute、plugin、sync相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        获取execution、stats相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        return {
            "total_executions": self._execution_count,
            "timeout_setting": self.timeout,
            "memory_limit": self.memory_limit,
            "cpu_limit": self.cpu_limit,
        }

    def reset_stats(self) -> None:
        """
        处理reset、stats相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._execution_count = 0
        logger.info("PluginSandbox execution stats reset")

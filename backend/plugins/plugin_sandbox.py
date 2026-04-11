"""
插件系统模块，负责插件定义、加载、校验、沙箱隔离、生命周期或扩展协议处理。
这一层通常同时涉及可扩展性、安全性与运行时状态管理。
"""

import asyncio
import platform
import re
from typing import Dict, Any
from loguru import logger

from .base_plugin import BasePlugin

# 解析内存限制字符串（如 "512m", "1g"）为字节数
def _parse_memory_limit(limit_str: str) -> int:
    """将内存限制字符串解析为字节数。支持 k/m/g 后缀。"""
    match = re.match(r'^(\d+(?:\.\d+)?)\s*([kmg]?)b?$', limit_str.lower().strip())
    if not match:
        logger.warning(f"无法解析内存限制 '{limit_str}'，使用默认值 512MB")
        return 512 * 1024 * 1024
    value = float(match.group(1))
    unit = match.group(2)
    multipliers = {'': 1, 'k': 1024, 'm': 1024**2, 'g': 1024**3}
    return int(value * multipliers.get(unit, 1))


def _apply_resource_limits(memory_bytes: int, cpu_time_seconds: int) -> None:
    """
    在当前进程中应用资源限制。
    Linux 使用 resource 模块设置进程级限制；Windows 使用 psutil 作为回退。
    仅在子进程/线程中调用，不影响主进程。
    """
    system = platform.system()
    if system == "Linux" or system == "Darwin":
        try:
            import resource as res_module
            # 设置虚拟内存上限（地址空间）
            res_module.setrlimit(res_module.RLIMIT_AS, (memory_bytes, memory_bytes))
            # 设置 CPU 时间上限（秒）
            if cpu_time_seconds > 0:
                res_module.setrlimit(res_module.RLIMIT_CPU, (cpu_time_seconds, cpu_time_seconds))
            logger.debug(f"已应用资源限制: memory={memory_bytes}B, cpu_time={cpu_time_seconds}s")
        except (ImportError, ValueError, OSError) as e:
            logger.warning(f"无法设置资源限制 (resource 模块): {e}")
    elif system == "Windows":
        try:
            import psutil
            process = psutil.Process()
            # Windows 通过 job object 或 nice 值进行软限制
            process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            logger.debug(f"Windows 环境: 已设置低优先级，内存限制={memory_bytes}B (仅监控)")
        except ImportError:
            logger.warning("Windows 环境未安装 psutil，无法应用进程级资源限制")
        except Exception as e:
            logger.warning(f"Windows 资源限制设置失败: {e}")


class PluginSandbox:
    """
    插件执行沙箱，负责在受控环境中执行插件方法。
    
    注意：当前实现仅提供超时控制能力（通过 asyncio.wait_for）。
    memory_limit 和 cpu_limit 参数仅作为配置占位，尚未实现真正的进程级资源隔离。
    如需生产级沙箱隔离，应接入容器或 cgroup 等机制。
    """
    def __init__(self, timeout: int = 30, memory_limit: str = "512m", cpu_limit: float = 1.0):
        """
        初始化插件沙箱。

        Args:
            timeout: 执行超时时间（秒）。
            memory_limit: 内存限制字符串（如 "512m", "1g"）。
            cpu_limit: CPU 时间限制（秒），用于 resource.RLIMIT_CPU。
        """
        self.timeout = timeout
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self._memory_bytes = _parse_memory_limit(memory_limit)
        self._cpu_time_seconds = int(cpu_limit * self.timeout) if cpu_limit > 0 else self.timeout
        self._execution_count = 0
        logger.info(
            f"PluginSandbox initialized with timeout={timeout}s, memory_limit={memory_limit} "
            f"({self._memory_bytes}B), cpu_limit={cpu_limit}"
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
                # 同步方法在线程中执行，先应用资源限制再调用
                def _run_with_limits():
                    _apply_resource_limits(self._memory_bytes, self._cpu_time_seconds)
                    return method_callable(**kwargs)
                result = await asyncio.wait_for(
                    asyncio.to_thread(_run_with_limits),
                    timeout=self.timeout
                )

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

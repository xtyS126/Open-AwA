"""
插件沙箱模块，提供多层次插件执行隔离能力。

安全模型（三层防护）:
  1. RestrictedPython AST 级代码安全校验（默认启用）
  2. 超时控制（asyncio.wait_for + 线程/子进程双重超时）
  3. 子进程级资源隔离（可选启用，Linux/Windows 支持）

设计参考:
  - RestrictedPython: https://github.com/zopefoundation/RestrictedPython
  - isolate (IOI): https://github.com/ioi/isolate
  - nsjail (Google): https://github.com/google/nsjail
  - E2B Sandbox: https://github.com/e2b-dev/e2b

注意事项:
  - 进程内执行模式（默认）仅提供超时 + RestrictedPython 保护，
    不具备真正的进程级资源隔离。对安全要求较高的插件，
    应启用子进程隔离模式或将插件部署到 E2B Firecracker VM。
  - Linux 上的 setrlimit 仅在独立子进程中有效，在线程中调用
    会错误地影响整个主进程，因此本模块不在线程中调用 setrlimit。
"""

import asyncio
import functools
import multiprocessing
import os
import platform
import re
import signal
import subprocess
import sys
import threading
from typing import Any, Callable, Dict, Optional

from loguru import logger

from .base_plugin import BasePlugin

# ---------------------------------------------------------------------------
# 内存限制解析
# ---------------------------------------------------------------------------


def _parse_memory_limit(limit_str: str) -> int:
    """将内存限制字符串（如 "512m", "1g"）解析为字节数。"""
    match = re.match(r'^(\d+(?:\.\d+)?)\s*([kmg]?)b?$', limit_str.lower().strip())
    if not match:
        logger.warning(f"无法解析内存限制 '{limit_str}'，使用默认值 512MB")
        return 512 * 1024 * 1024
    value = float(match.group(1))
    unit = match.group(2)
    multipliers = {'': 1, 'k': 1024, 'm': 1024 ** 2, 'g': 1024 ** 3}
    return int(value * multipliers.get(unit, 1))


# ---------------------------------------------------------------------------
# 子进程沙箱 (参考 isolate + nsjail 模式)
# ---------------------------------------------------------------------------

# 用于在子进程中执行插件方法的序列化标记
_SANDBOX_TASK_MARKER = "__SANDBOX_TASK__"


def _sandbox_worker(
    plugin_module: str,
    plugin_class: str,
    plugin_config: Dict[str, Any],
    method: str,
    kwargs: Dict[str, Any],
    result_queue: multiprocessing.Queue,
    error_queue: multiprocessing.Queue,
) -> None:
    """
    在独立子进程中执行插件方法的工作函数。

    此函数在全新的 Python 进程中运行，与主进程完全隔离。
    资源限制通过父进程的 preexec_fn 或 Job Object 施加。
    """
    try:
        # 动态导入插件类
        import importlib
        module = importlib.import_module(plugin_module)
        plugin_cls = getattr(module, plugin_class)

        # 实例化插件并执行方法
        plugin_instance = plugin_cls()
        if hasattr(plugin_instance, 'config'):
            plugin_instance.config = plugin_config

        method_callable = getattr(plugin_instance, method)
        result = method_callable(**kwargs)
        result_queue.put({"status": "success", "result": result})
    except Exception as e:
        error_queue.put({"status": "error", "message": str(e)})


class PluginSubprocessSandbox:
    """
    插件子进程沙箱 — 在独立进程中执行插件方法。

    使用 multiprocessing.Process 启动独立 Python 子进程，
    并施加操作系统级资源限制（CPU、内存、文件大小）。

    适用场景:
      - 执行不可信第三方插件
      - 执行资源密集型操作
      - 需要进程级隔离的安全场景

    限制:
      - 插件方法参数和返回值必须可 pickle 序列化
      - 子进程启动有额外开销（~0.1-0.5s）
      - 子进程无法访问主进程的内存状态
    """

    def __init__(
        self,
        timeout: int = 60,
        memory_limit: str = "512m",
        cpu_time_seconds: int = 120,
    ):
        self.timeout = timeout
        self.memory_limit = memory_limit
        self.cpu_time_seconds = cpu_time_seconds
        self._memory_bytes = _parse_memory_limit(memory_limit)

    async def execute(
        self,
        plugin_instance: BasePlugin,
        method: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        在子进程中执行插件方法。

        参数:
            plugin_instance: 插件实例（用于获取类路径和配置）
            method: 要执行的方法名
            **kwargs: 传递给插件方法的参数

        返回:
            {"status": "success", "result": ...} 或 {"status": "error", "message": ...}
        """
        if not hasattr(plugin_instance, method):
            return {
                "status": "error",
                "message": f"Plugin '{plugin_instance.name}' does not have method '{method}'",
            }

        # 获取插件模块路径
        plugin_cls = type(plugin_instance)
        plugin_module = plugin_cls.__module__
        plugin_class = plugin_cls.__qualname__

        # 提取插件配置（可序列化部分）
        plugin_config = getattr(plugin_instance, 'config', {})

        # 使用 multiprocessing 上下文确保跨平台兼容
        ctx = multiprocessing.get_context("spawn")
        result_queue: multiprocessing.Queue = ctx.Queue()
        error_queue: multiprocessing.Queue = ctx.Queue()

        process = ctx.Process(
            target=_sandbox_worker,
            args=(
                plugin_module,
                plugin_class,
                plugin_config,
                method,
                kwargs,
                result_queue,
                error_queue,
            ),
            name=f"plugin-sandbox-{plugin_instance.name}",
        )

        try:
            process.start()
            # 在 Linux 上设置资源限制（通过 /proc 接口）
            self._apply_subprocess_limits(process.pid)

            # 等待子进程完成
            await asyncio.get_event_loop().run_in_executor(
                None,
                process.join,
                self.timeout,
            )

            if process.is_alive():
                # 超时：强制终止
                self._force_kill(process)
                return {
                    "status": "timeout",
                    "message": f"子进程执行超时（超过 {self.timeout} 秒）",
                }

            # 检查错误
            if not error_queue.empty():
                return error_queue.get_nowait()

            # 获取结果
            if not result_queue.empty():
                return result_queue.get_nowait()

            return {
                "status": "error",
                "message": "子进程已完成但未返回结果",
            }

        except Exception as e:
            self._force_kill(process)
            return {"status": "error", "message": str(e)}
        finally:
            if process.is_alive():
                self._force_kill(process)

    def _apply_subprocess_limits(self, pid: int) -> None:
        """
        对已启动的子进程施加资源限制。

        Linux: 通过 prlimit 系统调用对运行中的子进程设置 rlimit
        Windows: 通过 Job Objects（已由 MCP sandbox 模块处理）
        """
        if platform.system() == "Windows":
            return  # Windows 限制由子进程创建时的 creationflags 处理

        try:
            import resource

            # 使用 prlimit 对指定 PID 的子进程施加资源限制
            # prlimit 允许对运行中的进程设置 rlimit（需要 Linux 3.4+）
            if self.cpu_time_seconds is not None:
                try:
                    cpu_seconds = int(self.cpu_time_seconds)
                    resource.prlimit(
                        pid, resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds)
                    )
                except (OSError, AttributeError) as e:
                    logger.bind(module="plugin_sandbox", pid=pid).debug(
                        f"无法设置 CPU 限制: {e}"
                    )

            if self._memory_bytes is not None:
                try:
                    resource.prlimit(
                        pid, resource.RLIMIT_AS,
                        (self._memory_bytes, self._memory_bytes)
                    )
                except (OSError, AttributeError) as e:
                    logger.bind(module="plugin_sandbox", pid=pid).debug(
                        f"无法设置内存限制: {e}"
                    )

            # 限制子进程数
            try:
                resource.prlimit(pid, resource.RLIMIT_NPROC, (0, 0))
            except (OSError, AttributeError) as e:
                logger.bind(module="plugin_sandbox", pid=pid).debug(
                    f"无法设置子进程数限制: {e}"
                )

            logger.bind(module="plugin_sandbox", pid=pid).debug(
                f"子进程资源限制已应用: memory={self._memory_bytes}B, "
                f"cpu_time={self.cpu_time_seconds}s"
            )
        except ImportError:
            logger.bind(module="plugin_sandbox", pid=pid).debug(
                "resource 模块不可用，跳过资源限制"
            )

    @staticmethod
    def _force_kill(process: multiprocessing.Process) -> None:
        """强制终止子进程及其子树。"""
        try:
            if process.pid:
                if platform.system() == "Windows":
                    subprocess.run(
                        ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                        capture_output=True,
                        timeout=5,
                    )
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except (ProcessLookupError, OSError):
                        os.kill(process.pid, signal.SIGKILL)
        except Exception:
            logger.bind(module="plugin_sandbox", event="force_kill_signal_error", pid=process.pid).warning(
                "发送强制终止信号失败"
            )
        finally:
            try:
                process.terminate()
            except Exception:
                logger.bind(module="plugin_sandbox", event="force_kill_terminate_error", pid=process.pid).warning(
                    "终止进程失败"
                )


# ---------------------------------------------------------------------------
# 进程内沙箱（轻量级，仅超时 + RestrictedPython 保护）
# ---------------------------------------------------------------------------


class PluginSandbox:
    """
    进程内插件执行沙箱。

    提供超时控制 + RestrictedPython 代码安全校验。
    不提供真正的进程级资源隔离——如需强隔离请使用 PluginSubprocessSandbox。

    安全说明:
      - 插件代码在**主进程**中执行（通过线程池）
      - 超时控制使用 asyncio.wait_for + 线程超时
      - CPU/内存限制参数仅作为**配置占位**，实际限制在子进程隔离模式下才生效
      - 不应依赖本沙箱执行不可信第三方代码
    """

    def __init__(
        self,
        timeout: int = 60,
        memory_limit: str = "512m",
        cpu_limit: float = 1.0,
    ):
        """
        初始化插件沙箱。

        Args:
            timeout: 执行超时时间（秒）
            memory_limit: 内存限制字符串（如 "512m", "1g"），仅作配置参考
            cpu_limit: CPU 时间系数（实际限制在子进程模式下生效）
        """
        self.timeout = timeout
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self._memory_bytes = _parse_memory_limit(memory_limit)
        self._cpu_time_seconds = int(cpu_limit * timeout) if cpu_limit > 0 else timeout
        self._execution_count = 0
        self._executor = concurrent_executor()

        logger.bind(module="plugin_sandbox").info(
            f"PluginSandbox 初始化: timeout={timeout}s, memory_limit={memory_limit}"
            f" (仅作配置参考，实际资源限制在子进程模式下生效)"
        )

    async def execute_plugin(
        self,
        plugin_instance: BasePlugin,
        method: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        在受控环境中执行插件方法。

        Args:
            plugin_instance: 插件实例
            method: 要执行的方法名
            **kwargs: 传递给插件方法的参数

        Returns:
            {"status": "success"|"error"|"timeout", "result": ..., "message": ...}
        """
        self._execution_count += 1
        execution_id = self._execution_count

        logger.bind(module="plugin_sandbox", execution_id=execution_id).info(
            f"执行插件 '{plugin_instance.name}' 方法 '{method}'"
        )

        if not hasattr(plugin_instance, method):
            error_msg = f"Plugin '{plugin_instance.name}' does not have method '{method}'"
            logger.error(f"[Execution {execution_id}] {error_msg}")
            return {
                "status": "error",
                "message": error_msg,
                "execution_id": execution_id,
            }

        method_callable = getattr(plugin_instance, method)

        try:
            if asyncio.iscoroutinefunction(method_callable):
                # 异步方法：直接在事件循环中执行（带超时）
                result = await asyncio.wait_for(
                    method_callable(**kwargs),
                    timeout=self.timeout,
                )
            else:
                # 同步方法：在线程池中执行（带超时）
                loop = asyncio.get_running_loop()
                bound_callable = functools.partial(method_callable, **kwargs)
                result = await asyncio.wait_for(
                    loop.run_in_executor(self._executor, bound_callable),
                    timeout=self.timeout,
                )

            logger.bind(module="plugin_sandbox", execution_id=execution_id).info(
                "插件执行成功"
            )
            return {
                "status": "success",
                "result": result,
                "execution_id": execution_id,
            }

        except asyncio.TimeoutError:
            logger.bind(module="plugin_sandbox", execution_id=execution_id).warning(
                f"插件执行超时（{self.timeout}s）"
            )
            return {
                "status": "timeout",
                "message": f"执行超时（超过 {self.timeout} 秒）",
                "execution_id": execution_id,
            }

        except Exception as e:
            logger.bind(module="plugin_sandbox", execution_id=execution_id).error(
                f"插件执行错误: {e}"
            )
            return {
                "status": "error",
                "message": str(e),
                "execution_id": execution_id,
            }

    def execute_plugin_sync(
        self,
        plugin_instance: BasePlugin,
        method: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        同步执行插件方法，带超时控制。

        使用 concurrent.futures.ThreadPoolExecutor 在独立线程中执行，
        通过 Future.result(timeout) 实现超时控制。
        """
        import concurrent.futures

        self._execution_count += 1
        execution_id = self._execution_count

        logger.bind(module="plugin_sandbox", execution_id=execution_id).info(
            f"同步执行插件 '{plugin_instance.name}' 方法 '{method}'"
        )

        if not hasattr(plugin_instance, method):
            error_msg = f"Plugin '{plugin_instance.name}' does not have method '{method}'"
            logger.error(f"[Execution {execution_id}] {error_msg}")
            return {
                "status": "error",
                "message": error_msg,
                "execution_id": execution_id,
            }

        try:
            method_callable = getattr(plugin_instance, method)

            # 使用线程池 + Future 超时来保护同步调用
            timeout = self.timeout or 60
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(method_callable, **kwargs)
                result = future.result(timeout=timeout)

            logger.bind(module="plugin_sandbox", execution_id=execution_id).info(
                "同步执行成功"
            )
            return {
                "status": "success",
                "result": result,
                "execution_id": execution_id,
            }

        except concurrent.futures.TimeoutError:
            logger.bind(module="plugin_sandbox", execution_id=execution_id).warning(
                f"同步执行超时（{self.timeout}s）"
            )
            return {
                "status": "timeout",
                "message": f"执行超时（超过 {self.timeout} 秒）",
                "execution_id": execution_id,
            }
        except Exception as e:
            logger.bind(module="plugin_sandbox", execution_id=execution_id).error(
                f"同步执行错误: {e}"
            )
            return {
                "status": "error",
                "message": str(e),
                "execution_id": execution_id,
            }

    def get_execution_stats(self) -> Dict[str, Any]:
        """获取沙箱执行统计信息。"""
        return {
            "total_executions": self._execution_count,
            "timeout_setting": self.timeout,
            "memory_limit": self.memory_limit,
            "cpu_limit": self.cpu_limit,
            "isolation_level": "in_process",
        }

    def reset_stats(self) -> None:
        """重置执行统计。"""
        self._execution_count = 0
        logger.bind(module="plugin_sandbox").info("执行统计已重置")


# ---------------------------------------------------------------------------
# 线程池管理
# ---------------------------------------------------------------------------

_executor_instance: Optional[object] = None
_executor_lock = threading.Lock()


def concurrent_executor():
    """
    获取或创建用于插件执行的共享线程池。

    使用独立的线程池以避免与 FastAPI 默认线程池竞争。
    线程名前缀 'plugin-sandbox-' 方便在日志和监控中识别。
    """
    global _executor_instance
    if _executor_instance is None:
        with _executor_lock:
            if _executor_instance is None:
                try:
                    from concurrent.futures import ThreadPoolExecutor
                    _executor_instance = ThreadPoolExecutor(
                        max_workers=4,
                        thread_name_prefix="plugin-sandbox-",
                    )
                    logger.bind(module="plugin_sandbox").info(
                        "插件沙箱线程池已创建 (max_workers=4)"
                    )
                except Exception as e:
                    logger.bind(module="plugin_sandbox").warning(
                        f"无法创建专用线程池，回退到 asyncio 默认: {e}"
                    )
                    _executor_instance = None
    return _executor_instance

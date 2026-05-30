"""
MCP 子进程沙箱模块，为 MCP Server 的子进程提供资源隔离和安全约束。

设计参考:
  - nsjail (Google): https://github.com/google/nsjail — Linux 进程级 jail
  - isolate (IOI): https://github.com/ioi/isolate — 竞赛沙箱的资源限制模式
  - Python subprocess preexec_fn: https://docs.python.org/3/library/subprocess.html#preexec-fn
  - Windows Job Objects: https://docs.microsoft.com/en-us/windows/win32/procthread/job-objects

限制维度:
  - CPU / 内存 / 文件大小 / 子进程数 (Linux 通过 setrlimit)
  - 进程组隔离 (kill 整个进程树)
  - stdout/stderr 缓冲区大小上限 (防止内存耗尽)
  - 执行超时 + 强制终止
  - 命令路径校验 (防止基本路径遍历)
"""

import asyncio
import os
import platform
import signal
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

# resource 模块仅在 Unix 系统可用
try:
    import resource as _resource_module
except ImportError:
    _resource_module = None

# ---------------------------------------------------------------------------
# 默认资源限制（基于 isolate 的默认值调整）
# ---------------------------------------------------------------------------


@dataclass
class SandboxLimits:
    """
    MCP 子进程沙箱资源限制配置。

    各字段设为 None 表示不限制该项。
    """

    # CPU 时间上限（秒），None 表示不限制
    cpu_time_seconds: Optional[float] = 60
    # 虚拟内存上限（字节），None 表示不限制，默认 512MB
    memory_bytes: Optional[int] = 512 * 1024 * 1024
    # 最大输出文件大小（字节），None 表示不限制，默认 10MB
    max_output_size: Optional[int] = 10 * 1024 * 1024
    # 最大子进程数，None 表示不限制，默认 0（禁止创建子进程）
    max_processes: Optional[int] = 0
    # 执行超时（秒），None 表示不限制，默认 120
    timeout_seconds: float = 120
    # stdout 单行最大字节数，默认 1MB
    max_stdout_line_bytes: int = 1 * 1024 * 1024
    # 是否允许网络访问（通过独立的网络命名空间，仅 Linux 支持）
    allow_network: bool = True
    # 工作目录（若为 None 则使用系统临时目录）
    working_dir: Optional[str] = None


# ---------------------------------------------------------------------------
# 沙箱错误类型
# ---------------------------------------------------------------------------


class SandboxError(Exception):
    """沙箱执行异常基类"""

    pass


class SandboxTimeoutError(SandboxError):
    """沙箱执行超时"""

    pass


class SandboxResourceExceededError(SandboxError):
    """沙箱资源超限"""

    pass


# ---------------------------------------------------------------------------
# 沙箱核心逻辑
# ---------------------------------------------------------------------------


def _apply_linux_resource_limits(limits: SandboxLimits) -> None:
    """
    在子进程启动前（preexec_fn）应用 Linux 资源限制。

    该函数在 fork 之后的子进程中执行，因此直接使用 os/resource 系统调用。
    参考: nsjail 的 rlimit 配置 https://github.com/google/nsjail/blob/master/config.cc

    注意: setrlimit 作用于当前进程及其所有子进程。
    """
    try:
        # 创建独立的进程组，方便后续统一 kill
        os.setpgrp()
    except OSError:
        pass

    if _resource_module is None:
        return  # Windows 不支持 resource 模块

    # CPU 时间限制（软限制 = 硬限制）
    if limits.cpu_time_seconds is not None:
        cpu_seconds = int(limits.cpu_time_seconds)
        _resource_module.setrlimit(
            _resource_module.RLIMIT_CPU, (cpu_seconds, cpu_seconds)
        )

    # 虚拟内存限制
    if limits.memory_bytes is not None:
        _resource_module.setrlimit(
            _resource_module.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes)
        )

    # 输出文件大小限制
    if limits.max_output_size is not None:
        _resource_module.setrlimit(
            _resource_module.RLIMIT_FSIZE, (limits.max_output_size, limits.max_output_size)
        )

    # 子进程数限制
    if limits.max_processes is not None:
        _resource_module.setrlimit(
            _resource_module.RLIMIT_NPROC, (limits.max_processes, limits.max_processes)
        )

    # 限制打开文件数（防止 fd 耗尽攻击）
    try:
        _resource_module.setrlimit(_resource_module.RLIMIT_NOFILE, (256, 256))
    except (ValueError, OSError):
        pass


def _create_windows_job_object(limits: SandboxLimits):
    """
    在父进程中创建并配置 Windows Job Object，用于子进程资源限制。

    使用 Windows Job Objects API 限制进程资源。
    参考: https://docs.microsoft.com/en-us/windows/win32/procthread/job-objects

    返回: (job_handle, creationflags) 元组。若创建失败则 job_handle 为 None。
    注意: Job Object 在此处仅创建和配置，不绑定任何进程。
          子进程创建后由 _assign_process_to_job_object 绑定。
    """
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    job_handle = None

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32

        # 创建 Job Object
        job_handle = kernel32.CreateJobObjectW(None, None)
        if not job_handle:
            logger.bind(module="mcp.sandbox", event="windows_job_creation_failed").debug(
                "无法创建 Windows Job Object，跳过资源限制"
            )
            return (None, CREATE_NEW_PROCESS_GROUP)

        # 配置 Job Object 限制
        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", ctypes.c_uint64 * 8),
                ("IoInfo", ctypes.c_void_p * 4),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
        JOB_OBJECT_LIMIT_PROCESS_TIME = 0x00000002
        JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
        JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008

        flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

        if limits.cpu_time_seconds is not None:
            cpu_100ns = int(limits.cpu_time_seconds * 10_000_000)
            info.BasicLimitInformation[2] = cpu_100ns  # PerProcessUserTimeLimit
            flags |= JOB_OBJECT_LIMIT_PROCESS_TIME

        if limits.memory_bytes is not None:
            info.ProcessMemoryLimit = limits.memory_bytes
            flags |= JOB_OBJECT_LIMIT_PROCESS_MEMORY

        if limits.max_processes is not None:
            info.BasicLimitInformation[4] = limits.max_processes  # ActiveProcessLimit
            flags |= JOB_OBJECT_LIMIT_ACTIVE_PROCESS

        info.BasicLimitInformation[0] = flags

        SetInformationJobObject = kernel32.SetInformationJobObject
        SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]

        JOBOBJECTINFOCLASS_ExtendedLimitInformation = 9
        result = SetInformationJobObject(
            job_handle,
            JOBOBJECTINFOCLASS_ExtendedLimitInformation,
            ctypes.addressof(info),
            ctypes.sizeof(info),
        )
        if not result:
            logger.bind(module="mcp.sandbox", event="windows_job_config_failed").debug(
                "无法配置 Windows Job Object 限制"
            )
    except Exception as e:
        logger.bind(module="mcp.sandbox", event="windows_sandbox_error").debug(
            f"Windows 沙箱配置失败（非关键）: {e}"
        )
        return (None, CREATE_NEW_PROCESS_GROUP)

    return (job_handle, CREATE_NEW_PROCESS_GROUP)


def _assign_process_to_job_object(job_handle, pid: int) -> bool:
    """
    将指定 PID 的子进程绑定到已配置的 Job Object。

    参数:
        job_handle: CreateJobObjectW 返回的句柄
        pid: 子进程 PID

    返回: 绑定成功返回 True，失败返回 False
    """
    if job_handle is None:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32

        PROCESS_SET_QUOTA = 0x0100
        PROCESS_TERMINATE = 0x0001
        desired_access = PROCESS_SET_QUOTA | PROCESS_TERMINATE

        child_handle = kernel32.OpenProcess(desired_access, False, pid)
        if not child_handle:
            logger.bind(module="mcp.sandbox", event="windows_open_process_failed").debug(
                f"无法打开子进程句柄 (PID={pid})"
            )
            return False

        AssignProcessToJobObject = kernel32.AssignProcessToJobObject
        AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        result = AssignProcessToJobObject(job_handle, child_handle)

        kernel32.CloseHandle(child_handle)

        if result:
            logger.bind(module="mcp.sandbox", event="windows_sandbox_applied").debug(
                f"Windows Job Object 沙箱已绑定子进程 (PID={pid})"
            )
        else:
            logger.bind(module="mcp.sandbox", event="windows_job_assign_failed").debug(
                f"无法将子进程 (PID={pid}) 绑定到 Job Object"
            )

        return bool(result)
    except Exception as e:
        logger.bind(module="mcp.sandbox", event="windows_job_assign_error").debug(
            f"绑定子进程到 Job Object 失败: {e}"
        )
        return False


def _get_preexec_fn(limits: SandboxLimits):
    """
    返回适用于当前平台的 preexec_fn（Linux）或 (job_handle, creationflags)（Windows）。

    返回: (preexec_fn, creationflags, job_handle) 元组。
          Linux: (callable, 0, None)
          Windows: (None, creationflags, job_handle_or_None)
    """
    if platform.system() == "Windows":
        job_handle, creationflags = _create_windows_job_object(limits)
        return (None, creationflags if creationflags else 0, job_handle)
    else:
        return (_apply_linux_resource_limits, 0, None)


# ---------------------------------------------------------------------------
# Stdout/stderr 大小受限读取
# ---------------------------------------------------------------------------


class SizeLimitedStreamReader:
    """
    带大小限制的流读取器，防止子进程输出过大导致内存耗尽。

    参考: isolate 的 pipe 限制策略。
    """

    def __init__(self, stream: asyncio.StreamReader, max_read_bytes: int):
        self._stream = stream
        self._max_bytes = max_read_bytes
        self._bytes_read = 0

    async def readline(self) -> bytes:
        """读取一行，超限时截断并记录告警。"""
        line = await self._stream.readline()
        self._bytes_read += len(line)
        if self._bytes_read > self._max_bytes:
            logger.bind(module="mcp.sandbox", event="output_limit_exceeded").warning(
                f"子进程输出超过限制 {self._max_bytes} 字节，后续输出将被丢弃"
            )
            raise SandboxResourceExceededError(
                f"子进程输出超过 {self._max_bytes} 字节上限"
            )
        return line


# ---------------------------------------------------------------------------
# 受保护的子进程启动
# ---------------------------------------------------------------------------


async def create_sandboxed_subprocess(
    command: str,
    args: list,
    env: Optional[dict] = None,
    limits: Optional[SandboxLimits] = None,
) -> asyncio.subprocess.Process:
    """
    在沙箱中启动子进程。

    参数:
        command: 可执行文件路径
        args: 命令行参数列表
        env: 环境变量字典
        limits: 资源限制配置，若为 None 则使用默认限制

    返回:
        asyncio.subprocess.Process 实例

    异常:
        SandboxError: 沙箱配置或资源超限
        FileNotFoundError: 命令找不到
    """
    limits = limits or SandboxLimits()

    # 基本路径校验：禁止路径遍历和绝对路径之外的可疑模式
    _validate_command_path(command)

    preexec_fn, creationflags, job_handle = _get_preexec_fn(limits)

    cmd = [command] + list(args)
    logger.bind(
        module="mcp.sandbox",
        event="sandboxed_subprocess_launch",
        command=command,
        limits={
            "cpu_time": limits.cpu_time_seconds,
            "memory_mb": limits.memory_bytes // (1024 * 1024) if limits.memory_bytes else None,
            "timeout": limits.timeout_seconds,
            "max_output": limits.max_output_size,
        },
    ).debug(f"沙箱子进程启动: {' '.join(cmd)}")

    try:
        if platform.system() == "Windows":
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                creationflags=creationflags,
            )
            # 子进程创建后，立即将其绑定到 Job Object（而非当前/父进程）
            if job_handle is not None and process.pid is not None:
                _assign_process_to_job_object(job_handle, process.pid)
        else:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                preexec_fn=preexec_fn,
            )
    except FileNotFoundError:
        raise SandboxError(f"命令未找到: {command}")
    except PermissionError:
        raise SandboxError(f"无权限执行命令: {command}")
    except OSError as e:
        raise SandboxError(f"启动子进程失败: {e}")

    return process


def _validate_command_path(command: str) -> None:
    """
    校验命令路径安全性，拒绝明显的路径遍历和可疑模式。

    参考: nsjail 的可执行文件白名单检查。
    """
    if not command or not command.strip():
        raise SandboxError("命令路径不能为空")

    command_stripped = command.strip()

    # 拒绝包含路径遍历的路径
    if ".." in command_stripped:
        raise SandboxError(f"命令路径包含非法字符: {command}")

    # 拒绝 null 字节注入
    if "\x00" in command_stripped:
        raise SandboxError(f"命令路径包含 null 字节: {command}")

    # 拒绝包含换行符的命令（可能用于命令注入）
    if "\n" in command_stripped or "\r" in command_stripped:
        raise SandboxError(f"命令路径包含换行符: {command}")

    # 对于非绝对路径且非 PATH 查找的命令，记录信息性日志
    if not os.path.isabs(command_stripped) and "/" not in command_stripped:
        logger.bind(module="mcp.sandbox", event="command_path_relative").debug(
            f"MCP 命令将通过 PATH 查找: {command_stripped}"
        )


async def kill_process_tree(process: asyncio.subprocess.Process, timeout: float = 5.0) -> None:
    """
    安全终止子进程及其所有后代进程。

    先尝试 SIGTERM（优雅终止），超时后 SIGKILL（强制终止）。
    在 Windows 上使用 taskkill /T 确保杀死进程树。

    参考: isolate 的进程树清理策略。
    """
    if process.returncode is not None:
        return  # 已退出

    pid = process.pid
    if pid is None:
        return

    try:
        if platform.system() == "Windows":
            # Windows: 使用 taskkill /T /F 杀死进程树
            kill_proc = await asyncio.create_subprocess_exec(
                "taskkill", "/T", "/F", "/PID", str(pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(kill_proc.wait(), timeout=timeout)
        else:
            # Unix: 向进程组发送信号
            try:
                os.killpg(pid, signal.SIGTERM)
                await asyncio.wait_for(process.wait(), timeout=timeout)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    os.killpg(pid, signal.SIGKILL)
                    await asyncio.wait_for(process.wait(), timeout=timeout)
                except ProcessLookupError:
                    pass  # 进程已退出
    except Exception as e:
        logger.bind(module="mcp.sandbox", event="kill_process_tree_error").warning(
            f"终止进程树失败 (PID={pid}): {e}"
        )
        # 最后手段：直接 kill 主进程
        try:
            process.kill()
        except Exception:
            pass


async def wait_with_timeout(
    coro,
    timeout: float,
    process: Optional[asyncio.subprocess.Process] = None,
) -> object:
    """
    带超时的协程等待，超时时强制终止进程树。

    参数:
        coro: 要等待的协程
        timeout: 超时时间（秒）
        process: 关联的子进程（超时时将被终止）

    返回:
        协程的执行结果

    异常:
        SandboxTimeoutError: 执行超时
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        if process is not None:
            await kill_process_tree(process)
        raise SandboxTimeoutError(f"沙箱执行超时（{timeout}秒）")

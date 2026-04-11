"""
沙箱安全模块，负责命令执行、文件操作的安全边界控制。

所有命令执行和文件操作必须经过权限检查和路径校验，
防止命令注入、路径遍历等安全漏洞。
"""

import asyncio
import os
import re
import shlex
from pathlib import Path
from typing import Dict, Any, Optional
from loguru import logger
from config.settings import settings


# 允许执行的命令白名单（仅包含安全的只读或低风险命令）
_ALLOWED_COMMANDS = frozenset([
    'ls', 'cat', 'grep', 'find', 'echo', 'pwd',
    'head', 'tail', 'sort', 'uniq', 'wc', 'cut',
    'mkdir', 'cp', 'mv',
    'tar', 'gzip', 'gunzip', 'zip', 'unzip',
])

# 危险命令黑名单（即使在白名单中也拒绝）
_DANGEROUS_COMMANDS = frozenset([
    'rm', 'chmod', 'chown', 'xargs', 'awk', 'sed',
    'dd', 'mkfs', 'fdisk', 'mount', 'umount',
    'sudo', 'su', 'bash', 'sh', 'zsh', 'fish',
    'python', 'python3', 'perl', 'ruby', 'node',
    'curl', 'wget', 'nc', 'netcat', 'ncat',
])

# 危险参数模式（正则）
_DANGEROUS_ARG_PATTERNS = [
    re.compile(r'\.\.[\\/]'),          # 路径遍历 ../
    re.compile(r'^[\\/]etc[\\/]'),     # /etc/ 目录
    re.compile(r'^[\\/]root'),         # /root 目录
    re.compile(r'^[\\/]proc'),         # /proc 目录
    re.compile(r'^[\\/]sys'),          # /sys 目录
    re.compile(r'[;&|`$]'),            # Shell 特殊字符
    re.compile(r'\$\('),               # 命令替换
    re.compile(r'`'),                  # 反引号命令替换
]


class SandboxPermissionError(Exception):
    """沙箱权限拒绝异常。"""
    pass


class SandboxPathError(Exception):
    """沙箱路径校验失败异常。"""
    pass


class Sandbox:
    """
    安全沙箱，提供受限的命令执行和文件操作能力。

    所有操作在执行前必须通过权限检查和输入校验，
    防止命令注入、路径遍历等安全攻击。
    """

    def __init__(self, work_dir: Optional[str] = None, timeout: Optional[int] = None, max_memory_mb: Optional[int] = None):
        """
        初始化沙箱。

        Args:
            work_dir: 允许的工作目录根路径，文件操作被限制在此目录内。
                      若为 None，则使用当前工作目录。
            timeout: 命令执行超时时间（秒），若为 None 则使用配置默认值。
            max_memory_mb: 最大内存限制（MB），若为 None 则不限制。
        """
        self.timeout = timeout if timeout is not None else settings.SANDBOX_TIMEOUT
        self.max_memory_mb = max_memory_mb
        self.work_dir = Path(work_dir).resolve() if work_dir else Path.cwd()
        logger.info(f"Sandbox initialized with work_dir={self.work_dir}, timeout={self.timeout}s, max_memory_mb={self.max_memory_mb}")

    def _validate_path(self, file_path: str) -> Path:
        """
        校验文件路径安全性，确保路径在允许的工作目录内。

        Args:
            file_path: 待校验的文件路径。

        Returns:
            解析后的绝对路径。

        Raises:
            SandboxPathError: 路径不合法或超出工作目录范围。
        """
        if not file_path or not file_path.strip():
            raise SandboxPathError("文件路径不能为空")

        # 拒绝包含危险字符的路径
        for pattern in _DANGEROUS_ARG_PATTERNS:
            if pattern.search(file_path):
                raise SandboxPathError(f"文件路径包含不允许的字符或模式: {file_path!r}")

        try:
            resolved = Path(file_path).resolve()
        except (ValueError, OSError) as e:
            raise SandboxPathError(f"无法解析文件路径: {e}")

        # 确保路径在工作目录内（防止路径遍历）
        try:
            resolved.relative_to(self.work_dir)
        except ValueError:
            raise SandboxPathError(
                f"文件路径超出允许范围: {resolved!r} 不在 {self.work_dir!r} 内"
            )

        return resolved

    def _validate_command(self, command_list: list[str]) -> None:
        """
        校验命令列表的安全性。

        Args:
            command_list: 已解析的命令参数列表。

        Raises:
            SandboxPermissionError: 命令不在白名单或包含危险参数。
        """
        if not command_list:
            raise SandboxPermissionError("命令列表不能为空")

        executable = command_list[0]

        # 拒绝危险命令
        if executable in _DANGEROUS_COMMANDS:
            raise SandboxPermissionError(f"命令 '{executable}' 被明确禁止执行")

        # 必须在白名单内
        if executable not in _ALLOWED_COMMANDS:
            raise SandboxPermissionError(
                f"命令 '{executable}' 不在允许列表中。"
                f"允许的命令: {', '.join(sorted(_ALLOWED_COMMANDS))}"
            )

        # 校验参数中是否含有危险模式
        for arg in command_list[1:]:
            for pattern in _DANGEROUS_ARG_PATTERNS:
                if pattern.search(arg):
                    raise SandboxPermissionError(
                        f"命令参数包含不允许的字符或模式: {arg!r}"
                    )

    async def check_permission(self, operation: str, target: str) -> bool:
        """
        检查操作权限。

        Args:
            operation: 操作类型，如 'execute'、'read'、'write'、'delete'。
            target: 操作目标（命令名或文件路径）。

        Returns:
            True 表示允许，False 表示拒绝。
        """
        dangerous_operations: Dict[str, list[str]] = {
            "delete": ["system", "config", "password", "/etc", "/root", ".env"],
            "execute": list(_DANGEROUS_COMMANDS),
            "write": ["/etc", "/root", ".env", "password"],
        }

        if operation in dangerous_operations:
            target_lower = target.lower()
            for keyword in dangerous_operations[operation]:
                if keyword in target_lower:
                    logger.warning(
                        f"Permission denied: operation={operation!r}, target={target!r}, "
                        f"matched_keyword={keyword!r}"
                    )
                    return False

        return True

    async def execute_command(
        self,
        command: str,
        working_dir: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        在沙箱内安全执行命令。

        使用 create_subprocess_exec（非 shell 模式）执行命令，
        执行前强制进行权限检查和命令白名单校验。

        Args:
            command: 待执行的命令字符串（将被解析为参数列表）。
            working_dir: 命令执行的工作目录，必须在沙箱允许范围内。
            env: 环境变量字典。
            timeout: 本次命令执行的超时时间（秒），为 None 时使用沙箱默认超时。

        Returns:
            包含 status、returncode、stdout、stderr 的字典。
        """
        # 确定本次执行的超时时间
        exec_timeout = timeout if timeout is not None else self.timeout
        logger.info(f"Sandbox execute_command: {command[:100]!r}, timeout={exec_timeout}s")

        # 解析命令字符串为参数列表（防止 shell 注入）
        try:
            command_list = shlex.split(command)
        except ValueError as e:
            logger.warning(f"Command parse failed: {e}")
            return {"status": "error", "message": f"命令解析失败: {e}"}

        if not command_list:
            return {"status": "error", "message": "命令不能为空"}

        # 权限检查
        allowed = await self.check_permission("execute", command_list[0])
        if not allowed:
            return {"status": "error", "message": f"权限拒绝: 不允许执行命令 '{command_list[0]}'"}

        # 命令白名单校验
        try:
            self._validate_command(command_list)
        except SandboxPermissionError as e:
            logger.warning(f"Command validation failed: {e}")
            return {"status": "error", "message": str(e)}

        # 校验工作目录
        exec_cwd: Optional[str] = None
        if working_dir:
            try:
                validated_dir = self._validate_path(working_dir)
                exec_cwd = str(validated_dir)
            except SandboxPathError as e:
                return {"status": "error", "message": f"工作目录校验失败: {e}"}
        else:
            exec_cwd = str(self.work_dir)

        try:
            # 使用 exec 模式而非 shell 模式，防止 shell 注入
            process = await asyncio.create_subprocess_exec(
                *command_list,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=exec_cwd,
                env=env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=exec_timeout,
                )
                return {
                    "status": "success",
                    "returncode": process.returncode,
                    "stdout": stdout.decode(errors="replace") if stdout else "",
                    "stderr": stderr.decode(errors="replace") if stderr else "",
                }
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.warning(f"Command timeout after {exec_timeout}s: {command_list[0]!r}")
                return {
                    "status": "timeout",
                    "message": f"命令执行超时（超过 {exec_timeout}s）",
                }

        except FileNotFoundError:
            return {"status": "error", "message": f"命令未找到: {command_list[0]!r}"}
        except PermissionError as e:
            return {"status": "error", "message": f"权限不足: {e}"}
        except Exception as e:
            logger.error(f"Command execution error: {e}")
            return {"status": "error", "message": f"命令执行错误: {e}"}

    async def execute_file_operation(
        self,
        operation: str,
        file_path: str,
        content: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        在沙箱内安全执行文件操作。

        所有文件路径在操作前经过严格校验，确保操作限制在
        工作目录内，防止路径遍历攻击。

        Args:
            operation: 操作类型，支持 'read'、'write'、'delete'。
            file_path: 目标文件路径。
            content: 写入内容（仅 write 操作需要）。

        Returns:
            包含 status 和操作结果的字典。
        """
        # 权限检查
        allowed = await self.check_permission(operation, file_path)
        if not allowed:
            return {"status": "error", "message": f"权限拒绝: 不允许对 '{file_path}' 执行 '{operation}' 操作"}

        # 路径安全校验
        try:
            safe_path = self._validate_path(file_path)
        except SandboxPathError as e:
            logger.warning(f"Path validation failed for operation={operation!r}: {e}")
            return {"status": "error", "message": str(e)}

        try:
            if operation == "read":
                if not safe_path.exists():
                    return {"status": "error", "message": f"文件不存在: {file_path}"}
                if not safe_path.is_file():
                    return {"status": "error", "message": f"路径不是文件: {file_path}"}
                file_content = safe_path.read_text(encoding="utf-8")
                return {"status": "success", "content": file_content}

            elif operation == "write":
                if content is None:
                    return {"status": "error", "message": "写入内容不能为 None"}
                # 确保父目录存在
                safe_path.parent.mkdir(parents=True, exist_ok=True)
                safe_path.write_text(content, encoding="utf-8")
                return {"status": "success", "message": f"已写入: {file_path}"}

            elif operation == "delete":
                if not safe_path.exists():
                    return {"status": "error", "message": f"文件不存在: {file_path}"}
                if not safe_path.is_file():
                    return {"status": "error", "message": f"仅支持删除文件，不支持删除目录: {file_path}"}
                safe_path.unlink()
                return {"status": "success", "message": f"已删除: {file_path}"}

            else:
                return {"status": "error", "message": f"不支持的操作类型: {operation!r}"}

        except PermissionError as e:
            logger.error(f"File operation permission error: {e}")
            return {"status": "error", "message": f"权限不足: {e}"}
        except OSError as e:
            logger.error(f"File operation OS error: {e}")
            return {"status": "error", "message": f"文件操作失败: {e}"}
        except Exception as e:
            logger.error(f"File operation unexpected error: {e}")
            return {"status": "error", "message": f"文件操作错误: {e}"}

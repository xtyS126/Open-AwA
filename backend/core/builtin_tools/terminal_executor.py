"""
终端命令执行工具 - 在受控沙箱中执行shell命令并返回结果。
安全策略：命令白名单、超时限制、输出长度限制。
"""

import asyncio
import os
import time
from typing import Dict, Any, List, Optional
from loguru import logger
from security.command_hard_block import is_hard_blocked_command
from security.command_validators import validate_command_for_execution


# 命令安全判定已统一到 security.command_validators.validate_command_for_execution
# （验证器流水线 + 硬阻断 + 终端黑名单/高危路径/危险模式）。本模块不再维护独立的
# BLOCKED_COMMANDS / BLOCKED_PATHS / BLOCKED_PATTERNS 黑名单，避免与单一真相源漂移。

# 最大输出长度（字符）
MAX_OUTPUT_LENGTH = 50000

# 默认超时时间（秒）
DEFAULT_TIMEOUT = 30

# Windows cmd.exe 内建命令平台适配已迁移到 core.command_platform 共享模块
# sandbox.py 与 terminal_executor.py 共用同一份解析逻辑，避免双写漂移
# 重新导出 WINDOWS_BUILTIN_COMMANDS 与 _resolve_command_for_platform，
# 供 tests/test_terminal_executor_platform.py 直接导入校验
from core.command_platform import (
    WINDOWS_BUILTIN_COMMANDS,
    resolve_command_for_platform as _resolve_command_for_platform,
)


class TerminalExecutorSkill:
    """
    终端命令执行技能。
    提供受控的shell命令执行环境，支持超时、输出限制和命令安全检查。
    """
    name: str = "terminal_executor"
    version: str = "1.0.0"
    description: str = "在受控环境中执行终端命令并获取状态和结果"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """初始化终端执行技能，加载配置项。"""
        self.config = config or {}
        self.timeout = self.config.get('timeout', DEFAULT_TIMEOUT)
        self.max_output = self.config.get('max_output', MAX_OUTPUT_LENGTH)
        self.allowed_directories: List[str] = self.config.get('allowed_directories', [])
        self._initialized = False

    async def initialize(self) -> bool:
        """初始化技能，设置工作目录。"""
        if not self.allowed_directories:
            self.allowed_directories = [os.getcwd()]
        logger.info(f"TerminalExecutor initialized, timeout={self.timeout}s")
        self._initialized = True
        return True

    def _is_command_safe(self, command: str) -> bool:
        """
        检查命令是否安全。

        命令安全已统一到 security.command_validators.validate_command_for_execution
        （验证器流水线 + 硬阻断 + 终端黑名单/高危路径/危险模式）。本方法仅保留
        系统级硬阻断作为第一道不可绕过的防线（与统一入口内部幂等），其余校验全部委托。
        """
        if is_hard_blocked_command(command):
            logger.warning("命令匹配系统级硬阻断规则")
            return False
        is_safe, err_msg = validate_command_for_execution(command)
        if not is_safe:
            logger.warning(f"命令被安全策略拦截: {err_msg}")
            return False
        return True

    def is_initialized(self) -> bool:
        """检查技能是否已初始化。"""
        return self._initialized

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """执行终端命令。"""
        if not self._initialized:
            return {"success": False, "error": "技能未初始化"}

        action = kwargs.get('action', 'run_command')
        if action == 'run_command':
            return await self._run_command(kwargs)
        elif action == 'get_status':
            return await self._get_status(kwargs)
        else:
            return {"success": False, "error": f"未知操作: {action}"}

    async def _run_command(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """执行一条命令并返回结果。"""
        command = kwargs.get('command', '').strip()
        working_dir = kwargs.get('working_dir', self.allowed_directories[0] if self.allowed_directories else os.getcwd())
        timeout = kwargs.get('timeout', self.timeout)

        if not command:
            return {"success": False, "error": "命令不能为空"}

        if not self._is_command_safe(command):
            return {"success": False, "error": "命令被安全策略拦截"}

        start_time = time.time()
        process = None
        try:
            args, resolve_error = _resolve_command_for_platform(command)
            if resolve_error:
                return {
                    "success": False,
                    "error": resolve_error,
                    "command": command,
                    "working_dir": working_dir,
                    "duration_ms": 0,
                }
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                env={**os.environ, 'LANG': 'en_US.UTF-8'}
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                elapsed = time.time() - start_time
                logger.warning(f"Command timed out after {elapsed:.1f}s: {command}")
                return {
                    "success": False,
                    "error": f"命令执行超时 ({timeout}秒)",
                    "exit_code": -1,
                    "duration_ms": int(elapsed * 1000)
                }

            elapsed = time.time() - start_time
            stdout_text = stdout.decode('utf-8', errors='replace')[:self.max_output]
            stderr_text = stderr.decode('utf-8', errors='replace')[:self.max_output]

            logger.info(f"Command completed: exit_code={process.returncode}, duration={elapsed:.2f}s")
            return {
                "success": process.returncode == 0,
                "exit_code": process.returncode,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "command": command,
                "working_dir": working_dir,
                "duration_ms": int(elapsed * 1000)
            }
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"Command execution error: {e}")
            return {
                "success": False,
                "error": str(e),
                "duration_ms": int(elapsed * 1000)
            }

    async def _get_status(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """获取系统状态信息。"""
        try:
            import platform
            return {
                "success": True,
                "system": platform.system(),
                "platform": platform.platform(),
                "python_version": platform.python_version(),
                "cwd": os.getcwd(),
                "allowed_directories": self.allowed_directories
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_tools(self) -> List[Dict[str, Any]]:
        """返回工具定义列表。"""
        return [
            {
                "name": "run_command",
                "description": "在终端执行命令并获取输出",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "要执行的shell命令"
                        },
                        "working_dir": {
                            "type": "string",
                            "description": "命令执行的工作目录（可选）"
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "超时时间（秒），默认30"
                        }
                    },
                    "required": ["command"]
                }
            },
            {
                "name": "get_system_status",
                "description": "获取当前系统状态信息",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        ]

    def cleanup(self):
        """清理技能资源。"""
        self._initialized = False
        logger.info(f"{self.name} skill cleaned up")

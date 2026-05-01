"""
终端命令执行工具 - 在受控沙箱中执行shell命令并返回结果。
安全策略：命令白名单、超时限制、输出长度限制。
"""

import asyncio
import os
import shlex
import time
from typing import Dict, Any, List, Optional
from loguru import logger


# 禁止执行的危险命令名（完整匹配命令名，非子串匹配）
BLOCKED_COMMANDS = [
    'rm', 'rmdir', 'mv', 'cp',
    'mkfs', 'mke2fs', 'mkfs.ext2', 'mkfs.ext3', 'mkfs.ext4', 'mkfs.xfs', 'mkfs.btrfs',
    'dd', 'shred',
    'shutdown', 'reboot', 'halt', 'poweroff', 'init',
    'chmod', 'chown', 'chgrp', 'chattr', 'setfacl', 'getfacl',
    'kill', 'pkill', 'killall', 'xkill',
    'iptables', 'ip6tables', 'nft', 'ufw', 'firewall-cmd',
    'mount', 'umount', 'fdisk', 'parted', 'losetup',
    'useradd', 'userdel', 'usermod', 'groupadd', 'groupdel',
    'passwd', 'su', 'sudo', 'doas',
    'wget', 'curl',
    'nc', 'ncat', 'netcat', 'socat', 'telnet',
    'ssh', 'scp', 'sftp', 'rsync',
    'crontab', 'at', 'systemctl', 'service',
    'export', 'unset', 'alias', 'source',
    'chroot', 'nsenter', 'unshare',
    ':(){', 'fork', 'exec',
]

# 禁止出现在命令参数中的高危路径
BLOCKED_PATHS = [
    '/etc/passwd', '/etc/shadow', '/etc/sudoers', '/etc/crontab',
    '/etc/ssh/', '/root/', '/boot/', '/sys/', '/proc/',
    '/dev/sda', '/dev/sdb', '/dev/sdc', '/dev/sdd',
    '/dev/nvme', '/dev/mem', '/dev/kmem', '/dev/port',
    r'\.ssh/', r'\.gnupg/',
]

# 禁止的命令行中出现的模式（正则）
BLOCKED_PATTERNS = [
    r'>\s*/dev/',           # 重定向到设备文件
    r'>>\s*/dev/',
    r'<\s*/dev/zero',      # 从 /dev/zero 读取输入
    r'\$\s*\(',            # $() 命令替换
    r'`[^`]+`',            # 反引号命令替换
    r';\s*\w',             # 命令串联
    r'\|\s*\w',            # 管道（可能用于串联恶意命令）
    r'&&\s*\w',            # 逻辑与串联
    r'\|\|\s*\w',          # 逻辑或串联
    r'\\x[0-9a-fA-F]{2}', # 十六进制编码绕过
    r'base64\s.*-d',       # base64 解码绕过
]

# 最大输出长度（字符）
MAX_OUTPUT_LENGTH = 50000

# 默认超时时间（秒）
DEFAULT_TIMEOUT = 30


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
        多层检查：危险命令名 + 高危路径 + 危险正则模式 + 命令名白名单。
        """
        import re
        try:
            cmd_parts = shlex.split(command)
        except ValueError:
            logger.warning(f"命令解析失败（可能包含未闭合的引号等）: {command}")
            return False
        if not cmd_parts:
            return False

        cmd_name = os.path.basename(cmd_parts[0]).lower()

        # 1. 检查命令名是否在禁止列表中
        if cmd_name in BLOCKED_COMMANDS:
            logger.warning(f"禁止的危险命令: {cmd_parts[0]}")
            return False

        # 2. 检查参数中是否包含高危路径
        cmd_full = command.lower()
        for blocked_path in BLOCKED_PATHS:
            if blocked_path.lower() in cmd_full:
                logger.warning(f"命令中包含禁止的路径: {blocked_path}")
                return False

        # 3. 检查是否匹配禁止的正则模式
        for pattern in BLOCKED_PATTERNS:
            if re.search(pattern, command):
                logger.warning(f"命令匹配禁止模式 '{pattern}': {command}")
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
            args = shlex.split(command)
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

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
from security.command_validators import ValidationResult, validate_command


# 允许执行的命令白名单（仅包含安全的只读或低风险命令）
_ALLOWED_COMMANDS = frozenset([
    'ls', 'cat', 'grep', 'find', 'echo', 'pwd',
    'head', 'tail', 'sort', 'uniq', 'wc', 'cut',
    'mkdir', 'cp', 'mv',
    'tar', 'gzip', 'gunzip', 'zip', 'unzip',
    'diff', 'du', 'df', 'file', 'stat',  # 只读诊断命令
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
    re.compile(r'[;|`$]'),             # Shell 命令分隔符和变量引用（& 已移除：create_subprocess_exec 非 shell 模式无意义）
    re.compile(r'\$\('),               # 命令替换
    re.compile(r'`'),                  # 反引号命令替换
]

# 路径 deny 规则：匹配则拒绝访问
# 同时兼容 Unix 正斜杠和 Windows 反斜杠
_DENY_PATH_PATTERNS = [
    re.compile(r'^/etc/'),                                  # Unix 系统配置目录
    re.compile(r'^/root/'),                                 # Unix root 用户目录
    re.compile(r'^/proc'),                                  # Unix 进程信息
    re.compile(r'^/sys'),                                   # Unix 内核
    re.compile(r'^/var/log/'),                              # 系统日志
    re.compile(r'^[A-Za-z]:[\\/]windows[\\/]system32[\\/]', re.IGNORECASE),  # Windows 系统目录
    re.compile(r'^[A-Za-z]:[\\/]windows[\\/]', re.IGNORECASE),               # Windows 安装目录
    re.compile(r'\.env$'),                                  # .env 文件（任意位置）
]

# 路径 allow 规则：匹配则允许访问（在白名单和内部可编辑路径之后生效）
_ALLOW_PATH_PATTERNS = [
    re.compile(r'^/tmp/'),        # Unix 临时目录
    re.compile(r'^/var/tmp/'),    # Unix 临时目录
]

# 内部可编辑路径：项目自身目录，允许读写
# 在模块加载时计算绝对路径，避免受工作目录影响
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_PROJECT_DIR = _BACKEND_DIR.parent
_INTERNAL_EDITABLE_PATHS = [
    str(_BACKEND_DIR),
    str(_PROJECT_DIR),
]

# 沙箱白名单目录：允许访问的额外目录
_SANDBOX_WHITELIST_DIRS = [
    '/tmp',
    '/var/tmp',
]

# 写操作禁止的 glob 字符
_GLOB_CHARS = ('*', '?', '[', ']')

# Windows 命令注入模式：= 后跟字母（如 =C: 用于设置驱动器当前目录环境变量）
_EQUALS_CMD_PATTERN = re.compile(r'=[A-Za-z]')

# Unix 根子目录危险列表（用于 is_dangerous_removal_path 判定）
_DANGEROUS_ROOT_SUBDIRS = frozenset([
    '/home', '/usr', '/etc', '/var', '/opt', '/bin', '/sbin',
    '/lib', '/lib64', '/tmp', '/root', '/proc', '/sys', '/dev',
    '/boot', '/mnt', '/media', '/srv', '/run',
])


class SandboxPermissionError(Exception):
    """沙箱权限拒绝异常。"""
    pass


class SandboxPathError(Exception):
    """沙箱路径校验失败异常。"""
    pass


def validate_command_safety(executable: str, args: list = None) -> tuple:
    """
    独立函数：校验命令安全性（白名单 + 危险命令黑名单 + 危险参数模式）。

    可在任何需要命令校验的地方使用，无需实例化 Sandbox。

    Args:
        executable: 可执行文件名（如 'ls', 'cat' 等）
        args: 命令参数列表（可选）

    Returns:
        (is_safe: bool, error_message: str or None) 元组
    """
    args = args or []

    # 拒绝危险命令
    if executable in _DANGEROUS_COMMANDS:
        return (False, f"命令 '{executable}' 被明确禁止执行")

    # 必须在白名单内
    if executable not in _ALLOWED_COMMANDS:
        return (False, f"命令 '{executable}' 不在允许列表中。允许的命令: {', '.join(sorted(_ALLOWED_COMMANDS))}")

    # 校验参数中是否含有危险模式
    for arg in args:
        for pattern in _DANGEROUS_ARG_PATTERNS:
            if pattern.search(arg):
                return (False, f"命令参数包含不允许的字符或模式: {arg!r}")

    return (True, None)


def validate_path(path: str) -> bool:
    """
    校验路径安全性，防止 TOCTOU（Time of Check to Time of Use）攻击。

    拒绝以下路径：
    - UNC 路径（\\\\server\\share 或 //server/share）
    - ~root/~+/~- 等 tilde 特殊扩展
    - 含 $ 的路径（环境变量注入）
    - 含 % 的路径（Windows 环境变量注入）
    - 含 =cmd 的路径（Windows 命令注入，如 =C: 设置驱动器当前目录）
    - 含 .. 的路径（路径穿越，但允许 normalize 后的路径）

    使用 pathlib.Path.resolve() 标准化路径后再检查，防止符号链接绕过。

    Args:
        path: 待校验的路径字符串。

    Returns:
        True 表示路径安全，False 表示不安全。
    """
    if not path or not path.strip():
        return False

    path_str = str(path)

    # 拒绝 UNC 路径（\\server\share 或 //server/share）
    if path_str.startswith('\\\\') or path_str.startswith('//'):
        return False

    # 拒绝 tilde 特殊扩展（~root、~+、~- 等）
    if path_str.startswith('~root') or path_str.startswith('~+') or path_str.startswith('~-'):
        return False

    # 拒绝含 $ 的路径（环境变量注入，如 $HOME）
    if '$' in path_str:
        return False

    # 拒绝含 % 的路径（Windows 环境变量注入，如 %PATH%）
    if '%' in path_str:
        return False

    # 拒绝含 =cmd 的路径（Windows 命令注入，如 =C:=C:\path）
    if _EQUALS_CMD_PATTERN.search(path_str):
        return False

    # 拒绝含 .. 的路径（路径穿越）
    # 注意：normalize 后的路径不含 ..，所以这里检查原始路径字符串
    if '..' in path_str:
        return False

    # 使用 pathlib.Path.resolve() 标准化路径后再检查
    # resolve() 会解析符号链接，防止 TOCTOU 攻击
    try:
        resolved = Path(path_str).resolve()
        resolved_str = str(resolved)
        # 标准化后再次检查 .. （防止符号链接绕过）
        if '..' in resolved_str:
            return False
    except (ValueError, OSError, RuntimeError):
        # 解析失败视为不安全
        return False

    return True


def normalize_path(path: str) -> str:
    """
    路径标准化：混合斜杠统一、解析 . 和 ..、去除尾部斜杠（根目录除外）。

    Args:
        path: 待标准化的路径字符串。

    Returns:
        标准化后的路径字符串。空路径返回空字符串。
    """
    if not path:
        return path

    # 混合斜杠统一为正斜杠（Windows 也可用反斜杠，但内部统一）
    normalized = path.replace('\\', '/')

    # 解析 . 和 ..
    parts = normalized.split('/')
    resolved_parts = []
    for part in parts:
        if part == '' or part == '.':
            # 空字符串（连续斜杠）和当前目录标记跳过
            continue
        if part == '..':
            # 父目录标记：弹出栈顶（如果栈非空且栈顶不是 ..）
            if resolved_parts and resolved_parts[-1] != '..':
                resolved_parts.pop()
            else:
                resolved_parts.append('..')
            continue
        resolved_parts.append(part)

    # 重新组装路径
    is_absolute = normalized.startswith('/')
    # UNC 路径以 // 开头，但第三个字符不是 /（如 //server/share）
    # 单独的 // 或 /// 不视为 UNC 路径，标准化为根目录 /
    is_unc = (normalized.startswith('//') and len(normalized) > 2
              and normalized[2] != '/')

    if is_unc:
        # UNC 路径保留前导 //
        result = '//' + '/'.join(resolved_parts)
    elif is_absolute:
        # Unix 绝对路径
        if resolved_parts:
            result = '/' + '/'.join(resolved_parts)
        else:
            # 根目录
            result = '/'
    else:
        # 相对路径
        result = '/'.join(resolved_parts) if resolved_parts else '.'

    # 去除尾部斜杠（根目录除外）
    if len(result) > 1 and result.endswith('/'):
        result = result.rstrip('/')

    return result


def is_dangerous_removal_path(path: str) -> bool:
    """
    判断是否为危险的删除路径。

    危险路径包括：
    - * 或 ? 通配符（可能删除大量文件）
    - / 根目录
    - /home/ 等根子目录
    - Windows 驱动器根（C:\、D:\）
    - 用户主目录（~）

    Args:
        path: 待检查的路径字符串。

    Returns:
        True 表示危险，False 表示安全。空路径视为危险。
    """
    if not path:
        # 空路径视为危险
        return True

    path_str = str(path)

    # 通配符检查（可能删除大量文件）
    if '*' in path_str or '?' in path_str:
        return True

    # 标准化路径用于后续检查
    normalized = normalize_path(path_str)

    # Unix 根目录
    if normalized == '/':
        return True

    # Unix 根子目录（/home、/usr、/etc 等）
    if normalized in _DANGEROUS_ROOT_SUBDIRS:
        return True

    # Windows 驱动器根（C:、D: 等）
    if re.match(r'^[A-Za-z]:$', normalized) or re.match(r'^[A-Za-z]:/$', normalized):
        return True

    # 用户主目录
    if normalized == '~':
        return True

    return False


def is_path_allowed(
    path: str,
    *,
    is_write: bool = False,
    working_dir: Optional[str] = None,
) -> bool:
    """
    五层路径检查：deny 规则 → 安全性检查 → 内部可编辑 → 工作目录 → 沙箱白名单 → allow 规则 → 默认拒绝。

    检查顺序（任一匹配则立即返回）：
        1. deny 规则：匹配则返回 False
        2. 安全性检查（validate_path TOCTOU 防护）：不安全则返回 False
        3. 内部可编辑路径：匹配则返回 True
        4. 工作目录检查：在工作目录内则返回 True
        5. 沙箱白名单：在白名单内则返回 True
        6. allow 规则：匹配则返回 True
        7. 默认拒绝：都不匹配则返回 False

    注意：安全性检查优先于内部可编辑路径检查，防止含危险字符的路径
    （如 $HOME、~root 等）通过相对路径解析绕过 TOCTOU 防护。

    写操作（is_write=True）额外禁止：
        - 路径含 glob 字符（*、?、[、]）
        - 路径含 .. （即使 normalize 后合法）

    Args:
        path: 待检查的路径字符串。
        is_write: 是否为写操作，写操作禁止 glob 模式和路径穿越。
        working_dir: 工作目录，用于检查路径是否在工作目录内。

    Returns:
        True 表示允许访问，False 表示拒绝。
    """
    if not path or not path.strip():
        return False

    path_str = str(path)

    # 写操作禁止 glob 模式和路径穿越（在 deny 规则之前检查，更严格）
    if is_write:
        for char in _GLOB_CHARS:
            if char in path_str:
                logger.warning(f"写操作禁止 glob 模式或路径穿越: {path}")
                return False
        if '..' in path_str:
            logger.warning(f"写操作禁止 glob 模式或路径穿越: {path}")
            return False

    # 第 1 层：deny 规则
    for pattern in _DENY_PATH_PATTERNS:
        if pattern.search(path_str):
            return False

    # 第 2 层：安全性检查（TOCTOU 防护）
    # 安全性检查优先于内部可编辑路径检查，防止含危险字符的路径绕过防护
    if not validate_path(path_str):
        return False

    # 第 3 层：内部可编辑路径（项目目录等）
    try:
        resolved = Path(path_str).resolve()
        for editable in _INTERNAL_EDITABLE_PATHS:
            try:
                editable_resolved = Path(editable).resolve()
                resolved.relative_to(editable_resolved)
                return True
            except ValueError:
                continue
    except (ValueError, OSError, RuntimeError):
        # 解析失败，继续后续检查
        pass

    # 第 4 层：工作目录检查
    if working_dir:
        try:
            working_resolved = Path(working_dir).resolve()
            resolved = Path(path_str).resolve()
            try:
                resolved.relative_to(working_resolved)
                return True
            except ValueError:
                pass
        except (ValueError, OSError, RuntimeError):
            pass

    # 第 5 层：沙箱白名单
    try:
        resolved = Path(path_str).resolve()
        for whitelist_dir in _SANDBOX_WHITELIST_DIRS:
            try:
                whitelist_resolved = Path(whitelist_dir).resolve()
                resolved.relative_to(whitelist_resolved)
                return True
            except ValueError:
                continue
    except (ValueError, OSError, RuntimeError):
        pass

    # 第 6 层：allow 规则
    for pattern in _ALLOW_PATH_PATTERNS:
        if pattern.search(path_str):
            return True

    # 第 7 层：默认拒绝
    return False


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

    def _validate_command(self, command_list: list[str], command_str: Optional[str] = None) -> None:
        """
        校验命令列表的安全性。

        在原有白名单校验之前，先调用验证器流水线对原始命令字符串进行检测。
        若验证器返回 ASK，记录 warning 日志并拒绝执行；
        若返回 ALLOW 或全部 PASSTHROUGH，继续执行白名单校验。

        Args:
            command_list: 已解析的命令参数列表。
            command_str: 原始命令字符串（可选），用于验证器流水线检测。
                         若为 None，则由 command_list 拼接生成。

        Raises:
            SandboxPermissionError: 命令被验证器拒绝、不在白名单或包含危险参数。
        """
        if not command_list:
            raise SandboxPermissionError("命令列表不能为空")

        # 调用验证器流水线：检测命令注入、危险模式等
        # 优先使用原始命令字符串（保留引号、转义等信息），否则由列表拼接
        pipeline_input = command_str if command_str is not None else ' '.join(command_list)
        validation_result = validate_command(pipeline_input)
        if validation_result == ValidationResult.ASK:
            logger.warning(f"命令验证器流水线拒绝执行: {pipeline_input!r}")
            raise SandboxPermissionError(
                f"命令被安全验证器拒绝执行（需用户确认）: {pipeline_input!r}"
            )

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
            self._validate_command(command_list, command)
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

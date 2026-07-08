"""
命令白名单单一真相源模块。

集中管理命令执行白名单、危险命令黑名单、危险参数模式，
以及命令安全校验与路径越权校验的统一入口。

设计目标：
- 消除 sandbox.py / command_executor.py / skill_executor.py 三处白名单漂移
- 危险命令（rm -rf /、sudo rm -rf /、mkfs、dd if=）直接拒绝，不进入用户审批流程
  （参考 project_memory.md 中 ACP 硬阻断安全策略）
- 路径校验必须使用 Path.resolve() + relative_to()，禁止 str.startswith()
  （str.startswith 可被 ../ 符号链接绕过，详见 project_memory.md 路径穿越硬约束）

使用方式：
- 新代码直接调用 validate_command_safety(cmd: list[str]) -> bool
- 需要错误信息的场景调用 validate_command_safety_detailed(executable, args) -> tuple
- 工作空间路径越权校验调用 is_path_allowed(path: Path, workspace: Path) -> bool
"""

import re
from pathlib import Path
from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# 命令白名单：合并自 sandbox.py / command_executor.py / skill_executor.py 三处
# 包含 shell 内建命令（echo/pwd）与跨平台兼容命令（dir/type/where）
# ---------------------------------------------------------------------------
ALLOWED_COMMANDS: frozenset[str] = frozenset([
    # 只读诊断命令
    'ls', 'cat', 'grep', 'find', 'echo', 'pwd',
    'head', 'tail', 'sort', 'uniq', 'wc', 'cut', 'tr', 'tee',
    'diff', 'du', 'df', 'file', 'stat',
    # 文件管理（低风险）
    'mkdir', 'cp', 'mv',
    'tar', 'gzip', 'gunzip', 'zip', 'unzip',
    # 跨平台兼容命令（command_executor.py 原 SAFE_COMMANDS 并入）
    'git', 'dir', 'type', 'rg', 'date',
    'whoami', 'hostname', 'uname', 'env', 'printenv',
    'which', 'where',
])


# ---------------------------------------------------------------------------
# 危险命令黑名单：即使在白名单中也拒绝
# 参考 project_memory.md ACP 硬阻断策略：rm/sudo/mkfs/dd 等直接拒绝
# ---------------------------------------------------------------------------
DANGEROUS_COMMANDS: frozenset[str] = frozenset([
    # 破坏性删除/权限变更
    'rm', 'chmod', 'chown', 'xargs', 'awk', 'sed',
    # 磁盘级破坏
    'dd', 'mkfs', 'fdisk', 'mount', 'umount',
    # 提权/Shell 转义
    'sudo', 'su', 'bash', 'sh', 'zsh', 'fish',
    # 脚本语言解释器（可绕过沙箱）
    'python', 'python3', 'perl', 'ruby', 'node',
    # 网络工具（可下载/上传任意文件）
    'curl', 'wget', 'nc', 'netcat', 'ncat',
])


# ---------------------------------------------------------------------------
# 危险参数模式（防止参数级注入）
# 注意：& 已移除全局拦截——create_subprocess_exec 非 shell 模式下 & 无意义，
#       且 URL 数据中常含 &（如 ?a=1&b=2），全局拦截会误伤合法用例。
# ---------------------------------------------------------------------------
DANGEROUS_ARG_PATTERNS: list[re.Pattern] = [
    re.compile(r'\.\.[\\/]'),          # 路径遍历 ../
    re.compile(r'^[\\/]etc[\\/]'),     # /etc/ 目录
    re.compile(r'^[\\/]root'),         # /root 目录
    re.compile(r'^[\\/]proc'),         # /proc 目录
    re.compile(r'^[\\/]sys'),          # /sys 目录
    re.compile(r'[;|`$]'),             # Shell 命令分隔符和变量引用
    re.compile(r'\$\('),               # 命令替换 $(
    re.compile(r'`'),                  # 反引号命令替换
]


# ---------------------------------------------------------------------------
# 危险命令模式：ACP 硬阻断策略，直接拒绝不进入用户审批流程
# 参考 project_memory.md：rm -rf / / sudo rm -rf / / mkfs / dd if= 命令子串直接拒绝
# ---------------------------------------------------------------------------
DANGEROUS_COMMAND_PATTERNS: list[re.Pattern] = [
    re.compile(r'\brm\s+-rf\s+/(\s|$)'),          # rm -rf /
    re.compile(r'\bsudo\s+rm\s+-rf\s+/(\s|$)'),   # sudo rm -rf /
    re.compile(r'\bmkfs\b'),                       # mkfs 任意文件系统格式化
    re.compile(r'\bdd\s+if='),                     # dd if= 磁盘级写入
]


def validate_command_safety(cmd: list[str]) -> bool:
    """
    校验命令是否安全可执行（统一入口，新代码推荐使用）。

    检查内容：
    1. 命令列表非空
    2. 可执行文件名不在 DANGEROUS_COMMANDS 黑名单中
    3. 可执行文件名在 ALLOWED_COMMANDS 白名单中
    4. 参数不包含 DANGEROUS_ARG_PATTERNS 中的任何模式
    5. 整条命令不匹配 DANGEROUS_COMMAND_PATTERNS（rm -rf / 等硬阻断）

    Args:
        cmd: 命令参数列表，第一个元素为可执行文件名。

    Returns:
        True 表示命令安全可执行，False 表示拒绝。
    """
    if not cmd:
        return False

    executable = cmd[0]
    args = cmd[1:]

    # 危险命令黑名单优先（rm/sudo/mkfs/dd 等直接拒绝）
    if executable in DANGEROUS_COMMANDS:
        return False

    # 必须在白名单内
    if executable not in ALLOWED_COMMANDS:
        return False

    # 参数危险模式检查
    for arg in args:
        for pattern in DANGEROUS_ARG_PATTERNS:
            if pattern.search(arg):
                return False

    # ACP 硬阻断策略：rm -rf / / sudo rm -rf / / mkfs / dd if= 直接拒绝
    full_cmd = ' '.join(cmd)
    for pattern in DANGEROUS_COMMAND_PATTERNS:
        if pattern.search(full_cmd):
            return False

    return True


def validate_command_safety_detailed(
    executable: str,
    args: Optional[list[str]] = None,
) -> Tuple[bool, Optional[str]]:
    """
    校验命令安全性，返回详细错误信息（向后兼容入口）。

    供 sandbox.py / skill_executor.py 等需要错误信息的调用方使用。
    内部委托给统一的危险命令/白名单/参数模式检查逻辑。

    Args:
        executable: 可执行文件名（如 'ls', 'cat' 等）。
        args: 命令参数列表（可选）。

    Returns:
        (is_safe, error_message) 元组。is_safe 为 True 时 error_message 为 None。
    """
    args = args or []

    # 危险命令黑名单
    if executable in DANGEROUS_COMMANDS:
        return (False, f"命令 '{executable}' 被明确禁止执行")

    # 必须在白名单内
    if executable not in ALLOWED_COMMANDS:
        return (
            False,
            f"命令 '{executable}' 不在允许列表中。"
            f"允许的命令: {', '.join(sorted(ALLOWED_COMMANDS))}"
        )

    # 参数危险模式检查
    for arg in args:
        for pattern in DANGEROUS_ARG_PATTERNS:
            if pattern.search(arg):
                return (False, f"命令参数包含不允许的字符或模式: {arg!r}")

    # ACP 硬阻断策略：rm -rf / / sudo rm -rf / / mkfs / dd if= 直接拒绝
    full_cmd = ' '.join([executable] + list(args))
    for pattern in DANGEROUS_COMMAND_PATTERNS:
        if pattern.search(full_cmd):
            return (False, f"命令匹配硬阻断模式（rm -rf / / mkfs / dd if= 等）: {full_cmd!r}")

    return (True, None)


def is_path_allowed(path: Path, workspace: Path) -> bool:
    """
    校验路径是否在指定工作空间内（防止路径越权）。

    使用 Path.resolve() + relative_to() 进行严格的路径包含校验，
    禁止使用 str.startswith()——str.startswith 可被 ../ 符号链接绕过。

    Args:
        path: 待校验的目标路径。
        workspace: 允许的工作空间根路径。

    Returns:
        True 表示路径在工作空间内，False 表示越权或解析失败。
    """
    if path is None or workspace is None:
        return False

    try:
        resolved_path = Path(path).resolve()
        resolved_workspace = Path(workspace).resolve()
        # relative_to 抛 ValueError 表示路径不在 workspace 内
        resolved_path.relative_to(resolved_workspace)
        return True
    except (ValueError, OSError, RuntimeError):
        return False

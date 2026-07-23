"""
跨平台命令解析模块。

提供 Windows 内建命令（cmd.exe 内建）的平台适配，避免 create_subprocess_exec
在 Windows 下因找不到内建命令可执行文件而抛出 WinError 2。

设计原则：
1. 不引入 shell=True，保持参数列表语义，避免 shell 注入风险
2. 仅对白名单内的只读/无害内建命令用 cmd.exe /c 包装
3. 可执行文件存在时直接使用绝对路径，与原逻辑等价
"""

import os
import shlex
import shutil
from typing import Tuple, List, Optional


# Windows cmd.exe 内建命令白名单（只读/无害命令）
# Windows 下这些命令不是独立可执行文件，需通过 cmd.exe /c 包装执行
# 仅含只读或显示类命令，不含 copy/move/del/rd/md/ren 等写操作命令
WINDOWS_BUILTIN_COMMANDS = frozenset({
    'echo', 'dir', 'type', 'ver', 'vol', 'path', 'cls', 'cd', 'chdir',
    'title', 'color', 'date', 'time', 'prompt', 'tree', 'where', 'whoami',
    'hostname', 'assoc', 'ftype', 'mode', 'sort', 'find', 'findstr',
    'more', 'comp', 'fc', 'systeminfo', 'tasklist', 'driverquery',
})


def resolve_command_for_platform(command: str) -> Tuple[List[str], Optional[str]]:
    """根据平台解析命令，返回 (args, error)。

    Windows 下对 cmd.exe 内建命令做平台适配：
    1. 先用 shutil.which 探测命令是否为可执行文件
    2. 找到 -> 直接执行（原逻辑）
    3. 找不到 + 在 WINDOWS_BUILTIN_COMMANDS 白名单 -> 用 cmd.exe /c 包装
    4. 找不到 + 不在白名单 -> 返回友好错误，避免 WinError 2

    其他平台保持原 shlex.split 逻辑。

    Args:
        command: 原始命令字符串

    Returns:
        (args, error)：args 为传给 create_subprocess_exec 的参数列表，
        error 为 None 时可执行，非 None 时为错误信息
    """
    try:
        args = shlex.split(command)
    except ValueError:
        return [], f"命令解析失败（可能包含未闭合的引号）: {command}"

    if not args:
        return [], "命令不能为空"

    # 非 Windows 平台保持原逻辑
    if os.name != 'nt':
        return args, None

    cmd_name = os.path.basename(args[0]).lower()

    # Windows 下先探测是否为可执行文件
    executable = shutil.which(cmd_name)
    if executable:
        # 找到可执行文件，替换为绝对路径执行
        args[0] = executable
        return args, None

    # 找不到可执行文件，检查是否为 cmd.exe 内建命令
    if cmd_name in WINDOWS_BUILTIN_COMMANDS:
        # 用 cmd.exe /c 包装，参数仍用 shlex 分割后传递
        # cmd.exe /c 后接命令名 + 参数，cmd.exe 自行解析内建命令
        return ["cmd.exe", "/c", *args], None

    # 既不是可执行文件，也不在内建命令白名单
    return [], (
        f"命令未找到: {cmd_name}（Windows 下请确认命令名或提供完整路径）"
    )

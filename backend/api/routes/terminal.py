"""
终端 WebSocket API，为前端 IDE 提供实时终端会话。
支持创建会话、执行命令、流式输出和会话管理。

本模块提供两条路径：
1. 一次性执行：通过 `POST /sessions` 创建 `TerminalSession`，调用 `POST /sessions/{id}/execute` 或
   `WS /ws/{id}` 执行单条命令。保持向后兼容。
2. PTY 持久化：通过 `POST /sessions/pty` 创建 `PTYTerminalSession`，调用 `WS /ws/pty/{id}`
   进行交互式 PTY 会话，支持断线重连与屏幕恢复。

安全策略：
1. 所有 HTTP 端点强制鉴权（Depends(get_current_user)）
2. WebSocket 端点通过 token 查询参数或 Sec-WebSocket-Protocol 子协议鉴权
3. WebSocket 端点校验 Origin 头，防止 CSWSH 跨站 WebSocket 劫持
4. 命令执行前过滤危险命令、高危路径、危险模式
5. cwd 参数必须位于允许的工作区根目录内
6. PTY 每条完整命令行（以 \\n 结束）都校验是否在黑名单中
7. 所有会话访问端点校验 owner_user_id 归属，防止 IDOR 越权访问
8. 模块级会话字典使用 OrderedDict + per-user/总容量上限，防止 OOM
"""

import asyncio
import inspect
import os
import re
import shlex
import sys
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketState

from api.dependencies import get_current_user
from api.security.ws_auth import extract_token_from_subprotocol, validate_ws_origin
from config.security import decode_access_token
from core.terminal import PTYSession
from db.models import SessionLocal, User
from security.command_hard_block import is_hard_blocked_command

router = APIRouter(prefix="/terminal", tags=["terminal"])


# 终端会话管理（一次性执行模式）：使用 OrderedDict 实现 LRU 淘汰
_terminal_sessions: "OrderedDict[str, TerminalSession]" = OrderedDict()

# PTY 持久化会话管理：使用 OrderedDict 实现 LRU 淘汰
_pty_sessions: "OrderedDict[str, PTYTerminalSession]" = OrderedDict()

# 安全限制
MAX_SESSIONS = 10
MAX_OUTPUT_LENGTH = 50000
DEFAULT_TIMEOUT = 30
MAX_PTY_SESSIONS = 5
_PTY_READER_QUEUE_SIZE = 1024

# LRU 容量上限：单用户最大会话数与全局总会话数
# MAX_SESSIONS / MAX_PTY_SESSIONS 现作为 per-user 上限（达到后拒绝创建）
_MAX_TOTAL_SESSIONS = 1000

# 默认 PTY 启动命令（跨平台）
_DEFAULT_PTY_COMMAND_WIN: List[str] = ["cmd.exe"]
_DEFAULT_PTY_COMMAND_POSIX: List[str] = ["/bin/bash"]

# 允许作为 cwd 的根目录白名单（默认为当前工作目录与其下级子目录）
_ALLOWED_WORKSPACE_ROOTS: List[str] = [os.path.abspath(os.getcwd())]


def _schedule_evicted_session_close(session_id: str, session: Any) -> None:
    """调度被 LRU 淘汰会话的异步关闭，防止其子进程继续存活。"""
    close = getattr(session, "close", None)
    if not callable(close):
        return
    try:
        result = close()
    except Exception as exc:
        logger.bind(
            event="session_lru_close_error",
            module="terminal",
            session_id=session_id,
            error_type=type(exc).__name__,
        ).warning("LRU 淘汰会话关闭失败")
        return
    if not inspect.isawaitable(result):
        return

    try:
        task = asyncio.get_running_loop().create_task(result)
    except RuntimeError:
        # 该函数通常仅在异步 API 路径调用；同步测试或异常上下文中不遗留协程。
        result.close()
        logger.bind(
            event="session_lru_close_deferred",
            module="terminal",
            session_id=session_id,
        ).warning("LRU 淘汰会话缺少运行事件循环，未能异步关闭")
        return

    def _log_close_result(completed_task: asyncio.Task[Any]) -> None:
        try:
            completed_task.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.bind(
                event="session_lru_close_error",
                module="terminal",
                session_id=session_id,
                error_type=type(exc).__name__,
            ).warning("LRU 淘汰会话异步关闭失败")

    task.add_done_callback(_log_close_result)


def _add_session(
    sessions_dict: "OrderedDict[str, Any]",
    session_id: str,
    session: Any,
    owner_user_id: str,
    max_per_user: int,
) -> None:
    """
    添加会话并维护 LRU 与 per-user 限制。

    - 当 per-user 会话数达到 max_per_user 时拒绝添加（由调用方判断返回错误）
    - 当总容量达到 _MAX_TOTAL_SESSIONS 时淘汰最早的会话（OrderedDict 头部）
    - 新会话添加到末尾（最近使用）

    Args:
        sessions_dict: OrderedDict 形式的会话字典
        session_id: 会话 ID
        session: 会话对象，必须包含 owner_user_id 属性
        owner_user_id: 所有者用户 ID
        max_per_user: 单用户最大会话数，达到则由调用方拒绝
    """
    # 检查总容量：超过上限时淘汰最早的会话（LRU 头部）
    while len(sessions_dict) >= _MAX_TOTAL_SESSIONS:
        evicted_sid, evicted_session = sessions_dict.popitem(last=False)
        _schedule_evicted_session_close(evicted_sid, evicted_session)
        logger.bind(
            event="session_lru_evicted",
            module="terminal",
            session_id=evicted_sid,
            owner_user_id=getattr(evicted_session, "owner_user_id", None),
        ).info(f"会话因总容量上限被 LRU 淘汰: {evicted_sid}")
    # 将新会话添加到末尾（最近使用）
    sessions_dict[session_id] = session


def _count_user_sessions(sessions_dict: Dict[str, Any], owner_user_id: str) -> int:
    """统计指定用户在会话字典中的活跃会话数。"""
    return sum(
        1 for s in sessions_dict.values() if getattr(s, "owner_user_id", None) == owner_user_id
    )


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
# 命令串联/管道/逻辑运算符：仅当串联到危险命令时才拦截，避免误拦 echo "Hi" && pwd 等无害组合
_CHAIN_RISKY_SUFFIX = r'(?:;|\|\||&&|\|)\s*(' + '|'.join(re.escape(c) for c in BLOCKED_COMMANDS) + r')\b'
BLOCKED_PATTERNS = [
    r'>\s*/dev/',           # 重定向到设备文件
    r'>>\s*/dev/',
    r'<\s*/dev/zero',      # 从 /dev/zero 读取输入
    r'\$\s*\(',            # $() 命令替换
    r'`[^`]+`',            # 反引号命令替换
    _CHAIN_RISKY_SUFFIX,   # 串联到危险命令（如 curl|bash, wget && 执行等）
    r'\\x[0-9a-fA-F]{2}', # 十六进制编码绕过
    r'base64\s.*-d',       # base64 解码绕过
    # === SEC-20 增强：解释器内联执行绕过防护 ===
    # 安全策略：黑名单基于命令名完整匹配，可被解释器 -c/-e/-i 等参数绕过，
    # 因此对解释器内联执行模式单独拦截，避免 python -c 'os.system("rm -rf /")' 等攻击
    # Python 内联代码执行：python/python3 + -c/-i 后跟任意代码（-i 可单独出现在行尾）
    r'\bpython[0-9]?\s+(-c|-i)\b',
    # Python 模块方式执行危险模块：python -m <危险模块>
    r'\bpython[0-9]?\s+-m\s+(subprocess|pty|code|codeop|pdb|IPython|shutil)',
    # Node.js 内联代码执行：node + -e/--eval/-p/--print 后跟任意代码
    r'\bnode\s+(-e|--eval|-p|--print)\s',
    # Node.js 通过 -r/--require 加载 child_process 模块
    r'\bnode\s+(-r|--require)\s+\S*child_process',
    # 任意 shell + -c 组合执行内联命令（bash -c, sh -c, zsh -c, dash -c, /bin/sh -c 等）
    r'(^|[\s/])(bash|sh|zsh|dash|ksh|csh|tcsh)\s+-c\b',
    # === SEC-20 增强：危险调用 API 模式 ===
    # 直接调用执行任意命令的系统接口，通常出现在解释器内联代码中
    r'\beval\s',                # shell eval 命令（执行字符串作为命令）
    r'\bexec\s*\(',             # Python/JS exec() 调用
    r'\bsubprocess\.',          # Python subprocess 模块引用
    r'\bos\.system\s*\(',       # Python os.system() 调用
    r'\bos\.popen\s*\(',        # Python os.popen() 调用
    r'\bos\.exec\w*\s*\(',      # Python os.exec* 系列调用
    r'\bchild_process\b',       # Node.js child_process 模块引用
    r"require\s*\(\s*['\"]child_process['\"]\s*\)",  # Node.js require('child_process')
    r'\bspawn\s*\(',            # Node.js spawn() 调用
    r'\bexecSync\s*\(',         # Node.js execSync() 调用
    r'\bexecFile\s*\(',         # Node.js execFile() 调用
    # === SEC-20 增强：环境变量绕过防护 ===
    # 通过 $IFS、${...} 等环境变量构造绕过黑名单的命令
    r'\$IFS',                   # IFS 变量绕过空格过滤
    r'\$\(\s*\{',               # $({ 命令替换变体
]


def _is_command_safe(command: str) -> bool:
    """
    检查命令是否安全。
    多层检查：危险命令名 + 高危路径 + 危险正则模式。
    """
    if is_hard_blocked_command(command):
        logger.warning("命令匹配系统级硬阻断规则")
        return False

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


def _validate_cwd(cwd: Optional[str]) -> str:
    """
    校验 cwd 参数：必须为 None（使用默认工作目录）或位于允许的工作区根目录内。
    返回校验通过后的绝对路径。校验失败抛出 400 HTTPException。
    """
    if not cwd:
        return os.getcwd()

    # 拒绝空字符串
    cwd_str = cwd.strip()
    if not cwd_str:
        raise HTTPException(status_code=400, detail="cwd 不能为空字符串")

    # 解析为绝对路径并规范化（解析 ..、符号链接等）
    try:
        cwd_path = Path(cwd_str).resolve()
    except (OSError, ValueError) as e:
        logger.warning(f"cwd 路径解析失败: {cwd_str}, 错误: {e}")
        raise HTTPException(status_code=400, detail="cwd 路径无效")

    # 校验路径必须位于允许的工作区根目录内
    for root in _ALLOWED_WORKSPACE_ROOTS:
        try:
            cwd_path.relative_to(Path(root).resolve())
            return str(cwd_path)
        except ValueError:
            continue

    logger.warning(f"cwd 路径越权: {cwd_str} 不在允许的工作区内")
    raise HTTPException(status_code=400, detail="cwd 路径不在允许的工作区内")


def _ws_load_user_by_name(username: str) -> Optional[User]:
    """
    WebSocket 鉴权专用：在独立短生命周期会话内查询用户。
    避免把请求外层 Session 传入 asyncio.to_thread（SQLAlchemy Session 非线程安全）。
    """
    with SessionLocal() as db:
        return db.query(User).filter(User.username == username).first()


class TerminalSession:
    """终端会话，管理子进程和输出流。"""

    def __init__(
        self,
        session_id: str,
        cwd: str = None,
        owner_user_id: Optional[str] = None,
    ):
        self.session_id = session_id
        self.cwd = cwd or os.getcwd()
        # 会话所有者用户 ID，用于 IDOR 越权访问防护
        self.owner_user_id: Optional[str] = owner_user_id
        self.process: Optional[asyncio.subprocess.Process] = None
        self.active = True
        # 安全防护：过滤敏感环境变量，防止用户通过 printenv/env/echo 读取密钥
        from core.terminal.env_sanitizer import build_safe_env
        self.env = build_safe_env()

    async def execute(self, command: str, timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
        """执行命令并返回输出。"""
        try:
            # 安全检查：危险命令黑名单 + 高危路径 + 危险模式
            if not _is_command_safe(command):
                return {"ok": False, "error": "命令被安全策略拒绝"}

            # 使用 shlex 分割参数，不使用 shell=True
            args = shlex.split(command)
            if not args:
                return {"ok": False, "error": "空命令"}

            self.process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.cwd,
                env=self.env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    self.process.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                self.process.kill()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.bind(
                        event="terminal_execute_kill_wait_timeout",
                        module="terminal",
                        session_id=self.session_id,
                    ).error("终端命令超时后子进程未在限定时间内退出")
                return {"ok": False, "error": f"命令执行超时（{timeout}s）"}

            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")

            # 截断过长输出
            if len(stdout_text) > MAX_OUTPUT_LENGTH:
                stdout_text = stdout_text[:MAX_OUTPUT_LENGTH] + "\n... [输出已截断]"
            if len(stderr_text) > MAX_OUTPUT_LENGTH:
                stderr_text = stderr_text[:MAX_OUTPUT_LENGTH] + "\n... [错误输出已截断]"

            return {
                "ok": True,
                "exit_code": self.process.returncode,
                "stdout": stdout_text,
                "stderr": stderr_text,
            }
        except FileNotFoundError:
            return {"ok": False, "error": f"命令不存在: {args[0]}"}
        except Exception as e:
            logger.bind(
                event="terminal_execute_error",
                module="terminal",
                session_id=self.session_id,
                error_type=type(e).__name__,
                error_message=str(e),
            ).warning(f"终端命令执行失败: {e}")
            return {"ok": False, "error": f"执行失败: {str(e)}"}

    async def close(self) -> None:
        """关闭会话，终止正在运行的进程。"""
        self.active = False
        if self.process and self.process.returncode is None:
            try:
                self.process.kill()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.bind(
                    event="terminal_close_timeout",
                    module="terminal",
                    session_id=self.session_id,
                ).error("终端子进程终止后未在限定时间内退出")
            except Exception as e:
                logger.bind(
                    event="terminal_close_error",
                    module="terminal",
                    session_id=self.session_id,
                    error_type=type(e).__name__,
                ).warning(f"关闭终端进程失败: {e}")


class TerminalCommandRequest(BaseModel):
    """终端命令请求。"""
    command: str = Field(..., min_length=1, max_length=10000, description="要执行的命令")
    timeout: int = Field(default=DEFAULT_TIMEOUT, ge=1, le=300, description="超时秒数")


class PTYCreateRequest(BaseModel):
    """PTY 会话创建请求。"""
    cwd: Optional[str] = Field(default=None, description="子进程工作目录")
    cols: int = Field(default=80, ge=10, le=500, description="初始列数")
    rows: int = Field(default=24, ge=2, le=200, description="初始行数")
    command: Optional[List[str]] = Field(
        default=None, description="自定义 PTY 启动命令；为空时按平台默认选择"
    )


class PTYTerminalSession:
    """
    PTY 持久化终端会话。

    封装 PTYSession，提供：
    - 输出广播队列：多个 WebSocket 客户端可订阅同一会话实现断线重连
    - 命令黑名单校验：每条完整命令行（以 \\n 结束）都校验是否在黑名单中
    - 屏幕快照与滚动历史查询
    """

    def __init__(
        self,
        session_id: str,
        cwd: str,
        command: Optional[List[str]] = None,
        cols: int = 80,
        rows: int = 24,
        owner_user_id: Optional[str] = None,
    ) -> None:
        self.session_id: str = session_id
        self.cwd: str = cwd
        # 会话所有者用户 ID，用于 IDOR 越权访问防护
        self.owner_user_id: Optional[str] = owner_user_id
        self.active: bool = True

        # 选择默认命令
        if not command:
            command = (
                _DEFAULT_PTY_COMMAND_WIN
                if sys.platform == "win32"
                else _DEFAULT_PTY_COMMAND_POSIX
            )
        self.command: List[str] = list(command)

        # 创建底层 PTY 会话（注册输出回调以广播给订阅者）
        self.pty: PTYSession = PTYSession(
            command=self.command,
            cwd=cwd,
            cols=cols,
            rows=rows,
            on_output=self._on_pty_output,
        )

        # 输出广播队列：每个连接的客户端一个队列，PTY reader 向所有队列推送
        self._subscribers: List[asyncio.Queue[Dict[str, Any]]] = []

        # 命令行缓冲区：用于跨数据包的命令行安全校验（替代旧的 _first_command_checked 标志）
        self._line_buffer: str = ""

        # 最近一次推送的输出（用于断线重连时回放最近片段）
        self._recent_output: List[str] = []
        self._recent_output_limit: int = 200

    def _on_pty_output(self, data: str) -> None:
        """PTY 输出回调：把数据推送给所有订阅者。"""
        self.push_output(data)

    async def start(self) -> None:
        """启动 PTY 子进程与读取协程。"""
        await self.pty.start()

    def push_output(self, data: str) -> None:
        """
        推送输出数据到所有订阅者队列。

        Args:
            data: PTY 输出的原始字符串数据。
        """
        # 维护最近输出缓冲
        self._recent_output.append(data)
        if len(self._recent_output) > self._recent_output_limit:
            # 截断保留最近 N 段
            self._recent_output = self._recent_output[-self._recent_output_limit:]

        message = {"type": "output", "data": data}
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # 队列满：丢弃该订阅者的消息
                logger.bind(
                    event="pty_subscriber_queue_full",
                    module="terminal",
                    session_id=self.session_id,
                ).warning("PTY 订阅者队列满，丢弃消息")

    async def write_input(self, data: str) -> Dict[str, Any]:
        """
        处理来自客户端的输入数据。

        对每条完整命令行（以 \\n 结束）都做 _is_command_safe 校验。
        通过行缓冲区处理跨数据包的命令行，避免被拆分绕过。
        拦截时返回 {"ok": False, "error": "...", "command": "..."}，
        否则写入 PTY 并返回 {"ok": True}。

        Args:
            data: 客户端输入的原始数据。
        """
        # 累积到行缓冲区，处理跨数据包的命令行
        self._line_buffer += data

        # 按 \n 分割，对每条完整命令行做安全校验
        while "\n" in self._line_buffer:
            line, self._line_buffer = self._line_buffer.split("\n", 1)
            # 去除可能的 \r 与首尾空白后校验
            clean_line = line.replace("\r", "").strip()
            if clean_line and not _is_command_safe(clean_line):
                logger.bind(
                    event="pty_command_blocked",
                    module="terminal",
                    session_id=self.session_id,
                    command=clean_line[:100],
                ).warning(f"PTY 命令被黑名单拦截: {clean_line[:50]}")
                # 清空缓冲区，丢弃剩余数据，避免后续命令拼接绕过
                self._line_buffer = ""
                return {
                    "ok": False,
                    "error": "命令被安全策略拒绝",
                    "command": clean_line,
                }

        # 所有完整行都通过校验，写入 PTY
        await self.pty.write(data)
        return {"ok": True}

    def get_snapshot(self) -> Dict[str, Any]:
        """返回当前屏幕快照与尺寸。"""
        return {
            "grid": self.pty.get_snapshot(),
            "cols": self.pty.cols,
            "rows": self.pty.rows,
        }

    def get_scrollback(self, limit: int = 100) -> List[str]:
        """返回滚动历史。"""
        return self.pty.get_scrollback(limit)

    def subscribe(self) -> asyncio.Queue[Dict[str, Any]]:
        """订阅本会话的输出消息流，返回一个新队列。"""
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(
            maxsize=_PTY_READER_QUEUE_SIZE
        )
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Dict[str, Any]]) -> None:
        """取消订阅。"""
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    async def resize(self, cols: int, rows: int) -> None:
        """调整 PTY 与 VT 屏幕大小。"""
        await self.pty.resize(cols, rows)

    async def close(self) -> None:
        """关闭 PTY 会话。"""
        self.active = False
        # 清空订阅者并放入关闭信号
        for queue in list(self._subscribers):
            try:
                queue.put_nowait({"type": "closed"})
            except asyncio.QueueFull:
                pass
        self._subscribers.clear()
        await self.pty.close()


@router.post("/sessions/pty")
async def create_pty_session(
    request: PTYCreateRequest,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    创建 PTY 持久化终端会话。

    与 `/sessions` 不同，PTY 会话长期持有交互式 shell 进程，支持断线重连与屏幕恢复。
    """
    # 校验 cwd 路径安全性
    safe_cwd = _validate_cwd(request.cwd)

    # 清理已关闭的 PTY 会话
    closed = [sid for sid, s in _pty_sessions.items() if not s.active]
    for sid in closed:
        _pty_sessions.pop(sid, None)

    # per-user 会话数限制（防止单用户耗尽全局配额）
    owner_id = str(current_user.id)
    if _count_user_sessions(_pty_sessions, owner_id) >= MAX_PTY_SESSIONS:
        return {"ok": False, "error": "已达到最大 PTY 会话数限制"}

    session_id = str(uuid.uuid4())[:8]
    session = PTYTerminalSession(
        session_id=session_id,
        cwd=safe_cwd,
        command=request.command,
        cols=request.cols,
        rows=request.rows,
        owner_user_id=owner_id,
    )

    try:
        await session.start()
    except Exception as e:
        logger.bind(
            event="pty_session_start_failed",
            module="terminal",
            session_id=session_id,
            error_type=type(e).__name__,
            error_message=str(e),
            user_id=current_user.id,
        ).error(f"PTY 会话启动失败: {e}")
        return {"ok": False, "error": f"PTY 会话启动失败: {str(e)}"}

    # 通过 LRU 辅助函数添加（处理总容量上限淘汰）
    _add_session(_pty_sessions, session_id, session, owner_id, MAX_PTY_SESSIONS)

    logger.bind(
        event="pty_session_created",
        module="terminal",
        session_id=session_id,
        cwd=safe_cwd,
        cols=request.cols,
        rows=request.rows,
        user_id=current_user.id,
    ).info(f"PTY 会话已创建: {session_id}")

    return {
        "ok": True,
        "session_id": session_id,
        "cwd": safe_cwd,
        "cols": request.cols,
        "rows": request.rows,
        "shell": session.command[0] if session.command else "",
    }


@router.get("/sessions/pty")
async def list_pty_sessions(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """列出当前用户所有活跃的 PTY 终端会话（按 owner_user_id 过滤）。"""
    owner_id = str(current_user.id)
    return {
        "ok": True,
        "sessions": [
            {
                "session_id": sid,
                "cwd": s.cwd,
                "active": s.active,
                "alive": s.pty.is_alive(),
                "shell": s.command[0] if s.command else "",
            }
            for sid, s in _pty_sessions.items()
            if s.active and getattr(s, "owner_user_id", None) == owner_id
        ],
    }


@router.delete("/sessions/pty/{session_id}")
async def close_pty_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """关闭 PTY 终端会话（仅会话所有者可操作）。"""
    session = _pty_sessions.get(session_id)
    if session is None:
        return {"ok": False, "error": "PTY 会话不存在"}

    # IDOR 校验：仅会话所有者可关闭
    if getattr(session, "owner_user_id", None) != str(current_user.id):
        raise HTTPException(status_code=403, detail="无权访问该会话")

    _pty_sessions.pop(session_id, None)
    await session.close()

    logger.bind(
        event="pty_session_closed",
        module="terminal",
        session_id=session_id,
        user_id=current_user.id,
    ).info(f"PTY 会话已关闭: {session_id}")

    return {"ok": True}


@router.get("/sessions/pty/{session_id}/snapshot")
async def get_pty_snapshot(
    session_id: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    返回 PTY 会话的屏幕快照（仅会话所有者可访问）。

    Returns:
        {"grid": [[...]], "cols": int, "rows": int}
    """
    session = _pty_sessions.get(session_id)
    if session is None or not session.active:
        raise HTTPException(status_code=404, detail="PTY 会话不存在或已关闭")

    # IDOR 校验：仅会话所有者可访问
    if getattr(session, "owner_user_id", None) != str(current_user.id):
        raise HTTPException(status_code=403, detail="无权访问该会话")

    snapshot = session.get_snapshot()
    return {
        "ok": True,
        "grid": snapshot["grid"],
        "cols": snapshot["cols"],
        "rows": snapshot["rows"],
    }


# 兼容路径：spec 11.4 路径，PTY 会话不存在时返回 404
@router.get("/sessions/{session_id}/snapshot")
async def get_session_snapshot(
    session_id: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    返回终端会话的屏幕快照（兼容路径，仅会话所有者可访问）。

    优先在 PTY 会话中查找；若不存在则返回 404。
    """
    session = _pty_sessions.get(session_id)
    if session is None or not session.active:
        raise HTTPException(status_code=404, detail="会话不存在或已关闭")

    # IDOR 校验：仅会话所有者可访问
    if getattr(session, "owner_user_id", None) != str(current_user.id):
        raise HTTPException(status_code=403, detail="无权访问该会话")

    snapshot = session.get_snapshot()
    return {
        "ok": True,
        "grid": snapshot["grid"],
        "cols": snapshot["cols"],
        "rows": snapshot["rows"],
    }


@router.websocket("/ws/pty/{session_id}")
async def terminal_pty_websocket(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(default=None, description="JWT 访问令牌"),
):
    """
    PTY 持久化终端 WebSocket 端点。

    协议：
    - 客户端发送：{"type":"input","data":"..."} 或 {"type":"resize","cols":80,"rows":24}
    - 服务端推送：
        {"type":"shell_info","shell":"bash"}
        {"type":"scrollback","lines":[...]}
        {"type":"snapshot","grid":[...]}
        {"type":"output","data":"..."}
        {"type":"resize_ack","cols":80,"rows":24}
        {"type":"closed"}
        {"type":"error","message":"..."}
        {"type":"command_blocked","command":"...","message":"..."}
    """
    # Origin 校验（防 CSWSH 跨站 WebSocket 劫持）：在 accept 之前 close
    origin = websocket.headers.get("origin", "")
    if not validate_ws_origin(origin):
        await websocket.close(code=4003, reason="Origin not allowed")
        return

    # token 解析：优先取 query 参数，缺失时尝试从 Sec-WebSocket-Protocol 子协议提取
    subprotocol: Optional[str] = None
    if not token:
        token, subprotocol = extract_token_from_subprotocol(websocket)

    # 鉴权
    if not token:
        await websocket.accept(subprotocol=subprotocol if subprotocol else None)
        await websocket.send_json({"type": "error", "message": "缺少认证 token"})
        await websocket.close(code=4001, reason="Missing authentication token")
        return

    payload = decode_access_token(token)
    if payload is None:
        await websocket.accept(subprotocol=subprotocol if subprotocol else None)
        await websocket.send_json({"type": "error", "message": "token 无效或已过期"})
        await websocket.close(code=4002, reason="Invalid or expired token")
        return

    username = payload.get("sub")
    if not isinstance(username, str):
        await websocket.accept(subprotocol=subprotocol if subprotocol else None)
        await websocket.send_json({"type": "error", "message": "token 载荷无效"})
        await websocket.close(code=4003, reason="Invalid token payload")
        return

    try:
        user = await asyncio.to_thread(_ws_load_user_by_name, username)
    except Exception as e:
        logger.bind(
            event="terminal_ws_db_error",
            module="terminal",
            action="pty_websocket",
            error_type=type(e).__name__,
        ).error("terminal pty websocket db query failed")
        await websocket.accept(subprotocol=subprotocol if subprotocol else None)
        await websocket.send_json({"type": "error", "message": "数据库查询失败"})
        await websocket.close(code=4004, reason="Database error")
        return

    if user is None:
        await websocket.accept(subprotocol=subprotocol if subprotocol else None)
        await websocket.send_json({"type": "error", "message": "用户不存在"})
        await websocket.close(code=4004, reason="User not found")
        return

    await websocket.accept(subprotocol=subprotocol if subprotocol else None)

    session = _pty_sessions.get(session_id)
    if session is None or not session.active:
        await websocket.send_json({"type": "error", "message": "PTY 会话不存在或已关闭"})
        await websocket.close()
        return

    # IDOR 校验：仅会话所有者可访问
    if getattr(session, "owner_user_id", None) != str(user.id):
        await websocket.send_json({"type": "error", "message": "无权访问该会话"})
        await websocket.close(code=4003, reason="Forbidden")
        return

    logger.bind(
        event="pty_ws_connected",
        module="terminal",
        session_id=session_id,
        user_id=user.id,
    ).info(f"PTY WebSocket 已连接: {session_id}")

    # 推送 shell_info
    await websocket.send_json({
        "type": "shell_info",
        "shell": session.command[0] if session.command else "",
    })

    # 推送 scrollback（最近 100 行）
    scrollback_lines = session.get_scrollback(limit=100)
    await websocket.send_json({"type": "scrollback", "lines": scrollback_lines})

    # 推送当前屏幕快照
    snapshot = session.get_snapshot()
    await websocket.send_json({
        "type": "snapshot",
        "grid": snapshot["grid"],
        "cols": snapshot["cols"],
        "rows": snapshot["rows"],
    })

    # 订阅输出
    subscriber = session.subscribe()

    async def _read_incoming() -> None:
        """读取客户端输入消息并转发到 PTY。"""
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                raise
            except Exception:
                # 解析失败的 JSON 视为断开
                raise WebSocketDisconnect()

            msg_type = data.get("type")
            if msg_type == "input":
                input_data = data.get("data", "")
                if not isinstance(input_data, str):
                    await websocket.send_json({
                        "type": "error",
                        "message": "input 数据必须为字符串",
                    })
                    continue
                result = await session.write_input(input_data)
                if not result.get("ok"):
                    # 命令被拦截
                    await websocket.send_json({
                        "type": "command_blocked",
                        "command": result.get("command", ""),
                        "message": result.get("error", "命令被安全策略拒绝"),
                    })
            elif msg_type == "resize":
                cols = int(data.get("cols", 80))
                rows = int(data.get("rows", 24))
                try:
                    await session.resize(cols, rows)
                    await websocket.send_json({
                        "type": "resize_ack",
                        "cols": cols,
                        "rows": rows,
                    })
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"调整大小失败: {str(e)}",
                    })
            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"未知消息类型: {msg_type}",
                })

    async def _push_output() -> None:
        """从订阅队列读取输出并推送给客户端。"""
        while True:
            try:
                message = await subscriber.get()
            except asyncio.CancelledError:
                raise
            try:
                await websocket.send_json(message)
            except Exception:
                # 客户端可能已断开
                raise

    # 同时处理输入与输出
    incoming_task = asyncio.create_task(_read_incoming())
    output_task = asyncio.create_task(_push_output())

    try:
        # 等待任一任务完成（断开/异常）
        done, pending = await asyncio.wait(
            {incoming_task, output_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
    except WebSocketDisconnect:
        logger.bind(
            event="pty_ws_disconnected",
            module="terminal",
            session_id=session_id,
            user_id=user.id,
        ).info(f"PTY WebSocket 断开: {session_id}")
    except Exception as e:
        logger.bind(
            event="pty_ws_error",
            module="terminal",
            session_id=session_id,
            user_id=user.id,
            error_type=type(e).__name__,
            error_message=str(e),
        ).error(f"PTY WebSocket 错误: {e}")
    finally:
        # 取消未完成的任务
        for task in (incoming_task, output_task):
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        # 取消订阅（PTY 会话保留，支持断线重连）
        session.unsubscribe(subscriber)
        logger.bind(
            event="pty_ws_closed",
            module="terminal",
            session_id=session_id,
            user_id=user.id,
        ).info(f"PTY WebSocket 已关闭: {session_id}")



@router.post("/sessions")
async def create_session(
    cwd: Optional[str] = Query(default=None, description="工作目录"),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """创建新的终端会话。需要认证。"""
    # 校验 cwd 路径安全性
    safe_cwd = _validate_cwd(cwd)

    # 清理已关闭的会话
    closed = [sid for sid, s in _terminal_sessions.items() if not s.active]
    for sid in closed:
        _terminal_sessions.pop(sid, None)

    # per-user 会话数限制（防止单用户耗尽全局配额）
    owner_id = str(current_user.id)
    if _count_user_sessions(_terminal_sessions, owner_id) >= MAX_SESSIONS:
        return {"ok": False, "error": "已达到最大会话数限制"}

    session_id = str(uuid.uuid4())[:8]
    session = TerminalSession(session_id, safe_cwd, owner_user_id=owner_id)
    _add_session(_terminal_sessions, session_id, session, owner_id, MAX_SESSIONS)

    logger.bind(
        event="terminal_session_created",
        module="terminal",
        session_id=session_id,
        cwd=session.cwd,
        user_id=current_user.id,
    ).info(f"终端会话已创建: {session_id}")

    return {"ok": True, "session_id": session_id, "cwd": session.cwd}


@router.post("/sessions/{session_id}/execute")
async def execute_command(
    session_id: str,
    request: TerminalCommandRequest,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """在指定会话中执行命令。需要认证（仅会话所有者可执行）。"""
    session = _terminal_sessions.get(session_id)
    if not session or not session.active:
        return {"ok": False, "error": "会话不存在或已关闭"}

    # IDOR 校验：仅会话所有者可执行命令
    if getattr(session, "owner_user_id", None) != str(current_user.id):
        raise HTTPException(status_code=403, detail="无权访问该会话")

    result = await session.execute(request.command, request.timeout)

    logger.bind(
        event="terminal_command_executed",
        module="terminal",
        session_id=session_id,
        command=request.command[:100],
        ok=result.get("ok"),
        user_id=current_user.id,
    ).info(f"终端命令执行: {request.command[:50]}...")

    return result


@router.delete("/sessions/{session_id}")
async def close_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """关闭终端会话。需要认证（仅会话所有者可关闭）。"""
    session = _terminal_sessions.get(session_id)
    if not session:
        return {"ok": False, "error": "会话不存在"}

    # IDOR 校验：仅会话所有者可关闭
    if getattr(session, "owner_user_id", None) != str(current_user.id):
        raise HTTPException(status_code=403, detail="无权访问该会话")

    await session.close()
    _terminal_sessions.pop(session_id, None)

    logger.bind(
        event="terminal_session_closed",
        module="terminal",
        session_id=session_id,
        user_id=current_user.id,
    ).info(f"终端会话已关闭: {session_id}")

    return {"ok": True}


@router.get("/sessions")
async def list_sessions(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """列出当前用户所有活跃的终端会话（按 owner_user_id 过滤）。"""
    owner_id = str(current_user.id)
    return {
        "ok": True,
        "sessions": [
            {
                "session_id": sid,
                "cwd": s.cwd,
                "active": s.active,
            }
            for sid, s in _terminal_sessions.items()
            if s.active and getattr(s, "owner_user_id", None) == owner_id
        ],
    }


@router.websocket("/ws/{session_id}")
async def terminal_websocket(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(default=None, description="JWT 访问令牌"),
):
    """
    终端 WebSocket 连接，支持实时命令执行和输出流。
    通过 token 查询参数或 Sec-WebSocket-Protocol 子协议鉴权，
    未认证或令牌无效时直接关闭连接。
    """
    # Origin 校验（防 CSWSH 跨站 WebSocket 劫持）：在 accept 之前 close
    origin = websocket.headers.get("origin", "")
    if not validate_ws_origin(origin):
        await websocket.close(code=4003, reason="Origin not allowed")
        return

    # token 解析：优先取 query 参数，缺失时尝试从 Sec-WebSocket-Protocol 子协议提取
    subprotocol: Optional[str] = None
    if not token:
        token, subprotocol = extract_token_from_subprotocol(websocket)

    # 鉴权：token 必须存在且可解析为有效用户
    if not token:
        await websocket.accept(subprotocol=subprotocol if subprotocol else None)
        await websocket.send_json({"type": "error", "message": "缺少认证 token"})
        await websocket.close(code=4001, reason="Missing authentication token")
        return

    payload = decode_access_token(token)
    if payload is None:
        await websocket.accept(subprotocol=subprotocol if subprotocol else None)
        await websocket.send_json({"type": "error", "message": "token 无效或已过期"})
        await websocket.close(code=4002, reason="Invalid or expired token")
        return

    username = payload.get("sub")
    if not isinstance(username, str):
        await websocket.accept(subprotocol=subprotocol if subprotocol else None)
        await websocket.send_json({"type": "error", "message": "token 载荷无效"})
        await websocket.close(code=4003, reason="Invalid token payload")
        return

    try:
        user = await asyncio.to_thread(_ws_load_user_by_name, username)
    except Exception as e:
        logger.bind(
            event="terminal_ws_db_error",
            module="terminal",
            action="websocket",
            error_type=type(e).__name__,
        ).error("terminal websocket db query failed")
        await websocket.accept(subprotocol=subprotocol if subprotocol else None)
        await websocket.send_json({"type": "error", "message": "数据库查询失败"})
        await websocket.close(code=4004, reason="Database error")
        return

    if user is None:
        await websocket.accept(subprotocol=subprotocol if subprotocol else None)
        await websocket.send_json({"type": "error", "message": "用户不存在"})
        await websocket.close(code=4004, reason="User not found")
        return

    await websocket.accept(subprotocol=subprotocol if subprotocol else None)

    session = _terminal_sessions.get(session_id)
    if not session:
        await websocket.send_json({"type": "error", "message": "会话不存在"})
        await websocket.close()
        return

    # IDOR 校验：仅会话所有者可访问
    if getattr(session, "owner_user_id", None) != str(user.id):
        await websocket.send_json({"type": "error", "message": "无权访问该会话"})
        await websocket.close(code=4003, reason="Forbidden")
        return

    logger.bind(
        event="terminal_ws_connected",
        module="terminal",
        session_id=session_id,
        user_id=user.id,
    ).info(f"终端 WebSocket 已连接: {session_id}")

    try:
        while True:
            data = await websocket.receive_json()
            command = data.get("command", "")
            timeout = data.get("timeout", DEFAULT_TIMEOUT)

            if not command:
                await websocket.send_json({"type": "error", "message": "空命令"})
                continue

            await websocket.send_json({"type": "command", "command": command})

            result = await session.execute(command, timeout)

            await websocket.send_json({
                "type": "output",
                "stdout": result.get("stdout", ""),
                "stderr": result.get("stderr", ""),
                "exit_code": result.get("exit_code"),
                "ok": result.get("ok"),
            })

    except WebSocketDisconnect:
        logger.bind(
            event="terminal_ws_disconnected",
            module="terminal",
            session_id=session_id,
            user_id=user.id,
        ).info(f"终端 WebSocket 断开: {session_id}")
    except Exception as e:
        logger.bind(
            event="terminal_ws_error",
            module="terminal",
            session_id=session_id,
            user_id=user.id,
            error_type=type(e).__name__,
            error_message=str(e),
        ).error(f"终端 WebSocket 错误: {e}")
    finally:
        await session.close()
        _terminal_sessions.pop(session_id, None)

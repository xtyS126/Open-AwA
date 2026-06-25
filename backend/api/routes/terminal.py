"""
终端 WebSocket API，为前端 IDE 提供实时终端会话。
支持创建会话、执行命令、流式输出和会话管理。

安全策略：
1. 所有 HTTP 端点强制鉴权（Depends(get_current_user)）
2. WebSocket 端点通过 token 查询参数鉴权
3. 命令执行前过滤危险命令、高危路径、危险模式
4. cwd 参数必须位于允许的工作区根目录内
"""

import asyncio
import os
import re
import shlex
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel, Field

from api.dependencies import get_current_user
from config.security import decode_access_token
from db.models import SessionLocal, User

router = APIRouter(prefix="/terminal", tags=["terminal"])


# 终端会话管理
_terminal_sessions: Dict[str, "TerminalSession"] = {}

# 安全限制
MAX_SESSIONS = 10
MAX_OUTPUT_LENGTH = 50000
DEFAULT_TIMEOUT = 30

# 允许作为 cwd 的根目录白名单（默认为当前工作目录与其下级子目录）
_ALLOWED_WORKSPACE_ROOTS: List[str] = [os.path.abspath(os.getcwd())]

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
]


def _is_command_safe(command: str) -> bool:
    """
    检查命令是否安全。
    多层检查：危险命令名 + 高危路径 + 危险正则模式。
    """
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

    def __init__(self, session_id: str, cwd: str = None):
        self.session_id = session_id
        self.cwd = cwd or os.getcwd()
        self.process: Optional[asyncio.subprocess.Process] = None
        self.active = True
        self.env = os.environ.copy()

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
                await self.process.wait()
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
                await self.process.wait()
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


@router.post("/sessions")
async def create_session(
    cwd: Optional[str] = Query(default=None, description="工作目录"),
    current_user: User = Depends(get_current_user),
):
    """创建新的终端会话。需要认证。"""
    # 校验 cwd 路径安全性
    safe_cwd = _validate_cwd(cwd)

    if len(_terminal_sessions) >= MAX_SESSIONS:
        # 清理已关闭的会话
        closed = [sid for sid, s in _terminal_sessions.items() if not s.active]
        for sid in closed:
            del _terminal_sessions[sid]
        if len(_terminal_sessions) >= MAX_SESSIONS:
            return {"ok": False, "error": "已达到最大会话数限制"}

    session_id = str(uuid.uuid4())[:8]
    session = TerminalSession(session_id, safe_cwd)
    _terminal_sessions[session_id] = session

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
):
    """在指定会话中执行命令。需要认证。"""
    session = _terminal_sessions.get(session_id)
    if not session or not session.active:
        return {"ok": False, "error": "会话不存在或已关闭"}

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
):
    """关闭终端会话。需要认证。"""
    session = _terminal_sessions.get(session_id)
    if not session:
        return {"ok": False, "error": "会话不存在"}

    await session.close()
    del _terminal_sessions[session_id]

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
):
    """列出所有活跃的终端会话。需要认证。"""
    return {
        "ok": True,
        "sessions": [
            {
                "session_id": sid,
                "cwd": s.cwd,
                "active": s.active,
            }
            for sid, s in _terminal_sessions.items()
            if s.active
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
    通过 token 查询参数鉴权，未认证或令牌无效时直接关闭连接。
    """
    # 鉴权：token 必须存在且可解析为有效用户
    if not token:
        await websocket.accept()
        await websocket.send_json({"type": "error", "message": "缺少认证 token"})
        await websocket.close(code=4001, reason="Missing authentication token")
        return

    payload = decode_access_token(token)
    if payload is None:
        await websocket.accept()
        await websocket.send_json({"type": "error", "message": "token 无效或已过期"})
        await websocket.close(code=4002, reason="Invalid or expired token")
        return

    username = payload.get("sub")
    if not isinstance(username, str):
        await websocket.accept()
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
        await websocket.accept()
        await websocket.send_json({"type": "error", "message": "数据库查询失败"})
        await websocket.close(code=4004, reason="Database error")
        return

    if user is None:
        await websocket.accept()
        await websocket.send_json({"type": "error", "message": "用户不存在"})
        await websocket.close(code=4004, reason="User not found")
        return

    await websocket.accept()

    session = _terminal_sessions.get(session_id)
    if not session:
        await websocket.send_json({"type": "error", "message": "会话不存在"})
        await websocket.close()
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

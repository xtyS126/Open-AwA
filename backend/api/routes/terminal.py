"""
终端 WebSocket API，为前端 IDE 提供实时终端会话。
支持创建会话、执行命令、流式输出和会话管理。
"""

import asyncio
import os
import shlex
import uuid
from typing import Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from loguru import logger
from pydantic import BaseModel, Field

router = APIRouter(prefix="/terminal", tags=["terminal"])


# 终端会话管理
_terminal_sessions: Dict[str, "TerminalSession"] = {}

# 安全限制
MAX_SESSIONS = 10
MAX_OUTPUT_LENGTH = 50000
DEFAULT_TIMEOUT = 30


class TerminalSession:
    """终端会话，管理子进程和输出流。"""

    def __init__(self, session_id: str, cwd: str = None):
        self.session_id = session_id
        self.cwd = cwd or os.getcwd()
        self.process: Optional[asyncio.subprocess.Process] = None
        self.active = True
        self.env = os.environ.copy()

    async def execute(self, command: str, timeout: int = DEFAULT_TIMEOUT) -> Dict[str, any]:
        """执行命令并返回输出。"""
        try:
            # 安全检查：使用 shlex 分割参数，不使用 shell=True
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
            return {"ok": False, "error": f"执行失败: {str(e)}"}

    async def close(self) -> None:
        """关闭会话，终止正在运行的进程。"""
        self.active = False
        if self.process and self.process.returncode is None:
            try:
                self.process.kill()
                await self.process.wait()
            except Exception:
                pass


class TerminalCommandRequest(BaseModel):
    """终端命令请求。"""
    command: str = Field(..., description="要执行的命令")
    timeout: int = Field(default=DEFAULT_TIMEOUT, ge=1, le=300, description="超时秒数")


@router.post("/sessions")
async def create_session(
    cwd: Optional[str] = Query(default=None, description="工作目录"),
):
    """创建新的终端会话。"""
    if len(_terminal_sessions) >= MAX_SESSIONS:
        # 清理已关闭的会话
        closed = [sid for sid, s in _terminal_sessions.items() if not s.active]
        for sid in closed:
            del _terminal_sessions[sid]
        if len(_terminal_sessions) >= MAX_SESSIONS:
            return {"ok": False, "error": "已达到最大会话数限制"}

    session_id = str(uuid.uuid4())[:8]
    session = TerminalSession(session_id, cwd)
    _terminal_sessions[session_id] = session

    logger.bind(
        event="terminal_session_created",
        module="terminal",
        session_id=session_id,
        cwd=session.cwd,
    ).info(f"终端会话已创建: {session_id}")

    return {"ok": True, "session_id": session_id, "cwd": session.cwd}


@router.post("/sessions/{session_id}/execute")
async def execute_command(
    session_id: str,
    request: TerminalCommandRequest,
):
    """在指定会话中执行命令。"""
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
    ).info(f"终端命令执行: {request.command[:50]}...")

    return result


@router.delete("/sessions/{session_id}")
async def close_session(session_id: str):
    """关闭终端会话。"""
    session = _terminal_sessions.get(session_id)
    if not session:
        return {"ok": False, "error": "会话不存在"}

    await session.close()
    del _terminal_sessions[session_id]

    logger.bind(
        event="terminal_session_closed",
        module="terminal",
        session_id=session_id,
    ).info(f"终端会话已关闭: {session_id}")

    return {"ok": True}


@router.get("/sessions")
async def list_sessions():
    """列出所有活跃的终端会话。"""
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
async def terminal_websocket(websocket: WebSocket, session_id: str):
    """终端 WebSocket 连接，支持实时命令执行和输出流。"""
    await websocket.accept()

    session = _terminal_sessions.get(session_id)
    if not session:
        await websocket.send_json({"type": "error", "message": "会话不存在"})
        await websocket.close()
        return

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
        ).info(f"终端 WebSocket 断开: {session_id}")
    except Exception as e:
        logger.bind(
            event="terminal_ws_error",
            module="terminal",
            session_id=session_id,
            error=str(e),
        ).error(f"终端 WebSocket 错误: {e}")
    finally:
        await session.close()
        _terminal_sessions.pop(session_id, None)

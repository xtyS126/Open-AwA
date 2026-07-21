"""
跨平台 PTY 会话抽象。

Windows 平台使用 pywinpty（仅 Windows 需要安装），POSIX 平台使用标准库 pty + asyncio。
PTYSession 维护 PTY 子进程、pyte 屏幕仿真器与读取协程。

VT100/VT220/VT320 终端序列解析委托给 pyte 库（HistoryScreen + Stream），
支持完整 CSI/SGR/DECSC/DECRC/256色/真彩色序列，可正确渲染 vim/tmux/htop 等复杂 TUI。
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Callable, Dict, List, Optional, Tuple

import pyte
from loguru import logger

# 跨平台判定
_is_windows: bool = sys.platform == "win32"

# 单次读取的缓冲区大小
_READ_BUFFER_SIZE = 4096

# pyte HistoryScreen 默认滚动历史保留行数
_DEFAULT_SCROLLBACK_LIMIT = 1000


class PTYSession:
    """跨平台 PTY 会话，结合 VT 屏幕仿真器实现断线重连与屏幕恢复。"""

    def __init__(
        self,
        command: List[str],
        cwd: str,
        env: Optional[Dict[str, str]] = None,
        cols: int = 80,
        rows: int = 24,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        初始化 PTY 会话。

        Args:
            command: 启动命令（已按 shlex 切分），如 ["/bin/bash"] 或 ["cmd.exe"]。
            cwd: 子进程工作目录。
            env: 子进程环境变量；None 表示继承当前进程。
            cols: 终端列数。
            rows: 终端行数。
            on_output: 可选的输出回调；每次从 PTY 读取到数据后会被调用，
                参数为解码后的字符串。回调同步执行，应避免阻塞。
        """
        if not command:
            raise ValueError("command 不能为空")
        self.command: List[str] = list(command)
        self.cwd: str = cwd or os.getcwd()
        # 安全防护：过滤敏感环境变量，防止用户通过 printenv/env/echo $VAR 读取密钥
        # env 参数为 None 时使用过滤后的父进程环境；显式 env 视为可信覆盖
        if env is not None:
            self.env: Dict[str, str] = dict(env)
        else:
            from core.terminal.env_sanitizer import build_safe_env
            self.env = build_safe_env()
        self.cols: int = max(1, cols)
        self.rows: int = max(1, rows)

        # pyte 屏幕仿真器：HistoryScreen 自带滚动历史（history.top 为 deque）
        # 保留 vt_screen 属性名以维持向后兼容（部分测试 mock 直接访问该属性）
        self.vt_screen: pyte.HistoryScreen = pyte.HistoryScreen(
            columns=self.cols,
            lines=self.rows,
            history=_DEFAULT_SCROLLBACK_LIMIT,
        )
        # Stream 绑定到 Screen，调用 feed(data) 解析 ANSI 流并更新屏幕
        self._stream: pyte.Stream = pyte.Stream(self.vt_screen)

        # 子进程句柄（POSIX）或 PtyProcess（Windows）
        self.process: Optional[asyncio.subprocess.Process] = None
        self._winpty_proc = None  # type: ignore[assignment]
        self._master_fd: Optional[int] = None

        # 读取协程
        self._reader_task: Optional[asyncio.Task] = None

        # 输出回调
        self._on_output: Optional[Callable[[str], None]] = on_output

        # 运行状态
        self._closed: bool = False
        self._started: bool = False

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """
        启动 PTY 子进程与读取协程。

        Raises:
            RuntimeError: 重复启动或启动失败时抛出。
        """
        if self._started:
            raise RuntimeError("PTYSession 已启动")
        self._started = True

        try:
            if _is_windows:
                await self._start_winpty()
            else:
                await self._start_posix()
        except Exception:
            # 启动失败时清理半初始化的状态
            self._started = False
            raise

        # 启动读取协程
        self._reader_task = asyncio.create_task(self._reader_loop())

    async def _start_posix(self) -> None:
        """POSIX 平台启动 PTY 子进程。"""
        import pty  # 标准库

        master_fd, slave_fd = pty.openpty()
        self._master_fd = master_fd

        # 设置初始窗口大小
        self._set_winsize_posix(master_fd, self.rows, self.cols)

        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=self.cwd,
                env=self.env,
                close_fds=True,
            )
        finally:
            # 子进程已 fork 出来，关闭 slave 端
            os.close(slave_fd)

    async def _start_winpty(self) -> None:
        """Windows 平台启动 pywinpty 子进程。"""
        try:
            from winpty import PtyProcess  # type: ignore[import]
        except ImportError as e:
            raise RuntimeError(
                "Windows 平台需要安装 pywinpty（pip install pywinpty）"
            ) from e

        # pywinpty 的 spawn 不接受 cols/rows 参数，需在 spawn 后调用 set_size
        self._winpty_proc = PtyProcess.spawn(
            self.command,
            cwd=self.cwd,
            env=self.env,
        )
        # 设置初始终端尺寸
        try:
            self._winpty_proc.set_size(self.cols, self.rows)
        except Exception as exc:
            # 部分版本可能不支持 set_size，忽略即可，记录 debug 便于排查
            logger.debug(f"[pty_session] winpty set_size 不支持或失败: {exc}")

    async def _reader_loop(self) -> None:
        """读取协程：从 PTY 读取数据并写入 VT 屏幕，并调用输出回调。"""
        loop = asyncio.get_running_loop()

        try:
            while not self._closed:
                data_bytes = await self._read_once(loop)
                if not data_bytes:
                    # EOF：子进程已退出
                    break
                # 解码并喂给 pyte Stream 解析 ANSI 流
                data_str = data_bytes.decode("utf-8", errors="replace")
                self._stream.feed(data_str)
                # 触发输出回调（如已注册）
                if self._on_output is not None:
                    try:
                        self._on_output(data_str)
                    except Exception as e:
                        logger.bind(
                            event="pty_output_callback_error",
                            module="terminal",
                            error_type=type(e).__name__,
                            error_message=str(e),
                        ).warning(f"PTY 输出回调异常: {e}")
        except asyncio.CancelledError:
            # 被显式取消：正常退出
            raise
        except Exception as e:
            logger.bind(
                event="pty_reader_error",
                module="terminal",
                error_type=type(e).__name__,
                error_message=str(e),
            ).warning(f"PTY 读取循环异常: {e}")

    async def _read_once(self, loop: asyncio.AbstractEventLoop) -> bytes:
        """读取一次数据，跨平台抽象。"""
        if _is_windows:
            return await self._read_winpty(loop)
        return await self._read_posix(loop)

    async def _read_posix(self, loop: asyncio.AbstractEventLoop) -> bytes:
        """POSIX 平台从 master_fd 读取。"""
        if self._master_fd is None:
            return b""
        try:
            data = await loop.run_in_executor(
                None, os.read, self._master_fd, _READ_BUFFER_SIZE
            )
            return data
        except OSError:
            # master_fd 已关闭
            return b""

    async def _read_winpty(self, loop: asyncio.AbstractEventLoop) -> bytes:
        """Windows 平台从 pywinpty 读取。"""
        if self._winpty_proc is None:
            return b""
        try:
            # pywinpty 的 read 在阻塞 IO 上工作；放到线程池中执行
            data = await loop.run_in_executor(
                None, self._winpty_proc.read, _READ_BUFFER_SIZE
            )
            # pywinpty 返回 str，需转回 bytes
            if isinstance(data, str):
                return data.encode("utf-8", errors="replace")
            return data
        except (OSError, EOFError):
            return b""

    # ------------------------------------------------------------------
    # 写入与调整大小
    # ------------------------------------------------------------------
    async def write(self, data: str) -> None:
        """
        向 PTY stdin 写入数据。

        Args:
            data: 待写入的字符串（UTF-8 编码）。
        """
        if self._closed:
            return
        data_bytes = data.encode("utf-8", errors="replace")
        if _is_windows:
            await self._write_winpty(data_bytes)
        else:
            await self._write_posix(data_bytes)

    async def _write_posix(self, data: bytes) -> None:
        """POSIX 平台写入 master_fd。"""
        if self._master_fd is None:
            return
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, os.write, self._master_fd, data)
        except OSError as e:
            logger.bind(
                event="pty_write_error",
                module="terminal",
                error_type=type(e).__name__,
            ).warning(f"PTY 写入失败: {e}")

    async def _write_winpty(self, data: bytes) -> None:
        """Windows 平台写入 pywinpty。"""
        if self._winpty_proc is None:
            return
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._winpty_proc.write, data)
        except (OSError, ValueError) as e:
            logger.bind(
                event="pty_write_error",
                module="terminal",
                error_type=type(e).__name__,
            ).warning(f"PTY 写入失败: {e}")

    async def resize(self, cols: int, rows: int) -> None:
        """调整 PTY 与 VT 屏幕大小。"""
        cols = max(1, cols)
        rows = max(1, rows)
        self.cols = cols
        self.rows = rows
        # pyte Screen.resize 第一个参数是 lines，第二个是 columns，必须用关键字参数
        self.vt_screen.resize(lines=rows, columns=cols)
        # 调整 PTY 窗口大小
        if _is_windows:
            await self._resize_winpty(cols, rows)
        else:
            await self._resize_posix(cols, rows)

    async def _resize_posix(self, cols: int, rows: int) -> None:
        """POSIX 平台调整窗口大小。"""
        if self._master_fd is None:
            return
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None, self._set_winsize_posix, self._master_fd, rows, cols
            )
        except OSError as e:
            logger.bind(
                event="pty_resize_error",
                module="terminal",
                error_type=type(e).__name__,
            ).warning(f"PTY 调整大小失败: {e}")

    async def _resize_winpty(self, cols: int, rows: int) -> None:
        """Windows 平台调整窗口大小。"""
        if self._winpty_proc is None:
            return
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None, self._winpty_proc.set_size, cols, rows
            )
        except (OSError, ValueError) as e:
            logger.bind(
                event="pty_resize_error",
                module="terminal",
                error_type=type(e).__name__,
            ).warning(f"PTY 调整大小失败: {e}")

    @staticmethod
    def _set_winsize_posix(fd: int, rows: int, cols: int) -> None:
        """设置 POSIX PTY 窗口大小（同步）。"""
        import struct
        import termios
        import fcntl  # 仅 POSIX 可用

        # struct winsize { unsigned short ws_row, ws_col, ws_xpixel, ws_ypixel }
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    def get_snapshot(self) -> List[List[str]]:
        """
        返回 VT 屏幕快照（二维字符网格）。

        pyte Screen.display 返回 List[str]（每行已 pad 到 columns 宽度），
        这里转为 List[List[str]] 以维持原接口签名。
        """
        return [list(line) for line in self.vt_screen.display]

    def get_scrollback(self, limit: int = 100) -> List[str]:
        """
        返回滚动历史（字符串列表）。

        pyte HistoryScreen.history.top 是 deque，每个元素是 {col: Char} 的行字典。
        缺列访问返回默认 Char(data=' ')，因此 join 后每行自动 pad 到 columns 宽度。
        """
        if limit <= 0:
            return []
        history_top = self.vt_screen.history.top
        # deque 末尾是最近滚出的行，按时间顺序取最近 limit 行
        total = len(history_top)
        start = max(0, total - limit)
        columns = self.vt_screen.columns
        result: List[str] = []
        for i in range(start, total):
            line = history_top[i]
            # line[i] 在缺列时返回默认 Char(data=' ')
            result.append("".join(line[c].data for c in range(columns)))
        return result

    def is_alive(self) -> bool:
        """子进程是否仍在运行。"""
        if _is_windows:
            if self._winpty_proc is None:
                return False
            try:
                # pywinpty 的 isalive 方法
                return bool(self._winpty_proc.isalive())
            except Exception:
                return False
        if self.process is None:
            return False
        return self.process.returncode is None

    # ------------------------------------------------------------------
    # 关闭
    # ------------------------------------------------------------------
    async def close(self) -> None:
        """关闭 PTY 会话：kill 子进程、取消读取协程、关闭 fd。"""
        if self._closed:
            return
        self._closed = True

        # 取消读取协程
        if self._reader_task is not None and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.bind(
                    event="pty_reader_cancel_error",
                    module="terminal",
                    error_type=type(e).__name__,
                ).debug(f"PTY 读取协程取消异常: {e}")
        self._reader_task = None

        # 关闭子进程
        if _is_windows:
            await self._close_winpty()
        else:
            await self._close_posix()

        self.process = None
        self._winpty_proc = None
        self._master_fd = None

    async def _close_posix(self) -> None:
        """POSIX 平台关闭子进程与 master_fd。"""
        if self.process is not None and self.process.returncode is None:
            try:
                self.process.kill()
                await asyncio.wait_for(self.process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                # 强制等待 2s 仍未退出，放弃等待
                pass
            except ProcessLookupError:
                # 进程已退出
                pass
            except Exception as e:
                logger.bind(
                    event="pty_kill_error",
                    module="terminal",
                    error_type=type(e).__name__,
                ).warning(f"PTY kill 子进程失败: {e}")

        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError as exc:
                # fd 已关闭或无效时忽略，记录 debug 便于排查
                logger.debug(f"[pty_session] 关闭 master_fd 失败: {exc}")

    async def _close_winpty(self) -> None:
        """Windows 平台关闭 pywinpty。"""
        if self._winpty_proc is None:
            return
        loop = asyncio.get_running_loop()
        try:
            # pywinpty 提供 terminate 方法
            await loop.run_in_executor(None, self._winpty_proc.terminate, 0)
        except Exception as e:
            logger.bind(
                event="pty_kill_error",
                module="terminal",
                error_type=type(e).__name__,
            ).warning(f"PTY terminate 子进程失败: {e}")


__all__ = ["PTYSession"]

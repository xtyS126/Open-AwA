"""
终端 PTY 持久化模块。

提供 VT100/ANSI 终端仿真器（VTScreen）和跨平台 PTY 会话（PTYSession）。
- VTScreen：解析 ANSI 转义序列，维护字符网格和滚动历史
- PTYSession：跨平台 PTY 子进程抽象，Windows 用 pywinpty，POSIX 用 asyncio + pty
"""

from core.terminal.pty_session import PTYSession
from core.terminal.vt_screen import VTScreen

__all__ = ["VTScreen", "PTYSession"]

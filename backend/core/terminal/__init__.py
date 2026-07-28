"""
终端 PTY 持久化模块。

提供跨平台 PTY 会话（PTYSession），结合 pyte 库实现完整 VT100/VT220/VT320 终端序列解析。
- PTYSession：跨平台 PTY 子进程抽象，Windows 用 pywinpty，POSIX 用 asyncio + pty
- 终端序列解析委托给 pyte.HistoryScreen + pyte.Stream，支持 vim/tmux/htop 等复杂 TUI
"""

from core.terminal.pty_session import PTYSession

__all__ = ["PTYSession"]

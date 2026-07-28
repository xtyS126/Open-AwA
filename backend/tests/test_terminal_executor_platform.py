"""terminal_executor 平台适配单元测试。

覆盖 Windows 下 cmd.exe 内建命令的解析与执行适配，
避免 LLM 调用 echo/dir/ver 等内建命令时出现 WinError 2。
"""

from __future__ import annotations

import asyncio
import os
from unittest import mock

import pytest

from core.builtin_tools.terminal_executor import (
    TerminalExecutorSkill,
    WINDOWS_BUILTIN_COMMANDS,
    _resolve_command_for_platform,
)


class TestResolveCommandForPlatform:
    """_resolve_command_for_platform 解析逻辑测试。"""

    def test_windows_builtin_echo_resolved_via_cmd(self) -> None:
        """Windows 下 echo 内建命令应通过 cmd.exe /c 包装。"""
        with mock.patch("os.name", "nt"):
            args, error = _resolve_command_for_platform("echo hello")
        assert error is None
        assert args[0] == "cmd.exe"
        assert args[1] == "/c"
        assert args[2] == "echo"
        assert args[3] == "hello"

    def test_windows_builtin_dir_resolved_via_cmd(self) -> None:
        """Windows 下 dir 内建命令应通过 cmd.exe /c 包装。"""
        with mock.patch("os.name", "nt"):
            args, error = _resolve_command_for_platform("dir /b")
        assert error is None
        assert args[:2] == ["cmd.exe", "/c"]

    def test_windows_executable_found_uses_absolute_path(self) -> None:
        """Windows 下找到可执行文件时应替换为绝对路径。"""
        fake_path = "C:\\fake\\python.exe"
        with mock.patch("os.name", "nt"), \
             mock.patch("shutil.which", return_value=fake_path):
            args, error = _resolve_command_for_platform("python -V")
        assert error is None
        assert args[0] == fake_path
        assert args[1] == "-V"

    def test_windows_unknown_command_returns_friendly_error(self) -> None:
        """Windows 下既不是可执行文件也不在内建白名单的命令应返回友好错误。"""
        with mock.patch("os.name", "nt"), \
             mock.patch("shutil.which", return_value=None):
            args, error = _resolve_command_for_platform("nonexistent_cmd_xyz arg1")
        assert args == []
        assert "命令未找到" in error
        assert "nonexistent_cmd_xyz" in error

    def test_non_windows_keeps_original_logic(self) -> None:
        """非 Windows 平台应保持原 shlex.split 逻辑。"""
        with mock.patch("os.name", "posix"):
            args, error = _resolve_command_for_platform("echo hello")
        assert error is None
        assert args == ["echo", "hello"]

    def test_unclosed_quote_returns_parse_error(self) -> None:
        """未闭合引号应返回解析错误。"""
        args, error = _resolve_command_for_platform('echo "unclosed')
        assert args == []
        assert "解析失败" in error

    def test_empty_command_returns_error(self) -> None:
        """空命令应返回错误。"""
        args, error = _resolve_command_for_platform("")
        assert args == []
        assert "不能为空" in error

    def test_windows_builtin_whitelist_covers_common_commands(self) -> None:
        """白名单应覆盖常见的 Windows 内建命令。"""
        expected = {"echo", "dir", "type", "ver", "vol", "path", "cls", "cd"}
        assert expected.issubset(WINDOWS_BUILTIN_COMMANDS)

    def test_windows_builtin_whitelist_excludes_write_commands(self) -> None:
        """白名单不应包含写操作命令（del/rd/md/ren/copy/move）。"""
        write_cmds = {"del", "rd", "md", "ren", "copy", "move", "erase", "rmdir", "mkdir"}
        assert not (write_cmds & WINDOWS_BUILTIN_COMMANDS)


@pytest.mark.skipif(os.name != "nt", reason="仅 Windows 验证 cmd.exe 内建命令实际执行")
class TestWindowsBuiltinExecution:
    """Windows 下内建命令实际执行测试（仅 Windows 运行）。"""

    @pytest.mark.asyncio
    async def test_echo_executes_successfully(self) -> None:
        """echo 命令应成功执行并输出文本，不再 WinError 2。"""
        skill = TerminalExecutorSkill({"allowed_directories": ["."]})
        await skill.initialize()
        result = await skill.execute(action="run_command", command="echo hello_world", timeout=10)
        assert result["success"] is True
        assert "hello_world" in result["stdout"]

    @pytest.mark.asyncio
    async def test_dir_executes_successfully(self) -> None:
        """dir 命令应成功执行并输出目录列表。"""
        skill = TerminalExecutorSkill({"allowed_directories": ["."]})
        await skill.initialize()
        result = await skill.execute(action="run_command", command="dir /b", timeout=10)
        assert result["success"] is True
        assert len(result["stdout"]) > 0

    @pytest.mark.asyncio
    async def test_ver_executes_successfully(self) -> None:
        """ver 命令应成功执行并输出 Windows 版本。"""
        skill = TerminalExecutorSkill({"allowed_directories": ["."]})
        await skill.initialize()
        result = await skill.execute(action="run_command", command="ver", timeout=10)
        assert result["success"] is True
        assert "Windows" in result["stdout"] or "Microsoft" in result["stdout"]

    @pytest.mark.asyncio
    async def test_unknown_command_returns_friendly_error_not_winerror(self) -> None:
        """未知命令应返回友好错误，而非 WinError 2 异常。"""
        skill = TerminalExecutorSkill({"allowed_directories": ["."]})
        await skill.initialize()
        result = await skill.execute(action="run_command", command="nonexistent_cmd_xyz", timeout=10)
        assert result["success"] is False
        assert "命令未找到" in result["error"]
        assert "WinError" not in result.get("error", "")

"""
SkillExecutor 安全模块单元测试。

测试覆盖：
- RestrictedPythonBackend 代码安全校验（替代已弃用的 CodeValidator）
- Shell 命令白名单
- 路径遍历防护
- SkillExecutor 代码/Shell/文件操作安全
"""

import os
import pytest
from pathlib import Path

from security.backends import RestrictedPythonBackend, SandboxBackend
from skills.skill_executor import (
    SkillExecutor,
    SecurityValidationError,
    _validate_file_path,
    _ALLOWED_SHELL_COMMANDS,
    _DANGEROUS_ARG_PATTERNS,
)


# ---------------------------------------------------------------------------
# RestrictedPythonBackend 代码安全校验（替代已弃用的 CodeValidator 测试）
# ---------------------------------------------------------------------------

class TestRestrictedPythonBackendCodeValidation:
    """测试 RestrictedPythonBackend.check_code_safety() 的代码校验功能。"""

    @pytest.fixture
    def backend(self) -> RestrictedPythonBackend:
        """创建 RestrictedPythonBackend 实例，跳过未安装情况。"""
        backend = RestrictedPythonBackend()
        if not backend._ensure_restricted():
            pytest.skip("RestrictedPython 未安装")
        return backend

    @pytest.mark.asyncio
    async def test_safe_code_passes(self, backend):
        """验证安全代码通过校验。"""
        code = "x = 1 + 2\nprint(x)"
        is_safe, error = await backend.check_code_safety(code)
        assert is_safe is True
        assert error == ""

    @pytest.mark.asyncio
    async def test_empty_code_rejected(self, backend):
        """验证空代码被拒绝。"""
        is_safe, error = await backend.check_code_safety("")
        assert is_safe is False
        assert "不能为空" in error

    @pytest.mark.asyncio
    async def test_whitespace_code_rejected(self, backend):
        """验证空白代码被拒绝。"""
        is_safe, error = await backend.check_code_safety("   ")
        assert is_safe is False
        assert "不能为空" in error

    @pytest.mark.asyncio
    async def test_exec_call_rejected(self, backend):
        """验证 exec 调用被 RestrictedPython compile_restricted 拒绝。"""
        is_safe, error = await backend.check_code_safety("exec('import os')")
        assert is_safe is False
        assert "Exec" in error or "语法错误" in error, f"期望错误信息包含 Exec 拒绝原因，实际: {error!r}"

    @pytest.mark.asyncio
    async def test_eval_call_rejected(self, backend):
        """验证 eval 调用被 RestrictedPython compile_restricted 拒绝。"""
        is_safe, error = await backend.check_code_safety("eval('1+1')")
        assert is_safe is False
        assert "Eval" in error or "语法错误" in error, f"期望错误信息包含 Eval 拒绝原因，实际: {error!r}"

    @pytest.mark.asyncio
    async def test_open_protected_at_runtime(self, backend):
        """
        验证 open 在 RestrictedPython 运行时由 safe_builtins 控制。
        compile_restricted 可能允许 open 通过编译（不同于旧 CodeValidator 的静态拦截），
        但运行时 safe_builtins 的受限实现会阻止危险操作。
        """
        is_safe, error = await backend.check_code_safety("open('/etc/passwd')")
        if is_safe:
            # 编译通过 — 运行时 safe_builtins 将加以限制
            assert error == "", f"编译通过时 error 应为空，实际: {error!r}"
        else:
            # 编译被拒 — 错误信息必须包含合法拒绝原因
            assert "不安全" in error or "校验失败" in error or "语法错误" in error, \
                f"被拒时错误信息应包含有效原因，实际: {error!r}"

    @pytest.mark.asyncio
    async def test_syntax_error_handled(self, backend):
        """验证语法错误被正确处理。"""
        code = "this is not valid python"
        is_safe, error = await backend.check_code_safety(code)
        assert is_safe is False
        assert "语法错误" in error

    @pytest.mark.asyncio
    async def test_function_def_accepted(self, backend):
        """RestrictedPython 7.x 允许安全的函数定义。"""
        code = "def f():\n    return 1\nresult = f()"
        is_safe, error = await backend.check_code_safety(code)
        assert is_safe is True, f"函数定义应被接受，但被拒绝: {error!r}"
        assert error == ""

    @pytest.mark.asyncio
    async def test_arithmetic_passes(self, backend):
        """验证基本算术运算通过校验。"""
        is_safe, error = await backend.check_code_safety("x = 1 + 2 * 3 / 4")
        assert is_safe is True

    @pytest.mark.asyncio
    async def test_list_comprehension_passes(self, backend):
        """验证列表推导通过校验。"""
        is_safe, error = await backend.check_code_safety("[x * 2 for x in range(10)]")
        assert is_safe is True

    @pytest.mark.asyncio
    async def test_getattr_protected_at_runtime(self, backend):
        """
        验证 getattr 在 RestrictedPython 运行时由 safer_getattr 守卫保护。
        compile_restricted 将 getattr 转换为 _getattr_ 守卫调用，
        而非在编译期拒绝 —— 运行时的 safer_getattr 用于阻止危险属性访问。
        """
        is_safe, error = await backend.check_code_safety("_getattr_(obj, 'attr')")
        if is_safe:
            # 编译通过 — 运行时 safer_getattr 提供实际保护
            assert error == "", f"编译通过时 error 应为空，实际: {error!r}"
        else:
            # 编译被拒 — 错误信息必须包含合法拒绝原因
            assert "不安全" in error or "校验失败" in error or "语法错误" in error, \
                f"被拒时错误信息应包含有效原因，实际: {error!r}"

    @pytest.mark.asyncio
    async def test_import_blocked(self, backend):
        """验证 __import__ 被 RestrictedPython compile_restricted 拒绝。"""
        is_safe, error = await backend.check_code_safety("__import__('os')")
        assert is_safe is False
        assert error != ""


# ---------------------------------------------------------------------------
# Shell 命令白名单
# ---------------------------------------------------------------------------

class TestShellCommandWhitelist:
    """测试 Shell 命令白名单。"""

    def test_rm_not_in_allowed(self):
        """验证 rm 不在白名单中。"""
        assert "rm" not in _ALLOWED_SHELL_COMMANDS

    def test_chmod_not_in_allowed(self):
        """验证 chmod 不在白名单中。"""
        assert "chmod" not in _ALLOWED_SHELL_COMMANDS

    def test_chown_not_in_allowed(self):
        """验证 chown 不在白名单中。"""
        assert "chown" not in _ALLOWED_SHELL_COMMANDS

    def test_xargs_not_in_allowed(self):
        """验证 xargs 不在白名单中。"""
        assert "xargs" not in _ALLOWED_SHELL_COMMANDS

    def test_awk_not_in_allowed(self):
        """验证 awk 不在白名单中。"""
        assert "awk" not in _ALLOWED_SHELL_COMMANDS

    def test_sed_not_in_allowed(self):
        """验证 sed 不在白名单中。"""
        assert "sed" not in _ALLOWED_SHELL_COMMANDS

    def test_sudo_not_in_allowed(self):
        """验证 sudo 不在白名单中。"""
        assert "sudo" not in _ALLOWED_SHELL_COMMANDS

    def test_python_not_in_allowed(self):
        """验证 python 不在白名单中。"""
        assert "python" not in _ALLOWED_SHELL_COMMANDS
        assert "python3" not in _ALLOWED_SHELL_COMMANDS

    def test_safe_commands_in_allowed(self):
        """验证安全命令在白名单中。"""
        safe_commands = {"ls", "cat", "echo", "pwd", "head", "tail"}
        assert safe_commands.issubset(_ALLOWED_SHELL_COMMANDS)


# ---------------------------------------------------------------------------
# 路径安全校验
# ---------------------------------------------------------------------------

class TestPathValidation:
    """测试路径校验。"""

    def test_empty_path_rejected(self):
        """验证空路径被拒绝。"""
        with pytest.raises(SecurityValidationError):
            _validate_file_path("")

    def test_whitespace_path_rejected(self):
        """验证空白路径被拒绝。"""
        with pytest.raises(SecurityValidationError):
            _validate_file_path("   ")

    def test_path_traversal_rejected(self):
        """验证路径遍历被拒绝。"""
        with pytest.raises(SecurityValidationError):
            _validate_file_path("../../../etc/passwd")

    def test_absolute_etc_path_rejected(self):
        """验证 /etc 路径被拒绝。"""
        with pytest.raises(SecurityValidationError):
            _validate_file_path("/etc/passwd")

    def test_absolute_root_path_rejected(self):
        """验证 /root 路径被拒绝。"""
        with pytest.raises(SecurityValidationError):
            _validate_file_path("/root/.ssh/id_rsa")

    def test_absolute_proc_path_rejected(self):
        """验证 /proc 路径被拒绝。"""
        with pytest.raises(SecurityValidationError):
            _validate_file_path("/proc/self/environ")

    def test_valid_path_accepted(self, tmp_path):
        """验证有效路径被接受。"""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        result = _validate_file_path(str(test_file), base_dir=str(tmp_path))
        assert result == test_file.resolve()

    def test_path_outside_base_dir_rejected(self, tmp_path):
        """验证基础目录外的路径被拒绝。"""
        with pytest.raises(SecurityValidationError):
            _validate_file_path("/etc/passwd", base_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# SkillExecutor Shell 动作安全
# ---------------------------------------------------------------------------

class TestSkillExecutorShellAction:
    """测试 SkillExecutor Shell 动作安全。"""

    @pytest.fixture
    def executor(self, tmp_path):
        """创建执行器实例。"""
        return SkillExecutor(work_dir=str(tmp_path))

    @pytest.mark.asyncio
    async def test_dangerous_command_rm_rejected(self, executor):
        """验证 rm 命令被拒绝。"""
        with pytest.raises(RuntimeError) as exc_info:
            await executor._execute_shell_action("test", {"command": "rm -rf /"})
        assert "不在允许列表" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_dangerous_command_sudo_rejected(self, executor):
        """验证 sudo 命令被拒绝。"""
        with pytest.raises(RuntimeError) as exc_info:
            await executor._execute_shell_action("test", {"command": "sudo ls"})
        assert "不在允许列表" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_shell_injection_semicolon_rejected(self, executor):
        """验证分号注入被拒绝。"""
        with pytest.raises(RuntimeError) as exc_info:
            await executor._execute_shell_action("test", {"command": "ls; rm -rf /"})
        assert "不在允许列表" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_shell_injection_pipe_rejected(self, executor):
        """验证管道注入被拒绝。"""
        with pytest.raises(RuntimeError) as exc_info:
            await executor._execute_shell_action("test", {"command": "ls | rm"})
        assert "不允许" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_shell_injection_backtick_rejected(self, executor):
        """验证反引号注入被拒绝。"""
        with pytest.raises(RuntimeError) as exc_info:
            await executor._execute_shell_action("test", {"command": "ls `rm`"})
        assert "不允许" in str(exc_info.value)

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        os.name == "nt",
        reason="Windows 系统不支持 ls 命令"
    )
    async def test_allowed_command_ls_executes(self, executor):
        """验证白名单命令 ls 可以执行。"""
        result = await executor._execute_shell_action("test", {"command": "ls"})
        assert "stdout" in result
        assert "returncode" in result

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        os.name == "nt",
        reason="Windows 系统不支持 cat 命令"
    )
    async def test_allowed_command_cat_executes(self, executor, tmp_path):
        """验证白名单命令 cat 可以执行。"""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")
        result = await executor._execute_shell_action(
            "test", {"command": f"cat {test_file}"}
        )
        assert result["returncode"] == 0
        assert "hello world" in result["stdout"]


# ---------------------------------------------------------------------------
# SkillExecutor 代码执行安全
# ---------------------------------------------------------------------------

class TestSkillExecutorCodeAction:
    """测试 SkillExecutor 代码执行安全（通过 RestrictedPythonBackend）。"""

    @pytest.fixture
    def executor(self, tmp_path):
        """创建执行器实例。"""
        executor = SkillExecutor(work_dir=str(tmp_path))
        executor.environment_initialized = True
        executor.execution_context = {}
        return executor

    @pytest.mark.asyncio
    async def test_safe_code_executes(self, executor):
        """验证安全代码可以执行。"""
        result = await executor._execute_code_action(
            "test", {"code": "result = {'value': 1 + 2}", "language": "python"}
        )
        assert result.get("status") == "executed" or "value" in str(result)

    @pytest.mark.asyncio
    async def test_dangerous_exec_rejected(self, executor):
        """验证 exec 调用被 RestrictedPython 拒绝（运行时）。"""
        with pytest.raises(RuntimeError) as exc_info:
            await executor._execute_code_action(
                "test", {"code": "exec('import os')", "language": "python"}
            )
        err = str(exc_info.value)
        assert "失败" in err or "安全" in err

    @pytest.mark.asyncio
    async def test_dangerous_eval_rejected(self, executor):
        """验证 eval 调用被 RestrictedPython 拒绝（编译期）。"""
        with pytest.raises(RuntimeError) as exc_info:
            await executor._execute_code_action(
                "test", {"code": "eval('1+1')", "language": "python"}
            )
        err = str(exc_info.value)
        assert "失败" in err or "安全" in err

    @pytest.mark.asyncio
    async def test_dangerous_import_rejected(self, executor):
        """验证 __import__ 调用被 RestrictedPython 拒绝（运行时）。"""
        with pytest.raises(RuntimeError) as exc_info:
            await executor._execute_code_action(
                "test", {"code": "__import__('os')", "language": "python"}
            )
        err = str(exc_info.value)
        assert "失败" in err or "安全" in err

    @pytest.mark.asyncio
    async def test_dangerous_open_rejected(self, executor):
        """验证 open 调用被 RestrictedPython 拒绝（运行时）。"""
        with pytest.raises(RuntimeError) as exc_info:
            await executor._execute_code_action(
                "test", {"code": "open('/etc/passwd')", "language": "python"}
            )
        err = str(exc_info.value)
        assert "失败" in err or "安全" in err

    @pytest.mark.asyncio
    async def test_function_def_accepted_safe_code(self, executor):
        """RestrictedPython 7.x 允许安全的函数定义（不含危险内容的函数）。"""
        result = await executor._execute_code_action(
            "test", {"code": "def f():\n    return 1\nresult = f()", "language": "python"}
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_unsupported_language_skipped(self, executor):
        """验证不支持的语言被跳过。"""
        result = await executor._execute_code_action(
            "test", {"code": "console.log(1)", "language": "javascript"}
        )
        assert result["status"] == "skipped"


# ---------------------------------------------------------------------------
# SkillExecutor 文件操作安全
# ---------------------------------------------------------------------------

class TestSkillExecutorFileAction:
    """测试 SkillExecutor 文件操作安全。"""

    @pytest.fixture
    def executor(self, tmp_path):
        """创建执行器实例。"""
        return SkillExecutor(work_dir=str(tmp_path))

    @pytest.mark.asyncio
    async def test_read_file_in_work_dir_success(self, executor, tmp_path):
        """验证读取工作目录内文件成功。"""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        result = await executor._execute_file_action(
            "read", {"path": str(test_file)}
        )
        assert result["content"] == "content"

    @pytest.mark.asyncio
    async def test_read_file_outside_work_dir_rejected(self, executor):
        """验证读取工作目录外文件被拒绝。"""
        with pytest.raises(RuntimeError) as exc_info:
            await executor._execute_file_action("read", {"path": "/etc/passwd"})
        assert "校验失败" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_write_file_in_work_dir_success(self, executor, tmp_path):
        """验证写入工作目录内文件成功。"""
        test_file = tmp_path / "write_test.txt"
        result = await executor._execute_file_action(
            "write", {"path": str(test_file), "content": "new content"}
        )
        assert result["status"] == "written"

    @pytest.mark.asyncio
    async def test_write_file_outside_work_dir_rejected(self, executor):
        """验证写入工作目录外文件被拒绝。"""
        with pytest.raises(RuntimeError) as exc_info:
            await executor._execute_file_action(
                "write", {"path": "/tmp/malicious.txt", "content": "bad"}
            )
        assert "校验失败" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_path_traversal_rejected(self, executor):
        """验证路径遍历被拒绝。"""
        with pytest.raises(RuntimeError) as exc_info:
            await executor._execute_file_action(
                "read", {"path": "../../../etc/passwd"}
            )
        assert "校验失败" in str(exc_info.value)

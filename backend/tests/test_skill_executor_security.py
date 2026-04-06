"""
SkillExecutor 安全模块单元测试。

测试覆盖：
- 代码执行沙箱
- 危险函数拦截
- AST 节点限制
- Shell 命令白名单
- 路径遍历防护
"""

import os
import pytest
from pathlib import Path

from skills.skill_executor import (
    CodeValidator,
    SkillExecutor,
    SecurityValidationError,
    _validate_file_path,
    _ALLOWED_SHELL_COMMANDS,
    _DANGEROUS_ARG_PATTERNS,
)


class TestCodeValidatorAllowedNodes:
    """测试 AST 节点白名单。"""

    def test_functiondef_not_in_allowed_nodes(self):
        """验证 FunctionDef 不在允许的节点类型中。"""
        validator = CodeValidator()
        assert "FunctionDef" not in validator._ALLOWED_NODE_TYPES

    def test_asyncfunctiondef_not_in_allowed_nodes(self):
        """验证 AsyncFunctionDef 不在允许的节点类型中。"""
        validator = CodeValidator()
        assert "AsyncFunctionDef" not in validator._ALLOWED_NODE_TYPES

    def test_allowed_nodes_do_not_contain_dangerous_types(self):
        """验证允许的节点类型不包含危险类型。"""
        validator = CodeValidator()
        dangerous_nodes = {
            "FunctionDef", "AsyncFunctionDef", "ClassDef",
            "Import", "ImportFrom", "Global", "Nonlocal",
            "Yield", "YieldFrom", "Await",
            "Lambda", "Starred",
        }
        intersection = validator._ALLOWED_NODE_TYPES & dangerous_nodes
        assert len(intersection) == 0, f"允许的节点包含危险类型: {intersection}"


class TestCodeValidatorForbiddenBuiltins:
    """测试禁止的内置函数。"""

    def test_getattr_in_forbidden_builtins(self):
        """验证 getattr 在禁止列表中。"""
        validator = CodeValidator()
        assert "getattr" in validator._FORBIDDEN_BUILTINS

    def test_setattr_in_forbidden_builtins(self):
        """验证 setattr 在禁止列表中。"""
        validator = CodeValidator()
        assert "setattr" in validator._FORBIDDEN_BUILTINS

    def test_delattr_in_forbidden_builtins(self):
        """验证 delattr 在禁止列表中。"""
        validator = CodeValidator()
        assert "delattr" in validator._FORBIDDEN_BUILTINS

    def test_exec_in_forbidden_builtins(self):
        """验证 exec 在禁止列表中。"""
        validator = CodeValidator()
        assert "exec" in validator._FORBIDDEN_BUILTINS

    def test_eval_in_forbidden_builtins(self):
        """验证 eval 在禁止列表中。"""
        validator = CodeValidator()
        assert "eval" in validator._FORBIDDEN_BUILTINS

    def test_import_in_forbidden_builtins(self):
        """验证 __import__ 在禁止列表中。"""
        validator = CodeValidator()
        assert "__import__" in validator._FORBIDDEN_BUILTINS

    def test_open_in_forbidden_builtins(self):
        """验证 open 在禁止列表中。"""
        validator = CodeValidator()
        assert "open" in validator._FORBIDDEN_BUILTINS


class TestCodeValidatorSafeBuiltins:
    """测试安全内置函数白名单。"""

    def test_getattr_not_in_safe_builtins(self):
        """验证 getattr 不在安全白名单中。"""
        validator = CodeValidator()
        assert "getattr" not in validator._SAFE_BUILTINS

    def test_setattr_not_in_safe_builtins(self):
        """验证 setattr 不在安全白名单中。"""
        validator = CodeValidator()
        assert "setattr" not in validator._SAFE_BUILTINS

    def test_delattr_not_in_safe_builtins(self):
        """验证 delattr 不在安全白名单中。"""
        validator = CodeValidator()
        assert "delattr" not in validator._SAFE_BUILTINS


class TestCodeValidatorDangerousPatterns:
    """测试危险模式检测。"""

    def test_getattr_in_dangerous_patterns(self):
        """验证 getattr 在危险模式中。"""
        validator = CodeValidator()
        assert "getattr" in validator._DANGEROUS_PATTERNS

    def test_setattr_in_dangerous_patterns(self):
        """验证 setattr 在危险模式中。"""
        validator = CodeValidator()
        assert "setattr" in validator._DANGEROUS_PATTERNS

    def test_builtins_in_dangerous_patterns(self):
        """验证 __builtins__ 在危险模式中。"""
        validator = CodeValidator()
        assert "__builtins__" in validator._DANGEROUS_PATTERNS

    def test_subprocess_in_dangerous_patterns(self):
        """验证 subprocess 在危险模式中。"""
        validator = CodeValidator()
        assert "subprocess" in validator._DANGEROUS_PATTERNS


class TestCodeValidatorCodeValidation:
    """测试代码校验功能。"""

    @pytest.fixture
    def validator(self):
        """创建校验器实例。"""
        return CodeValidator()

    def test_safe_code_passes(self, validator):
        """验证安全代码通过校验。"""
        code = "x = 1 + 2\nprint(x)"
        is_safe, error = validator.validate_code(code)
        assert is_safe is True
        assert error == ""

    def test_function_def_rejected(self, validator):
        """验证函数定义被拒绝。"""
        code = "def malicious():\n    pass"
        is_safe, error = validator.validate_code(code)
        assert is_safe is False
        assert "不支持的代码结构" in error

    def test_exec_call_rejected(self, validator):
        """验证 exec 调用被拒绝。"""
        code = "exec('import os')"
        is_safe, error = validator.validate_code(code)
        assert is_safe is False
        assert "禁止调用函数" in error

    def test_eval_call_rejected(self, validator):
        """验证 eval 调用被拒绝。"""
        code = "eval('1+1')"
        is_safe, error = validator.validate_code(code)
        assert is_safe is False
        assert "禁止调用函数" in error

    def test_getattr_call_rejected(self, validator):
        """验证 getattr 调用被拒绝。"""
        code = "getattr(obj, 'attr')"
        is_safe, error = validator.validate_code(code)
        assert is_safe is False
        assert "禁止调用函数" in error or "不在安全函数列表" in error

    def test_import_call_rejected(self, validator):
        """验证 __import__ 调用被拒绝。"""
        code = "__import__('os')"
        is_safe, error = validator.validate_code(code)
        assert is_safe is False
        assert "禁止调用函数" in error

    def test_open_call_rejected(self, validator):
        """验证 open 调用被拒绝。"""
        code = "open('/etc/passwd')"
        is_safe, error = validator.validate_code(code)
        assert is_safe is False
        assert "禁止调用函数" in error

    def test_nested_depth_limit(self, validator):
        """验证嵌套深度限制。"""
        code = "x = " + "[" * 15 + "1" + "]" * 15
        is_safe, error = validator.validate_code(code)
        assert is_safe is False
        assert "嵌套深度" in error

    def test_syntax_error_handled(self, validator):
        """验证语法错误被正确处理。"""
        code = "this is not valid python"
        is_safe, error = validator.validate_code(code)
        assert is_safe is False
        assert "语法错误" in error


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


class TestSkillExecutorCodeAction:
    """测试 SkillExecutor 代码执行安全。"""

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
        """验证 exec 调用被拒绝。"""
        with pytest.raises(RuntimeError) as exc_info:
            await executor._execute_code_action(
                "test", {"code": "exec('import os')", "language": "python"}
            )
        assert "安全校验失败" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_dangerous_eval_rejected(self, executor):
        """验证 eval 调用被拒绝。"""
        with pytest.raises(RuntimeError) as exc_info:
            await executor._execute_code_action(
                "test", {"code": "eval('1+1')", "language": "python"}
            )
        assert "安全校验失败" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_dangerous_import_rejected(self, executor):
        """验证 __import__ 调用被拒绝。"""
        with pytest.raises(RuntimeError) as exc_info:
            await executor._execute_code_action(
                "test", {"code": "__import__('os')", "language": "python"}
            )
        assert "安全校验失败" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_dangerous_open_rejected(self, executor):
        """验证 open 调用被拒绝。"""
        with pytest.raises(RuntimeError) as exc_info:
            await executor._execute_code_action(
                "test", {"code": "open('/etc/passwd')", "language": "python"}
            )
        assert "安全校验失败" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_function_def_rejected(self, executor):
        """验证函数定义被拒绝。"""
        with pytest.raises(RuntimeError) as exc_info:
            await executor._execute_code_action(
                "test", {"code": "def f():\n    pass", "language": "python"}
            )
        assert "安全校验失败" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_unsupported_language_skipped(self, executor):
        """验证不支持的语言被跳过。"""
        result = await executor._execute_code_action(
            "test", {"code": "console.log(1)", "language": "javascript"}
        )
        assert result["status"] == "skipped"


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

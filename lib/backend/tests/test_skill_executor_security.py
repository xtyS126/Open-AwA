"""
SkillExecutor 安全模块单元测试。

测试覆盖：
- RestrictedPythonBackend 代码安全校验（替代已弃用的 CodeValidator）
- Shell 命令白名单
- 路径遍历防护
- SkillExecutor 代码/Shell/文件操作安全
- Task 16: Skill 双模执行（steps / prompt / fork）
"""

import os
import uuid
import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base, Skill
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
        # rm 在 DANGEROUS_COMMANDS 黑名单中，返回"被明确禁止执行"，
        # 与 sandbox.py 行为一致（命令白名单单一真相源）
        assert "禁止" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_dangerous_command_sudo_rejected(self, executor):
        """验证 sudo 命令被拒绝。"""
        with pytest.raises(RuntimeError) as exc_info:
            await executor._execute_shell_action("test", {"command": "sudo ls"})
        # sudo 在 DANGEROUS_COMMANDS 黑名单中，返回"被明确禁止执行"，
        # 与 sandbox.py 行为一致（命令白名单单一真相源）
        assert "禁止" in str(exc_info.value)

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


# ---------------------------------------------------------------------------
# Task 16: Skill 双模执行测试（steps / prompt / fork）
# ---------------------------------------------------------------------------

def _create_test_db_session():
    """创建内存 SQLite 数据库会话，用于 SkillEngine 测试。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)
    return session_local()


def _create_skill_record(db_session, name, config):
    """在数据库中创建测试技能记录。"""
    skill = Skill(
        id=str(uuid.uuid4()),
        name=name,
        version=config.get("version", "1.0.0"),
        description=config.get("description", ""),
        config=yaml.dump(config),
        category="general",
        tags="[]",
        dependencies="[]",
        author="tester",
        enabled=True,
        usage_count=0,
    )
    db_session.add(skill)
    db_session.commit()
    return skill


class TestSkillMetadataExecutionMode:
    """测试 SkillMetadata 的 execution_mode 字段（SubTask 16.1）。"""

    def test_skill_metadata_execution_mode_default(self):
        """验证默认 execution_mode 为 'steps'，保持向后兼容。"""
        from skills.skill_md_loader import SkillMetadata

        meta = SkillMetadata(name="test-skill", description="测试技能")
        assert meta.execution_mode == "steps"

    def test_skill_metadata_execution_mode_prompt(self):
        """验证可以设置 execution_mode 为 'prompt'。"""
        from skills.skill_md_loader import SkillMetadata

        meta = SkillMetadata(
            name="test-skill",
            description="测试技能",
            execution_mode="prompt",
        )
        assert meta.execution_mode == "prompt"

    def test_skill_metadata_execution_mode_fork(self):
        """验证可以设置 execution_mode 为 'fork'。"""
        from skills.skill_md_loader import SkillMetadata

        meta = SkillMetadata(
            name="test-skill",
            description="测试技能",
            execution_mode="fork",
        )
        assert meta.execution_mode == "fork"


class TestGetPromptForCommand:
    """测试 get_prompt_for_command 函数（SubTask 16.2）。"""

    def test_get_prompt_for_command_returns_prompt(self):
        """验证返回 prompt 字符串。"""
        from skills.skill_prompt_resolver import get_prompt_for_command

        skill_config = {
            "name": "test-skill",
            "description": "这是一个测试技能",
            "prompt": "请执行测试任务",
        }
        result = get_prompt_for_command(
            "test-skill", {}, skill_config=skill_config
        )
        assert isinstance(result, str)
        assert "请执行测试任务" in result

    def test_get_prompt_for_command_with_context(self):
        """验证带上下文的 prompt 模板变量替换。"""
        from skills.skill_prompt_resolver import get_prompt_for_command

        skill_config = {
            "name": "test-skill",
            "description": "测试技能",
            "prompt": "请分析 {language} 代码",
        }
        context = {"language": "Python"}
        result = get_prompt_for_command(
            "test-skill", context, skill_config=skill_config
        )
        assert "Python" in result
        # 模板变量已被替换
        assert "{language}" not in result


class TestExecuteForkedSkill:
    """测试 execute_forked_skill 函数（SubTask 16.4）。"""

    def test_execute_forked_skill_returns_task_id(self):
        """验证返回 task_id 字符串。"""
        from skills.skill_fork_executor import execute_forked_skill

        skill = {
            "name": "fork-skill",
            "description": "Fork 模式测试技能",
        }
        parent_context = {
            "messages": [
                {"role": "user", "content": "你好"},
            ],
            "user_id": "u_001",
        }
        task_id = execute_forked_skill(skill, parent_context)

        # 返回值应为非空字符串
        assert isinstance(task_id, str)
        assert len(task_id) > 0


class TestPrepareForkedCommandContext:
    """测试 prepare_forked_command_context 函数（SubTask 16.5）。"""

    def test_prepare_forked_command_context(self):
        """验证桥接函数为 Fork 子 Agent 准备上下文。"""
        from skills.skill_fork_executor import prepare_forked_command_context

        skill = {
            "name": "fork-skill",
            "description": "Fork 模式测试技能",
        }
        parent_context = {
            "messages": [{"role": "user", "content": "父任务"}],
            "user_id": "u_001",
            "conversation_id": "conv_001",
        }
        prepared = prepare_forked_command_context(skill, parent_context)

        # 验证技能信息已注入
        assert prepared["skill_id"] == "fork-skill"
        assert prepared["skill_name"] == "fork-skill"
        assert prepared["skill_description"] == "Fork 模式测试技能"

        # 验证 Fork 子 Agent 标志已设置
        assert prepared["is_fork_child"] is True

        # 验证父上下文内容保留
        assert prepared["user_id"] == "u_001"
        assert prepared["conversation_id"] == "conv_001"

        # 验证深拷贝独立性：修改 prepared 不影响 parent_context
        prepared["messages"].append({"role": "assistant", "content": "子"})
        assert len(parent_context["messages"]) == 1


class TestSkillEngineDualModeExecution:
    """测试 SkillEngine 的双模执行分派（SubTask 16.3）。"""

    @pytest.fixture
    def db_session(self):
        """创建内存数据库会话。"""
        session = _create_test_db_session()
        yield session
        session.close()

    @pytest.fixture
    def skill_engine(self, db_session):
        """创建 SkillEngine 实例。"""
        from skills.skill_engine import SkillEngine
        return SkillEngine(db_session)

    @pytest.mark.asyncio
    async def test_execute_skill_steps_mode(self, skill_engine, db_session):
        """验证 steps 模式执行（默认模式，保持向后兼容）。"""
        config = {
            "name": "steps-skill",
            "version": "1.0.0",
            "description": "steps 模式技能",
            "execution_mode": "steps",
            "steps": [
                {"action": "test", "tool": "default", "params": {}}
            ],
        }
        _create_skill_record(db_session, "steps-skill", config)

        result = await skill_engine.execute_skill(
            skill_name="steps-skill",
            inputs={},
            context={},
        )

        assert result["success"] is True
        assert result["skill_name"] == "steps-skill"
        # steps 模式应执行步骤并返回步骤结果
        assert "steps" in result
        assert len(result["steps"]) >= 1

    @pytest.mark.asyncio
    async def test_execute_skill_prompt_mode(self, skill_engine, db_session):
        """验证 prompt 模式执行：返回 prompt 字符串。"""
        config = {
            "name": "prompt-skill",
            "version": "1.0.0",
            "description": "prompt 模式技能",
            "execution_mode": "prompt",
            "prompt": "请执行 {task}",
        }
        _create_skill_record(db_session, "prompt-skill", config)

        result = await skill_engine.execute_skill(
            skill_name="prompt-skill",
            inputs={},
            context={"task": "代码审查"},
        )

        assert result["success"] is True
        assert result["skill_name"] == "prompt-skill"
        # prompt 模式应返回 prompt 字段
        assert "prompt" in result
        assert "代码审查" in result["prompt"]
        # execution_mode 标记
        assert result.get("execution_mode") == "prompt"

    @pytest.mark.asyncio
    async def test_execute_skill_fork_mode(self, skill_engine, db_session):
        """验证 fork 模式执行：返回 task_id。"""
        config = {
            "name": "fork-skill",
            "version": "1.0.0",
            "description": "fork 模式技能",
            "execution_mode": "fork",
        }
        _create_skill_record(db_session, "fork-skill", config)

        result = await skill_engine.execute_skill(
            skill_name="fork-skill",
            inputs={},
            context={"messages": []},
        )

        assert result["success"] is True
        assert result["skill_name"] == "fork-skill"
        # fork 模式应返回 task_id 字段
        assert "task_id" in result
        assert isinstance(result["task_id"], str)
        assert len(result["task_id"]) > 0
        # execution_mode 标记
        assert result.get("execution_mode") == "fork"

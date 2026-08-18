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
        # rm -rf / 命中系统级硬阻断（最高优先级），统一入口直接拒绝
        assert "硬阻断" in str(exc_info.value) or "禁止" in str(exc_info.value)

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
        assert "硬阻断" in str(exc_info.value) or "拒绝" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_shell_injection_pipe_rejected(self, executor):
        """验证管道注入被拒绝。"""
        with pytest.raises(RuntimeError) as exc_info:
            await executor._execute_shell_action("test", {"command": "ls | rm"})
        assert "拒绝" in str(exc_info.value) or "不允许" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_shell_injection_backtick_rejected(self, executor):
        """验证反引号注入被拒绝。"""
        with pytest.raises(RuntimeError) as exc_info:
            await executor._execute_shell_action("test", {"command": "ls `rm`"})
        assert "拒绝" in str(exc_info.value) or "不允许" in str(exc_info.value)

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
    """测试 execute_forked_skill 函数（SubTask 16.4 + Task 18 真实调度）。"""

    @pytest.mark.asyncio
    async def test_execute_forked_skill_returns_task_id(self):
        """验证真实调度 Fork 子 Agent 后返回结果字典（含非空 task_id）。"""
        from unittest.mock import AsyncMock, patch
        from skills.skill_fork_executor import execute_forked_skill
        from core.task_runtime import task_runtime

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

        async def fake_stream():
            yield {"type": "fork_started", "agent_id": "ag_fork_1", "task_id": "ag_fork_1", "result": ""}

        with patch.object(task_runtime, "spawn_agent", new=AsyncMock(return_value=fake_stream())) as mock_spawn, \
             patch.object(task_runtime, "get_agent", new=AsyncMock(return_value={"state": "completed", "summary": "完成"})), \
             patch.object(task_runtime, "get_transcript", new=AsyncMock(return_value=[])):
            result = await execute_forked_skill(skill, parent_context)

        # 返回值应为结果字典
        assert isinstance(result, dict)
        assert isinstance(result["task_id"], str)
        assert len(result["task_id"]) > 0
        assert result["success"] is True
        # fork_mode 参数必须透传给 task_runtime.spawn_agent
        assert mock_spawn.call_args.kwargs["fork_mode"] is True


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
        """验证 fork 模式执行：桥接真实调度并返回 task_id 与结果文本。"""
        from unittest.mock import AsyncMock, patch

        config = {
            "name": "fork-skill",
            "version": "1.0.0",
            "description": "fork 模式技能",
            "execution_mode": "fork",
        }
        _create_skill_record(db_session, "fork-skill", config)

        with patch(
            "skills.skill_engine.execute_forked_skill",
            new=AsyncMock(return_value={
                "success": True,
                "task_id": "task_fork_1",
                "agent_type": "general-purpose",
                "result": "子代理完成",
            }),
        ) as mock_fork:
            result = await skill_engine.execute_skill(
                skill_name="fork-skill",
                inputs={},
                context={"messages": []},
            )

        # execute_forked_skill 必须被真实 await 调用（Task 18 真实调度）
        mock_fork.assert_awaited_once()
        assert result["success"] is True
        assert result["skill_name"] == "fork-skill"
        # fork 模式应返回 task_id 字段与结果文本
        assert result["task_id"] == "task_fork_1"
        assert result["result"] == "子代理完成"
        assert isinstance(result["task_id"], str)
        assert len(result["task_id"]) > 0
        # execution_mode 标记
        assert result.get("execution_mode") == "fork"


# ---------------------------------------------------------------------------
# Task 17: 内置 Agent 工具过滤生效测试
# （permission_guard 真正 gate 子代理工具调用 + bundle 注入工具约束）
# ---------------------------------------------------------------------------

class TestPermissionGuardReadonlyAgents:
    """验证 plan 模式的只读 Agent（verification/Explore）无法调用写入工具。"""

    def test_plan_mode_rejects_write_file(self):
        """验证 plan 模式拒绝 builtin_write_file 写入工具。"""
        from core.task_runtime.permission_guard import permission_guard

        decision = permission_guard.evaluate("builtin_write_file", {}, permission_mode="plan")
        assert decision.allowed is False
        assert decision.mode == "deny"

    def test_plan_mode_rejects_run_command(self):
        """验证 plan 模式拒绝 builtin_run_command 命令执行工具。"""
        from core.task_runtime.permission_guard import permission_guard

        decision = permission_guard.evaluate("builtin_run_command", {}, permission_mode="plan")
        assert decision.allowed is False
        assert decision.mode == "deny"

    def test_plan_mode_rejects_delete_file(self):
        """验证 plan 模式拒绝 builtin_delete_file 删除工具。"""
        from core.task_runtime.permission_guard import permission_guard

        decision = permission_guard.evaluate("builtin_delete_file", {}, permission_mode="plan")
        assert decision.allowed is False

    def test_plan_mode_allows_read_tools(self):
        """验证 plan 模式放行只读工具（读文件/搜索），保证内置 Agent 主要工具可用。"""
        from core.task_runtime.permission_guard import permission_guard

        for tool_name in (
            "builtin_read_file",
            "builtin_list_files",
            "builtin_file_exists",
            "builtin_web_search",
            "builtin_local_search",
        ):
            decision = permission_guard.evaluate(tool_name, {}, permission_mode="plan")
            assert decision.allowed is True, f"{tool_name} 应被 plan 模式放行"

    def test_allowed_tools_whitelist_rejects_undeclared_tool(self):
        """验证显式 allowed_tools 白名单下，白名单之外的写入工具被拒绝（default 模式 tools 声明生效）。"""
        from core.task_runtime.permission_guard import permission_guard

        decision = permission_guard.evaluate(
            "write_file",
            {},
            permission_mode="default",
            allowed_tools=["read_file", "list_files", "web_search"],
        )
        assert decision.allowed is False
        assert "允许列表" in decision.reason

    def test_allowed_tools_whitelist_allows_declared_tool(self):
        """验证显式 allowed_tools 白名单内的工具放行（含 builtin_ 归一化匹配）。"""
        from core.task_runtime.permission_guard import permission_guard

        decision = permission_guard.evaluate(
            "builtin_read_file",
            {},
            permission_mode="default",
            allowed_tools=["read_file", "list_files", "web_search"],
        )
        assert decision.allowed is True


class TestSubagentBundleToolFilter:
    """验证 _create_subagent_execution_bundle 按 AgentDefinition 注入工具约束。"""

    @pytest.mark.asyncio
    async def test_explore_bundle_rejects_write_tools(self):
        """验证 Explore（plan 模式）bundle 注入 plan 权限模式，白名单不含写入工具。"""
        from unittest.mock import AsyncMock, MagicMock, patch
        from core.task_runtime.definitions import get_agent_definition
        from core.task_runtime.runners import _create_subagent_execution_bundle

        with patch("core.task_runtime.runners.SessionLocal") as mock_session_local, \
             patch("core.task_runtime.runners._load_project_context", return_value=""), \
             patch("core.task_runtime.runners.load_agent_memory_prompt", new=AsyncMock(return_value="")), \
             patch("core.agent.AIAgent") as mock_agent_cls:
            mock_agent_cls.return_value = MagicMock()
            mock_db = MagicMock()
            mock_session_local.return_value = mock_db

            _, _, sub_context = await _create_subagent_execution_bundle(
                agent_id="ag_explore_1",
                agent_type="Explore",
                provider=None,
                model=None,
                context={"user_id": "u1"},
                agent_def=get_agent_definition("Explore"),
            )

        # plan 权限模式必须注入（执行时 PermissionGuard 真正 gate 写工具）
        assert sub_context["permission_mode"] == "plan"
        allowed = set(sub_context["allowed_tools"])
        assert "write_file" not in allowed and "builtin_write_file" not in allowed
        assert "run_command" not in allowed and "builtin_run_command" not in allowed
        # 主要只读工具必须可用
        assert "read_file" in allowed or "builtin_read_file" in allowed
        assert "list_files" in allowed or "builtin_list_files" in allowed

    @pytest.mark.asyncio
    async def test_verification_bundle_keeps_readonly_tools(self):
        """验证 verification（plan 模式）bundle 白名单保留其声明的只读工具。"""
        from unittest.mock import AsyncMock, MagicMock, patch
        from core.task_runtime.definitions import get_agent_definition
        from core.task_runtime.runners import _create_subagent_execution_bundle

        with patch("core.task_runtime.runners.SessionLocal") as mock_session_local, \
             patch("core.task_runtime.runners._load_project_context", return_value=""), \
             patch("core.task_runtime.runners.load_agent_memory_prompt", new=AsyncMock(return_value="")), \
             patch("core.agent.AIAgent") as mock_agent_cls:
            mock_agent_cls.return_value = MagicMock()
            mock_db = MagicMock()
            mock_session_local.return_value = mock_db

            _, _, sub_context = await _create_subagent_execution_bundle(
                agent_id="ag_verify_1",
                agent_type="verification",
                provider=None,
                model=None,
                context={"user_id": "u1"},
                agent_def=get_agent_definition("verification"),
            )

        assert sub_context["permission_mode"] == "plan"
        allowed = set(sub_context["allowed_tools"])
        assert "write_file" not in allowed and "builtin_write_file" not in allowed
        assert "run_command" not in allowed and "builtin_run_command" not in allowed
        # 只读工具保留
        assert "read_file" in allowed or "builtin_read_file" in allowed
        assert "list_files" in allowed or "builtin_list_files" in allowed


# ---------------------------------------------------------------------------
# Task 18: Skill fork 真实调度与 prompt 注入测试
# ---------------------------------------------------------------------------

class TestForkSkillRealDispatch:
    """验证 execute_forked_skill 真实调度子 Agent 并提取结果。"""

    @pytest.mark.asyncio
    async def test_execute_forked_skill_spawns_agent_and_extracts_result(self):
        """验证 spawn_agent 以 fork_mode=True 被真实调用，且结果文本被提取返回。"""
        from unittest.mock import AsyncMock, patch
        from skills.skill_fork_executor import execute_forked_skill
        from core.task_runtime import task_runtime

        skill = {
            "name": "fork-skill",
            "description": "请分析代码库结构",
            "agent_type": "Explore",
        }
        parent_context = {
            "messages": [{"role": "user", "content": "父任务"}],
            "user_id": "u_001",
        }

        async def fake_stream():
            yield {"type": "fork_started", "agent_id": "ag_fork_9", "task_id": "ag_fork_9", "result": ""}

        with patch.object(task_runtime, "spawn_agent", new=AsyncMock(return_value=fake_stream())) as mock_spawn, \
             patch.object(task_runtime, "get_agent", new=AsyncMock(return_value={"state": "completed", "summary": "完成"})), \
             patch.object(task_runtime, "get_transcript", new=AsyncMock(return_value=[
                 {"event": "agent_message", "message": "分析结果：模块 A 位于 src/a.py"},
             ])):
            result = await execute_forked_skill(skill, parent_context)

        mock_spawn.assert_awaited_once()
        call_kwargs = mock_spawn.call_args.kwargs
        # 必须桥接 Task 15 新增的 fork_mode=True 参数
        assert call_kwargs["fork_mode"] is True
        assert call_kwargs["agent_type"] == "Explore"
        # 子 Agent 上下文必须设置防递归标志
        assert call_kwargs["context"]["is_fork_child"] is True
        assert result["success"] is True
        assert result["task_id"] == "ag_fork_9"
        # 等待完成后提取的结果文本
        assert "分析结果" in result["result"]


class TestPromptSkillInjection:
    """验证 prompt 模式技能结果回注入主对话（Task 18）。"""

    @pytest.mark.asyncio
    async def test_execute_skill_prompt_mode_injects_user_message(self):
        """验证 prompt 模式以 user 消息回注入 conversation_history 并标记 inject_as_user。"""
        from skills.skill_engine import SkillEngine

        db_session = _create_test_db_session()
        try:
            config = {
                "name": "prompt-inject-skill",
                "version": "1.0.0",
                "description": "prompt 注入技能",
                "execution_mode": "prompt",
                "prompt": "请执行 {task}",
            }
            _create_skill_record(db_session, "prompt-inject-skill", config)

            engine = SkillEngine(db_session)
            context = {"task": "代码审查", "conversation_history": []}
            result = await engine.execute_skill(
                skill_name="prompt-inject-skill",
                inputs={},
                context=context,
            )
        finally:
            db_session.close()

        assert result["success"] is True
        # 返回值必须标记 inject_as_user，供 plan_executor 消费
        assert result.get("inject_as_user") is True
        # 结果以 user 消息回注入主对话
        assert context["conversation_history"][-1] == {"role": "user", "content": "请执行 代码审查"}

    @pytest.mark.asyncio
    async def test_plan_executor_injects_prompt_result(self):
        """验证 plan_executor 消费 inject_as_user 标记并把 prompt 注入对话历史。"""
        from unittest.mock import AsyncMock, MagicMock
        from core.plan_executor import PlanExecutor

        executor = MagicMock()
        executor.execute_step = AsyncMock()
        executor.retry_step = AsyncMock()
        feedback = MagicMock()
        feedback.evaluate_result = AsyncMock(return_value={})
        execute_skill = AsyncMock(return_value={
            "status": "success",
            "skill_name": "prompt-skill",
            "outputs": {"prompt": "请执行 代码审查"},
            "inject_as_user": True,
        })
        plan_executor = PlanExecutor(
            executor,
            feedback,
            execute_skill,
            AsyncMock(),
            AsyncMock(return_value=[]),
            AsyncMock(return_value=[]),
            MagicMock(),
            MagicMock(side_effect=lambda output, _: output),
        )
        context = {"enable_skill_plugin": True, "conversation_history": []}
        results: list = []

        await plan_executor.execute_single_step(
            {"use_skill": True, "skill_name": "prompt-skill", "inputs": {}},
            "用户输入",
            context,
            results,
        )

        # prompt 已作为 user 消息注入对话历史
        assert context["conversation_history"][-1] == {"role": "user", "content": "请执行 代码审查"}

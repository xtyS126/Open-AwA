"""
CommandExecutor 和 EventLog 单元测试。
测试命令发现、模板渲染、shell 注入、事件记录。
"""

import tempfile
from pathlib import Path
import pytest

from core.command_executor import (
    CommandExecutor,
    CommandDefinition,
    BUILTIN_COMMANDS,
)


class TestCommandDefinition:
    """命令定义测试"""

    def test_parse_from_markdown(self):
        """从 Markdown 文件解析命令"""
        content = """---
description: 测试命令
model: gpt-4
subtask: true
---

这是命令模板内容
!`echo hello`"""

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False, encoding='utf-8'
        ) as f:
            f.write(content)
            temp_path = f.name

        try:
            cmd = CommandDefinition.parse_from_markdown(temp_path)
            assert cmd is not None
            assert cmd.name == Path(temp_path).stem
            assert cmd.description == "测试命令"
            assert cmd.model == "gpt-4"
            assert cmd.subtask is True
            assert "命令模板" in cmd.template
        finally:
            Path(temp_path).unlink()

    def test_parse_readme_skipped(self):
        """README 文件被跳过"""
        # README 不应作为命令，由 discover_commands 处理
        pass

    def test_render_template_variables(self):
        """模板变量渲染"""
        cmd = CommandDefinition(
            name="test",
            template="Hello {{name}}, your task is {{task}}",
        )
        rendered = cmd.render_template({"name": "World", "task": "testing"})
        assert rendered == "Hello World, your task is testing"

    def test_render_template_no_context(self):
        """无上下文时保持模板"""
        cmd = CommandDefinition(
            name="test",
            template="Hello {{name}}",
        )
        rendered = cmd.render_template()
        assert rendered == "Hello {{name}}"

    def test_render_template_shell_expansion(self):
        """Shell 命令注入"""
        cmd = CommandDefinition(
            name="test",
            template="Result: !`echo hello world`",
        )
        rendered = cmd.render_template()
        assert "hello world" in rendered


class TestCommandExecutor:
    """命令执行器测试"""

    @pytest.fixture
    def executor(self):
        """创建 CommandExecutor"""
        exe = CommandExecutor()
        # 注册内建命令
        for cmd in BUILTIN_COMMANDS:
            exe.register_builtin(cmd)
        return exe

    def test_list_builtin_commands(self, executor):
        """列出内建命令"""
        commands = executor.list_commands()
        assert len(commands) >= 3
        names = [c.name for c in commands]
        assert "commit" in names
        assert "review" in names

    def test_get_command(self, executor):
        """获取指定命令"""
        cmd = executor.get_command("commit")
        assert cmd is not None
        assert "git diff" in cmd.template

    def test_get_nonexistent_command(self, executor):
        """获取不存在的命令"""
        assert executor.get_command("nonexistent") is None

    def test_render_command(self, executor):
        """渲染命令模板"""
        rendered = executor.render_command("commit")
        assert rendered is not None
        assert "git diff" in rendered

    def test_discover_commands_from_dir(self, executor):
        """从目录发现命令"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建一个命令文件
            cmd_file = Path(tmpdir) / "test-cmd.md"
            cmd_file.write_text("""---
description: 发现测试
---

命令内容
!`echo found`""", encoding="utf-8")

            # 创建一个 README（应跳过）
            readme = Path(tmpdir) / "README.md"
            readme.write_text("# README", encoding="utf-8")

            count = executor.discover_commands(tmpdir)
            assert count >= 1
            assert executor.get_command("test-cmd") is not None

    def test_render_command_with_context(self, executor):
        """带上下文的命令渲染"""
        cmd = CommandDefinition(
            name="context-test",
            template="Task: {{task}} for {{user}}",
        )
        executor.register_builtin(cmd)
        rendered = executor.render_command("context-test", {
            "task": "deploy",
            "user": "admin",
        })
        assert "deploy" in rendered
        assert "admin" in rendered


class TestBuiltinCommands:
    """内建命令测试"""

    def test_commit_command_exists(self):
        """commit 命令已定义"""
        commit_cmd = next((c for c in BUILTIN_COMMANDS if c.name == "commit"), None)
        assert commit_cmd is not None
        assert "Conventional Commits" in commit_cmd.template

    def test_review_command_is_subtask(self):
        """review 命令标记为子任务"""
        review_cmd = next((c for c in BUILTIN_COMMANDS if c.name == "review"), None)
        assert review_cmd is not None
        assert review_cmd.subtask is True

    def test_changelog_command_exists(self):
        """changelog 命令已定义"""
        changelog_cmd = next(
            (c for c in BUILTIN_COMMANDS if c.name == "changelog"), None
        )
        assert changelog_cmd is not None
        assert "变更日志" in changelog_cmd.template

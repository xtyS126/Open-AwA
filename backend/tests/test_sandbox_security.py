"""
Sandbox 安全模块单元测试。

测试覆盖：
- 命令注入防护
- 路径遍历防护
- 权限检查
- 危险命令拒绝
- 权限检查强制调用验证
"""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from security.sandbox import (
    Sandbox,
    SandboxPermissionError,
    SandboxPathError,
    _ALLOWED_COMMANDS,
    _DANGEROUS_COMMANDS,
    _DANGEROUS_ARG_PATTERNS,
    is_path_allowed,
    validate_command_safety,
)


class TestCommandWhitelist:
    """测试命令白名单配置。"""

    def test_allowed_commands_not_contain_dangerous(self):
        """验证白名单不包含危险命令。"""
        dangerous_in_allowed = _ALLOWED_COMMANDS & _DANGEROUS_COMMANDS
        assert len(dangerous_in_allowed) == 0, (
            f"白名单包含危险命令: {dangerous_in_allowed}"
        )

    def test_rm_not_in_allowed(self):
        """验证 rm 不在白名单中。"""
        assert "rm" not in _ALLOWED_COMMANDS, "rm 不应在白名单中"

    def test_chmod_not_in_allowed(self):
        """验证 chmod 不在白名单中。"""
        assert "chmod" not in _ALLOWED_COMMANDS, "chmod 不应在白名单中"

    def test_chown_not_in_allowed(self):
        """验证 chown 不在白名单中。"""
        assert "chown" not in _ALLOWED_COMMANDS, "chown 不应在白名单中"

    def test_xargs_not_in_allowed(self):
        """验证 xargs 不在白名单中。"""
        assert "xargs" not in _ALLOWED_COMMANDS, "xargs 不应在白名单中"

    def test_awk_not_in_allowed(self):
        """验证 awk 不在白名单中。"""
        assert "awk" not in _ALLOWED_COMMANDS, "awk 不应在白名单中"

    def test_sed_not_in_allowed(self):
        """验证 sed 不在白名单中。"""
        assert "sed" not in _ALLOWED_COMMANDS, "sed 不应在白名单中"

    def test_dangerous_commands_blacklist_complete(self):
        """验证危险命令黑名单完整。"""
        required_dangerous = {
            "rm", "chmod", "chown", "xargs", "awk", "sed",
            "dd", "mkfs", "fdisk", "mount", "umount",
            "sudo", "su", "bash", "sh", "zsh", "fish",
            "python", "python3", "perl", "ruby", "node",
            "curl", "wget", "nc", "netcat", "ncat",
        }
        missing = required_dangerous - _DANGEROUS_COMMANDS
        assert len(missing) == 0, f"黑名单缺少危险命令: {missing}"


class TestDangerousArgPatterns:
    """测试危险参数模式。"""

    def test_path_traversal_pattern_exists(self):
        """验证路径遍历模式存在。"""
        pattern_texts = [p.pattern for p in _DANGEROUS_ARG_PATTERNS]
        assert any(r"\.\." in p for p in pattern_texts), "缺少路径遍历模式"

    def test_shell_special_chars_pattern_exists(self):
        """验证 Shell 特殊字符模式存在。"""
        pattern_texts = [p.pattern for p in _DANGEROUS_ARG_PATTERNS]
        assert any(";" in p or "|" in p or "&" in p for p in pattern_texts), (
            "缺少 Shell 特殊字符模式"
        )

    def test_command_substitution_pattern_exists(self):
        """验证命令替换模式存在。"""
        pattern_texts = [p.pattern for p in _DANGEROUS_ARG_PATTERNS]
        assert any(r"\$\(" in p for p in pattern_texts), "缺少命令替换模式"


class TestCommandInjectionPrevention:
    """测试命令注入防护。"""

    @pytest.fixture
    def sandbox(self, tmp_path):
        """创建沙箱实例。"""
        return Sandbox(work_dir=str(tmp_path))

    @pytest.mark.asyncio
    async def test_shell_injection_semicolon_rejected(self, sandbox):
        """验证分号注入被拒绝。"""
        result = await sandbox.execute_command("ls; rm -rf /")
        assert result["status"] == "error"
        assert "不在允许列表" in result["message"] or "拒绝" in result["message"]

    @pytest.mark.asyncio
    async def test_shell_injection_pipe_rejected(self, sandbox):
        """验证管道注入被拒绝。"""
        result = await sandbox.execute_command("ls | rm -rf /")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_shell_injection_backtick_rejected(self, sandbox):
        """验证反引号注入被拒绝。"""
        result = await sandbox.execute_command("ls `rm -rf /`")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_shell_injection_dollar_paren_rejected(self, sandbox):
        """验证 $() 命令替换被拒绝。"""
        result = await sandbox.execute_command("ls $(rm -rf /)")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_dangerous_command_rm_rejected(self, sandbox):
        """验证 rm 命令被拒绝。"""
        result = await sandbox.execute_command("rm -rf /")
        assert result["status"] == "error"
        assert "禁止" in result["message"] or "拒绝" in result["message"]

    @pytest.mark.asyncio
    async def test_dangerous_command_sudo_rejected(self, sandbox):
        """验证 sudo 命令被拒绝。"""
        result = await sandbox.execute_command("sudo ls")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_dangerous_command_bash_rejected(self, sandbox):
        """验证 bash 命令被拒绝。"""
        result = await sandbox.execute_command("bash -c 'rm -rf /'")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_dangerous_command_python_rejected(self, sandbox):
        """验证 python 命令被拒绝。"""
        result = await sandbox.execute_command("python -c 'import os; os.system(\"rm -rf /\")'")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        os.name == "nt",
        reason="Windows 系统不支持 ls 命令"
    )
    async def test_allowed_command_ls_executes(self, sandbox):
        """验证白名单命令 ls 可以执行。"""
        result = await sandbox.execute_command("ls")
        assert result["status"] == "success"

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        os.name == "nt",
        reason="Windows 系统不支持 cat 命令"
    )
    async def test_allowed_command_cat_executes(self, sandbox, tmp_path):
        """验证白名单命令 cat 可以执行。"""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")
        result = await sandbox.execute_command(f"cat {test_file}")
        assert result["status"] == "success"
        assert "hello world" in result["stdout"]


class TestPathTraversalPrevention:
    """测试路径遍历防护。"""

    @pytest.fixture
    def sandbox(self, tmp_path):
        """创建沙箱实例。"""
        return Sandbox(work_dir=str(tmp_path))

    @pytest.fixture
    def test_file(self, tmp_path):
        """创建测试文件。"""
        file_path = tmp_path / "test.txt"
        file_path.write_text("test content")
        return str(file_path)

    def test_path_traversal_parent_rejected(self, sandbox, tmp_path):
        """验证父目录遍历被拒绝。"""
        with pytest.raises(SandboxPathError):
            sandbox._validate_path("../../../etc/passwd")

    def test_path_traversal_absolute_root_rejected(self, sandbox):
        """验证绝对路径 /etc 被拒绝。"""
        with pytest.raises(SandboxPathError):
            sandbox._validate_path("/etc/passwd")

    def test_path_traversal_root_directory_rejected(self, sandbox):
        """验证 /root 目录被拒绝。"""
        with pytest.raises(SandboxPathError):
            sandbox._validate_path("/root/.ssh/id_rsa")

    def test_path_traversal_proc_rejected(self, sandbox):
        """验证 /proc 目录被拒绝。"""
        with pytest.raises(SandboxPathError):
            sandbox._validate_path("/proc/self/environ")

    def test_path_traversal_sys_rejected(self, sandbox):
        """验证 /sys 目录被拒绝。"""
        with pytest.raises(SandboxPathError):
            sandbox._validate_path("/sys/kernel")

    def test_valid_path_in_work_dir_accepted(self, sandbox, test_file):
        """验证工作目录内的路径被接受。"""
        result = sandbox._validate_path(test_file)
        assert result.exists()

    def test_empty_path_rejected(self, sandbox):
        """验证空路径被拒绝。"""
        with pytest.raises(SandboxPathError):
            sandbox._validate_path("")

    def test_whitespace_path_rejected(self, sandbox):
        """验证空白路径被拒绝。"""
        with pytest.raises(SandboxPathError):
            sandbox._validate_path("   ")


class TestFileOperationSecurity:
    """测试文件操作安全。"""

    @pytest.fixture
    def sandbox(self, tmp_path):
        """创建沙箱实例。"""
        return Sandbox(work_dir=str(tmp_path))

    @pytest.mark.asyncio
    async def test_read_file_in_work_dir_success(self, sandbox, tmp_path):
        """验证读取工作目录内文件成功。"""
        test_file = tmp_path / "read_test.txt"
        test_file.write_text("read content")
        result = await sandbox.execute_file_operation("read", str(test_file))
        assert result["status"] == "success"
        assert result["content"] == "read content"

    @pytest.mark.asyncio
    async def test_read_file_outside_work_dir_rejected(self, sandbox):
        """验证读取工作目录外文件被拒绝。"""
        result = await sandbox.execute_file_operation("read", "/etc/passwd")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_write_file_in_work_dir_success(self, sandbox, tmp_path):
        """验证写入工作目录内文件成功。"""
        test_file = tmp_path / "write_test.txt"
        result = await sandbox.execute_file_operation(
            "write", str(test_file), content="write content"
        )
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_write_file_outside_work_dir_rejected(self, sandbox):
        """验证写入工作目录外文件被拒绝。"""
        result = await sandbox.execute_file_operation(
            "write", "/tmp/malicious.txt", content="malicious"
        )
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_delete_file_in_work_dir_success(self, sandbox, tmp_path):
        """验证删除工作目录内文件成功。"""
        test_file = tmp_path / "delete_test.txt"
        test_file.write_text("to be deleted")
        result = await sandbox.execute_file_operation("delete", str(test_file))
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_file_outside_work_dir_rejected(self, sandbox):
        """验证删除工作目录外文件被拒绝。"""
        result = await sandbox.execute_file_operation("delete", "/etc/passwd")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_read_env_file_rejected(self, sandbox):
        """验证读取 .env 文件被拒绝。"""
        result = await sandbox.execute_file_operation("read", ".env")
        assert result["status"] == "error"


class TestPermissionCheck:
    """测试权限检查。"""

    @pytest.fixture
    def sandbox(self, tmp_path):
        """创建沙箱实例。"""
        return Sandbox(work_dir=str(tmp_path))

    @pytest.mark.asyncio
    async def test_permission_check_dangerous_execute_rejected(self, sandbox):
        """验证危险命令权限检查拒绝。"""
        allowed = await sandbox.check_permission("execute", "rm")
        assert allowed is False

    @pytest.mark.asyncio
    async def test_permission_check_dangerous_delete_rejected(self, sandbox):
        """验证危险删除权限检查拒绝。"""
        allowed = await sandbox.check_permission("delete", ".env")
        assert allowed is False

    @pytest.mark.asyncio
    async def test_permission_check_dangerous_write_rejected(self, sandbox):
        """验证危险写入权限检查拒绝。"""
        allowed = await sandbox.check_permission("write", "/etc/passwd")
        assert allowed is False

    @pytest.mark.asyncio
    async def test_permission_check_safe_operation_allowed(self, sandbox):
        """验证安全操作权限检查通过。"""
        allowed = await sandbox.check_permission("read", "safe_file.txt")
        assert allowed is True


class TestPermissionCheckEnforced:
    """测试权限检查被强制调用。"""

    @pytest.fixture
    def sandbox(self, tmp_path):
        """创建沙箱实例。"""
        return Sandbox(work_dir=str(tmp_path))

    @pytest.mark.asyncio
    async def test_execute_command_calls_check_permission(self, sandbox, tmp_path):
        """验证 execute_command 强制调用 check_permission。"""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        with patch.object(
            sandbox, 'check_permission', new_callable=AsyncMock
        ) as mock_check:
            mock_check.return_value = True

            await sandbox.execute_command("ls")

            mock_check.assert_called_once()
            call_args = mock_check.call_args
            assert call_args[0][0] == "execute"
            assert call_args[0][1] == "ls"

    @pytest.mark.asyncio
    async def test_execute_command_permission_denied_returns_error(self, sandbox):
        """验证 execute_command 权限拒绝时返回错误。"""
        with patch.object(
            sandbox, 'check_permission', new_callable=AsyncMock
        ) as mock_check:
            mock_check.return_value = False

            result = await sandbox.execute_command("ls")

            assert result["status"] == "error"
            assert "权限拒绝" in result["message"]
            mock_check.assert_called_once_with("execute", "ls")

    @pytest.mark.asyncio
    async def test_execute_file_operation_read_calls_check_permission(self, sandbox, tmp_path):
        """验证 execute_file_operation read 操作调用 check_permission。"""
        test_file = tmp_path / "read_test.txt"
        test_file.write_text("content")

        with patch.object(
            sandbox, 'check_permission', new_callable=AsyncMock
        ) as mock_check:
            mock_check.return_value = True

            result = await sandbox.execute_file_operation("read", str(test_file))

            assert result["status"] == "success"
            mock_check.assert_called_once()
            call_args = mock_check.call_args
            assert call_args[0][0] == "read"

    @pytest.mark.asyncio
    async def test_execute_file_operation_write_calls_check_permission(self, sandbox, tmp_path):
        """验证 execute_file_operation write 操作调用 check_permission。"""
        test_file = tmp_path / "write_test.txt"

        with patch.object(
            sandbox, 'check_permission', new_callable=AsyncMock
        ) as mock_check:
            mock_check.return_value = True

            result = await sandbox.execute_file_operation(
                "write", str(test_file), content="test content"
            )

            assert result["status"] == "success"
            mock_check.assert_called_once()
            call_args = mock_check.call_args
            assert call_args[0][0] == "write"

    @pytest.mark.asyncio
    async def test_execute_file_operation_delete_calls_check_permission(self, sandbox, tmp_path):
        """验证 execute_file_operation delete 操作调用 check_permission。"""
        test_file = tmp_path / "delete_test.txt"
        test_file.write_text("to delete")

        with patch.object(
            sandbox, 'check_permission', new_callable=AsyncMock
        ) as mock_check:
            mock_check.return_value = True

            result = await sandbox.execute_file_operation("delete", str(test_file))

            assert result["status"] == "success"
            mock_check.assert_called_once()
            call_args = mock_check.call_args
            assert call_args[0][0] == "delete"

    @pytest.mark.asyncio
    async def test_execute_file_operation_permission_denied_returns_error(self, sandbox):
        """验证 execute_file_operation 权限拒绝时返回错误。"""
        with patch.object(
            sandbox, 'check_permission', new_callable=AsyncMock
        ) as mock_check:
            mock_check.return_value = False

            result = await sandbox.execute_file_operation("read", ".env")

            assert result["status"] == "error"
            assert "权限拒绝" in result["message"]
            mock_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_permission_called_before_path_validation(self, sandbox, tmp_path):
        """验证权限检查在路径校验之前被调用。"""
        call_order = []

        original_check = sandbox.check_permission
        async def track_check(*args, **kwargs):
            call_order.append('check_permission')
            return await original_check(*args, **kwargs)

        original_validate = sandbox._validate_path
        def track_validate(*args, **kwargs):
            call_order.append('_validate_path')
            return original_validate(*args, **kwargs)

        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        with patch.object(sandbox, 'check_permission', side_effect=track_check):
            with patch.object(sandbox, '_validate_path', side_effect=track_validate):
                await sandbox.execute_file_operation("read", str(test_file))

        assert call_order == ['check_permission', '_validate_path']

    @pytest.mark.asyncio
    async def test_execute_command_check_permission_with_dangerous_command(self, sandbox):
        """验证危险命令触发权限检查并被拒绝。"""
        with patch.object(
            sandbox, 'check_permission', new_callable=AsyncMock
        ) as mock_check:
            mock_check.return_value = False

            result = await sandbox.execute_command("rm")

            assert result["status"] == "error"
            mock_check.assert_called_once_with("execute", "rm")

    @pytest.mark.asyncio
    async def test_execute_file_operation_with_sensitive_path(self, sandbox):
        """验证敏感路径触发权限检查并被拒绝。"""
        with patch.object(
            sandbox, 'check_permission', new_callable=AsyncMock
        ) as mock_check:
            mock_check.return_value = False

            result = await sandbox.execute_file_operation("delete", ".env")

            assert result["status"] == "error"
            mock_check.assert_called_once()
            call_args = mock_check.call_args
            assert call_args[0][0] == "delete"
            assert ".env" in call_args[0][1]


class TestTask12DenyEnvVariants:
    """Task 12：.env 及常见变体路径拒绝（含大小写变体）。"""

    def test_env_variants_rejected_by_is_path_allowed(self):
        """验证 .env 及常见变体均被 is_path_allowed 拒绝。"""
        assert is_path_allowed('.env') is False
        assert is_path_allowed('.env.local') is False
        assert is_path_allowed('.env.production') is False
        assert is_path_allowed('.env.dev') is False
        assert is_path_allowed('.env.test') is False
        # 大小写变体（IGNORECASE）
        assert is_path_allowed('.ENV') is False
        assert is_path_allowed('.Env.Local') is False
        assert is_path_allowed('/tmp/.env.production') is False
        assert is_path_allowed('/home/user/.ENV') is False

    @pytest.mark.asyncio
    async def test_env_variants_rejected_by_file_operation(self, tmp_path):
        """验证 execute_file_operation 读取 .env 变体被拒绝。"""
        sandbox = Sandbox(work_dir=str(tmp_path))
        env_file = tmp_path / '.env.production'
        env_file.write_text("SECRET=value")
        result = await sandbox.execute_file_operation("read", str(env_file))
        assert result["status"] == "error"


class TestTask12DenySecretFiles:
    """Task 12：常见密钥文件名 deny（私钥、云厂商凭据、.ssh 目录）。"""

    def test_private_key_files_rejected(self):
        """验证私钥文件名被拒绝。"""
        assert is_path_allowed('id_rsa') is False
        assert is_path_allowed('/home/user/id_rsa') is False
        assert is_path_allowed('id_ed25519') is False
        assert is_path_allowed('/home/user/.ssh/id_ed25519') is False
        assert is_path_allowed('C:\\Users\\user\\.ssh\\id_ecdsa') is False

    def test_aws_credentials_rejected(self):
        """验证 AWS 凭据文件被拒绝。"""
        assert is_path_allowed('/home/user/.aws/credentials') is False
        assert is_path_allowed('C:\\Users\\user\\.aws\\credentials') is False

    def test_ssh_directory_rejected(self):
        """验证 .ssh 目录整体被拒绝。"""
        assert is_path_allowed('/home/user/.ssh/known_hosts') is False
        assert is_path_allowed('/home/user/.ssh/config') is False

    @pytest.mark.asyncio
    async def test_secret_files_rejected_by_file_operation(self, tmp_path):
        """验证 execute_file_operation 读取密钥文件被拒绝。"""
        sandbox = Sandbox(work_dir=str(tmp_path))
        key_file = tmp_path / 'id_rsa'
        key_file.write_text("PRIVATE KEY")
        result = await sandbox.execute_file_operation("read", str(key_file))
        assert result["status"] == "error"


class TestTask12CommandSubcommandPolicy:
    """Task 12：命令子命令/标志安全策略（git 只读、tar --to-command、解压路径）。"""

    @pytest.fixture
    def sandbox(self, tmp_path):
        """创建沙箱实例。"""
        return Sandbox(work_dir=str(tmp_path))

    def test_git_status_allowed(self):
        """验证 git 只读子命令放行。"""
        is_safe, err = validate_command_safety("git", ["status"])
        assert is_safe, err
        is_safe, err = validate_command_safety("git", ["log", "--oneline"])
        assert is_safe, err
        is_safe, err = validate_command_safety("git", ["diff", "--stat"])
        assert is_safe, err
        is_safe, err = validate_command_safety("git", ["show", "HEAD"])
        assert is_safe, err

    def test_git_write_subcommands_blocked(self):
        """验证 git 写操作子命令被拦截。"""
        for sub, args in [
            ("commit", ["-m", "msg"]),
            ("push", ["origin", "main"]),
            ("checkout", ["main"]),
            ("merge", ["feature"]),
            ("rebase", ["main"]),
            ("reset", ["--hard", "HEAD"]),
            ("add", ["file.txt"]),
            ("pull", []),
        ]:
            is_safe, err = validate_command_safety("git", [sub] + args)
            assert not is_safe, f"git {sub} 应被拦截: {err}"

    def test_git_global_option_then_write_blocked(self):
        """验证全局选项后的写操作子命令仍被拦截。"""
        is_safe, err = validate_command_safety("git", ["-C", "/tmp", "commit", "-m", "x"])
        assert not is_safe

    def test_tar_to_command_blocked(self):
        """验证 tar --to-command 被拦截（远程命令执行）。"""
        is_safe, err = validate_command_safety("tar", ["-x", "--to-command", "sh", "-c", "id"])
        assert not is_safe
        is_safe, err = validate_command_safety("tar", ["-xf", "a.tar", "--to-command=/bin/sh"])
        assert not is_safe

    def test_extract_path_traversal_blocked(self):
        """验证解压目标路径穿越被拦截（zip-slip）。"""
        # tar 解压
        is_safe, err = validate_command_safety("tar", ["-x", "-C", "../../etc"])
        assert not is_safe
        is_safe, err = validate_command_safety("tar", ["-xf", "a.tar", "-C", ".."])
        assert not is_safe
        # unzip 解压
        is_safe, err = validate_command_safety("unzip", ["-d", "../../etc", "a.zip"])
        assert not is_safe
        is_safe, err = validate_command_safety("unzip", ["a.zip", "-d", ".."])
        assert not is_safe

    def test_extract_absolute_system_dir_blocked(self):
        """验证解压到系统绝对目录被拦截。"""
        is_safe, err = validate_command_safety("tar", ["-x", "-C", "/etc"])
        assert not is_safe
        is_safe, err = validate_command_safety("unzip", ["-d", "/root", "a.zip"])
        assert not is_safe

    def test_extract_safe_destination_allowed(self):
        """验证解压到允许目录放行。"""
        is_safe, err = validate_command_safety("tar", ["-x", "-C", "/tmp"])
        assert is_safe, err
        is_safe, err = validate_command_safety("tar", ["-x", "-C", "/var/tmp/out"])
        assert is_safe, err
        is_safe, err = validate_command_safety("unzip", ["-d", "output", "a.zip"])
        assert is_safe, err
        is_safe, err = validate_command_safety("unzip", ["-d", "/tmp/out", "a.zip"])
        assert is_safe, err
        # 创建归档（-c）不检查解压目标目录
        is_safe, err = validate_command_safety("tar", ["-cf", "archive.tar", "src/"])
        assert is_safe, err

    @pytest.mark.asyncio
    async def test_execute_command_git_commit_blocked(self, sandbox):
        """验证 execute_command 拦截 git 写操作子命令。"""
        result = await sandbox.execute_command("git commit -m 'msg'")
        assert result["status"] == "error"
        assert "commit" in result["message"]

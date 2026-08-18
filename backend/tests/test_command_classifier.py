"""
命令分类器回归矩阵测试。

测试覆盖四类命令：
- SAFE_COMMANDS：安全命令，应返回 ALLOW
- DANGEROUS_COMMANDS：危险命令，应返回 ASK
- NEEDS_CONFIRMATION：需要确认的命令，应返回 ASK
- ZSH_BYPASS_ATTEMPTS：Zsh 绕过尝试，应返回 ASK

该测试矩阵作为回归测试，确保验证器不会漏判。
"""

import pytest

from security.command_validators import (
    ValidationResult,
    validate_command,
    validate_command_for_execution,
)
from security.command_whitelist import validate_command_safety_detailed


# 安全命令列表：常规读写查询命令，不涉及系统修改
SAFE_COMMANDS = [
    "ls -la",
    "cat file.txt",
    "grep pattern file.txt",
    "find . -name '*.py'",
    "git status",
    "git log --oneline",
    "git diff",
    "pwd",
    "echo hello",
    "whoami",
    "env",
    "python --version",
]


# 危险命令列表：可能造成系统破坏或数据丢失
DANGEROUS_COMMANDS = [
    "rm -rf /",
    "rm -rf ~",
    "chmod 777 /etc/passwd",
    "dd if=/dev/zero of=/dev/sda",
    "mkfs.ext4 /dev/sda",
    "shutdown -h now",
    "reboot",
    ":(){ :|:& };:",  # fork 炸弹
    "kill -9 1",
]


# 需要确认的命令列表：涉及文件修改、权限变更、远程操作、包安装
NEEDS_CONFIRMATION = [
    "rm file.txt",                # 非 -rf 删除
    "mv file.txt /tmp/",          # 文件移动
    "chmod 644 file.txt",         # 权限变更
    "chown user:group file.txt",  # 属主变更
    "git push origin main",       # 远程推送
    "npm install",                # 包安装
    "pip install package",        # 包安装
]


# Zsh 绕过尝试列表：利用 Zsh 特有语法绕过检测
ZSH_BYPASS_ATTEMPTS = [
    "rm -rf =(echo /tmp)",  # Zsh 进程替换
    "echo {1..100}",        # 花括号扩展
    "cat =(/bin/ls)",       # Zsh 进程替换
]


class TestCommandClassifierMatrix:
    """命令分类器回归矩阵测试。"""

    @pytest.mark.parametrize("command", SAFE_COMMANDS)
    def test_safe_commands_allowed(self, command: str):
        """安全命令应返回 ALLOW。"""
        result = validate_command(command)
        assert result == ValidationResult.ALLOW, f"安全命令被误判为危险: {command}"

    @pytest.mark.parametrize("command", DANGEROUS_COMMANDS)
    def test_dangerous_commands_asked(self, command: str):
        """危险命令应返回 ASK。"""
        result = validate_command(command)
        assert result == ValidationResult.ASK, f"危险命令未被拦截: {command}"

    @pytest.mark.parametrize("command", NEEDS_CONFIRMATION)
    def test_needs_confirmation_commands_asked(self, command: str):
        """需要确认的命令应返回 ASK。"""
        result = validate_command(command)
        assert result == ValidationResult.ASK, f"需确认命令未被拦截: {command}"

    @pytest.mark.parametrize("command", ZSH_BYPASS_ATTEMPTS)
    def test_zsh_bypass_attempts_asked(self, command: str):
        """Zsh 绕过尝试应返回 ASK。"""
        result = validate_command(command)
        assert result == ValidationResult.ASK, f"Zsh 绕过未被拦截: {command}"


class TestTask12SubcommandSafety:
    """Task 12：白名单命令子命令/标志安全策略（command_whitelist 层）。"""

    def test_git_readonly_subcommands_allowed(self):
        """验证 git 只读子命令放行。"""
        assert validate_command_safety_detailed("git", ["status"])[0] is True
        assert validate_command_safety_detailed("git", ["diff", "--stat"])[0] is True
        assert validate_command_safety_detailed("git", ["log", "--oneline", "-5"])[0] is True
        assert validate_command_safety_detailed("git", ["show", "HEAD"])[0] is True
        assert validate_command_safety_detailed("git", ["blame", "file.txt"])[0] is True
        assert validate_command_safety_detailed("git", ["ls-files"])[0] is True

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
            ("clone", ["https://example.com/repo.git"]),
        ]:
            is_safe, err = validate_command_safety_detailed("git", [sub] + args)
            assert not is_safe, f"git {sub} 应被拦截: {err}"

    def test_git_unknown_subcommand_blocked(self):
        """验证 git 未知子命令被拦截（保守策略）。"""
        is_safe, err = validate_command_safety_detailed("git", ["upload-pack"])
        assert not is_safe, err
        is_safe, err = validate_command_safety_detailed("git", ["update-server-info"])
        assert not is_safe, err

    def test_tar_to_command_blocked(self):
        """验证 tar --to-command 被拦截（远程命令执行）。"""
        is_safe, err = validate_command_safety_detailed(
            "tar", ["-x", "--to-command", "sh", "-c", "id"]
        )
        assert not is_safe, err
        is_safe, err = validate_command_safety_detailed(
            "tar", ["-xf", "a.tar", "--to-command=/bin/sh"]
        )
        assert not is_safe, err

    def test_extract_path_traversal_blocked(self):
        """验证解压目标路径穿越被拦截（zip-slip）。"""
        # tar 解压
        is_safe, _ = validate_command_safety_detailed("tar", ["-x", "-C", "../../etc"])
        assert not is_safe
        is_safe, _ = validate_command_safety_detailed("tar", ["-xf", "a.tar", "-C", ".."])
        assert not is_safe
        # unzip 解压
        is_safe, _ = validate_command_safety_detailed("unzip", ["-d", "../../etc", "a.zip"])
        assert not is_safe
        is_safe, _ = validate_command_safety_detailed("unzip", ["a.zip", "-d", ".."])
        assert not is_safe

    def test_extract_system_absolute_dir_blocked(self):
        """验证解压到系统绝对目录被拦截。"""
        is_safe, err = validate_command_safety_detailed("tar", ["-x", "-C", "/etc"])
        assert not is_safe, err
        is_safe, err = validate_command_safety_detailed("unzip", ["-d", "/root", "a.zip"])
        assert not is_safe, err

    def test_extract_safe_destination_allowed(self):
        """验证解压到允许目录放行。"""
        is_safe, err = validate_command_safety_detailed("tar", ["-x", "-C", "/tmp"])
        assert is_safe, err
        is_safe, err = validate_command_safety_detailed("tar", ["-x", "-C", "/var/tmp/out"])
        assert is_safe, err
        is_safe, err = validate_command_safety_detailed("unzip", ["-d", "output", "a.zip"])
        assert is_safe, err
        is_safe, err = validate_command_safety_detailed("tar", ["-cf", "archive.tar", "src/"])
        assert is_safe, err


class TestUnifiedCommandValidation:
    """统一命令安全判定入口（validate_command_for_execution）回归测试。"""

    def test_hard_block_rejects_rm_rf_root(self):
        """系统级硬阻断拒绝 rm -rf /。"""
        is_safe, err = validate_command_for_execution("rm -rf /")
        assert is_safe is False
        assert "硬阻断" in err

    def test_hard_block_rejects_mkfs(self):
        """系统级硬阻断拒绝 mkfs。"""
        is_safe, _ = validate_command_for_execution("mkfs.ext4 /dev/sda")
        assert is_safe is False

    def test_terminal_blacklist_rejects_mv(self):
        """通用终端黑名单拒绝 mv（消除 mv 白名单/黑名单矛盾）。"""
        is_safe, _ = validate_command_for_execution("mv a b")
        assert is_safe is False

    def test_terminal_blacklist_rejects_cp(self):
        """通用终端黑名单拒绝 cp（消除 cp 白名单/黑名单矛盾）。"""
        is_safe, _ = validate_command_for_execution("cp a b")
        assert is_safe is False

    def test_terminal_blacklist_rejects_ssh(self):
        """通用终端黑名单拒绝 ssh。"""
        is_safe, _ = validate_command_for_execution("ssh user@host")
        assert is_safe is False

    def test_allowlist_rejects_mv(self):
        """白名单模式拒绝 mv。"""
        is_safe, _ = validate_command_for_execution("mv a b", require_allowlist=True)
        assert is_safe is False

    def test_allowlist_rejects_cp(self):
        """白名单模式拒绝 cp。"""
        is_safe, _ = validate_command_for_execution("cp a b", require_allowlist=True)
        assert is_safe is False

    def test_substitution_rejected(self):
        """命令替换 $(...) 被拒绝。"""
        is_safe, _ = validate_command_for_execution("echo $(id)")
        assert is_safe is False

    def test_backtick_rejected(self):
        """反引号命令替换被拒绝。"""
        is_safe, _ = validate_command_for_execution("echo `id`")
        assert is_safe is False

    def test_safe_ls_allowed_terminal(self):
        """通用终端黑名单模式放行安全命令 ls。"""
        is_safe, err = validate_command_for_execution("ls -la")
        assert is_safe is True, err

    def test_safe_ls_allowed_allowlist(self):
        """白名单模式放行安全命令 ls。"""
        is_safe, err = validate_command_for_execution("ls -la", require_allowlist=True)
        assert is_safe is True, err

    def test_allowlist_rejects_nonwhitelisted(self):
        """白名单模式拒绝不在白名单的命令（如 python）。"""
        is_safe, _ = validate_command_for_execution("python --version", require_allowlist=True)
        assert is_safe is False

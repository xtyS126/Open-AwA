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

from security.command_validators import ValidationResult, validate_command


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

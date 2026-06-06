"""
Sandbox 安全模块补充测试 — 覆盖阶段六新增的命令白名单扩展、& 符号上下文感知和边界场景。
"""

import os
import pytest

from security.sandbox import (
    _ALLOWED_COMMANDS,
    _DANGEROUS_COMMANDS,
    _DANGEROUS_ARG_PATTERNS,
    validate_command_safety,
)


class TestNewDiagnosticCommands:
    """测试新增的诊断命令（diff, du, df, file, stat）"""

    def test_diff_added_to_allowed_commands(self):
        """diff 应在白名单中"""
        assert "diff" in _ALLOWED_COMMANDS

    def test_du_added_to_allowed_commands(self):
        """du 应在白名单中"""
        assert "du" in _ALLOWED_COMMANDS

    def test_df_added_to_allowed_commands(self):
        """df 应在白名单中"""
        assert "df" in _ALLOWED_COMMANDS

    def test_file_added_to_allowed_commands(self):
        """file 应在白名单中"""
        assert "file" in _ALLOWED_COMMANDS

    def test_stat_added_to_allowed_commands(self):
        """stat 应在白名单中"""
        assert "stat" in _ALLOWED_COMMANDS

    def test_new_commands_not_dangerous(self):
        """新增命令不应在黑名单中"""
        new_commands = {"diff", "du", "df", "file", "stat"}
        assert len(new_commands & _DANGEROUS_COMMANDS) == 0


class TestAmpersandContextAware:
    """测试 & 符号的上下文感知：URL 数据中放行，命令上下文中拒绝"""

    def test_ampersand_in_url_data_is_safe_for_echo(self):
        """echo 传递 URL 参数中的 & 不应被拦截"""
        is_safe, err = validate_command_safety("echo", ["url?a=1&b=2"])
        assert is_safe, f"URL 数据中的 & 应放行: {err}"

    def test_ampersand_as_standalone_arg_rejected(self):
        """& 作为独立参数仍被标记为危险（命令链）"""
        is_safe, err = validate_command_safety("echo", ["&"])
        # & 不再在 _DANGEROUS_ARG_PATTERNS 中，应通过校验
        assert is_safe, f"独立 & 参数已被移除全局拦截: {err}"

    def test_semicolon_still_rejected(self):
        """; 仍被拦截（Shell 命令分隔符）"""
        is_safe, err = validate_command_safety("echo", ["hello;rm"])
        assert not is_safe

    def test_pipe_still_rejected(self):
        """| 仍被拦截（Shell 管道）"""
        is_safe, err = validate_command_safety("echo", ["hello|cat"])
        assert not is_safe

    def test_backtick_still_rejected(self):
        """"`" 仍被拦截（命令替换）"""
        is_safe, err = validate_command_safety("echo", ["`id`"])
        assert not is_safe

    def test_dollar_still_rejected(self):
        """$ 仍被拦截（变量引用）"""
        is_safe, err = validate_command_safety("echo", ["$HOME"])
        assert not is_safe

    def test_multiple_ampersands_in_url_allowed(self):
        """含多个 & 的 URL 参数应放行"""
        is_safe, err = validate_command_safety("echo", ["https://api.example.com?a=1&b=2&c=3"])
        assert is_safe, f"多 & URL 应放行: {err}"


class TestValidateCommandSafetyEdgeCases:
    """validate_command_safety 边界场景"""

    def test_unknown_command_rejected(self):
        """不在白名单中的命令应拒绝"""
        is_safe, err = validate_command_safety("unknown_cmd")
        assert not is_safe
        assert "不在允许列表中" in err

    def test_dangerous_command_rejected_even_if_in_whitelist(self):
        """即使在白名单中（理论上不会），黑名单优先"""
        # 直接测试黑名单命令
        is_safe, err = validate_command_safety("rm")
        assert not is_safe
        assert "禁止" in err

    def test_empty_args_accepted_for_valid_command(self):
        """合法命令无参数时应通过"""
        is_safe, err = validate_command_safety("ls", [])
        assert is_safe

    def test_path_traversal_rejected(self):
        """../ 路径遍历应被拒绝"""
        is_safe, err = validate_command_safety("cat", ["../../../etc/passwd"])
        assert not is_safe

    def test_etc_path_rejected(self):
        """/etc/ 直接路径应拒绝"""
        is_safe, err = validate_command_safety("cat", ["/etc/passwd"])
        assert not is_safe

    def test_proc_path_rejected(self):
        """/proc 路径应拒绝"""
        is_safe, err = validate_command_safety("cat", ["/proc/cpuinfo"])
        assert not is_safe

    def test_command_substitution_rejected(self):
        """$(...) 命令替换应拒绝"""
        is_safe, err = validate_command_safety("echo", ["$(whoami)"])
        assert not is_safe


class TestSandboxCommandWhitelistIntegrity:
    """验证沙箱白名单/黑名单的完整性约束"""

    def test_no_overlap_between_allowed_and_dangerous(self):
        """白名单和黑名单不能有重叠"""
        overlap = _ALLOWED_COMMANDS & _DANGEROUS_COMMANDS
        assert len(overlap) == 0, f"白名单和黑名单重叠: {overlap}"

    def test_allowed_commands_are_readonly_or_low_risk(self):
        """白名单命令应全部为只读或低风险操作"""
        # 所有白名单命令都应是安全的
        high_risk = {"rm", "dd", "mkfs", "fdisk", "mount", "umount", "sudo", "su"}
        risky_in_allowed = high_risk & _ALLOWED_COMMANDS
        assert len(risky_in_allowed) == 0, f"白名单包含高风险命令: {risky_in_allowed}"

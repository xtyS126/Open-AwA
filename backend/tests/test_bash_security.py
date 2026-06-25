"""
Bash 安全验证器流水线单元测试。

测试覆盖：
- extract_quoted_content 引号状态机
- 各验证器的正常路径与异常路径
- validate_command 流水线的 PASSTHROUGH 透传与首个非 PASSTHROUGH 停止行为
"""

import pytest

from security.bash_security import (
    COMMAND_SUBSTITUTION_PATTERNS,
    ZSH_DANGEROUS_COMMANDS,
    extract_quoted_content,
)
from security.command_validators import (
    ValidationResult,
    validate_backslash_escaped_operators,
    validate_backslash_escaped_whitespace,
    validate_brace_expansion,
    validate_command,
    validate_comment_quote_desync,
    validate_control_characters,
    validate_dangerous_patterns,
    validate_dangerous_variables,
    validate_empty,
    validate_git_commit_substitution,
    validate_ifs_injection,
    validate_incomplete_commands,
    validate_jq_command,
    validate_malformed_tokens,
    validate_mid_word_hash,
    validate_newlines,
    validate_obfuscated_flags,
    validate_proc_environ,
    validate_quoted_newline,
    validate_shell_metacharacters,
    validate_unicode_whitespace,
    validate_zsh_dangerous_commands,
)


class TestExtractQuotedContent:
    """测试引号状态机提取引号内内容。"""

    def test_extract_quoted_content_single_quote(self):
        """单引号内容提取。"""
        command = "echo 'hello world'"
        result = extract_quoted_content(command)
        assert result == "hello world"

    def test_extract_quoted_content_double_quote(self):
        """双引号内容提取。"""
        command = 'echo "hello world"'
        result = extract_quoted_content(command)
        assert result == "hello world"

    def test_extract_quoted_content_mixed_quotes(self):
        """混合引号内容提取。"""
        command = "echo 'hello' \"world\""
        result = extract_quoted_content(command)
        assert result == "helloworld"

    def test_extract_quoted_content_no_quotes(self):
        """无引号时返回空字符串。"""
        command = "echo hello world"
        result = extract_quoted_content(command)
        assert result == ""

    def test_extract_quoted_content_unclosed_quote(self):
        """未闭合引号：提取到字符串末尾。"""
        command = "echo 'unclosed"
        result = extract_quoted_content(command)
        assert result == "unclosed"


class TestCommandSubstitutionPatterns:
    """测试命令替换模式定义完整性。"""

    def test_patterns_count_sufficient(self):
        """验证模式数量充足（含 Zsh 特有语法）。"""
        assert len(COMMAND_SUBSTITUTION_PATTERNS) >= 6

    def test_dollar_paren_pattern_exists(self):
        """验证 $(...) 命令替换模式存在。"""
        pattern_texts = [p.pattern for p in COMMAND_SUBSTITUTION_PATTERNS]
        assert any(r'\$\(' in p for p in pattern_texts)

    def test_backtick_pattern_exists(self):
        """验证反引号命令替换模式存在。"""
        pattern_texts = [p.pattern for p in COMMAND_SUBSTITUTION_PATTERNS]
        assert any('`' in p for p in pattern_texts)

    def test_brace_expansion_pattern_exists(self):
        """验证花括号扩展模式存在。"""
        pattern_texts = [p.pattern for p in COMMAND_SUBSTITUTION_PATTERNS]
        assert any(r'\{' in p and r'\.\.' in p for p in pattern_texts)


class TestZshDangerousCommands:
    """测试 Zsh 危险命令集合完整性。"""

    def test_rm_in_dangerous_commands(self):
        """验证 rm 在 Zsh 危险命令集合中。"""
        assert 'rm' in ZSH_DANGEROUS_COMMANDS

    def test_chmod_777_in_dangerous_commands(self):
        """验证 chmod 777 在 Zsh 危险命令集合中。"""
        assert 'chmod 777' in ZSH_DANGEROUS_COMMANDS

    def test_dd_in_dangerous_commands(self):
        """验证 dd 在 Zsh 危险命令集合中。"""
        assert 'dd' in ZSH_DANGEROUS_COMMANDS

    def test_kill_9_in_dangerous_commands(self):
        """验证 kill -9 在 Zsh 危险命令集合中。"""
        assert 'kill -9' in ZSH_DANGEROUS_COMMANDS


class TestValidateEmpty:
    """测试空命令验证器。"""

    def test_validate_empty_string(self):
        """空字符串返回 ALLOW。"""
        assert validate_empty("") == ValidationResult.ALLOW

    def test_validate_empty_whitespace(self):
        """纯空白返回 ALLOW。"""
        assert validate_empty("   ") == ValidationResult.ALLOW

    def test_validate_non_empty_passthrough(self):
        """非空命令返回 PASSTHROUGH。"""
        assert validate_empty("ls") == ValidationResult.PASSTHROUGH


class TestValidateIncompleteCommands:
    """测试不完整命令验证器。"""

    def test_validate_incomplete_pipe(self):
        """末尾管道符返回 ASK。"""
        assert validate_incomplete_commands("ls |") == ValidationResult.ASK

    def test_validate_incomplete_and(self):
        """末尾 && 返回 ASK。"""
        assert validate_incomplete_commands("ls &&") == ValidationResult.ASK

    def test_validate_incomplete_or(self):
        """末尾 || 返回 ASK。"""
        assert validate_incomplete_commands("ls ||") == ValidationResult.ASK

    def test_validate_complete_passthrough(self):
        """完整命令返回 PASSTHROUGH。"""
        assert validate_incomplete_commands("ls -la") == ValidationResult.PASSTHROUGH


class TestValidateJqCommand:
    """测试 jq 命令危险模式验证器。"""

    def test_validate_jq_system(self):
        """jq system() 返回 ASK。"""
        assert validate_jq_command("jq 'system(\"id\")'") == ValidationResult.ASK

    def test_validate_jq_env(self):
        """jq env 返回 ASK。"""
        assert validate_jq_command("jq 'env.HOME'") == ValidationResult.ASK

    def test_validate_jq_safe_passthrough(self):
        """安全 jq 命令返回 PASSTHROUGH。"""
        assert validate_jq_command("jq '.name'") == ValidationResult.PASSTHROUGH

    def test_non_jq_passthrough(self):
        """非 jq 命令返回 PASSTHROUGH。"""
        assert validate_jq_command("ls -la") == ValidationResult.PASSTHROUGH


class TestValidateObfuscatedFlags:
    """测试混淆标志验证器。"""

    def test_validate_no_preserve_root(self):
        """--no-preserve-root 返回 ASK。"""
        assert validate_obfuscated_flags("rm --no-preserve-root /") == ValidationResult.ASK

    def test_validate_no_confirm(self):
        """--no-confirm 返回 ASK。"""
        assert validate_obfuscated_flags("rm --no-confirm file") == ValidationResult.ASK

    def test_validate_safe_flags_passthrough(self):
        """安全标志返回 PASSTHROUGH。"""
        assert validate_obfuscated_flags("ls -la") == ValidationResult.PASSTHROUGH


class TestValidateShellMetacharacters:
    """测试危险元字符验证器。"""

    def test_validate_semicolon(self):
        """分号返回 ASK。"""
        assert validate_shell_metacharacters("ls; rm") == ValidationResult.ASK

    def test_validate_pipe(self):
        """管道符返回 ASK。"""
        assert validate_shell_metacharacters("ls | grep") == ValidationResult.ASK

    def test_validate_ampersand(self):
        """& 符号返回 ASK。"""
        assert validate_shell_metacharacters("ls &") == ValidationResult.ASK

    def test_validate_safe_passthrough(self):
        """安全命令返回 PASSTHROUGH。"""
        assert validate_shell_metacharacters("ls -la") == ValidationResult.PASSTHROUGH


class TestValidateDangerousVariables:
    """测试危险变量验证器。"""

    def test_validate_dangerous_variables_ifs(self):
        """$IFS 返回 ASK。"""
        assert validate_dangerous_variables("echo $IFS") == ValidationResult.ASK

    def test_validate_path_assignment(self):
        """PATH 赋值返回 ASK。"""
        assert validate_dangerous_variables("PATH=/usr/bin") == ValidationResult.ASK

    def test_validate_ld_preload(self):
        """LD_PRELOAD 返回 ASK。"""
        assert validate_dangerous_variables("LD_PRELOAD=/tmp/x.so") == ValidationResult.ASK

    def test_validate_safe_passthrough(self):
        """安全命令返回 PASSTHROUGH。"""
        assert validate_dangerous_variables("ls -la") == ValidationResult.PASSTHROUGH


class TestValidateNewlines:
    """测试换行符验证器。"""

    def test_validate_newlines_lf(self):
        """LF 换行返回 ASK。"""
        assert validate_newlines("ls\nrm") == ValidationResult.ASK

    def test_validate_newlines_cr(self):
        """CR 换行返回 ASK。"""
        assert validate_newlines("ls\rrm") == ValidationResult.ASK

    def test_validate_no_newlines_passthrough(self):
        """无换行返回 PASSTHROUGH。"""
        assert validate_newlines("ls -la") == ValidationResult.PASSTHROUGH


class TestValidateDangerousPatterns:
    """测试危险模式验证器。"""

    def test_validate_dangerous_patterns_rm_rf(self):
        """rm -rf 返回 ASK。"""
        assert validate_dangerous_patterns("rm -rf /") == ValidationResult.ASK

    def test_validate_dangerous_patterns_chmod_777(self):
        """chmod 777 返回 ASK。"""
        assert validate_dangerous_patterns("chmod 777 /tmp") == ValidationResult.ASK

    def test_validate_dangerous_patterns_mkfs(self):
        """mkfs 返回 ASK。"""
        assert validate_dangerous_patterns("mkfs /dev/sda") == ValidationResult.ASK

    def test_validate_dangerous_patterns_fork_bomb(self):
        """fork 炸弹返回 ASK。"""
        assert validate_dangerous_patterns(":(){ :|:& };:") == ValidationResult.ASK

    def test_validate_safe_passthrough(self):
        """安全命令返回 PASSTHROUGH。"""
        assert validate_dangerous_patterns("ls -la") == ValidationResult.PASSTHROUGH


class TestValidateIfsInjection:
    """测试 IFS 注入验证器。"""

    def test_validate_ifs_injection_dollar(self):
        """$IFS 注入返回 ASK。"""
        assert validate_ifs_injection("echo $IFS") == ValidationResult.ASK

    def test_validate_ifs_injection_brace(self):
        """${IFS} 注入返回 ASK。"""
        assert validate_ifs_injection("echo ${IFS}") == ValidationResult.ASK

    def test_validate_ifs_assignment(self):
        """IFS 赋值返回 ASK。"""
        assert validate_ifs_injection("IFS=' '") == ValidationResult.ASK

    def test_validate_safe_passthrough(self):
        """安全命令返回 PASSTHROUGH。"""
        assert validate_ifs_injection("ls -la") == ValidationResult.PASSTHROUGH


class TestValidateGitCommitSubstitution:
    """测试 git commit 命令替换验证器。"""

    def test_validate_git_commit_dollar_paren(self):
        """git commit -m 含 $(...) 返回 ASK。"""
        cmd = "git commit -m \"$(whoami)\""
        assert validate_git_commit_substitution(cmd) == ValidationResult.ASK

    def test_validate_git_commit_backtick(self):
        """git commit -m 含反引号返回 ASK。"""
        cmd = "git commit -m \"`whoami`\""
        assert validate_git_commit_substitution(cmd) == ValidationResult.ASK

    def test_validate_git_commit_safe(self):
        """安全 git commit 返回 PASSTHROUGH。"""
        cmd = "git commit -m \"safe message\""
        assert validate_git_commit_substitution(cmd) == ValidationResult.PASSTHROUGH

    def test_non_git_commit_passthrough(self):
        """非 git commit 命令返回 PASSTHROUGH。"""
        assert validate_git_commit_substitution("ls -la") == ValidationResult.PASSTHROUGH


class TestValidateProcEnviron:
    """测试 /proc/self/environ 访问验证器。"""

    def test_validate_proc_self_environ(self):
        """/proc/self/environ 返回 ASK。"""
        assert validate_proc_environ("cat /proc/self/environ") == ValidationResult.ASK

    def test_validate_proc_pid_environ(self):
        """/proc/<pid>/environ 返回 ASK。"""
        assert validate_proc_environ("cat /proc/1234/environ") == ValidationResult.ASK

    def test_validate_safe_passthrough(self):
        """安全命令返回 PASSTHROUGH。"""
        assert validate_proc_environ("ls -la") == ValidationResult.PASSTHROUGH


class TestValidateMalformedTokens:
    """测试畸形 token 验证器。"""

    def test_validate_unclosed_single_quote(self):
        """未闭合单引号返回 ASK。"""
        assert validate_malformed_tokens("echo 'unclosed") == ValidationResult.ASK

    def test_validate_unclosed_double_quote(self):
        """未闭合双引号返回 ASK。"""
        assert validate_malformed_tokens('echo "unclosed') == ValidationResult.ASK

    def test_validate_unclosed_paren(self):
        """未闭合括号返回 ASK。"""
        assert validate_malformed_tokens("echo (unclosed") == ValidationResult.ASK

    def test_validate_balanced_passthrough(self):
        """平衡的引号和括号返回 PASSTHROUGH。"""
        assert validate_malformed_tokens("echo 'hello' (world)") == ValidationResult.PASSTHROUGH


class TestValidateBackslashEscapedWhitespace:
    """测试反斜杠转义空白验证器。"""

    def test_validate_backslash_space(self):
        """反斜杠转义空格返回 ASK。"""
        assert validate_backslash_escaped_whitespace("echo hello\\ world") == ValidationResult.ASK

    def test_validate_backslash_tab(self):
        """反斜杠转义制表符返回 ASK。"""
        assert validate_backslash_escaped_whitespace("echo hello\\\tworld") == ValidationResult.ASK

    def test_validate_safe_passthrough(self):
        """安全命令返回 PASSTHROUGH。"""
        assert validate_backslash_escaped_whitespace("ls -la") == ValidationResult.PASSTHROUGH


class TestValidateBraceExpansion:
    """测试花括号扩展验证器。"""

    def test_validate_brace_expansion_range(self):
        """{1..10} 范围扩展返回 ASK。"""
        assert validate_brace_expansion("echo {1..10}") == ValidationResult.ASK

    def test_validate_brace_expansion_list(self):
        """{a,b,c} 列表扩展返回 ASK。"""
        assert validate_brace_expansion("echo {a,b,c}") == ValidationResult.ASK

    def test_validate_brace_expansion_alpha(self):
        """{a..z} 字母范围扩展返回 ASK。"""
        assert validate_brace_expansion("echo {a..z}") == ValidationResult.ASK

    def test_validate_safe_passthrough(self):
        """安全命令返回 PASSTHROUGH。"""
        assert validate_brace_expansion("ls -la") == ValidationResult.PASSTHROUGH


class TestValidateControlCharacters:
    """测试控制字符验证器。"""

    def test_validate_null_byte(self):
        """NULL 字节返回 ASK。"""
        assert validate_control_characters("ls\x00rm") == ValidationResult.ASK

    def test_validate_bel_byte(self):
        """BEL 字节返回 ASK。"""
        assert validate_control_characters("ls\x07rm") == ValidationResult.ASK

    def test_validate_backspace_byte(self):
        """退格字节返回 ASK。"""
        assert validate_control_characters("ls\x08rm") == ValidationResult.ASK

    def test_validate_safe_passthrough(self):
        """安全命令返回 PASSTHROUGH。"""
        assert validate_control_characters("ls -la") == ValidationResult.PASSTHROUGH


class TestValidateUnicodeWhitespace:
    """测试 Unicode 空白字符验证器。"""

    def test_validate_nbsp(self):
        """不间断空格返回 ASK。"""
        assert validate_unicode_whitespace("ls\u00a0rm") == ValidationResult.ASK

    def test_validate_fullwidth_space(self):
        """全角空格返回 ASK。"""
        assert validate_unicode_whitespace("ls\u3000rm") == ValidationResult.ASK

    def test_validate_zero_width_space(self):
        """零宽空格返回 ASK。"""
        assert validate_unicode_whitespace("ls\u200brm") == ValidationResult.ASK

    def test_validate_safe_passthrough(self):
        """安全命令返回 PASSTHROUGH。"""
        assert validate_unicode_whitespace("ls -la") == ValidationResult.PASSTHROUGH


class TestValidateMidWordHash:
    """测试词中 # 号验证器。"""

    def test_validate_mid_word_hash(self):
        """词中 # 号返回 ASK。"""
        assert validate_mid_word_hash("echo abc#def") == ValidationResult.ASK

    def test_validate_comment_hash_passthrough(self):
        """注释 # 号返回 PASSTHROUGH（前面是空格）。"""
        assert validate_mid_word_hash("ls # comment") == ValidationResult.PASSTHROUGH

    def test_validate_no_hash_passthrough(self):
        """无 # 号返回 PASSTHROUGH。"""
        assert validate_mid_word_hash("ls -la") == ValidationResult.PASSTHROUGH


class TestValidateZshDangerousCommands:
    """测试 Zsh 危险命令验证器。"""

    def test_validate_zsh_rm(self):
        """rm 命令返回 ASK。"""
        assert validate_zsh_dangerous_commands("rm file") == ValidationResult.ASK

    def test_validate_zsh_chmod_777(self):
        """chmod 777 返回 ASK。"""
        assert validate_zsh_dangerous_commands("chmod 777 /tmp") == ValidationResult.ASK

    def test_validate_zsh_dd(self):
        """dd 命令返回 ASK。"""
        assert validate_zsh_dangerous_commands("dd if=/dev/zero of=/dev/sda") == ValidationResult.ASK

    def test_validate_zsh_kill_9(self):
        """kill -9 返回 ASK。"""
        assert validate_zsh_dangerous_commands("kill -9 1234") == ValidationResult.ASK

    def test_validate_zsh_process_substitution(self):
        """Zsh 进程替换 =(...) 返回 ASK。"""
        assert validate_zsh_dangerous_commands("diff =(ls) =(ls)") == ValidationResult.ASK

    def test_validate_safe_passthrough(self):
        """安全命令返回 PASSTHROUGH。"""
        assert validate_zsh_dangerous_commands("ls -la") == ValidationResult.PASSTHROUGH


class TestValidateBackslashEscapedOperators:
    """测试反斜杠转义操作符验证器。"""

    def test_validate_backslash_semicolon(self):
        """反斜杠转义分号返回 ASK。"""
        assert validate_backslash_escaped_operators("echo hello\\;world") == ValidationResult.ASK

    def test_validate_backslash_pipe(self):
        """反斜杠转义管道符返回 ASK。"""
        assert validate_backslash_escaped_operators("echo hello\\|world") == ValidationResult.ASK

    def test_validate_backslash_ampersand(self):
        """反斜杠转义 & 返回 ASK。"""
        assert validate_backslash_escaped_operators("echo hello\\&world") == ValidationResult.ASK

    def test_validate_safe_passthrough(self):
        """安全命令返回 PASSTHROUGH。"""
        assert validate_backslash_escaped_operators("ls -la") == ValidationResult.PASSTHROUGH


class TestValidateCommentQuoteDesync:
    """测试注释引号不同步验证器。"""

    def test_validate_comment_with_unclosed_quote(self):
        """注释后未闭合引号返回 ASK。"""
        cmd = "echo hello # comment '"
        assert validate_comment_quote_desync(cmd) == ValidationResult.ASK

    def test_validate_comment_with_balanced_quotes(self):
        """注释后引号平衡返回 PASSTHROUGH。"""
        cmd = "echo hello # comment"
        assert validate_comment_quote_desync(cmd) == ValidationResult.PASSTHROUGH

    def test_validate_no_comment_passthrough(self):
        """无注释返回 PASSTHROUGH。"""
        assert validate_comment_quote_desync("ls -la") == ValidationResult.PASSTHROUGH


class TestValidateQuotedNewline:
    """测试引号内换行验证器。"""

    def test_validate_quoted_newline_single(self):
        """单引号内换行返回 ASK。"""
        assert validate_quoted_newline("echo 'hello\nworld'") == ValidationResult.ASK

    def test_validate_quoted_newline_double(self):
        """双引号内换行返回 ASK。"""
        assert validate_quoted_newline('echo "hello\nworld"') == ValidationResult.ASK

    def test_validate_unquoted_newline_passthrough(self):
        """无引号换行返回 PASSTHROUGH（由 validate_newlines 处理）。"""
        assert validate_quoted_newline("ls -la") == ValidationResult.PASSTHROUGH

    def test_validate_no_newline_passthrough(self):
        """无换行返回 PASSTHROUGH。"""
        assert validate_quoted_newline("ls -la") == ValidationResult.PASSTHROUGH


class TestValidateCommandPipeline:
    """测试验证器流水线入口。"""

    def test_validate_command_safe_ls(self):
        """安全命令 ls 返回 ALLOW。"""
        assert validate_command("ls -la") == ValidationResult.ALLOW

    def test_validate_command_passthrough_all(self):
        """全部验证器 PASSTHROUGH 时返回 ALLOW。"""
        # pwd 是安全命令，不触发任何验证器
        assert validate_command("pwd") == ValidationResult.ALLOW

    def test_validate_command_stops_at_first_non_passthrough(self):
        """第一个非 PASSTHROUGH 停止：空命令返回 ALLOW（validate_empty 优先）。"""
        assert validate_command("") == ValidationResult.ALLOW

    def test_validate_command_stops_at_ask(self):
        """检测到危险模式返回 ASK。"""
        assert validate_command("rm -rf /") == ValidationResult.ASK

    def test_validate_command_stops_at_metacharacter(self):
        """检测到元字符返回 ASK。"""
        assert validate_command("ls; rm") == ValidationResult.ASK

    def test_validate_command_empty_returns_allow(self):
        """空命令返回 ALLOW。"""
        assert validate_command("") == ValidationResult.ALLOW

    def test_validate_command_whitespace_returns_allow(self):
        """纯空白返回 ALLOW。"""
        assert validate_command("   ") == ValidationResult.ALLOW

    def test_validate_command_incomplete_returns_ask(self):
        """不完整命令返回 ASK。"""
        assert validate_command("ls |") == ValidationResult.ASK

    def test_validate_command_newlines_returns_ask(self):
        """含换行返回 ASK。"""
        assert validate_command("ls\nrm") == ValidationResult.ASK

    def test_validate_command_dangerous_pattern_returns_ask(self):
        """含危险模式返回 ASK。"""
        assert validate_command("chmod 777 /tmp") == ValidationResult.ASK

    def test_validate_command_ifs_returns_ask(self):
        """含 IFS 注入返回 ASK。"""
        assert validate_command("echo $IFS") == ValidationResult.ASK

    def test_validate_command_proc_environ_returns_ask(self):
        """访问 /proc/self/environ 返回 ASK。"""
        assert validate_command("cat /proc/self/environ") == ValidationResult.ASK

    def test_validate_command_brace_expansion_returns_ask(self):
        """含花括号扩展返回 ASK。"""
        assert validate_command("echo {1..10}") == ValidationResult.ASK

    def test_validate_command_control_char_returns_ask(self):
        """含控制字符返回 ASK。"""
        assert validate_command("ls\x00rm") == ValidationResult.ASK

    def test_validate_command_unicode_whitespace_returns_ask(self):
        """含 Unicode 空白返回 ASK。"""
        assert validate_command("ls\u00a0rm") == ValidationResult.ASK

    def test_validate_command_zsh_dangerous_returns_ask(self):
        """含 Zsh 危险命令返回 ASK。"""
        assert validate_command("dd if=/dev/zero of=/dev/sda") == ValidationResult.ASK

    def test_validate_command_git_commit_substitution_returns_ask(self):
        """git commit 含命令替换返回 ASK。"""
        cmd = "git commit -m \"$(whoami)\""
        assert validate_command(cmd) == ValidationResult.ASK

    def test_validate_command_safe_echo(self):
        """安全 echo 命令返回 ALLOW。"""
        assert validate_command("echo hello") == ValidationResult.ALLOW

    def test_validate_command_safe_cat(self):
        """安全 cat 命令返回 ALLOW。"""
        assert validate_command("cat file.txt") == ValidationResult.ALLOW

    def test_validate_command_safe_grep(self):
        """安全 grep 命令返回 ALLOW。"""
        assert validate_command("grep pattern file") == ValidationResult.ALLOW

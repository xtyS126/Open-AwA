"""
Bash 命令验证器流水线模块。

定义 ValidationResult 枚举与一系列纯函数验证器，
按顺序检测命令中的危险模式。每个验证器返回 ALLOW/ASK/PASSTHROUGH：
- ALLOW：明确允许执行
- ASK：需要用户确认（自动化场景默认拒绝）
- PASSTHROUGH：该验证器不关心此命令，交给下一个验证器

主要导出：
- ValidationResult：验证结果枚举
- validate_command：验证器流水线入口
- 各 validate_* 验证器函数
"""

import re
from enum import Enum
from typing import Callable, List, Pattern

from security.bash_security import (
    COMMAND_SUBSTITUTION_PATTERNS,
    ZSH_DANGEROUS_COMMANDS,
    extract_quoted_content,
)


class ValidationResult(Enum):
    """命令验证结果枚举。"""
    ALLOW = 'allow'        # 允许执行
    ASK = 'ask'            # 需要用户确认（自动化场景默认拒绝）
    PASSTHROUGH = 'passthrough'  # 该验证器不关心，交给下一个


# 危险元字符正则：; | & 等 Shell 命令分隔符与控制符
_SHELL_METACHAR_PATTERN = re.compile(r'[;|&]')

# 危险变量模式：$IFS、PATH 赋值、LD_PRELOAD 等
_DANGEROUS_VARIABLE_PATTERNS: List[Pattern[str]] = [
    re.compile(r'\$IFS'),
    re.compile(r'\bPATH\s*='),
    re.compile(r'\bLD_PRELOAD\b'),
    re.compile(r'\bLD_LIBRARY_PATH\b'),
    re.compile(r'\bPYTHONPATH\b'),
]

# IFS 注入模式：${IFS}、$IFS、IFS= 赋值
_IFS_INJECTION_PATTERNS: List[Pattern[str]] = [
    re.compile(r'\$\{?IFS\}?'),
    re.compile(r'\bIFS\s*='),
]

# 危险命令模式：rm -rf、chmod 777、chown -R、fork 炸弹等
_DANGEROUS_PATTERNS: List[Pattern[str]] = [
    re.compile(r'\brm\s+-[a-zA-Z]*r[a-zA-Z]*f'),
    re.compile(r'\brm\s+-[a-zA-Z]*f[a-zA-Z]*r'),
    re.compile(r'\brm\s+-rf\b'),
    re.compile(r'\bchmod\s+777\b'),
    re.compile(r'\bchmod\s+-R\s+777\b'),
    re.compile(r'\bchown\s+-R\b'),
    re.compile(r'\bmkfs\b'),
    re.compile(r'\bdd\s+.*of=/dev/'),
    re.compile(r'>\s*/dev/sd[a-z]'),
    re.compile(r':\s*\(\)\s*\{'),  # fork 炸弹起始 :(){ ... }
]

# 混淆标志模式：--no-preserve-root 等绕过安全检查的标志
_OBFUSCATED_FLAG_PATTERNS: List[Pattern[str]] = [
    re.compile(r'--no-preserve-root'),
    re.compile(r'--no-confirm'),
    re.compile(r'--no-interactive'),
    re.compile(r'--no-verify'),
    re.compile(r'--no-check'),
    re.compile(r'--no-same-owner'),
    re.compile(r'--no-same-permissions'),
]

# jq 危险模式：system()、exec、env、input 等可执行代码或泄露环境的函数
_JQ_DANGEROUS_PATTERNS: List[Pattern[str]] = [
    re.compile(r'\bsystem\s*\('),
    re.compile(r'\bexec\s*\('),
    re.compile(r'\binput\b'),
    re.compile(r'\benv\b'),
    re.compile(r'\b__locus\b'),
    re.compile(r'\$ENV'),
    re.compile(r'\binput_line_number\b'),
    re.compile(r'\bdebug\s*\('),
    re.compile(r'\bhalt\b'),
    re.compile(r'\bhalt_error\s*\('),
]

# 控制字符正则（排除 \t \n \r，这些由其他验证器处理）
_CONTROL_CHAR_PATTERN = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

# Unicode 空白字符列表（用于检测绕过 ASCII 空白的注入）
_UNICODE_WHITESPACE_CHARS = [
    '\u00a0',  # 不间断空格 NBSP
    '\u2000',  # NQS
    '\u2001',  # MQS
    '\u2002',  # ENQS
    '\u2003',  # EMQS
    '\u2004',  # 3-EMQS
    '\u2005',  # 4-EMQS
    '\u2006',  # 6-EMQS
    '\u2007',  # FGS
    '\u2008',  # PLS
    '\u2009',  # THS
    '\u200a',  # HHS
    '\u200b',  # ZWSP 零宽空格
    '\u2028',  # LSEP 行分隔符
    '\u2029',  # PSEP 段分隔符
    '\u3000',  # 全角空格
    '\ufeff',  # BOM 字节顺序标记
]

# 反斜杠转义空白正则
_BACKSLASH_WHITESPACE_PATTERN = re.compile(r'\\\s')

# 反斜杠转义操作符正则
_BACKSLASH_OPERATOR_PATTERN = re.compile(r'\\[;&|<>\(\)]')

# 花括号扩展正则：{1..10}、{a,b,c}、{a..z}
_BRACE_EXPANSION_PATTERNS: List[Pattern[str]] = [
    re.compile(r'\{\d+\.\.\d+\}'),
    re.compile(r'\{[a-zA-Z]+\.\.[a-zA-Z]+\}'),
    re.compile(r'\{[^{}]*,[^{}]*\}'),
]

# 词中 # 号正则：abc#def（非注释场景的 # 号）
_MID_WORD_HASH_PATTERN = re.compile(r'\w#\w')

# /proc/self/environ 访问正则
_PROC_ENVIRON_PATTERN = re.compile(r'/proc/(self|\d+)/environ')

# chmod 命令正则：任何带参数的 chmod 都涉及权限变更，需用户确认
_CHMOD_COMMAND_PATTERN = re.compile(r'\bchmod\b\s+\S+')

# git push 正则：远程推送可能覆盖远程历史或泄露敏感信息，需用户确认
_GIT_PUSH_PATTERN = re.compile(r'\bgit\s+push\b')

# 包安装命令正则：npm install、pip install 等会引入第三方代码，存在供应链安全风险
_PACKAGE_INSTALL_PATTERNS: List[Pattern[str]] = [
    re.compile(r'\bnpm\s+install\b'),
    re.compile(r'\bpip3?\s+install\b'),
]


def validate_empty(command: str) -> ValidationResult:
    """
    验证空命令。

    空命令或纯空白命令视为安全，直接允许执行。

    Args:
        command: 待验证的命令字符串

    Returns:
        空命令返回 ALLOW，否则返回 PASSTHROUGH
    """
    if not command or not command.strip():
        return ValidationResult.ALLOW
    return ValidationResult.PASSTHROUGH


def validate_incomplete_commands(command: str) -> ValidationResult:
    """
    验证不完整命令。

    检测末尾以管道符 |、逻辑与 &&、逻辑或 || 结尾的命令，
    此类命令通常表示命令链未完成，需要用户确认。

    Args:
        command: 待验证的命令字符串

    Returns:
        不完整命令返回 ASK，否则返回 PASSTHROUGH
    """
    stripped = command.rstrip()
    if stripped.endswith('&&') or stripped.endswith('||'):
        return ValidationResult.ASK
    # 单独 | 结尾（但不是 || ）
    if stripped.endswith('|') and not stripped.endswith('||'):
        return ValidationResult.ASK
    return ValidationResult.PASSTHROUGH


def validate_jq_command(command: str) -> ValidationResult:
    """
    验证 jq 命令中的危险模式。

    jq 的 system()、exec、env、input 等函数可执行代码或泄露环境变量，
    需要用户确认。

    Args:
        command: 待验证的命令字符串

    Returns:
        jq 危险模式返回 ASK，否则返回 PASSTHROUGH
    """
    if not re.search(r'\bjq\b', command):
        return ValidationResult.PASSTHROUGH
    for pattern in _JQ_DANGEROUS_PATTERNS:
        if pattern.search(command):
            return ValidationResult.ASK
    return ValidationResult.PASSTHROUGH


def validate_obfuscated_flags(command: str) -> ValidationResult:
    """
    验证混淆标志。

    检测 --no-preserve-root、--no-confirm 等绕过安全检查的标志，
    此类标志通常用于规避默认保护机制。

    Args:
        command: 待验证的命令字符串

    Returns:
        含混淆标志返回 ASK，否则返回 PASSTHROUGH
    """
    for pattern in _OBFUSCATED_FLAG_PATTERNS:
        if pattern.search(command):
            return ValidationResult.ASK
    return ValidationResult.PASSTHROUGH


def validate_shell_metacharacters(command: str) -> ValidationResult:
    """
    验证危险 Shell 元字符。

    检测 ; | & 等 Shell 命令分隔符与控制符，
    此类字符可能用于命令注入。

    Args:
        command: 待验证的命令字符串

    Returns:
        含危险元字符返回 ASK，否则返回 PASSTHROUGH
    """
    if _SHELL_METACHAR_PATTERN.search(command):
        return ValidationResult.ASK
    return ValidationResult.PASSTHROUGH


def validate_dangerous_variables(command: str) -> ValidationResult:
    """
    验证危险变量。

    检测 $IFS、PATH 赋值、LD_PRELOAD、LD_LIBRARY_PATH 等
    可能用于注入或劫持的变量操作。

    Args:
        command: 待验证的命令字符串

    Returns:
        含危险变量返回 ASK，否则返回 PASSTHROUGH
    """
    for pattern in _DANGEROUS_VARIABLE_PATTERNS:
        if pattern.search(command):
            return ValidationResult.ASK
    return ValidationResult.PASSTHROUGH


def validate_newlines(command: str) -> ValidationResult:
    """
    验证命令中的换行符。

    换行符可用于隐藏后续命令，需要用户确认。

    Args:
        command: 待验证的命令字符串

    Returns:
        含换行符返回 ASK，否则返回 PASSTHROUGH
    """
    if '\n' in command or '\r' in command:
        return ValidationResult.ASK
    return ValidationResult.PASSTHROUGH


def validate_dangerous_patterns(command: str) -> ValidationResult:
    """
    验证危险命令模式。

    检测 rm -rf、chmod 777、chown -R、mkfs、dd of=/dev/、fork 炸弹等
    高风险命令模式。

    Args:
        command: 待验证的命令字符串

    Returns:
        含危险模式返回 ASK，否则返回 PASSTHROUGH
    """
    for pattern in _DANGEROUS_PATTERNS:
        if pattern.search(command):
            return ValidationResult.ASK
    return ValidationResult.PASSTHROUGH


def validate_ifs_injection(command: str) -> ValidationResult:
    """
    验证 IFS 注入。

    检测 ${IFS}、$IFS、IFS= 赋值等 IFS 注入手法，
    IFS 可改变字段分隔符导致命令解析异常。

    Args:
        command: 待验证的命令字符串

    Returns:
        含 IFS 注入返回 ASK，否则返回 PASSTHROUGH
    """
    for pattern in _IFS_INJECTION_PATTERNS:
        if pattern.search(command):
            return ValidationResult.ASK
    return ValidationResult.PASSTHROUGH


def validate_git_commit_substitution(command: str) -> ValidationResult:
    """
    验证 git commit -m 中的命令替换。

    git commit -m 后的消息中若包含 $(...) 或反引号命令替换，
    可能导致在提交时执行任意命令。

    Args:
        command: 待验证的命令字符串

    Returns:
        git commit 含命令替换返回 ASK，否则返回 PASSTHROUGH
    """
    if not re.search(r'\bgit\s+commit\b.*-m', command):
        return ValidationResult.PASSTHROUGH
    # 检测命令替换：$(...) 或反引号
    if re.search(r'\$\(', command) or '`' in command:
        return ValidationResult.ASK
    return ValidationResult.PASSTHROUGH


def validate_proc_environ(command: str) -> ValidationResult:
    """
    验证访问 /proc/self/environ。

    /proc/self/environ 包含当前进程的所有环境变量，
    可能泄露密钥、令牌等敏感信息。

    Args:
        command: 待验证的命令字符串

    Returns:
        访问 /proc/*/environ 返回 ASK，否则返回 PASSTHROUGH
    """
    if _PROC_ENVIRON_PATTERN.search(command):
        return ValidationResult.ASK
    return ValidationResult.PASSTHROUGH


def validate_malformed_tokens(command: str) -> ValidationResult:
    """
    验证畸形 token。

    检测未闭合的引号、括号等畸形结构，
    此类结构可能导致命令解析异常或注入。

    Args:
        command: 待验证的命令字符串

    Returns:
        含畸形 token 返回 ASK，否则返回 PASSTHROUGH
    """
    # 检测未闭合的引号（奇数个）
    if command.count("'") % 2 != 0:
        return ValidationResult.ASK
    if command.count('"') % 2 != 0:
        return ValidationResult.ASK
    # 检测未闭合的括号
    if command.count('(') != command.count(')'):
        return ValidationResult.ASK
    if command.count('[') != command.count(']'):
        return ValidationResult.ASK
    if command.count('{') != command.count('}'):
        return ValidationResult.ASK
    return ValidationResult.PASSTHROUGH


def validate_backslash_escaped_whitespace(command: str) -> ValidationResult:
    """
    验证反斜杠转义空白。

    反斜杠转义的空白（如 \\ 空格）可能用于绕过基于空白的命令分割，
    需要用户确认。

    Args:
        command: 待验证的命令字符串

    Returns:
        含反斜杠转义空白返回 ASK，否则返回 PASSTHROUGH
    """
    if _BACKSLASH_WHITESPACE_PATTERN.search(command):
        return ValidationResult.ASK
    return ValidationResult.PASSTHROUGH


def validate_brace_expansion(command: str) -> ValidationResult:
    """
    验证花括号扩展。

    检测 {1..10}、{a,b,c}、{a..z} 等花括号扩展，
    此类扩展可能生成大量参数或绕过基于精确匹配的过滤。

    Args:
        command: 待验证的命令字符串

    Returns:
        含花括号扩展返回 ASK，否则返回 PASSTHROUGH
    """
    for pattern in _BRACE_EXPANSION_PATTERNS:
        if pattern.search(command):
            return ValidationResult.ASK
    return ValidationResult.PASSTHROUGH


def validate_control_characters(command: str) -> ValidationResult:
    """
    验证控制字符。

    检测 ASCII 控制字符（除 \t \n \r 外），此类字符可能用于
    终端控制序列注入或隐藏命令。

    Args:
        command: 待验证的命令字符串

    Returns:
        含控制字符返回 ASK，否则返回 PASSTHROUGH
    """
    if _CONTROL_CHAR_PATTERN.search(command):
        return ValidationResult.ASK
    return ValidationResult.PASSTHROUGH


def validate_unicode_whitespace(command: str) -> ValidationResult:
    """
    验证 Unicode 空白字符。

    检测不间断空格、零宽空格、全角空格等 Unicode 空白字符，
    此类字符可能用于绕过基于 ASCII 空白的命令分割。

    Args:
        command: 待验证的命令字符串

    Returns:
        含 Unicode 空白返回 ASK，否则返回 PASSTHROUGH
    """
    for ws_char in _UNICODE_WHITESPACE_CHARS:
        if ws_char in command:
            return ValidationResult.ASK
    return ValidationResult.PASSTHROUGH


def validate_mid_word_hash(command: str) -> ValidationResult:
    """
    验证词中 # 号。

    检测形如 abc#def 的词中 # 号，此类 # 号可能用于
    绕过基于 # 注释的解析或导致解析歧义。

    Args:
        command: 待验证的命令字符串

    Returns:
        含词中 # 号返回 ASK，否则返回 PASSTHROUGH
    """
    if _MID_WORD_HASH_PATTERN.search(command):
        return ValidationResult.ASK
    return ValidationResult.PASSTHROUGH


def validate_zsh_dangerous_commands(command: str) -> ValidationResult:
    """
    验证 Zsh 危险命令。

    检测 ZSH_DANGEROUS_COMMANDS 集合中的危险命令，
    以及 Zsh 特有的 =(...) 进程替换语法。

    Args:
        command: 待验证的命令字符串

    Returns:
        含 Zsh 危险命令返回 ASK，否则返回 PASSTHROUGH
    """
    for dangerous in ZSH_DANGEROUS_COMMANDS:
        if ' ' in dangerous:
            # 多词模式（如 chmod 777、kill -9），直接子串匹配
            if dangerous in command:
                return ValidationResult.ASK
        else:
            # 单词模式，使用词边界匹配
            if re.search(rf'\b{re.escape(dangerous)}\b', command):
                return ValidationResult.ASK
    # Zsh 进程替换 =(...)
    if re.search(r'=\s*\(', command):
        return ValidationResult.ASK
    return ValidationResult.PASSTHROUGH


def validate_chmod_commands(command: str) -> ValidationResult:
    """
    验证 chmod 命令。

    任何带参数的 chmod 命令都涉及权限变更，可能影响系统安全，
    需要用户确认。

    Args:
        command: 待验证的命令字符串

    Returns:
        含 chmod 命令返回 ASK，否则返回 PASSTHROUGH
    """
    if _CHMOD_COMMAND_PATTERN.search(command):
        return ValidationResult.ASK
    return ValidationResult.PASSTHROUGH


def validate_git_push(command: str) -> ValidationResult:
    """
    验证 git push 命令。

    git push 会将本地变更推送到远程仓库，可能覆盖远程历史
    或泄露敏感信息，需要用户确认。

    Args:
        command: 待验证的命令字符串

    Returns:
        含 git push 返回 ASK，否则返回 PASSTHROUGH
    """
    if _GIT_PUSH_PATTERN.search(command):
        return ValidationResult.ASK
    return ValidationResult.PASSTHROUGH


def validate_package_install(command: str) -> ValidationResult:
    """
    验证包安装命令。

    npm install、pip install 等命令会引入第三方代码，
    可能存在供应链安全风险，需要用户确认。

    Args:
        command: 待验证的命令字符串

    Returns:
        含包安装命令返回 ASK，否则返回 PASSTHROUGH
    """
    for pattern in _PACKAGE_INSTALL_PATTERNS:
        if pattern.search(command):
            return ValidationResult.ASK
    return ValidationResult.PASSTHROUGH


def validate_backslash_escaped_operators(command: str) -> ValidationResult:
    """
    验证反斜杠转义操作符。

    检测 \\; \\& \\| \\< \\> \\( \\) 等反斜杠转义的操作符，
    此类转义可能用于绕过基于操作符的命令分割检测。

    Args:
        command: 待验证的命令字符串

    Returns:
        含反斜杠转义操作符返回 ASK，否则返回 PASSTHROUGH
    """
    if _BACKSLASH_OPERATOR_PATTERN.search(command):
        return ValidationResult.ASK
    return ValidationResult.PASSTHROUGH


def validate_comment_quote_desync(command: str) -> ValidationResult:
    """
    验证注释引号不同步。

    检测命令中注释 (#) 后存在未闭合引号的情况，
    此类不同步可能导致解析器与执行器对引号状态理解不一致，
    从而引发注入。

    Args:
        command: 待验证的命令字符串

    Returns:
        注释引号不同步返回 ASK，否则返回 PASSTHROUGH
    """
    if '#' not in command:
        return ValidationResult.PASSTHROUGH

    # 使用引号状态机定位第一个未引用的 #（注释起始）
    in_single = False
    in_double = False
    comment_pos = -1
    i = 0
    while i < len(command):
        char = command[i]
        if char == '\\' and not in_single:
            # 反斜杠转义下一字符（双引号或无引号状态下）
            i += 2
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == '#' and not in_single and not in_double:
            # # 在词首（前面是空白或行首）才视为注释
            if i == 0 or command[i - 1] in ' \t':
                comment_pos = i
                break
        i += 1

    if comment_pos == -1:
        return ValidationResult.PASSTHROUGH

    # 检查注释后的引号数量是否为奇数（不同步）
    after_comment = command[comment_pos + 1:]
    if after_comment.count("'") % 2 != 0:
        return ValidationResult.ASK
    if after_comment.count('"') % 2 != 0:
        return ValidationResult.ASK
    return ValidationResult.PASSTHROUGH


def validate_quoted_newline(command: str) -> ValidationResult:
    """
    验证引号内换行。

    检测引号内包含换行符的情况，此类结构可能用于
    隐藏多行命令或绕过基于行分割的检测。

    Args:
        command: 待验证的命令字符串

    Returns:
        引号内含换行返回 ASK，否则返回 PASSTHROUGH
    """
    if '\n' not in command:
        return ValidationResult.PASSTHROUGH

    # 使用引号状态机检测引号内换行
    in_single = False
    in_double = False
    i = 0
    while i < len(command):
        char = command[i]
        if char == '\\' and not in_single:
            # 反斜杠转义下一字符（双引号或无引号状态下）
            i += 2
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == '\n' and (in_single or in_double):
            return ValidationResult.ASK
        i += 1
    return ValidationResult.PASSTHROUGH


# 验证器列表（按检测顺序排列）
# 顺序原则：先检测结构性问题（空、不完整、换行、控制字符），
# 再检测语法层问题（转义、畸形 token、注释），
# 最后检测语义层问题（元字符、变量、危险命令）
_VALIDATORS: List[Callable[[str], ValidationResult]] = [
    validate_empty,
    validate_incomplete_commands,
    validate_newlines,
    validate_control_characters,
    validate_unicode_whitespace,
    validate_quoted_newline,
    validate_backslash_escaped_whitespace,
    validate_backslash_escaped_operators,
    validate_malformed_tokens,
    validate_mid_word_hash,
    validate_comment_quote_desync,
    validate_shell_metacharacters,
    validate_brace_expansion,
    validate_dangerous_variables,
    validate_ifs_injection,
    validate_dangerous_patterns,
    validate_zsh_dangerous_commands,
    validate_chmod_commands,
    validate_git_push,
    validate_package_install,
    validate_obfuscated_flags,
    validate_jq_command,
    validate_git_commit_substitution,
    validate_proc_environ,
]


def validate_command(command: str) -> ValidationResult:
    """
    验证器流水线入口。

    按顺序调用所有验证器，遇到第一个非 PASSTHROUGH 的结果立即返回。
    全部验证器返回 PASSTHROUGH 则返回 ALLOW。

    Args:
        command: 待验证的命令字符串

    Returns:
        第一个非 PASSTHROUGH 的验证结果，或 ALLOW
    """
    for validator in _VALIDATORS:
        result = validator(command)
        if result != ValidationResult.PASSTHROUGH:
            return result
    return ValidationResult.ALLOW

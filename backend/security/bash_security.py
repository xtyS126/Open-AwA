"""
Bash 命令安全基础模块。

提供命令替换模式定义、Zsh 危险命令集合等基础设施，
供 command_validators 模块使用。

主要导出：
- COMMAND_SUBSTITUTION_PATTERNS：命令替换/参数扩展/算术扩展正则模式列表
- ZSH_DANGEROUS_COMMANDS：Zsh 危险命令集合

说明：extract_quoted_content（引号内内容提取）已被删除。验证器直接对原始命令字符串
匹配危险模式，引号不影响正则匹配，故无需先提取引号内容；command_validators 内部的
validate_comment_quote_desync / validate_quoted_newline 各自持有内联引号状态机。
"""

import re
from typing import List, Pattern


# 命令替换/参数扩展/算术扩展正则模式列表（含 Zsh 特有语法）
# 每个模式用于检测命令中可能引发注入或执行子命令的结构
COMMAND_SUBSTITUTION_PATTERNS: List[Pattern[str]] = [
    # $(...) 命令替换：POSIX 标准命令替换
    re.compile(r'\$\([^)]*\)'),
    # `...` 反引号命令替换：旧式命令替换
    re.compile(r'`[^`]*`'),
    # ${...} 参数扩展：变量参数扩展
    re.compile(r'\$\{[^}]*\}'),
    # $((...)) 算术扩展：算术运算
    re.compile(r'\$\(\([^)]*\)\)'),
    # Zsh 特有：=(...) 进程替换，将命令输出替换为临时文件路径
    re.compile(r'=\([^)]*\)'),
    # Zsh 特有：{1..10} 花括号扩展，生成序列
    re.compile(r'\{\d+\.\.\d+\}'),
    # Zsh 特有：{a..z} 字母序列花括号扩展
    re.compile(r'\{[a-zA-Z]+\.\.[a-zA-Z]+\}'),
    # Zsh 特有：{a,b,c} 逗号分隔花括号扩展
    re.compile(r'\{[^{}]*,[^{}]*\}'),
]

# Zsh 危险命令集合
# 包含可能造成文件系统破坏、权限提升、系统关停等高风险操作
ZSH_DANGEROUS_COMMANDS = frozenset([
    'rm',           # 删除文件/目录
    'mv',           # 移动/覆盖文件（覆盖场景危险）
    'chmod 777',    # 全权限开放
    'chown',        # 修改文件属主
    'kill -9',      # 强制终止进程
    'shutdown',     # 关机
    'reboot',       # 重启
    'dd',           # 块设备读写（可覆盖磁盘）
    'mkfs',         # 格式化文件系统
    'fdisk',        # 分区表操作
])

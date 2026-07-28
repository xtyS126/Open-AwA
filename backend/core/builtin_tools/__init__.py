"""
Agent内置工具模块，提供文件管理、终端执行和网页搜索等基础能力。
这些工具直接通过 function calling 协议暴露给 LLM，不走技能系统。
"""

from .file_manager import FileManagerSkill
from .terminal_executor import TerminalExecutorSkill
from .web_search import WebSearchSkill
from .local_search import LocalSearchEngine
from .browser_extended import BrowserExtendedSkill
from .notify import NotifyTool
from .todo import TodoManager
from .manager import BuiltInToolManager, builtin_tool_manager

__all__ = [
    'FileManagerSkill',
    'TerminalExecutorSkill',
    'WebSearchSkill',
    'LocalSearchEngine',
    'BrowserExtendedSkill',
    'NotifyTool',
    'TodoManager',
    'BuiltInToolManager',
    'builtin_tool_manager',
]

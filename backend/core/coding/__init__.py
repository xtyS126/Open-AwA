"""
Coding 模式核心模块。
提供文件树、Git 集成、LSP 代理、AST 搜索和 Diff 引擎等编码工具。
"""
from core.coding.file_tree import FileTreeService
from core.coding.git_integration import GitIntegration
from core.coding.ast_search import ASTSearchService
from core.coding.diff_engine import DiffEngine
from core.coding.lsp_proxy import LSPProxy
from core.coding.claude_code import ClaudeCodeAdapter
from core.coding.prompts import build_coding_prompt, CODING_SYSTEM_PROMPT_TEMPLATE

__all__ = [
    "FileTreeService", "GitIntegration", "ASTSearchService", "DiffEngine",
    "LSPProxy", "ClaudeCodeAdapter",
    "build_coding_prompt", "CODING_SYSTEM_PROMPT_TEMPLATE",
]

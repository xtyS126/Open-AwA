"""
Coding 模式核心模块。
提供文件树、Git 集成、LSP 代理、AST 搜索和 Diff 引擎等编码工具。
"""
from backend.core.coding.file_tree import FileTreeService
from backend.core.coding.git_integration import GitIntegration
from backend.core.coding.ast_search import ASTSearchService
from backend.core.coding.diff_engine import DiffEngine

__all__ = ["FileTreeService", "GitIntegration", "ASTSearchService", "DiffEngine"]

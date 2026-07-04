"""
AST 搜索服务 — 基于抽象语法树的结构化代码搜索。
支持 Python AST 解析和基础多语言文本搜索。
"""
import ast
import os
from pathlib import Path
from typing import Optional

from loguru import logger


class ASTSearchService:
    """
    基于 AST 的结构化代码搜索。
    当前完整支持 Python AST 解析，其他语言使用文本模式匹配。
    """

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir).resolve()
        self._py_ast_cache: dict[str, ast.AST] = {}

    def search_definitions(self, name: str, file_pattern: str = "*.py") -> list[dict]:
        """
        搜索函数/类定义（Python 语言）。
        """
        results = []
        for py_file in self.root_dir.rglob(file_pattern):
            if any(p.startswith(".") for p in py_file.parts):
                continue
            try:
                tree = self._parse_python(py_file)
                if not tree:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        if name.lower() in node.name.lower():
                            results.append({
                                "name": node.name,
                                "type": "class" if isinstance(node, ast.ClassDef) else "function",
                                "file": str(py_file.relative_to(self.root_dir)).replace("\\", "/"),
                                "line": node.lineno,
                                "col": node.col_offset,
                            })
            except Exception:
                continue
        return results

    def search_references(self, name: str, file_pattern: str = "*.py") -> list[dict]:
        """
        搜索变量/函数引用（Python 语言，基于 AST Name 节点）。
        """
        results = []
        for py_file in self.root_dir.rglob(file_pattern):
            if any(p.startswith(".") for p in py_file.parts):
                continue
            try:
                tree = self._parse_python(py_file)
                if not tree:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Name) and node.id == name:
                        results.append({
                            "name": node.id,
                            "context": type(node.ctx).__name__ if hasattr(node, 'ctx') else "unknown",
                            "file": str(py_file.relative_to(self.root_dir)).replace("\\", "/"),
                            "line": node.lineno,
                            "col": node.col_offset,
                        })
            except Exception:
                continue
        return results

    def search_pattern(self, pattern: str, file_pattern: str = "*") -> list[dict]:
        """
        通用文本模式搜索（正则，跨语言）。
        """
        import re
        results = []
        try:
            regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        except re.error:
            return [{"error": f"无效的正则表达式: {pattern}"}]

        for file_path in self.root_dir.rglob(file_pattern):
            if any(p.startswith(".") for p in file_path.parts):
                continue
            if not file_path.is_file():
                continue
            # 跳过二进制和大型文件
            if file_path.suffix in {".pyc", ".pyo", ".so", ".dll", ".exe", ".bin", ".png", ".jpg"}:
                continue
            try:
                if file_path.stat().st_size > 1024 * 1024:
                    continue
                content = file_path.read_text(errors="replace")
                for match in regex.finditer(content):
                    line_start = content[:match.start()].count("\n") + 1
                    results.append({
                        "file": str(file_path.relative_to(self.root_dir)).replace("\\", "/"),
                        "line": line_start,
                        "match": match.group()[:200],
                    })
                    if len(results) >= 200:
                        break
            except Exception:
                continue
            if len(results) >= 200:
                break
        return results

    def get_structure(self, file_path: str) -> dict:
        """
        获取 Python 文件的结构概览（函数/类/导入）。
        """
        full_path = self.root_dir / file_path
        if not full_path.exists():
            return {"error": f"文件不存在: {file_path}"}

        try:
            tree = self._parse_python(full_path)
            if not tree:
                return {"error": "无法解析该文件"}

            structure = {"imports": [], "classes": [], "functions": [], "top_level": []}

            for node in ast.iter_child_nodes(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        structure["imports"].append({
                            "name": alias.name,
                            "alias": alias.asname,
                            "line": node.lineno,
                        })
                elif isinstance(node, ast.ClassDef):
                    methods = []
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            methods.append({"name": item.name, "line": item.lineno})
                    structure["classes"].append({
                        "name": node.name,
                        "line": node.lineno,
                        "methods": methods,
                    })
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    structure["functions"].append({
                        "name": node.name,
                        "line": node.lineno,
                    })
                else:
                    structure["top_level"].append({
                        "type": type(node).__name__,
                        "line": node.lineno if hasattr(node, "lineno") else 1,
                    })

            return structure
        except Exception as e:
            return {"error": f"解析失败: {str(e)}"}

    def _parse_python(self, file_path: Path) -> Optional[ast.AST]:
        """缓存 Python AST 解析。"""
        key = str(file_path)
        if key in self._py_ast_cache:
            return self._py_ast_cache[key]
        try:
            source = file_path.read_text(errors="replace")
            tree = ast.parse(source, filename=str(file_path))
            self._py_ast_cache[key] = tree
            return tree
        except Exception as exc:
            # 语法错误的文件无法 AST 解析，降级为 None，记录 debug 便于排查
            logger.debug(f"[ast_search] AST 解析失败，跳过缓存: {file_path}, error={exc}")
            return None

    def clear_cache(self):
        """清除 AST 解析缓存。"""
        self._py_ast_cache.clear()

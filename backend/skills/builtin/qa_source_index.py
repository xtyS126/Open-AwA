"""
QA_source_index 内置技能 — 源码与文档索引和检索。
将关键词映射到本地源码路径和文档，支持快速定位。
"""
import os
import json
from pathlib import Path
from typing import Any, Optional
from loguru import logger

SKILL_NAME = "qa_source_index"
SKILL_DESCRIPTION = "构建和查询源码/文档索引，将关键词映射到本地文件路径和文档位置"

# 索引缓存路径
_INDEX_CACHE_DIR = Path.home() / ".openawa" / "cache"
_INDEX_FILE = _INDEX_CACHE_DIR / "qa_index.json"


async def execute(
    action: str,
    query: Optional[str] = None,
    source_dir: Optional[str] = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    执行源码索引操作。

    Args:
        action: 操作类型（build/search/info）
        query: 搜索关键词
        source_dir: 要索引的源码目录（默认当前目录）

    Returns:
        操作结果
    """
    valid_actions = {"build", "search", "info", "clear"}
    if action not in valid_actions:
        return {"success": False, "error": f"不支持的操作: {action}"}

    logger.bind(event="qa_index_skill", action=action).info("源码索引操作")

    if action == "build":
        target_dir = Path(source_dir) if source_dir else Path.cwd()
        if not target_dir.is_dir():
            return {"success": False, "error": f"目录不存在: {target_dir}"}

        index = _build_index(target_dir)
        _INDEX_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _INDEX_FILE.write_text(json.dumps(index, ensure_ascii=False, indent=2))

        return {
            "success": True,
            "action": "build",
            "source_dir": str(target_dir),
            "files_indexed": len(index),
            "index_file": str(_INDEX_FILE),
        }

    elif action == "search":
        if not query:
            return {"success": False, "error": "搜索需要提供 query 参数"}

        if not _INDEX_FILE.exists():
            return {"success": False, "error": "索引不存在，请先运行 build 操作"}

        try:
            index_data = json.loads(_INDEX_FILE.read_text())
        except Exception:
            return {"success": False, "error": "索引文件损坏，请重新 build"}

        results = []
        query_lower = query.lower()
        for file_path, info in index_data.items():
            score = 0
            # 文件名匹配
            if query_lower in Path(file_path).name.lower():
                score += 10
            # 内容关键词匹配
            for kw in info.get("keywords", []):
                if query_lower in kw.lower():
                    score += 5
            # 函数/类名匹配
            for name in info.get("names", []):
                if query_lower in name.lower():
                    score += 8
            if score > 0:
                results.append({**info, "file": file_path, "score": score})

        results.sort(key=lambda r: r["score"], reverse=True)
        return {
            "success": True,
            "action": "search",
            "query": query,
            "results": results[:20],
            "total": len(results),
        }

    elif action == "info":
        if _INDEX_FILE.exists():
            try:
                data = json.loads(_INDEX_FILE.read_text())
                return {
                    "success": True,
                    "index_exists": True,
                    "files_indexed": len(data),
                    "index_file": str(_INDEX_FILE),
                    "index_size": _INDEX_FILE.stat().st_size,
                }
            except Exception as exc:
                # 索引文件损坏或不可读时降级为"未构建"，记录 debug 便于排查
                logger.debug(f"[qa_source_index] 读取索引文件失败，降级为未构建: {exc}", exc_info=exc)
        return {"success": True, "index_exists": False, "note": "索引尚未构建"}

    elif action == "clear":
        if _INDEX_FILE.exists():
            _INDEX_FILE.unlink()
            return {"success": True, "action": "clear"}
        return {"success": True, "action": "clear", "note": "索引文件不存在"}

    return {"success": False}


def _build_index(target_dir: Path) -> dict[str, dict]:
    """
    扫描目录并构建索引。
    支持 Python/JS/TS/Markdown 文件。
    """
    import ast
    import re

    index = {}
    # 关键词提取正则
    keyword_pattern = re.compile(r'\b(?:def|class|function|const|let|var|import|export|async|await)\s+(\w+)', re.IGNORECASE)

    for file_path in target_dir.rglob("*"):
        if any(p.startswith(".") for p in file_path.parts):
            continue
        if file_path.is_dir():
            continue
        if file_path.suffix not in {".py", ".js", ".ts", ".jsx", ".tsx", ".md", ".json", ".yaml", ".yml"}:
            continue
        try:
            if file_path.stat().st_size > 512 * 1024:  # 跳过 512KB+ 文件
                continue

            content = file_path.read_text(errors="replace")
            rel_path = str(file_path.relative_to(target_dir)).replace("\\", "/")

            # 提取 Python AST 名称
            names = []
            if file_path.suffix == ".py":
                try:
                    tree = ast.parse(content)
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            names.append(node.name)
                except Exception as exc:
                    # 语法错误的文件无法 AST 解析，降级为空名称列表
                    logger.debug(f"[qa_source_index] AST 解析失败，跳过名称提取: {file_path}, error={exc}")

            # 提取关键词
            keywords = [m.group(1) for m in keyword_pattern.finditer(content)][:20]

            index[rel_path] = {
                "size": len(content),
                "lines": content.count("\n") + 1,
                "names": list(set(names))[:30],
                "keywords": list(set(keywords))[:20],
            }
        except Exception:
            continue

    return index

"""
文件树服务 — 管理项目目录的文件浏览和内容读写。
"""
import os
from pathlib import Path
from typing import Optional

from loguru import logger


# 常见忽略目录
DEFAULT_IGNORE_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "node_modules",
    ".next", "dist", "build", ".mypy_cache", ".pytest_cache",
    ".vite-cache", ".idea", ".vscode", ".DS_Store",
    "egg-info", ".eggs", ".tox",
}


class FileTreeService:
    """
    文件树服务，负责目录结构扫描、文件内容读写和基本文件操作。
    """

    def __init__(self, root_dir: str, ignore_dirs: Optional[set[str]] = None):
        self.root_dir = Path(root_dir).resolve()
        self.ignore_dirs = ignore_dirs or DEFAULT_IGNORE_DIRS

    def list_directory(self, rel_path: str = "") -> dict:
        """
        列出指定目录的内容。
        返回包含文件和子目录的树结构。
        """
        full_path = self.root_dir / rel_path
        if not full_path.exists():
            return {"error": f"路径不存在: {rel_path}"}
        if not full_path.is_dir():
            return {"error": f"不是目录: {rel_path}"}

        items = []
        try:
            for entry in sorted(full_path.iterdir()):
                name = entry.name
                if name in self.ignore_dirs or name.startswith("."):
                    continue
                item = {
                    "name": name,
                    "path": str(Path(rel_path) / name).replace("\\", "/"),
                    "type": "directory" if entry.is_dir() else "file",
                }
                if entry.is_file():
                    try:
                        size = entry.stat().st_size
                        item["size"] = size
                    except OSError:
                        item["size"] = 0
                items.append(item)
        except PermissionError:
            return {"error": f"无权访问: {rel_path}", "items": []}

        return {"path": rel_path, "items": items, "count": len(items)}

    def read_file(self, rel_path: str, max_size: int = 1024 * 1024) -> dict:
        """
        读取文件内容。
        """
        full_path = self.root_dir / rel_path
        if not full_path.exists():
            return {"error": f"文件不存在: {rel_path}"}
        if not full_path.is_file():
            return {"error": f"不是文件: {rel_path}"}

        # 检查文件大小
        try:
            size = full_path.stat().st_size
            if size > max_size:
                return {"error": f"文件过大 ({size} bytes)，限制 {max_size} bytes"}
        except OSError as exc:
            # stat 失败时跳过大小检查，继续尝试读取内容，记录 debug 便于排查
            logger.debug(f"[file_tree] 文件 stat 失败，跳过大小检查: {full_path}, error={exc}")

        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
            return {
                "path": rel_path,
                "content": content,
                "size": len(content),
                "lines": content.count("\n") + 1,
            }
        except Exception as e:
            return {"error": f"读取失败: {str(e)}"}

    def write_file(self, rel_path: str, content: str) -> dict:
        """
        写入文件内容。
        """
        full_path = self.root_dir / rel_path
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")
            return {"path": rel_path, "written": True, "size": len(content)}
        except Exception as e:
            return {"error": f"写入失败: {str(e)}"}

    def search_files(self, pattern: str, rel_path: str = "") -> list[dict]:
        """
        按文件名模式搜索文件。
        """
        base = self.root_dir / rel_path if rel_path else self.root_dir
        results = []
        try:
            for root, dirs, files in os.walk(base):
                # 过滤忽略目录
                dirs[:] = [d for d in dirs if d not in self.ignore_dirs and not d.startswith(".")]
                for fname in files:
                    if pattern.lower() in fname.lower():
                        full = Path(root) / fname
                        rel = full.relative_to(self.root_dir)
                        results.append({
                            "name": fname,
                            "path": str(rel).replace("\\", "/"),
                            "size": full.stat().st_size if full.exists() else 0,
                        })
        except PermissionError:
            pass
        return results

    def get_tree(self, rel_path: str = "", max_depth: int = 4) -> dict:
        """
        获取目录树结构（嵌套格式，用于前端渲染）。
        """
        def _build_tree(path: Path, depth: int) -> list[dict]:
            if depth > max_depth:
                return [{"name": "...", "type": "overflow"}]
            items = []
            try:
                entries = sorted(path.iterdir())
            except PermissionError:
                return []
            for entry in entries:
                if entry.name in self.ignore_dirs or entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    children = _build_tree(entry, depth + 1)
                    items.append({
                        "name": entry.name,
                        "type": "directory",
                        "expanded": depth == 0 and len(children) < 5,
                        "children": children,
                    })
                else:
                    items.append({
                        "name": entry.name,
                        "type": "file",
                    })
            return items

        full_path = self.root_dir / rel_path if rel_path else self.root_dir
        return {
            "root": str(self.root_dir),
            "tree": _build_tree(full_path, 0),
        }

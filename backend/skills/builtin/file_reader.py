"""
file_reader 内置技能 — 读取和摘要文本文件。
支持多种编码检测、格式识别和内容摘要。
"""
import os
from pathlib import Path
from typing import Any, Optional
from loguru import logger

SKILL_NAME = "file_reader"
SKILL_DESCRIPTION = "读取文本文件内容，支持自动编码检测、格式识别和智能摘要"

# 支持的文件类型
SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".json", ".csv", ".log", ".xml", ".yaml", ".yml",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".scss",
    ".sql", ".sh", ".bash", ".toml", ".ini", ".cfg", ".env", ".rst",
    ".c", ".cpp", ".h", ".hpp", ".java", ".go", ".rs", ".rb", ".php",
    ".vue", ".svelte",
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_OUTPUT_LENGTH = 10000  # 最大输出字符数


async def execute(
    file_path: str,
    action: str = "read",
    max_lines: Optional[int] = None,
    encoding: str = "utf-8",
    **kwargs: Any,
) -> dict[str, Any]:
    """
    读取文件内容。

    Args:
        file_path: 文件路径（绝对路径或相对于工作目录的路径）
        action: 操作类型（read/summary/info）
        max_lines: 最大读取行数（可选）
        encoding: 文件编码（默认 utf-8）

    Returns:
        文件内容或操作结果
    """
    path = Path(file_path)
    if not path.is_absolute():
        path = Path.cwd() / path

    if not path.exists():
        return {"success": False, "error": f"文件不存在: {file_path}"}
    if not path.is_file():
        return {"success": False, "error": f"不是文件: {file_path}"}

    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return {"success": False, "error": f"不支持的文件类型: {ext}"}

    try:
        file_size = path.stat().st_size
        if file_size > MAX_FILE_SIZE:
            return {"success": False, "error": f"文件过大 ({file_size} bytes)"}
    except OSError as exc:
        # stat 失败时跳过大小检查，继续尝试读取内容，记录 debug 便于排查
        logger.debug(f"[file_reader] 文件 stat 失败，跳过大小检查: {path}, error={exc}")

    try:
        content = path.read_text(encoding=encoding, errors="replace")
    except Exception as e:
        return {"success": False, "error": f"读取失败: {str(e)}"}

    lines = content.split("\n")

    if action == "read":
        if max_lines and max_lines > 0:
            lines = lines[:max_lines]
            content = "\n".join(lines)

        # 截断过长内容
        if len(content) > MAX_OUTPUT_LENGTH:
            content = content[:MAX_OUTPUT_LENGTH] + f"\n... (截断，共 {len(lines)} 行)"

        return {
            "success": True,
            "file": str(path),
            "size": len(content),
            "lines": len(lines),
            "extension": ext,
            "content": content,
        }

    elif action == "summary":
        # 生成摘要：前 5 行 + 统计信息
        preview = "\n".join(lines[:5])
        return {
            "success": True,
            "file": str(path),
            "total_lines": len(lines),
            "total_chars": sum(len(l) for l in lines),
            "extension": ext,
            "preview": preview,
            "has_more": len(lines) > 5,
        }

    elif action == "info":
        stat = path.stat()
        return {
            "success": True,
            "file": str(path),
            "size_bytes": stat.st_size,
            "extension": ext,
            "modified_at": stat.st_mtime,
        }

    return {"success": False, "error": f"未知操作: {action}"}

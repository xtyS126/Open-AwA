"""
Diff 引擎 — 计算文件差异和生成内联 diff 展示数据。
"""
import difflib
from pathlib import Path
from typing import Optional


class DiffEngine:
    """
    差异计算引擎，支持文件版本对比和内联 diff 展示。
    """

    @staticmethod
    def compute_diff(original: str, modified: str, context_lines: int = 3) -> list[dict]:
        """
        计算两段文本之间的差异。
        返回结构化的 diff hunk 列表。
        """
        original_lines = original.splitlines(keepends=True)
        modified_lines = modified.splitlines(keepends=True)

        differ = difflib.unified_diff(
            original_lines,
            modified_lines,
            lineterm="",
        )

        hunks = []
        current_hunk = None

        for line in differ:
            if line.startswith("@@"):
                if current_hunk:
                    hunks.append(current_hunk)
                current_hunk = {"header": line, "lines": []}
            elif current_hunk is not None:
                op = "keep"
                if line.startswith("+"):
                    op = "add"
                elif line.startswith("-"):
                    op = "del"
                current_hunk["lines"].append({
                    "content": line[1:] if line else "",
                    "operation": op,
                })

        if current_hunk:
            hunks.append(current_hunk)

        return hunks

    @staticmethod
    def compute_inline_diff(original: str, modified: str) -> dict:
        """
        计算面向行内显示的差异（用于编辑器的改前/改后对比）。
        """
        original_lines = original.split("\n")
        modified_lines = modified.split("\n")

        matcher = difflib.SequenceMatcher(None, original_lines, modified_lines)
        changes = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for idx in range(i1, i2):
                    changes.append({
                        "type": "unchanged",
                        "oldLine": idx + 1,
                        "newLine": j1 + (idx - i1) + 1,
                        "content": original_lines[idx],
                    })
            elif tag == "replace":
                # 删除旧行
                for idx in range(i1, i2):
                    changes.append({
                        "type": "removed",
                        "oldLine": idx + 1,
                        "content": original_lines[idx],
                    })
                # 插入新行
                for idx in range(j1, j2):
                    changes.append({
                        "type": "added",
                        "newLine": idx + 1,
                        "content": modified_lines[idx],
                    })
            elif tag == "delete":
                for idx in range(i1, i2):
                    changes.append({
                        "type": "removed",
                        "oldLine": idx + 1,
                        "content": original_lines[idx],
                    })
            elif tag == "insert":
                for idx in range(j1, j2):
                    changes.append({
                        "type": "added",
                        "newLine": idx + 1,
                        "content": modified_lines[idx],
                    })

        return {
            "changes": changes,
            "oldLineCount": len(original_lines),
            "newLineCount": len(modified_lines),
            "addedCount": sum(1 for c in changes if c["type"] == "added"),
            "removedCount": sum(1 for c in changes if c["type"] == "removed"),
        }

    @staticmethod
    def diff_files(file_a: str, file_b: str) -> dict:
        """
        比较两个文件的差异。
        """
        path_a = Path(file_a)
        path_b = Path(file_b)

        try:
            content_a = path_a.read_text(errors="replace")
        except Exception:
            content_a = ""
        try:
            content_b = path_b.read_text(errors="replace")
        except Exception:
            content_b = ""

        return DiffEngine.compute_inline_diff(content_a, content_b)

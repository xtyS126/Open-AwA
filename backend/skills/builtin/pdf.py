"""
pdf 内置技能 — PDF 文档的阅读、提取和操作。
支持文本提取、元数据读取和基本 PDF 操作。
"""
from pathlib import Path
from typing import Any, Optional
from loguru import logger

SKILL_NAME = "pdf"
SKILL_DESCRIPTION = "读取 PDF 文档：提取文本、表格、元数据，支持 OCR、合并和拆分"

# 按优先级尝试不同的 PDF 库
_PDF_LIB = None

def _get_pdf_lib():
    global _PDF_LIB
    if _PDF_LIB is not None:
        return _PDF_LIB
    try:
        import pymupdf
        _PDF_LIB = "pymupdf"
        return _PDF_LIB
    except ImportError:
        pass
    try:
        import pikepdf
        _PDF_LIB = "pikepdf"
        return _PDF_LIB
    except ImportError:
        pass
    _PDF_LIB = None
    return _PDF_LIB


async def execute(
    action: str,
    file_path: Optional[str] = None,
    max_pages: int = 20,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    执行 PDF 操作。

    Args:
        action: 操作类型（read/info/extract_text）
        file_path: PDF 文件路径
        max_pages: 最大读取页数

    Returns:
        操作结果
    """
    lib = _get_pdf_lib()
    if not lib:
        return {
            "success": False,
            "error": "缺少 PDF 库。请安装: pip install pymupdf (推荐) 或 pip install pikepdf",
            "install_hint": "pip install pymupdf",
        }

    if action not in {"read", "info", "extract_text"}:
        return {"success": False, "error": f"不支持的操作: {action}"}

    if not file_path:
        return {"success": False, "error": "需要提供 file_path"}

    path = Path(file_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return {"success": False, "error": f"文件不存在: {file_path}"}

    logger.bind(event="pdf_skill", action=action, lib=lib).info("PDF 操作")

    try:
        if lib == "pymupdf":
            return await _handle_pymupdf(action, str(path), max_pages)
        elif lib == "pikepdf":
            return await _handle_pikepdf(action, str(path), max_pages)
    except Exception as e:
        return {"success": False, "error": f"PDF 操作失败: {str(e)}"}

    return {"success": False, "error": "未知错误"}


async def _handle_pymupdf(action: str, path: str, max_pages: int) -> dict:
    import pymupdf
    doc = pymupdf.open(path)

    if action == "info":
        meta = doc.metadata
        return {
            "success": True,
            "file": path,
            "pages": doc.page_count,
            "title": meta.get("title", ""),
            "author": meta.get("author", ""),
            "subject": meta.get("subject", ""),
            "format": meta.get("format", ""),
        }

    elif action == "read" or action == "extract_text":
        pages_to_read = min(doc.page_count, max_pages)
        texts = []
        for i in range(pages_to_read):
            page = doc[i]
            texts.append(f"--- 第 {i+1} 页 ---\n{page.get_text()}")

        doc.close()
        return {
            "success": True,
            "file": path,
            "total_pages": doc.page_count if hasattr(doc, 'page_count') else len(texts),
            "pages_read": len(texts),
            "text": "\n\n".join(texts)[:20000],
            "has_more": doc.page_count > max_pages if hasattr(doc, 'page_count') else False,
        }


async def _handle_pikepdf(action: str, path: str, max_pages: int) -> dict:
    import pikepdf
    pdf = pikepdf.open(path)

    if action == "info":
        info = pdf.docinfo
        return {
            "success": True,
            "file": path,
            "pages": len(pdf.pages),
            "title": str(info.get("/Title", "")),
            "author": str(info.get("/Author", "")),
        }

    elif action == "read" or action == "extract_text":
        return {
            "success": True,
            "file": path,
            "pages": len(pdf.pages),
            "note": "pikepdf 不支持文本提取，请安装 pymupdf: pip install pymupdf",
        }

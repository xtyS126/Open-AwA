"""LLM 结构化任务可选参数的辅助工具。"""

from __future__ import annotations

import inspect
from typing import Any


def call_accepts_keyword(fn: Any, name: str) -> bool:
    """判断一个 callable 是否接受某个关键字参数。"""

    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    for param in signature.parameters.values():
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            return True
    return name in signature.parameters


def without_core_memory_kwargs(fn: Any) -> dict[str, Any]:
    """在支持时返回关闭额外 core-memory 注入的 kwargs。"""

    if call_accepts_keyword(fn, "inject_core_memory"):
        return {"inject_core_memory": False}
    return {}

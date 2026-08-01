"""执行器各协作者共享的常量与纯辅助函数。"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from loguru import logger

from config.settings import settings


MAX_TOOL_RESULT_CHARS = 8_000
MAX_TOOL_EVENT_RESULT_CHARS = 2_000


def resolve_max_tool_call_rounds(context: Dict[str, Any]) -> int:
    """解析工具调用回环上限，默认从配置读取，上限 100 轮。"""
    raw_value = context.get("max_tool_call_rounds")
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return settings.MAX_TOOL_CALL_ROUNDS
    return max(1, min(100, value))


def validate_parameters_against_schema(
    parameters: Dict[str, Any],
    schema: Optional[Dict[str, Any]],
    tool_name: str,
) -> Optional[str]:
    """校验工具参数的基础 JSON Schema 约束。"""
    if not schema or not isinstance(schema, dict):
        return None
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if schema.get("type", "object") != "object":
        return None
    for field in required:
        if field not in parameters or parameters[field] is None:
            return f"缺少必填参数: {field}"
    for key, value in parameters.items():
        field_schema = properties.get(key)
        if not field_schema or value is None:
            continue
        expected_type = field_schema.get("type", "")
        if expected_type == "string" and not isinstance(value, str):
            return f"参数 {key} 期望类型为 string，实际为 {type(value).__name__}"
        if expected_type == "integer" and not isinstance(value, int):
            return f"参数 {key} 期望类型为 integer，实际为 {type(value).__name__}"
        if expected_type == "number" and not isinstance(value, (int, float)):
            return f"参数 {key} 期望类型为 number，实际为 {type(value).__name__}"
        if expected_type == "boolean" and not isinstance(value, bool):
            return f"参数 {key} 期望类型为 boolean，实际为 {type(value).__name__}"
        if expected_type == "array" and not isinstance(value, (list, tuple)):
            return f"参数 {key} 期望类型为 array，实际为 {type(value).__name__}"
        if expected_type == "object" and not isinstance(value, dict):
            return f"参数 {key} 期望类型为 object，实际为 {type(value).__name__}"
    return None


def _handle_audit_task_result(task: asyncio.Task) -> None:
    """记录审计日志后台任务的取消或异常。"""
    try:
        if task.cancelled():
            logger.warning("[审计日志] 任务被取消")
            return
        exc = task.exception()
        if exc is not None:
            logger.warning(f"[审计日志] 任务执行失败: {exc}")
            return
        task.result()
    except Exception as exc:
        logger.warning(f"[审计日志] 任务执行失败: {exc}")

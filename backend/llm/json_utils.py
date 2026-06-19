"""
JSON 工具函数，提供结构化输出的容错解析能力。
"""

import json
import re
from typing import Any, Dict, Optional, Type, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def extract_json_from_text(text: str) -> Optional[str]:
    """
    从文本中提取 JSON 字符串。
    支持多种格式：代码块、裸 JSON、嵌套 JSON 等。

    Args:
        text: 包含 JSON 的文本

    Returns:
        Optional[str]: 提取的 JSON 字符串，失败返回 None
    """
    if not text:
        return None

    # 尝试匹配 ```json 代码块
    json_block_pattern = r"```(?:json)?\s*\n?(.*?)\n?```"
    match = re.search(json_block_pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # 尝试匹配裸 JSON（对象或数组）
    # 找到第一个 { 或 [ 和最后一个 } 或 ]
    first_brace = text.find("{")
    first_bracket = text.find("[")

    if first_brace == -1 and first_bracket == -1:
        return None

    # 确定起始位置
    if first_brace == -1:
        start = first_bracket
        end_char = "]"
    elif first_bracket == -1:
        start = first_brace
        end_char = "}"
    else:
        start = min(first_brace, first_bracket)
        end_char = "}" if first_brace < first_bracket else "]"

    # 找到最后一个匹配的结束字符
    end = text.rfind(end_char)
    if end > start:
        return text[start:end + 1]

    return None


def complete_brackets(json_str: str) -> str:
    """
    补全 JSON 字符串中缺失的括号。

    Args:
        json_str: 可能缺少括号的 JSON 字符串

    Returns:
        str: 补全括号后的 JSON 字符串
    """
    if not json_str:
        return json_str

    # 统计括号
    open_braces = json_str.count("{")
    close_braces = json_str.count("}")
    open_brackets = json_str.count("[")
    close_brackets = json_str.count("]")

    # 补全缺失的括号
    missing_braces = open_braces - close_braces
    missing_brackets = open_brackets - close_brackets

    result = json_str
    if missing_braces > 0:
        result += "}" * missing_braces
    if missing_brackets > 0:
        result += "]" * missing_brackets

    return result


def fix_json_escapes(json_str: str) -> str:
    """
    修复 JSON 字符串中的转义问题。

    Args:
        json_str: 可能有转义问题的 JSON 字符串

    Returns:
        str: 修复后的 JSON 字符串
    """
    if not json_str:
        return json_str

    # 修复未转义的反斜杠（但保留已转义的）
    # 先替换所有 \\ 为占位符
    result = json_str.replace("\\\\", "\x00ESCAPED_BACKSLASH\x00")
    # 替换单独的 \ 为 \\
    result = result.replace("\\", "\\\\")
    # 恢复已转义的反斜杠
    result = result.replace("\x00ESCAPED_BACKSLASH\x00", "\\\\")

    # 修复未转义的引号（在字符串值内部）
    # 这个比较复杂，暂时不做

    return result


def extract_json(text: str, default: Any = None) -> Any:
    """
    从文本中提取并解析 JSON，支持容错。

    Args:
        text: 包含 JSON 的文本
        default: 解析失败时的默认值

    Returns:
        Any: 解析后的 JSON 对象，失败返回 default
    """
    if not text:
        return default

    # 提取 JSON 块
    json_str = extract_json_from_text(text)
    if not json_str:
        return default

    # 补全括号
    json_str = complete_brackets(json_str)

    # 尝试解析
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        # 尝试修复常见错误
        try:
            # 移除尾部逗号
            json_str = re.sub(r",(\s*[}\]])", r"\1", json_str)
            return json.loads(json_str)
        except json.JSONDecodeError:
            return default


def parse_structured_output(text: str, schema: Type[T]) -> T:
    """
    从文本中解析结构化输出，支持容错。

    Args:
        text: 包含 JSON 的文本
        schema: Pydantic 模型类

    Returns:
        T: Pydantic 模型实例

    Raises:
        StructuredOutputError: 解析失败
    """
    from pydantic import ValidationError
    from llm.exceptions import StructuredOutputError

    # 提取 JSON
    json_data = extract_json(text, default=None)
    if json_data is None:
        raise StructuredOutputError(
            f"无法从文本中提取 JSON: {text[:200]}",
            raw_output=text,
            reason="extraction_failed"
        )

    # 验证 schema
    try:
        return schema.model_validate(json_data)
    except ValidationError as e:
        raise StructuredOutputError(
            f"JSON 不符合 schema: {e}",
            raw_output=text,
            reason="schema_validation_failed"
        )

"""解析 LLM 生成的结构化 JSON 的共享工具。

集中了每个分析器过去都自行重新实现的三个关注点：

1. 结构化任务的统一 ``max_tokens`` 预算 —— provider 默认值 4096 经常
   会把中文 JSON 载荷从值中间截断。把它提升到 16384 给 preference /
   profile / awareness / insight / layer-delta 响应留出足够余量。
2. Markdown 代码块围栏剥离。
3. 尽力挽救截断的 JSON：遍历花括号/方括号深度（带字符串感知），
   在最后一个安全边界闭合所有仍打开的容器，并返回可恢复的最大前缀。

这些挽救辅助函数过去位于 ``soul/preference_analyzer.py`` 中作为带
下划线的局部函数；现在调用方都从本模块导入，使行为在所有分析器之间
一致，单点修复即可同时改善它们。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import TypeAlias

logger = logging.getLogger(__name__)

# 结构化（JSON）LLM 任务的统一 token 预算。Gemini 3 Flash preview 和
# Claude 都支持大得多的输出，且中文 JSON 载荷经常超过 4096 token。
# 使用 16384 留出充足余量，同时远低于 provider 上限。
DEFAULT_STRUCTURED_MAX_TOKENS = 16384

JSONPrimitive: TypeAlias = None | bool | int | float | str
JSONValue: TypeAlias = JSONPrimitive | dict[str, "JSONValue"] | list["JSONValue"]
JSONObject: TypeAlias = dict[str, JSONValue]
JSONArray: TypeAlias = list[JSONValue]
JSONContainer: TypeAlias = JSONObject | JSONArray
JSONDictPredicate: TypeAlias = Callable[[dict[str, JSONValue]], bool]

_DEFAULT_LIST_WRAPPER_KEYS = (
    "results",
    "items",
    "data",
    "output",
    "scores",
    "evaluations",
    "entries",
    "candidates",
    "delights",
    "observations",
    "insights",
    "hypotheses",
    "notes",
    "list",
    "array",
)
_DEFAULT_OBJECT_WRAPPER_KEYS = ("result", "item", "data", "output")


def strip_json_fences(text: str) -> str:
    """若存在 Markdown ``` / ```json 围栏则移除。

    许多 LLM 即便被要求输出纯 JSON 也会把输出包在代码块里；这里
    对常见情况做归一化，使下游的 ``json.loads`` 能成功。
    """
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.startswith("json"):
            s = s[4:].lstrip()
    return s


def parse_llm_json_tolerant(text: str) -> JSONContainer | None:
    """容忍地解析 LLM JSON 输出。

    策略：
        1. 剥离 Markdown 围栏。
        2. 尝试一次普通 ``json.loads``。
        3. 失败时，通过在最后一个安全边界闭合未平衡的括号，
           尝试挽救被截断的对象或数组。

    成功时返回解析后的 ``dict`` 或 ``list``，不可恢复时返回 ``None``。
    需要区分"对象"与"数组"的调用方应对结果做 isinstance 检查。
    """
    cleaned = strip_json_fences(text)
    try:
        return _coerce_json_container(json.loads(cleaned))
    except json.JSONDecodeError:
        pass

    stripped = cleaned.lstrip()
    if stripped.startswith("{"):
        return _salvage_container(cleaned, open_ch="{")
    if stripped.startswith("["):
        return _salvage_container(cleaned, open_ch="[")

    # 未知根 —— 两种都试
    return _salvage_container(cleaned, open_ch="{") or _salvage_container(cleaned, open_ch="[")


def extract_llm_json_list(
    content: str,
    *,
    wrapper_keys: tuple[str, ...] = (),
    allow_singleton: bool = False,
    item_predicate: JSONDictPredicate | None = None,
) -> list[dict[str, JSONValue]] | None:
    """从杂乱的 LLM 输出中提取符合 schema 的 JSON 对象列表。"""
    keys = _merge_wrapper_keys(_DEFAULT_LIST_WRAPPER_KEYS, wrapper_keys)
    parsed = parse_llm_json_tolerant(content)
    direct = _coerce_candidate_list(
        parsed,
        wrapper_keys=keys,
        allow_singleton=allow_singleton,
        item_predicate=item_predicate,
    )
    if direct is not None:
        return direct

    for snippet in reversed(_extract_json_array_snippets(content)):
        candidate = _coerce_candidate_list(
            parse_llm_json_tolerant(snippet),
            wrapper_keys=keys,
            allow_singleton=allow_singleton,
            item_predicate=item_predicate,
        )
        if candidate is not None:
            return candidate

    jsonl_candidate = _coerce_jsonl_objects(content, item_predicate=item_predicate)
    if jsonl_candidate is not None:
        return jsonl_candidate

    if allow_singleton:
        for snippet in reversed(_extract_json_object_snippets(content)):
            candidate = _coerce_candidate_list(
                parse_llm_json_tolerant(snippet),
                wrapper_keys=keys,
                allow_singleton=True,
                item_predicate=item_predicate,
            )
            if candidate is not None:
                return candidate
    return None


def extract_llm_json_object(
    content: str,
    *,
    wrapper_keys: tuple[str, ...] = (),
    item_predicate: JSONDictPredicate | None = None,
) -> dict[str, JSONValue] | None:
    """从杂乱的 LLM 输出中提取符合 schema 的 JSON 对象。"""
    keys = _merge_wrapper_keys(_DEFAULT_OBJECT_WRAPPER_KEYS, wrapper_keys)
    parsed = parse_llm_json_tolerant(content)
    direct = _coerce_candidate_object(
        parsed,
        wrapper_keys=keys,
        item_predicate=item_predicate,
    )
    if direct is not None:
        return direct

    for snippet in reversed(_extract_json_object_snippets(content)):
        candidate = _coerce_candidate_object(
            parse_llm_json_tolerant(snippet),
            wrapper_keys=keys,
            item_predicate=item_predicate,
        )
        if candidate is not None:
            return candidate
    return None


def format_parse_failure(content: str, exc: Exception, *, label: str) -> str:
    """为解析失败格式化一条紧凑的诊断条目。

    故意同时包含原始响应的头部和尾部：尾部通常是截断发生的地方，
    而头部能揭示 LLM 是否遵循了 schema。
    """
    snippet = content.strip()
    head = snippet[:400]
    tail = snippet[-400:]
    return (
        f"{label} JSON parse failed at {exc}; "
        f"total_chars={len(snippet)} head={head!r} tail={tail!r}"
    )


def _salvage_container(text: str, *, open_ch: str) -> JSONContainer | None:
    """尽力恢复被从值中间截断的 JSON 对象或数组。

    遍历 ``text``，跟踪花括号/方括号深度与字符串状态；记录最后一个
    "安全"截断点（顶层闭合括号匹配或深度 ≥1 处的逗号）。然后尝试
    逐渐加长的候选：要么在安全点截断，要么用缺失的闭合符修补尾部。
    """
    start = text.find(open_ch)
    if start < 0:
        return None

    depth_stack: list[str] = []
    in_string = False
    escape = False
    last_safe: int | None = None

    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch in "{[":
            depth_stack.append(ch)
            continue
        if ch in "}]":
            if not depth_stack:
                continue
            depth_stack.pop()
            if not depth_stack:
                last_safe = i + 1
            continue
        if ch == "," and depth_stack:
            last_safe = i

    candidates: list[str] = []
    if last_safe is not None:
        candidates.append(text[start:last_safe])

    trimmed = text[start:]
    for cut_char in (",", "{", "["):
        idx = trimmed.rfind(cut_char)
        if idx >= 0:
            candidate_tail = trimmed[: idx + (0 if cut_char == "," else 1)]
            closers = _remaining_closers(candidate_tail)
            if closers is not None:
                candidates.append(candidate_tail + closers)

    for candidate in candidates:
        candidate = candidate.strip().rstrip(",")
        if not candidate:
            continue
        try:
            parsed = _coerce_json_container(json.loads(candidate))
        except json.JSONDecodeError:
            continue
        if open_ch == "{" and isinstance(parsed, dict):
            return parsed
        if open_ch == "[" and isinstance(parsed, list):
            return parsed
    return None


def _coerce_json_container(value: object) -> JSONContainer | None:
    coerced = _coerce_json_value(value)
    if isinstance(coerced, (dict, list)):
        return coerced
    return None


def _coerce_json_value(value: object) -> JSONValue | None:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        coerced_dict: JSONObject = {}
        for key, item in value.items():
            if not isinstance(key, str):
                return None
            coerced_item = _coerce_json_value(item)
            if coerced_item is None and item is not None:
                return None
            coerced_dict[key] = coerced_item
        return coerced_dict
    if isinstance(value, list):
        coerced_list: JSONArray = []
        for item in value:
            coerced_item = _coerce_json_value(item)
            if coerced_item is None and item is not None:
                return None
            coerced_list.append(coerced_item)
        return coerced_list
    return None


def _merge_wrapper_keys(
    default_keys: tuple[str, ...],
    caller_keys: tuple[str, ...],
) -> tuple[str, ...]:
    merged: list[str] = []
    for key in (*caller_keys, *default_keys):
        if key and key not in merged:
            merged.append(key)
    return tuple(merged)


def _coerce_candidate_list(
    value: object,
    *,
    wrapper_keys: tuple[str, ...],
    allow_singleton: bool,
    item_predicate: JSONDictPredicate | None,
) -> list[dict[str, JSONValue]] | None:
    for candidate in _iter_list_candidates(
        value,
        wrapper_keys=wrapper_keys,
        allow_singleton=allow_singleton,
    ):
        coerced = _coerce_json_object_list(candidate)
        if coerced is None:
            continue
        if item_predicate is not None and not any(item_predicate(item) for item in coerced):
            continue
        return coerced
    return None


def _iter_list_candidates(
    value: object,
    *,
    wrapper_keys: tuple[str, ...],
    allow_singleton: bool,
) -> list[object]:
    candidates: list[object] = []
    if isinstance(value, list):
        candidates.append(value)
    if isinstance(value, dict):
        for key in wrapper_keys:
            if key in value:
                nested = value[key]
                candidates.append(nested)
                if isinstance(nested, dict):
                    for nested_key in wrapper_keys:
                        if nested_key in nested:
                            candidates.append(nested[nested_key])
        if allow_singleton:
            candidates.append(value)
    return candidates


def _coerce_json_object_list(value: object) -> list[dict[str, JSONValue]] | None:
    if not isinstance(value, list) or not value:
        return None
    results: list[dict[str, JSONValue]] = []
    for item in value:
        coerced_item = _coerce_json_value(item)
        if not isinstance(coerced_item, dict):
            return None
        results.append(coerced_item)
    return results


def _coerce_candidate_object(
    value: object,
    *,
    wrapper_keys: tuple[str, ...],
    item_predicate: JSONDictPredicate | None,
) -> dict[str, JSONValue] | None:
    for candidate in _iter_object_candidates(value, wrapper_keys=wrapper_keys):
        coerced = _coerce_json_value(candidate)
        if not isinstance(coerced, dict):
            continue
        if item_predicate is not None and not item_predicate(coerced):
            continue
        return coerced
    return None


def _iter_object_candidates(
    value: object,
    *,
    wrapper_keys: tuple[str, ...],
) -> list[object]:
    candidates: list[object] = []
    if isinstance(value, dict):
        candidates.append(value)
        for key in wrapper_keys:
            if key in value:
                nested = value[key]
                candidates.append(nested)
                if isinstance(nested, dict):
                    for nested_key in wrapper_keys:
                        if nested_key in nested:
                            candidates.append(nested[nested_key])
    return candidates


def _coerce_jsonl_objects(
    content: str,
    *,
    item_predicate: JSONDictPredicate | None,
) -> list[dict[str, JSONValue]] | None:
    rows: list[dict[str, JSONValue]] = []
    for line in content.splitlines():
        stripped = line.strip().rstrip(",")
        if not stripped or not stripped.startswith("{"):
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        coerced = _coerce_json_value(parsed)
        if isinstance(coerced, dict):
            rows.append(coerced)
    if not rows:
        return None
    if item_predicate is not None and not any(item_predicate(item) for item in rows):
        return None
    return rows


def _extract_json_array_snippets(text: str) -> list[str]:
    return _extract_balanced_json_snippets(text, open_char="[", close_char="]")


def _extract_json_object_snippets(text: str) -> list[str]:
    return _extract_balanced_json_snippets(text, open_char="{", close_char="}")


def _extract_balanced_json_snippets(
    text: str,
    *,
    open_char: str,
    close_char: str,
) -> list[str]:
    snippets: list[str] = []
    start: int | None = None
    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == open_char:
            if depth == 0:
                start = index
            depth += 1
            continue
        if char == close_char and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                snippets.append(text[start : index + 1])
                start = None
    return snippets


def _remaining_closers(partial: str) -> str | None:
    """返回平衡 ``partial`` 所需的闭合括号字符串。

    若 partial 末尾位于一个无法安全闭合的字符串字面量中，则返回
    ``None``（我们拒绝猜测字符串应在哪里终止）。
    """
    stack: list[str] = []
    in_string = False
    escape = False
    for ch in partial:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if not stack:
                return None
            stack.pop()
    if in_string:
        return None
    return "".join("}" if opener == "{" else "]" for opener in reversed(stack))

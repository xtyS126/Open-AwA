"""
API 自动化测试 Skill — 断言引擎

支持 6 种断言类型，自动校验 API 返回结果是否符合预期：
    - status_code:   HTTP 状态码校验
    - json_path:     JSON 字段路径取值校验
    - response_time: 响应耗时上限校验
    - body_contains: 响应体文本包含校验
    - header_check:  响应头字段值校验
    - schema_match:  JSON 结构模式匹配校验
"""

import json
import re
from typing import Any, Dict, List, Optional

import httpx

from .models import AssertionResult, AssertionRule


class AssertionEngine:
    """
    断言引擎 — 根据断言规则列表对 HTTP 响应执行自动化校验

    使用方式:
        engine = AssertionEngine()
        results = engine.run(response, duration_ms, rules)
    """

    # 支持的比较运算符
    _SUPPORTED_OPERATORS = frozenset({
        "eq", "ne", "gt", "lt", "gte", "lte",
        "contains", "not_contains", "regex",
        "in", "not_in", "is_none", "is_not_none",
    })

    # ========================================================================
    # 公共入口
    # ========================================================================

    def run(
        self,
        response: httpx.Response,
        duration_ms: float,
        rules: List[AssertionRule],
    ) -> List[AssertionResult]:
        """
        按规则列表依次执行断言，返回所有断言结果

        Args:
            response: httpx 响应对象
            duration_ms: 请求耗时（毫秒）
            rules: 断言规则列表

        Returns:
            AssertionResult 列表
        """
        results: List[AssertionResult] = []

        for rule in rules:
            result = self._execute_rule(response, duration_ms, rule)
            results.append(result)

        return results

    # ========================================================================
    # 规则分发
    # ========================================================================

    def _execute_rule(
        self,
        response: httpx.Response,
        duration_ms: float,
        rule: AssertionRule,
    ) -> AssertionResult:
        """根据规则类型分发到具体断言方法"""
        dispatcher = {
            "status_code": self._assert_status_code,
            "json_path": self._assert_json_path,
            "response_time": self._assert_response_time,
            "body_contains": self._assert_body_contains,
            "header_check": self._assert_header_check,
            "schema_match": self._assert_schema_match,
        }

        handler = dispatcher.get(rule.type)
        if handler is None:
            return AssertionResult(
                rule_type=rule.type,
                passed=False,
                expected=rule.expected,
                message=f"不支持的断言类型: {rule.type}",
                description=rule.description,
            )

        try:
            return handler(response, duration_ms, rule)
        except Exception as e:
            return AssertionResult(
                rule_type=rule.type,
                passed=False,
                expected=rule.expected,
                message=f"断言执行异常: {type(e).__name__}: {str(e)}",
                description=rule.description,
            )

    # ========================================================================
    # status_code: HTTP 状态码断言
    # ========================================================================

    def _assert_status_code(
        self,
        response: httpx.Response,
        duration_ms: float,
        rule: AssertionRule,
    ) -> AssertionResult:
        """校验 HTTP 状态码"""
        actual = response.status_code
        expected = rule.expected
        passed = self._compare(actual, expected, rule.operator)

        return AssertionResult(
            rule_type="status_code",
            passed=passed,
            expected=expected,
            actual=actual,
            operator=rule.operator,
            message=(
                f"状态码校验通过: {actual}"
                if passed
                else f"状态码校验失败: 期望 {expected}, 实际 {actual}"
            ),
            description=rule.description,
        )

    # ========================================================================
    # json_path: JSON 字段取值断言
    # ========================================================================

    def _assert_json_path(
        self,
        response: httpx.Response,
        duration_ms: float,
        rule: AssertionRule,
    ) -> AssertionResult:
        """通过点号路径提取 JSON 字段值并校验"""
        if rule.field is None:
            return AssertionResult(
                rule_type="json_path",
                passed=False,
                expected=rule.expected,
                message="json_path 断言缺少 field 参数",
                description=rule.description,
            )

        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as e:
            return AssertionResult(
                rule_type="json_path",
                passed=False,
                expected=rule.expected,
                message=f"响应体不是有效的 JSON: {str(e)[:200]}",
                description=rule.description,
            )

        # 按点号分隔路径并逐级取值
        actual = self._resolve_json_path(data, rule.field)
        if actual is _SENTINEL:
            return AssertionResult(
                rule_type="json_path",
                passed=False,
                expected=rule.expected,
                field=rule.field,
                message=f"JSON 路径 '{rule.field}' 不存在于响应体中",
                description=rule.description,
            )

        passed = self._compare(actual, rule.expected, rule.operator)

        return AssertionResult(
            rule_type="json_path",
            passed=passed,
            expected=rule.expected,
            actual=actual,
            operator=rule.operator,
            field=rule.field,
            message=(
                f"JSON 路径 '{rule.field}' 校验通过"
                if passed
                else f"JSON 路径 '{rule.field}' 校验失败: 期望 {rule.expected}, 实际 {actual}"
            ),
            description=rule.description,
        )

    # ========================================================================
    # response_time: 响应耗时断言
    # ========================================================================

    def _assert_response_time(
        self,
        response: httpx.Response,
        duration_ms: float,
        rule: AssertionRule,
    ) -> AssertionResult:
        """校验响应耗时是否在允许范围内"""
        actual = round(duration_ms, 2)
        expected = rule.expected
        operator = rule.operator if rule.operator in ("lt", "lte", "gt", "gte") else "lte"
        passed = self._compare(actual, expected, operator)

        return AssertionResult(
            rule_type="response_time",
            passed=passed,
            expected=f"{operator} {expected}ms",
            actual=f"{actual}ms",
            operator=operator,
            message=(
                f"响应耗时校验通过: {actual}ms"
                if passed
                else f"响应耗时校验失败: {actual}ms 超过了 {operator} {expected}ms"
            ),
            description=rule.description,
        )

    # ========================================================================
    # body_contains: 响应体文本包含断言
    # ========================================================================

    def _assert_body_contains(
        self,
        response: httpx.Response,
        duration_ms: float,
        rule: AssertionRule,
    ) -> AssertionResult:
        """校验响应体文本是否包含指定内容"""
        body_text = response.text
        expected = str(rule.expected)

        operator = rule.operator if rule.operator in ("contains", "not_contains") else "contains"
        passed = self._compare(body_text, expected, operator)

        preview = body_text[:200] + ("..." if len(body_text) > 200 else "")

        return AssertionResult(
            rule_type="body_contains",
            passed=passed,
            expected=expected,
            actual=f"响应体({len(body_text)} 字符): {preview}",
            operator=operator,
            message=(
                "响应体内容包含校验通过"
                if passed
                else "响应体内容包含校验失败"
            ),
            description=rule.description,
        )

    # ========================================================================
    # header_check: 响应头字段断言
    # ========================================================================

    def _assert_header_check(
        self,
        response: httpx.Response,
        duration_ms: float,
        rule: AssertionRule,
    ) -> AssertionResult:
        """校验响应头中指定字段的值"""
        if rule.field is None:
            return AssertionResult(
                rule_type="header_check",
                passed=False,
                expected=rule.expected,
                message="header_check 断言缺少 field 参数",
                description=rule.description,
            )

        headers_lower = {k.lower(): v for k, v in response.headers.items()}
        field_lower = rule.field.lower()
        actual = headers_lower.get(field_lower)

        if actual is None:
            return AssertionResult(
                rule_type="header_check",
                passed=False,
                expected=rule.expected,
                field=rule.field,
                message=f"响应头中不存在 '{rule.field}' 字段",
                description=rule.description,
            )

        passed = self._compare(actual, rule.expected, rule.operator)

        return AssertionResult(
            rule_type="header_check",
            passed=passed,
            expected=rule.expected,
            actual=actual,
            operator=rule.operator,
            field=rule.field,
            message=(
                f"响应头 '{rule.field}' 校验通过"
                if passed
                else f"响应头 '{rule.field}' 校验失败: 期望 {rule.expected}, 实际 {actual}"
            ),
            description=rule.description,
        )

    # ========================================================================
    # schema_match: JSON 结构模式匹配断言
    # ========================================================================

    def _assert_schema_match(
        self,
        response: httpx.Response,
        duration_ms: float,
        rule: AssertionRule,
    ) -> AssertionResult:
        """
        校验 JSON 响应体是否包含期望的字段结构

        expected 为一个 dict，key 为字段名，value 为期望的类型字符串，
        例如 {"data": "dict", "data.id": "int", "message": "str", "success": "bool"}

        特殊类型值:
            - "any": 任意非 None 值
            - "list": 列表
            - "non_empty_str": 非空字符串
            - "positive_int": 正整数
        """
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as e:
            return AssertionResult(
                rule_type="schema_match",
                passed=False,
                expected=rule.expected,
                message=f"响应体不是有效的 JSON: {str(e)[:200]}",
                description=rule.description,
            )

        if not isinstance(rule.expected, dict):
            return AssertionResult(
                rule_type="schema_match",
                passed=False,
                expected=rule.expected,
                message="schema_match 的 expected 必须是一个 dict",
                description=rule.description,
            )

        errors: List[str] = []
        for field_path, expected_type in rule.expected.items():
            value = self._resolve_json_path(data, field_path)
            if value is _SENTINEL:
                errors.append(f"字段 '{field_path}' 不存在")
                continue
            type_ok = self._check_type(value, str(expected_type))
            if not type_ok:
                errors.append(
                    f"字段 '{field_path}' 类型不匹配: "
                    f"期望 {expected_type}, 实际 {type(value).__name__} (值={value!r})"
                )

        passed = len(errors) == 0
        return AssertionResult(
            rule_type="schema_match",
            passed=passed,
            expected=rule.expected,
            actual={"errors": errors} if errors else {"all_fields_match": True},
            message=(
                "Schema 结构校验通过"
                if passed
                else f"Schema 结构校验失败: {'; '.join(errors)}"
            ),
            description=rule.description,
        )

    # ========================================================================
    # 工具方法
    # ========================================================================

    @staticmethod
    def _resolve_json_path(data: Any, path: str) -> Any:
        """
        按点号分隔的路径从嵌套结构中提取值

        支持列表索引，如 'results.0.name' 表示取 results[0].name

        Args:
            data: 根数据（通常为 dict）
            path: 点号分隔的路径字符串

        Returns:
            路径对应的值，或 _SENTINEL 表示路径不存在
        """
        current = data
        for segment in path.split("."):
            if current is _SENTINEL:
                return _SENTINEL

            # 尝试列表索引
            if isinstance(current, list):
                try:
                    index = int(segment)
                    if 0 <= index < len(current):
                        current = current[index]
                        continue
                except ValueError:
                    pass

            # 字典访问
            if isinstance(current, dict):
                current = current.get(segment, _SENTINEL)
            else:
                return _SENTINEL

        return current

    @staticmethod
    def _compare(actual: Any, expected: Any, operator: str) -> bool:
        """
        根据运算符比较实际值和期望值

        Args:
            actual: 实际值
            expected: 期望值
            operator: 比较运算符

        Returns:
            比较结果
        """
        try:
            if operator == "eq":
                return actual == expected
            if operator == "ne":
                return actual != expected
            if operator == "gt":
                return actual > expected
            if operator == "lt":
                return actual < expected
            if operator == "gte":
                return actual >= expected
            if operator == "lte":
                return actual <= expected
            if operator == "contains":
                return str(expected) in str(actual)
            if operator == "not_contains":
                return str(expected) not in str(actual)
            if operator == "regex":
                return bool(re.search(str(expected), str(actual)))
            if operator == "in":
                return actual in expected if isinstance(expected, (list, tuple, set)) else str(actual) in str(expected)
            if operator == "not_in":
                return actual not in expected if isinstance(expected, (list, tuple, set)) else str(actual) not in str(expected)
            if operator == "is_none":
                return actual is None
            if operator == "is_not_none":
                return actual is not None
        except (TypeError, ValueError):
            return False

        return False

    @staticmethod
    def _check_type(value: Any, expected_type: str) -> bool:
        """
        校验 Python 值是否匹配期望的类型描述

        Args:
            value: 待校验的值
            expected_type: 类型描述字符串（如 "str", "int", "dict", "any" 等）

        Returns:
            类型是否匹配
        """
        if expected_type == "any":
            return value is not None
        if expected_type == "non_empty_str":
            return isinstance(value, str) and len(value) > 0
        if expected_type == "positive_int":
            return isinstance(value, int) and value > 0
        if expected_type == "list":
            return isinstance(value, list)
        if expected_type == "dict":
            return isinstance(value, dict)
        if expected_type == "bool":
            return isinstance(value, bool)
        if expected_type == "int":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected_type == "float":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected_type == "str":
            return isinstance(value, str)
        if expected_type == "null" or expected_type == "none":
            return value is None
        return False


# ============================================================================
# 哨兵值 — 标记 JSON 路径不存在
# ============================================================================

_SENTINEL = object()

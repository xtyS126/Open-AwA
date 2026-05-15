"""
断言引擎单元测试

覆盖 6 种断言类型：status_code / json_path / response_time / body_contains / header_check / schema_match
以及 JSON 路径解析和比较运算符的边界情况。
"""

import json
from unittest.mock import MagicMock

import httpx
import pytest

# 确保能导入 skill 的 core 模块
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.assertions import AssertionEngine
from core.models import AssertionRule


class TestAssertStatuscode:
    """HTTP 状态码断言测试"""

    def setup_method(self):
        self.engine = AssertionEngine()

    def _make_response(self, status_code: int, body: dict = None) -> httpx.Response:
        """构建 mock HTTP 响应"""
        request = httpx.Request("GET", "http://test/api")
        return httpx.Response(
            status_code=status_code,
            json=body or {"status": "ok"},
            request=request,
        )

    def test_status_code_pass(self):
        """状态码匹配时通过"""
        response = self._make_response(200)
        rule = AssertionRule(type="status_code", expected=200, operator="eq")
        result = self.engine.run(response, 50.0, [rule])[0]
        assert result.passed is True
        assert result.actual == 200

    def test_status_code_fail(self):
        """状态码不匹配时失败"""
        response = self._make_response(404)
        rule = AssertionRule(type="status_code", expected=200, operator="eq")
        result = self.engine.run(response, 50.0, [rule])[0]
        assert result.passed is False
        assert result.actual == 404

    def test_status_code_ne_pass(self):
        """不等于运算符"""
        response = self._make_response(201)
        rule = AssertionRule(type="status_code", expected=400, operator="ne")
        result = self.engine.run(response, 50.0, [rule])[0]
        assert result.passed is True


class TestAssertJsonPath:
    """JSON 路径断言测试"""

    def setup_method(self):
        self.engine = AssertionEngine()

    def _make_response(self, body: dict) -> httpx.Response:
        request = httpx.Request("GET", "http://test/api")
        return httpx.Response(
            status_code=200,
            json=body,
            request=request,
        )

    def test_simple_field_pass(self):
        """简单字段取值校验通过"""
        response = self._make_response({"data": {"name": "test", "id": 1}})
        rule = AssertionRule(
            type="json_path", field="data.name",
            expected="test", operator="eq",
        )
        result = self.engine.run(response, 50.0, [rule])[0]
        assert result.passed is True

    def test_simple_field_fail(self):
        """简单字段取值校验失败"""
        response = self._make_response({"data": {"name": "wrong"}})
        rule = AssertionRule(
            type="json_path", field="data.name",
            expected="expected", operator="eq",
        )
        result = self.engine.run(response, 50.0, [rule])[0]
        assert result.passed is False

    def test_list_index_access(self):
        """列表索引取值"""
        response = self._make_response({
            "results": [
                {"id": 1, "name": "first"},
                {"id": 2, "name": "second"},
            ]
        })
        rule = AssertionRule(
            type="json_path", field="results.0.name",
            expected="first", operator="eq",
        )
        result = self.engine.run(response, 50.0, [rule])[0]
        assert result.passed is True

    def test_nonexistent_path(self):
        """路径不存在时失败"""
        response = self._make_response({"data": {"name": "test"}})
        rule = AssertionRule(
            type="json_path", field="data.nonexistent.field",
            expected="anything", operator="eq",
        )
        result = self.engine.run(response, 50.0, [rule])[0]
        assert result.passed is False
        assert "不存在" in result.message

    def test_not_json_response(self):
        """非 JSON 响应应失败"""
        request = httpx.Request("GET", "http://test/api")
        response = httpx.Response(
            status_code=200,
            content=b"<html>not json</html>",
            headers={"content-type": "text/html"},
            request=request,
        )
        rule = AssertionRule(
            type="json_path", field="field", expected="val", operator="eq",
        )
        result = self.engine.run(response, 50.0, [rule])[0]
        assert result.passed is False
        assert "JSON" in result.message

    def test_gt_operator(self):
        """大于运算符"""
        response = self._make_response({"count": 10})
        rule = AssertionRule(
            type="json_path", field="count", expected=5, operator="gt",
        )
        result = self.engine.run(response, 50.0, [rule])[0]
        assert result.passed is True

    def test_contains_operator(self):
        """包含运算符"""
        response = self._make_response({"message": "hello world"})
        rule = AssertionRule(
            type="json_path", field="message",
            expected="world", operator="contains",
        )
        result = self.engine.run(response, 50.0, [rule])[0]
        assert result.passed is True

    def test_regex_operator(self):
        """正则匹配运算符"""
        response = self._make_response({"email": "user@example.com"})
        rule = AssertionRule(
            type="json_path", field="email",
            expected=r".+@.+\.com", operator="regex",
        )
        result = self.engine.run(response, 50.0, [rule])[0]
        assert result.passed is True


class TestAssertResponseTime:
    """响应耗时断言测试"""

    def setup_method(self):
        self.engine = AssertionEngine()

    def _make_response(self, status_code: int = 200) -> httpx.Response:
        request = httpx.Request("GET", "http://test/api")
        return httpx.Response(status_code=status_code, json={}, request=request)

    def test_within_limit(self):
        """耗时在限制内"""
        response = self._make_response()
        rule = AssertionRule(type="response_time", expected=1000, operator="lte")
        result = self.engine.run(response, 500.0, [rule])[0]
        assert result.passed is True

    def test_exceed_limit(self):
        """耗时超限"""
        response = self._make_response()
        rule = AssertionRule(type="response_time", expected=100, operator="lte")
        result = self.engine.run(response, 500.0, [rule])[0]
        assert result.passed is False


class TestAssertBodyContains:
    """响应体文本包含断言测试"""

    def setup_method(self):
        self.engine = AssertionEngine()

    def _make_response(self, text: str, content_type: str = "text/html") -> httpx.Response:
        request = httpx.Request("GET", "http://test/api")
        return httpx.Response(
            status_code=200,
            content=text.encode("utf-8"),
            headers={"content-type": content_type},
            request=request,
        )

    def test_contains_pass(self):
        """包含指定文本"""
        response = self._make_response("<html><body>success</body></html>")
        rule = AssertionRule(type="body_contains", expected="success", operator="contains")
        result = self.engine.run(response, 50.0, [rule])[0]
        assert result.passed is True

    def test_contains_fail(self):
        """不包含指定文本"""
        response = self._make_response("<html><body>Content</body></html>")
        rule = AssertionRule(type="body_contains", expected="not_found", operator="contains")
        result = self.engine.run(response, 50.0, [rule])[0]
        assert result.passed is False

    def test_not_contains_pass(self):
        """不包含运算符通过"""
        response = self._make_response("<html><body>clean</body></html>")
        rule = AssertionRule(type="body_contains", expected="error", operator="not_contains")
        result = self.engine.run(response, 50.0, [rule])[0]
        assert result.passed is True


class TestAssertHeaderCheck:
    """响应头校验断言测试"""

    def setup_method(self):
        self.engine = AssertionEngine()

    def _make_response(self, headers: dict) -> httpx.Response:
        request = httpx.Request("GET", "http://test/api")
        return httpx.Response(
            status_code=200,
            json={},
            headers=headers,
            request=request,
        )

    def test_header_match_pass(self):
        """响应头匹配通过"""
        response = self._make_response({"content-type": "application/json"})
        rule = AssertionRule(
            type="header_check", field="content-type",
            expected="application/json", operator="contains",
        )
        result = self.engine.run(response, 50.0, [rule])[0]
        assert result.passed is True

    def test_header_missing(self):
        """响应头不存在"""
        response = self._make_response({"x-custom": "value"})
        rule = AssertionRule(
            type="header_check", field="x-non-existent-header-xyz",
            expected="anything", operator="eq",
        )
        result = self.engine.run(response, 50.0, [rule])[0]
        assert result.passed is False
        assert "不存在" in result.message


class TestAssertSchemaMatch:
    """Schema 结构匹配断言测试"""

    def setup_method(self):
        self.engine = AssertionEngine()

    def _make_response(self, body: dict) -> httpx.Response:
        request = httpx.Request("GET", "http://test/api")
        return httpx.Response(status_code=200, json=body, request=request)

    def test_all_fields_match(self):
        """所有字段类型匹配"""
        response = self._make_response({
            "success": True,
            "data": {"id": 1, "name": "test"},
            "message": "ok",
        })
        rule = AssertionRule(
            type="schema_match",
            expected={
                "success": "bool",
                "data": "dict",
                "data.id": "int",
                "data.name": "str",
                "message": "str",
            },
        )
        result = self.engine.run(response, 50.0, [rule])[0]
        assert result.passed is True

    def test_type_mismatch(self):
        """类型不匹配"""
        response = self._make_response({"count": "not_an_int"})
        rule = AssertionRule(
            type="schema_match",
            expected={"count": "int"},
        )
        result = self.engine.run(response, 50.0, [rule])[0]
        assert result.passed is False
        assert "不匹配" in result.message

    def test_field_missing(self):
        """字段缺失"""
        response = self._make_response({"name": "test"})
        rule = AssertionRule(
            type="schema_match",
            expected={"missing_field": "str"},
        )
        result = self.engine.run(response, 50.0, [rule])[0]
        assert result.passed is False
        assert "不存在" in result.message


class TestCompareOperators:
    """比较运算符边界测试"""

    def setup_method(self):
        self.engine = AssertionEngine()

    def test_is_none(self):
        """is_none 运算符"""
        assert self.engine._compare(None, None, "is_none") is True
        assert self.engine._compare("value", None, "is_none") is False

    def test_is_not_none(self):
        """is_not_none 运算符"""
        assert self.engine._compare("value", None, "is_not_none") is True
        assert self.engine._compare(None, None, "is_not_none") is False

    def test_in_operator(self):
        """in 运算符"""
        assert self.engine._compare(1, [1, 2, 3], "in") is True
        assert self.engine._compare(4, [1, 2, 3], "in") is False

    def test_not_in_operator(self):
        """not_in 运算符"""
        assert self.engine._compare(4, [1, 2, 3], "not_in") is True

    def test_unknown_operator(self):
        """未知运算符返回 False"""
        assert self.engine._compare(1, 1, "unknown_op") is False


class TestResolveJsonPath:
    """JSON 路径解析测试"""

    def setup_method(self):
        self.engine = AssertionEngine()

    def test_nested_dict(self):
        """嵌套字典路径"""
        data = {"a": {"b": {"c": "value"}}}
        result = self.engine._resolve_json_path(data, "a.b.c")
        assert result == "value"

    def test_list_index(self):
        """列表索引"""
        data = {"items": [{"name": "first"}, {"name": "second"}]}
        result = self.engine._resolve_json_path(data, "items.1.name")
        assert result == "second"

    def test_nonexistent_path_returns_sentinel(self):
        """不存在的路径返回哨兵"""
        from core.assertions import _SENTINEL
        data = {"a": {"b": "c"}}
        result = self.engine._resolve_json_path(data, "x.y.z")
        assert result is _SENTINEL

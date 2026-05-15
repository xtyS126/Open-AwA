"""
异常处理模块单元测试

覆盖 ExceptionHandler 的异常分类、上下文捕获和处理函数。
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import pytest

from core.exception_handler import (
    ExceptionHandler,
    classify_exception,
    handle_exception,
)


class TestExceptionClassifier:
    """异常分类功能测试"""

    def test_network_error_connect(self):
        """连接拒绝错误"""
        exc = httpx.ConnectError("Connection refused")
        error_type, error_msg = classify_exception(exc)
        assert error_type == "network"
        assert "连接" in error_msg or "Connection" in error_msg

    def test_network_error_connect_timeout(self):
        """连接超时"""
        exc = httpx.ConnectTimeout("Connection timed out")
        error_type, error_msg = classify_exception(exc)
        assert error_type == "network"
        assert "timed out" in error_msg.lower()

    def test_timeout_error(self):
        """请求超时"""
        exc = httpx.TimeoutException("Request timed out")
        error_type, error_msg = classify_exception(exc)
        assert error_type == "timeout"

    def test_read_timeout(self):
        """读取超时（也是 timeout）"""
        exc = httpx.ReadTimeout("Read timed out")
        error_type, error_msg = classify_exception(exc)
        assert error_type == "timeout"

    def test_http_status_error(self):
        """HTTP 状态码错误"""
        request = httpx.Request("GET", "http://test/api")
        response = httpx.Response(status_code=404, request=request)
        exc = httpx.HTTPStatusError("Not Found", request=request, response=response)
        error_type, error_msg = classify_exception(exc)
        assert error_type == "http_error"
        assert "404" in error_msg

    def test_assertion_error(self):
        """断言错误"""
        exc = AssertionError("expected 200, got 404")
        error_type, error_msg = classify_exception(exc)
        assert error_type == "assertion"
        assert "断言" in error_msg

    def test_json_decode_error(self):
        """JSON 解析错误"""
        import json
        exc = json.JSONDecodeError("Invalid JSON", "doc", 0)
        error_type, error_msg = classify_exception(exc)
        assert error_type == "parse_error"

    def test_unknown_exception(self):
        """未分类的通用异常"""
        exc = RuntimeError("Something unexpected")
        error_type, error_msg = classify_exception(exc)
        assert error_type == "unknown"


class TestExceptionContextCapture:
    """异常上下文捕获测试"""

    def test_http_status_error_context(self):
        """HTTP 状态码错误的上下文应包含响应信息"""
        request = httpx.Request("POST", "http://test/api/endpoint")
        response = httpx.Response(
            status_code=500,
            json={"error": "internal"},
            request=request,
        )
        exc = httpx.HTTPStatusError("Server Error", request=request, response=response)

        context = ExceptionHandler.capture_request_context(exc)
        assert context["exception_type"] == "HTTPStatusError"
        assert context["response_status_code"] == 500
        assert context["response_url"] == "http://test/api/endpoint"

    def test_connect_error_context(self):
        """连接错误的上下文应包含目标 URL"""
        request = httpx.Request("GET", "http://test:9999/api")
        exc = httpx.ConnectError("Connection refused", request=request)

        context = ExceptionHandler.capture_request_context(exc)
        assert "target_url" in context
        assert "9999" in context.get("target_url", "")

    def test_timeout_error_context(self):
        """超时错误应记录超时类型"""
        exc = httpx.ReadTimeout("Read timeout")
        context = ExceptionHandler.capture_request_context(exc)
        assert context["timeout_class"] == "ReadTimeout"

    def test_generic_error_context(self):
        """通用异常上下文"""
        exc = ValueError("test error")
        context = ExceptionHandler.capture_request_context(exc)
        assert context["exception_type"] == "ValueError"
        assert context["exception_message"] == "test error"


class TestHandleException:
    """一站式异常处理测试"""

    def test_handle_returns_tuple(self):
        """handle 返回 (error_type, error_message, context)"""
        exc = httpx.TimeoutException("timeout")
        error_type, error_msg, context = handle_exception(exc)
        assert error_type == "timeout"
        assert isinstance(context, dict)
        assert "exception_type" in context

    def test_handle_with_request_snapshot(self):
        """带请求快照的异常处理"""
        exc = RuntimeError("test")
        snapshot = {"method": "GET", "url": "/api/test"}
        error_type, error_msg, context = handle_exception(exc, snapshot)
        assert context["request"] == snapshot

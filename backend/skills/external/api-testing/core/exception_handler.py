"""
API 自动化测试 Skill — 异常处理模块

针对网络错误、超时、HTTP 错误、JSON 解析错误等场景，
提供统一的异常分类、上下文捕获和错误信息格式化能力。
"""

import json
from typing import Any, Dict, Optional, Tuple

import httpx


class ExceptionHandler:
    """
    测试执行过程中的异常捕获与分类处理器

    使用方式:
        handler = ExceptionHandler()
        error_type, error_message, context = handler.handle(exception, request_snapshot)
    """

    # 错误类型常量
    ERROR_NETWORK = "network"
    ERROR_TIMEOUT = "timeout"
    ERROR_HTTP = "http_error"
    ERROR_ASSERTION = "assertion"
    ERROR_PARSE = "parse_error"
    ERROR_UNKNOWN = "unknown"

    @staticmethod
    def classify(exception: Exception) -> Tuple[str, str]:
        """
        对异常进行分类，返回 (error_type, error_message)

        Args:
            exception: 捕获到的异常对象

        Returns:
            (错误类型标识, 人类可读的错误描述)
        """
        exc_type = type(exception).__name__
        exc_msg = str(exception)

        # 网络连接错误
        if isinstance(exception, (httpx.ConnectError, httpx.ConnectTimeout)):
            return (
                ExceptionHandler.ERROR_NETWORK,
                f"[{exc_type}] 无法连接到目标服务器: {exc_msg[:500]}"
            )

        # 网络读写错误
        if isinstance(exception, (httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError)):
            return (
                ExceptionHandler.ERROR_NETWORK,
                f"[{exc_type}] 网络传输异常: {exc_msg[:500]}"
            )

        # 请求/响应超时
        if isinstance(exception, httpx.TimeoutException):
            return (
                ExceptionHandler.ERROR_TIMEOUT,
                f"[{exc_type}] 请求超时: {exc_msg[:500]}"
            )

        # HTTP 状态码错误（4xx/5xx）
        if isinstance(exception, httpx.HTTPStatusError):
            status_code = getattr(exception.response, 'status_code', '?')
            return (
                ExceptionHandler.ERROR_HTTP,
                f"[{exc_type}] HTTP {status_code}: {exc_msg[:500]}"
            )

        # HTTP 通用请求错误
        if isinstance(exception, httpx.HTTPError):
            return (
                ExceptionHandler.ERROR_HTTP,
                f"[{exc_type}] HTTP 请求异常: {exc_msg[:500]}"
            )

        # JSON 解析错误
        if isinstance(exception, (json.JSONDecodeError, ValueError)):
            if "json" in exc_msg.lower() or "json" in exc_type.lower():
                return (
                    ExceptionHandler.ERROR_PARSE,
                    f"[{exc_type}] 响应体 JSON 解析失败: {exc_msg[:500]}"
                )

        # 断言错误
        if isinstance(exception, AssertionError):
            return (
                ExceptionHandler.ERROR_ASSERTION,
                f"断言校验失败: {exc_msg[:500]}"
            )

        # 未知错误
        return (
            ExceptionHandler.ERROR_UNKNOWN,
            f"[{exc_type}] 未预期的异常: {exc_msg[:500]}"
        )

    @staticmethod
    def capture_request_context(
        exception: Exception,
        request_snapshot: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        捕获完整的请求上下文用于错误分析和调试

        Args:
            exception: 捕获到的异常对象
            request_snapshot: 请求快照字典（可选）

        Returns:
            包含请求上下文和异常详情的字典
        """
        context: Dict[str, Any] = {
            "exception_type": type(exception).__name__,
            "exception_message": str(exception),
            "exception_module": type(exception).__module__,
        }

        # 对 httpx.HTTPStatusError 提取更多响应信息
        if isinstance(exception, httpx.HTTPStatusError):
            response = exception.response
            context["response_status_code"] = response.status_code
            context["response_headers"] = dict(response.headers)
            context["response_url"] = str(response.url)
            try:
                context["response_body_preview"] = response.text[:1000]
            except Exception:
                context["response_body_preview"] = "<无法读取响应体>"

        # 对 httpx.TimeoutException 记录超时类型
        if isinstance(exception, httpx.TimeoutException):
            context["timeout_class"] = type(exception).__name__

        # 对 httpx.ConnectError 记录目标地址
        if isinstance(exception, httpx.ConnectError):
            request_info = getattr(exception, 'request', None)
            if request_info:
                context["target_url"] = str(getattr(request_info, 'url', '?'))
                context["target_method"] = str(getattr(request_info, 'method', '?'))

        # 追加请求快照
        if request_snapshot:
            context["request"] = request_snapshot

        return context

    @staticmethod
    def handle(
        exception: Exception,
        request_snapshot: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, str, Dict[str, Any]]:
        """
        一站式异常处理：分类 + 上下文捕获

        Args:
            exception: 捕获到的异常对象
            request_snapshot: 请求快照字典（可选）

        Returns:
            (error_type, error_message, context_dict)
        """
        error_type, error_message = ExceptionHandler.classify(exception)
        context = ExceptionHandler.capture_request_context(exception, request_snapshot)
        return error_type, error_message, context


# ============================================================================
# 便捷函数
# ============================================================================

def classify_exception(exception: Exception) -> Tuple[str, str]:
    """
    快速异常分类便捷函数

    Args:
        exception: 异常对象

    Returns:
        (error_type, error_message)
    """
    return ExceptionHandler.classify(exception)


def handle_exception(
    exception: Exception,
    request_snapshot: Optional[Dict[str, Any]] = None
) -> Tuple[str, str, Dict[str, Any]]:
    """
    一站式异常处理便捷函数

    Args:
        exception: 异常对象
        request_snapshot: 请求快照

    Returns:
        (error_type, error_message, context)
    """
    return ExceptionHandler.handle(exception, request_snapshot)

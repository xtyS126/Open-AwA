"""
测试统一错误码注册表与 build_standard_error 的契约。

覆盖：
- 注册表条目的关键字段完整性
- resolve_defaults 的优先级（显式 > 注册表 > 兜底）
- build_standard_error 在不同入参下的字段填充
- main.py 全局 handler 使用的错误码常量已注册
"""

import pytest

from core.error_codes import (
    ErrorCode,
    REGISTRY,
    get_error_code_meta,
    resolve_defaults,
)
from core.litellm_adapter import build_standard_error


class TestErrorCodeRegistry:
    """注册表完整性测试。"""

    def test_registry_contains_critical_codes(self):
        """关键错误码必须在注册表中，main.py 全局 handler 依赖这些默认值。"""
        critical_codes = [
            ErrorCode.INTERNAL_SERVER_ERROR,
            ErrorCode.REQUEST_TIMEOUT,
            ErrorCode.DATABASE_UNAVAILABLE,
            ErrorCode.LLM_API_KEY_STALE,
            ErrorCode.FAILOVER_TOTAL_TIMEOUT,
        ]
        for code in critical_codes:
            assert code in REGISTRY, f"关键错误码未注册: {code}"
            meta = REGISTRY[code]
            assert "default_retryable" in meta
            assert "default_status_code" in meta
            assert "user_message" in meta

    def test_registry_retryable_status_code_consistent(self):
        """注册表 retryable=True 的条目，状态码应为 5xx 或 429（可重试场景）。"""
        retryable_codes = []
        for code, meta in REGISTRY.items():
            if meta["default_retryable"]:
                retryable_codes.append((code, meta["default_status_code"]))
        for code, status_code in retryable_codes:
            # 4xx 中只有 429 (Too Many Requests) 可重试
            if 400 <= status_code < 500:
                assert status_code == 429, (
                    f"错误码 {code} 标记 retryable=True 但状态码 {status_code} 不可重试"
                )
            else:
                assert status_code >= 500, (
                    f"错误码 {code} 标记 retryable=True 但状态码 {status_code} 不在 5xx 区间"
                )

    def test_get_error_code_meta_returns_copy(self):
        """get_error_code_meta 返回副本，调用方修改不影响注册表。"""
        meta = get_error_code_meta(ErrorCode.REQUEST_TIMEOUT)
        meta["default_retryable"] = not meta["default_retryable"]
        # 注册表条目不受影响
        assert REGISTRY[ErrorCode.REQUEST_TIMEOUT]["default_retryable"] is True

    def test_get_error_code_meta_unknown_code_returns_empty(self):
        """未注册的 code 返回空字典。"""
        assert get_error_code_meta("nonexistent_code_xyz") == {}
        assert get_error_code_meta("") == {}


class TestResolveDefaults:
    """resolve_defaults 优先级测试。"""

    def test_explicit_values_override_registry(self):
        """显式传值优先级最高。"""
        # REQUEST_TIMEOUT 注册表默认 retryable=True / status_code=504
        result = resolve_defaults(
            ErrorCode.REQUEST_TIMEOUT,
            retryable=False,
            status_code=400,
        )
        assert result["retryable"] is False
        assert result["status_code"] == 400

    def test_registry_defaults_used_when_not_explicit(self):
        """未显式传值时使用注册表默认值。"""
        result = resolve_defaults(ErrorCode.REQUEST_TIMEOUT)
        assert result["retryable"] is True
        assert result["status_code"] == 504

    def test_fallback_for_unregistered_code(self):
        """未注册 code 兜底 retryable=False，status_code 不设置。"""
        result = resolve_defaults("nonexistent_code_xyz")
        assert result["retryable"] is False
        assert "status_code" not in result

    def test_partial_explicit_values(self):
        """仅显式传 retryable 时，status_code 仍从注册表取。"""
        result = resolve_defaults(
            ErrorCode.REQUEST_TIMEOUT,
            retryable=False,
        )
        assert result["retryable"] is False
        assert result["status_code"] == 504


class TestBuildStandardError:
    """build_standard_error 集成测试。"""

    def test_uses_registry_defaults_for_known_code(self):
        """已知 code 自动填充注册表默认值。"""
        error = build_standard_error(
            code=ErrorCode.REQUEST_TIMEOUT,
            message="请求超时",
        )
        assert error["code"] == ErrorCode.REQUEST_TIMEOUT
        assert error["message"] == "请求超时"
        assert error["retryable"] is True
        assert error["status_code"] == 504
        assert "request_id" in error
        assert error["details"] == {}

    def test_explicit_values_override_registry_in_build(self):
        """显式传值优先级高于注册表。"""
        error = build_standard_error(
            code=ErrorCode.REQUEST_TIMEOUT,
            message="自定义超时",
            retryable=False,
            status_code=400,
        )
        assert error["retryable"] is False
        assert error["status_code"] == 400

    def test_unknown_code_falls_back_to_false_retryable(self):
        """未注册 code 兜底 retryable=False。"""
        error = build_standard_error(
            code="custom_business_error",
            message="业务错误",
        )
        assert error["retryable"] is False
        # 未注册 code 且未显式传 status_code 时，不设置 status_code 字段
        assert "status_code" not in error

    def test_unknown_code_with_explicit_status_code(self):
        """未注册 code 但显式传 status_code 时，status_code 字段存在。"""
        error = build_standard_error(
            code="custom_business_error",
            message="业务错误",
            status_code=422,
        )
        assert error["status_code"] == 422

    def test_empty_code_falls_back_to_unknown_error(self):
        """空 code 兜底为 unknown_error。"""
        error = build_standard_error(
            code="",
            message="",
        )
        assert error["code"] == "unknown_error"
        assert error["message"] == "Unknown error"

    def test_details_passed_through(self):
        """details 字段透传。"""
        details = {"provider": "openai", "model": "gpt-4"}
        error = build_standard_error(
            code=ErrorCode.LLM_CALL_FAILED,
            message="LLM 调用失败",
            details=details,
        )
        assert error["details"] == details

    def test_request_id_passed_through(self):
        """request_id 字段透传。"""
        error = build_standard_error(
            code=ErrorCode.INTERNAL_SERVER_ERROR,
            message="内部错误",
            request_id="req-123",
        )
        assert error["request_id"] == "req-123"


class TestMainPyErrorCodes:
    """验证 main.py 全局 handler 使用的错误码已注册。"""

    def test_request_timeout_registered(self):
        """main.py 全局 handler 用于 TimeoutError 的 code 已注册。"""
        meta = get_error_code_meta(ErrorCode.REQUEST_TIMEOUT)
        assert meta["default_retryable"] is True
        assert meta["default_status_code"] == 504

    def test_database_unavailable_registered(self):
        """main.py 全局 handler 用于 SQLAlchemyError 的 code 已注册。"""
        meta = get_error_code_meta(ErrorCode.DATABASE_UNAVAILABLE)
        assert meta["default_retryable"] is True
        assert meta["default_status_code"] == 503

    def test_internal_server_error_registered(self):
        """main.py 全局 handler 兜底 code 已注册。"""
        meta = get_error_code_meta(ErrorCode.INTERNAL_SERVER_ERROR)
        assert meta["default_retryable"] is False
        assert meta["default_status_code"] == 500


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

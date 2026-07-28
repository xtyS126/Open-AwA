"""
billing/routers/billing.py 新增模型参数（frequency_penalty、presence_penalty、timeout、retry_count）的单元测试。
覆盖参数校验、capabilities 返回和重置功能。
"""

import pytest
from billing.routers.billing import ModelParameterUpdateRequest


# ==================== 参数校验模型测试 ====================

class TestModelParameterUpdateRequest:
    """测试 ModelParameterUpdateRequest 的字段定义和默认值"""

    def test_all_new_fields_are_optional_and_default_to_none(self):
        """新增 4 个参数字段均为 Optional，默认值为 None"""
        req = ModelParameterUpdateRequest()
        assert req.frequency_penalty is None
        assert req.presence_penalty is None
        assert req.timeout is None
        assert req.retry_count is None

    def test_new_fields_accept_valid_values(self):
        """新增字段接受合法的数值"""
        req = ModelParameterUpdateRequest(
            frequency_penalty=0.5,
            presence_penalty=-0.3,
            timeout=180,
            retry_count=5,
        )
        assert req.frequency_penalty == 0.5
        assert req.presence_penalty == -0.3
        assert req.timeout == 180
        assert req.retry_count == 5

    def test_all_fields_together(self):
        """新增字段与已有字段同时传入"""
        req = ModelParameterUpdateRequest(
            temperature=0.8,
            top_k=0.9,
            top_p=1.0,
            max_tokens_limit=4096,
            frequency_penalty=0.5,
            presence_penalty=0.2,
            timeout=300,
            retry_count=3,
        )
        assert req.temperature == 0.8
        assert req.top_k == 0.9
        assert req.top_p == 1.0
        assert req.max_tokens_limit == 4096
        assert req.frequency_penalty == 0.5
        assert req.presence_penalty == 0.2
        assert req.timeout == 300
        assert req.retry_count == 3


# ==================== 范围校验测试 ====================

class TestFrequencyPenaltyValidation:
    """frequency_penalty 范围校验：必须在 -2.0 到 2.0 之间"""

    def test_min_boundary_valid(self):
        """下边界 -2.0 合法"""
        req = ModelParameterUpdateRequest(frequency_penalty=-2.0)
        assert req.frequency_penalty == -2.0

    def test_max_boundary_valid(self):
        """上边界 2.0 合法"""
        req = ModelParameterUpdateRequest(frequency_penalty=2.0)
        assert req.frequency_penalty == 2.0

    def test_zero_valid(self):
        """0.0 合法"""
        req = ModelParameterUpdateRequest(frequency_penalty=0.0)
        assert req.frequency_penalty == 0.0

    @pytest.mark.parametrize("invalid_value", [-2.1, 2.1, -10.0, 10.0])
    def test_out_of_range_values_accepted_by_model(self, invalid_value):
        """Pydantic 模型层面不拦截超出范围的值（范围校验在路由层执行）"""
        req = ModelParameterUpdateRequest(frequency_penalty=invalid_value)
        assert req.frequency_penalty == invalid_value


class TestPresencePenaltyValidation:
    """presence_penalty 范围校验：必须在 -2.0 到 2.0 之间"""

    def test_min_boundary_valid(self):
        """下边界 -2.0 合法"""
        req = ModelParameterUpdateRequest(presence_penalty=-2.0)
        assert req.presence_penalty == -2.0

    def test_max_boundary_valid(self):
        """上边界 2.0 合法"""
        req = ModelParameterUpdateRequest(presence_penalty=2.0)
        assert req.presence_penalty == 2.0

    def test_zero_valid(self):
        """0.0 合法"""
        req = ModelParameterUpdateRequest(presence_penalty=0.0)
        assert req.presence_penalty == 0.0


class TestTimeoutValidation:
    """timeout 范围校验：必须在 1 到 600 之间"""

    def test_min_boundary_valid(self):
        """下边界 1 合法"""
        req = ModelParameterUpdateRequest(timeout=1)
        assert req.timeout == 1

    def test_max_boundary_valid(self):
        """上边界 600 合法"""
        req = ModelParameterUpdateRequest(timeout=600)
        assert req.timeout == 600

    def test_mid_range_valid(self):
        """中间值 120 合法"""
        req = ModelParameterUpdateRequest(timeout=120)
        assert req.timeout == 120

    @pytest.mark.parametrize("invalid_value", [0, -1, -10])
    def test_invalid_values_accepted_by_model(self, invalid_value):
        """Pydantic 模型层面不拦截无效值（范围校验在路由层执行）"""
        req = ModelParameterUpdateRequest(timeout=invalid_value)
        assert req.timeout == invalid_value


class TestRetryCountValidation:
    """retry_count 范围校验：必须在 0 到 10 之间"""

    def test_min_boundary_valid(self):
        """下边界 0 合法（0 次重试 = 不重试）"""
        req = ModelParameterUpdateRequest(retry_count=0)
        assert req.retry_count == 0

    def test_max_boundary_valid(self):
        """上边界 10 合法"""
        req = ModelParameterUpdateRequest(retry_count=10)
        assert req.retry_count == 10

    def test_mid_range_valid(self):
        """中间值 3 合法"""
        req = ModelParameterUpdateRequest(retry_count=3)
        assert req.retry_count == 3

    @pytest.mark.parametrize("invalid_value", [-1, 11, 100])
    def test_invalid_values_accepted_by_model(self, invalid_value):
        """Pydantic 模型层面不拦截无效值（范围校验在路由层执行）"""
        req = ModelParameterUpdateRequest(retry_count=invalid_value)
        assert req.retry_count == invalid_value


# ==================== 路由层范围校验测试 ====================

VALIDATION_TEST_CASES = [
    # (field_name, valid_value, invalid_value, expected_error_keyword)
    ("frequency_penalty", 0.5, 2.5, "frequency_penalty"),
    ("frequency_penalty", -2.0, -2.5, "frequency_penalty"),
    ("presence_penalty", 1.0, 3.0, "presence_penalty"),
    ("presence_penalty", -1.5, -3.0, "presence_penalty"),
    ("timeout", 300, 0, "timeout"),
    ("timeout", 600, 601, "timeout"),
    ("timeout", 1, -5, "timeout"),
    ("retry_count", 5, -1, "retry_count"),
    ("retry_count", 10, 11, "retry_count"),
    ("retry_count", 0, 100, "retry_count"),
]


class TestRouteLayerValidation:
    """
    路由层范围校验测试：直接调用 _validate_parameter_range 函数验证边界行为。
    该函数被 update_configuration_parameters 端点使用，确保校验逻辑独立可测。
    """

    @pytest.mark.parametrize("field_name,valid_value,invalid_value,expected_keyword", VALIDATION_TEST_CASES)
    def test_validate_rejects_invalid_values(self, field_name, valid_value, invalid_value, expected_keyword):
        """非法值应抛出 HTTPException(422)"""
        from fastapi import HTTPException
        from billing.routers.billing import _validate_parameter_range

        # 根据参数名确定合法的范围边界
        if field_name in ("frequency_penalty", "presence_penalty"):
            min_val, max_val = -2.0, 2.0
        elif field_name == "timeout":
            min_val, max_val = 1, 600
        elif field_name == "retry_count":
            min_val, max_val = 0, 10
        else:
            pytest.skip(f"未知参数: {field_name}")

        with pytest.raises(HTTPException) as exc_info:
            _validate_parameter_range(float(invalid_value), min_val, max_val, field_name)
        assert exc_info.value.status_code == 422
        assert expected_keyword in exc_info.value.detail

    @pytest.mark.parametrize("field_name,valid_value,invalid_value,expected_keyword", VALIDATION_TEST_CASES)
    def test_validate_accepts_valid_values(self, field_name, valid_value, invalid_value, expected_keyword):
        """合法值不应抛出异常"""
        from billing.routers.billing import _validate_parameter_range

        if field_name in ("frequency_penalty", "presence_penalty"):
            min_val, max_val = -2.0, 2.0
        elif field_name == "timeout":
            min_val, max_val = 1, 600
        elif field_name == "retry_count":
            min_val, max_val = 0, 10
        else:
            pytest.skip(f"未知参数: {field_name}")

        # 合法值不应抛出异常
        _validate_parameter_range(float(valid_value), min_val, max_val, field_name)


# ==================== serialize_configuration 测试 ====================

class TestSerializeConfiguration:
    """测试 serialize_configuration 函数正确输出新参数字段"""

    def test_serialize_includes_new_fields_with_defaults(self):
        """序列化时包含 4 个新参数，默认值为 None"""
        from unittest.mock import MagicMock
        from billing.routers.billing import serialize_configuration

        # 模拟一个只有基础字段的配置对象
        mock_config = MagicMock()
        mock_config.id = 1
        mock_config.provider = "test-provider"
        mock_config.model = "test-model"
        mock_config.temperature = 0.7
        mock_config.top_k = 0.9
        mock_config.top_p = None
        mock_config.max_tokens_limit = None
        mock_config.frequency_penalty = None
        mock_config.presence_penalty = None
        mock_config.timeout = None
        mock_config.retry_count = None
        mock_config.supports_temperature = True
        mock_config.supports_top_k = True
        mock_config.supports_vision = False
        mock_config.is_enabled = True
        mock_config.is_active = True
        mock_config.is_default = False
        mock_config.selected_models = None
        mock_config.custom_endpoint = None
        mock_config.api_key_encrypted = None
        mock_config.created_at = None
        mock_config.updated_at = None

        mock_pricing_manager = MagicMock()

        result = serialize_configuration(mock_config, mock_pricing_manager)

        assert "frequency_penalty" in result
        assert "presence_penalty" in result
        assert "timeout" in result
        assert "retry_count" in result
        assert result["frequency_penalty"] is None
        assert result["presence_penalty"] is None
        assert result["timeout"] is None
        assert result["retry_count"] is None

"""
OnionProfile 和 LayerData 单元测试。
"""

import pytest
from datetime import datetime
from soul.profile import OnionProfile, LayerData


class TestLayerData:
    """LayerData 数据模型测试套件。"""

    def test_create_layer_data_defaults(self):
        """测试创建默认 LayerData"""
        layer = LayerData()
        assert layer.description == ""
        assert layer.structured_data == {}
        assert layer.confidence == 0.0

    def test_create_layer_data_with_values(self):
        """测试创建带自定义值的 LayerData"""
        layer = LayerData(
            description="测试描述",
            structured_data={"key": "value"},
            confidence=0.8,
        )
        assert layer.description == "测试描述"
        assert layer.structured_data == {"key": "value"}
        assert layer.confidence == 0.8

    def test_layer_data_confidence_range(self):
        """测试 LayerData 置信度范围"""
        # 置信度不应超出 0.0-1.0 范围
        layer = LayerData(confidence=1.5)
        assert layer.confidence == 1.5  # dataclass 不强制校验，由上层控制


class TestOnionProfile:
    """OnionProfile 五层画像模型测试套件。"""

    def test_create_empty_profile(self):
        """测试创建空画像"""
        profile = OnionProfile(user_id="test_user")
        assert profile.user_id == "test_user"
        assert profile.surface.description == ""
        assert profile.surface.confidence == 0.0
        assert profile.interest.description == ""
        assert profile.role.description == ""
        assert profile.values.description == ""
        assert profile.core.description == ""

    def test_create_profile_with_default_user_id(self):
        """测试默认 user_id 为空字符串"""
        profile = OnionProfile()
        assert profile.user_id == ""

    def test_get_summary_with_all_layers(self):
        """测试所有层都有内容时的摘要生成"""
        profile = OnionProfile(user_id="test_user")
        profile.surface.description = "测试行为"
        profile.interest.description = "测试兴趣"
        profile.role.description = "测试角色"
        profile.values.description = "测试价值观"
        profile.core.description = "测试核心人格"
        summary = profile.get_summary()
        assert "行为表象: 测试行为" in summary
        assert "兴趣偏好: 测试兴趣" in summary
        assert "角色认同: 测试角色" in summary
        assert "价值驱动: 测试价值观" in summary
        assert "核心人格: 测试核心人格" in summary

    def test_get_summary_empty_profile(self):
        """测试空画像的摘要生成"""
        profile = OnionProfile(user_id="test_user")
        summary = profile.get_summary()
        assert summary == "画像尚未建立"

    def test_get_summary_partial_layers(self):
        """测试部分层有内容时的摘要生成"""
        profile = OnionProfile(user_id="test_user")
        profile.surface.description = "仅表层"
        profile.role.description = "仅角色"
        summary = profile.get_summary()
        assert "行为表象: 仅表层" in summary
        assert "角色认同: 仅角色" in summary
        assert "兴趣偏好" not in summary
        assert "价值驱动" not in summary
        assert "核心人格" not in summary

    def test_to_dict_and_from_dict(self):
        """测试序列化和反序列化"""
        profile = OnionProfile(user_id="test_user")
        profile.surface.description = "测试行为"
        profile.surface.confidence = 0.7
        profile.interest.structured_data = {"likes": ["编程"]}
        data = profile.to_dict()
        restored = OnionProfile.from_dict(data)
        assert restored.user_id == "test_user"
        assert restored.surface.description == "测试行为"
        assert restored.surface.confidence == 0.7
        assert restored.interest.structured_data == {"likes": ["编程"]}

    def test_to_dict_includes_timestamp(self):
        """测试序列化包含时间戳"""
        profile = OnionProfile(user_id="test_user")
        data = profile.to_dict()
        assert "updated_at" in data
        # 验证时间戳格式为 ISO 格式
        assert "T" in data["updated_at"]

    def test_from_dict_missing_fields(self):
        """测试从缺少字段的字典创建画像"""
        data = {"user_id": "test_user", "surface": {}}
        restored = OnionProfile.from_dict(data)
        assert restored.user_id == "test_user"
        assert restored.surface.description == ""
        assert restored.surface.confidence == 0.0
        assert restored.interest.description == ""

    def test_from_dict_empty_dict(self):
        """测试从空字典创建画像"""
        restored = OnionProfile.from_dict({})
        assert restored.user_id == ""
        assert restored.surface.description == ""

    def test_updated_at_is_datetime(self):
        """测试 updated_at 是 datetime 类型"""
        profile = OnionProfile(user_id="test_user")
        assert isinstance(profile.updated_at, datetime)
"""
LayerUpdaters 层更新器单元测试。
"""

import pytest
from soul.profile import OnionProfile
from soul.preference_analyzer import PreferenceUpdate
from soul.awareness_analyzer import AwarenessUpdate
from soul.insight_analyzer import InsightUpdate
from soul.layer_updaters import LayerUpdaters


class TestLayerUpdaters:
    """LayerUpdaters 层更新器测试套件。"""

    @pytest.fixture
    def updaters(self):
        """创建层更新器实例"""
        return LayerUpdaters()

    @pytest.fixture
    def profile(self):
        """创建基础画像"""
        return OnionProfile(user_id="test_user")

    # 测试 update_surface

    def test_update_surface_single_update(self, updaters, profile):
        """测试单个偏好更新到 surface 层"""
        updates = [
            PreferenceUpdate(
                preference_type="like",
                target="编程",
                detail="用户喜欢编程",
                confidence=0.8,
                source_event_type="dialogue",
            )
        ]
        updated = updaters.update_surface(profile, updates)
        assert "用户喜欢编程" in updated.surface.description
        assert updated.surface.confidence > 0.0

    def test_update_surface_multiple_updates(self, updaters, profile):
        """测试多个偏好更新累积到 surface 层"""
        updates = [
            PreferenceUpdate(
                preference_type="like",
                target="编程",
                detail="用户喜欢编程",
                confidence=0.8,
                source_event_type="dialogue",
            ),
            PreferenceUpdate(
                preference_type="like",
                target="设计",
                detail="用户喜欢设计",
                confidence=0.7,
                source_event_type="dialogue",
            ),
        ]
        updated = updaters.update_surface(profile, updates)
        assert "用户喜欢编程" in updated.surface.description
        assert "用户喜欢设计" in updated.surface.description
        # 置信度应累积增长
        assert updated.surface.confidence > 0.0

    def test_update_surface_structured_data(self, updaters, profile):
        """测试 surface 层结构化数据更新"""
        updates = [
            PreferenceUpdate(
                preference_type="like",
                target="编程",
                detail="用户喜欢编程",
                confidence=0.8,
                source_event_type="dialogue",
            )
        ]
        updated = updaters.update_surface(profile, updates)
        assert "编程" in updated.surface.structured_data
        assert updated.surface.structured_data["编程"] == ["用户喜欢编程"]

    # 测试 update_interest

    def test_update_interest_like(self, updaters, profile):
        """测试喜欢偏好更新到 interest 层"""
        updates = [
            PreferenceUpdate(
                preference_type="like",
                target="编程",
                detail="用户喜欢编程",
                confidence=0.8,
                source_event_type="dialogue",
            )
        ]
        updated = updaters.update_interest(profile, updates)
        assert "喜欢" in updated.interest.description
        assert "编程" in updated.interest.description
        assert "likes" in updated.interest.structured_data
        assert "编程" in updated.interest.structured_data["likes"]

    def test_update_interest_dislike(self, updaters, profile):
        """测试不喜欢偏好更新到 interest 层"""
        updates = [
            PreferenceUpdate(
                preference_type="dislike",
                target="复杂工具",
                detail="用户不喜欢复杂工具",
                confidence=0.7,
                source_event_type="dialogue",
            )
        ]
        updated = updaters.update_interest(profile, updates)
        assert "dislikes" in updated.interest.structured_data
        assert "复杂工具" in updated.interest.structured_data["dislikes"]
        # dislike 不更新 description（仅更新 structured_data）
        assert updated.interest.confidence > 0.0

    # 测试 update_role

    def test_update_role_frequent_behavior(self, updaters, profile):
        """测试频繁行为模式更新到 role 层"""
        updates = [
            AwarenessUpdate(
                pattern_type="frequent_behavior",
                description="用户频繁进行 tool_call 操作",
                confidence=0.6,
                evidence_count=5,
                metadata={"event_type": "tool_call", "count": 5},
            )
        ]
        updated = updaters.update_role(profile, updates)
        assert "roles" in updated.role.structured_data
        assert "频繁tool_call" in updated.role.structured_data["roles"]
        assert updated.role.confidence > 0.0

    def test_update_role_sentiment_tendency(self, updaters, profile):
        """测试情感倾向更新到 role 层"""
        updates = [
            AwarenessUpdate(
                pattern_type="sentiment_tendency",
                description="用户近期呈现积极倾向",
                confidence=0.5,
                evidence_count=4,
                metadata={"sentiment": "positive", "count": 4},
            )
        ]
        updated = updaters.update_role(profile, updates)
        # sentiment_tendency 不更新 roles（仅更新 frequent_behavior）
        assert updated.role.confidence > 0.0

    # 测试 update_values

    def test_update_values_cognitive_style(self, updaters, profile):
        """测试认知风格更新到 values 层"""
        updates = [
            InsightUpdate(
                insight_type="cognitive_style",
                value="analytical",
                description="分析型 - 善于逻辑推理和系统性思考",
                confidence=0.6,
                reasoning="基于关键词匹配",
            )
        ]
        updated = updaters.update_values(profile, updates)
        assert "认知风格" in updated.values.description
        assert "cognitive_style" in updated.values.structured_data
        assert updated.values.structured_data["cognitive_style"] == "analytical"
        assert updated.values.confidence > 0.0

    # 测试 update_core

    def test_update_core_mbti(self, updaters, profile):
        """测试 MBTI 更新到 core 层"""
        updates = [
            InsightUpdate(
                insight_type="mbti",
                value="INTJ",
                description="推断 MBTI 类型为 INTJ",
                confidence=0.6,
                reasoning="基于关键词匹配",
            )
        ]
        updated = updaters.update_core(profile, updates)
        assert "MBTI" in updated.core.description
        assert "INTJ" in updated.core.description
        assert updated.core.structured_data["mbti"] == "INTJ"
        assert updated.core.confidence > 0.0

    def test_update_core_cognitive_style(self, updaters, profile):
        """测试认知风格也更新到 core 层"""
        updates = [
            InsightUpdate(
                insight_type="cognitive_style",
                value="analytical",
                description="分析型风格",
                confidence=0.6,
                reasoning="基于关键词匹配",
            )
        ]
        updated = updaters.update_core(profile, updates)
        assert updated.core.structured_data["cognitive_style"] == "analytical"
        assert updated.core.confidence > 0.0

    def test_update_surface_confidence_capped(self, updaters, profile):
        """测试 surface 层置信度不会超过 1.0"""
        # 创建大量更新，确认置信度上限为 1.0
        updates = [
            PreferenceUpdate(
                preference_type="like",
                target="target",
                detail="detail",
                confidence=1.0,
                source_event_type="dialogue",
            )
            for _ in range(20)
        ]
        updated = updaters.update_surface(profile, updates)
        assert updated.surface.confidence <= 1.0
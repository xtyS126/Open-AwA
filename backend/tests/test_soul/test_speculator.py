"""
InterestSpeculator 兴趣推测器单元测试。
"""

import pytest
from soul.profile import OnionProfile
from soul.speculator import InterestSpeculator, InterestHypothesis


class TestInterestHypothesis:
    """InterestHypothesis 数据模型测试套件。"""

    def test_create_interest_hypothesis(self):
        """测试创建兴趣假设"""
        hypothesis = InterestHypothesis(
            hypothesis="用户可能对技术领域感兴趣",
            category="技术",
            confidence=0.6,
            reasoning="画像中匹配到关键词: 编程, 开发",
            probe_question="您平时会关注哪些技术领域的最新动态？",
        )
        assert hypothesis.hypothesis == "用户可能对技术领域感兴趣"
        assert hypothesis.category == "技术"
        assert hypothesis.confidence == 0.6
        assert hypothesis.reasoning == "画像中匹配到关键词: 编程, 开发"
        assert "技术" in hypothesis.probe_question
        assert hypothesis.metadata == {}

    def test_create_hypothesis_default_probe_question(self):
        """测试默认探针问题"""
        hypothesis = InterestHypothesis(
            hypothesis="测试假设",
            category="技术",
            confidence=0.5,
            reasoning="测试",
        )
        assert hypothesis.probe_question == ""


class TestInterestSpeculator:
    """InterestSpeculator 兴趣推测器测试套件。"""

    @pytest.fixture
    def speculator(self):
        """创建兴趣推测器实例"""
        return InterestSpeculator()

    def _create_profile_with_text(self, user_id: str, text: str) -> OnionProfile:
        """创建包含指定文本的画像"""
        profile = OnionProfile(user_id=user_id)
        profile.surface.description = text
        profile.interest.description = text
        return profile

    def test_speculate_with_keywords(self, speculator):
        """测试基于关键词匹配推测兴趣"""
        profile = self._create_profile_with_text(
            "user_001",
            "用户喜欢编程开发，研究算法和架构设计，关注AI人工智能",
        )
        hypotheses = speculator.speculate(profile)
        # 应匹配到"技术"类别
        assert len(hypotheses) >= 1
        categories = {h.category for h in hypotheses}
        assert "技术" in categories

    def test_speculate_empty_profile(self, speculator):
        """测试空画像不产生推测"""
        profile = OnionProfile(user_id="empty_user")
        hypotheses = speculator.speculate(profile)
        # 空画像 get_summary 返回 "画像尚未建立"，没有关键词匹配
        assert len(hypotheses) == 0

    def test_speculate_none_profile(self, speculator):
        """测试传入 None 画像"""
        hypotheses = speculator.speculate(None)
        assert len(hypotheses) == 0

    def test_speculate_multiple_categories(self, speculator):
        """测试同时匹配多个兴趣类别"""
        profile = self._create_profile_with_text(
            "user_002",
            "用户喜欢编程开发，也喜欢摄影绘画，经常学习和阅读",
        )
        hypotheses = speculator.speculate(profile)
        # 应匹配到多个类别（技术、艺术、教育等）
        assert len(hypotheses) >= 1

    def test_speculate_with_adjacent_categories(self, speculator):
        """测试基于已有兴趣推测相邻领域"""
        profile = OnionProfile(user_id="user_003")
        profile.surface.description = "用户喜欢编程"
        profile.interest.description = "用户喜欢编程"
        profile.interest.structured_data = {"likes": ["编程"]}

        hypotheses = speculator.speculate(profile)
        # 应包含相邻类别推测
        categories = {h.category for h in hypotheses}
        # 编程的相邻类别包括"技术"、"游戏"、"教育"
        assert "技术" in categories or "游戏" in categories or "教育" in categories

    def test_speculate_confidence_increases_with_matches(self, speculator):
        """测试关键词匹配越多置信度越高"""
        profile_single = self._create_profile_with_text(
            "user_004",
            "用户喜欢编程",
        )
        profile_multi = self._create_profile_with_text(
            "user_005",
            "用户喜欢编程开发，研究算法架构，关注AI人工智能开源",
        )

        single_hypotheses = speculator.speculate(profile_single)
        multi_hypotheses = speculator.speculate(profile_multi)

        # 更多匹配关键词应产生更高置信度
        if single_hypotheses and multi_hypotheses:
            single_tech = [h for h in single_hypotheses if h.category == "技术"]
            multi_tech = [h for h in multi_hypotheses if h.category == "技术"]
            if single_tech and multi_tech:
                assert multi_tech[0].confidence >= single_tech[0].confidence

    def test_speculate_includes_probe_questions(self, speculator):
        """测试推测结果包含探针问题"""
        profile = self._create_profile_with_text(
            "user_006",
            "用户喜欢编程开发",
        )
        hypotheses = speculator.speculate(profile)
        # 所有假设应有探针问题（category 在预定义字典中）
        for h in hypotheses:
            assert h.probe_question != ""

    def test_speculate_unknown_category_has_default_probe(self, speculator):
        """测试未知类别使用默认探针问题"""
        profile = OnionProfile(user_id="user_007")
        profile.surface.description = "用户喜欢编程"
        profile.interest.structured_data = {"likes": ["编程"]}

        hypotheses = speculator.speculate(profile)
        # 相邻类别推测也应有探针问题
        for h in hypotheses:
            assert h.probe_question != ""
"""
InsightAnalyzer 洞察分析器单元测试。
"""

import pytest
from soul.profile import OnionProfile
from soul.insight_analyzer import InsightAnalyzer, InsightUpdate


class TestInsightUpdate:
    """InsightUpdate 数据模型测试套件。"""

    def test_create_insight_update(self):
        """测试创建洞察更新"""
        update = InsightUpdate(
            insight_type="mbti",
            value="INTJ",
            description="推断 MBTI 类型为 INTJ",
            confidence=0.6,
            reasoning="基于关键词匹配",
            metadata={"matched_keywords": 3},
        )
        assert update.insight_type == "mbti"
        assert update.value == "INTJ"
        assert update.description == "推断 MBTI 类型为 INTJ"
        assert update.confidence == 0.6
        assert update.reasoning == "基于关键词匹配"
        assert update.metadata == {"matched_keywords": 3}


class TestInsightAnalyzer:
    """InsightAnalyzer 洞察分析器测试套件。"""

    @pytest.fixture
    def analyzer(self):
        """创建洞察分析器实例"""
        return InsightAnalyzer()

    def _create_profile_with_text(self, user_id: str, text: str) -> OnionProfile:
        """创建包含指定文本的画像"""
        profile = OnionProfile(user_id=user_id)
        profile.surface.description = text
        profile.interest.description = text
        return profile

    @pytest.mark.asyncio
    async def test_analyze_with_mbti_keywords(self, analyzer):
        """测试根据 MBTI 关键词推断人格类型"""
        profile = self._create_profile_with_text(
            "user_001",
            "用户喜欢系统架构规划，善于分析逻辑问题，独立完成项目",
        )
        updates = await analyzer.analyze(profile)
        # 应匹配到 INTJ 类型（架构、规划、分析、逻辑、独立等关键词）
        mbti_updates = [u for u in updates if u.insight_type == "mbti"]
        assert len(mbti_updates) >= 1
        assert mbti_updates[0].value == "INTJ"

    @pytest.mark.asyncio
    async def test_analyze_with_cognitive_style_keywords(self, analyzer):
        """测试根据认知风格关键词推断认知风格"""
        profile = self._create_profile_with_text(
            "user_002",
            "用户经常进行数据分析和逻辑推理，善于系统性思考",
        )
        updates = await analyzer.analyze(profile)
        cognitive_updates = [u for u in updates if u.insight_type == "cognitive_style"]
        assert len(cognitive_updates) >= 1
        assert cognitive_updates[0].value == "analytical"

    @pytest.mark.asyncio
    async def test_analyze_empty_profile(self, analyzer):
        """测试空画像不产生洞察"""
        profile = OnionProfile(user_id="empty_user")
        updates = await analyzer.analyze(profile)
        assert len(updates) == 0

    @pytest.mark.asyncio
    async def test_analyze_insufficient_keywords(self, analyzer):
        """测试关键词不足时不产生洞察"""
        profile = self._create_profile_with_text(
            "user_003",
            "今天天气不错",
        )
        updates = await analyzer.analyze(profile)
        # 不足2个匹配关键词，不应产生任何洞察
        assert len(updates) == 0

    @pytest.mark.asyncio
    async def test_analyze_none_profile(self, analyzer):
        """测试传入 None 画像"""
        updates = await analyzer.analyze(None)
        assert len(updates) == 0

    @pytest.mark.asyncio
    async def test_analyze_multiple_mbti_matches(self, analyzer):
        """测试多个 MBTI 类型匹配时选择得分最高者"""
        profile = self._create_profile_with_text(
            "user_004",
            "用户喜欢创新探索研究，善于抽象概念分析，"
            "同时也注重务实细节和可靠稳定",
        )
        updates = await analyzer.analyze(profile)
        mbti_updates = [u for u in updates if u.insight_type == "mbti"]
        assert len(mbti_updates) >= 1
        # 应返回得分最高的类型
        assert mbti_updates[0].value in InsightAnalyzer.MBTI_RULES

    @pytest.mark.asyncio
    async def test_analyze_creative_style(self, analyzer):
        """测试推断创造型认知风格"""
        profile = self._create_profile_with_text(
            "user_005",
            "用户喜欢创意设计，善于创新和艺术表达，充满想象力",
        )
        updates = await analyzer.analyze(profile)
        cognitive_updates = [u for u in updates if u.insight_type == "cognitive_style"]
        assert len(cognitive_updates) >= 1
        assert cognitive_updates[0].value == "creative"
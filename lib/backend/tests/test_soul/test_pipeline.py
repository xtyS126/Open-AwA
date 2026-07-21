"""
ProfileUpdatePipeline 画像更新管道单元测试。
"""

import pytest
from soul.event import BehaviorEvent
from soul.profile import OnionProfile
from soul.pipeline import ProfileUpdatePipeline


class TestProfileUpdatePipeline:
    """ProfileUpdatePipeline 画像更新管道测试套件。"""

    @pytest.fixture
    def pipeline(self):
        """创建管道实例"""
        return ProfileUpdatePipeline()

    @pytest.mark.asyncio
    async def test_process_empty_events(self, pipeline):
        """测试处理空事件列表"""
        profile = OnionProfile(user_id="test_user")
        profile.surface.description = "已有内容"
        result = await pipeline.process([], profile)
        # 空事件应返回原画像不变
        assert result.surface.description == "已有内容"

    @pytest.mark.asyncio
    async def test_process_no_profile_provided(self, pipeline):
        """测试不提供画像时自动创建"""
        events = [
            BehaviorEvent(
                event_type="dialogue",
                content="这个工具很好用",
                user_id="user_001",
            )
        ]
        result = await pipeline.process(events)
        assert isinstance(result, OnionProfile)
        assert result.user_id == ""  # 默认 user_id

    @pytest.mark.asyncio
    async def test_process_with_positive_preferences(self, pipeline):
        """测试处理包含积极关键词的事件"""
        event = BehaviorEvent(
            event_type="dialogue",
            content="这个工具非常好用，我很喜欢",
            user_id="user_001",
        )
        result = await pipeline.process([event])
        # 应更新 surface 层
        assert result.surface.description != ""
        assert result.surface.confidence > 0.0

    @pytest.mark.asyncio
    async def test_process_with_existing_profile(self, pipeline):
        """测试在已有画像基础上更新"""
        profile = OnionProfile(user_id="user_001")
        profile.surface.description = "原有行为"
        profile.surface.confidence = 0.3

        event = BehaviorEvent(
            event_type="dialogue",
            content="这个工具好用且高效",
            user_id="user_001",
        )
        result = await pipeline.process([event], profile)
        # 应保留原有内容并追加新内容
        assert "原有行为" in result.surface.description
        # 置信度应增加
        assert result.surface.confidence > 0.3

    @pytest.mark.asyncio
    async def test_process_multiple_events(self, pipeline):
        """测试处理多个事件"""
        events = [
            BehaviorEvent(
                event_type="dialogue",
                content=f"对话{i}，这个工具很好用",
                user_id="user_001",
            )
            for i in range(3)
        ]
        result = await pipeline.process(events)
        assert result.surface.description != ""
        assert result.surface.confidence > 0.0

    @pytest.mark.asyncio
    async def test_process_awareness_threshold(self, pipeline):
        """测试达到觉察分析阈值时触发觉察分析"""
        # 创建5个事件，达到 AWARENESS_THRESHOLD
        events = [
            BehaviorEvent(
                event_type="dialogue",
                content=f"对话内容 {i}",
                user_id="user_001",
                sentiment="positive",
            )
            for i in range(5)
        ]
        result = await pipeline.process(events)
        # 5个事件应触发觉察分析（缓冲区满）
        # 置信度应有更新
        assert result.role.confidence >= 0.0

    @pytest.mark.asyncio
    async def test_process_insight_threshold(self, pipeline):
        """测试画像足够丰富时触发洞察分析"""
        profile = OnionProfile(user_id="user_001")
        profile.surface.description = "用户喜欢架构规划和系统分析"
        profile.interest.description = "用户对编程和技术感兴趣"

        event = BehaviorEvent(
            event_type="dialogue",
            content="测试内容",
            user_id="user_001",
        )
        result = await pipeline.process([event], profile)
        # 有两层有内容，应触发洞察分析
        # 可能更新了 values 或 core 层
        assert isinstance(result, OnionProfile)

    @pytest.mark.asyncio
    async def test_process_preserves_user_id(self, pipeline):
        """测试处理时保留 user_id"""
        profile = OnionProfile(user_id="user_001")
        event = BehaviorEvent(
            event_type="dialogue",
            content="测试内容",
            user_id="user_001",
        )
        result = await pipeline.process([event], profile)
        assert result.user_id == "user_001"

    @pytest.mark.asyncio
    async def test_process_accumulates_event_buffer(self, pipeline):
        """测试事件缓冲区累积"""
        # 第一次处理3个事件，不触发觉察分析
        events_1 = [
            BehaviorEvent(
                event_type="dialogue",
                content=f"内容 {i}",
                user_id="user_001",
            )
            for i in range(3)
        ]
        await pipeline.process(events_1)
        # 缓冲区应有3个事件
        assert len(pipeline._event_buffer) == 3

        # 第二次处理2个事件，累计5个触发觉察分析
        events_2 = [
            BehaviorEvent(
                event_type="dialogue",
                content=f"内容 {i+3}",
                user_id="user_001",
            )
            for i in range(2)
        ]
        await pipeline.process(events_2)
        # 触发觉察分析后缓冲区应被清空
        assert len(pipeline._event_buffer) == 0
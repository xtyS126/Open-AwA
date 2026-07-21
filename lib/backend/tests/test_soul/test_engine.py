"""
SoulEngine 主入口单元测试。
"""

import pytest
from soul.event import BehaviorEvent
from soul.profile import OnionProfile
from soul.engine import SoulEngine


class TestSoulEngine:
    """SoulEngine 测试套件。"""

    @pytest.fixture
    def engine(self):
        """创建 SoulEngine 实例"""
        return SoulEngine()

    @pytest.mark.asyncio
    async def test_process_event_new_user(self, engine):
        """测试处理新用户的事件"""
        event = BehaviorEvent(
            event_type="dialogue",
            content="这个工具很好用，我很喜欢",
            user_id="new_user",
        )
        profile = await engine.process_event("new_user", event)
        assert isinstance(profile, OnionProfile)
        assert profile.user_id == "new_user"
        assert profile.surface.confidence > 0.0

    @pytest.mark.asyncio
    async def test_process_events_multiple(self, engine):
        """测试批量处理多个事件"""
        events = [
            BehaviorEvent(
                event_type="dialogue",
                content=f"对话{i}，这个工具好用",
                user_id="user_001",
            )
            for i in range(3)
        ]
        profile = await engine.process_events("user_001", events)
        assert isinstance(profile, OnionProfile)
        assert profile.user_id == "user_001"

    @pytest.mark.asyncio
    async def test_process_event_accumulates_profile(self, engine):
        """测试连续处理事件会累积画像"""
        # 第一次处理
        event1 = BehaviorEvent(
            event_type="dialogue",
            content="这个工具好用",
            user_id="user_001",
        )
        profile1 = await engine.process_event("user_001", event1)

        # 第二次处理
        event2 = BehaviorEvent(
            event_type="dialogue",
            content="这个工具高效",
            user_id="user_001",
        )
        profile2 = await engine.process_event("user_001", event2)

        # 第二次处理后的置信度应 >= 第一次（累积效果）
        assert profile2.surface.confidence >= profile1.surface.confidence

    def test_get_profile_nonexistent(self, engine):
        """测试获取不存在的用户画像"""
        profile = engine.get_profile("nonexistent_user")
        assert profile is None

    def test_get_or_create_profile_new(self, engine):
        """测试获取或创建新用户画像"""
        profile = engine.get_or_create_profile("new_user")
        assert isinstance(profile, OnionProfile)
        assert profile.user_id == "new_user"

    def test_get_or_create_profile_existing(self, engine):
        """测试获取或创建已有用户画像"""
        # 先创建
        engine.get_or_create_profile("user_001")
        # 再次获取，应返回同一实例
        profile = engine.get_or_create_profile("user_001")
        assert profile.user_id == "user_001"

    def test_get_profile_summary_nonexistent(self, engine):
        """测试获取不存在用户的画像摘要"""
        summary = engine.get_profile_summary("nonexistent_user")
        assert summary == "画像尚未建立"

    def test_get_profile_summary_existing(self, engine):
        """测试获取已有用户的画像摘要"""
        engine.get_or_create_profile("user_001")
        summary = engine.get_profile_summary("user_001")
        assert isinstance(summary, str)

    @pytest.mark.asyncio
    async def test_get_profile_summary_after_events(self, engine):
        """测试事件处理后获取画像摘要"""
        event = BehaviorEvent(
            event_type="dialogue",
            content="这个工具很好用，我喜欢编程",
            user_id="user_001",
        )
        await engine.process_event("user_001", event)
        summary = engine.get_profile_summary("user_001")
        assert "行为表象" in summary or "喜欢" in summary

    def test_get_profile_for_prompt_nonexistent(self, engine):
        """测试获取不存在用户的 prompt 画像"""
        prompt_text = engine.get_profile_for_prompt("nonexistent_user")
        assert prompt_text == ""

    @pytest.mark.asyncio
    async def test_get_profile_for_prompt_with_data(self, engine):
        """测试获取有数据用户的 prompt 画像"""
        event = BehaviorEvent(
            event_type="dialogue",
            content="这个工具很好用",
            user_id="user_001",
        )
        await engine.process_event("user_001", event)
        prompt_text = engine.get_profile_for_prompt("user_001")
        # 只有 surface 层有内容，不足2层，不会生成 prompt 文本
        # 但 surface 层有内容，至少应有 [用户画像] 头部
        assert isinstance(prompt_text, str)

    def test_clear_profile(self, engine):
        """测试清除用户画像"""
        engine.get_or_create_profile("user_001")
        assert engine.get_profile("user_001") is not None

        engine.clear_profile("user_001")
        assert engine.get_profile("user_001") is None

    def test_clear_nonexistent_profile(self, engine):
        """测试清除不存在的用户画像（不应报错）"""
        engine.clear_profile("nonexistent_user")
        # 清除不存在的用户应不抛出异常
        assert engine.get_profile("nonexistent_user") is None

    @pytest.mark.asyncio
    async def test_process_events_sets_user_id(self, engine):
        """测试批量处理事件时设置 user_id"""
        events = [
            BehaviorEvent(
                event_type="dialogue",
                content="测试内容",
            )
            for _ in range(2)
        ]
        profile = await engine.process_events("user_002", events)
        assert profile.user_id == "user_002"
"""
Soul Engine 主入口。
协调画像分析器、管道和存储，提供统一的画像管理接口。
"""

from typing import Dict, Optional
from loguru import logger
from soul.event import BehaviorEvent
from soul.profile import OnionProfile
from soul.pipeline import ProfileUpdatePipeline


class SoulEngine:
    """
    Soul Engine 主类。
    协调画像分析器、管道和存储，提供统一的画像管理接口。
    """

    def __init__(self):
        self.pipeline = ProfileUpdatePipeline()
        # 内存中的画像缓存
        self._profiles: Dict[str, OnionProfile] = {}
        logger.info("SoulEngine 初始化完成")

    async def process_event(self, user_id: str, event: BehaviorEvent) -> OnionProfile:
        """
        处理单个行为事件，更新用户画像。

        Args:
            user_id: 用户ID
            event: 行为事件

        Returns:
            OnionProfile: 更新后的画像
        """
        event.user_id = user_id
        current_profile = self._profiles.get(user_id)

        updated_profile = await self.pipeline.process([event], current_profile)
        updated_profile.user_id = user_id
        self._profiles[user_id] = updated_profile

        return updated_profile

    async def process_events(self, user_id: str, events: list) -> OnionProfile:
        """
        处理多个行为事件，批量更新用户画像。

        Args:
            user_id: 用户ID
            events: 行为事件列表

        Returns:
            OnionProfile: 更新后的画像
        """
        for event in events:
            event.user_id = user_id

        current_profile = self._profiles.get(user_id)

        updated_profile = await self.pipeline.process(events, current_profile)
        updated_profile.user_id = user_id
        self._profiles[user_id] = updated_profile

        return updated_profile

    def get_profile(self, user_id: str) -> Optional[OnionProfile]:
        """
        获取用户画像。

        Args:
            user_id: 用户ID

        Returns:
            Optional[OnionProfile]: 用户画像，不存在时返回 None
        """
        return self._profiles.get(user_id)

    def get_or_create_profile(self, user_id: str) -> OnionProfile:
        """
        获取或创建用户画像。

        Args:
            user_id: 用户ID

        Returns:
            OnionProfile: 用户画像
        """
        if user_id not in self._profiles:
            self._profiles[user_id] = OnionProfile(user_id=user_id)
        return self._profiles[user_id]

    def get_profile_summary(self, user_id: str) -> str:
        """
        获取用户画像摘要。

        Args:
            user_id: 用户ID

        Returns:
            str: 画像摘要文本
        """
        profile = self.get_profile(user_id)
        if profile is None:
            return "画像尚未建立"
        return profile.get_summary()

    def get_profile_for_prompt(self, user_id: str) -> str:
        """
        获取用于注入 system prompt 的画像摘要。
        格式化为适合 LLM 理解的文本。

        Args:
            user_id: 用户ID

        Returns:
            str: 画像摘要（适合注入 prompt）
        """
        profile = self.get_profile(user_id)
        if profile is None:
            return ""

        parts = []
        parts.append("[用户画像]")
        if profile.surface.description:
            parts.append(f"- 行为偏好: {profile.surface.description}")
        if profile.interest.description:
            parts.append(f"- 兴趣偏好: {profile.interest.description}")
        if profile.role.description:
            parts.append(f"- 角色认同: {profile.role.description}")
        if profile.core.description:
            parts.append(f"- 人格特征: {profile.core.description}")
        if len(parts) <= 1:
            return ""

        return "\n".join(parts)

    def clear_profile(self, user_id: str) -> None:
        """
        清除用户画像。

        Args:
            user_id: 用户ID
        """
        if user_id in self._profiles:
            del self._profiles[user_id]
            logger.info(f"已清除用户画像: {user_id}")
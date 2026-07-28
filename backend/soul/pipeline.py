"""
画像更新管道。
将行为事件依次经过偏好分析、觉察分析、洞察分析，最终更新用户画像。
"""

from typing import List, Optional
from loguru import logger
from soul.event import BehaviorEvent
from soul.profile import OnionProfile
from soul.preference_analyzer import PreferenceAnalyzer, PreferenceUpdate
from soul.awareness_analyzer import AwarenessAnalyzer, AwarenessUpdate
from soul.insight_analyzer import InsightAnalyzer, InsightUpdate
from soul.layer_updaters import LayerUpdaters


class ProfileUpdatePipeline:
    """
    画像更新管道。
    事件 → 偏好分析 → 觉察分析 → 洞察分析 → 层更新 → 新画像
    """

    def __init__(self):
        self.preference_analyzer = PreferenceAnalyzer()
        self.awareness_analyzer = AwarenessAnalyzer()
        self.insight_analyzer = InsightAnalyzer()
        self.layer_updaters = LayerUpdaters()
        # 事件缓冲区，用于累积事件进行觉察分析
        self._event_buffer: List[BehaviorEvent] = []
        # 觉察分析触发阈值（累积多少事件后触发）
        self.AWARENESS_THRESHOLD = 5
        # 洞察分析触发阈值
        self.INSIGHT_THRESHOLD = 10

        logger.info("ProfileUpdatePipeline 初始化完成")

    async def process(self, events: List[BehaviorEvent], profile: Optional[OnionProfile] = None) -> OnionProfile:
        """
        处理行为事件，更新用户画像。

        Args:
            events: 行为事件列表
            profile: 当前用户画像（None 时创建空画像）

        Returns:
            OnionProfile: 更新后的画像
        """
        if profile is None:
            profile = OnionProfile()

        if not events:
            return profile

        # 第一层：偏好分析（每个事件单独分析）
        all_preferences: List[PreferenceUpdate] = []
        for event in events:
            preferences = await self.preference_analyzer.analyze(event)
            all_preferences.extend(preferences)

        if all_preferences:
            profile = self.layer_updaters.update_surface(profile, all_preferences)
            profile = self.layer_updaters.update_interest(profile, all_preferences)

        # 第二层：觉察分析（累积事件后触发）
        self._event_buffer.extend(events)
        if len(self._event_buffer) >= self.AWARENESS_THRESHOLD:
            awareness_updates = await self.awareness_analyzer.analyze(self._event_buffer)
            if awareness_updates:
                profile = self.layer_updaters.update_role(profile, awareness_updates)
            self._event_buffer = []  # 清空缓冲区

        # 第三层：洞察分析（画像足够丰富后触发）
        if self._is_profile_rich_enough(profile):
            insight_updates = await self.insight_analyzer.analyze(profile)
            if insight_updates:
                profile = self.layer_updaters.update_values(profile, insight_updates)
                profile = self.layer_updaters.update_core(profile, insight_updates)

        logger.bind(
            user_id=profile.user_id,
            event_count=len(events),
            preference_count=len(all_preferences),
        ).debug("画像管道处理完成")

        return profile

    def _is_profile_rich_enough(self, profile: OnionProfile) -> bool:
        """检查画像是否足够丰富以触发洞察分析"""
        # 至少有两层有内容
        layers_with_content = sum([
            1 if profile.surface.description else 0,
            1 if profile.interest.description else 0,
            1 if profile.role.description else 0,
        ])
        return layers_with_content >= 2
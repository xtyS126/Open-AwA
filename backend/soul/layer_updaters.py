"""
层更新器。
负责将分析结果应用到用户画像的对应层级。
"""

from typing import Any, Dict, List
from soul.profile import OnionProfile, LayerData
from soul.preference_analyzer import PreferenceUpdate
from soul.awareness_analyzer import AwarenessUpdate
from soul.insight_analyzer import InsightUpdate


class LayerUpdaters:
    """
    层更新器集合。
    将分析结果映射到五层画像的对应层级。
    """

    def update_surface(self, profile: OnionProfile, updates: List[PreferenceUpdate]) -> OnionProfile:
        """
        更新 surface 层（行为表象）。
        偏好更新直接反映在表层。
        """
        for update in updates:
            # 追加到表层描述
            if profile.surface.description:
                profile.surface.description += f"\n{update.detail}"
            else:
                profile.surface.description = update.detail

            # 更新结构化数据
            if update.target not in profile.surface.structured_data:
                profile.surface.structured_data[update.target] = []
            profile.surface.structured_data[update.target].append(update.detail)

            # 更新置信度
            profile.surface.confidence = min(1.0, profile.surface.confidence + update.confidence * 0.1)

        return profile

    def update_interest(self, profile: OnionProfile, updates: List[PreferenceUpdate]) -> OnionProfile:
        """
        更新 interest 层（兴趣偏好）。
        将偏好表达映射到兴趣层。
        """
        for update in updates:
            if update.preference_type == "like":
                if "likes" not in profile.interest.structured_data:
                    profile.interest.structured_data["likes"] = []
                profile.interest.structured_data["likes"].append(update.target)
                if profile.interest.description:
                    profile.interest.description += f"\n喜欢: {update.target}"
                else:
                    profile.interest.description = f"喜欢: {update.target}"

            elif update.preference_type == "dislike":
                if "dislikes" not in profile.interest.structured_data:
                    profile.interest.structured_data["dislikes"] = []
                profile.interest.structured_data["dislikes"].append(update.target)

            profile.interest.confidence = min(1.0, profile.interest.confidence + update.confidence * 0.05)

        return profile

    def update_role(self, profile: OnionProfile, updates: List[AwarenessUpdate]) -> OnionProfile:
        """
        更新 role 层（角色认同）。
        从行为模式中推断角色。
        """
        for update in updates:
            if update.pattern_type == "frequent_behavior":
                event_type = update.metadata.get("event_type", "")
                if event_type:
                    if "roles" not in profile.role.structured_data:
                        profile.role.structured_data["roles"] = []
                    profile.role.structured_data["roles"].append(f"频繁{event_type}")

            profile.role.confidence = min(1.0, profile.role.confidence + update.confidence * 0.1)

        return profile

    def update_values(self, profile: OnionProfile, updates: List[InsightUpdate]) -> OnionProfile:
        """
        更新 values 层（价值驱动）。
        从洞察中推断价值取向。
        """
        for update in updates:
            if update.insight_type == "cognitive_style":
                if "cognitive_style" not in profile.values.structured_data:
                    profile.values.structured_data["cognitive_style"] = update.value
                if profile.values.description:
                    profile.values.description += f"\n认知风格: {update.description}"
                else:
                    profile.values.description = f"认知风格: {update.description}"

            profile.values.confidence = min(1.0, profile.values.confidence + update.confidence * 0.1)

        return profile

    def update_core(self, profile: OnionProfile, updates: List[InsightUpdate]) -> OnionProfile:
        """
        更新 core 层（核心人格）。
        从洞察中推断 MBTI 和核心人格特征。
        """
        for update in updates:
            if update.insight_type == "mbti":
                profile.core.structured_data["mbti"] = update.value
                if profile.core.description:
                    profile.core.description += f"\nMBTI: {update.value}"
                else:
                    profile.core.description = f"MBTI: {update.value}"

            elif update.insight_type == "cognitive_style":
                profile.core.structured_data["cognitive_style"] = update.value

            profile.core.confidence = min(1.0, profile.core.confidence + update.confidence * 0.05)

        return profile
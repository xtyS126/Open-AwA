"""
画像覆盖层管理。
实现用户手动编辑与 AI 画像的合并逻辑（用户编辑 ⊕ AI 画像）。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from datetime import datetime
from soul.profile import OnionProfile, LayerData


@dataclass
class ProfileOverrides:
    """
    画像覆盖层。
    存储用户手动编辑的画像信息，优先级高于 AI 推断。
    """
    user_id: str = ""
    overrides: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def merge(self, ai_profile: OnionProfile) -> OnionProfile:
        """
        合并覆盖层与 AI 画像。
        用户手动编辑的内容优先于 AI 推断。

        Args:
            ai_profile: AI 推断的画像

        Returns:
            OnionProfile: 合并后的画像
        """
        merged = (ai_profile.__class__)(
            user_id=ai_profile.user_id,
            surface=ai_profile.surface,
            interest=ai_profile.interest,
            role=ai_profile.role,
            values=ai_profile.values,
            core=ai_profile.core,
            updated_at=ai_profile.updated_at,
        )

        # 逐个层合并覆盖
        for layer_name in ["surface", "interest", "role", "values", "core"]:
            if layer_name in self.overrides:
                override_data = self.overrides[layer_name]
                current_layer = getattr(merged, layer_name)

                # 覆盖描述
                if "description" in override_data and override_data["description"]:
                    current_layer.description = override_data["description"]

                # 合并结构化数据
                if "structured_data" in override_data:
                    current_layer.structured_data.update(override_data["structured_data"])

                # 覆盖置信度
                if "confidence" in override_data:
                    current_layer.confidence = override_data["confidence"]

                setattr(merged, layer_name, current_layer)

        return merged

    def set_override(self, layer_name: str, field: str, value: Any) -> None:
        """
        设置单个覆盖项。

        Args:
            layer_name: 层级名称（surface/interest/role/values/core）
            field: 字段名称（description/structured_data/confidence）
            value: 覆盖值
        """
        if layer_name not in self.overrides:
            self.overrides[layer_name] = {}
        self.overrides[layer_name][field] = value
        self.updated_at = datetime.utcnow()

    def remove_override(self, layer_name: str, field: Optional[str] = None) -> None:
        """
        移除覆盖项。

        Args:
            layer_name: 层级名称
            field: 字段名称（None 时移除整个层）
        """
        if field is None:
            self.overrides.pop(layer_name, None)
        elif layer_name in self.overrides:
            self.overrides[layer_name].pop(field, None)
            if not self.overrides[layer_name]:
                self.overrides.pop(layer_name, None)
        self.updated_at = datetime.utcnow()

    def get_effective_description(self, layer_name: str, ai_description: str) -> str:
        """
        获取生效的描述（优先使用覆盖层）。

        Args:
            layer_name: 层级名称
            ai_description: AI 推断的描述

        Returns:
            str: 生效的描述
        """
        if layer_name in self.overrides and "description" in self.overrides[layer_name]:
            override_desc = self.overrides[layer_name]["description"]
            if override_desc:
                return override_desc
        return ai_description

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "user_id": self.user_id,
            "overrides": self.overrides,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProfileOverrides":
        """从字典格式创建"""
        return cls(
            user_id=data.get("user_id", ""),
            overrides=data.get("overrides", {}),
            created_at=datetime.fromisoformat(data.get("created_at", datetime.utcnow().isoformat())),
            updated_at=datetime.fromisoformat(data.get("updated_at", datetime.utcnow().isoformat())),
        )
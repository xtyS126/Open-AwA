"""
用户五层画像数据模型（Onion Profile）。
五层结构：surface（行为表象）→ interest（兴趣偏好）→ role（角色认同）→ values（价值驱动）→ core（核心人格）。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class LayerData:
    """单层画像数据"""
    description: str = ""  # 自然语言描述
    structured_data: Dict[str, Any] = field(default_factory=dict)  # 结构化数据
    confidence: float = 0.0  # 置信度（0.0-1.0）


@dataclass
class OnionProfile:
    """
    五层用户画像（洋葱模型）。
    从外到内：surface → interest → role → values → core
    外层是表层行为，内层是深层心理特征。
    """
    user_id: str = ""
    # 第一层：行为表象（最近行为、偏好表达）
    surface: LayerData = field(default_factory=LayerData)
    # 第二层：兴趣偏好（喜欢/不喜欢/中性）
    interest: LayerData = field(default_factory=LayerData)
    # 第三层：角色认同（自我定位、身份标签）
    role: LayerData = field(default_factory=LayerData)
    # 第四层：价值驱动（决策依据、优先级）
    values: LayerData = field(default_factory=LayerData)
    # 第五层：核心人格（MBTI、认知风格）
    core: LayerData = field(default_factory=LayerData)
    # 画像更新时间
    updated_at: datetime = field(default_factory=lambda: datetime.utcnow())

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于数据库存储）"""
        return {
            "user_id": self.user_id,
            "surface": {
                "description": self.surface.description,
                "structured_data": self.surface.structured_data,
                "confidence": self.surface.confidence,
            },
            "interest": {
                "description": self.interest.description,
                "structured_data": self.interest.structured_data,
                "confidence": self.interest.confidence,
            },
            "role": {
                "description": self.role.description,
                "structured_data": self.role.structured_data,
                "confidence": self.role.confidence,
            },
            "values": {
                "description": self.values.description,
                "structured_data": self.values.structured_data,
                "confidence": self.values.confidence,
            },
            "core": {
                "description": self.core.description,
                "structured_data": self.core.structured_data,
                "confidence": self.core.confidence,
            },
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OnionProfile":
        """从字典格式创建画像"""
        def parse_layer(layer_data: Dict[str, Any]) -> LayerData:
            return LayerData(
                description=layer_data.get("description", ""),
                structured_data=layer_data.get("structured_data", {}),
                confidence=layer_data.get("confidence", 0.0),
            )

        return cls(
            user_id=data.get("user_id", ""),
            surface=parse_layer(data.get("surface", {})),
            interest=parse_layer(data.get("interest", {})),
            role=parse_layer(data.get("role", {})),
            values=parse_layer(data.get("values", {})),
            core=parse_layer(data.get("core", {})),
            updated_at=datetime.fromisoformat(data.get("updated_at", datetime.utcnow().isoformat())),
        )

    def get_summary(self) -> str:
        """生成画像摘要"""
        parts = []
        if self.surface.description:
            parts.append(f"行为表象: {self.surface.description}")
        if self.interest.description:
            parts.append(f"兴趣偏好: {self.interest.description}")
        if self.role.description:
            parts.append(f"角色认同: {self.role.description}")
        if self.values.description:
            parts.append(f"价值驱动: {self.values.description}")
        if self.core.description:
            parts.append(f"核心人格: {self.core.description}")
        return "\n".join(parts) if parts else "画像尚未建立"
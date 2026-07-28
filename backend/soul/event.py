"""
用户行为事件数据模型。
定义用户在系统中的各种行为事件，用于驱动画像更新管道。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class BehaviorEvent:
    """
    用户行为事件。
    记录用户在系统中的各种行为，作为画像更新的输入。
    """
    # 事件类型：dialogue（对话）、tool_call（工具调用）、content_consumption（内容消费）、feedback（反馈）
    event_type: str
    # 事件内容
    content: str
    # 事件发生时间
    timestamp: datetime = field(default_factory=datetime.utcnow)
    # 用户ID
    user_id: str = ""
    # 情感倾向：positive（正面）、negative（负面）、neutral（中性）
    sentiment: str = "neutral"
    # 话题标签
    topics: list = field(default_factory=list)
    # 上下文信息
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 有效的事件类型
    VALID_EVENT_TYPES = {"dialogue", "tool_call", "content_consumption", "feedback"}
    # 有效的情感类型
    VALID_SENTIMENTS = {"positive", "negative", "neutral"}

    def __post_init__(self):
        """校验事件类型和情感类型"""
        if self.event_type not in self.VALID_EVENT_TYPES:
            raise ValueError(f"无效的事件类型: {self.event_type}，有效值: {self.VALID_EVENT_TYPES}")
        if self.sentiment not in self.VALID_SENTIMENTS:
            raise ValueError(f"无效的情感类型: {self.sentiment}，有效值: {self.VALID_SENTIMENTS}")

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "event_type": self.event_type,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "user_id": self.user_id,
            "sentiment": self.sentiment,
            "topics": self.topics,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BehaviorEvent":
        """从字典格式创建事件"""
        return cls(
            event_type=data.get("event_type", ""),
            content=data.get("content", ""),
            timestamp=datetime.fromisoformat(data.get("timestamp", datetime.utcnow().isoformat())),
            user_id=data.get("user_id", ""),
            sentiment=data.get("sentiment", "neutral"),
            topics=data.get("topics", []),
            metadata=data.get("metadata", {}),
        )
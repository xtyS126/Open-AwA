"""
多 Agent 讨论任务核心数据结构定义。

本模块定义讨论任务相关的枚举、数据类与异常层级，供 orchestrator 与
API 路由层共享。所有数据类均提供与 SQLAlchemy 模型互转的方法。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional


# ── 枚举定义 ──────────────────────────────────────────────────────


class DiscussionStatus(str, Enum):
    """讨论任务状态机枚举。"""

    CREATED = "created"
    DISCUSSING = "discussing"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class DiscussionRole(str, Enum):
    """讨论角色枚举，每个角色代表一种评审视角。"""

    CRITIC = "critic"        # 批判性审查者
    VALIDATOR = "validator"  # 可行性验证者
    APPROVER = "approver"    # 最终批准者


class VoteDecision(str, Enum):
    """投票决策枚举。"""

    APPROVE = "approve"
    REJECT = "reject"
    ABSTAIN = "abstain"


# 内置角色列表，按讨论轮次中的发言顺序排列
BUILTIN_ROLES: List[DiscussionRole] = [
    DiscussionRole.CRITIC,
    DiscussionRole.VALIDATOR,
    DiscussionRole.APPROVER,
]


# ── 数据类定义 ──────────────────────────────────────────────────────


@dataclass
class ProposedAction:
    """
    待评审的提议动作。

    type 为执行器类型，payload 为执行器特定参数：
    - plugin_command: {"plugin": str, "method": str, "args": dict}
    - tool_call: {"tool": str, "parameters": dict}
    - subagent_delegate: {"agent": str, "instruction": str, "context_snippet": str}
    """

    type: Literal["plugin_command", "tool_call", "subagent_delegate"]
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，便于序列化为 JSON。"""
        return {"type": self.type, "payload": dict(self.payload)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProposedAction":
        """从字典构造实例，校验必填字段。"""
        if not isinstance(data, dict):
            raise ValueError("ProposedAction 数据必须为字典")
        action_type = data.get("type")
        if action_type not in ("plugin_command", "tool_call", "subagent_delegate"):
            raise ValueError(f"未知的提议动作类型: {action_type}")
        payload = data.get("payload") or {}
        if not isinstance(payload, dict):
            raise ValueError("ProposedAction.payload 必须为字典")
        return cls(type=action_type, payload=payload)


@dataclass
class DiscussionTaskData:
    """
    讨论任务数据传输对象，从 SQLAlchemy DiscussionTask 模型转换而来。

    用于 orchestrator 内部流转与 API 响应序列化。
    """

    id: str
    user_id: str
    title: str
    description: str
    proposed_action: ProposedAction
    context: Dict[str, Any] = field(default_factory=dict)
    status: str = DiscussionStatus.CREATED.value
    round: int = 1
    max_rounds: int = 3
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典。"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "description": self.description,
            "proposed_action": self.proposed_action.to_dict(),
            "context": dict(self.context),
            "status": self.status,
            "round": self.round,
            "max_rounds": self.max_rounds,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    @classmethod
    def from_orm(cls, model: Any) -> "DiscussionTaskData":
        """从 SQLAlchemy DiscussionTask 模型实例转换。"""
        return cls(
            id=model.id,
            user_id=model.user_id,
            title=model.title,
            description=model.description,
            proposed_action=ProposedAction.from_dict(model.proposed_action),
            context=dict(model.context) if model.context else {},
            status=model.status,
            round=model.round,
            max_rounds=model.max_rounds,
            created_at=model.created_at,
            updated_at=model.updated_at,
            completed_at=model.completed_at,
        )


@dataclass
class DiscussionVoteData:
    """
    讨论投票数据传输对象，从 SQLAlchemy DiscussionVote 模型转换而来。
    """

    id: str
    discussion_id: str
    role: str
    round: int
    vote: str
    reason: Optional[str] = None
    transcript: List[Any] = field(default_factory=list)
    created_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典。"""
        return {
            "id": self.id,
            "discussion_id": self.discussion_id,
            "role": self.role,
            "round": self.round,
            "vote": self.vote,
            "reason": self.reason,
            "transcript": list(self.transcript),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_orm(cls, model: Any) -> "DiscussionVoteData":
        """从 SQLAlchemy DiscussionVote 模型实例转换。"""
        return cls(
            id=model.id,
            discussion_id=model.discussion_id,
            role=model.role,
            round=model.round,
            vote=model.vote,
            reason=model.reason,
            transcript=list(model.transcript) if model.transcript else [],
            created_at=model.created_at,
        )


# ── 异常层级 ──────────────────────────────────────────────────────


class DiscussionError(Exception):
    """讨论任务相关异常基类。"""


class DiscussionStateError(DiscussionError):
    """非法状态转换或非法操作时抛出。"""


class DiscussionRoundLimitError(DiscussionError):
    """超过最大讨论轮次时抛出。"""


class DiscussionExecutionError(DiscussionError):
    """提议动作执行失败或执行器不可用时抛出。"""


class DiscussionParseError(DiscussionError):
    """LLM 输出解析失败时抛出（非致命，调用方应降级处理）。"""

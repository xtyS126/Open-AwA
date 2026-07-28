"""
工具审批反馈机制 — 用户拒绝工具调用后，Agent 收到反馈不再重试。
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from loguru import logger


class ApprovalStatus(Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING = "pending"
    TIMEOUT = "timeout"


@dataclass
class ToolApprovalRecord:
    """工具审批记录。"""
    approval_id: str
    tool_name: str
    tool_args: dict[str, Any]
    status: ApprovalStatus = ApprovalStatus.PENDING
    reject_reason: str = ""
    rejected_at: Optional[str] = None
    approved_at: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ToolApprovalManager:
    """
    工具审批管理器。
    管理工具审批的生命周期，生成拒绝后的 Agent 反馈指令。
    """

    def __init__(self):
        self._records: dict[str, ToolApprovalRecord] = {}
        self._rejection_cache: dict[str, set[str]] = {}  # session_id -> 被拒绝的工具集合

    def create_approval(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        session_id: str,
    ) -> str:
        """
        创建工具审批请求。
        返回 approval_id。
        """
        import uuid
        approval_id = str(uuid.uuid4())[:12]

        record = ToolApprovalRecord(
            approval_id=approval_id,
            tool_name=tool_name,
            tool_args=tool_args,
        )
        self._records[approval_id] = record

        logger.bind(
            event="tool_approval_created",
            approval_id=approval_id,
            tool=tool_name,
            session=session_id,
        ).info("工具审批已创建")

        return approval_id

    def approve(self, approval_id: str) -> dict:
        """
        批准工具调用。
        """
        record = self._records.get(approval_id)
        if not record:
            return {"error": "审批记录不存在"}

        record.status = ApprovalStatus.APPROVED
        record.approved_at = datetime.now(timezone.utc).isoformat()

        logger.bind(event="tool_approved", approval_id=approval_id, tool=record.tool_name).info("工具已批准")
        return {"status": "approved", "approval_id": approval_id}

    def reject(self, approval_id: str, reason: str = "", session_id: str = "") -> dict:
        """
        拒绝工具调用，生成 Agent 反馈指令。
        """
        record = self._records.get(approval_id)
        if not record:
            return {"error": "审批记录不存在"}

        record.status = ApprovalStatus.REJECTED
        record.reject_reason = reason
        record.rejected_at = datetime.now(timezone.utc).isoformat()

        # 缓存拒绝记录，防止 Agent 重试
        if session_id:
            if session_id not in self._rejection_cache:
                self._rejection_cache[session_id] = set()
            self._rejection_cache[session_id].add(record.tool_name)

        # 生成给 Agent 的反馈指令
        feedback = self._build_rejection_feedback(record)

        logger.bind(
            event="tool_rejected",
            approval_id=approval_id,
            tool=record.tool_name,
            reason=reason,
            session=session_id,
        ).info("工具已拒绝")

        return {
            "status": "rejected",
            "approval_id": approval_id,
            "feedback_to_agent": feedback,
            "should_retry": False,
        }

    def is_tool_rejected_in_session(self, session_id: str, tool_name: str) -> bool:
        """
        检查工具在指定会话中是否已被拒绝。
        """
        if session_id not in self._rejection_cache:
            return False
        return tool_name in self._rejection_cache[session_id]

    def clear_session_rejections(self, session_id: str):
        """
        清除会话中的拒绝缓存（新对话开始时调用）。
        """
        self._rejection_cache.pop(session_id, None)

    def get_pending_approvals(self) -> list[dict]:
        """
        获取所有待审批的记录。
        """
        return [
            {
                "approval_id": r.approval_id,
                "tool_name": r.tool_name,
                "tool_args": r.tool_args,
                "created_at": r.created_at,
            }
            for r in self._records.values()
            if r.status == ApprovalStatus.PENDING
        ]

    def _build_rejection_feedback(self, record: ToolApprovalRecord) -> str:
        """
        构建拒绝后的 Agent 反馈指令。
        """
        reason_text = f"，原因: {record.reject_reason}" if record.reject_reason else ""
        return (
            f"[工具审批结果] 工具 '{record.tool_name}' 的调用已被用户拒绝{reason_text}。"
            f"请不要重试该工具调用，改用其他方案完成任务，或向用户确认下一步操作。"
        )

    def build_agent_context(
        self,
        session_id: str,
        available_tools: list[str],
    ) -> Optional[str]:
        """
        为 Agent 构建包含被拒工具的上下文。
        在 System Prompt 中注入已被拒绝的工具列表。
        """
        rejected = self._rejection_cache.get(session_id, set())
        if not rejected:
            return None

        rejected_list = ", ".join(sorted(rejected))
        return (
            f"注意：以下工具在当前会话中已被用户拒绝，请勿再次调用：{rejected_list}。"
            f"请使用其他可用工具完成用户任务。"
        )


# 全局单例
_tool_approval_manager: Optional[ToolApprovalManager] = None


def get_tool_approval_manager() -> ToolApprovalManager:
    global _tool_approval_manager
    if _tool_approval_manager is None:
        _tool_approval_manager = ToolApprovalManager()
    return _tool_approval_manager

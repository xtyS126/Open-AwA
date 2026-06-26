"""
步骤级回滚管理模块，为 Agent 执行步骤提供快照和回滚能力。
每个步骤执行前保存快照，失败时自动回滚到上一个稳定状态。
"""

import copy
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from loguru import logger
from config.settings import settings


# 不可序列化的键名前缀和精确键名集合，深拷贝时跳过
_UNSERIALIZABLE_KEY_PREFIXES = ("_", "db", "session", "pricing")
_UNSERIALIZABLE_EXACT_KEYS = {
    "db", "session", "pricing_manager", "rollback_manager",
    "abort_controller", "content_replacement_state",
    "record_usage", "record_latency", "spawn_subagent",
    "agent", "executor", "planner", "comprehension", "feedback",
}


def _is_unserializable_key(key: str) -> bool:
    """判断 context 键是否可能持有不可序列化对象。"""
    if key in _UNSERIALIZABLE_EXACT_KEYS:
        return True
    for prefix in _UNSERIALIZABLE_KEY_PREFIXES:
        if key.startswith(prefix):
            return True
    return False


def _safe_deepcopy_context(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    安全深拷贝 Agent 上下文，跳过不可序列化的对象。

    Agent context 中常含 db session、回调函数、模块对象等，
    直接 deepcopy 会触发 "cannot pickle 'module' object" 错误。
    本函数仅拷贝可序列化的标量/列表/字典数据，跳过可疑键。
    """
    result: Dict[str, Any] = {}
    for key, value in context.items():
        if _is_unserializable_key(key):
            continue
        try:
            result[key] = copy.deepcopy(value)
        except (TypeError, ValueError, AttributeError) as e:
            # 单个键拷贝失败时跳过，记录调试日志
            logger.bind(
                event="snapshot_key_skip",
                module="rollback",
                key=key,
                error=str(e),
            ).debug(f"深拷贝 context 键 '{key}' 失败，已跳过: {e}")
    return result


@dataclass
class StepSnapshot:
    """步骤执行快照。"""
    step_index: int
    step_action: str
    context_state: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    description: str = ""


class RollbackManager:
    """
    步骤级回滚管理器。

    在每个步骤执行前保存上下文快照，步骤失败时可以回滚到上一个稳定状态。
    快照数量受 AGENT_SNAPSHOT_MAX_COUNT 限制，超出时自动淘汰最旧的快照。
    """

    def __init__(self, max_snapshots: Optional[int] = None):
        self._snapshots: List[StepSnapshot] = []
        self._max_snapshots = max_snapshots or settings.AGENT_SNAPSHOT_MAX_COUNT

    def save_snapshot(
        self,
        step_index: int,
        step_action: str,
        context: Dict[str, Any],
        description: str = "",
    ) -> StepSnapshot:
        """保存步骤执行前的上下文快照。"""
        context_copy = _safe_deepcopy_context(context)

        snapshot = StepSnapshot(
            step_index=step_index,
            step_action=step_action,
            context_state=context_copy,
            description=description,
        )

        self._snapshots.append(snapshot)

        while len(self._snapshots) > self._max_snapshots:
            removed = self._snapshots.pop(0)
            logger.bind(
                event="snapshot_evicted",
                module="rollback",
                step_index=removed.step_index,
            ).debug(f"淘汰旧快照: 步骤 {removed.step_index}")

        logger.bind(
            event="snapshot_saved",
            module="rollback",
            step_index=step_index,
            total_snapshots=len(self._snapshots),
        ).debug(f"保存快照: 步骤 {step_index} ({step_action})")

        return snapshot

    def rollback_to_last_stable(self) -> Optional[StepSnapshot]:
        """回滚到最后一个快照（即上一个稳定状态）。"""
        if not self._snapshots:
            logger.bind(event="rollback_no_snapshot", module="rollback").warning(
                "没有可用的快照，无法回滚"
            )
            return None

        snapshot = self._snapshots.pop()
        logger.bind(
            event="rollback_executed",
            module="rollback",
            step_index=snapshot.step_index,
            step_action=snapshot.step_action,
        ).info(f"回滚到步骤 {snapshot.step_index} ({snapshot.step_action})")

        return snapshot

    def get_context_after_rollback(self) -> Optional[Dict[str, Any]]:
        """执行回滚并返回恢复的上下文。"""
        snapshot = self.rollback_to_last_stable()
        if snapshot is None:
            return None
        return copy.deepcopy(snapshot.context_state)

    def clear(self) -> None:
        """清空所有快照。"""
        self._snapshots.clear()

    @property
    def snapshot_count(self) -> int:
        """当前快照数量。"""
        return len(self._snapshots)

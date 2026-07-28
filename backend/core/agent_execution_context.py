"""Agent 执行阶段使用的显式上下文对象。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class PlanExecutionContext:
    """封装计划执行与技能插件匹配必须保持一致的输入。"""

    intent: Dict[str, Any]
    entities: Dict[str, Any]
    intent_keywords: str
    entities_list: List[Dict[str, Any]]
    user_input: str
    context: Dict[str, Any]


@dataclass
class RoundState:
    """封装单轮模型调用的内容、计数与跨轮共享状态。"""

    round_count: int
    round_content: str
    round_reasoning: str
    shared_state: Dict[str, Any]
    effective_user_input: str


@dataclass(frozen=True)
class StreamFinalizationContext:
    """封装流结束清理所需的生命周期数据。"""

    user_input: str
    context: Dict[str, Any]
    state: Dict[str, Any]
    started_at: float
    task_user_id: str
    session_id: str
    current_task: Optional[Any]
    abort_controller: Optional[Any]

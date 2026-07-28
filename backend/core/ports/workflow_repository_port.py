"""工作流读取仓储端口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, runtime_checkable

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class WorkflowDefinition:
    """核心层执行工作流所需的持久化投影。"""

    workflow_id: Any
    name: str
    definition: Dict[str, Any]


@runtime_checkable
class WorkflowRepositoryPort(Protocol):
    """按 ID 读取工作流定义，并支持请求级会话重绑定。"""

    def bind_db(self, db_session: Session) -> None:
        """更新当前请求使用的数据库会话。"""
        ...

    async def find_by_id(self, workflow_id: Any) -> Optional[WorkflowDefinition]:
        """按 ID 返回工作流核心投影，不向核心层暴露 ORM 实体。"""
        ...

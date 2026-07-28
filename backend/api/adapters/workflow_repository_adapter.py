"""工作流仓储端口的 SQLAlchemy 适配器。"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from core.ports.workflow_repository_port import (
    WorkflowDefinition,
)
from db.models import Workflow


class WorkflowRepositoryAdapter:
    """使用请求级 SQLAlchemy Session 读取工作流投影。"""

    def __init__(self, db_session: Session) -> None:
        self._db_session = db_session

    def bind_db(self, db_session: Session) -> None:
        """Agent 实例复用时切换到当前请求的会话。"""
        self._db_session = db_session

    async def find_by_id(self, workflow_id: Any) -> Optional[WorkflowDefinition]:
        """查询 ORM 实体并转换为核心层投影。"""
        record = (
            self._db_session.query(Workflow)
            .filter(Workflow.id == workflow_id)
            .first()
        )
        if record is None:
            return None
        return WorkflowDefinition(
            workflow_id=record.id,
            name=record.name,
            definition=record.definition,
        )

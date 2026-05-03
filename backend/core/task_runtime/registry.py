"""
代理定义注册表，支持从内置定义、插件和数据库加载代理类型。
提供三层优先级: DB注册 > 插件注册 > 内置定义。
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from .definitions import AgentDefinition, BUILTIN_AGENT_DEFINITIONS


def _parse_json_field(value: Optional[str], default: list | dict) -> list | dict:
    """安全解析 JSON 字段。"""
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


class AgentDefinitionRegistry:
    """
    代理定义注册表，管理所有可用的 AgentDefinition。
    优先级: DB注册 > 插件注册 > 内置定义。
    """

    def __init__(self):
        self._db_definitions: Dict[str, AgentDefinition] = {}
        self._plugin_definitions: Dict[str, AgentDefinition] = {}

    def register(self, name: str, definition: AgentDefinition, source: str = "plugin") -> None:
        """注册一个代理定义，source 为 'plugin' 或 'db'。"""
        if source == "db":
            self._db_definitions[name] = definition
        else:
            self._plugin_definitions[name] = definition
        logger.bind(
            module="task_runtime",
            agent_type=name,
            source=source,
        ).info(f"代理定义已注册: {name}")

    def unregister(self, name: str) -> None:
        """注销一个代理定义（不影响内置定义）。"""
        self._db_definitions.pop(name, None)
        self._plugin_definitions.pop(name, None)

    def get(self, name: str) -> Optional[AgentDefinition]:
        """按名称查找定义，优先级: DB > 插件 > 内置。"""
        if name in self._db_definitions:
            return self._db_definitions[name]
        if name in self._plugin_definitions:
            return self._plugin_definitions[name]
        return BUILTIN_AGENT_DEFINITIONS.get(name)

    def list_types(self) -> List[str]:
        """列出所有可用代理类型名称，保持内置优先的顺序。"""
        seen = set()
        result = []
        for name in BUILTIN_AGENT_DEFINITIONS:
            seen.add(name)
            result.append(name)
        for name in self._plugin_definitions:
            if name not in seen:
                seen.add(name)
                result.append(name)
        for name in self._db_definitions:
            if name not in seen:
                seen.add(name)
                result.append(name)
        return result

    def load_from_db(self, db: Session) -> int:
        """从数据库加载持久化的代理定义（仅启用的）。"""
        from db.models import TaskAgentDefinition

        rows = db.query(TaskAgentDefinition).filter(
            TaskAgentDefinition.is_enabled == True
        ).all()

        count = 0
        for row in rows:
            try:
                definition = AgentDefinition(
                    name=row.name,
                    scope=row.scope,
                    description=row.description or "",
                    system_prompt=row.system_prompt or "",
                    tools=_parse_json_field(row.tools_json, []),  # type: ignore[arg-type]
                    disallowed_tools=_parse_json_field(row.disallowed_tools_json, []),  # type: ignore[arg-type]
                    model=row.model,
                    permission_mode=row.permission_mode,
                    memory_mode=row.memory_mode,
                    background_default=row.background_default,
                    isolation_mode=row.isolation_mode,
                    color=row.color or "",
                    metadata=_parse_json_field(row.metadata_json, {}),  # type: ignore[arg-type]
                )
                self._db_definitions[row.name] = definition
                count += 1
            except Exception as exc:
                logger.bind(
                    module="task_runtime",
                    name=row.name,
                    error=str(exc),
                ).warning(f"加载代理定义失败: {row.name}")

        if count:
            logger.bind(module="task_runtime", count=count).info(f"从数据库加载了 {count} 个代理定义")
        return count

    def save_to_db(self, db: Session, definition: AgentDefinition) -> bool:
        """将代理定义持久化到数据库。若已存在则更新，否则新增。"""
        from db.models import TaskAgentDefinition

        existing = db.query(TaskAgentDefinition).filter(
            TaskAgentDefinition.name == definition.name
        ).first()

        if existing:
            existing.scope = definition.scope
            existing.description = definition.description
            existing.system_prompt = definition.system_prompt
            existing.tools_json = json.dumps(definition.tools, ensure_ascii=False)
            existing.disallowed_tools_json = json.dumps(definition.disallowed_tools, ensure_ascii=False)
            existing.model = definition.model
            existing.permission_mode = definition.permission_mode
            existing.memory_mode = definition.memory_mode
            existing.background_default = definition.background_default
            existing.isolation_mode = definition.isolation_mode
            existing.color = definition.color
            existing.metadata_json = json.dumps(definition.metadata, ensure_ascii=False)
        else:
            row = TaskAgentDefinition(
                name=definition.name,
                scope=definition.scope,
                description=definition.description,
                system_prompt=definition.system_prompt,
                tools_json=json.dumps(definition.tools, ensure_ascii=False),
                disallowed_tools_json=json.dumps(definition.disallowed_tools, ensure_ascii=False),
                model=definition.model,
                permission_mode=definition.permission_mode,
                memory_mode=definition.memory_mode,
                background_default=definition.background_default,
                isolation_mode=definition.isolation_mode,
                color=definition.color,
                metadata_json=json.dumps(definition.metadata, ensure_ascii=False),
            )
            db.add(row)

        db.commit()
        self._db_definitions[definition.name] = definition
        logger.bind(module="task_runtime", name=definition.name).info(f"代理定义已持久化: {definition.name}")
        return True

    def delete_from_db(self, db: Session, name: str) -> bool:
        """从数据库删除代理定义（仅用户自定义，不影响内置）。"""
        from db.models import TaskAgentDefinition

        row = db.query(TaskAgentDefinition).filter(
            TaskAgentDefinition.name == name,
            TaskAgentDefinition.scope != "system",
        ).first()
        if not row:
            return False
        db.delete(row)
        db.commit()
        self._db_definitions.pop(name, None)
        logger.bind(module="task_runtime", name=name).info(f"代理定义已删除: {name}")
        return True


# 模块级单例
agent_registry = AgentDefinitionRegistry()

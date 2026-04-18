"""
工作流解析器，支持 YAML/JSON 两种定义格式。
负责把原始定义归一化为统一的内部结构。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Union

import yaml


class WorkflowParser:
    """
    工作流定义解析器。
    """

    def parse_definition(self, definition: Union[str, Dict[str, Any]], format_hint: str | None = None) -> Dict[str, Any]:
        """
        解析工作流定义并返回规范化结果。
        """
        raw_definition = definition
        if isinstance(definition, str):
            raw_definition = self._load_text_definition(definition, format_hint=format_hint)

        if not isinstance(raw_definition, dict):
            raise ValueError("工作流定义必须是对象结构")

        steps = raw_definition.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("工作流定义至少需要一个步骤")

        normalized_steps = [
            self._normalize_step(step, index=index)
            for index, step in enumerate(steps)
        ]

        return {
            "name": str(raw_definition.get("name") or "unnamed_workflow"),
            "description": str(raw_definition.get("description") or ""),
            "steps": normalized_steps,
        }

    def _load_text_definition(self, definition: str, format_hint: str | None = None) -> Dict[str, Any]:
        text = definition.strip()
        if not text:
            raise ValueError("工作流定义不能为空")

        normalized_hint = str(format_hint or "").strip().lower()
        if normalized_hint == "json" or text.startswith("{"):
            return json.loads(text)

        return yaml.safe_load(text)

    def _normalize_step(self, step: Dict[str, Any], index: int) -> Dict[str, Any]:
        if not isinstance(step, dict):
            raise ValueError(f"第 {index + 1} 个步骤必须是对象")

        step_type = str(step.get("type") or "tool").strip().lower()
        step_id = str(step.get("id") or f"step_{index + 1}")
        normalized = {
            **step,
            "id": step_id,
            "name": str(step.get("name") or step_id),
            "type": step_type,
        }

        if step_type == "condition":
            normalized["expression"] = str(step.get("expression") or "").strip()
            normalized["on_true"] = [
                self._normalize_step(child, index=child_index)
                for child_index, child in enumerate(step.get("on_true", []))
            ]
            normalized["on_false"] = [
                self._normalize_step(child, index=child_index)
                for child_index, child in enumerate(step.get("on_false", []))
            ]

        return normalized
"""技能系统 —— 可扩展的能力框架。

技能是自包含的模块，赋予 agent 特定的能力。
用户和社区可以创建自定义技能来扩展 agent。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SkillMetadata:
    """描述技能的元数据。"""

    name: str
    description: str
    version: str = "0.1.0"
    author: str = ""
    tags: list[str] = field(default_factory=list)


class Skill(ABC):
    """所有技能的基类。

    Skill 是 agent 可使用的独立、自包含能力。
    每个技能具有：
    - 名称与描述
    - 一个执行技能动作的 execute 方法
    - 输入/输出 schema 定义

    创建自定义技能的步骤：
    1. 继承 Skill
    2. 实现 `execute` 方法
    3. 定义 `metadata` 属性
    4. 放到 skills/ 目录下并附带 SKILL.md 文件
    """

    @property
    @abstractmethod
    def metadata(self) -> SkillMetadata:
        """返回此技能的元数据。"""
        ...

    @property
    def name(self) -> str:
        """技能名称快捷访问。"""
        return self.metadata.name

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        """执行技能。

        Args:
            **kwargs: 技能特定的参数。

        Returns:
            技能特定的结果。
        """
        ...

    def describe(self) -> str:
        """返回供 LLM 上下文使用的人类可读描述。"""
        meta = self.metadata
        return f"[{meta.name}] {meta.description}"


class SkillRegistry:
    """用于发现和管理技能的注册表。"""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        """注册一个技能实例。"""
        self._skills[skill.name] = skill
        logger.info("Skill registered: %s", skill.name)

    def get(self, name: str) -> Skill | None:
        """按名称获取技能。"""
        return self._skills.get(name)

    @property
    def all_skills(self) -> list[Skill]:
        """所有已注册的技能。"""
        return list(self._skills.values())

    def describe_all(self) -> str:
        """返回所有技能的描述（供 LLM 上下文使用）。"""
        return "\n".join(skill.describe() for skill in self._skills.values())

    @staticmethod
    def discover_skills(skills_dir: Path) -> list[Path]:
        """在指定路径下发现技能目录。

        一个合法的技能目录需包含 SKILL.md 文件。

        Args:
            skills_dir: 搜索技能的根目录。

        Returns:
            SKILL.md 文件的路径列表。
        """
        if not skills_dir.exists():
            return []
        return sorted(skills_dir.glob("*/SKILL.md"))

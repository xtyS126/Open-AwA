"""
统一内置工具注册器。
负责懒加载文件管理、终端执行和网页搜索工具，并提供对 SkillRegistry 的内置技能注册能力。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from skills.built_in.file_manager import FileManagerSkill
from skills.built_in.terminal_executor import TerminalExecutorSkill
from skills.built_in.web_search import WebSearchSkill
from skills.skill_loader import SkillLoader


class BuiltInToolRegistry:
    """
    内置工具注册器。
    对外统一暴露工具查询、执行与技能种子初始化能力。
    """

    def __init__(self):
        self._instances: Dict[str, Any] = {}

    async def _initialize_tool(self, tool_name: str, config: Optional[Dict[str, Any]] = None) -> Any:
        if tool_name in self._instances and not config:
            return self._instances[tool_name]

        config = config or {}
        if tool_name == "file_manager":
            instance = FileManagerSkill(config)
        elif tool_name == "terminal_executor":
            instance = TerminalExecutorSkill(config)
        elif tool_name == "web_search":
            instance = WebSearchSkill(config)
        else:
            raise ValueError(f"未知内置工具: {tool_name}")

        await instance.initialize()
        self._instances[tool_name] = instance
        return instance

    async def list_tools(self) -> Dict[str, Dict[str, Any]]:
        """
        返回全部内置工具的定义与状态。
        """
        tools = {}
        for tool_name in ["file_manager", "terminal_executor", "web_search"]:
            instance = await self._initialize_tool(tool_name)
            tools[tool_name] = {
                "name": tool_name,
                "display_name": getattr(instance, "name", tool_name),
                "description": getattr(instance, "description", ""),
                "version": getattr(instance, "version", "1.0.0"),
                "tools": instance.get_tools(),
            }
        return tools

    async def execute_tool(
        self,
        tool_name: str,
        *,
        action: str,
        params: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        执行指定内置工具动作。
        """
        instance = await self._initialize_tool(tool_name, config=config)
        return await instance.execute(action=action, **(params or {}))

    def _config_files(self) -> List[Path]:
        configs_dir = Path(__file__).resolve().parents[1] / "skills" / "configs"
        return sorted(configs_dir.glob("*.yaml"))

    def seed_built_in_skills(self, db_session) -> int:
        """
        将内置工具以技能配置形式写入数据库，供 SkillRegistry 与工作流复用。
        """
        loader = SkillLoader(db_session)
        inserted = 0

        for config_file in self._config_files():
            config = loader.load_from_file(str(config_file))
            if not config.get("builtin_tool"):
                continue
            loader.convert_to_skill_model(config)
            inserted += 1

        if inserted > 0:
            db_session.commit()
            logger.info(f"已同步 {inserted} 个内置工具技能配置")
        return inserted


built_in_tool_registry = BuiltInToolRegistry()
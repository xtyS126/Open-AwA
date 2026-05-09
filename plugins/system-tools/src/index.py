"""
系统内置工具插件，集成文件管理和终端执行能力。
将原有的 file_manager 和 terminal_executor 技能转换为统一的内置插件。
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

# 在插件加载时 backend/ 目录已加入 sys.path，可直接导入核心工具
from core.builtin_tools.file_manager import FileManagerSkill
from core.builtin_tools.terminal_executor import TerminalExecutorSkill
from plugins.base_plugin import BasePlugin


# 文件管理支持的操作列表
_FILE_ACTIONS = frozenset({
    "read_file",
    "write_file",
    "list_files",
    "delete_file",
    "file_exists",
    "create_directory",
})

# 终端执行支持的操作列表
_TERMINAL_ACTIONS = frozenset({
    "run_command",
    "get_status",
    "get_system_status",
})


class SystemToolsPlugin(BasePlugin):
    """
    系统内置工具插件，提供文件管理和终端命令执行功能。
    替代原有的 file_manager 和 terminal_executor 技能，以插件形式对外提供服务。
    """

    name: str = "system-tools"
    version: str = "1.0.0"
    description: str = "系统内置工具插件，提供文件管理和终端命令执行能力"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """初始化插件，创建文件管理和终端执行技能实例。"""
        super().__init__(config)
        self._file_skill: Optional[FileManagerSkill] = None
        self._terminal_skill: Optional[TerminalExecutorSkill] = None

    def initialize(self) -> bool:
        """
        同步初始化子技能实例。
        直接配置允许目录而不依赖异步 initialize 方法，避免事件循环冲突。
        """
        logger.info(f"[{self.name}] 开始初始化系统内置工具插件 v{self.version}")
        try:
            # 初始化文件管理技能
            file_config = self.config.get("file_manager", {})
            self._file_skill = FileManagerSkill(config=file_config)
            # 直接调用内部初始化方法，避免 async 事件循环冲突
            self._file_skill._setup_allowed_directories()
            self._file_skill._initialized = True
            logger.info(f"[{self.name}] 文件管理技能已初始化，允许目录: {self._file_skill.allowed_directories}")

            # 初始化终端执行技能
            terminal_config = self.config.get("terminal_executor", {})
            self._terminal_skill = TerminalExecutorSkill(config=terminal_config)
            if not self._terminal_skill.allowed_directories:
                self._terminal_skill.allowed_directories = [str(Path(os.getcwd()).resolve())]
            self._terminal_skill._initialized = True
            logger.info(f"[{self.name}] 终端执行技能已初始化，超时: {self._terminal_skill.timeout}s")

            self._initialized = True
            logger.info(f"[{self.name}] 系统内置工具插件初始化完成")
            return True
        except Exception as exc:
            logger.error(f"[{self.name}] 初始化失败: {exc}")
            return False

    async def execute(self, *args, **kwargs) -> Dict[str, Any]:
        """
        异步统一执行入口，根据 action 参数分发到文件管理或终端执行。

        文件管理 action：read_file / write_file / list_files / delete_file / file_exists / create_directory
        终端执行 action：run_command / get_status / get_system_status
        """
        if not self._initialized:
            return {"success": False, "status": "error", "error": "插件未初始化"}

        action = kwargs.get("action", "")
        logger.info(f"[{self.name}] 执行操作: {action}")

        if action in _FILE_ACTIONS:
            return await self._file_skill.execute(**kwargs)
        elif action in _TERMINAL_ACTIONS:
            # get_system_status 映射到内部 get_status
            if action == "get_system_status":
                kwargs = dict(kwargs)
                kwargs["action"] = "get_status"
            return await self._terminal_skill.execute(**kwargs)
        else:
            return {
                "success": False,
                "status": "error",
                "error": f"未知操作: {action}，支持的操作: {sorted(_FILE_ACTIONS | _TERMINAL_ACTIONS)}"
            }

    def validate(self) -> bool:
        """校验插件配置。"""
        return True

    def cleanup(self) -> None:
        """清理资源。"""
        logger.info(f"[{self.name}] 插件清理中")
        super().cleanup()
        logger.info(f"[{self.name}] 插件已清理")

    def on_enabled(self) -> None:
        logger.info(f"[{self.name}] 插件已启用")
        super().on_enabled()

    def on_disabled(self) -> None:
        logger.info(f"[{self.name}] 插件已禁用")
        super().on_disabled()

    def get_tools(self) -> List[Dict[str, Any]]:
        """返回所有可用工具的定义列表。"""
        file_tools = self._file_skill.get_tools() if self._file_skill else []
        terminal_tools = self._terminal_skill.get_tools() if self._terminal_skill else []

        # 为每个工具设置默认参数，以便插件执行框架正确映射 action
        for tool in file_tools:
            tool.setdefault("default_params", {})
            tool["default_params"]["action"] = tool["name"]

        for tool in terminal_tools:
            tool.setdefault("default_params", {})
            if tool["name"] == "get_system_status":
                tool["default_params"]["action"] = "get_status"
            else:
                tool["default_params"]["action"] = tool["name"]

        return file_tools + terminal_tools

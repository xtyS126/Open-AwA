"""系统工具集内置插件入口模块。

实现 ``SystemToolsPlugin(BasePlugin)`` 子类，作为 Open-AwA
插件系统中 ``system-tools`` 内置插件的配置持有者与生命周期管理入口。

关键设计：
- 系统工具（文件管理、终端执行、网页搜索、本地检索、记忆管理、浏览器扩展）
  的实际实现位于 ``core/builtin_tools/``，由 ``builtin_tool_manager`` 统一懒加载
  并通过 function calling 协议直接暴露给 Agent。
- 本插件不重复暴露工具定义（避免与 ``builtin_tool_manager`` 产生同名工具冲突），
  ``get_tools()`` 返回空列表；插件职责是持有 schema.json 配置并在初始化时
  将配置应用到 ``builtin_tool_manager`` 的底层工具实例。
- ``execute()`` 抛 ``NotImplementedError``，与 ``user-profile-builtin`` 一致。
- ``cleanup()`` 为同步方法（被 ``_load_rollback`` 同步调用）。
- manifest.json 中的 ``extensions`` 为元数据声明，标识本插件配置的工具能力范围，
  与 ``get_tools()`` 返回值不强制一致。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger

from plugins.base_plugin import BasePlugin


class SystemToolsPlugin(BasePlugin):
    """系统工具集内置插件入口类。

    作为 ``core/builtin_tools/`` 各工具的配置持有者：
    - 持有 schema.json 中定义的运行参数（超时、白名单、开关等）
    - 在 ``initialize()`` 时将配置应用到 ``builtin_tool_manager`` 的工具实例
    - 不直接暴露工具定义（工具由 ``builtin_tool_manager`` 通过 function calling 暴露）
    """

    name: str = "system-tools"
    version: str = "1.0.0"
    description: str = (
        "系统工具集内置插件，提供文件管理、终端执行、网页搜索、本地检索、"
        "记忆管理与浏览器扩展能力的配置入口"
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        # 已应用配置的工具实例名集合（用于 cleanup 时判断）
        self._configured_tools: List[str] = []

    async def initialize(self) -> bool:
        """初始化插件：将 schema 配置应用到 builtin_tool_manager 的底层工具实例。

        builtin_tool_manager 采用懒加载，仅在工具已被实例化时应用配置；
        尚未加载的工具会在首次 ``_initialize_tool`` 时从插件配置注入。

        Returns:
            True 表示初始化成功。
        """
        self._apply_config_to_builtin_manager()
        logger.info(
            f"SystemToolsPlugin 初始化完成，已配置工具数={len(self._configured_tools)}"
        )
        return True

    def get_tools(self) -> List[Dict[str, Any]]:
        """返回插件暴露的工具定义列表。

        系统工具的实际工具定义由 ``builtin_tool_manager.get_tool_definitions()``
        通过 function calling 协议直接暴露给 Agent，本插件不重复声明，
        避免产生同名工具冲突。返回空列表。
        """
        return []

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        """BasePlugin 抽象方法实现。

        SystemToolsPlugin 不通过统一 execute 入口调度，
        工具调用直接走 ``builtin_tool_manager.execute_tool``。
        """
        raise NotImplementedError(
            "SystemToolsPlugin 不支持统一 execute 入口，"
            "系统工具调用请通过 builtin_tool_manager.execute_tool"
        )

    def cleanup(self) -> None:
        """清理插件资源：重置已配置工具记录。

        注意：plugin_manager._load_rollback 同步调用 cleanup()，
        因此本方法必须为同步方法（与 BasePlugin.cleanup 基类一致）。
        不主动销毁 builtin_tool_manager 中的工具实例（它们由全局管理器统一管理生命周期）。
        """
        self._configured_tools = []
        self._initialized = False

    # ── 配置应用逻辑 ────────────────────────────────────────────

    def _apply_config_to_builtin_manager(self) -> None:
        """将插件配置应用到 builtin_tool_manager 中已实例化的工具。

        builtin_tool_manager 采用懒加载策略，仅在工具已被实例化时应用配置；
        尚未加载的工具会在首次初始化时通过 config 参数注入。
        此处对已缓存实例做热更新，对未加载工具记录待注入的 config。
        """
        try:
            from core.builtin_tools.manager import builtin_tool_manager
        except ImportError as exc:
            logger.warning(
                f"无法导入 builtin_tool_manager，跳过系统工具配置应用: {exc}"
            )
            return

        config = self.config or {}

        # 构建 builtin_tool_manager 各工具的 config 子字典
        tool_configs: Dict[str, Dict[str, Any]] = {}

        # 文件管理工具配置
        if config.get("file_manager_enabled", True):
            tool_configs["file_manager"] = {
                "allowed_directories": self._parse_csv(
                    config.get("file_manager_allowed_directories", "")
                ),
                "max_file_size_mb": config.get("file_manager_max_file_size_mb", 50),
            }

        # 终端执行工具配置
        if config.get("terminal_executor_enabled", True):
            tool_configs["terminal_executor"] = {
                "timeout_seconds": config.get(
                    "terminal_executor_timeout_seconds", 30
                ),
                "max_output_chars": config.get(
                    "terminal_executor_max_output_chars", 50000
                ),
                "allowed_directories": self._parse_csv(
                    config.get("terminal_executor_allowed_directories", "")
                ),
            }

        # 网页搜索工具配置
        if config.get("web_search_enabled", True):
            tool_configs["web_search"] = {
                "default_engine": config.get("web_search_default_engine", "searxng"),
                "max_results": config.get("web_search_max_results", 10),
                "timeout_seconds": config.get("web_search_timeout_seconds", 15),
            }

        # 本地检索工具配置
        if config.get("local_search_enabled", True):
            tool_configs["local_search"] = {
                "index_path": config.get(
                    "local_search_index_path", "./data/local_search_index"
                ),
                "max_results": config.get("local_search_max_results", 20),
            }

        # 记忆管理工具配置
        if config.get("memory_manager_enabled", True):
            tool_configs["memory_manager"] = {
                "backend": config.get("memory_manager_backend", "sqlite"),
                "max_facts_per_user": config.get(
                    "memory_manager_max_facts_per_user", 1000
                ),
            }

        # 浏览器扩展工具配置
        if config.get("browser_extended_enabled", False):
            tool_configs["browser_extended"] = {
                "headless": config.get("browser_extended_headless", True),
                "default_timeout_seconds": config.get(
                    "browser_extended_default_timeout_seconds", 30
                ),
            }

        # 对已实例化的工具热更新配置
        for tool_name, tool_config in tool_configs.items():
            instance = builtin_tool_manager._instances.get(tool_name)
            if instance is None:
                # 未加载的工具：暂存 config，首次 _initialize_tool 时注入
                # builtin_tool_manager._initialize_tool 接受 config 参数，由调用方传入
                # 此处仅记录，实际注入由 executor 调用时从插件配置读取
                logger.debug(
                    f"工具 '{tool_name}' 尚未实例化，配置将在首次加载时注入"
                )
                continue
            try:
                self._apply_config_to_instance(instance, tool_name, tool_config)
                self._configured_tools.append(tool_name)
            except Exception as exc:
                logger.warning(
                    f"应用配置到工具 '{tool_name}' 失败: {exc}"
                )

    def _apply_config_to_instance(
        self,
        instance: Any,
        tool_name: str,
        tool_config: Dict[str, Any],
    ) -> None:
        """将配置应用到工具实例的对应属性。

        不同工具有不同的配置属性名，按工具类型分发。
        容错处理：仅更新实例已存在的属性，跳过不支持的配置项。
        """
        if tool_name == "file_manager":
            if hasattr(instance, "allowed_directories"):
                instance.allowed_directories = tool_config.get("allowed_directories") or []
            if hasattr(instance, "max_file_size_mb"):
                instance.max_file_size_mb = tool_config.get("max_file_size_mb", 50)
        elif tool_name == "terminal_executor":
            if hasattr(instance, "timeout_seconds"):
                instance.timeout_seconds = tool_config.get("timeout_seconds", 30)
            if hasattr(instance, "max_output_chars"):
                instance.max_output_chars = tool_config.get("max_output_chars", 50000)
            if hasattr(instance, "allowed_directories"):
                instance.allowed_directories = tool_config.get("allowed_directories") or []
        elif tool_name == "web_search":
            if hasattr(instance, "default_engine"):
                instance.default_engine = tool_config.get("default_engine", "searxng")
            if hasattr(instance, "max_results"):
                instance.max_results = tool_config.get("max_results", 10)
            if hasattr(instance, "timeout_seconds"):
                instance.timeout_seconds = tool_config.get("timeout_seconds", 15)
        elif tool_name == "local_search":
            if hasattr(instance, "index_path"):
                instance.index_path = tool_config.get(
                    "index_path", "./data/local_search_index"
                )
            if hasattr(instance, "max_results"):
                instance.max_results = tool_config.get("max_results", 20)
        elif tool_name == "memory_manager":
            if hasattr(instance, "backend"):
                instance.backend = tool_config.get("backend", "sqlite")
            if hasattr(instance, "max_facts_per_user"):
                instance.max_facts_per_user = tool_config.get("max_facts_per_user", 1000)
        elif tool_name == "browser_extended":
            if hasattr(instance, "headless"):
                instance.headless = tool_config.get("headless", True)
            if hasattr(instance, "default_timeout_seconds"):
                instance.default_timeout_seconds = tool_config.get(
                    "default_timeout_seconds", 30
                )
        else:
            logger.debug(f"未知工具类型 '{tool_name}'，跳过配置应用")

    @staticmethod
    def _parse_csv(value: str) -> List[str]:
        """解析逗号分隔的字符串为列表，空字符串返回空列表。

        Args:
            value: 逗号分隔的字符串（如 "/path/a, /path/b"）。

        Returns:
            路径列表，空白项已过滤。
        """
        if not value or not isinstance(value, str):
            return []
        return [item.strip() for item in value.split(",") if item.strip()]

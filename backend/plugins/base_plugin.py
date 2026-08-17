"""
插件系统模块，负责插件定义、加载、校验、沙箱隔离、生命周期或扩展协议处理。
这一层通常同时涉及可扩展性、安全性与运行时状态管理。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List, ClassVar

from .plugin_context import PluginContext


class BasePlugin(ABC):
    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    enable_count: int = 0
    rollback_events: ClassVar[List[str]] = []
    HELP_SENSITIVE_KEYWORDS: ClassVar[tuple[str, ...]] = (
        "key",
        "token",
        "secret",
        "password",
        "credential",
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """初始化插件实例：加载配置字典，设置默认状态为 'registered'。"""
        self.config = config or {}
        self.context: Optional[PluginContext] = None
        self._initialized = False
        self._state = "registered"
        self.rollback_events = []

    def set_context(self, context: PluginContext) -> None:
        self.context = context

    @abstractmethod
    def initialize(self) -> bool:
        """抽象方法：插件初始化逻辑，子类必须实现。返回 True 表示初始化成功。"""
        raise NotImplementedError

    @abstractmethod
    def execute(self, *args, **kwargs) -> Any:
        """抽象方法：执行插件核心功能，子类必须实现。"""
        raise NotImplementedError

    def cleanup(self) -> None:
        """清理插件资源：重置 _initialized 标志。"""
        self._initialized = False

    def validate(self) -> bool:
        """验证插件配置有效性，基类默认返回 True，子类可按需覆写。"""
        return True

    def on_registered(self) -> None:
        """生命周期钩子：插件已注册到系统。"""
        self._state = "registered"

    def on_loaded(self) -> None:
        """生命周期钩子：插件代码已加载到内存。"""
        self._state = "loaded"

    def on_enabled(self) -> None:
        """生命周期钩子：插件已启用，可以对外提供服务。"""
        self._state = "enabled"

    def on_disabled(self) -> None:
        """生命周期钩子：插件已被禁用。"""
        self._state = "disabled"

    def on_unloaded(self) -> None:
        """生命周期钩子：插件已从内存中卸载。"""
        self._state = "unloaded"

    def on_updating(self) -> None:
        """生命周期钩子：插件正在进行蓝绿热更新。"""
        self._state = "updating"

    def on_error_state(self) -> None:
        """生命周期钩子：插件进入错误状态。"""
        self._state = "error"

    def on_error(self, error: Exception, from_state: str, to_state: str) -> None:
        """生命周期钩子：状态迁移发生异常时回调，可记录错误上下文。"""
        self._state = "error"

    def rollback(self, previous_state: str, context: Optional[Dict[str, Any]] = None) -> bool:
        """回滚插件状态到之前的状态，基类默认恢复 _state 并返回 True。"""
        self._state = previous_state
        return True

    def _mask_help_config_value(self, key: str, value: Any) -> Any:
        """
        在帮助输出中隐藏敏感配置，避免把密钥类信息直接暴露给模型或前端。
        """
        normalized_key = key.lower()
        if any(keyword in normalized_key for keyword in self.HELP_SENSITIVE_KEYWORDS):
            return {
                "configured": bool(value),
                "masked": "***" if value else "",
            }

        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, list):
            return f"list[{len(value)}]"
        if isinstance(value, dict):
            return f"object[{len(value)}]"
        return str(value)

    def _build_help_tool_item(self, tool: Dict[str, Any]) -> Dict[str, Any]:
        """
        将工具定义转换为适合帮助展示的结构化内容。
        """
        parameters = tool.get("parameters") if isinstance(tool.get("parameters"), dict) else {}
        properties = parameters.get("properties") if isinstance(parameters.get("properties"), dict) else {}
        required = parameters.get("required") if isinstance(parameters.get("required"), list) else []

        parameter_details: List[Dict[str, Any]] = []
        for parameter_name, schema in properties.items():
            schema_payload = schema if isinstance(schema, dict) else {}
            item = {
                "name": parameter_name,
                "type": schema_payload.get("type", "any"),
                "required": parameter_name in required,
                "description": schema_payload.get("description", ""),
            }
            if "enum" in schema_payload:
                item["enum"] = schema_payload.get("enum")
            parameter_details.append(item)

        required_text = "、".join(required) if required else "无"
        usage_hint = f"调用 {tool.get('name', '')} 前需要关注的必填参数: {required_text}"

        return {
            "name": tool.get("name", ""),
            "description": tool.get("description", ""),
            "required_parameters": required,
            "parameter_details": parameter_details,
            "usage_hint": usage_hint,
        }

    def get_help(self, tool_name: Optional[str] = None, include_examples: bool = True) -> Dict[str, Any]:
        """
        返回插件用途、配置摘要、工具列表和调用建议，供模型在首次使用插件时查询。
        """
        raw_tools: List[Dict[str, Any]] = []
        if hasattr(self, "get_tools") and callable(getattr(self, "get_tools")):
            try:
                candidate_tools = self.get_tools()
                if isinstance(candidate_tools, list):
                    raw_tools = [item for item in candidate_tools if isinstance(item, dict)]
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"构建帮助信息失败: {e}",
                }

        tools = [self._build_help_tool_item(tool) for tool in raw_tools]
        if tool_name:
            normalized_tool_name = str(tool_name).strip().lower()
            tools = [tool for tool in tools if str(tool.get("name", "")).lower() == normalized_tool_name]
            if not tools:
                return {
                    "status": "not_found",
                    "message": f"插件 '{self.name}' 中未找到工具: {tool_name}",
                }

        config_summary = {
            key: self._mask_help_config_value(key, value)
            for key, value in self.config.items()
        }

        usage_steps = [
            "先阅读 tools 中的 description、required_parameters 和 parameter_details。",
            "按需调用具体工具；如果拿到的是结构化数据，直接基于这些数据继续回答，不要重复调用无关工具。",
        ]
        if include_examples:
            usage_steps.append("当不确定某个工具参数时，可再次调用 help 并传入 tool_name 查看单个工具说明。")

        return {
            "status": "success",
            "plugin": self.name,
            "version": self.version,
            "description": self.description,
            "configuration": config_summary,
            "tools": tools,
            "usage_steps": usage_steps,
        }

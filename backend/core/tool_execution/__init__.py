"""
工具执行策略模块：将工具分发逻辑从巨型 if-elif 链替换为策略模式注册表。
"""
from .base import ToolExecutionStrategy, ToolExecutionContext, ToolExecutionResult
from .registry import ToolExecutionStrategyRegistry
from .builtin_strategy import BuiltinToolStrategy
from .plugin_strategy import PluginToolStrategy
from .mcp_strategy import MCPToolStrategy
from .task_strategy import TaskToolStrategy

__all__ = [
    "ToolExecutionStrategy",
    "ToolExecutionContext",
    "ToolExecutionResult",
    "ToolExecutionStrategyRegistry",
    "BuiltinToolStrategy",
    "PluginToolStrategy",
    "MCPToolStrategy",
    "TaskToolStrategy",
]
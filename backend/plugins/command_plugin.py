"""
命令插件模块 — 允许插件注册自定义魔法命令 (/command)。
扩展插件系统的能力类型：Provider/Hook/Command/HTTP API/前端页面/工具渲染/组件行为。
"""
from typing import Optional
from dataclasses import dataclass

from loguru import logger


@dataclass
class CommandPluginDef:
    """命令插件定义。"""
    name: str
    description: str
    handler_module: str
    plugin_id: str
    requires_wait: bool = False


@dataclass
class ToolRenderPluginDef:
    """工具渲染插件定义 — 自定义工具调用结果的展示方式。"""
    tool_name: str
    render_module: str
    plugin_id: str
    description: str = ""


@dataclass
class ComponentOverrideDef:
    """组件行为修改定义 — 通过模块注册表修改前端已有组件行为。"""
    component_path: str
    override_module: str
    plugin_id: str
    description: str = ""


class PluginExtensionRegistry:
    """
    插件扩展注册表。
    管理插件注册的自定义命令、工具渲染和组件行为修改。
    """

    def __init__(self):
        self._commands: dict[str, CommandPluginDef] = {}
        self._tool_renders: dict[str, ToolRenderPluginDef] = {}
        self._component_overrides: dict[str, ComponentOverrideDef] = {}

    # ---- 命令插件 ----

    def register_command(self, cmd: CommandPluginDef) -> bool:
        """注册插件命令。"""
        if cmd.name in self._commands:
            logger.warning(f"命令 '{cmd.name}' 已被注册，跳过")
            return False
        self._commands[cmd.name] = cmd
        logger.bind(event="plugin_command_registered", name=cmd.name, plugin=cmd.plugin_id).info("插件命令已注册")
        return True

    def unregister_command(self, name: str):
        """注销插件命令。"""
        self._commands.pop(name, None)

    def get_plugin_commands(self) -> list[dict]:
        """获取所有插件注册的命令。"""
        return [
            {"name": c.name, "description": c.description, "plugin_id": c.plugin_id}
            for c in self._commands.values()
        ]

    # ---- 工具渲染插件 ----

    def register_tool_render(self, render: ToolRenderPluginDef) -> bool:
        """注册工具渲染插件。"""
        self._tool_renders[render.tool_name] = render
        logger.bind(event="tool_render_registered", tool=render.tool_name, plugin=render.plugin_id).info("工具渲染已注册")
        return True

    def get_tool_render(self, tool_name: str) -> Optional[ToolRenderPluginDef]:
        """获取指定工具的渲染器。"""
        return self._tool_renders.get(tool_name)

    # ---- 组件行为覆盖 ----

    def register_component_override(self, override: ComponentOverrideDef) -> bool:
        """注册组件行为覆盖。"""
        key = f"{override.component_path}:{override.plugin_id}"
        self._component_overrides[key] = override
        logger.bind(event="component_override_registered", component=override.component_path).info("组件行为覆盖已注册")
        return True

    def get_component_overrides(self, component_path: str) -> list[ComponentOverrideDef]:
        """获取指定组件的所有覆盖。"""
        return [
            o for o in self._component_overrides.values()
            if o.component_path == component_path
        ]

    def get_stats(self) -> dict:
        """获取注册统计。"""
        return {
            "commands": len(self._commands),
            "tool_renders": len(self._tool_renders),
            "component_overrides": len(self._component_overrides),
        }


# 全局单例
_extension_registry: Optional[PluginExtensionRegistry] = None


def get_extension_registry() -> PluginExtensionRegistry:
    """获取插件扩展注册表单例。"""
    global _extension_registry
    if _extension_registry is None:
        _extension_registry = PluginExtensionRegistry()
    return _extension_registry

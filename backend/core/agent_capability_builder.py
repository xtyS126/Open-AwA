"""AIAgent 能力采集函数集合，从 core/agent.py 迁移以便独立测试与演进。

本模块包含以下 4 个纯函数 / 协程函数：
- summarize_skill_capabilities: 将技能列表收敛为模型上下文摘要
- summarize_plugin_capabilities: 收敛插件与工具元信息
- collect_mcp_capabilities: 采集 MCP 连接态信息（异步）
- collect_configured_model_capabilities: 汇总会话可见的已配置模型目录

`CapabilityAggregator` 直接接收采集函数，避免在 `AIAgent` 上保留测试专用别名。
"""

from __future__ import annotations

# 标准库
from typing import Any, Dict, List, Optional, Set

# 第三方库
from sqlalchemy.orm import Session
from loguru import logger

# 项目内部
from core.agent_helpers import build_configured_model_hint
from core.task_runtime.tool_definitions import build_task_runtime_tool_definitions


def summarize_skill_capabilities(skills: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    将技能列表收敛为适合注入模型上下文的轻量摘要，避免把统计和配置细节全部暴露给提示词。
    """
    summarized_skills: List[Dict[str, Any]] = []
    for skill in skills:
        if not isinstance(skill, dict):
            continue
        if not skill.get("enabled"):
            continue

        summarized_skills.append({
            "name": skill.get("name", ""),
            "description": skill.get("description", ""),
        })

    return summarized_skills


def summarize_plugin_capabilities(plugins: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    仅保留插件名称、描述和工具摘要，用于让模型理解当前会话有哪些插件可被平台调度。
    """
    summarized_plugins: List[Dict[str, Any]] = []
    for plugin in plugins:
        if not isinstance(plugin, dict):
            continue

        raw_tools = plugin.get("tools") if isinstance(plugin.get("tools"), list) else []
        summarized_tools = []
        for tool in raw_tools:
            if not isinstance(tool, dict):
                continue
            summarized_tools.append({
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "method": tool.get("method", ""),
                "parameters": tool.get("parameters"),
                "default_params": tool.get("default_params"),
            })

        summarized_plugins.append({
            "name": plugin.get("name", ""),
            "description": plugin.get("description", ""),
            "loaded": bool(plugin.get("loaded", False)),
            "tools": summarized_tools,
        })

    return summarized_plugins


async def collect_mcp_capabilities(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    采集 MCP 连接态信息，用于提示模型平台是否已接入 MCP Server 以及当前有哪些已连接工具。
    这里只描述能力边界，不直接触发 MCP 调用。
    """
    chat_dispatch_enabled = bool(context.get("enable_mcp_tool_dispatch", False))
    default_payload = {
        "platform_supported": True,
        "chat_dispatch_enabled": chat_dispatch_enabled,
        "connected_servers": [],
        "tools": [],
    }

    try:
        # 延迟导入避免在不启用 MCP 的部署中扩大 Agent 启动依赖。
        from mcp.manager import MCPManager
        manager = MCPManager()
        if manager is None:
            return default_payload
        servers = manager.get_all_servers()
        tools = await manager.get_all_tools()

        default_payload["connected_servers"] = [
            {
                "server_id": item.get("server_id", ""),
                "name": item.get("name", ""),
                "transport_type": item.get("transport_type", ""),
                "connected": bool(item.get("connected", False)),
                "tools_count": int(item.get("tools_count", 0) or 0),
            }
            for item in servers
            if isinstance(item, dict)
        ]
        default_payload["tools"] = [
            {
                "server_id": item.get("server_id", ""),
                "server_name": item.get("server_name", ""),
                "name": item.get("tool", {}).get("name", "") if isinstance(item.get("tool"), dict) else "",
                "description": item.get("tool", {}).get("description", "") if isinstance(item.get("tool"), dict) else "",
            }
            for item in tools
            if isinstance(item, dict)
        ]
        return default_payload
    except Exception as e:
        logger.bind(
            event="get_mcp_capabilities_error",
            module="agent",
            error_type=type(e).__name__,
        ).warning(f"获取 MCP 能力摘要失败: {e}")
        default_payload["error"] = str(e)
        return default_payload


def collect_configured_model_capabilities(
    context: Dict[str, Any],
    db_session: Optional[Session],
) -> Dict[str, Any]:
    """
    汇总当前会话可见的已配置模型目录，供主 Agent 为子代理选择模型时参考。
    """
    default_payload = {
        "count": 0,
        "provider_count": 0,
        "entries": [],
        "providers": [],
        "summary": "",
    }

    cached_payload = context.get("configured_model_catalog")
    if isinstance(cached_payload, dict):
        return cached_payload

    # 优先使用 context 中的 db 会话，便于调用方按需注入；回退到构造时传入的 db_session
    db_session = context.get("db") or db_session
    if not db_session:
        return default_payload

    try:
        from billing.pricing_manager import PricingManager

        pricing_manager = PricingManager(db_session)
        configurations = pricing_manager.get_active_configurations()

        provider_models: Dict[str, List[str]] = {}
        for config in configurations:
            provider = pricing_manager.normalize_provider(getattr(config, "provider", None))
            if not provider:
                continue

            candidates: List[str] = []
            base_model = pricing_manager.normalize_model(getattr(config, "model", None))
            if base_model:
                candidates.append(base_model)

            selected_models = pricing_manager.parse_selected_models(
                getattr(config, "selected_models", None)
            )
            for candidate in selected_models:
                if candidate not in candidates:
                    candidates.append(candidate)

            if not candidates:
                continue

            bucket = provider_models.setdefault(provider, [])
            for candidate in candidates:
                if candidate not in bucket:
                    bucket.append(candidate)

        entries: List[Dict[str, str]] = []
        providers: List[Dict[str, Any]] = []
        for provider, models in provider_models.items():
            providers.append({"provider": provider, "models": list(models)})
            for model_name in models:
                entries.append(
                    {
                        "provider": provider,
                        "model": model_name,
                        "label": f"{provider}:{model_name}",
                    }
                )

        summary_labels = [entry["label"] for entry in entries[:12]]
        summary = "、".join(summary_labels)
        if len(entries) > len(summary_labels) and summary:
            summary = f"{summary} 等"

        payload = {
            "count": len(entries),
            "provider_count": len(providers),
            "entries": entries,
            "providers": providers,
            "summary": summary,
        }
        context["configured_model_catalog"] = payload
        return payload
    except Exception as e:
        logger.bind(
            event="get_configured_model_capabilities_error",
            module="agent",
            error_type=type(e).__name__,
        ).warning(f"获取已配置模型目录失败: {e}")
        return default_payload


def build_native_tools(capabilities: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把插件、MCP、内置和任务运行时工具汇总为原生工具定义。"""
    tools: List[Dict[str, Any]] = []
    seen_names: Set[str] = set()
    _append_plugin_tools(capabilities, tools, seen_names)
    _append_mcp_tools(capabilities, tools, seen_names)
    _append_builtin_tools(tools, seen_names)
    _append_task_runtime_tools(capabilities, tools, seen_names)
    if tools:
        logger.bind(
            event="native_tools_built",
            module="agent_capability_builder",
            tool_count=len(tools),
        ).debug(f"已构建 {len(tools)} 个原生工具定义")
    return tools


def _append_plugin_tools(
    capabilities: Dict[str, Any],
    tools: List[Dict[str, Any]],
    seen_names: Set[str],
) -> None:
    """追加插件工具定义。"""
    plugins = capabilities.get("plugins")
    for plugin in plugins if isinstance(plugins, list) else []:
        if not isinstance(plugin, dict):
            continue
        plugin_name = str(plugin.get("name", "")).strip()
        plugin_tools = plugin.get("tools")
        if not plugin_name or not isinstance(plugin_tools, list):
            continue
        for tool_definition in plugin_tools:
            if not isinstance(tool_definition, dict):
                continue
            tool_name = str(tool_definition.get("name", "")).strip()
            function_name = f"plugin_{plugin_name}__{tool_name}"
            if not tool_name or function_name in seen_names:
                continue
            seen_names.add(function_name)
            parameters = tool_definition.get("parameters")
            if not isinstance(parameters, dict) or not parameters:
                parameters = {"type": "object", "properties": {}}
            tools.append({
                "type": "function",
                "function": {
                    "name": function_name,
                    "description": str(tool_definition.get("description", "")),
                    "parameters": parameters,
                },
            })


def _append_mcp_tools(
    capabilities: Dict[str, Any],
    tools: List[Dict[str, Any]],
    seen_names: Set[str],
) -> None:
    """追加已启用聊天分发的 MCP 工具定义。"""
    mcp = capabilities.get("mcp")
    if not isinstance(mcp, dict) or not mcp.get("chat_dispatch_enabled", False):
        return
    mcp_tools = mcp.get("tools")
    for tool_definition in mcp_tools if isinstance(mcp_tools, list) else []:
        if not isinstance(tool_definition, dict):
            continue
        server_name = str(
            tool_definition.get("server_name", tool_definition.get("server_id", ""))
        ).strip()
        tool_name = str(tool_definition.get("name", "")).strip()
        function_name = f"mcp_{server_name}__{tool_name}"
        if not server_name or not tool_name or function_name in seen_names:
            continue
        seen_names.add(function_name)
        parameters = tool_definition.get("parameters")
        if not isinstance(parameters, dict) or not parameters:
            parameters = {"type": "object", "properties": {}}
        tools.append({
            "type": "function",
            "function": {
                "name": function_name,
                "description": str(tool_definition.get("description", "")),
                "parameters": parameters,
            },
        })


def _append_builtin_tools(
    tools: List[Dict[str, Any]],
    seen_names: Set[str],
) -> None:
    """追加内置工具；可选运行时不可用时保持降级。"""
    try:
        from core.builtin_tools.manager import builtin_tool_manager

        for tool_definition in builtin_tool_manager.get_tool_definitions():
            function_name = tool_definition.get("function", {}).get("name", "")
            if function_name and function_name not in seen_names:
                seen_names.add(function_name)
                tools.append(tool_definition)
    except Exception:
        logger.bind(
            module="agent_capability_builder",
            event="builtin_tools_load_error",
        ).warning("加载内置工具定义失败，跳过内置工具")


def _append_task_runtime_tools(
    capabilities: Dict[str, Any],
    tools: List[Dict[str, Any]],
    seen_names: Set[str],
) -> None:
    """追加任务运行时工具；可选运行时不可用时保持降级。"""
    try:
        from core.task_runtime.definitions import list_agent_types

        list_agent_types()
        model_hint = build_configured_model_hint(capabilities)
        for tool_definition in build_task_runtime_tool_definitions(model_hint):
            function_name = tool_definition.get("function", {}).get("name", "")
            if function_name and function_name not in seen_names:
                seen_names.add(function_name)
                tools.append(tool_definition)
    except Exception:
        logger.bind(
            module="agent_capability_builder",
            event="task_tools_load_error",
        ).warning("加载任务运行时工具定义失败，跳过任务工具")

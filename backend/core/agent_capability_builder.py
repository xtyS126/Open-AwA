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
from core.tool_factory import TOOL_DEFAULTS


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
        from mcp_integration.manager import MCPManager
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
        mcp_tool_entries: List[Dict[str, Any]] = []
        for item in tools:
            if not isinstance(item, dict):
                continue
            tool_payload = item.get("tool") if isinstance(item.get("tool"), dict) else {}
            # MCPTool.model_dump() 默认输出字段名 input_schema；兼容别名 inputSchema 的透传
            input_schema = tool_payload.get("input_schema") or tool_payload.get("inputSchema")
            mcp_tool_entries.append({
                "server_id": item.get("server_id", ""),
                "server_name": item.get("server_name", ""),
                "name": tool_payload.get("name", ""),
                "description": tool_payload.get("description", ""),
                "input_schema": input_schema if isinstance(input_schema, dict) else None,
                # 透传 MCP 工具的并发属性（来自 annotations 映射，失败关闭），
                # 供并发执行器判定 MCP 工具是否可并发执行。
                "is_read_only": bool(tool_payload.get("is_read_only", False)),
                "is_destructive": bool(tool_payload.get("is_destructive", False)),
                "is_concurrency_safe": bool(tool_payload.get("is_concurrency_safe", False)),
            })
        default_payload["tools"] = mcp_tool_entries
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
        # 生图模型目录：仅用于图像生成（SD / GPT-Image / Qwen-Image 系列），不参与聊天模型候选
        image_entries: List[Dict[str, Any]] = []
        for config in configurations:
            provider = pricing_manager.normalize_provider(getattr(config, "provider", None))
            if not provider:
                continue

            # 生图模型：单独收集并携带用途/限制描述，供 AI 生图时准确选择模型
            if getattr(config, "is_image_generation", False):
                base_model = pricing_manager.normalize_model(getattr(config, "model", None))
                if base_model:
                    image_entries.append(
                        {
                            "provider": provider,
                            "model": base_model,
                            "label": f"{provider}:{base_model}",
                            "is_image_generation": True,
                            "usage": getattr(config, "image_generation_usage", None) or "",
                        }
                    )
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

        image_summary = "、".join(entry["label"] for entry in image_entries[:12])
        if len(image_entries) > 12 and image_summary:
            image_summary = f"{image_summary} 等"

        payload = {
            "count": len(entries),
            "provider_count": len(providers),
            "entries": entries,
            "providers": providers,
            "summary": summary,
            "image_entries": image_entries,
            "image_summary": image_summary,
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


def _concurrency_defaults() -> Dict[str, Any]:
    """返回失败关闭的并发属性默认值（与 TOOL_DEFAULTS 对齐）。"""
    return {
        "is_read_only": bool(TOOL_DEFAULTS["is_read_only"]),
        "is_destructive": bool(TOOL_DEFAULTS["is_destructive"]),
        "is_concurrency_safe": bool(TOOL_DEFAULTS["is_concurrency_safe"]),
    }


def build_dynamic_tool_concurrency_map(
    capabilities: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """
    构建 plugin/MCP/task 动态工具的并发属性映射（键为工具全限定名）。

    这三类工具以原生 function 定义注入、经策略注册表执行，绕开了 ToolDefinition，
    并发执行器无法从 ToolRegistry 查到其并发属性。本映射提供明确来源：
    - plugin / task 工具：失败关闭默认值（is_concurrency_safe=False 等）
    - MCP 工具：来自 annotations 映射（readOnlyHint/destructiveHint），缺失时失败关闭兜底

    Returns:
        {tool_name: {is_read_only, is_destructive, is_concurrency_safe}} 映射
    """
    concurrency_map: Dict[str, Dict[str, Any]] = {}

    # 插件工具：失败关闭默认值
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
            if not tool_name:
                continue
            concurrency_map[f"plugin_{plugin_name}__{tool_name}"] = _concurrency_defaults()

    # MCP 工具：annotations 映射（失败关闭兜底）
    mcp = capabilities.get("mcp")
    if isinstance(mcp, dict):
        mcp_tools = mcp.get("tools")
        for tool_definition in mcp_tools if isinstance(mcp_tools, list) else []:
            if not isinstance(tool_definition, dict):
                continue
            server_id = str(tool_definition.get("server_id", "")).strip()
            tool_name = str(tool_definition.get("name", "")).strip()
            if not server_id or not tool_name:
                continue
            concurrency_map[f"mcp__{server_id}__{tool_name}"] = {
                "is_read_only": bool(tool_definition.get("is_read_only", False)),
                "is_destructive": bool(tool_definition.get("is_destructive", False)),
                "is_concurrency_safe": bool(tool_definition.get("is_concurrency_safe", False)),
            }

    # 任务运行时工具：失败关闭默认值
    from core.task_runtime.definitions import list_agent_types

    list_agent_types()
    model_hint = build_configured_model_hint(capabilities)
    for tool_definition in build_task_runtime_tool_definitions(model_hint):
        function_name = tool_definition.get("function", {}).get("name", "")
        if function_name:
            concurrency_map[function_name] = _concurrency_defaults()

    return concurrency_map


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
    """追加已启用聊天分发的 MCP 工具定义。

    工具函数名统一使用三段式 mcp__<server_id>__<tool_name>：
    - 服务段使用 server_id（与 MCPManager._clients / call_tool 的键一致），
      保证执行回调 MCPToolStrategy.execute 解析出的标识能命中客户端连接；
    - 显示用 server_name 保留在 function 的 description 中，便于模型识别具体服务。
    """
    mcp = capabilities.get("mcp")
    if not isinstance(mcp, dict) or not mcp.get("chat_dispatch_enabled", False):
        return
    mcp_tools = mcp.get("tools")
    for tool_definition in mcp_tools if isinstance(mcp_tools, list) else []:
        if not isinstance(tool_definition, dict):
            continue
        server_id = str(tool_definition.get("server_id", "")).strip()
        server_name = str(tool_definition.get("server_name", "")).strip()
        tool_name = str(tool_definition.get("name", "")).strip()
        function_name = f"mcp__{server_id}__{tool_name}"
        if not server_id or not tool_name or function_name in seen_names:
            continue
        seen_names.add(function_name)
        # 透传 MCP 工具的 inputSchema 作为 LLM 可见的参数定义；
        # 兼容旧调用方直接在 capabilities 中放置 parameters 键
        parameters = tool_definition.get("input_schema")
        if not isinstance(parameters, dict) or not parameters:
            parameters = tool_definition.get("parameters")
        if not isinstance(parameters, dict) or not parameters:
            parameters = {"type": "object", "properties": {}}
        description = str(tool_definition.get("description", "")).strip()
        if server_name and server_name != server_id:
            # 服务段是 UUID，此处保留显示名提升可读性
            description = (
                f"[{server_name}] {description}".strip()
                if description
                else f"MCP Server「{server_name}」提供的工具 {tool_name}"
            )
        tools.append({
            "type": "function",
            "function": {
                "name": function_name,
                "description": description,
                "parameters": parameters,
            },
        })


def _append_builtin_tools(
    tools: List[Dict[str, Any]],
    seen_names: Set[str],
) -> None:
    """追加内置工具；加载失败时直接抛错，禁止静默剔除工具。

    单一事实来源：优先从 ToolRegistry 派生 LLM 可见定义（含 enabled/permission 过滤），
    注册表未填充（启动早期）时回退到 builtin_tool_manager 静态列表以保持兼容。
    """
    from core.tool_registry import tool_registry

    # 注册表已接线（startup 调用 register_builtin_tools 后非空）时统一从注册表派生
    definitions = tool_registry.get_definitions_for_llm()
    if definitions:
        for tool_definition in definitions:
            function_name = tool_definition.get("function", {}).get("name", "")
            if function_name and function_name not in seen_names:
                seen_names.add(function_name)
                tools.append(tool_definition)
        return

    # 启动早期注册表未填充：回退静态列表（与旧行为一致）
    from core.builtin_tools.manager import builtin_tool_manager

    for tool_definition in builtin_tool_manager.get_tool_definitions():
        function_name = tool_definition.get("function", {}).get("name", "")
        if function_name and function_name not in seen_names:
            seen_names.add(function_name)
            tools.append(tool_definition)


def _append_task_runtime_tools(
    capabilities: Dict[str, Any],
    tools: List[Dict[str, Any]],
    seen_names: Set[str],
) -> None:
    """追加任务运行时工具；加载失败时直接抛错，禁止静默剔除工具。"""
    from core.task_runtime.definitions import list_agent_types

    list_agent_types()
    model_hint = build_configured_model_hint(capabilities)
    for tool_definition in build_task_runtime_tool_definitions(model_hint):
        function_name = tool_definition.get("function", {}).get("name", "")
        if function_name and function_name not in seen_names:
            seen_names.add(function_name)
            tools.append(tool_definition)

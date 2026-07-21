"""AIAgent 能力采集函数集合，从 core/agent.py 迁移以便独立测试与演进。

本模块包含以下 4 个纯函数 / 协程函数：
- summarize_skill_capabilities: 将技能列表收敛为模型上下文摘要
- summarize_plugin_capabilities: 收敛插件与工具元信息
- collect_mcp_capabilities: 采集 MCP 连接态信息（异步）
- collect_configured_model_capabilities: 汇总会话可见的已配置模型目录

core/agent.py 中对应的方法保留为薄包装 / 类级别名，仅用于兼容既有测试
AIAgent._xxx(...) 调用，待 fix-test-implementation-coupling spec 落地后移除。
"""

from __future__ import annotations

# 标准库
from typing import Any, Dict, List, Optional

# 第三方库
from sqlalchemy.orm import Session
from loguru import logger

# 项目内部
# 注意：MCPManager 在 collect_mcp_capabilities 函数体内延迟导入，
# 通过 core.agent 模块引用，确保测试 monkeypatch.setattr(agent_module, "MCPManager", ...) 生效


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
        # 延迟通过 core.agent 模块引用 MCPManager，确保测试 monkeypatch.setattr(agent_module, "MCPManager", ...) 生效
        # 详见 extract-agent-capability-builder spec 的 wrapper 委托链问题
        import core.agent as agent_module
        manager = agent_module.MCPManager()
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

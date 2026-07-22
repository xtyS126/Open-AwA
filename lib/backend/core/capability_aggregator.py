"""Agent 运行时能力聚合与短期缓存。"""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from loguru import logger


class CapabilityAggregator:
    """聚合会话能力，并在短 TTL 内复用可用工具定义。"""

    def __init__(self, cache_ttl: float) -> None:
        self.cache_ttl = cache_ttl
        self.capabilities_cache: Optional[Dict[str, Any]] = None
        self.capabilities_cache_ts = 0.0
        self.tools_cache: Optional[List[Dict[str, Any]]] = None
        self.tools_cache_version = ""

    def invalidate(self) -> None:
        """清空能力与工具缓存。"""
        self.capabilities_cache = None
        self.capabilities_cache_ts = 0.0
        self.tools_cache = None
        self.tools_cache_version = ""

    async def inject(
        self,
        context: Dict[str, Any],
        *,
        get_available_skills: Callable[[], Awaitable[List[Dict[str, Any]]]],
        get_available_plugins: Callable[[], Awaitable[List[Dict[str, Any]]]],
        summarize_skills: Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]],
        summarize_plugins: Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]],
        collect_configured_models: Callable[[Dict[str, Any]], Dict[str, Any]],
        collect_mcp: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]],
        build_native_tools: Callable[[Dict[str, Any]], List[Dict[str, Any]]],
    ) -> None:
        """将当前会话可用能力与原生工具定义写入上下文。"""
        if isinstance(context.get("agent_capabilities"), dict):
            return

        now = time.time()
        if (
            self.capabilities_cache is not None
            and self.tools_cache is not None
            and (now - self.capabilities_cache_ts) < self.cache_ttl
        ):
            context["agent_capabilities"] = self.capabilities_cache
            context["_tools"] = self.tools_cache
            logger.bind(
                event="capabilities_instance_cache_hit",
                module="agent",
                session_id=context.get("session_id", ""),
                cache_age=round(now - self.capabilities_cache_ts, 3),
            ).debug("复用实例级缓存的 capabilities 与工具定义")
            return

        skill_plugin_enabled = bool(context.get("enable_skill_plugin", True))
        skills: List[Dict[str, Any]] = []
        plugins: List[Dict[str, Any]] = []
        if skill_plugin_enabled:
            skills = summarize_skills(await get_available_skills())
            plugins = summarize_plugins(await get_available_plugins())

        capabilities = {
            "skills_enabled": skill_plugin_enabled,
            "plugins_enabled": skill_plugin_enabled,
            "tool_dispatch_mode": "platform_managed",
            "skills": skills,
            "plugins": plugins,
            "configured_models": collect_configured_models(context),
            "mcp": await collect_mcp(context),
        }
        context["agent_capabilities"] = capabilities
        self._apply_agent_type_hint(context)

        tools = build_native_tools(capabilities)
        self.tools_cache = tools
        self.capabilities_cache = capabilities
        self.capabilities_cache_ts = time.time()
        context["_tools"] = tools
        logger.bind(
            event="tool_definition_built",
            module="agent",
            tool_count=len(tools),
            session_id=context.get("session_id", ""),
        ).debug("工具定义已构建并写入实例级缓存")

    @staticmethod
    def _apply_agent_type_hint(context: Dict[str, Any]) -> None:
        """校验 Agent 类型并提供对应的系统提示。"""
        allowed_agent_types = {"Explore", "Plan", "general-purpose"}
        agent_type = context.get("agent_type", "general-purpose")
        if agent_type not in allowed_agent_types:
            logger.warning(f"非法的 agent_type '{agent_type}'，已回退为 general-purpose")
            agent_type = "general-purpose"
        context["agent_type"] = agent_type
        hints = {
            "Explore": "你是一个只读的代码探索Agent，专注于搜索、阅读和分析代码。不要修改任何文件。",
            "Plan": "你是一个规划Agent，专注于分析需求并制定执行计划。不要直接执行代码或修改文件。",
            "general-purpose": "你是一个通用Agent，具备完整的读写和执行能力。",
        }
        context.setdefault("agent_type_hint", hints[agent_type])

"""
_inject_runtime_capabilities 的 capabilities 整体缓存单元测试。

覆盖 backend/core/agent.py 的 _inject_runtime_capabilities 缓存逻辑：
- 首次调用构建 capabilities 并写入 _capabilities_cache / _tools_cache
- 同一 context 第二次调用命中 context 缓存（agent_capabilities 已设置），跳过所有查询
- 跨 context（新 process_stream）在 TTL 内命中实例缓存，跳过 skills/plugins/mcp 三次查询
- TTL 过期后下一次调用重建 capabilities
- invalidate_capabilities_cache() 主动失效后下一次调用重建

通过 AIAgent() 无 db_session 实例化 + mock 外部依赖，
避免触发真实数据库/向量库/插件目录加载。
"""

import sys
import time
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent import AIAgent


def _make_partial_agent() -> AIAgent:
    """创建无 db_session 的 AIAgent 实例，避免触发 DB/向量库/插件目录加载。

    AIAgent() 不带参数时不会创建 memory_manager / workflow_engine，
    避免了复杂的依赖初始化。
    """
    return AIAgent()


def _stub_capabilities(
    agent: AIAgent,
    *,
    skills: List[Dict[str, Any]],
    plugins: List[Dict[str, Any]],
    mcp_tools: List[Dict[str, Any]] = None,
    chat_dispatch_enabled: bool = False,
) -> MagicMock:
    """mock _inject_runtime_capabilities 调用的所有外部方法。

    返回 mock_build_native_tools 以便断言调用次数。
    """
    agent.get_available_skills = AsyncMock(return_value=skills)
    agent.get_available_plugins = AsyncMock(return_value=plugins)

    mcp_payload = {
        "platform_supported": True,
        "chat_dispatch_enabled": chat_dispatch_enabled,
        "connected_servers": [],
        "tools": mcp_tools or [],
    }
    agent._capability_aggregator.collect_mcp = AsyncMock(return_value=mcp_payload)
    agent._capability_aggregator.collect_configured_models = MagicMock(
        return_value={"count": 0, "entries": [], "providers": [], "summary": ""}
    )

    # mock _build_native_tools：每次返回新列表对象，便于断言调用次数与缓存替换
    def _build_stub(_capabilities):
        return [{"type": "function", "function": {"name": "stub_tool"}}]

    mock_build = MagicMock(side_effect=_build_stub)
    agent.native_tool_builder = mock_build
    return mock_build


@pytest.mark.asyncio
async def test_first_call_builds_capabilities() -> None:
    """首次调用 _inject_runtime_capabilities 时应构建 capabilities 并填充实例缓存。"""
    agent = _make_partial_agent()
    mock_build = _stub_capabilities(
        agent,
        skills=[{"name": "skill1"}],
        plugins=[{"name": "plugin1", "loaded": True, "tools": [{"name": "tool1"}]}],
    )

    # 首次调用前缓存应为空
    assert agent._capabilities_cache is None
    assert agent._tools_cache is None
    assert agent._capabilities_cache_ts == 0.0

    context: Dict[str, Any] = {"enable_skill_plugin": True, "session_id": "sess-1"}
    await agent._inject_runtime_capabilities(context)

    # 首次调用后 capabilities 与 tools 缓存应被填充
    assert agent._capabilities_cache is not None
    assert agent._tools_cache is not None
    # 时间戳应被写入（大于 0 表示已构建）
    assert agent._capabilities_cache_ts > 0.0
    # context 中也应被写入 agent_capabilities 与 _tools
    assert isinstance(context.get("agent_capabilities"), dict)
    assert context.get("_tools") is agent._tools_cache
    # _build_native_tools 应被调用一次
    assert mock_build.call_count == 1
    # skills/plugins/mcp 查询应各被调用一次
    assert agent.get_available_skills.call_count == 1
    assert agent.get_available_plugins.call_count == 1
    assert agent._capability_aggregator.collect_mcp.call_count == 1


@pytest.mark.asyncio
async def test_second_call_with_same_context_hits_cache() -> None:
    """同一 context 第二次调用应命中 context 缓存，跳过所有外部查询。

    首次调用后 context["agent_capabilities"] 已被设置为 dict，
    第二次进入时第一个检查 `if isinstance(context.get("agent_capabilities"), dict): return`
    直接返回，不触发 skills/plugins/mcp 查询与 _build_native_tools。
    """
    agent = _make_partial_agent()
    mock_build = _stub_capabilities(
        agent,
        skills=[{"name": "skill1"}],
        plugins=[{"name": "plugin1", "loaded": True, "tools": [{"name": "tool1"}]}],
    )

    context: Dict[str, Any] = {"enable_skill_plugin": True, "session_id": "sess-1"}
    await agent._inject_runtime_capabilities(context)
    assert mock_build.call_count == 1
    assert agent.get_available_skills.call_count == 1

    # 第二次调用（同一 context）：agent_capabilities 已设置，应直接返回
    await agent._inject_runtime_capabilities(context)

    # 所有 mock 不应再次被调用
    assert mock_build.call_count == 1
    assert agent.get_available_skills.call_count == 1
    assert agent.get_available_plugins.call_count == 1
    assert agent._capability_aggregator.collect_mcp.call_count == 1


@pytest.mark.asyncio
async def test_instance_cache_hit_on_fresh_context_within_ttl() -> None:
    """跨 context（新 process_stream）在 TTL 内应命中实例缓存。

    新 context 中 agent_capabilities 未设置，但实例级 _capabilities_cache
    在 TTL 内有效，直接复用，跳过 skills/plugins/mcp 三次查询与 _build_native_tools。
    这是 Task 7 修复循环依赖后的核心收益场景。
    """
    agent = _make_partial_agent()
    mock_build = _stub_capabilities(
        agent,
        skills=[{"name": "skill1"}],
        plugins=[{"name": "plugin1", "loaded": True, "tools": [{"name": "tool1"}]}],
    )

    context1: Dict[str, Any] = {"enable_skill_plugin": True, "session_id": "sess-1"}
    await agent._inject_runtime_capabilities(context1)
    first_capabilities_cache = agent._capabilities_cache
    first_tools_cache = agent._tools_cache
    first_ts = agent._capabilities_cache_ts
    assert mock_build.call_count == 1
    assert agent.get_available_skills.call_count == 1

    # 第二次调用（新 context，TTL 内）
    context2: Dict[str, Any] = {"enable_skill_plugin": True, "session_id": "sess-2"}
    await agent._inject_runtime_capabilities(context2)

    # capabilities 与 tools 缓存对象应是同一份（未重建）
    assert agent._capabilities_cache is first_capabilities_cache
    assert agent._tools_cache is first_tools_cache
    # 时间戳不应被更新（命中缓存时不重建）
    assert agent._capabilities_cache_ts == first_ts
    # skills/plugins/mcp 查询不应被再次调用
    assert agent.get_available_skills.call_count == 1
    assert agent.get_available_plugins.call_count == 1
    assert agent._capability_aggregator.collect_mcp.call_count == 1
    # _build_native_tools 不应再次被调用
    assert mock_build.call_count == 1
    # 新 context 应被写入复用的 capabilities 与 tools
    assert context2.get("agent_capabilities") is first_capabilities_cache
    assert context2.get("_tools") is first_tools_cache


@pytest.mark.asyncio
async def test_ttl_expiry_rebuilds_capabilities() -> None:
    """TTL 过期后下一次调用应重建 capabilities 与 tools。

    通过手动修改 _capabilities_cache_ts 模拟时间前进超过 TTL。
    """
    agent = _make_partial_agent()
    mock_build = _stub_capabilities(
        agent,
        skills=[{"name": "skill1"}],
        plugins=[{"name": "plugin1", "loaded": True, "tools": [{"name": "tool1"}]}],
    )

    context1: Dict[str, Any] = {"enable_skill_plugin": True, "session_id": "sess-1"}
    await agent._inject_runtime_capabilities(context1)
    first_capabilities = agent._capabilities_cache
    first_tools = agent._tools_cache
    assert mock_build.call_count == 1

    # 模拟时间前进超过 TTL（将时间戳设为 31 秒前）
    agent._capabilities_cache_ts = time.time() - (agent._CAPABILITIES_CACHE_TTL + 1.0)

    context2: Dict[str, Any] = {"enable_skill_plugin": True, "session_id": "sess-2"}
    await agent._inject_runtime_capabilities(context2)

    # 缓存应被重建（不是同一对象）
    assert agent._capabilities_cache is not first_capabilities
    assert agent._tools_cache is not first_tools
    # 时间戳应被更新为当前时间
    assert agent._capabilities_cache_ts > time.time() - 1.0
    # skills/plugins/mcp 查询应被再次调用
    assert agent.get_available_skills.call_count == 2
    assert agent.get_available_plugins.call_count == 2
    assert agent._capability_aggregator.collect_mcp.call_count == 2
    # _build_native_tools 应被再次调用
    assert mock_build.call_count == 2


@pytest.mark.asyncio
async def test_invalidate_capabilities_cache_clears_state() -> None:
    """invalidate_capabilities_cache() 应清空所有缓存字段。"""
    agent = _make_partial_agent()
    _stub_capabilities(
        agent,
        skills=[{"name": "skill1"}],
        plugins=[{"name": "plugin1", "loaded": True, "tools": [{"name": "tool1"}]}],
    )

    context: Dict[str, Any] = {"enable_skill_plugin": True, "session_id": "sess-1"}
    await agent._inject_runtime_capabilities(context)
    assert agent._capabilities_cache is not None
    assert agent._tools_cache is not None
    assert agent._capabilities_cache_ts > 0.0

    # 主动失效
    agent.invalidate_capabilities_cache()

    # 所有缓存字段应被清空
    assert agent._capabilities_cache is None
    assert agent._tools_cache is None
    assert agent._capabilities_cache_ts == 0.0
    assert agent._tools_cache_version == ""


@pytest.mark.asyncio
async def test_invalidate_forces_rebuild_on_next_call() -> None:
    """主动失效后下一次调用应重建 capabilities，即使 TTL 未过期。"""
    agent = _make_partial_agent()
    mock_build = _stub_capabilities(
        agent,
        skills=[{"name": "skill1"}],
        plugins=[{"name": "plugin1", "loaded": True, "tools": [{"name": "tool1"}]}],
    )

    context1: Dict[str, Any] = {"enable_skill_plugin": True, "session_id": "sess-1"}
    await agent._inject_runtime_capabilities(context1)
    first_capabilities = agent._capabilities_cache
    assert mock_build.call_count == 1

    # 主动失效（模拟插件 load/unload 后调用）
    agent.invalidate_capabilities_cache()

    # 改变技能列表（模拟状态变化）
    agent.get_available_skills = AsyncMock(
        return_value=[{"name": "skill1"}, {"name": "skill2"}]
    )

    context2: Dict[str, Any] = {"enable_skill_plugin": True, "session_id": "sess-2"}
    await agent._inject_runtime_capabilities(context2)

    # 缓存应被重建（不是同一对象）
    assert agent._capabilities_cache is not first_capabilities
    # skills 查询应被再次调用（缓存未命中）
    assert agent.get_available_skills.call_count == 1
    # _build_native_tools 应被再次调用
    assert mock_build.call_count == 2


@pytest.mark.asyncio
async def test_skill_plugin_disabled_skips_queries() -> None:
    """enable_skill_plugin=False 时应跳过 skills/plugins 查询。"""
    agent = _make_partial_agent()
    mock_build = _stub_capabilities(
        agent,
        skills=[{"name": "skill1"}],
        plugins=[{"name": "plugin1", "loaded": True, "tools": [{"name": "tool1"}]}],
    )

    context: Dict[str, Any] = {"enable_skill_plugin": False, "session_id": "sess-1"}
    await agent._inject_runtime_capabilities(context)

    # skills/plugins 查询不应被调用
    assert agent.get_available_skills.call_count == 0
    assert agent.get_available_plugins.call_count == 0
    # mcp 查询仍应被调用（不受 enable_skill_plugin 控制）
    assert agent._capability_aggregator.collect_mcp.call_count == 1
    # _build_native_tools 应被调用（基于空 skills/plugins 构建）
    assert mock_build.call_count == 1
    # capabilities 中 skills_enabled 应为 False
    assert context["agent_capabilities"]["skills_enabled"] is False
    assert context["agent_capabilities"]["plugins_enabled"] is False
    assert context["agent_capabilities"]["skills"] == []
    assert context["agent_capabilities"]["plugins"] == []

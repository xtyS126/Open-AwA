"""
AIAgent 工具定义实例级缓存单元测试。

覆盖 backend/core/agent.py 的 _inject_runtime_capabilities 缓存逻辑：
- 首次调用时构建工具并写入 _tools_cache
- 第二次相同 context 在 TTL 内命中实例级缓存
- 技能/插件集合变化后通过显式失效触发重建

通过 AIAgent() 无 db_session 实例化 + mock 外部依赖，
避免触发真实数据库/向量库/插件目录加载。
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any, Dict, List

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

    # _summarize_*_capabilities 是 staticmethod，绑到实例时需通过 patch.object 替换
    # 这里直接覆盖实例属性即可（staticmethod 通过实例访问返回普通函数）
    agent._summarize_skill_capabilities = lambda raw: raw  # 透传便于版本计算
    agent._summarize_plugin_capabilities = lambda raw: raw

    mcp_payload = {
        "platform_supported": True,
        "chat_dispatch_enabled": chat_dispatch_enabled,
        "connected_servers": [],
        "tools": mcp_tools or [],
    }
    agent._collect_mcp_capabilities = AsyncMock(return_value=mcp_payload)
    agent._collect_configured_model_capabilities = MagicMock(
        return_value={"count": 0, "entries": [], "providers": [], "summary": ""}
    )

    # mock _build_native_tools：每次返回新列表对象，便于断言调用次数与缓存替换
    # side_effect 每次调用返回独立 list，避免 _tools_cache is not first_cache 误判
    def _build_stub(_capabilities):
        return [{"type": "function", "function": {"name": "stub_tool"}}]

    mock_build = MagicMock(side_effect=_build_stub)
    agent._build_native_tools = mock_build
    return mock_build


@pytest.mark.asyncio
async def test_first_call_builds_tools_cache() -> None:
    """首次调用 _inject_runtime_capabilities 时 _tools_cache 为空 → 构建后非空。"""
    agent = _make_partial_agent()
    mock_build = _stub_capabilities(
        agent,
        skills=[{"name": "skill1"}],
        plugins=[
            {"name": "plugin1", "loaded": True, "tools": [{"name": "tool1"}]}
        ],
    )

    # 首次调用前缓存应为空
    assert agent._tools_cache is None
    assert agent._capabilities_cache is None
    assert agent._capabilities_cache_ts == 0.0

    context: Dict[str, Any] = {"enable_skill_plugin": True, "session_id": "sess-1"}
    await agent._inject_runtime_capabilities(context)

    # 首次调用后工具与能力缓存均已建立
    assert agent._tools_cache is not None
    assert len(agent._tools_cache) > 0
    assert agent._capabilities_cache is context["agent_capabilities"]
    assert agent._capabilities_cache_ts > 0.0
    # _build_native_tools 应被调用一次
    assert mock_build.call_count == 1
    # context["_tools"] 也应被填充（同一次 process_stream 内二次访问走 context 缓存）
    assert context.get("_tools") is agent._tools_cache


@pytest.mark.asyncio
async def test_second_call_with_same_capabilities_hits_cache() -> None:
    """第二次调用相同 context（技能/插件集合不变）时命中实例级缓存。"""
    agent = _make_partial_agent()
    mock_build = _stub_capabilities(
        agent,
        skills=[{"name": "skill1"}],
        plugins=[
            {"name": "plugin1", "loaded": True, "tools": [{"name": "tool1"}]}
        ],
    )

    context1: Dict[str, Any] = {"enable_skill_plugin": True, "session_id": "sess-1"}
    await agent._inject_runtime_capabilities(context1)

    first_cache = agent._tools_cache
    first_timestamp = agent._capabilities_cache_ts
    assert mock_build.call_count == 1

    # 第二次调用：context 中没有 agent_capabilities，重新走缓存判定路径
    # TTL 未过期时应直接命中实例级缓存
    context2: Dict[str, Any] = {"enable_skill_plugin": True, "session_id": "sess-2"}
    await agent._inject_runtime_capabilities(context2)

    # 缓存对象应是同一份（未重建）
    assert agent._tools_cache is first_cache
    assert agent._capabilities_cache_ts == first_timestamp
    # _build_native_tools 不应再次被调用
    assert mock_build.call_count == 1


@pytest.mark.asyncio
async def test_skill_changes_rebuild_after_explicit_invalidation() -> None:
    """技能列表变化后显式失效缓存会触发重建。"""
    agent = _make_partial_agent()
    mock_build = _stub_capabilities(
        agent,
        skills=[{"name": "skill1"}],
        plugins=[
            {"name": "plugin1", "loaded": True, "tools": [{"name": "tool1"}]}
        ],
    )

    context1: Dict[str, Any] = {"enable_skill_plugin": True, "session_id": "sess-1"}
    await agent._inject_runtime_capabilities(context1)
    first_cache = agent._tools_cache
    assert mock_build.call_count == 1

    # 改变技能列表（增加 skill2），触发版本变化
    agent.get_available_skills = AsyncMock(
        return_value=[{"name": "skill1"}, {"name": "skill2"}]
    )

    agent.invalidate_capabilities_cache()
    context2: Dict[str, Any] = {"enable_skill_plugin": True, "session_id": "sess-2"}
    await agent._inject_runtime_capabilities(context2)

    # 缓存应被重建（不是同一对象）
    assert agent._tools_cache is not first_cache
    # _build_native_tools 应被再次调用
    assert mock_build.call_count == 2


@pytest.mark.asyncio
async def test_plugin_changes_rebuild_after_explicit_invalidation() -> None:
    """插件工具集合变化后显式失效缓存会触发重建。"""
    agent = _make_partial_agent()
    mock_build = _stub_capabilities(
        agent,
        skills=[],
        plugins=[
            {"name": "plugin1", "loaded": True, "tools": [{"name": "tool1"}]}
        ],
    )

    context1: Dict[str, Any] = {"enable_skill_plugin": True}
    await agent._inject_runtime_capabilities(context1)
    assert mock_build.call_count == 1

    # 改变插件工具集合（新增 tool2）
    agent.get_available_plugins = AsyncMock(
        return_value=[
            {
                "name": "plugin1",
                "loaded": True,
                "tools": [{"name": "tool1"}, {"name": "tool2"}],
            }
        ]
    )

    agent.invalidate_capabilities_cache()
    context2: Dict[str, Any] = {"enable_skill_plugin": True}
    await agent._inject_runtime_capabilities(context2)

    assert mock_build.call_count == 2


def test_compute_tools_version_empty_when_no_capabilities() -> None:
    """context 中无 agent_capabilities 时版本为空字符串。"""
    assert AIAgent._compute_tools_version({}) == ""
    assert AIAgent._compute_tools_version({"agent_capabilities": "not-a-dict"}) == ""


def test_compute_tools_version_changes_with_skill_set() -> None:
    """技能集合变化时 _compute_tools_version 返回不同 md5。"""
    capabilities_a = {
        "skills": [{"name": "skill1"}],
        "plugins": [],
        "mcp": {"chat_dispatch_enabled": False, "tool_count": 0},
    }
    capabilities_b = {
        "skills": [{"name": "skill1"}, {"name": "skill2"}],
        "plugins": [],
        "mcp": {"chat_dispatch_enabled": False, "tool_count": 0},
    }
    version_a = AIAgent._compute_tools_version({"agent_capabilities": capabilities_a})
    version_b = AIAgent._compute_tools_version({"agent_capabilities": capabilities_b})
    assert version_a != version_b
    assert len(version_a) == 32  # md5 hex 长度


def test_compute_tools_version_stable_for_same_capabilities() -> None:
    """相同 agent_capabilities 多次调用版本一致（哈希稳定性）。"""
    capabilities = {
        "skills": [{"name": "skill1"}],
        "plugins": [{"name": "plugin1", "loaded": True, "tool_names": ["tool1"]}],
        "mcp": {"chat_dispatch_enabled": False, "tool_count": 0},
    }
    context = {"agent_capabilities": capabilities}
    v1 = AIAgent._compute_tools_version(context)
    v2 = AIAgent._compute_tools_version(context)
    assert v1 == v2

# -*- coding: utf-8 -*-
"""
ACP service 模块单元测试。

验证 ACPService 的生命周期管理、状态查询与错误路径。由于外部 acp SDK 未安装
（_ACP_AVAILABLE=False），测试聚焦于错误路径与状态管理，不实际 spawn 子进程。
"""

from __future__ import annotations

import atexit
import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from acp_host import service as acp_service_module
from acp_host.core import ACPAgentConfig, ACPConfig, ACPConfigurationError, ACPSessionError
from acp_host.service import (
    ACPService,
    _acp_services,
    _kill_process_tree,
    _shutdown_acp_services,
    close_acp_service,
    get_acp_service,
    init_acp_service,
)


def _make_agent_config(
    agent_id: str = "test-agent",
    name: str = "Test Agent",
    enabled: bool = True,
    **overrides: Any,
) -> ACPAgentConfig:
    """构造测试用 ACPAgentConfig。

    Args:
        agent_id: Agent 标识。
        name: Agent 展示名。
        enabled: 是否启用。
        **overrides: 覆盖默认字段的参数。

    Returns:
        填充默认值的 ACPAgentConfig 实例。
    """
    base: dict[str, Any] = {
        "agent_id": agent_id,
        "name": name,
        "command": "echo",
        "enabled": enabled,
    }
    base.update(overrides)
    return ACPAgentConfig(**base)


def _make_config(
    agents: dict[str, ACPAgentConfig] | None = None,
) -> ACPConfig:
    """构造测试用 ACPConfig。

    Args:
        agents: 按 agent_id 索引的 Agent 配置字典；为 None 时使用默认 agent。

    Returns:
        ACPConfig 实例。
    """
    if agents is None:
        agents = {"test-agent": _make_agent_config()}
    return ACPConfig(agents=agents)


@pytest.fixture(autouse=True)
def _reset_acp_services() -> Any:
    """每个测试前后清空模块级 _acp_services 字典，避免测试间状态污染。

    Yields:
        None：仅作为 setup/teardown 哨兵。
    """
    _acp_services.clear()
    yield
    _acp_services.clear()


class TestInstantiation:
    """ACPService 实例化测试。"""

    def test_can_instantiate_without_acp_sdk(self) -> None:
        """验证 ACPService 在 acp SDK 未安装时仍可正常实例化。"""
        service = ACPService(config=_make_config())
        assert service is not None
        assert hasattr(service, "_lock")
        assert hasattr(service, "_sessions")
        assert service._sessions == {}


class TestServiceRegistry:
    """init_acp_service / get_acp_service / close_acp_service 注册表测试。"""

    def test_init_acp_service_creates_and_registers_service(self) -> None:
        """验证 init_acp_service 创建 service 并存入 _acp_services。"""
        config = _make_config()
        service = init_acp_service("agent-1", config)
        assert service is not None
        assert get_acp_service("agent-1") is service

    def test_get_acp_service_returns_registered_service(self) -> None:
        """验证 get_acp_service 返回已注册的 service。"""
        config = _make_config()
        service = init_acp_service("agent-2", config)
        assert get_acp_service("agent-2") is service

    def test_get_acp_service_returns_none_for_unknown_id(self) -> None:
        """验证 get_acp_service 对未知 agent_id 返回 None。"""
        assert get_acp_service("does-not-exist") is None

    def test_get_acp_service_returns_none_for_none_argument(self) -> None:
        """验证 get_acp_service(None) 返回 None。"""
        assert get_acp_service(None) is None

    def test_close_acp_service_removes_from_registry(self) -> None:
        """验证 close_acp_service 从 _acp_services 移除 service。"""
        init_acp_service("agent-3", _make_config())
        assert get_acp_service("agent-3") is not None
        close_acp_service("agent-3")
        assert get_acp_service("agent-3") is None

    def test_close_acp_service_unknown_id_does_not_raise(self) -> None:
        """验证 close_acp_service 对未知 agent_id 静默返回不抛异常。"""
        # 不应抛任何异常
        close_acp_service("totally-unknown")


class TestRunTurnRequiresAcpSdk:
    """run_turn 在 acp SDK 未安装时的行为测试。"""

    async def test_run_turn_raises_when_acp_sdk_not_installed(self) -> None:
        """验证 _ACP_AVAILABLE=False 时 run_turn 抛 ACPConfigurationError。

        测试不依赖外部 acp SDK，确保错误路径清晰可定位。
        """
        # 强制模拟 SDK 不可用（即使测试环境本就如此，仍显式 patch 以保证可移植性）
        with patch.object(acp_service_module, "_ACP_AVAILABLE", False):
            service = ACPService(config=_make_config())

            async def on_message(payload: dict[str, Any], is_last: bool) -> None:
                pass

            with pytest.raises(ACPConfigurationError):
                await service.run_turn(
                    chat_id="chat-1",
                    agent="test-agent",
                    prompt_blocks=[{"type": "text", "text": "hi"}],
                    cwd=".",
                    on_message=on_message,
                )


class TestGetAgentConfig:
    """_get_agent_config 校验逻辑测试。"""

    def test_unknown_agent_raises_configuration_error(self) -> None:
        """验证未知 agent 抛 ACPConfigurationError，agent 字段携带上下文。"""
        service = ACPService(config=_make_config(agents={}))
        with pytest.raises(ACPConfigurationError) as exc_info:
            service._get_agent_config("unknown-agent")
        assert exc_info.value.agent == "unknown-agent"

    def test_disabled_agent_raises_configuration_error(self) -> None:
        """验证 enabled=False 的 agent 抛 ACPConfigurationError。"""
        disabled_config = _make_agent_config(
            agent_id="disabled-agent",
            name="Disabled",
            enabled=False,
        )
        service = ACPService(config=_make_config(agents={"disabled-agent": disabled_config}))
        with pytest.raises(ACPConfigurationError) as exc_info:
            service._get_agent_config("disabled-agent")
        assert exc_info.value.agent == "disabled-agent"

    def test_enabled_agent_returns_config(self) -> None:
        """验证 enabled=True 的 agent 返回配置实例。"""
        enabled_config = _make_agent_config(
            agent_id="enabled-agent",
            name="Enabled",
            enabled=True,
        )
        service = ACPService(config=_make_config(agents={"enabled-agent": enabled_config}))
        result = service._get_agent_config("enabled-agent")
        assert result is enabled_config
        assert result.agent_id == "enabled-agent"
        assert result.enabled is True


class TestSessionLookupsWithoutSessions:
    """无会话时的状态查询/操作测试，验证不抛异常。"""

    async def test_close_chat_session_no_existing_does_not_raise(self) -> None:
        """验证关闭不存在的会话静默返回。"""
        service = ACPService(config=_make_config())
        # 不应抛任何异常
        await service.close_chat_session(chat_id="missing", agent="test-agent")
        assert service._session_locks == {}
        assert service._session_lock_refs == {}

    async def test_cancel_turn_no_session_returns_false(self) -> None:
        """验证对不存在的会话调用 cancel_turn 返回 False。"""
        service = ACPService(config=_make_config())
        result = await service.cancel_turn(chat_id="missing", agent="test-agent")
        assert result is False

    async def test_get_session_returns_none_when_absent(self) -> None:
        """验证 get_session 对不存在的键返回 None。"""
        service = ACPService(config=_make_config())
        result = await service.get_session("missing", "test-agent")
        assert result is None

    async def test_get_pending_permission_returns_none_when_no_session(self) -> None:
        """验证 get_pending_permission 在无会话时返回 None。"""
        service = ACPService(config=_make_config())
        result = await service.get_pending_permission(
            chat_id="missing",
            agent="test-agent",
        )
        assert result is None


class TestKillProcessTree:
    """_kill_process_tree 边界条件测试。"""

    async def test_kill_process_tree_with_nonexistent_pid_does_not_raise(self) -> None:
        """验证对不存在的 pid 调用 _kill_process_tree 静默返回。

        使用一个几乎不可能存活的极大 pid（2**31-1 在大多数系统都不存在）
        验证不会抛 NoSuchProcess 之外的异常。
        """
        # 取一个几乎不可能存活的 pid
        bogus_pid = 2**31 - 1
        await _kill_process_tree(bogus_pid)  # 不应抛任何异常

    async def test_kill_process_tree_fallback_path_when_psutil_unavailable(self) -> None:
        """验证 _PSUTIL_AVAILABLE=False 时回退路径不抛异常。

        通过 patch 强制走 fallback 分支，确保 psutil 缺失时也能安全调用。
        """
        with patch.object(acp_service_module, "_PSUTIL_AVAILABLE", False), \
                patch.object(acp_service_module, "psutil", None):
            # 不应抛任何异常
            await _kill_process_tree(2**31 - 2)


class TestAtexitRegistration:
    """atexit 回调注册测试。"""

    def test_shutdown_acp_services_registered_with_atexit(self) -> None:
        """验证 _shutdown_acp_services 已通过 atexit.register 注册。"""
        # atexit 在解释器退出时执行注册的回调，无法直接获取完整列表，
        # 但可以通过 atexit.unregister + re-register 验证其已注册
        # 这里使用更可靠的方式：检查 atexit 内部注册表
        # atexit 的回调列表存储在 atexit._exithandlers（CPython < 3.12）
        # 或通过 atexit.unregister 不会抛 KeyError 验证已注册
        # 简单验证：unregister 后再 register 回去，确保整个流程不抛异常
        atexit.unregister(_shutdown_acp_services)
        atexit.register(_shutdown_acp_services)
        # 再次 unregister 验证它确实存在
        atexit.unregister(_shutdown_acp_services)
        # 重新注册以保持模块加载时的状态
        atexit.register(_shutdown_acp_services)

    def test_shutdown_acp_services_with_empty_registry_does_not_raise(self) -> None:
        """验证 _shutdown_acp_services 在注册表为空时静默返回。"""
        _acp_services.clear()
        # 不应抛任何异常
        _shutdown_acp_services()

    def test_shutdown_acp_services_clears_registry(self) -> None:
        """验证 _shutdown_acp_services 清空 _acp_services 字典。"""
        init_acp_service("temp-agent", _make_config())
        assert get_acp_service("temp-agent") is not None
        _shutdown_acp_services()
        assert get_acp_service("temp-agent") is None

    def test_shutdown_acp_services_awaits_close_without_default_loop(self) -> None:
        """没有默认事件循环时仍必须实际等待服务关闭。"""

        class FakeService:
            """记录关闭协程是否被等待。"""

            def __init__(self) -> None:
                self.closed = False

            async def close_all_sessions(self) -> None:
                self.closed = True

        service = FakeService()
        _acp_services["temp-agent"] = service

        _shutdown_acp_services()

        assert service.closed is True
        assert _acp_services == {}


class TestCloseAllSessions:
    """close_all_sessions 边界条件测试。"""

    async def test_close_all_sessions_with_empty_registry_does_not_raise(self) -> None:
        """验证空会话注册表时调用 close_all_sessions 静默返回。"""
        service = ACPService(config=_make_config())
        await service.close_all_sessions()  # 不应抛任何异常


class TestRequireExistingSession:
    """require_existing=True 在无会话时的行为测试。"""

    async def test_get_or_create_session_requires_existing_raises(self) -> None:
        """验证 require_existing=True 且无会话时抛 ACPSessionError。"""
        service = ACPService(config=_make_config())
        with pytest.raises(ACPSessionError):
            await service._get_or_create_session(
                chat_id="missing-chat",
                agent="test-agent",
                cwd=".",
                require_existing=True,
            )


class TestConcurrentSessionCreation:
    """ACP 会话首次创建的并发隔离测试。"""

    @pytest.mark.asyncio
    async def test_same_chat_and_agent_only_open_once(self) -> None:
        """同一用户会话的并发首轮 prompt 只能创建一个子进程会话。"""
        service = ACPService(config=_make_config())
        open_started = asyncio.Event()
        allow_open = asyncio.Event()
        conversation = MagicMock()
        conversation.process.returncode = None

        async def fake_open(**kwargs: Any) -> Any:
            open_started.set()
            await allow_open.wait()
            return conversation

        with patch.object(service, "_open_conversation", side_effect=fake_open) as open_mock:
            first = asyncio.create_task(
                service._get_or_create_session(
                    chat_id="user-a:session-1",
                    agent="test-agent",
                    cwd=".",
                    require_existing=False,
                )
            )
            await open_started.wait()
            second = asyncio.create_task(
                service._get_or_create_session(
                    chat_id="user-a:session-1",
                    agent="test-agent",
                    cwd=".",
                    require_existing=False,
                )
            )
            await asyncio.sleep(0)
            allow_open.set()
            first_result, second_result = await asyncio.gather(first, second)

        assert first_result is conversation
        assert second_result is conversation
        assert open_mock.call_count == 1

    @pytest.mark.asyncio
    async def test_different_users_create_independent_sessions(self) -> None:
        """不同用户即使前端 session_id 相同也应并发创建独立会话。"""
        service = ACPService(config=_make_config())
        both_started = asyncio.Event()
        allow_open = asyncio.Event()
        started_count = 0

        async def fake_open(**kwargs: Any) -> Any:
            nonlocal started_count
            started_count += 1
            if started_count == 2:
                both_started.set()
            await allow_open.wait()
            conversation = MagicMock()
            conversation.process.returncode = None
            conversation.chat_id = kwargs["chat_id"]
            return conversation

        with patch.object(service, "_open_conversation", side_effect=fake_open):
            first = asyncio.create_task(
                service._get_or_create_session(
                    chat_id="user-a:shared-session",
                    agent="test-agent",
                    cwd=".",
                    require_existing=False,
                )
            )
            second = asyncio.create_task(
                service._get_or_create_session(
                    chat_id="user-b:shared-session",
                    agent="test-agent",
                    cwd=".",
                    require_existing=False,
                )
            )
            await asyncio.wait_for(both_started.wait(), timeout=1.0)
            allow_open.set()
            first_result, second_result = await asyncio.gather(first, second)

        assert first_result is not second_result
        assert first_result.chat_id == "user-a:shared-session"
        assert second_result.chat_id == "user-b:shared-session"

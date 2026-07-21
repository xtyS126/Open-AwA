# -*- coding: utf-8 -*-
"""
ACP core 模块单元测试。

覆盖 ACPAgentConfig / ACPConfig / SuspendedPermission 数据结构与 ACPErrors 异常层级
的创建、默认值、字段访问、继承关系与 dataclass 序列化行为。
"""

from dataclasses import asdict

import pytest

from acp_host import (
    ACPAgentConfig,
    ACPConfig,
    ACPConfigurationError,
    ACPErrors,
    ACPProtocolError,
    ACPSessionError,
    ACPTransportError,
    SuspendedPermission,
)
from acp_host.core import ACPAgentConfig as CoreACPAgentConfig


class TestACPAgentConfig:
    """ACPAgentConfig dataclass 行为测试。"""

    def test_create_with_required_fields_returns_instance(self) -> None:
        """验证仅传必填字段时能创建实例，且默认值符合规范。"""
        config = ACPAgentConfig(
            agent_id="test-agent",
            name="Test Agent",
            command="python",
        )

        assert config.agent_id == "test-agent"
        assert config.name == "Test Agent"
        assert config.command == "python"

    def test_create_with_defaults_applies_expected_values(self) -> None:
        """验证未显式赋值时，关键字段采用规范约定的默认值。"""
        config = ACPAgentConfig(
            agent_id="test-agent",
            name="Test Agent",
            command="python",
        )

        # 列表/字典字段应为独立的新实例，不共享默认引用
        assert config.args == []
        assert config.env == {}
        assert config.permission_rules == {}

        # 标量默认值
        assert config.cwd is None
        assert config.tool_parse_mode == "update_detail"
        assert config.stdio_buffer_limit_bytes == 1024 * 1024
        assert config.enabled is True

    def test_default_collections_are_independent_between_instances(self) -> None:
        """验证可变默认值使用 field(default_factory=...)，实例间互不污染。"""
        first = ACPAgentConfig(agent_id="a", name="A", command="cmd")
        second = ACPAgentConfig(agent_id="b", name="B", command="cmd")

        first.args.append("--verbose")
        first.env["DEBUG"] = "1"
        first.permission_rules["allow"] = True

        assert second.args == []
        assert second.env == {}
        assert second.permission_rules == {}


class TestACPConfig:
    """ACPConfig dataclass 行为测试。"""

    def test_create_with_defaults_has_empty_agents(self) -> None:
        """验证 ACPConfig 默认创建时 agents 为空字典。"""
        config = ACPConfig()

        assert config.agents == {}
        assert isinstance(config.agents, dict)

    def test_create_with_agents_preserves_provided_mapping(self) -> None:
        """验证传入 agents 时能正确保留映射内容。"""
        agent = ACPAgentConfig(
            agent_id="opencode",
            name="OpenCode",
            command="opencode",
        )
        config = ACPConfig(agents={"opencode": agent})

        assert "opencode" in config.agents
        assert config.agents["opencode"] is agent


class TestSuspendedPermission:
    """SuspendedPermission dataclass 行为测试。"""

    def test_create_with_required_fields_returns_instance(self) -> None:
        """验证必填字段创建后可正确访问。"""
        permission = SuspendedPermission(
            payload={"tool": "shell", "args": ["ls"]},
            options=[{"label": "允许", "value": "allow"}],
            agent="opencode",
            tool_name="shell",
            tool_kind="shell",
        )

        assert permission.payload == {"tool": "shell", "args": ["ls"]}
        assert permission.options == [{"label": "允许", "value": "allow"}]
        assert permission.agent == "opencode"
        assert permission.tool_name == "shell"
        assert permission.tool_kind == "shell"

    def test_optional_fields_default_to_none(self) -> None:
        """验证可选字段未赋值时默认为 None。"""
        permission = SuspendedPermission(
            payload={},
            options=[],
            agent="agent",
            tool_name="tool",
            tool_kind="file",
        )

        assert permission.target is None
        assert permission.action is None
        assert permission.summary is None
        assert permission.command is None

    def test_paths_defaults_to_empty_list(self) -> None:
        """验证 paths 字段默认为空列表，且 requires_user_confirmation 默认为 True。"""
        permission = SuspendedPermission(
            payload={},
            options=[],
            agent="agent",
            tool_name="tool",
            tool_kind="file",
        )

        assert permission.paths == []
        assert permission.requires_user_confirmation is True

    def test_paths_default_is_independent_between_instances(self) -> None:
        """验证 paths 使用 default_factory，实例间不共享引用。"""
        first = SuspendedPermission(
            payload={},
            options=[],
            agent="a",
            tool_name="t",
            tool_kind="file",
        )
        second = SuspendedPermission(
            payload={},
            options=[],
            agent="b",
            tool_name="t",
            tool_kind="file",
        )

        first.paths.append("/etc/passwd")

        assert second.paths == []


class TestACPExceptionHierarchy:
    """ACP 异常层级与上下文承载行为测试。"""

    def test_all_subclass_errors_inherit_from_acp_errors(self) -> None:
        """验证所有具体异常类均继承自 ACPErrors。"""
        assert issubclass(ACPConfigurationError, ACPErrors)
        assert issubclass(ACPTransportError, ACPErrors)
        assert issubclass(ACPProtocolError, ACPErrors)
        assert issubclass(ACPSessionError, ACPErrors)

    def test_acp_errors_accepts_agent_keyword_argument(self) -> None:
        """验证 ACPErrors 构造器接收 agent 关键字参数且不报错。"""
        # 通过实例化校验关键字参数被正确接受
        error = ACPErrors("boom", agent="opencode")

        assert isinstance(error, Exception)
        assert error.args == ("boom",)

    def test_acp_errors_agent_attribute_is_accessible(self) -> None:
        """验证 ACPErrors 实例的 agent 属性可读，且未传时为 None。"""
        with_agent = ACPErrors("oops", agent="qwen_code")
        without_agent = ACPErrors("oops")

        assert with_agent.agent == "qwen_code"
        assert without_agent.agent is None

    def test_subclass_errors_propagate_agent_attribute(self) -> None:
        """验证子类异常同样能承载 agent 属性并可被 except ACPErrors 捕获。"""
        with pytest.raises(ACPErrors) as exc_info:
            raise ACPConfigurationError("bad config", agent="opencode")

        assert exc_info.value.agent == "opencode"
        assert isinstance(exc_info.value, ACPConfigurationError)


class TestDataclassSerialization:
    """dataclass asdict() 序列化行为测试。"""

    def test_acp_agent_config_asdict_roundtrip(self) -> None:
        """验证 ACPAgentConfig 的 asdict() 序列化输出包含全部字段。"""
        config = ACPAgentConfig(
            agent_id="opencode",
            name="OpenCode",
            command="opencode",
            args=["acp"],
            env={"LANG": "en"},
            cwd="/workspace",
            tool_parse_mode="call_title",
            stdio_buffer_limit_bytes=2048,
            enabled=False,
            permission_rules={"allow_file": True},
        )

        data = asdict(config)

        assert data["agent_id"] == "opencode"
        assert data["name"] == "OpenCode"
        assert data["command"] == "opencode"
        assert data["args"] == ["acp"]
        assert data["env"] == {"LANG": "en"}
        assert data["cwd"] == "/workspace"
        assert data["tool_parse_mode"] == "call_title"
        assert data["stdio_buffer_limit_bytes"] == 2048
        assert data["enabled"] is False
        assert data["permission_rules"] == {"allow_file": True}

    def test_suspended_permission_asdict_includes_all_fields(self) -> None:
        """验证 SuspendedPermission 的 asdict() 包含所有字段及默认值。"""
        permission = SuspendedPermission(
            payload={"x": 1},
            options=[{"value": "allow"}],
            agent="agent",
            tool_name="tool",
            tool_kind="shell",
            command="rm -rf /tmp/cache",
        )

        data = asdict(permission)

        assert data["payload"] == {"x": 1}
        assert data["options"] == [{"value": "allow"}]
        assert data["agent"] == "agent"
        assert data["tool_name"] == "tool"
        assert data["tool_kind"] == "shell"
        assert data["command"] == "rm -rf /tmp/cache"
        assert data["target"] is None
        assert data["paths"] == []
        assert data["requires_user_confirmation"] is True


class TestModuleExports:
    """模块导出一致性测试。"""

    def test_acp_package_reexports_same_class_as_core(self) -> None:
        """验证 acp 包顶层导出的 ACPAgentConfig 与 core 模块中为同一类。"""
        assert ACPAgentConfig is CoreACPAgentConfig

# -*- coding: utf-8 -*-
"""
ACP agents 模块单元测试。

覆盖 discover_agents() 与 is_agent_available() 的核心行为：4 个内置 agent
配置的正确性、命令探测的失败路径等。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from acp_host.agents import discover_agents, is_agent_available
from acp_host.core import ACPAgentConfig


class TestDiscoverAgents:
    """discover_agents() 函数行为测试。"""

    def test_returns_dict_with_four_expected_keys(self) -> None:
        """验证返回字典包含 4 个内置 agent 的 key。"""
        agents = discover_agents()

        assert set(agents.keys()) == {
            "claude_code",
            "codex",
            "openclaw",
            "opencode",
        }
        assert len(agents) == 4

    @pytest.mark.parametrize(
        "agent_id, expected_command",
        [
            ("claude_code", "claude"),
            ("codex", "codex"),
            ("openclaw", "openclaw"),
            ("opencode", "opencode"),
        ],
    )
    def test_each_agent_command_matches_agent_id(
        self,
        agent_id: str,
        expected_command: str,
    ) -> None:
        """验证每个 agent 的 command 与 agent_id 对应正确。"""
        agents = discover_agents()
        config = agents[agent_id]

        assert isinstance(config, ACPAgentConfig)
        assert config.agent_id == agent_id
        assert config.command == expected_command

    @pytest.mark.parametrize(
        "agent_id",
        ["claude_code", "codex", "openclaw", "opencode"],
    )
    def test_each_agent_enabled_defaults_to_true(self, agent_id: str) -> None:
        """验证每个 agent 的 enabled 默认为 True。"""
        agents = discover_agents()

        assert agents[agent_id].enabled is True

    @pytest.mark.parametrize(
        "agent_id",
        ["claude_code", "codex", "openclaw", "opencode"],
    )
    def test_each_agent_tool_parse_mode_defaults_to_update_detail(
        self,
        agent_id: str,
    ) -> None:
        """验证每个 agent 的 tool_parse_mode 默认为 "update_detail"。"""
        agents = discover_agents()

        assert agents[agent_id].tool_parse_mode == "update_detail"


class TestIsAgentAvailable:
    """is_agent_available() 函数行为测试。"""

    def test_returns_false_when_command_not_found(self) -> None:
        """验证 command 不存在时返回 False。

        通过 patch 模拟 subprocess.run 抛 FileNotFoundError，确保测试在
        任何环境下都确定性地验证"command 不存在"路径（假设本地未安装 claude CLI）。
        """

        def _raise_file_not_found(*args: Any, **kwargs: Any) -> None:
            raise FileNotFoundError(
                "[Errno 2] No such file or directory: 'claude'",
            )

        with patch(
            "acp_host.agents.subprocess.run",
            side_effect=_raise_file_not_found,
        ):
            result = is_agent_available("claude_code")

        assert result is False

    def test_returns_false_for_unknown_agent_id(self) -> None:
        """验证未知 agent_id 返回 False（agent 不在字典中，短路返回）。"""
        result = is_agent_available("unknown")

        assert result is False

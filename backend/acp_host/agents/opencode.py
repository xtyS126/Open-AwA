# -*- coding: utf-8 -*-
"""OpenCode agent 配置。"""
from acp_host.core import ACPAgentConfig

AGENT_CONFIG = ACPAgentConfig(
    agent_id="opencode",
    name="OpenCode",
    command="opencode",
    args=[],
    env={},
    tool_parse_mode="update_detail",
    stdio_buffer_limit_bytes=1024 * 1024,
    enabled=True,
    permission_rules={},
)

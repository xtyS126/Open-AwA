# -*- coding: utf-8 -*-
"""
ACP 内置 Agent 配置发现模块。

扫描本目录下所有 *.py 文件（除 __init__.py），动态导入每个模块并读取模块级
变量 AGENT_CONFIG: ACPAgentConfig，汇总返回按 agent_id 索引的字典。

同时提供 is_agent_available(agent_id) 函数，通过 subprocess 探测本地是否安装
对应 Agent 的 CLI 命令。
"""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path
from typing import Optional

from acp_host.core import ACPAgentConfig


__all__ = [
    "discover_agents",
    "is_agent_available",
]


def discover_agents() -> dict[str, ACPAgentConfig]:
    """扫描 agents/ 目录下所有 *.py 文件并汇总 ACPAgentConfig 配置。

    遍历本模块所在目录下的所有 .py 模块（除 __init__.py），动态导入每个模块
    并读取模块级变量 AGENT_CONFIG: ACPAgentConfig，按 agent_id 索引返回字典。

    单个模块导入失败或缺少 AGENT_CONFIG 时跳过，不影响其他 agent 的发现。

    Returns:
        按 agent_id 索引的 ACPAgentConfig 字典。
    """
    agents: dict[str, ACPAgentConfig] = {}
    package_dir = Path(__file__).parent
    package_name = __name__  # acp_host.agents

    for module_file in package_dir.glob("*.py"):
        if module_file.name == "__init__.py":
            continue
        module_name = module_file.stem  # 文件名（不含 .py）
        full_module_name = f"{package_name}.{module_name}"
        try:
            module = importlib.import_module(full_module_name)
        except Exception:
            # 模块导入失败时跳过，不影响其他 agent 的发现
            continue
        agent_config = getattr(module, "AGENT_CONFIG", None)
        if not isinstance(agent_config, ACPAgentConfig):
            continue
        agents[agent_config.agent_id] = agent_config

    return agents


def is_agent_available(
    agent_id: str,
    agents: Optional[dict[str, ACPAgentConfig]] = None,
) -> bool:
    """探测本地是否安装了指定 Agent 的 CLI 命令。

    通过 subprocess.run([command, "--version"], capture_output=True, timeout=5)
    探测本地是否安装了对应 Agent 的命令行工具。返回 True 当且仅当 exit code == 0。

    Args:
        agent_id: Agent 标识。
        agents: 可选的已发现 Agent 字典；为 None 时调用 discover_agents()。

    Returns:
        True 当且仅当本地安装了对应 CLI 命令且 exit code == 0；
        任何异常（FileNotFoundError、TimeoutExpired 等）返回 False。
    """
    if agents is None:
        agents = discover_agents()
    agent_config = agents.get(agent_id)
    if agent_config is None:
        return False
    try:
        result = subprocess.run(
            [agent_config.command, "--version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        # FileNotFoundError / PermissionError / TimeoutExpired 等均属于
        # OSError 或 subprocess.SubprocessError 的子类
        return False

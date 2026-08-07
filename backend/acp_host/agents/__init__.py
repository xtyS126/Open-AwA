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
import sys
from pathlib import Path
from typing import Optional

from loguru import logger

from acp_host.core import ACPAgentConfig


__all__ = [
    "discover_agents",
    "is_agent_available",
    "resolve_agent_command",
]


def discover_agents() -> dict[str, ACPAgentConfig]:
    """扫描 agents/ 目录下所有 *.py 文件并汇总 ACPAgentConfig 配置。

    遍历本模块所在目录下的所有 .py 模块（除 __init__.py），动态导入每个模块
    并读取模块级变量 AGENT_CONFIG: ACPAgentConfig，按 agent_id 索引返回字典。

    单个模块导入失败时以禁用状态（enabled=False）显式暴露该 agent，
    供 /api/acp/agents 展示为"可见不可用"，不静默消失。

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
        except Exception as e:
            # 导入失败的 agent 显式标记 broken 状态：以禁用配置暴露（可见不可用）
            logger.error(
                f"加载 ACP agent 模块 {full_module_name} 失败，以禁用状态暴露: {e}",
                exc_info=True,
            )
            agents[module_name] = ACPAgentConfig(
                agent_id=module_name,
                name=f"{module_name}（加载失败）",
                command="",
                enabled=False,
            )
            continue
        agent_config = getattr(module, "AGENT_CONFIG", None)
        if not isinstance(agent_config, ACPAgentConfig):
            continue
        agents[agent_config.agent_id] = agent_config

    return agents


def is_agent_available(
    agent_id: str,
    agents: Optional[dict[str, ACPAgentConfig]] = None,
    cwd: Optional[str] = None,
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
    command = resolve_agent_command(agent_config, cwd)
    try:
        result = subprocess.run(
            [command, "--version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        # FileNotFoundError / PermissionError / TimeoutExpired 等均属于
        # OSError 或 subprocess.SubprocessError 的子类
        return False


def resolve_agent_command(
    agent_config: ACPAgentConfig,
    cwd: Optional[str] = None,
) -> str:
    """解析 Agent 可执行文件，OpenCode 优先使用项目本地安装。"""
    if agent_config.agent_id != "opencode" or not cwd:
        return agent_config.command

    bin_dir = Path(cwd) / "node_modules" / ".bin"
    candidates = ["opencode.cmd", "opencode.exe", "opencode"]
    if sys.platform != "win32":
        candidates = ["opencode", "opencode.cmd", "opencode.exe"]
    for filename in candidates:
        candidate = bin_dir / filename
        if candidate.is_file():
            return str(candidate)
    return agent_config.command

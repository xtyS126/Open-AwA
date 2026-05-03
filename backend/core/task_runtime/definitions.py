"""
代理定义数据类与内置代理类型注册。
描述某一类代理的静态配置，而非某次运行实例。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass
class AgentDefinition:
    """代理类型定义，描述一类子代理的静态配置。"""

    name: str
    scope: str = "system"  # system / project / user / plugin
    description: str = ""
    system_prompt: str = ""
    tools: List[str] = field(default_factory=list)
    disallowed_tools: List[str] = field(default_factory=list)
    model: Optional[str] = None
    permission_mode: str = "default"  # default / accept_edits / plan / bypass_permissions / dont_ask
    memory_mode: str = "none"  # none / user / project / local
    background_default: bool = False
    isolation_mode: str = "inherit"  # inherit / fresh / worktree
    color: str = ""  # UI 展示颜色标识
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "scope": self.scope,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "tools": self.tools,
            "disallowed_tools": self.disallowed_tools,
            "model": self.model,
            "permission_mode": self.permission_mode,
            "memory_mode": self.memory_mode,
            "background_default": self.background_default,
            "isolation_mode": self.isolation_mode,
            "color": self.color,
            "metadata": self.metadata,
        }


# 内置代理定义

BUILTIN_AGENT_DEFINITIONS: Dict[str, AgentDefinition] = {
    "Explore": AgentDefinition(
        name="Explore",
        scope="system",
        description="只读调研代理，用于搜索代码库、查找文件、grep 符号或回答'某功能在哪实现'类问题",
        system_prompt="""你是一个代码调研助手。你的任务是搜索和阅读代码库，回答用户关于代码结构、实现位置、依赖关系等问题。
规则：
- 只使用只读工具（Read、Grep、Glob），不得修改任何文件
- 返回简洁的结构化结果，包含文件路径和行号
- 如果找不到答案，如实报告，不要猜测""",
        tools=["read_file", "list_files", "web_search", "local_search"],
        permission_mode="plan",
        memory_mode="none",
        isolation_mode="inherit",
        color="#6B8E23",
    ),
    "Plan": AgentDefinition(
        name="Plan",
        scope="system",
        description="规划代理，用于设计实施方案、评估架构决策、拆解复杂任务",
        system_prompt="""你是一个技术规划助手。你的任务是分析需求、设计方案、评估取舍。
规则：
- 只使用只读工具，专注于分析和设计
- 输出结构化方案，包含步骤、风险、依赖
- 考虑现有代码库的架构约束""",
        tools=["read_file", "list_files", "web_search", "local_search"],
        permission_mode="plan",
        memory_mode="none",
        isolation_mode="inherit",
        color="#4169E1",
    ),
    "general-purpose": AgentDefinition(
        name="general-purpose",
        scope="system",
        description="通用代理，可执行调研、代码修改、测试等多种任务",
        system_prompt="""你是一个通用编程助手。根据用户的任务执行相应的操作。
规则：
- 优先使用现有工具完成任务
- 完成后返回简洁的摘要
- 如果操作可能产生副作用，先说明风险""",
        tools=[],
        permission_mode="default",
        memory_mode="user",
        isolation_mode="fresh",
        color="#FF8C00",
    ),
}


def get_builtin_agents() -> Dict[str, AgentDefinition]:
    """返回所有内置代理定义。"""
    return dict(BUILTIN_AGENT_DEFINITIONS)


def get_agent_definition(agent_type: str) -> Optional[AgentDefinition]:
    """按名称获取代理定义，先查内置，后续可扩展插件注册来源。"""
    if agent_type in BUILTIN_AGENT_DEFINITIONS:
        return BUILTIN_AGENT_DEFINITIONS[agent_type]
    logger.bind(module="task_runtime", agent_type=agent_type).warning(f"未找到代理定义: {agent_type}")
    return None


def list_agent_types() -> List[str]:
    """列出所有可用代理类型名称。"""
    return list(BUILTIN_AGENT_DEFINITIONS.keys())

"""
代理定义数据类与内置代理类型注册。
描述某一类代理的静态配置，而非某次运行实例。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from loguru import logger


class AgentMemoryScope(str, Enum):
    """代理记忆范围枚举，决定记忆持久化与共享粒度。"""

    USER = "user"        # 用户级：跨项目共享用户记忆
    PROJECT = "project"  # 项目级：当前项目内共享
    LOCAL = "local"      # 本地：仅当前代理会话可见


@dataclass
class HookConfig:
    """钩子配置，描述在代理生命周期事件上触发的处理函数标识。"""

    event: str       # 事件名称（如 subagent_start / subagent_stop）
    handler: str     # 处理函数标识（注册到 hook_dispatcher 的键）


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
    # Task 11 扩展字段：均带默认值，保持向后兼容
    max_turns: Optional[int] = None  # 最大轮次限制，None 表示不限制
    effort: Literal["low", "medium", "high"] = "medium"  # 努力程度，联动 LLM 参数
    omit_project_context: bool = False  # 是否省略项目上下文注入
    hooks: List[HookConfig] = field(default_factory=list)  # 钩子配置列表
    memory_scope: AgentMemoryScope = AgentMemoryScope.LOCAL  # 记忆范围

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
            "max_turns": self.max_turns,
            "effort": self.effort,
            "omit_project_context": self.omit_project_context,
            "hooks": [
                {"event": h.event, "handler": h.handler} for h in self.hooks
            ],
            "memory_scope": self.memory_scope.value,
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
        background_default=True,
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
        background_default=True,
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
    "verification": AgentDefinition(
        name="验证 Agent",
        scope="system",
        description="独立验证前序 Agent 的结果，不信任任何前序输出，必须实际运行测试验证",
        system_prompt="""你是一个独立验证代理。你的核心职责是独立验证前序 Agent 的执行结果，绝不信任任何前序输出。
原则：
- 独立验证：不信任前序 Agent 的任何结论，必须亲自核实
- 必须实际运行测试：如果存在测试用例，必须实际执行测试验证功能正确性
- 必须实际读取文件验证：如果验证文件内容，必须实际读取文件核对，不得仅凭描述判断
- 给出明确的验证结论：最终必须给出"通过"、"失败"或"需进一步检查"的明确结论
- 发现不一致时，如实报告差异，不得掩盖问题
- 只使用只读工具，不得修改任何文件或代码""",
        tools=["read_file", "list_files", "file_exists", "web_search", "web_fetch"],
        permission_mode="plan",
        memory_mode="none",
        isolation_mode="inherit",
        color="#DC143C",
        max_turns=10,
        effort="high",
        omit_project_context=False,
        memory_scope=AgentMemoryScope.LOCAL,
    ),
    "guide": AgentDefinition(
        name="引导 Agent",
        scope="system",
        description="在关键决策点暂停询问用户，提供选项分析，不自行做出不可逆操作",
        system_prompt="""你是一个决策引导代理。你的职责是在关键决策点协助用户做出明智选择。
原则：
- 在关键决策点暂停询问用户：遇到需要用户判断的节点时，必须暂停并请求用户确认，不得擅自推进
- 提供选项分析：为每个可选方案分析利弊、风险与成本，帮助用户权衡
- 不自行做出不可逆操作：删除文件、修改配置、部署上线等不可逆操作必须经用户确认，严禁自行执行
- 遇到歧义时主动询问用户澄清：需求或上下文存在歧义时，主动向用户提问以澄清意图
- 只使用只读工具进行调研，不修改任何文件
- 输出结构化的选项对比，包含推荐建议与理由""",
        tools=["read_file", "list_files", "web_search"],
        permission_mode="plan",
        memory_mode="user",
        isolation_mode="inherit",
        color="#9370DB",
        max_turns=5,
        effort="medium",
        omit_project_context=True,
        memory_scope=AgentMemoryScope.USER,
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

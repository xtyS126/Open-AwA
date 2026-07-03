# -*- coding: utf-8 -*-
"""
ACP (Agent Client Protocol) 核心共享定义模块。

本模块定义 ACP 子系统的基础数据结构与异常层级，供后续 client.py、service.py、
permissions.py 等模块复用。本模块不依赖外部 `acp` SDK，可在未安装 SDK 的环境
下安全导入，便于阶段化集成。

包含内容：
- ACPAgentConfig：单个 ACP Agent 的配置（命令、环境变量、解析模式等）
- ACPConfig：ACP 子系统顶层配置（按 agent_id 索引的 agents 集合）
- SuspendedPermission：被挂起的权限审批请求载体
- ACPErrors 及其子类：ACP 相关异常层级
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional


__all__ = [
    "ACPAgentConfig",
    "ACPConfig",
    "ACPErrors",
    "ACPConfigurationError",
    "ACPTransportError",
    "ACPProtocolError",
    "ACPSessionError",
    "SuspendedPermission",
]


class ACPErrors(Exception):
    """ACP 模块异常基类。

    所有 ACP 相关异常均继承自此基类，便于上层统一捕获处理。
    通过 agent 关键字参数携带出错时所属的 Agent 标识，便于排查定位。
    """

    def __init__(self, message: str, *, agent: Optional[str] = None) -> None:
        """初始化 ACP 异常。

        Args:
            message: 异常描述信息。
            agent: 触发异常的 Agent 标识，可选，用于上下文追踪。
        """
        super().__init__(message)
        self.agent = agent


class ACPConfigurationError(ACPErrors):
    """ACP 配置错误：agent 配置缺失、字段非法或加载失败时抛出。"""


class ACPTransportError(ACPErrors):
    """ACP 传输层错误：stdio/SSE 传输中断、读写超时或底层 IO 异常时抛出。"""


class ACPProtocolError(ACPErrors):
    """ACP 协议错误：收到不符合 ACP 规范的消息、未知事件类型或序列化失败时抛出。"""


class ACPSessionError(ACPErrors):
    """ACP 会话错误：会话生命周期异常、会话已关闭或会话状态非法时抛出。"""


@dataclass
class ACPAgentConfig:
    """单个 ACP Agent 的配置项。

    描述如何拉起一个 ACP Agent 子进程：启动命令、参数、环境变量、工作目录，
    以及工具调用解析模式、stdio 缓冲上限、是否启用、权限规则等运行时参数。

    Attributes:
        agent_id: Agent 唯一标识，用于在 ACPConfig.agents 中索引。
        name: Agent 展示名称，用于日志和前端展示。
        command: 启动 Agent 子进程的命令（可执行文件名或路径）。
        args: 传递给启动命令的参数列表。
        env: 子进程环境变量覆盖项。
        cwd: 子进程工作目录，None 表示继承父进程。
        tool_parse_mode: 工具调用的解析模式，支持 update_detail 与 call_title。
        stdio_buffer_limit_bytes: stdio 传输单条缓冲上限字节数。
        enabled: 是否启用该 Agent。
        permission_rules: Agent 的权限规则配置，结构由 permissions 模块定义。
    """

    agent_id: str
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: Optional[str] = None
    tool_parse_mode: Literal["update_detail", "call_title"] = "update_detail"
    stdio_buffer_limit_bytes: int = 1024 * 1024
    enabled: bool = True
    permission_rules: dict[str, Any] = field(default_factory=dict)


@dataclass
class ACPConfig:
    """ACP 子系统顶层配置。

    以 agent_id 为键组织所有已配置的 ACP Agent。默认为空集合，
    由上层加载逻辑（配置文件 / 数据库 / 默认值合并）填充内容。

    Attributes:
        agents: 按 agent_id 索引的 Agent 配置字典。
    """

    agents: dict[str, ACPAgentConfig] = field(default_factory=dict)


@dataclass
class SuspendedPermission:
    """被挂起的权限审批请求载体。

    当 ACP Agent 调用需要用户确认的工具时，将审批上下文封装为本对象挂起，
    等待用户在前端确认后恢复执行。承载工具调用元信息与受影响的资源描述。

    Attributes:
        payload: 原始工具调用请求体，用于恢复时回放。
        options: 可选的审批选项列表（如 allow_once/allow_always/deny）。
        agent: 触发该权限请求的 Agent 标识。
        tool_name: 工具名称。
        tool_kind: 工具类别（如 file/shell/network）。
        target: 操作目标资源标识，可选。
        action: 具体动作（如 read/write/execute），可选。
        summary: 人类可读的操作摘要，可选。
        command: 当工具为 shell 类时记录的具体命令，可选。
        paths: 涉及的文件路径列表，默认为空。
        requires_user_confirmation: 是否必须用户显式确认。
    """

    payload: dict[str, Any]
    options: list[dict[str, Any]]
    agent: str
    tool_name: str
    tool_kind: str
    target: Optional[str] = None
    action: Optional[str] = None
    summary: Optional[str] = None
    command: Optional[str] = None
    paths: list[str] = field(default_factory=list)
    requires_user_confirmation: bool = True

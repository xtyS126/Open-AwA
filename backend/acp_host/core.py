# -*- coding: utf-8 -*-
"""
ACP (Agent Client Protocol) 核心共享定义模块。

本模块定义 ACP 子系统的 Open-AwA 特有语义层，供后续 client.py、service.py、
permissions.py 等模块复用。异常类与数据结构尽量收敛为对外部 `acp` SDK 原生
类型的薄封装或 re-export，仅保留 Open-AwA 特有的上下文字段（如 agent 标识、
asyncio.Future 集成等）。

包含内容：
- RequestError：re-export 自 acp.exceptions.RequestError（SDK 缺失时使用签名一致的占位类）
- ACPErrors：Open-AwA 异常基类，薄封装 SDK RequestError，增加 agent 上下文
- ACPConfigurationError / ACPTransportError / ACPProtocolError / ACPSessionError：
  Open-AwA 语义层异常分类，继承 ACPErrors，自动获得 RequestError 身份
- ACPAgentConfig：Open-AwA 特有的"如何拉起 Agent 子进程"配置（SDK 无对应类型）
- ACPConfig：Open-AwA 特有的 agents 集合（SDK 无对应类型）
- SuspendedPermission：Open-AwA 特有的"挂起-恢复"权限审批载体（SDK 无对应类型，
  与 acp.schema.PermissionOption / RequestPermissionRequest 配合使用）

SDK 依赖说明：
- 异常类通过 try/except 优雅降级；SDK 缺失时 RequestError 使用签名一致的占位类，
  ACPErrors 仍可被实例化与抛出
- 数据结构不直接依赖 SDK 类型，仅在文档注释中标注与 SDK 类型的协作关系
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

try:
    # 优先使用官方 acp SDK 的 RequestError 作为异常基类
    from acp.exceptions import RequestError as _SDKRequestError

    _ACP_SDK_AVAILABLE = True
except ImportError:
    _ACP_SDK_AVAILABLE = False

    class _SDKRequestError(Exception):  # type: ignore[no-redef]
        """SDK 缺失时占位的 RequestError 异常类型。

        签名与 acp.exceptions.RequestError 保持一致（位置参数 code/message/data），
        使 Open-AwA 异常层级在 SDK 缺失环境下仍可正常实例化与抛出。
        """

        def __init__(
            self,
            code: int = 0,
            message: str = "",
            data: Any = None,
        ) -> None:
            super().__init__(message)
            self.code = code
            self.message = message
            self.data = data

        def to_error_obj(self) -> dict[str, Any]:
            """转换为 JSON-RPC error 对象，签名对齐 SDK RequestError。"""
            return {"code": self.code, "message": str(self), "data": self.data}


# re-export SDK 的 RequestError，供上层在需要捕获 SDK 协议异常时统一导入
RequestError = _SDKRequestError


__all__ = [
    "RequestError",
    "ACPAgentConfig",
    "ACPConfig",
    "ACPErrors",
    "ACPConfigurationError",
    "ACPTransportError",
    "ACPProtocolError",
    "ACPSessionError",
    "SuspendedPermission",
]


class ACPErrors(_SDKRequestError):
    """ACP 模块异常基类（薄封装 SDK RequestError，增加 agent 上下文）。

    继承自 acp.exceptions.RequestError，使 Open-AwA 自定义异常可被 SDK 异常处理
    逻辑统一捕获（例如 except RequestError 同时捕获 ACPConfigurationError 等）。
    在 SDK 原生 code/message/data 字段之外，额外携带 agent 上下文字段，便于
    上层排查定位出错时所属的 Agent 标识。

    构造签名兼容两种调用方式：
    - Open-AwA 风格：ACPErrors("boom", agent="opencode")
    - SDK 风格：ACPErrors(code=-32000, message="boom", data={"key": "value"})
    """

    def __init__(
        self,
        message: str,
        *,
        agent: Optional[str] = None,
        code: int = 0,
        data: Any = None,
    ) -> None:
        """初始化 ACP 异常。

        Args:
            message: 异常描述信息。
            agent: 触发异常的 Agent 标识，可选，用于上下文追踪。
            code: JSON-RPC 错误码，默认 0（Open-AwA 语义层错误通常无标准码）。
            data: JSON-RPC 错误附加数据，可选。
        """
        super().__init__(code=code, message=message, data=data)
        self.agent = agent


class ACPConfigurationError(ACPErrors):
    """ACP 配置错误：agent 配置缺失、字段非法或加载失败时抛出。"""


class ACPTransportError(ACPErrors):
    """ACP 传输层错误：stdio/SSE 传输中断、读写超时或底层 IO 异常时抛出。"""


class ACPProtocolError(ACPErrors):
    """ACP 协议错误：收到不符合 ACP 规范的消息、未知事件类型或序列化失败时抛出。

    语义上对应 SDK RequestError 的 protocol_error 场景，但保留 Open-AwA 上下文。
    """


class ACPSessionError(ACPErrors):
    """ACP 会话错误：会话生命周期异常、会话已关闭或会话状态非法时抛出。"""


@dataclass
class ACPAgentConfig:
    """单个 ACP Agent 的配置项（Open-AwA 特有语义层，SDK 无对应类型）。

    描述如何拉起一个 ACP Agent 子进程：启动命令、参数、环境变量、工作目录，
    以及工具调用解析模式、stdio 缓冲上限、是否启用、权限规则等运行时参数。
    本结构与 SDK 的 spawn_agent_process / connect_to_agent 函数配合使用：
    service.py 读取本配置后调用 spawn_agent_process(command, *args, env, cwd,
    transport_kwargs={"limit": stdio_buffer_limit_bytes}) 拉起子进程。

    SDK 关系说明：
    - SDK 的 acp.core.DEFAULT_STDIO_BUFFER_LIMIT_BYTES 默认 50MB，Open-AwA 出于
      内存控制考虑默认 1MB；可在配置中按需上调
    - SDK 不提供"agent 配置"数据结构，因为 SDK 假设调用方直接传参给
      spawn_agent_process；Open-AwA 需要多 Agent 注册表，故保留本结构

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
    """ACP 子系统顶层配置（Open-AwA 特有语义层，SDK 无对应类型）。

    以 agent_id 为键组织所有已配置的 ACP Agent。默认为空集合，
    由上层加载逻辑（配置文件 / 数据库 / 默认值合并）填充内容。

    SDK 不提供"agents 集合"数据结构，因为 SDK 假设调用方单次拉起一个 Agent；
    Open-AwA 需要支持多 Agent 注册与切换，故保留本结构。

    Attributes:
        agents: 按 agent_id 索引的 Agent 配置字典。
    """

    agents: dict[str, ACPAgentConfig] = field(default_factory=dict)


@dataclass
class SuspendedPermission:
    """被挂起的权限审批请求载体（Open-AwA 特有语义层，SDK 无对应类型）。

    当 ACP Agent 调用需要用户确认的工具时，将审批上下文封装为本对象挂起，
    等待用户在前端确认后恢复执行。承载工具调用元信息与受影响的资源描述。

    SDK 关系说明：
    - SDK 的 acp.schema.RequestPermissionRequest 描述"请求"语义，但 SDK 假设
      request_permission 同步返回 RequestPermissionResponse；Open-AwA 需要异步
      挂起-恢复机制（asyncio.Future），故保留本载体
    - options 字段的元素结构与 acp.schema.PermissionOption 对齐（optionId/name/
      kind），但以 dict 形式流转以兼容 SDK 缺失场景
    - payload 字段保留原始 tool_call 与 options 的 dict 序列化结果，用于恢复时回放

    asyncio.Future 集成（Open-AwA 特有语义层，必须保留）：
    - client.py 在 request_permission 中创建 asyncio.Future 并挂起本载体
    - 用户审批后通过 resolve_permission(option_id) 调用 future.set_result()
    - 恢复执行后 request_permission 协程返回 RequestPermissionResponse

    Attributes:
        payload: 原始工具调用请求体，用于恢复时回放。
        options: 可选的审批选项列表（元素结构对齐 acp.schema.PermissionOption）。
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

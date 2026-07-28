"""
ToolUseContext：工具执行的显式依赖注入容器。

替代散乱的 Dict[str, Any] 上下文，将工具执行所需的运行态依赖集中到一个 dataclass：
- 标识字段：session_id / user_id / agent_id
- 中止控制：abort_controller（树状级联中止）
- 内容替换：content_replacement_state（工具结果 token 预算管理）
- 回调钩子：record_usage / record_latency / spawn_subagent
- 扩展元数据：metadata

设计目标：
- 显式声明依赖，避免 Dict 的隐式契约与拼写错误
- 类型安全，IDE 自动补全与静态检查友好
- 渐进式迁移：通过适配器函数支持仍接收 Dict 的旧工具
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Union

from core.abort_controller import AbortController
from core.content_replacement import ContentReplacementState


@dataclass
class ToolUseContext:
    """
    工具执行的显式依赖注入容器。

    必填字段：
        session_id: 会话 ID
        user_id: 用户 ID
        agent_id: Agent ID

    可选字段（默认 None）：
        abort_controller: 中止控制器，用于级联中止工具执行
        content_replacement_state: 工具结果内容替换状态，管理 token 预算
        record_usage: 记录 token 使用量的回调，签名为 (usage: dict) -> None
        record_latency: 记录工具延迟的回调，签名为 (tool_name: str, latency: float) -> None
        spawn_subagent: 启动子 Agent 的回调，签名为 (agent_type: str, params: dict) -> str

    可选字段（默认空容器）：
        metadata: 额外元数据 dict，每个实例独立
    """

    session_id: str
    user_id: str
    agent_id: str
    abort_controller: Optional[AbortController] = None
    content_replacement_state: Optional[ContentReplacementState] = None
    record_usage: Optional[Callable[[dict], None]] = None  # 记录 token 使用量
    record_latency: Optional[Callable[[str, float], None]] = None  # 记录工具延迟
    spawn_subagent: Optional[Callable[[str, dict], str]] = None  # 启动子 Agent
    metadata: dict = field(default_factory=dict)  # 额外元数据


def create_default(session_id: str, user_id: str, agent_id: str) -> ToolUseContext:
    """
    构造仅含必填字段的 ToolUseContext 实例。

    可选字段（abort_controller / content_replacement_state / 回调）均为默认值 None，
    metadata 为空 dict。调用方可在获得实例后按需赋值。

    Args:
        session_id: 会话 ID
        user_id: 用户 ID
        agent_id: Agent ID

    Returns:
        仅含必填字段的 ToolUseContext 实例
    """
    return ToolUseContext(
        session_id=session_id,
        user_id=user_id,
        agent_id=agent_id,
    )


def context_to_dict(ctx: ToolUseContext) -> Dict[str, Any]:
    """
    将 ToolUseContext 转换为 Dict[str, Any]，用于向后兼容仍接收 Dict 的旧工具。

    转换规则：
    - 标识字段直接平铺为顶层键
    - abort_controller / content_replacement_state 平铺为顶层键
    - 回调函数不平铺（Dict 上下文中不支持回调，旧工具不应依赖）
    - metadata 的键值合并到顶层（与历史 context.get("xxx") 用法兼容）

    Args:
        ctx: ToolUseContext 实例

    Returns:
        包含标识字段与状态的 Dict 上下文
    """
    result: Dict[str, Any] = {
        "session_id": ctx.session_id,
        "user_id": ctx.user_id,
        "agent_id": ctx.agent_id,
        "abort_controller": ctx.abort_controller,
        "content_replacement_state": ctx.content_replacement_state,
    }
    # 合并 metadata 到顶层，兼容旧工具的 context.get("xxx") 调用
    if ctx.metadata:
        for key, value in ctx.metadata.items():
            result.setdefault(key, value)
    return result


def coerce_tool_context(context: Union[ToolUseContext, Dict[str, Any], None]) -> ToolUseContext:
    """
    适配器：将任意形式的上下文统一转换为 ToolUseContext。

    用于渐进式迁移阶段，工具 execute 函数可调用本函数获取 ToolUseContext，
    无论调用方传入的是 Dict 还是 ToolUseContext。

    Args:
        context: ToolUseContext 实例、Dict 上下文或 None

    Returns:
        ToolUseContext 实例；传入 None 时返回必填字段为空串的默认实例
    """
    if isinstance(context, ToolUseContext):
        return context
    if context is None:
        return ToolUseContext(session_id="", user_id="", agent_id="")
    # Dict 上下文：提取已知字段，其余键归入 metadata
    known_keys = {
        "session_id", "user_id", "agent_id",
        "abort_controller", "content_replacement_state",
        "record_usage", "record_latency", "spawn_subagent",
    }
    return ToolUseContext(
        session_id=str(context.get("session_id", "")),
        user_id=str(context.get("user_id", "")),
        agent_id=str(context.get("agent_id", "")),
        abort_controller=context.get("abort_controller"),
        content_replacement_state=context.get("content_replacement_state"),
        record_usage=context.get("record_usage"),
        record_latency=context.get("record_latency"),
        spawn_subagent=context.get("spawn_subagent"),
        metadata={
            k: v for k, v in context.items() if k not in known_keys
        },
    )

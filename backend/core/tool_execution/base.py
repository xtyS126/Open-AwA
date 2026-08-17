"""
工具执行策略抽象基类：定义统一的工具执行接口。
所有工具类型（builtin/plugin/mcp/task）的策略类必须继承此类。
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from dataclasses import dataclass, field


@dataclass
class ToolExecutionContext:
    """工具执行上下文：权限检查、钩子应用、结果构建所需的共享数据"""
    session_id: str
    user_id: int
    tool_name: str
    tool_input: Dict[str, Any]
    tool_call_id: str
    abort_controller: Optional[Any] = None
    content_replacement_state: Optional[Any] = None
    # 权限相关
    permission_mode: str = "auto"
    # 钩子相关
    hook_manager: Optional[Any] = None
    # 预算相关
    record_usage: Optional[Any] = None
    record_latency: Optional[Any] = None
    # 原始上下文 Dict（兼容现有代码）
    raw_context: Dict[str, Any] = field(default_factory=dict)
    # 扩展字段
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolExecutionResult:
    """工具执行结果"""
    output: Any
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    # 是否需要在执行前请求用户权限
    needs_permission: bool = False
    permission_message: Optional[str] = None


class ToolExecutionStrategy(ABC):
    """工具执行策略抽象基类"""

    @abstractmethod
    async def execute(self, context: ToolExecutionContext) -> ToolExecutionResult:
        """执行工具，返回结果"""
        ...

    @abstractmethod
    def can_handle(self, tool_name: str) -> bool:
        """判断此策略是否能处理该工具"""
        ...

    async def check_permission(self, context: ToolExecutionContext) -> bool:
        """检查工具执行权限（默认实现：总是允许，子类可覆盖）"""
        return True

    async def apply_pre_hooks(self, context: ToolExecutionContext) -> Optional[ToolExecutionResult]:
        """应用 PreToolUse 钩子（默认实现：无操作，子类可覆盖）"""
        return None

    async def apply_post_hooks(self, context: ToolExecutionContext, result: ToolExecutionResult) -> ToolExecutionResult:
        """应用 PostToolUse 钩子（默认实现：透传结果，子类可覆盖）"""
        return result
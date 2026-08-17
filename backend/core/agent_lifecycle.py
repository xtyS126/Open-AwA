"""
Agent 生命周期管理器：管理核心组件的实例创建、持有和销毁。
替代模块级全局单例，便于测试隔离。
"""
from typing import Optional, Any
from dataclasses import dataclass, field


@dataclass
class AgentLifecycle:
    """Agent 生命周期管理器"""

    # 核心组件实例
    tool_registry: Optional[Any] = None
    hook_manager: Optional[Any] = None
    feedback_layer: Optional[Any] = None
    task_runtime: Optional[Any] = None

    # 后台任务追踪
    _running_background_tasks: dict = field(default_factory=dict)

    def init_tool_registry(self):
        """初始化工具注册表"""
        from core.tool_registry import ToolRegistry
        self.tool_registry = ToolRegistry()

    def init_hook_manager(self):
        """初始化钩子管理器"""
        from core.hook_manager import HookManager
        self.hook_manager = HookManager()

    def init_feedback_layer(self):
        """初始化反馈层"""
        from core.feedback import FeedbackLayer
        self.feedback_layer = FeedbackLayer()

    def create_task_runtime(self, db_session_factory=None):
        """创建 TaskRuntime 实例（工厂方法）"""
        from core.task_runtime.facade import TaskRuntimeFacade
        self.task_runtime = TaskRuntimeFacade()
        if db_session_factory:
            self.task_runtime.db_session_factory = db_session_factory
        return self.task_runtime

    def get_tool_registry(self):
        """获取工具注册表（懒初始化）"""
        if self.tool_registry is None:
            self.init_tool_registry()
        return self.tool_registry

    def get_hook_manager(self):
        """获取钩子管理器（懒初始化）"""
        if self.hook_manager is None:
            self.init_hook_manager()
        return self.hook_manager

    def get_feedback_layer(self):
        """获取反馈层（懒初始化）"""
        if self.feedback_layer is None:
            self.init_feedback_layer()
        return self.feedback_layer

    def get_task_runtime(self):
        """获取 TaskRuntime（懒初始化）"""
        if self.task_runtime is None:
            self.create_task_runtime()
        return self.task_runtime

    def track_background_task(self, task_id: str, task: Any):
        """追踪后台任务"""
        self._running_background_tasks[task_id] = task

    def untrack_background_task(self, task_id: str):
        """取消追踪后台任务"""
        self._running_background_tasks.pop(task_id, None)

    def cleanup(self):
        """清理所有资源"""
        self._running_background_tasks.clear()
        self.tool_registry = None
        self.hook_manager = None
        self.feedback_layer = None
        self.task_runtime = None

    @classmethod
    def create_test_instance(cls):
        """创建测试用独立实例"""
        return cls()


# 全局默认实例（保持向后兼容）
_default_lifecycle = AgentLifecycle()


def get_agent_lifecycle() -> AgentLifecycle:
    """获取全局默认 AgentLifecycle 实例"""
    return _default_lifecycle


def set_agent_lifecycle(lifecycle: AgentLifecycle):
    """替换全局 AgentLifecycle 实例（用于测试）"""
    global _default_lifecycle
    _default_lifecycle = lifecycle
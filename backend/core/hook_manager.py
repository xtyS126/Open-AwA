"""
类型化 Hook 系统，提供插件可扩展的生命周期事件机制。

参考 OpenCode PluginV2 Hook 设计：
- 类型化的 Hook 接口：每个 Hook 有明确的输入/输出类型
- 隔离执行：每个 Hook 在独立作用域中运行，错误不传播
- 超时控制：单个 Hook 默认 30 秒超时
- 插件自动注册/卸载：插件加载时注册 Hook，卸载时自动清理

核心 Hooks 定义：
- agent.system_prompt: 修改系统提示
- tool.before_execute: 工具执行前
- tool.after_execute: 工具执行后
- llm.before_request: LLM 请求前
- llm.after_response: LLM 响应后
- session.created: 会话创建时
- session.closed: 会话关闭时
"""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from loguru import logger


class HookName(str, Enum):
    """预定义的 Hook 名称"""
    # Agent 相关
    AGENT_SYSTEM_PROMPT = "agent.system_prompt"
    AGENT_TOOL_FILTER = "agent.tool_filter"

    # 工具相关
    TOOL_BEFORE_EXECUTE = "tool.before_execute"
    TOOL_AFTER_EXECUTE = "tool.after_execute"
    TOOL_VALIDATE_PARAMETERS = "tool.validate_parameters"

    # LLM 相关
    LLM_BEFORE_REQUEST = "llm.before_request"
    LLM_AFTER_RESPONSE = "llm.after_response"
    LLM_ON_ERROR = "llm.on_error"

    # 会话相关
    SESSION_CREATED = "session.created"
    SESSION_CLOSED = "session.closed"
    SESSION_COMPACTED = "session.compacted"

    # 技能/插件
    SKILL_DISCOVERED = "skill.discovered"
    PLUGIN_LOADED = "plugin.loaded"


@dataclass
class HookContext:
    """Hook 执行上下文"""
    hook_name: str
    plugin_id: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HookRegistration:
    """Hook 注册信息"""
    plugin_id: str
    hook_name: str
    callback: Callable  # async def callback(context: HookContext, data: Any) -> Any
    timeout_seconds: float = 30.0
    enabled: bool = True
    created_at: float = field(default_factory=time.time)


class HookManager:
    """
    Hook 管理器。

    负责：
    1. 注册/注销 Hook 回调
    2. 按顺序触发 Hook
    3. 隔离执行（单个 Hook 失败不影响其他）
    4. 超时控制
    """

    def __init__(self):
        # Hook 注册表：hook_name -> [HookRegistration]
        self._hooks: Dict[str, List[HookRegistration]] = {}
        # 插件注册的 Hook 映射：plugin_id -> [hook_name]
        self._plugin_hooks: Dict[str, Set[str]] = {}

    def register(
        self,
        plugin_id: str,
        hook_name: str,
        callback: Callable,
        timeout_seconds: float = 30.0,
    ) -> HookRegistration:
        """
        注册 Hook 回调。

        Args:
            plugin_id: 插件标识
            hook_name: Hook 名称
            callback: 异步回调函数（必须是 async def 或返回 awaitable 的可调用对象）
            timeout_seconds: 超时时间（秒）

        Returns:
            HookRegistration 对象

        Raises:
            TypeError: callback 不是异步可调用对象
        """
        # 校验 callback 为异步可调用对象
        if not asyncio.iscoroutinefunction(callback):
            raise TypeError(
                f"Hook callback must be an async function, got {type(callback).__name__}. "
                f"Use `async def` to define hook callbacks."
            )

        if hook_name not in self._hooks:
            self._hooks[hook_name] = []

        # 检查是否已存在同插件的同 Hook
        existing = [
            reg for reg in self._hooks[hook_name] if reg.plugin_id == plugin_id
        ]
        if existing:
            logger.warning(f"插件 {plugin_id} 已注册 Hook {hook_name}，将被替换")
            self._hooks[hook_name] = [
                reg for reg in self._hooks[hook_name]
                if reg.plugin_id != plugin_id
            ]

        registration = HookRegistration(
            plugin_id=plugin_id,
            hook_name=hook_name,
            callback=callback,
            timeout_seconds=timeout_seconds,
        )
        self._hooks[hook_name].append(registration)

        # 追踪插件的 Hook 列表
        if plugin_id not in self._plugin_hooks:
            self._plugin_hooks[plugin_id] = set()
        self._plugin_hooks[plugin_id].add(hook_name)

        logger.debug(f"Hook 已注册: {plugin_id} -> {hook_name}")
        return registration

    def unregister_plugin(self, plugin_id: str) -> int:
        """
        注销指定插件的所有 Hook。

        Args:
            plugin_id: 插件标识

        Returns:
            注销的 Hook 数量
        """
        hook_names = self._plugin_hooks.pop(plugin_id, set())
        count = 0
        for hook_name in hook_names:
            if hook_name in self._hooks:
                before = len(self._hooks[hook_name])
                self._hooks[hook_name] = [
                    reg for reg in self._hooks[hook_name]
                    if reg.plugin_id != plugin_id
                ]
                count += before - len(self._hooks[hook_name])
                if not self._hooks[hook_name]:
                    del self._hooks[hook_name]

        if count > 0:
            logger.info(f"已注销插件 {plugin_id} 的 {count} 个 Hook")
        return count

    def unregister(self, hook_name: str, plugin_id: str) -> bool:
        """
        注销指定的 Hook 注册。

        Args:
            hook_name: Hook 名称
            plugin_id: 插件标识

        Returns:
            是否成功注销
        """
        if hook_name not in self._hooks:
            return False

        before = len(self._hooks[hook_name])
        self._hooks[hook_name] = [
            reg for reg in self._hooks[hook_name]
            if reg.plugin_id != plugin_id
        ]
        removed = before - len(self._hooks[hook_name])

        if hook_name in self._plugin_hooks.get(plugin_id, set()):
            self._plugin_hooks[plugin_id].discard(hook_name)

        return removed > 0

    async def trigger(
        self,
        hook_name: str,
        data: Any = None,
        context: Optional[HookContext] = None,
        default_timeout: float = 30.0,
    ) -> List[Any]:
        """
        触发 Hook。

        所有注册的回调按注册顺序依次执行，每个回调在隔离作用域中运行。
        单个回调失败不会影响其他回调的执行。

        Args:
            hook_name: Hook 名称
            data: 传递给回调的数据
            context: Hook 执行上下文
            default_timeout: 默认超时时间

        Returns:
            所有成功回调的返回值列表
        """
        registrations = self._hooks.get(hook_name, [])
        if not registrations:
            return []

        ctx = context or HookContext(hook_name=hook_name)
        results: List[Any] = []

        for reg in registrations:
            if not reg.enabled:
                continue

            timeout = reg.timeout_seconds or default_timeout
            try:
                result = await asyncio.wait_for(
                    reg.callback(ctx, data),
                    timeout=timeout,
                )
                results.append(result)
            except asyncio.TimeoutError:
                logger.warning(
                    f"Hook {hook_name} (插件: {reg.plugin_id}) 超时 ({timeout}s)"
                )
            except Exception as e:
                logger.error(
                    f"Hook {hook_name} (插件: {reg.plugin_id}) 执行异常: {e}"
                )

        return results

    async def trigger_chain(
        self,
        hook_name: str,
        data: Any = None,
        context: Optional[HookContext] = None,
    ) -> Any:
        """
        链式触发 Hook（数据经过每个 Hook 依次处理）。

        第一个 Hook 的返回值作为第二个 Hook 的输入，以此类推。

        Args:
            hook_name: Hook 名称
            data: 初始数据
            context: Hook 执行上下文

        Returns:
            经过所有 Hook 处理后的数据
        """
        registrations = self._hooks.get(hook_name, [])
        if not registrations:
            return data

        ctx = context or HookContext(hook_name=hook_name)
        current_data = data

        for reg in registrations:
            if not reg.enabled:
                continue

            timeout = reg.timeout_seconds or 30.0
            try:
                current_data = await asyncio.wait_for(
                    reg.callback(ctx, current_data),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"链式 Hook {hook_name} (插件: {reg.plugin_id}) 超时 ({timeout}s)"
                )
            except Exception as e:
                logger.error(
                    f"链式 Hook {hook_name} (插件: {reg.plugin_id}) 执行异常: {e}"
                )

        return current_data

    def get_registrations(self, hook_name: Optional[str] = None) -> Dict[str, List[HookRegistration]]:
        """获取 Hook 注册信息"""
        if hook_name:
            return {hook_name: self._hooks.get(hook_name, [])}
        return dict(self._hooks)

    def get_plugin_hooks(self, plugin_id: str) -> Set[str]:
        """获取指定插件注册的 Hook 列表"""
        return self._plugin_hooks.get(plugin_id, set())

    def clear(self) -> None:
        """清空所有 Hook 注册"""
        self._hooks.clear()
        self._plugin_hooks.clear()


# 全局 HookManager 实例
hook_manager = HookManager()

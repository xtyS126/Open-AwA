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


class HookResultType(str, Enum):
    """
    Hook 结果类型枚举。

    用于明确表达钩子对后续执行流程的决策意图，
    替代原先返回 bool/None 的隐式约定。
    """
    # 批准执行
    APPROVE = "approve"
    # 拒绝执行
    DENY = "deny"
    # 修改输入（携带 modified_input 字段）
    MODIFY_INPUT = "modify_input"
    # 修改输出（携带 modified_output 字段）
    MODIFY_OUTPUT = "modify_output"
    # 阻止后续链路继续执行
    PREVENT_CONTINUATION = "prevent_continuation"
    # 替换结果，跳过实际执行（携带 replace_result 字段）
    REPLACE_RESULT = "replace_result"
    # 错误（携带 error_message 字段）
    ERROR = "error"


# 钩子执行耗时告警阈值（毫秒），超过该值会记录 warning 日志
HOOK_TIMING_DISPLAY_THRESHOLD_MS = 500


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


@dataclass
class HookResult:
    """
    Hook 执行结果。

    每个钩子回调返回一个 HookResult，表达对后续流程的决策意图。
    不同 result_type 携带不同字段：
    - APPROVE: 无附加字段，表示放行
    - DENY: 可携带 reason 说明拒绝原因
    - MODIFY_INPUT: 携带 modified_input 用于覆盖原始输入
    - MODIFY_OUTPUT: 携带 modified_output 用于覆盖原始输出
    - PREVENT_CONTINUATION: 可携带 reason 说明阻止原因
    - REPLACE_RESULT: 携带 replace_result 跳过实际执行直接返回
    - ERROR: 携带 error_message 说明错误原因
    """
    result_type: HookResultType
    # 用于 MODIFY_INPUT：合并到原始输入的覆写字段
    modified_input: Optional[dict] = None
    # 用于 MODIFY_OUTPUT：替换原始输出的值
    modified_output: Optional[Any] = None
    # 用于 REPLACE_RESULT：跳过实际执行直接返回的结果
    replace_result: Optional[Any] = None
    # 用于 ERROR：错误信息
    error_message: Optional[str] = None
    # 说明原因（DENY/PREVENT_CONTINUATION/ERROR 等场景的补充说明）
    reason: Optional[str] = None


def _coerce_to_hook_result(raw: Any) -> HookResult:
    """
    将钩子回调的原始返回值转换为 HookResult。

    向后兼容策略：
    - HookResult 实例：原样返回
    - bool: True -> APPROVE, False -> DENY
    - None: -> APPROVE（默认放行）
    - dict: 尝试解析 result_type/decision 等字段，失败则视为 APPROVE 并把返回值放入 modified_output
    - 其他类型: 视为 APPROVE 并把返回值放入 modified_output（保留原始返回值供调用方使用）

    Args:
        raw: 钩子回调的原始返回值

    Returns:
        转换后的 HookResult 实例
    """
    if isinstance(raw, HookResult):
        return raw

    if raw is None:
        return HookResult(result_type=HookResultType.APPROVE)

    if isinstance(raw, bool):
        if raw:
            return HookResult(result_type=HookResultType.APPROVE)
        return HookResult(result_type=HookResultType.DENY, reason="钩子返回 False")

    if isinstance(raw, dict):
        # 兼容 dict 形式的返回值，尝试解析已知字段
        result_type_raw = raw.get("result_type")
        decision = raw.get("decision")
        if result_type_raw is not None:
            try:
                result_type = HookResultType(str(result_type_raw))
            except ValueError:
                result_type = HookResultType.APPROVE
            return HookResult(
                result_type=result_type,
                modified_input=raw.get("modified_input"),
                modified_output=raw.get("modified_output"),
                replace_result=raw.get("replace_result"),
                error_message=raw.get("error_message"),
                reason=raw.get("reason"),
            )
        if decision is not None:
            # 兼容 task_runtime.hook_dispatcher 的 decision 字段
            decision_str = str(decision).lower()
            if decision_str == "deny":
                return HookResult(
                    result_type=HookResultType.DENY,
                    reason=raw.get("reason", ""),
                    modified_input=raw.get("updated_input"),
                )
            if decision_str == "ask":
                return HookResult(
                    result_type=HookResultType.DENY,
                    reason=raw.get("reason", "钩子要求人工确认"),
                )
            # allow / defer 等视为 APPROVE
            return HookResult(
                result_type=HookResultType.APPROVE,
                modified_input=raw.get("updated_input"),
            )
        # 无法识别的 dict，视为 APPROVE 并保留原始返回值
        return HookResult(result_type=HookResultType.APPROVE, modified_output=raw)

    # 其他类型（字符串、数字等）：视为 APPROVE 并保留原始返回值
    return HookResult(result_type=HookResultType.APPROVE, modified_output=raw)


def hook_updated_input(results: List[HookResult], original_input: dict) -> dict:
    """
    合并所有 MODIFY_INPUT 类型钩子的 modified_input 到原始输入。

    合并策略：以 original_input 为基础，依次用每个 MODIFY_INPUT 结果的
    modified_input 进行浅合并（后者覆盖前者）。

    Args:
        results: 钩子结果列表
        original_input: 原始输入字典

    Returns:
        合并后的输入字典（新对象，不修改 original_input）
    """
    merged: Dict[str, Any] = dict(original_input)
    for result in results:
        if (
            result.result_type == HookResultType.MODIFY_INPUT
            and result.modified_input is not None
        ):
            merged.update(result.modified_input)
    return merged


def hook_updated_output(results: List[HookResult], original_output: Any) -> Any:
    """
    应用所有 MODIFY_OUTPUT 类型钩子的修改，返回最终输出。

    策略：遍历所有 MODIFY_INPUT 结果，最后一个非 None 的 modified_output 生效。
    若没有任何 MODIFY_OUTPUT 结果，返回 original_output。

    Args:
        results: 钩子结果列表
        original_output: 原始输出

    Returns:
        修改后的输出（若有 MODIFY_OUTPUT），否则原始输出
    """
    updated = original_output
    for result in results:
        if (
            result.result_type == HookResultType.MODIFY_OUTPUT
            and result.modified_output is not None
        ):
            updated = result.modified_output
    return updated


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
    ) -> List[HookResult]:
        """
        触发 Hook。

        所有注册的回调按注册顺序依次执行，每个回调在隔离作用域中运行。
        单个回调失败不会影响其他回调的执行。

        钩子回调的原始返回值会通过 _coerce_to_hook_result 转换为 HookResult，
        保持对 bool/None/dict 等旧式返回值的向后兼容。

        Args:
            hook_name: Hook 名称
            data: 传递给回调的数据
            context: Hook 执行上下文
            default_timeout: 默认超时时间

        Returns:
            所有成功回调的 HookResult 列表；无注册钩子时返回空列表
        """
        registrations = self._hooks.get(hook_name, [])
        if not registrations:
            return []

        ctx = context or HookContext(hook_name=hook_name)
        results: List[HookResult] = []

        for reg in registrations:
            if not reg.enabled:
                continue

            timeout = reg.timeout_seconds or default_timeout
            # 记录单个钩子执行耗时，超过阈值时记录 warning
            hook_start = time.perf_counter()
            try:
                raw_result = await asyncio.wait_for(
                    reg.callback(ctx, data),
                    timeout=timeout,
                )
                results.append(_coerce_to_hook_result(raw_result))
            except asyncio.TimeoutError:
                logger.warning(
                    f"Hook {hook_name} (插件: {reg.plugin_id}) 超时 ({timeout}s)"
                )
            except Exception as e:
                logger.error(
                    f"Hook {hook_name} (插件: {reg.plugin_id}) 执行异常: {e}"
                )

            elapsed_ms = int((time.perf_counter() - hook_start) * 1000)
            if elapsed_ms > HOOK_TIMING_DISPLAY_THRESHOLD_MS:
                logger.warning(
                    f"钩子 {hook_name} (插件: {reg.plugin_id}) 执行耗时 {elapsed_ms}ms"
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

"""
钩子调度器模块，管理 PreToolUse / PostToolUse / TaskCompleted / SubagentStop /
SubagentStart / TaskCreated / Stop 生命周期事件的注册与分发。
支持插件注册自定义钩子处理函数。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from loguru import logger

# 支持的钩子事件类型
HookEventType = str
HOOK_PRE_TOOL_USE: HookEventType = "pre_tool_use"
HOOK_POST_TOOL_USE: HookEventType = "post_tool_use"
HOOK_TASK_COMPLETED: HookEventType = "task_completed"
HOOK_SUBAGENT_START: HookEventType = "subagent_start"
HOOK_SUBAGENT_STOP: HookEventType = "subagent_stop"
HOOK_TASK_CREATED: HookEventType = "task_created"
HOOK_STOP: HookEventType = "stop"

# 钩子处理函数签名: async def handler(payload: dict) -> dict
HookHandler = Callable[[Dict[str, Any]], Any]


class HookResult:
    """钩子执行结果，包含决策与可选的消息覆写。"""

    def __init__(
        self,
        decision: str = "allow",  # allow / deny / ask / defer
        reason: str = "",
        updated_input: Optional[Dict[str, Any]] = None,
        additional_context: Optional[str] = None,
    ):
        self.decision = decision
        self.reason = reason
        self.updated_input = updated_input or {}
        self.additional_context = additional_context

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "updated_input": self.updated_input,
            "additional_context": self.additional_context,
        }


class HookDispatcher:
    """
    生命周期钩子调度器。

    事件类型：
    - pre_tool_use: 工具调用前触发，可阻止/修改调用
    - post_tool_use: 工具调用后触发，用于审计/脱敏
    - task_completed: 任务完成前触发，可强制质量门控
    - subagent_start: 子代理启动时触发，可注入附加上下文
    - subagent_stop: 子代理退出前触发，用于结果校验
    - task_created: 任务创建时触发，可校验命名/描述/依赖合法性
    - stop: 主线程停机前触发，用于完成度校验
    """

    def __init__(self):
        self._handlers: Dict[HookEventType, List[HookHandler]] = {
            HOOK_PRE_TOOL_USE: [],
            HOOK_POST_TOOL_USE: [],
            HOOK_TASK_COMPLETED: [],
            HOOK_SUBAGENT_START: [],
            HOOK_SUBAGENT_STOP: [],
            HOOK_TASK_CREATED: [],
            HOOK_STOP: [],
        }

    def register(self, event_type: HookEventType, handler: HookHandler) -> None:
        """注册一个钩子处理函数。handler 为 async def。"""
        if event_type not in self._handlers:
            logger.bind(module="task_runtime", event_type=event_type).warning(f"未知钩子事件类型: {event_type}")
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        logger.bind(
            module="task_runtime",
            event_type=event_type,
            handler_count=len(self._handlers[event_type]),
        ).debug(f"钩子已注册: {event_type}")

    def unregister(self, event_type: HookEventType, handler: HookHandler) -> None:
        """注销一个钩子处理函数。"""
        if event_type in self._handlers and handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)

    async def dispatch(self, event_type: HookEventType, payload: Dict[str, Any]) -> List[HookResult]:
        """按序分发事件给所有注册的处理器，返回所有结果。"""
        results: List[HookResult] = []
        handlers = self._handlers.get(event_type, [])
        if not handlers:
            return results

        for handler in handlers:
            try:
                result = await handler(payload)
                if isinstance(result, HookResult):
                    results.append(result)
                elif isinstance(result, dict):
                    results.append(HookResult(
                        decision=result.get("decision", "allow"),
                        reason=result.get("reason", ""),
                        updated_input=result.get("updated_input"),
                        additional_context=result.get("additional_context"),
                    ))
            except Exception as exc:
                logger.bind(
                    module="task_runtime",
                    event_type=event_type,
                    error=str(exc),
                ).warning(f"钩子处理异常: {event_type}")
                results.append(HookResult(decision="allow", reason=f"钩子异常已忽略: {str(exc)}"))

        return results

    def has_deny(self, results: List[HookResult]) -> Optional[HookResult]:
        """检查结果列表中是否存在 deny 决策。"""
        for r in results:
            if r.decision == "deny":
                return r
        return None

    def has_ask(self, results: List[HookResult]) -> Optional[HookResult]:
        """检查结果列表中是否存在 ask 决策。"""
        for r in results:
            if r.decision == "ask":
                return r
        return None

    def get_updated_input(self, results: List[HookResult]) -> Dict[str, Any]:
        """合并所有钩子的 input 覆写。"""
        merged = {}
        for r in results:
            if r.updated_input:
                merged.update(r.updated_input)
        return merged

    def get_additional_context(self, results: List[HookResult]) -> str:
        """收集所有钩子提供的附加上下文。"""
        parts = [r.additional_context for r in results if r.additional_context]
        return "\n".join(parts)


# 模块级单例
hook_dispatcher = HookDispatcher()

# -*- coding: utf-8 -*-
"""
ACP 托管客户端（Hosted Client）模块。

实现 ACP 协议中的回调接口（session_update / request_permission 等），将外部
ACP Agent 在子进程中产生的事件流转换为 Open-AwA 内部使用的 dict 事件，并通过
on_message 回调向上转发。同时负责挂起权限审批请求，等待用户在前端确认后恢复
Agent 执行。

本模块对外部 `acp` SDK 的依赖通过 try/except 优雅降级：
- SDK 可用时：使用真实的 acp.schema 类型进行 isinstance 分发
- SDK 缺失时：所有 schema 类置为 None，_safe_isinstance 辅助函数返回 False，
  session_update 中的所有事件分支被忽略。这是可接受的，因为没有 acp SDK 时
  根本不会有 ACP 事件流入。其它不依赖 SDK 类型的方法（如增量合并、权限挂起）
  仍可正常工作。

注意：本文件严禁修改 __init__.py / core.py / permissions.py / tool_adapter.py。
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, NoReturn, Optional

try:
    from acp import RequestError, session_notification
    from acp.contrib.session_state import SessionAccumulator, ToolCallView
    from acp.schema import (
        AgentMessageChunk,
        AgentPlanUpdate,
        AgentThoughtChunk,
        AvailableCommandsUpdate,
        CurrentModeUpdate,
        RequestPermissionResponse,
        ToolCallProgress,
        ToolCallStart,
        UserMessageChunk,
    )

    _ACP_AVAILABLE = True
except ImportError:
    _ACP_AVAILABLE = False
    # SDK 缺失时用占位对象避免运行时 NameError；isinstance 检查全部走 _safe_isinstance
    # 返回 False，事件被忽略。RequestError 需要可调用以构造异常实例。
    class RequestError(Exception):  # type: ignore[no-redef]
        """SDK 缺失时占位的 RequestError 异常类型。"""

        def __init__(self, *, code: int = 0, message: str = "") -> None:
            super().__init__(message)
            self.code = code
            self.message = message

    session_notification = None  # type: ignore[assignment]
    SessionAccumulator = None  # type: ignore[assignment]
    ToolCallView = None  # type: ignore[assignment]
    AgentMessageChunk = None  # type: ignore[assignment]
    AgentPlanUpdate = None  # type: ignore[assignment]
    AgentThoughtChunk = None  # type: ignore[assignment]
    AvailableCommandsUpdate = None  # type: ignore[assignment]
    CurrentModeUpdate = None  # type: ignore[assignment]
    RequestPermissionResponse = None  # type: ignore[assignment]
    ToolCallProgress = None  # type: ignore[assignment]
    ToolCallStart = None  # type: ignore[assignment]
    UserMessageChunk = None  # type: ignore[assignment]


from .core import ACPAgentConfig, SuspendedPermission
from .permissions import ACPPermissionAdapter


__all__ = ["ACPHostedClient", "MessageHandler"]

# 消息回调签名：(payload, is_last) -> Awaitable[None]
MessageHandler = Callable[[dict[str, Any], bool], Awaitable[None]]


def _safe_isinstance(obj: Any, cls: Any) -> bool:
    """安全 isinstance 检查，cls 为 None 时返回 False。

    当 acp SDK 未安装时，所有 schema 类被置为 None，原生 isinstance 会抛
    TypeError；本辅助函数在这种情况下返回 False，使 session_update 中的事件
    分支被静默忽略而非崩溃。

    Args:
        obj: 待检查对象。
        cls: 期望的类，可能为 None。

    Returns:
        cls 为 None 时返回 False；否则返回 isinstance(obj, cls) 结果。
    """
    if cls is None:
        return False
    try:
        return isinstance(obj, cls)
    except TypeError:
        return False


class ACPHostedClient:
    """ACP 托管客户端：实现 ACP 协议回调接口的适配器。

    负责：
    1. 将 ACP session_update 事件流分发为 dict 形式的 on_message 回调
    2. 累积 AgentMessageChunk 文本并按增量合并去重后转发
    3. 处理工具调用事件（ToolCallStart/ToolCallProgress）渲染为可读事件
    4. 挂起权限审批请求（request_permission），等待用户确认后通过
       resolve_permission 恢复执行

    当 acp SDK 缺失时仍可实例化与调用，但 session_update 中的事件分发逻辑
    会全部跳过（_safe_isinstance 返回 False），其它方法照常工作。

    Attributes:
        agent_name: 当前 Agent 的展示名。
        tool_parse_mode: 工具调用解析模式（来自 ACPAgentConfig）。
    """

    def __init__(
        self,
        *,
        agent_name: str,
        agent_config: ACPAgentConfig,
        cwd: str,
    ) -> None:
        """初始化 ACP 托管客户端。

        Args:
            agent_name: Agent 展示名，用于权限请求与日志上下文。
            agent_config: Agent 配置项，提供 tool_parse_mode 等参数。
            cwd: 当前工作目录，用于权限适配器的路径越权检测。
        """
        self.agent_name = agent_name
        self.tool_parse_mode = agent_config.tool_parse_mode
        self._permission_adapter = ACPPermissionAdapter(cwd=cwd)
        # SessionAccumulator 仅在 SDK 可用时可用；缺失时置为 None，
        # session_update 中相关分支会因 _safe_isinstance 失败而跳过。
        self._session_acc: Any = (
            SessionAccumulator() if _ACP_AVAILABLE and SessionAccumulator else None
        )
        self._on_message: Optional[MessageHandler] = None
        self._assistant_text: str = ""
        self._emitted_assistant_text: str = ""
        self._thinking_active: bool = False
        self._pending_permission: Optional[SuspendedPermission] = None
        self._permission_future: Optional[asyncio.Future[Any]] = None
        self._permission_requested: asyncio.Event = asyncio.Event()

    @property
    def pending_permission(self) -> Optional[SuspendedPermission]:
        """当前挂起的权限审批请求；无挂起时为 None。"""
        return self._pending_permission

    def update_cwd(self, cwd: str) -> None:
        """更新权限适配器绑定的工作目录。

        Args:
            cwd: 新的工作目录字符串。
        """
        self._permission_adapter = ACPPermissionAdapter(cwd=cwd)

    def start_prompt(self, on_message: MessageHandler) -> None:
        """开始一轮新的 prompt 处理，重置累积状态。

        Args:
            on_message: 事件回调函数。
        """
        self._on_message = on_message
        self._assistant_text = ""
        self._emitted_assistant_text = ""
        self._thinking_active = False
        self._pending_permission = None
        self._permission_requested.clear()
        if _ACP_AVAILABLE and SessionAccumulator is not None:
            self._session_acc = SessionAccumulator()

    def resume_prompt(self, on_message: MessageHandler) -> None:
        """权限审批完成后恢复 prompt 处理。

        仅重置回调与权限请求标记，保留已累积的 assistant_text 等状态。

        Args:
            on_message: 事件回调函数。
        """
        self._on_message = on_message
        self._permission_requested.clear()

    async def wait_for_permission_request(self) -> None:
        """阻塞直到 request_permission 被调用并发出挂起信号。

        用于上层在发起 prompt 后等待权限请求到来的场景。
        """
        await self._permission_requested.wait()

    def resolve_permission(self, option_id: str) -> None:
        """恢复被挂起的权限请求。

        通过 option_id 在挂起选项列表中查找匹配项，找到后 set_result 到挂起
        future，使 request_permission 协程继续执行。

        Args:
            option_id: 用户选择的选项 ID。

        Raises:
            ValueError: 无挂起的权限请求，或 option_id 不匹配任何选项。
        """
        if self._pending_permission is None or self._permission_future is None:
            raise ValueError("No pending ACP permission request.")

        selected_option = self._permission_adapter.resolve_option_by_id(
            self._pending_permission.options,
            option_id,
        )
        if selected_option is None:
            raise ValueError(
                "respond requires the exact selected permission option id "
                "from the provided options.",
            )

        if not self._permission_future.done():
            self._permission_future.set_result(
                self._permission_adapter.selected_response(selected_option),
            )

    async def request_permission(
        self,
        options: list[Any],
        session_id: str,
        tool_call: Any,
        **_: Any,
    ) -> Any:
        """处理 ACP 权限请求：构建挂起载体并等待用户响应。

        流程：
        1. flush 已累积的 assistant_text 增量
        2. 构建 SuspendedPermission 载体
        3. emit permission_request 事件给上层
        4. 命中硬阻断规则时直接返回 cancelled_response
        5. 否则挂起 future 等待 resolve_permission 调用

        Args:
            options: 可选的审批选项列表。
            session_id: 当前会话 ID（保留未使用）。
            tool_call: 原始工具调用对象。
            **_: 其他保留参数。

        Returns:
            acp.schema.RequestPermissionResponse 实例（或 dict 占位结构）。
        """
        _ = session_id
        await self.flush_assistant_text()

        suspended = self._permission_adapter.build_suspended_permission(
            agent=self.agent_name,
            tool_call=tool_call,
            options=options,
        )
        await self._emit_message(
            {
                "type": "permission_request",
                "title": suspended.summary or suspended.tool_name,
                "options": suspended.options,
                "tool_kind": suspended.tool_kind,
                "tool_name": suspended.tool_name,
            },
            True,
        )

        if self._permission_adapter.is_hard_blocked(tool_call):
            return self._permission_adapter.cancelled_response()

        self._pending_permission = suspended
        self._permission_requested.set()
        self._permission_future = asyncio.get_running_loop().create_future()
        try:
            return await self._permission_future
        finally:
            self._pending_permission = None
            self._permission_future = None
            self._permission_requested.clear()

    async def session_update(
        self,
        session_id: str,
        update: Any,
        **_: Any,
    ) -> None:
        """处理 ACP session_update 事件分发。

        根据 update 的实际类型路由到不同处理分支：
        - AgentMessageChunk → 累积到 _assistant_text（不立即 emit）
        - AgentThoughtChunk → 设置 _thinking_active=True
        - ToolCallStart/ToolCallProgress → 渲染为工具事件并 emit
        - CurrentModeUpdate/AgentPlanUpdate/AvailableCommandsUpdate/
          UserMessageChunk → 仅累积到 SessionAccumulator

        当 acp SDK 缺失时，所有 _safe_isinstance 检查均返回 False，
        update 走到最后无条件累积分支（仍尝试 apply，但 _session_acc 为 None
        时会被忽略）。

        Args:
            session_id: 当前会话 ID。
            update: ACP 事件对象。
            **_: 其他保留参数。
        """
        if _safe_isinstance(update, AgentMessageChunk):
            self._thinking_active = False
            await self._accumulate_assistant_content(update.content)
            return

        await self.flush_assistant_text()

        if _safe_isinstance(update, AgentThoughtChunk):
            self._thinking_active = True
            return

        self._thinking_active = False

        if _safe_isinstance(update, ToolCallStart) or _safe_isinstance(
            update,
            ToolCallProgress,
        ):
            snapshot = self._apply_session_notification(session_id, update)
            event = self._tool_event_from_state(
                update,
                self._get_tool_call_view(snapshot, update),
            )
            if event is not None:
                await self._emit_message(event, True)
            return

        if (
            _safe_isinstance(update, CurrentModeUpdate)
            or _safe_isinstance(update, AgentPlanUpdate)
            or _safe_isinstance(update, AvailableCommandsUpdate)
            or _safe_isinstance(update, UserMessageChunk)
        ):
            self._apply_session_notification(session_id, update)

    async def ext_method(
        self,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """处理 ACP 扩展方法请求（不支持时抛 RequestError）。

        Args:
            method: 扩展方法名。
            params: 方法参数。

        Raises:
            RequestError: 始终抛出，本客户端不支持任何扩展方法。
        """
        _ = params
        self._unsupported_method(method)

    async def ext_notification(
        self,
        method: str,
        params: dict[str, Any],
    ) -> None:
        """处理 ACP 扩展通知（不支持时抛 RequestError）。

        Args:
            method: 扩展通知名。
            params: 通知参数。

        Raises:
            RequestError: 始终抛出，本客户端不支持任何扩展通知。
        """
        _ = params
        self._unsupported_method(method)

    def _unsupported_method(self, method: str) -> NoReturn:
        """抛出"不支持的 ACP 扩展方法"异常。"""
        raise RequestError(
            code=-32601,
            message=f"Unsupported ACP extension method: {method}",
        )

    async def emit_permission_resolved(self) -> None:
        """emit 权限已解决的状态事件，提示恢复执行。"""
        await self._emit_message(
            {
                "type": "status",
                "status": "permission_resolved",
                "summary": "Permission resolved, resuming execution.",
            },
            True,
        )

    async def finish_prompt(self) -> Optional[dict[str, Any]]:
        """结束本轮 prompt 处理，flush 残留文本并返回最终事件。

        Returns:
            若 _assistant_text 非空则返回形如
            {"type": "text", "text": ..., "is_chunk": False} 的事件 dict；
            否则返回 None。
        """
        await self.flush_assistant_text()
        if self._assistant_text:
            return {
                "type": "text",
                "text": self._assistant_text,
                "is_chunk": False,
            }
        return None

    async def flush_assistant_text(self) -> None:
        """flush 当前累积的 assistant_text 增量。

        将自上次 emit 以来新增的文本片段作为 delta 事件转发。无新增时不 emit。
        """
        await self._emit_assistant_text_delta()

    async def _emit_message(
        self,
        payload: dict[str, Any],
        is_last: bool,
    ) -> None:
        """转发事件 payload 给 on_message 回调；回调未设置时静默返回。

        Args:
            payload: 事件 dict。
            is_last: 是否为最后一帧标记。
        """
        if self._on_message is None:
            return
        await self._on_message(payload, is_last)

    async def _accumulate_assistant_content(self, content: Any) -> None:
        """提取 content 中的文本并合并到 _assistant_text。

        Args:
            content: AgentMessageChunk.content 字段，可为 str/list/dict/对象。
        """
        text = self._extract_text_from_content(content)
        if not text:
            return
        self._merge_assistant_text(text)

    async def _emit_assistant_text_delta(self) -> None:
        """计算并 emit _assistant_text 相对 _emitted_assistant_text 的增量。

        无文本、无新增或增量为空时均不 emit。
        """
        if not self._assistant_text:
            return
        if self._assistant_text == self._emitted_assistant_text:
            return
        delta = self._assistant_text[len(self._emitted_assistant_text) :]
        if not delta:
            return
        self._emitted_assistant_text = self._assistant_text
        await self._emit_message(
            {"type": "text", "text": delta, "is_chunk": False},
            False,
        )

    def _merge_assistant_text(self, text: str) -> None:
        """将新文本片段合并到 _assistant_text，处理重复/前缀/重叠/无重叠四种情况。

        合并策略：
        1. text 为空 → 忽略
        2. text 完全等于已累积文本 → 忽略（去重）
        3. 已累积为空 → 直接赋值
        4. text 以已累积文本为前缀 → 用 text 替换（覆盖式更新）
        5. 已累积文本末尾与新文本开头存在最大重叠 → 拼接去重部分
        6. 无重叠 → 直接追加

        Args:
            text: 新到达的文本片段。
        """
        if not text:
            return
        if text == self._assistant_text:
            return
        if not self._assistant_text:
            self._assistant_text = text
            return
        if text.startswith(self._assistant_text):
            self._assistant_text = text
            return

        max_overlap = min(len(self._assistant_text), len(text))
        for size in range(max_overlap, 0, -1):
            if self._assistant_text.endswith(text[:size]):
                self._assistant_text = self._assistant_text + text[size:]
                return
        self._assistant_text = self._assistant_text + text

    def _extract_text_from_content(self, content: Any) -> str:
        """从 AgentMessageChunk.content 中提取纯文本。

        支持的 content 形态：
        - 对象含 text 字段（str）：返回 text
        - 对象含 name 或 uri：返回 name 或 uri
        - 对象含 resource 字段：递归提取 resource.text / resource.blob
        - list：递归提取每个 item 后拼接
        - dict：type=text 时返回 text 字段
        - 其它：返回空串

        Args:
            content: 原始 content 值。

        Returns:
            提取出的纯文本字符串；无法识别时返回空串。
        """
        # pylint: disable=too-many-return-statements
        if hasattr(content, "text") and isinstance(
            getattr(content, "text", None),
            str,
        ):
            return str(content.text)
        if hasattr(content, "name") and hasattr(content, "uri"):
            return str(
                getattr(content, "name", None)
                or getattr(content, "uri", None)
                or "",
            )
        if hasattr(content, "resource"):
            resource = getattr(content, "resource", None)
            if resource is not None:
                text = getattr(resource, "text", None)
                if isinstance(text, str) and text:
                    return text
                blob = getattr(resource, "blob", None)
                if isinstance(blob, str) and blob:
                    return blob
            return ""
        if isinstance(content, list):
            parts = [self._extract_text_from_content(item) for item in content]
            return "".join(part for part in parts if part)
        if isinstance(content, dict):
            if content.get("type") == "text" and isinstance(
                content.get("text"),
                str,
            ):
                return str(content["text"])
            return ""
        return ""

    def _apply_session_notification(self, session_id: str, update: Any) -> Any:
        """将 session_notification 应用到 _session_acc 并返回 snapshot。

        SDK 缺失或 _session_acc 为 None 时返回 None，调用方需处理。

        Args:
            session_id: 当前会话 ID。
            update: 原始事件对象。

        Returns:
            SessionAccumulator.apply 的返回值（snapshot），或 None。
        """
        if (
            not _ACP_AVAILABLE
            or self._session_acc is None
            or session_notification is None
        ):
            return None
        return self._session_acc.apply(session_notification(session_id, update))

    def _get_tool_call_view(self, snapshot: Any, update: Any) -> Any:
        """从 snapshot 中取出 update 对应 tool_call_id 的 ToolCallView。

        Args:
            snapshot: SessionAccumulator.apply 返回的 snapshot 对象。
            update: 原始事件对象，含 tool_call_id 字段。

        Returns:
            ToolCallView 实例，或 None。
        """
        if snapshot is None:
            return None
        tool_calls = getattr(snapshot, "tool_calls", None) or {}
        if not isinstance(tool_calls, dict):
            return None
        call_id = getattr(update, "tool_call_id", None)
        if call_id is None:
            return None
        return tool_calls.get(call_id)

    def _tool_event_from_state(
        self,
        update: Any,
        state: Any,
    ) -> Optional[dict[str, Any]]:
        """根据 update 与 SessionAccumulator 的 state 渲染工具事件 dict。

        Args:
            update: ToolCallStart 或 ToolCallProgress 事件对象。
            state: 对应 tool_call_id 的 ToolCallView 快照，可为 None。

        Returns:
            形如 {"type": "tool_start"/"tool_end"/"tool_update", ...} 的事件
            dict；缺少 tool_call_id 时返回 None。
        """
        call_id = str(getattr(update, "tool_call_id", "") or "")
        if not call_id:
            return None

        title = (
            self._string_value(getattr(state, "title", None))
            or self._string_value(getattr(update, "title", None))
            or "unknown"
        )
        kind = (
            self._string_value(getattr(state, "kind", None))
            or self._string_value(getattr(update, "kind", None))
            or "other"
        )
        status = str(
            getattr(state, "status", None)
            or getattr(update, "status", None)
            or "pending",
        )
        target = self._tool_target(state, update)
        detail = self._tool_detail(kind, title, state, update) or title
        summary = self._stringify_summary(
            getattr(state, "raw_output", None),
        ) or self._stringify_summary(getattr(update, "raw_output", None))

        event: dict[str, Any] = {
            "type": self._tool_event_type(update, state),
            "name": title,
            "call_id": call_id,
            "title": title,
            "kind": kind,
            "status": status,
        }
        if detail:
            event["detail"] = detail
        if target:
            event["target"] = target
        if summary:
            event["summary"] = summary
        return event

    def _tool_event_type(self, update: Any, state: Any) -> str:
        """决定工具事件类型：tool_start / tool_end / tool_update。

        - ToolCallStart 或 tool_parse_mode == "call_title" → tool_start
        - 状态为 completed/failed → tool_end
        - 其它 → tool_update

        Args:
            update: 原始事件对象。
            state: ToolCallView 快照。

        Returns:
            事件类型字符串。
        """
        if (
            _safe_isinstance(update, ToolCallStart)
            or self.tool_parse_mode == "call_title"
        ):
            return "tool_start"
        status = str(
            getattr(state, "status", None)
            or getattr(update, "status", None)
            or "pending",
        )
        if status in {"completed", "failed"}:
            return "tool_end"
        return "tool_update"

    def _tool_detail(
        self,
        kind: str,
        title: str,
        state: Any,
        update: Any,
    ) -> Optional[str]:
        """根据 kind 与 tool_parse_mode 决定工具事件 detail 字段。

        Args:
            kind: 工具类别（execute/read/search/edit/other）。
            title: 工具标题。
            state: ToolCallView 快照。
            update: 原始事件对象。

        Returns:
            detail 字符串，或 None。
        """
        target = self._tool_target(state, update)
        if self.tool_parse_mode == "call_title":
            return title
        if kind == "execute":
            return self._tool_input_text(state, update, "command") or title
        if kind == "read":
            return (
                self._tool_input_text(
                    state,
                    update,
                    "file_path",
                    "filePath",
                    "path",
                )
                or target
                or title
            )
        if kind == "search":
            return (
                self._tool_input_text(state, update, "path", "pattern")
                or target
                or title
            )
        if kind == "edit":
            return title or target
        return title

    def _tool_target(
        self,
        state: Any,
        update: Any,
    ) -> Optional[str]:
        """从 state/update 的 locations 中提取目标路径。

        Args:
            state: ToolCallView 快照。
            update: 原始事件对象。

        Returns:
            第一个非空 path 字符串，或 None。
        """
        locations = (
            getattr(state, "locations", None)
            or getattr(update, "locations", None)
            or []
        )
        for location in locations:
            path = getattr(location, "path", None)
            if path:
                return str(path)
            if isinstance(location, dict) and location.get("path"):
                return str(location["path"])
        return None

    def _tool_input_text(
        self,
        state: Any,
        update: Any,
        *keys: str,
    ) -> Optional[str]:
        """从 state/update 的 raw_input 中按指定 keys 顺序提取首个非空字符串值。

        Args:
            state: ToolCallView 快照。
            update: 原始事件对象。
            *keys: 候选字段名，按顺序匹配。

        Returns:
            首个非空值字符串，或 None。
        """
        raw_inputs = (
            getattr(state, "raw_input", None),
            getattr(update, "raw_input", None),
        )
        for raw_input in raw_inputs:
            if not isinstance(raw_input, dict):
                continue
            for key in keys:
                value = raw_input.get(key)
                if isinstance(value, list):
                    for item in reversed(value):
                        text = self._string_value(item)
                        if text:
                            return text
                else:
                    text = self._string_value(value)
                    if text:
                        return text
        return None

    def _string_value(self, value: Any) -> Optional[str]:
        """将任意值转换为去空白字符串；空时返回 None。"""
        text = str(value).strip() if value is not None else ""
        return text or None

    def _stringify_summary(self, value: Any) -> Optional[str]:
        """将 raw_output 等摘要值字符串化。

        str 类型直接 strip；其它类型 str() 转换；None 返回 None。

        Args:
            value: 原始值。

        Returns:
            字符串化的值，或 None。
        """
        if value is None:
            return None
        return (
            self._string_value(value) if isinstance(value, str) else str(value)
        )

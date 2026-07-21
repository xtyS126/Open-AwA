# -*- coding: utf-8 -*-
"""
ACP 工具调用响应适配器模块。

负责将 ACP 协议事件流转换为 Open-AwA 内部使用的工具响应结构（dict 等价形式），
替代对 agentscope SDK 中 TextBlock / ToolResponse 类型的依赖。

模块包含：
- 事件渲染函数：将各类 ACP 事件（text/tool_call/status/permission_request/error）
  渲染为可读字符串
- 响应构造函数：将渲染结果组装为统一的 dict 响应结构

注意：本模块返回的 dict 结构形如：
  - 文本块：{"type": "text", "text": "..."}
  - 工具响应：{"content": [<文本块列表>], "stream": <bool>, "is_last": <bool>}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Tuple


__all__ = [
    "render_event_text",
    "response_blocks",
    "response_text",
    "format_stream_snapshot_response",
    "format_final_assistant_response",
    "format_permission_suspended_response",
    "format_close_response",
]


def _text_block(text: str) -> dict[str, str]:
    """构造文本块 dict。

    等价于 agentscope.message.TextBlock(type="text", text=text)。

    Args:
        text: 文本内容。

    Returns:
        形如 {"type": "text", "text": "..."} 的字典。
    """
    return {"type": "text", "text": text}


def response_blocks(
    blocks: list[dict[str, str]],
    *,
    stream: bool = False,
    is_last: bool = True,
) -> dict[str, Any]:
    """构造工具响应 dict。

    等价于 agentscope.tool.ToolResponse(content=blocks, stream=stream, is_last=is_last)。

    Args:
        blocks: 文本块列表。
        stream: 是否为流式响应片段。
        is_last: 是否为最后一帧。

    Returns:
        形如 {"content": [...], "stream": bool, "is_last": bool} 的字典。
    """
    return {"content": list(blocks), "stream": stream, "is_last": is_last}


def response_text(
    text: str,
    *,
    stream: bool = False,
    is_last: bool = True,
) -> dict[str, Any]:
    """构造单文本块的工具响应。

    Args:
        text: 文本内容。
        stream: 是否为流式响应片段。
        is_last: 是否为最后一帧。

    Returns:
        含单个文本块的工具响应 dict。
    """
    return response_blocks([_text_block(text)], stream=stream, is_last=is_last)


def _header_text(*, runner_name: str, execution_cwd: Path) -> str:
    """构造响应头部文本，标识 runner 与工作目录。

    Args:
        runner_name: runner 标识名称。
        execution_cwd: 执行工作目录。

    Returns:
        头部字符串。
    """
    return f"runner: {runner_name} working directory: {execution_cwd}"


def _string(value: Any) -> str:
    """将任意值转换为去除首尾空白的字符串。

    None / 空值 / 空字符串均返回空字符串。

    Args:
        value: 原始值。

    Returns:
        去除首尾空白后的字符串。
    """
    return str(value or "").strip()


def _option_parts(option: Any) -> Optional[Tuple[str, str]]:
    """从选项对象中提取展示名与选项 ID。

    兼容 dict 与对象两种结构，同时兼容 camelCase（optionId）与 snake_case（option_id）。

    Args:
        option: 选项对象（dict 或具备属性访问的对象）。

    Returns:
        (title, option_id) 二元组；title 为空时返回 None。
    """
    option_id = None
    title = None
    if isinstance(option, dict):
        option_id = _string(
            option.get("optionId")
            or option.get("option_id")
            or option.get("id"),
        )
        title = _string(option.get("title") or option.get("name"))
    else:
        option_id = _string(
            getattr(option, "option_id", None)
            or getattr(option, "optionId", None)
            or getattr(option, "id", None),
        )
        title = _string(
            getattr(option, "title", None) or getattr(option, "name", None),
        )
    title = title or option_id or "option"
    if not title:
        return None
    return title, option_id


def _render_text_event(event: dict[str, Any]) -> Optional[str]:
    """渲染文本事件为可读字符串。

    Args:
        event: 文本事件 dict，需含 text 字段。

    Returns:
        形如 "[assistant]\n{text}" 的字符串；text 为空时返回 None。
    """
    text = _string(event.get("text"))
    return f"[assistant]\n{text}" if text else None


def _render_tool_event(event: dict[str, Any]) -> Optional[str]:
    """渲染工具调用事件为可读字符串。

    Args:
        event: 工具调用事件 dict，需含 kind 与 detail/title 字段。

    Returns:
        形如 "[tool_call] {kind} ({detail})" 的字符串；kind 或 detail 缺失时返回 None。
    """
    kind = _string(event.get("kind"))
    detail = _string(event.get("detail") or event.get("title"))
    return f"[tool_call] {kind} ({detail})" if kind and detail else None


def _render_status_event(event: dict[str, Any]) -> Optional[str]:
    """渲染状态事件为可读字符串。

    分支：
    - status="run_finished" → 返回 None（事件可忽略）
    - status="agent_thinking" + summary → 返回 summary
    - 其他 status + summary → 返回 "[status] {status}\n{summary}"

    Args:
        event: 状态事件 dict。

    Returns:
        渲染后的字符串，或 None 表示事件可忽略。
    """
    status = _string(event.get("status")) or "unknown"
    if status == "run_finished":
        return None
    summary = _string(event.get("summary"))
    if status == "agent_thinking":
        return summary or "agent thinking..."
    return "\n".join(part for part in [f"[status] {status}", summary] if part)


def _render_permission_event(event: dict[str, Any]) -> str:
    """渲染权限请求事件为可读字符串。

    Args:
        event: 权限请求事件 dict，含 title/reason 与 options 列表。

    Returns:
        多行字符串，包含权限标题与选项列表（options 行缺失时省略）。
    """
    title = _string(
        event.get("title") or event.get("reason") or "permission request",
    )
    options = [
        f"{name} ({option_id})" if option_id else name
        for parts in (_option_parts(opt) for opt in event.get("options") or [])
        if parts
        for name, option_id in [parts]
    ]
    return "\n".join(
        part
        for part in [
            f"[permission_request] {title}",
            f"options: {', '.join(options)}" if options else "",
        ]
        if part
    )


def _render_error_event(event: dict[str, Any]) -> Optional[str]:
    """渲染错误事件为可读字符串。

    Args:
        event: 错误事件 dict，需含 message 字段。

    Returns:
        形如 "[error] {message}" 的字符串；message 为空或缺失时返回 None。
    """
    message_text = _string(event.get("message"))
    return f"[error] {message_text}" if message_text else None


def render_event_text(event: dict[str, Any]) -> Optional[str]:
    """主分发函数：根据事件 type 路由到对应的渲染函数。

    支持的事件类型：
    - text → _render_text_event
    - tool_* (前缀匹配，如 tool_call / tool_result) → _render_tool_event
    - status → _render_status_event
    - permission_request → _render_permission_event
    - error → _render_error_event
    - 其他未知类型 → None

    Args:
        event: ACP 事件 dict。

    Returns:
        渲染后的字符串，或 None 表示事件可忽略或类型未识别。
    """
    event_type = _string(event.get("type")).lower()
    if event_type == "text":
        return _render_text_event(event)
    if event_type.startswith("tool_"):
        return _render_tool_event(event)
    if event_type == "status":
        return _render_status_event(event)
    if event_type == "permission_request":
        return _render_permission_event(event)
    if event_type == "error":
        return _render_error_event(event)
    return None


def format_stream_snapshot_response(
    snapshot_items: list[str],
    *,
    runner_name: str,
    execution_cwd: Path,
    include_header: bool = False,
) -> Optional[dict[str, Any]]:
    """构造流式快照响应。

    将累积的快照文本列表组装为流式响应帧（stream=True, is_last=False）。
    runner_name、execution_cwd、include_header 参数为兼容性保留，当前不参与渲染。

    Args:
        snapshot_items: 快照文本列表。
        runner_name: runner 标识名称（保留，未使用）。
        execution_cwd: 执行工作目录（保留，未使用）。
        include_header: 是否包含头部（保留，未使用）。

    Returns:
        流式响应 dict；无有效文本块时返回 None。
    """
    del runner_name
    del execution_cwd
    del include_header
    blocks: list[dict[str, str]] = []
    for text in snapshot_items:
        cleaned = (text or "").strip()
        if cleaned:
            blocks.append(_text_block(cleaned))
    if not blocks:
        return None
    return response_blocks(blocks, stream=True, is_last=False)


def format_final_assistant_response(
    *,
    runner_name: str,
    execution_cwd: Path,
    final_event: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """构造最终助手响应。

    渲染 final_event 并附加头部信息，标记 is_last=True。final_event 为 None 或
    渲染结果为空时，body 回退为固定提示文本 "completed without text output"。

    Args:
        runner_name: runner 标识名称。
        execution_cwd: 执行工作目录。
        final_event: 最终事件 dict，可选。

    Returns:
        工具响应 dict，含头部块与 body 块两个文本块。
    """
    text = None
    if final_event is not None:
        text = render_event_text(final_event or {})
    body = text or "completed without text output"
    return response_blocks(
        [
            _text_block(
                _header_text(
                    runner_name=runner_name,
                    execution_cwd=execution_cwd,
                ),
            ),
            _text_block(body),
        ],
        is_last=True,
    )


def format_permission_suspended_response(
    *,
    suspended_permission: Any,
) -> dict[str, Any]:
    """构造权限挂起响应。

    将挂起的权限审批请求渲染为用户可读的提示文本，要求用户在确认选项前不得
    自行代为决策。响应文本包含 Agent / Tool / Action / Files / Target / Command /
    Summary 等元信息与可用选项列表。

    注意：原 QwenPaw 实现开头使用 emoji 标记，Open-AwA 规范严禁 emoji，
    此处改用纯文本标记 "[Permission]"。

    Args:
        suspended_permission: 被挂起的权限载体（SuspendedPermission 实例
            或具备等价属性的对象）。

    Returns:
        工具响应 dict。
    """
    agent = getattr(suspended_permission, "agent", "unknown")
    tool_name = getattr(
        suspended_permission,
        "tool_name",
        "external-agent",
    )
    tool_kind = getattr(suspended_permission, "tool_kind", "other")
    details = [
        f"- Agent: `{agent}`",
        f"- Tool: `{tool_name}` (kind: `{tool_kind}`)",
    ]
    action = getattr(suspended_permission, "action", None)
    if action:
        details.append(f"- Action: `{action}`")
    paths = list(getattr(suspended_permission, "paths", []) or [])
    if paths:
        details.append("- Files:")
        details.extend(f"  - `{path}`" for path in paths)
    else:
        target = getattr(suspended_permission, "target", None)
        if target:
            details.append(f"- Target: `{target}`")
    command = getattr(suspended_permission, "command", None)
    if command:
        details.append(f"- Command: `{command}`")
    summary = getattr(suspended_permission, "summary", None)
    if summary:
        details.append(f"- Summary: {summary}")

    options = [
        f"  - **{name}** (`{option_id}`)" if option_id else f"  - **{name}**"
        for parts in (
            _option_parts(opt)
            for opt in getattr(suspended_permission, "options", []) or []
        )
        if parts
        for name, option_id in [parts]
    ]

    intro = (
        "[Permission] External Agent Permission Request\n\n"
        "Do not make permission decisions on the user's behalf. "
        "Clearly present the permission details and available options, "
        "then ask the user for confirmation.\n\n"
    )
    reply_hint = (
        "\n\nReply with one exact option id using "
        '`delegate_external_agent(action="respond", runner=..., message=...)`.'
    )
    text = (
        intro
        + "\n".join(details)
        + ("\n\nOptions:\n" + "\n".join(options) if options else "")
        + reply_hint
    )
    return response_text(text)


def format_close_response(*, runner_name: str, closed: bool) -> dict[str, Any]:
    """构造关闭会话响应。

    Args:
        runner_name: runner 标识名称。
        closed: 是否成功关闭会话。True 表示已关闭，False 表示无绑定会话可关闭。

    Returns:
        工具响应 dict，含描述关闭结果的单文本块。
    """
    if closed:
        text = f"Closed the bound ACP session for runner '{runner_name}'."
    else:
        text = (
            "No bound ACP session found for runner "
            f"'{runner_name}' in the current chat."
        )
    return response_text(text)

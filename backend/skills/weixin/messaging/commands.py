"""
斜杠指令系统模块
提供指令解析、处理和分发功能
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

from loguru import logger


class CommandType(Enum):
    """指令类型枚举"""
    ECHO = "echo"
    TOGGLE_DEBUG = "toggle-debug"
    TASK = "task"


@dataclass
class SlashCommand:
    """
    斜杠指令数据类
    封装解析后的指令信息
    
    属性:
        command_type: 指令类型
        args: 指令参数字符串
        raw_text: 原始文本
        command_name: 指令名称（如 /echo）
    """
    command_type: CommandType
    args: str = ""
    raw_text: str = ""
    command_name: str = ""


@dataclass
class CommandContext:
    """
    指令执行上下文数据类
    封装指令执行所需的环境信息
    
    属性:
        account_id: 账号ID
        user_id: 用户ID
        from_user_id: 消息发送者ID
        context_token: 上下文令牌
        event_time: 事件时间戳
        is_authorized: 是否有权限执行指令
        debug_mode: 当前调试模式状态
        extra: 额外参数字典
    """
    account_id: str = ""
    user_id: str = ""
    from_user_id: str = ""
    context_token: str = ""
    event_time: float = 0.0
    is_authorized: bool = False
    debug_mode: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CommandResult:
    """
    指令执行结果数据类
    封装指令执行后的返回信息
    
    属性:
        success: 是否执行成功
        message: 返回消息
        data: 返回数据字典
        error: 错误信息
        timing: 耗时统计字典
    """
    success: bool = True
    message: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    timing: Dict[str, float] = field(default_factory=dict)


COMMAND_PREFIX = "/"

COMMAND_ALIASES: Dict[str, CommandType] = {
    "/echo": CommandType.ECHO,
    "/toggle-debug": CommandType.TOGGLE_DEBUG,
    "/toggle_debug": CommandType.TOGGLE_DEBUG,
    "/debug": CommandType.TOGGLE_DEBUG,
    "/task": CommandType.TASK,
    "/tasks": CommandType.TASK,
}

_debug_mode_store: Dict[str, bool] = {}

_task_store: Dict[str, Dict[str, Any]] = {}


def parse_command(text: str) -> Optional[SlashCommand]:
    """
    解析斜杠指令
    
    参数:
        text: 待解析的文本
        
    返回:
        SlashCommand实例，如果不是有效指令则返回None
    """
    if not text or not isinstance(text, str):
        return None
    
    text = text.strip()
    if not text.startswith(COMMAND_PREFIX):
        return None
    
    first_space = text.find(" ")
    if first_space == -1:
        command_name = text.lower()
        args = ""
    else:
        command_name = text[:first_space].lower()
        args = text[first_space + 1:].strip()
    
    command_type = COMMAND_ALIASES.get(command_name)
    if command_type is None:
        return None
    
    return SlashCommand(
        command_type=command_type,
        args=args,
        raw_text=text,
        command_name=command_name,
    )


def is_command(text: str) -> bool:
    """
    检查文本是否为斜杠指令
    
    参数:
        text: 待检查的文本
        
    返回:
        如果是有效指令则返回True，否则返回False
    """
    return parse_command(text) is not None


def check_command_permission(context: CommandContext) -> bool:
    """
    检查指令执行权限
    
    参数:
        context: 指令执行上下文
        
    返回:
        如果有权限则返回True，否则返回False
    """
    if not context.account_id or not context.from_user_id:
        return False
    
    return context.is_authorized


async def handle_echo(args: str, context: CommandContext) -> CommandResult:
    """
    处理 /echo 指令
    用于测试通道延迟，返回消息内容和耗时统计
    
    参数:
        args: 指令参数（要回显的内容）
        context: 指令执行上下文
        
    返回:
        CommandResult实例
    """
    start_time = time.time()
    
    if not check_command_permission(context):
        return CommandResult(
            success=False,
            message="",
            error="权限不足，无法执行此指令",
        )
    
    event_time_dt = datetime.fromtimestamp(context.event_time / 1000) if context.event_time > 0 else datetime.now()
    
    platform_to_plugin_delay = 0.0
    if context.event_time > 0:
        platform_to_plugin_delay = (start_time * 1000 - context.event_time)
    
    plugin_process_time = (time.time() - start_time) * 1000
    
    echo_content = args if args else "(无内容)"
    
    timing_lines = [
        "通道耗时统计:",
        f"  事件时间: {event_time_dt.isoformat()}",
        f"  平台->插件: {platform_to_plugin_delay:.1f}ms",
        f"  插件处理: {plugin_process_time:.1f}ms",
    ]
    
    result_message = f"{echo_content}\n\n" + "\n".join(timing_lines)
    
    return CommandResult(
        success=True,
        message=result_message,
        data={
            "echo_content": echo_content,
            "event_time": context.event_time,
        },
        timing={
            "platform_to_plugin_ms": platform_to_plugin_delay,
            "plugin_process_ms": plugin_process_time,
        },
    )


async def handle_toggle_debug(args: str, context: CommandContext) -> CommandResult:
    """
    处理 /toggle-debug 指令
    用于切换调试模式
    
    参数:
        args: 指令参数（可选：on/off）
        context: 指令执行上下文
        
    返回:
        CommandResult实例
    """
    if not check_command_permission(context):
        return CommandResult(
            success=False,
            message="",
            error="权限不足，无法执行此指令",
        )
    
    account_id = context.account_id
    current_mode = _debug_mode_store.get(account_id, False)
    
    args_lower = args.lower().strip()
    
    if args_lower == "on":
        new_mode = True
    elif args_lower == "off":
        new_mode = False
    else:
        new_mode = not current_mode
    
    _debug_mode_store[account_id] = new_mode
    
    status_text = "已开启" if new_mode else "已关闭"
    result_message = f"Debug 模式{status_text}"
    
    logger.info(f"账号 {account_id} 调试模式切换: {current_mode} -> {new_mode}")
    
    return CommandResult(
        success=True,
        message=result_message,
        data={
            "previous_mode": current_mode,
            "current_mode": new_mode,
        },
    )


async def handle_task(args: str, context: CommandContext) -> CommandResult:
    """
    处理 /task 指令
    用于异步任务管理（创建、查询状态）
    
    参数:
        args: 指令参数（create/status/list）
        context: 指令执行上下文
        
    返回:
        CommandResult实例
    """
    if not check_command_permission(context):
        return CommandResult(
            success=False,
            message="",
            error="权限不足，无法执行此指令",
        )
    
    parts = args.split(maxsplit=1) if args else []
    sub_command = parts[0].lower() if parts else "list"
    sub_args = parts[1] if len(parts) > 1 else ""
    
    if sub_command == "create":
        return await _handle_task_create(sub_args, context)
    elif sub_command == "status":
        return await _handle_task_status(sub_args, context)
    elif sub_command == "list":
        return await _handle_task_list(context)
    elif sub_command == "cancel":
        return await _handle_task_cancel(sub_args, context)
    else:
        return CommandResult(
            success=False,
            message="",
            error=f"未知的任务子指令: {sub_command}",
            data={"available_commands": ["create", "status", "list", "cancel"]},
        )


async def _handle_task_create(args: str, context: CommandContext) -> CommandResult:
    """
    处理任务创建子指令
    
    参数:
        args: 任务描述
        context: 指令执行上下文
        
    返回:
        CommandResult实例
    """
    task_id = f"task-{uuid.uuid4().hex[:8]}"
    created_at = time.time()
    
    task_info = {
        "task_id": task_id,
        "account_id": context.account_id,
        "user_id": context.from_user_id,
        "description": args or "未命名任务",
        "status": "pending",
        "created_at": created_at,
        "updated_at": created_at,
        "progress": 0,
    }
    
    _task_store[task_id] = task_info
    
    logger.info(f"创建任务: {task_id}, 描述: {args}")
    
    return CommandResult(
        success=True,
        message=f"任务已创建\n任务ID: {task_id}\n状态: pending\n描述: {args or '未命名任务'}",
        data=task_info,
    )


async def _handle_task_status(args: str, context: CommandContext) -> CommandResult:
    """
    处理任务状态查询子指令
    
    参数:
        args: 任务ID
        context: 指令执行上下文
        
    返回:
        CommandResult实例
    """
    task_id = args.strip()
    
    if not task_id:
        return CommandResult(
            success=False,
            message="",
            error="请提供任务ID",
        )
    
    task_info = _task_store.get(task_id)
    
    if not task_info:
        return CommandResult(
            success=False,
            message="",
            error=f"未找到任务: {task_id}",
        )
    
    if task_info["account_id"] != context.account_id:
        return CommandResult(
            success=False,
            message="",
            error="无权访问此任务",
        )
    
    status_lines = [
        f"任务ID: {task_id}",
        f"状态: {task_info['status']}",
        f"进度: {task_info['progress']}%",
        f"描述: {task_info['description']}",
        f"创建时间: {datetime.fromtimestamp(task_info['created_at']).isoformat()}",
    ]
    
    return CommandResult(
        success=True,
        message="\n".join(status_lines),
        data=task_info,
    )


async def _handle_task_list(context: CommandContext) -> CommandResult:
    """
    处理任务列表查询子指令
    
    参数:
        context: 指令执行上下文
        
    返回:
        CommandResult实例
    """
    user_tasks = [
        task for task in _task_store.values()
        if task["account_id"] == context.account_id
    ]
    
    if not user_tasks:
        return CommandResult(
            success=True,
            message="当前没有任务",
            data={"tasks": []},
        )
    
    task_lines = [f"共有 {len(user_tasks)} 个任务:"]
    for task in user_tasks:
        task_lines.append(
            f"  - {task['task_id']}: [{task['status']}] {task['description'][:30]}"
        )
    
    return CommandResult(
        success=True,
        message="\n".join(task_lines),
        data={"tasks": user_tasks},
    )


async def _handle_task_cancel(args: str, context: CommandContext) -> CommandResult:
    """
    处理任务取消子指令
    
    参数:
        args: 任务ID
        context: 指令执行上下文
        
    返回:
        CommandResult实例
    """
    task_id = args.strip()
    
    if not task_id:
        return CommandResult(
            success=False,
            message="",
            error="请提供任务ID",
        )
    
    task_info = _task_store.get(task_id)
    
    if not task_info:
        return CommandResult(
            success=False,
            message="",
            error=f"未找到任务: {task_id}",
        )
    
    if task_info["account_id"] != context.account_id:
        return CommandResult(
            success=False,
            message="",
            error="无权访问此任务",
        )
    
    if task_info["status"] in ("completed", "cancelled"):
        return CommandResult(
            success=False,
            message="",
            error=f"任务已{task_info['status']}，无法取消",
        )
    
    task_info["status"] = "cancelled"
    task_info["updated_at"] = time.time()
    
    logger.info(f"取消任务: {task_id}")
    
    return CommandResult(
        success=True,
        message=f"任务已取消: {task_id}",
        data=task_info,
    )


CommandHandler = Callable[[str, CommandContext], CommandResult]

_COMMAND_HANDLERS: Dict[CommandType, CommandHandler] = {
    CommandType.ECHO: handle_echo,
    CommandType.TOGGLE_DEBUG: handle_toggle_debug,
    CommandType.TASK: handle_task,
}


async def dispatch_command(command: SlashCommand, context: CommandContext) -> CommandResult:
    """
    分发指令到对应的处理器
    
    参数:
        command: 解析后的指令对象
        context: 指令执行上下文
        
    返回:
        CommandResult实例
    """
    handler = _COMMAND_HANDLERS.get(command.command_type)
    
    if handler is None:
        return CommandResult(
            success=False,
            message="",
            error=f"未实现的指令类型: {command.command_type.value}",
        )
    
    try:
        if asyncio.iscoroutinefunction(handler):
            result = await handler(command.args, context)
        else:
            result = handler(command.args, context)
        return result
    except Exception as e:
        logger.error(f"指令执行异常: {command.command_name}, 错误: {e}")
        return CommandResult(
            success=False,
            message="",
            error=f"指令执行异常: {str(e)}",
        )


def get_debug_mode(account_id: str) -> bool:
    """
    获取账号的调试模式状态
    
    参数:
        account_id: 账号ID
        
    返回:
        调试模式是否开启
    """
    return _debug_mode_store.get(account_id, False)


def set_debug_mode(account_id: str, mode: bool) -> None:
    """
    设置账号的调试模式状态
    
    参数:
        account_id: 账号ID
        mode: 调试模式状态
    """
    _debug_mode_store[account_id] = mode


def build_debug_timing_report(
    event_time: float,
    seq: int,
    msg_id: int,
    from_user: str,
    body: str,
    auth_result: Dict[str, bool],
    route_result: Dict[str, str],
    reply_text_len: int,
    deliver_time_ms: float,
    inbound_process_ms: float,
    ai_generate_ms: float,
) -> str:
    """
    构建调试模式的耗时报告
    
    参数:
        event_time: 事件时间戳
        seq: 消息序列号
        msg_id: 消息ID
        from_user: 发送者ID
        body: 消息体
        auth_result: 鉴权结果
        route_result: 路由结果
        reply_text_len: 回复文本长度
        deliver_time_ms: 发送耗时
        inbound_process_ms: 入站处理耗时
        ai_generate_ms: AI生成耗时
        
    返回:
        格式化的调试报告字符串
    """
    event_time_dt = datetime.fromtimestamp(event_time / 1000) if event_time > 0 else datetime.now()
    total_ms = deliver_time_ms + inbound_process_ms + ai_generate_ms
    
    lines = [
        "Debug 全链路",
        "-- 收消息 --",
        f"| seq={seq} msgId={msg_id} from={from_user}",
        f'| body="{body[:50]}..." (len={len(body)})' if len(body) > 50 else f'| body="{body}" (len={len(body)})',
        "-- 鉴权 & 路由 --",
        f"| auth: cmdAuthorized={auth_result.get('command_authorized', False)} senderAllowed={auth_result.get('sender_allowed', False)}",
        f"| route: agent={route_result.get('agent', 'unknown')} session={route_result.get('session', 'unknown')}",
        "-- 回复 --",
        f"| textLen={reply_text_len}",
        f"| deliver耗时: {deliver_time_ms:.1f}ms",
        "-- 耗时 --",
        f"| 入站处理(auth+route): {inbound_process_ms:.1f}ms",
        f"| AI生成+回复: {ai_generate_ms:.1f}ms",
        f"| 总耗时: {total_ms:.1f}ms",
        f"| eventTime: {event_time_dt.isoformat()}",
    ]
    
    return "\n".join(lines)


def clear_task_store() -> None:
    """
    清空任务存储（用于测试）
    """
    global _task_store
    _task_store = {}


def clear_debug_store() -> None:
    """
    清空调试模式存储（用于测试）
    """
    global _debug_mode_store
    _debug_mode_store = {}

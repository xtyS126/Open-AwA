# -*- coding: utf-8 -*-
"""
ACP 服务模块：生命周期管理。

提供 ACPService 类，封装 ACP Agent 子进程的拉起、会话管理、prompt 处理与权限审批
恢复等高层逻辑。同时提供模块级单例服务注册表（_acp_services）与 init/close/get
辅助函数，以及进程退出时的 atexit 清理回调。

本模块对外部 `acp` SDK 与 `psutil` 的依赖通过 try/except 优雅降级：
- SDK 可用时：使用真实的 spawn_agent_process / text_block / ClientCapabilities 等
- SDK 缺失时：相关方法（run_turn / resume_permission / _open_conversation 等）抛
  ACPConfigurationError("acp SDK not installed")，但状态管理方法（get_session /
  close_chat_session / cancel_turn 等）仍可正常工作
"""

from __future__ import annotations

import asyncio
import atexit
import os
import signal
import subprocess
import sys
import threading
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from loguru import logger

try:
    import psutil  # type: ignore[import-untyped]
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False
    psutil = None  # type: ignore[assignment]

try:
    from acp import PROTOCOL_VERSION, spawn_agent_process, text_block
    from acp.schema import ClientCapabilities, Implementation

    _ACP_AVAILABLE = True
except ImportError:
    _ACP_AVAILABLE = False
    PROTOCOL_VERSION = 0
    spawn_agent_process = None  # type: ignore[assignment]
    text_block = None  # type: ignore[assignment]
    ClientCapabilities = None  # type: ignore[assignment]
    Implementation = None  # type: ignore[assignment]


from .client import ACPHostedClient
from .core import (
    ACPAgentConfig,
    ACPConfigurationError,
    ACPConfig,
    ACPSessionError,
)


__all__ = [
    "ACPService",
    "MessageHandler",
    "init_acp_service",
    "close_acp_service",
    "get_acp_service",
]


# 消息回调签名：(payload, is_last) -> Awaitable[None]
MessageHandler = Callable[[dict[str, Any], bool], Awaitable[None]]


# 敏感环境变量键名（精确匹配，命中即过滤不传递给子进程）
_SENSITIVE_ENV_KEYS = {
    "SECRET_KEY", "JWT_SECRET_KEY", "CSRF_SECRET_KEY", "ENCRYPTION_KEY",
    "DATABASE_URL", "DATABASE_PASSWORD",
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
    "DEEPSEEK_API_KEY", "OPENAWA_API_KEY",
}

# 敏感环境变量子串（键名大写后包含任一即过滤）
_SENSITIVE_ENV_SUBSTRINGS = ("SECRET", "TOKEN", "PASSWORD", "API_KEY", "PRIVATE_KEY")


def _build_safe_env(agent_env: dict[str, str]) -> dict[str, str]:
    """构建安全的子进程环境变量，过滤敏感键避免泄露给 Agent 子进程。

    Agent 子进程（如 Claude Code、Codex）会执行用户指定的任意代码，
    可通过 env 命令或 /proc/self/environ 读取环境变量。
    本函数过滤掉含密钥的变量，仅保留运行所需的基础变量。

    Args:
        agent_env: agent 配置中显式声明的环境变量（优先级最高，覆盖父进程值）。

    Returns:
        过滤后的安全环境变量字典。
    """
    safe_env: dict[str, str] = {}
    for key, value in os.environ.items():
        # 精确匹配黑名单
        if key in _SENSITIVE_ENV_KEYS:
            continue
        # 子串匹配（键名大写后检查）
        key_upper = key.upper()
        if any(s in key_upper for s in _SENSITIVE_ENV_SUBSTRINGS):
            continue
        safe_env[key] = value

    # 应用 agent 配置的环境变量（覆盖优先级最高）
    safe_env.update(agent_env)

    # 确保必要的基础变量存在
    safe_env.setdefault("PATH", os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"))
    if "HOME" in os.environ:
        safe_env.setdefault("HOME", os.environ["HOME"])
    safe_env.setdefault("TERM", "xterm-256color")

    return safe_env


def _kill_process_tree_sync(pid: int) -> None:
    """递归 kill 进程树（跨平台，同步实现）。

    优先使用 psutil 遍历子进程并 kill；psutil 不可用时回退到 POSIX 的
    os.kill(SIGTERM) 或 Windows 的 taskkill 命令。pid 不存在或已退出时静默返回。

    PERF-08: 此函数使用 psutil 递归遍历进程树，可能阻塞事件循环数百毫秒。
    异步上下文应调用 _kill_process_tree 异步包装版本。

    Args:
        pid: 待 kill 的根进程 ID。
    """
    if _PSUTIL_AVAILABLE and psutil is not None:
        try:
            parent = psutil.Process(pid)
        except psutil.NoSuchProcess:  # type: ignore[union-attr]
            return
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.kill()
            except psutil.NoSuchProcess:  # type: ignore[union-attr]
                pass
        try:
            parent.kill()
        except psutil.NoSuchProcess:  # type: ignore[union-attr]
            pass
        return

    # psutil 不可用时的回退实现
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                check=False,
                capture_output=True,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass


async def _kill_process_tree(pid: int) -> None:
    """递归 kill 进程树的异步包装。

    PERF-08: psutil 递归遍历进程树是同步操作，可能阻塞事件循环数百毫秒。
    通过 asyncio.to_thread 将同步实现卸载到线程池，避免阻塞事件循环。
    同步上下文（如 atexit 回调）应直接调用 _kill_process_tree_sync。

    Args:
        pid: 待 kill 的根进程 ID。
    """
    await asyncio.to_thread(_kill_process_tree_sync, pid)


@dataclass
class _Conversation:
    """单个 ACP 会话的运行时上下文。

    封装从 spawn agent 进程到 prompt task 的全部可变状态。每个 (chat_id, agent)
    组合对应一个 _Conversation 实例，存储在 ACPService._sessions 字典中。

    Attributes:
        chat_id: 所属聊天会话 ID。
        agent: ACP Agent 标识。
        acp_session_id: ACP 协议分配的会话 ID。
        cwd: 当前工作目录。
        conn: ACP 连接对象（spawn_agent_process 返回）。
        process: 子进程对象。
        client: ACPHostedClient 实例。
        exit_stack: 资源清理栈。
        turn_lock: 单轮 prompt 串行化锁。
        prompt_task: 当前 prompt 异步任务，无则 None。
    """

    chat_id: str
    agent: str
    acp_session_id: str
    cwd: str
    conn: Any
    process: Any
    client: ACPHostedClient
    exit_stack: AsyncExitStack
    turn_lock: asyncio.Lock
    prompt_task: Optional[asyncio.Task[Any]] = None


class ACPService:
    """ACP 服务：管理 ACP Agent 子进程与会话生命周期。

    一个 ACPService 实例绑定一个 ACPConfig，按 (chat_id, agent) 维度维护多个
    _Conversation 会话。提供 run_turn 发起一轮 prompt、resume_permission 恢复
    挂起的权限审批、close_chat_session / close_all_sessions 清理会话等接口。
    """

    def __init__(self, *, config: ACPConfig) -> None:
        """初始化 ACP 服务。

        Args:
            config: ACP 子系统顶层配置。
        """
        self.config = config
        self._lock = asyncio.Lock()
        self._sessions: dict[tuple[str, str], _Conversation] = {}

    async def run_turn(
        self,
        *,
        chat_id: str,
        agent: str,
        prompt_blocks: list[dict[str, Any]],
        cwd: str,
        on_message: MessageHandler,
        restart: bool = False,
        require_existing: bool = False,
    ) -> dict[str, Any]:
        """发起一轮 ACP prompt 处理。

        流程：
        1. 若 restart=True，先关闭已存在的会话
        2. 获取或创建会话（require_existing=True 时强制要求已存在）
        3. 检查会话状态：不能有挂起的权限请求或未完成的 prompt
        4. 更新 cwd、start_prompt，创建 prompt_task
        5. 等待 prompt 完成或权限请求挂起

        Args:
            chat_id: 聊天会话 ID。
            agent: ACP Agent 标识。
            prompt_blocks: prompt 文本块列表，形如 [{"type": "text", "text": "..."}]。
            cwd: 工作目录。
            on_message: 事件回调。
            restart: 是否重启会话（先关闭再创建）。
            require_existing: 是否要求会话已存在。

        Returns:
            形如 {"status": "completed"/"permission_required", "event": ...,
            "suspended_permission": ...} 的结果字典。

        Raises:
            ACPConfigurationError: acp SDK 未安装。
            ACPSessionError: 会话状态非法（已有挂起权限或正在处理 prompt）。
        """
        if restart:
            await self.close_chat_session(chat_id=chat_id, agent=agent)

        conversation = await self._get_or_create_session(
            chat_id=chat_id,
            agent=agent,
            cwd=cwd,
            require_existing=require_existing,
        )
        async with conversation.turn_lock:
            if conversation.client.pending_permission is not None:
                raise ACPSessionError(
                    "Session "
                    f"{conversation.acp_session_id} is waiting for "
                    "permission",
                )
            if (
                conversation.prompt_task is not None
                and not conversation.prompt_task.done()
            ):
                raise ACPSessionError(
                    "Session "
                    f"{conversation.acp_session_id} is already "
                    "processing a turn",
                )

            conversation.cwd = cwd or conversation.cwd
            conversation.client.update_cwd(conversation.cwd)
            conversation.client.start_prompt(on_message)
            conversation.prompt_task = asyncio.create_task(
                conversation.conn.prompt(
                    session_id=conversation.acp_session_id,
                    prompt=self._prompt_blocks_to_models(prompt_blocks),
                ),
            )
            return await self._wait_for_prompt_outcome(
                conversation=conversation,
                on_message=on_message,
            )

    async def resume_permission(
        self,
        *,
        acp_session_id: str,
        option_id: str,
        on_message: MessageHandler,
    ) -> dict[str, Any]:
        """恢复被挂起的权限审批请求。

        通过 acp_session_id 找到对应会话，校验存在挂起的权限请求且 prompt_task
        仍在等待中，然后通过 client.resolve_permission 恢复执行。

        Args:
            acp_session_id: ACP 会话 ID。
            option_id: 用户选择的审批选项 ID。
            on_message: 事件回调。

        Returns:
            形如 {"status": "completed"/"permission_required", ...} 的结果字典。

        Raises:
            ACPConfigurationError: acp SDK 未安装。
            ACPSessionError: 会话不存在、无挂起权限或 prompt 未在等待恢复。
        """
        conversation = await self._find_session_by_acp_id(acp_session_id)
        if conversation is None:
            raise ACPSessionError(f"Session not found: {acp_session_id}")
        if conversation.client.pending_permission is None:
            raise ACPSessionError(
                f"Session {acp_session_id} has no pending permission request",
            )
        if conversation.prompt_task is None or conversation.prompt_task.done():
            raise ACPSessionError(
                f"Session {acp_session_id} is not awaiting permission resume",
            )

        async with conversation.turn_lock:
            conversation.client.resume_prompt(on_message)
            conversation.client.resolve_permission(option_id)
            await conversation.client.emit_permission_resolved()
            return await self._wait_for_prompt_outcome(
                conversation=conversation,
                on_message=on_message,
            )

    async def close_chat_session(self, *, chat_id: str, agent: str) -> None:
        """关闭指定 (chat_id, agent) 的会话。

        从 _sessions 字典中弹出会话并调用 _close_conversation 清理资源。
        会话不存在时静默返回。

        Args:
            chat_id: 聊天会话 ID。
            agent: ACP Agent 标识。
        """
        async with self._lock:
            conversation = self._sessions.pop((chat_id, agent), None)
        if conversation is not None:
            await self._close_conversation(conversation)

    async def close_all_sessions(self) -> None:
        """关闭所有会话并清空 _sessions 字典。"""
        async with self._lock:
            conversations = list(self._sessions.values())
            self._sessions.clear()
        for conversation in conversations:
            await self._close_conversation(conversation)

    async def get_session(
        self,
        chat_id: str,
        agent: str,
    ) -> Optional[_Conversation]:
        """按 (chat_id, agent) 获取已存在的会话。

        Args:
            chat_id: 聊天会话 ID。
            agent: ACP Agent 标识。

        Returns:
            _Conversation 实例；不存在时返回 None。
        """
        async with self._lock:
            return self._sessions.get((chat_id, agent))

    async def get_pending_permission(
        self,
        *,
        chat_id: str,
        agent: str,
    ) -> Any | None:
        """获取指定会话当前挂起的权限审批请求。

        Args:
            chat_id: 聊天会话 ID。
            agent: ACP Agent 标识。

        Returns:
            挂起的 SuspendedPermission 实例；无会话或无挂起时返回 None。
        """
        conversation = await self.get_session(chat_id, agent)
        if conversation is None:
            return None
        return conversation.client.pending_permission

    async def cancel_turn(self, *, chat_id: str, agent: str) -> bool:
        """取消指定会话当前正在进行的 prompt 任务。

        调用 conn.cancel 通知子进程取消，并通过 asyncio.wait_for +
        asyncio.shield 等待 prompt_task 结束（最多重试 3 次，每次 0.5s）。

        Args:
            chat_id: 聊天会话 ID。
            agent: ACP Agent 标识。

        Returns:
            True 表示 prompt_task 已结束（成功取消或自然完成）；False 表示
            会话不存在、无运行中的 prompt 或取消失败。
        """
        conversation = await self.get_session(chat_id, agent)
        if conversation is None:
            return False

        prompt_task = conversation.prompt_task
        if prompt_task is None or prompt_task.done():
            return False

        for _ in range(3):
            try:
                await conversation.conn.cancel(
                    session_id=conversation.acp_session_id,
                )
            except Exception as exc:
                logger.bind(
                    event="acp_cancel_failed",
                    chat_id=chat_id,
                    agent=agent,
                ).warning(f"ACP cancel 调用失败：{exc}", exc_info=exc)
                return False

            try:
                await asyncio.wait_for(
                    asyncio.shield(prompt_task),
                    timeout=0.5,
                )
            except asyncio.TimeoutError:
                if prompt_task.done():
                    break
                continue
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.bind(
                    event="acp_cancel_wait_failed",
                    chat_id=chat_id,
                    agent=agent,
                ).warning(f"ACP cancel 等待 prompt_task 时发生未预期异常：{exc}", exc_info=exc)
                break
            else:
                break

        return prompt_task.done()

    async def _get_or_create_session(
        self,
        *,
        chat_id: str,
        agent: str,
        cwd: str,
        require_existing: bool,
    ) -> _Conversation:
        """获取或创建 ACP 会话。

        流程：
        1. 校验 agent 配置存在且启用
        2. 若已存在会话且子进程仍存活，复用
        3. 若子进程已退出，关闭旧会话；require_existing=True 时抛异常
        4. require_existing=True 且无已存在会话时抛异常
        5. 调用 _open_conversation 启动新会话

        Args:
            chat_id: 聊天会话 ID。
            agent: ACP Agent 标识。
            cwd: 工作目录。
            require_existing: 是否要求会话已存在。

        Returns:
            _Conversation 实例。

        Raises:
            ACPConfigurationError: agent 配置缺失或禁用，或 acp SDK 未安装。
            ACPSessionError: require_existing=True 但会话不存在或已失效。
        """
        agent_config = self._get_agent_config(agent)
        async with self._lock:
            existing = self._sessions.get((chat_id, agent))

        if existing is not None:
            if existing.process.returncode is None:
                return existing
            await self.close_chat_session(chat_id=chat_id, agent=agent)
            if require_existing:
                raise ACPSessionError(
                    f"ACP session for runner '{agent}' is no longer "
                    "active; call start first",
                )
        elif require_existing:
            raise ACPSessionError(
                "no bound ACP session found for runner "
                f"'{agent}' in current chat",
            )

        session_cwd = cwd or "."
        conversation = await self._open_conversation(
            chat_id=chat_id,
            agent=agent,
            cwd=session_cwd,
            agent_config=agent_config,
        )

        async with self._lock:
            self._sessions[(chat_id, agent)] = conversation
        return conversation

    async def _find_session_by_acp_id(
        self,
        acp_session_id: str,
    ) -> Optional[_Conversation]:
        """按 acp_session_id 在所有会话中查找匹配项。

        Args:
            acp_session_id: ACP 协议分配的会话 ID。

        Returns:
            匹配的 _Conversation 实例；未找到时返回 None。
        """
        async with self._lock:
            for session in self._sessions.values():
                if session.acp_session_id == acp_session_id:
                    return session
        return None

    def _get_agent_config(self, agent: str) -> ACPAgentConfig:
        """获取指定 agent 的配置。

        Args:
            agent: ACP Agent 标识。

        Returns:
            ACPAgentConfig 实例。

        Raises:
            ACPConfigurationError: agent 配置缺失或未启用。
        """
        agent_config = self.config.agents.get(agent)
        if agent_config is None:
            raise ACPConfigurationError(
                f"Unknown ACP agent: {agent}",
                agent=agent,
            )
        if not agent_config.enabled:
            raise ACPConfigurationError(
                f"ACP agent '{agent}' is disabled",
                agent=agent,
            )
        return agent_config

    async def _open_conversation(
        self,
        *,
        chat_id: str,
        agent: str,
        cwd: str,
        agent_config: ACPAgentConfig,
    ) -> _Conversation:
        """启动新的 ACP 会话。

        通过 spawn_agent_process 拉起子进程，初始化协议握手并创建会话。
        任一步骤失败时清理 exit_stack 后向上抛出异常。

        Args:
            chat_id: 聊天会话 ID。
            agent: ACP Agent 标识。
            cwd: 工作目录。
            agent_config: Agent 配置项。

        Returns:
            _Conversation 实例。

        Raises:
            ACPConfigurationError: acp SDK 未安装。
            ACPSessionError: 协议版本不匹配或会话创建失败。
        """
        if not _ACP_AVAILABLE or spawn_agent_process is None:
            raise ACPConfigurationError("acp SDK not installed")

        client = ACPHostedClient(
            agent_name=agent,
            agent_config=agent_config,
            cwd=cwd,
        )
        exit_stack = AsyncExitStack()
        try:
            conn, process = await exit_stack.enter_async_context(
                spawn_agent_process(
                    client,
                    agent_config.command,
                    *agent_config.args,
                    cwd=cwd,
                    env=_build_safe_env(agent_config.env),
                    transport_kwargs={
                        "limit": agent_config.stdio_buffer_limit_bytes,
                    },
                ),
            )
            initialized = await conn.initialize(
                protocol_version=PROTOCOL_VERSION,
                capabilities=ClientCapabilities(),
                client_info=Implementation(
                    name="open-awa-acp-service",
                    version="0.1.0",
                ),
            )
            if initialized.protocol_version != PROTOCOL_VERSION:
                raise ACPSessionError(
                    f"Protocol mismatch: {initialized.protocol_version}",
                )
            new_session = await conn.new_session(cwd=cwd)
            return _Conversation(
                chat_id=chat_id,
                agent=agent,
                acp_session_id=new_session.session_id,
                cwd=cwd,
                conn=conn,
                process=process,
                client=client,
                exit_stack=exit_stack,
                turn_lock=asyncio.Lock(),
            )
        except Exception:
            await exit_stack.aclose()
            raise

    async def _wait_for_prompt_outcome(
        self,
        *,
        conversation: _Conversation,
        on_message: MessageHandler,
    ) -> dict[str, Any]:
        """等待 prompt_task 完成，处理权限挂起。

        并发等待 prompt_task 与权限请求事件，谁先完成谁触发后续分支：
        - 权限请求先到 -> 返回 permission_required 状态
        - prompt 先完成 -> 检查是否在期间产生权限请求，无则返回 completed

        Args:
            conversation: 当前会话上下文。
            on_message: 事件回调（保留参数，未来扩展用）。

        Returns:
            形如 {"status": "completed"/"permission_required", "event": ...,
            "suspended_permission": ...} 的结果字典。

        Raises:
            ACPSessionError: prompt_task 缺失或执行失败。
        """
        del on_message
        prompt_task = conversation.prompt_task
        if prompt_task is None:
            raise ACPSessionError("ACP prompt task is missing")

        permission_task = asyncio.create_task(
            conversation.client.wait_for_permission_request(),
        )
        try:
            done, _ = await asyncio.wait(
                {prompt_task, permission_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if (
                permission_task in done
                and conversation.client.pending_permission is not None
            ):
                finished_event = await conversation.client.finish_prompt()
                return {
                    "status": "permission_required",
                    "suspended_permission": (
                        conversation.client.pending_permission
                    ),
                    "event": finished_event,
                }

            permission_task.cancel()
            try:
                await permission_task
            except asyncio.CancelledError:
                pass

            try:
                await prompt_task
            except Exception as exc:
                conversation.prompt_task = None
                await conversation.client.finish_prompt()
                raise ACPSessionError(str(exc)) from exc

            conversation.prompt_task = None
            finished_event = await conversation.client.finish_prompt()
            pending_permission = conversation.client.pending_permission
            if pending_permission is not None:
                return {
                    "status": "permission_required",
                    "suspended_permission": pending_permission,
                    "event": finished_event,
                }
            return {"status": "completed", "event": finished_event}
        finally:
            if not permission_task.done():
                permission_task.cancel()
                try:
                    await permission_task
                except asyncio.CancelledError:
                    pass

    async def _close_conversation(self, conversation: _Conversation) -> None:
        """关闭单个会话并清理资源。

        流程：
        1. 取消未完成的 prompt_task
        2. 尝试调用 conn.close_session（5s 超时）
        3. _kill_process_tree 强制 kill 进程树
        4. 关闭 exit_stack

        Args:
            conversation: 待关闭的会话上下文。
        """
        try:
            if (
                conversation.prompt_task is not None
                and not conversation.prompt_task.done()
            ):
                conversation.prompt_task.cancel()
                try:
                    await conversation.prompt_task
                except Exception as exc:
                    # 取消任务自身抛异常被记录，便于诊断子进程清理问题
                    logger.debug(
                        "ACP prompt_task 取消时抛出异常（通常可忽略）",
                        exc_info=exc,
                    )
            # [Fix #4615] node wrapper 启动的子进程需要主动 close_session
            try:
                await asyncio.wait_for(
                    conversation.conn.close_session(
                        session_id=conversation.acp_session_id,
                    ),
                    timeout=5.0,
                )
            except Exception as exc:
                # close_session 失败可能掩盖子进程泄露，记录日志便于排查
                logger.warning(
                    "ACP close_session 失败，将强制 kill 进程树",
                    exc_info=exc,
                )
        finally:
            # [Fix #4615] 直接二进制启动的子进程需 kill 整个进程树防止泄露
            # PERF-08: 使用异步包装避免 psutil 同步遍历阻塞事件循环
            await _kill_process_tree(conversation.process.pid)
            await conversation.exit_stack.aclose()

    @staticmethod
    def _prompt_blocks_to_models(blocks: list[dict[str, Any]]) -> list[Any]:
        """将 prompt 文本块列表转换为 acp SDK 的 Block 模型列表。

        Args:
            blocks: 形如 [{"type": "text", "text": "..."}] 的字典列表。

        Returns:
            acp.text_block 生成的 Block 模型列表。

        Raises:
            ACPConfigurationError: 包含非 text 类型块或 acp SDK 未安装。
        """
        if not _ACP_AVAILABLE or text_block is None:
            raise ACPConfigurationError("acp SDK not installed")
        prompt_models: list[Any] = []
        for block in blocks:
            if block.get("type") != "text":
                raise ACPConfigurationError(
                    "Only text prompt blocks are currently supported",
                )
            prompt_models.append(text_block(str(block.get("text", ""))))
        return prompt_models


# 模块级单例服务注册表：按 agent_id 索引 ACPService 实例
# 并发安全：使用 threading.Lock 保护 check-then-set，防止并发注册导致旧 service 资源泄露
_acp_services: dict[str, ACPService] = {}
_acp_services_lock = threading.Lock()


def get_acp_service(agent_id: Optional[str] = None) -> Optional[ACPService]:
    """按 agent_id 获取已注册的 ACPService 实例。

    Args:
        agent_id: Agent 标识；为 None 时始终返回 None。

    Returns:
        已注册的 ACPService 实例；未注册时返回 None。
    """
    if agent_id is None:
        return None
    with _acp_services_lock:
        return _acp_services.get(agent_id)


def init_acp_service(agent_id: str, config: ACPConfig) -> ACPService:
    """初始化并注册 ACPService 实例。

    若该 agent_id 已注册过旧 service，会尝试在合适的事件循环中关闭其全部会话。
    新 service 替换旧实例后返回。

    Args:
        agent_id: Agent 标识。
        config: ACP 子系统顶层配置。

    Returns:
        新创建并注册的 ACPService 实例。
    """
    # 加锁保护 check-then-set，防止并发注册丢失 previous_service 引用导致资源泄露
    with _acp_services_lock:
        previous_service = _acp_services.get(agent_id)
        new_service = ACPService(config=config)
        _acp_services[agent_id] = new_service
    if previous_service is not None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = None
        if loop is not None and not loop.is_closed():
            if loop.is_running():
                loop.create_task(previous_service.close_all_sessions())
            else:
                loop.run_until_complete(previous_service.close_all_sessions())
    return new_service


def close_acp_service(agent_id: str) -> None:
    """关闭并移除已注册的 ACPService 实例。

    从 _acp_services 字典中弹出 service，并在合适的事件循环中关闭其全部会话。
    未注册的 agent_id 静默返回。

    Args:
        agent_id: Agent 标识。
    """
    with _acp_services_lock:
        previous_service = _acp_services.pop(agent_id, None)
    if previous_service is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
    if loop is not None and not loop.is_closed():
        if loop.is_running():
            loop.create_task(previous_service.close_all_sessions())
        else:
            loop.run_until_complete(previous_service.close_all_sessions())


def _shutdown_acp_services() -> None:
    """atexit 回调：关闭全部已注册的 ACPService。

    进程退出时遍历 _acp_services 中所有 service 并并发关闭其会话。
    若当前无运行中的事件循环，则新建临时 loop 执行清理。
    """
    with _acp_services_lock:
        services = list(_acp_services.values())
        _acp_services.clear()
    if not services:
        return
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            for service in services:
                loop.create_task(service.close_all_sessions())
            return
    except RuntimeError:
        pass
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            asyncio.gather(
                *(service.close_all_sessions() for service in services),
            ),
        )
        loop.close()
    except Exception as exc:
        # atexit 期间 stderr 仍可用，记录异常避免进程退出阶段问题完全不可见
        sys.stderr.write(f"[ACP shutdown] atexit 关闭服务失败: {exc}\n")


atexit.register(_shutdown_acp_services)

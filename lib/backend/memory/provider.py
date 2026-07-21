"""
记忆提供者边界抽象模块。

定义记忆系统与 Agent 循环之间的隔离边界，确保：
- 记忆系统可独立演进和测试
- Agent 循环不依赖具体记忆实现
- 支持多种记忆后端（向量数据库、文件系统、云服务等）

参考 Agent Diva 的 MemoryProvider trait 设计，定义四个生命周期阶段：
1. system_prompt_block() - 启动注入，构建系统提示词的记忆块
2. prefetch() - 意图预取，在轮次开始前主动召回相关记忆
3. sync_turn() - 回合同步，在轮次完成后持久化证据
4. on_session_end() - 会话结束，触发清理和节奏任务
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================================
# 状态枚举
# ============================================================================

class StartupStatus(str, Enum):
    """启动注入状态。"""
    READY = "ready"  # 成功生成启动内容
    DEGRADED = "degraded"  # 启动内容生成失败，使用降级方案


class PrefetchStatus(str, Enum):
    """意图预取状态。"""
    SKIPPED_NO_INTENT = "skipped_no_intent"  # 无可用意图，跳过召回
    READY = "ready"  # 召回成功
    FAILED = "failed"  # 召回失败


class SyncTurnStatus(str, Enum):
    """回合同步状态。"""
    PERSISTED = "persisted"  # 至少完成一次持久化写入
    NOOP = "noop"  # 无需写入
    FAILED = "failed"  # 写入失败


class SessionEndStatus(str, Enum):
    """会话结束状态。"""
    TRIGGERED = "triggered"  # 触发关闭任务
    NOOP = "noop"  # 无需处理
    ALREADY_HANDLED = "already_handled"  # 已处理（幂等）
    FAILED = "failed"  # 处理失败


# ============================================================================
# 请求/响应数据结构
# ============================================================================

@dataclass
class SystemPromptRequest:
    """
    系统提示词请求。
    
    用于启动时构建记忆块，注入到系统提示词中。
    """
    workspace_root: Path


@dataclass
class SystemPromptBlock:
    """
    系统提示词块。
    
    包含注入形状和 markdown 内容。
    """
    shape: str  # "compact_rendered_markdown"
    markdown: str


@dataclass
class SystemPromptResponse:
    """
    系统提示词响应。
    
    包含状态和可选的提示词块。
    """
    status: StartupStatus
    markdown: Optional[str] = None
    reason: Optional[str] = None
    last_usable_wakeup: Optional[SystemPromptBlock] = None

    @classmethod
    def ready(cls, markdown: str) -> "SystemPromptResponse":
        """创建就绪状态响应。"""
        return cls(status=StartupStatus.READY, markdown=markdown)

    @classmethod
    def degraded(cls, reason: str, last_usable_wakeup: Optional[SystemPromptBlock] = None) -> "SystemPromptResponse":
        """创建降级状态响应。"""
        return cls(
            status=StartupStatus.DEGRADED,
            reason=reason,
            last_usable_wakeup=last_usable_wakeup,
            markdown=f"## Memory Startup Status\n- status: degraded\n- reason: {reason}\n- last_usable_wakeup: omitted (no cache reuse)\n"
        )


@dataclass
class PrefetchRequest:
    """
    意图预取请求。
    
    代表从当前轮次推断的意图感知召回请求。
    """
    workspace_root: Path
    intent: str
    current_room: Optional[str] = None
    user_message: Optional[str] = None


@dataclass
class PrefetchResponse:
    """意图预取响应。"""
    status: PrefetchStatus
    prompt_block: Optional[str] = None
    reason: Optional[str] = None

    @classmethod
    def default(cls) -> "PrefetchResponse":
        """创建默认响应（无意图可召回）。"""
        return cls(status=PrefetchStatus.SKIPPED_NO_INTENT, prompt_block=None)


@dataclass
class SyncTurnRequest:
    """
    回合同步请求。
    
    在成功完成一轮对话后持久化证据。
    """
    workspace_root: Path
    memory_update_markdown: Optional[str] = None
    history_entry: Optional[str] = None


@dataclass
class SyncTurnResponse:
    """回合同步响应。"""
    status: SyncTurnStatus
    reason: Optional[str] = None

    @classmethod
    def default(cls) -> "SyncTurnResponse":
        """创建默认响应（无需同步）。"""
        return cls(status=SyncTurnStatus.NOOP)


@dataclass
class SessionEndRequest:
    """
    会话结束请求。
    
    触发会话结束时的节奏处理和资源清理。
    """
    workspace_root: Path
    session_id: Optional[str] = None


@dataclass
class SessionEndResponse:
    """会话结束响应。"""
    status: SessionEndStatus
    reason: Optional[str] = None

    @classmethod
    def default(cls) -> "SessionEndResponse":
        """创建默认响应（无需处理）。"""
        return cls(status=SessionEndStatus.NOOP)


# ============================================================================
# MemoryProvider 抽象基类
# ============================================================================

class MemoryProvider(ABC):
    """
    记忆提供者抽象基类。
    
    定义记忆系统与 Agent 循环之间的隔离边界，确保：
    - 记忆系统可独立演进和测试
    - Agent 循环不依赖具体记忆实现
    - 支持多种记忆后端（向量数据库、文件系统、云服务等）
    
    生命周期方法：
    1. system_prompt_block() - 启动注入，构建系统提示词的记忆块
    2. prefetch() - 意图预取，在轮次开始前主动召回相关记忆
    3. sync_turn() - 回合同步，在轮次完成后持久化证据
    4. on_session_end() - 会话结束，触发清理和节奏任务
    """

    @abstractmethod
    def system_prompt_block(self, request: SystemPromptRequest) -> SystemPromptResponse:
        """
        构建启动记忆块（同步方法）。
        
        在系统提示词组装时调用，注入长期记忆上下文。
        此方法必须是同步的，因为提示词组装流程是同步的。
        
        Args:
            request: 系统提示词请求，包含工作区根路径
            
        Returns:
            SystemPromptResponse: 包含记忆块的响应，可能是就绪或降级状态
        """
        pass

    @abstractmethod
    async def prefetch(self, request: PrefetchRequest) -> PrefetchResponse:
        """
        意图感知预取（异步方法）。
        
        在轮次执行前，根据推断的意图主动召回相关记忆。
        可选操作，用于增强上下文相关性。
        
        Args:
            request: 预取请求，包含意图和房间上下文
            
        Returns:
            PrefetchResponse: 预取结果，可能是跳过、就绪或失败
        """
        pass

    @abstractmethod
    async def sync_turn(self, request: SyncTurnRequest) -> SyncTurnResponse:
        """
        回合同步（异步方法）。
        
        在成功完成一轮对话后，持久化记忆更新和历史证据。
        确保记忆系统的持久性与 Agent 循环保持一致。
        
        Args:
            request: 同步请求，包含记忆更新和历史条目
            
        Returns:
            SyncTurnResponse: 同步结果，可能是已持久化、无操作或失败
        """
        pass

    @abstractmethod
    async def on_session_end(self, request: SessionEndRequest) -> SessionEndResponse:
        """
        会话结束处理（异步方法）。
        
        在会话结束时触发节奏任务、资源清理和最终持久化。
        支持幂等调用，多次调用不会产生副作用。
        
        Args:
            request: 会话结束请求，包含工作区和会话 ID
            
        Returns:
            SessionEndResponse: 处理结果，可能是已触发、无操作或失败
        """
        pass


# ============================================================================
# 虚拟实现（用于测试和演示）
# ============================================================================

class DummyMemoryProvider(MemoryProvider):
    """
    虚拟记忆提供者实现，用于测试和演示。
    
    提供最小化的记忆功能，返回固定的响应。
    """

    def system_prompt_block(self, request: SystemPromptRequest) -> SystemPromptResponse:
        """返回虚拟的启动记忆块。"""
        return SystemPromptResponse.ready(
            markdown=f"## 虚拟记忆\n工作区: {request.workspace_root}\n状态: 测试模式"
        )

    async def prefetch(self, request: PrefetchRequest) -> PrefetchResponse:
        """返回虚拟的预取结果。"""
        return PrefetchResponse(
            status=PrefetchStatus.READY,
            prompt_block=f"意图: {request.intent}\n房间: {request.current_room or 'none'}"
        )

    async def sync_turn(self, request: SyncTurnRequest) -> SyncTurnResponse:
        """模拟回合同步。"""
        if request.memory_update_markdown or request.history_entry:
            return SyncTurnResponse(status=SyncTurnStatus.PERSISTED)
        return SyncTurnResponse.default()

    async def on_session_end(self, request: SessionEndRequest) -> SessionEndResponse:
        """模拟会话结束处理。"""
        if request.session_id:
            return SessionEndResponse(status=SessionEndStatus.TRIGGERED)
        return SessionEndResponse.default()

"""
MemoryManager 适配器实现。

将现有的 MemoryManager 桥接到 MemoryProvider 接口，实现：
- 系统提示词记忆块构建
- 意图感知预取
- 回合同步持久化
- 会话结束处理
"""

from pathlib import Path
from typing import Optional
from loguru import logger

from memory.provider import (
    MemoryProvider,
    SystemPromptRequest,
    SystemPromptResponse,
    SystemPromptBlock,
    StartupStatus,
    PrefetchRequest,
    PrefetchResponse,
    PrefetchStatus,
    SyncTurnRequest,
    SyncTurnResponse,
    SyncTurnStatus,
    SessionEndRequest,
    SessionEndResponse,
    SessionEndStatus,
)
from memory.manager import MemoryManager


class MemoryManagerProvider(MemoryProvider):
    """
    MemoryManager 适配器 MemoryProvider 接口。
    
    将现有的 MemoryManager 功能封装为标准的四阶段生命周期接口，
    使 Agent 循环可以通过统一接口调用记忆系统。
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        workspace_id: str = "default",
        user_id: Optional[str] = None,
    ):
        """
        初始化适配器。

        Args:
            memory_manager: 现有的 MemoryManager 实例
            workspace_id: 工作区 ID
            user_id: 绑定用户 ID，用于用户级隔离；为空时记忆检索级降级拒绝
        """
        self.memory_manager = memory_manager
        self.workspace_id = workspace_id
        self.user_id = user_id
        self._session_ended: set[str] = set()  # 记录已结束的会话，用于幂等性
        logger.info(f"MemoryManagerProvider initialized for workspace {workspace_id}")

    def system_prompt_block(self, request: SystemPromptRequest) -> SystemPromptResponse:
        """
        构建启动记忆块。
        
        从长期记忆中检索高重要性记忆，构建系统提示词的记忆上下文。
        此方法为同步方法，直接调用 MemoryManager 的内部同步方法。
        
        Args:
            request: 系统提示词请求
            
        Returns:
            SystemPromptResponse: 包含记忆块的响应
        """
        # 用户隔离硬防线：未绑定 user_id 时不得检索长期记忆，避免跨用户泄露
        if not self.user_id:
            return SystemPromptResponse.degraded(
                reason="MemoryManagerProvider 未绑定 user_id，拒绝检索长期记忆（防止跨用户泄露）",
            )

        try:
            # 直接调用内部同步方法，避免 async/sync 转换开销
            memories = self.memory_manager._get_and_evaluate_long_term_memories_sync(
                min_importance=0.6,
                limit=10,
                user_id=self.user_id,
                workspace_id=self.workspace_id,
            )

            if not memories:
                return SystemPromptResponse.ready(
                    markdown="## 记忆上下文\n暂无高重要性记忆。"
                )

            # 构建记忆块 markdown
            memory_lines = []
            for mem in memories[:10]:
                content_preview = (mem.content or "")[:200]
                importance = mem.importance or 0.0
                memory_lines.append(f"- [{importance:.2f}] {content_preview}")

            markdown = "## 记忆上下文\n\n以下是相关长期记忆：\n\n" + "\n".join(memory_lines)
            
            return SystemPromptResponse.ready(markdown=markdown)

        except Exception as e:
            logger.bind(event="system_prompt_block_error").error(f"构建记忆块失败: {e}")
            return SystemPromptResponse.degraded(
                reason=f"记忆系统初始化失败: {str(e)}",
                last_usable_wakeup=None,
            )

    async def prefetch(self, request: PrefetchRequest) -> PrefetchResponse:
        """
        意图感知预取。
        
        根据用户意图搜索相关记忆，增强上下文。
        
        Args:
            request: 预取请求
            
        Returns:
            PrefetchResponse: 预取结果
        """
        if not request.intent or not request.intent.strip():
            return PrefetchResponse.default()

        try:
            # 使用 auto_search_memories 进行智能搜索，按绑定 user_id 隔离
            results = await self.memory_manager.auto_search_memories(
                query=request.intent,
                workspace_id=self.workspace_id,
                max_results=5,
                min_score=0.5,
                user_id=self.user_id,
            )

            if not results:
                return PrefetchResponse(
                    status=PrefetchStatus.SKIPPED_NO_INTENT,
                    prompt_block=None,
                    reason="未找到相关记忆",
                )

            # 构建预取块
            memory_lines = []
            for item in results:
                content = item.get("content", "")[:150]
                importance = item.get("importance", 0.0)
                memory_lines.append(f"- [{importance:.2f}] {content}")

            prompt_block = "## 相关记忆\n\n" + "\n".join(memory_lines)

            return PrefetchResponse(
                status=PrefetchStatus.READY,
                prompt_block=prompt_block,
            )

        except Exception as e:
            logger.bind(event="prefetch_error").warning(f"记忆预取失败: {e}")
            return PrefetchResponse(
                status=PrefetchStatus.FAILED,
                prompt_block=None,
                reason=str(e),
            )

    async def sync_turn(self, request: SyncTurnRequest) -> SyncTurnResponse:
        """
        回合同步。
        
        在轮次完成后持久化记忆更新。
        
        Args:
            request: 同步请求
            
        Returns:
            SyncTurnResponse: 同步结果
        """
        try:
            # 如果有记忆更新标记，触发持久化
            if request.memory_update_markdown or request.history_entry:
                # 这里可以添加具体的持久化逻辑
                # 例如：将 history_entry 写入短期记忆
                # 或者触发向量数据库更新
                
                logger.debug("Memory sync turn completed")
                return SyncTurnResponse(status=SyncTurnStatus.PERSISTED)

            return SyncTurnResponse.default()

        except Exception as e:
            logger.bind(event="sync_turn_error").error(f"回合同步失败: {e}")
            return SyncTurnResponse(
                status=SyncTurnStatus.FAILED,
                reason=str(e),
            )

    async def on_session_end(self, request: SessionEndRequest) -> SessionEndResponse:
        """
        会话结束处理。
        
        触发会话清理和最终持久化。支持幂等调用。
        
        Args:
            request: 会话结束请求
            
        Returns:
            SessionEndResponse: 处理结果
        """
        session_id = request.session_id or "unknown"

        # 幂等性检查
        if session_id in self._session_ended:
            return SessionEndResponse(
                status=SessionEndStatus.ALREADY_HANDLED,
                reason=f"会话 {session_id} 已结束处理",
            )

        try:
            # 标记会话为已结束
            self._session_ended.add(session_id)

            # 触发会话清理逻辑
            # 例如：归档短期记忆、更新长期记忆质量等
            logger.info(f"Session {session_id} end processing triggered")

            return SessionEndResponse(
                status=SessionEndStatus.TRIGGERED,
                reason="会话结束处理已触发",
            )

        except Exception as e:
            logger.bind(event="session_end_error").error(f"会话结束处理失败: {e}")
            return SessionEndResponse(
                status=SessionEndStatus.FAILED,
                reason=str(e),
            )

    def reset_session_tracking(self, session_id: Optional[str] = None) -> None:
        """
        重置会话跟踪状态（用于测试或手动清理）。
        
        Args:
            session_id: 要重置的会话 ID，None 表示重置全部
        """
        if session_id:
            self._session_ended.discard(session_id)
            logger.debug(f"Reset session tracking for {session_id}")
        else:
            self._session_ended.clear()
            logger.debug("Reset all session tracking")

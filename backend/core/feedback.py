"""
核心执行编排模块,负责 Agent 主流程中的理解,规划,执行,反馈或记录能力.
这些文件决定了用户请求在内部被如何拆解,编排以及最终落地执行.
"""

import time
from typing import Dict, List, Any, Optional
from loguru import logger


class FeedbackLayer:
    """
    Agent 反馈层:负责在工具调用完成后提取经验,记录对话并持久化记忆.
    依赖外部注入的 MemoryManager 执行实际的记忆写入操作.
    """
    def __init__(self):
        """初始化反馈层,memory_manager 需通过 set_memory_manager 注入."""
        self.memory_manager = None
        logger.info("FeedbackLayer initialized")

    def set_memory_manager(self, memory_manager):
        """注入 MemoryManager 实例,供后续反馈收集时写入记忆和对话记录."""
        self.memory_manager = memory_manager
    
    async def evaluate_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """评估工具执行结果,判断是否需要重试,提供建议或标记为失败."""
        status = result.get("status")
        
        if status == "error":
            return {
                "needs_retry": True,
                "error_type": "execution_error",
                "message": result.get("message", "Unknown error")
            }
        
        if result.get("requires_confirmation"):
            return {
                "needs_confirmation": True,
                "message": "This operation requires user confirmation",
                "details": result
            }
        
        return {
            "needs_retry": False,
            "needs_confirmation": False,
            "success": True
        }
    
    async def generate_response(self, results: List[Dict[str, Any]], context: Dict[str, Any] | None = None) -> str:
        """根据工具执行结果列表生成面向用户的自然语言反馈文本, 支持通过 context._record_hook 注入行为记录回调."""
        started_at = time.perf_counter()
        if not results:
            response_text = "No results to report."
            if context and callable(context.get("_record_hook")):
                try:
                    context["_record_hook"](
                        node_type="feedback_generation",
                        user_message=context.get("message", ""),
                        context=context,
                        llm_output=response_text,
                        execution_duration_ms=int((time.perf_counter() - started_at) * 1000),
                        metadata={
                            "results_count": 0
                        }
                    )
                except Exception:
                    pass
            return response_text

        responses = []
        for item in results:
            result = item.get("result", item)
            status = result.get("status")

            if status == "completed":
                response_text = result.get("response")
                if response_text is not None:
                    responses.append(str(response_text))
                elif "results" in result:
                    for file_path, file_result in result["results"].items():
                        if file_result.get("status") == "success":
                            responses.append(f"Successfully read {file_path}")
                        else:
                            responses.append(f"Failed to read {file_path}: {file_result.get('message')}")
                elif "stdout" in result:
                    responses.append(f"Command output:\n{result['stdout']}")
            else:
                responses.append(f"Error: {result.get('message', 'Unknown error')}")

        if not responses:
            response_text = "No response generated."
        else:
            response_text = "\n\n".join(responses)

        if context and callable(context.get("_record_hook")):
            try:
                context["_record_hook"](
                    node_type="feedback_generation",
                    user_message=context.get("message", ""),
                    context=context,
                    llm_output=response_text,
                    execution_duration_ms=int((time.perf_counter() - started_at) * 1000),
                    metadata={
                        "results_count": len(results)
                    }
                )
            except Exception:
                pass

        return response_text
    
    async def update_memory(
        self,
        user_input: str,
        response: str,
        context: Dict[str, Any],
        reasoning_content: Optional[str] = None,
        tool_events: Optional[list] = None,
    ):
        """
        更新memory相关数据,配置或状态.
        reasoning_content 为本轮思维链文本,tool_events 为工具调用事件列表,用于历史恢复时展示.
        阅读时需要重点关注覆盖规则,副作用以及更新后的数据一致性.
        """
        if context.get("scheduled_execution_isolated") or context.get("disable_memory_update"):
            logger.info("Memory update disabled for current execution context")
            return

        if not self.memory_manager:
            logger.warning("Memory manager not set, skipping memory update")
            return

        user_id = context.get("user_id")
        continuation = context.get("continuation")
        is_subagent_continuation = isinstance(continuation, dict) and continuation.get("source") == "subagent"
        
        try:
            if is_subagent_continuation:
                merge_with_last_assistant = bool(continuation.get("merge_with_last_assistant", True))
                if merge_with_last_assistant:
                    await self.memory_manager.append_to_last_assistant_memory(
                        session_id=context.get("session_id", "default"),
                        content=response,
                        user_id=user_id,
                    )
                else:
                    await self.memory_manager.add_short_term_memory(
                        session_id=context.get("session_id", "default"),
                        role="assistant",
                        content=response,
                        user_id=user_id,
                    )
                return

            await self.memory_manager.add_short_term_memory(
                session_id=context.get("session_id", "default"),
                role="user",
                content=user_input,
                user_id=user_id,
            )
            
            await self.memory_manager.add_short_term_memory(
                session_id=context.get("session_id", "default"),
                role="assistant",
                content=response,
                user_id=user_id,
                reasoning_content=reasoning_content or None,
                tool_events=tool_events or None,
            )
            
            if self._should_persist(response):
                await self.memory_manager.add_long_term_memory(
                    content=f"User asked: {user_input}\nAssistant responded: {response}",
                    importance=0.7,
                    user_id=user_id,
                )
                
        except Exception as e:
            logger.error(f"Error updating memory: {str(e)}")
    
    def _should_persist(self, content: str) -> bool:
        """判断对话内容是否包含需持久化到长期记忆的关键词(如 remember/记住/preference 等)."""
        important_keywords = [
            "remember", "记住", "important", "重要",
            "preference", "偏好", "习惯", "always"
        ]
        
        content_lower = content.lower()
        return any(keyword in content_lower for keyword in important_keywords)

    async def record_explicit_feedback(
        self,
        session_id: str,
        message_id: str,
        user_id: str,
        rating: int,
        comment: Optional[str] = None,
    ) -> None:
        """
        记录用户对助手消息的显式反馈(点赞/点踩).

        Args:
            session_id: 会话 ID
            message_id: 消息 ID
            user_id: 用户 ID(字符串类型)
            rating: 评分(1=点赞,-1=点踩)
            comment: 可选备注
        """
        if rating not in (-1, 1):
            raise ValueError(f"无效的评分值: {rating},应为 1(点赞)或 -1(点踩)")

        import asyncio
        from db.models import UserFeedback, SessionLocal

        def _sync_record():
            db = SessionLocal()
            try:
                feedback_record = UserFeedback(
                    session_id=session_id,
                    message_id=message_id,
                    user_id=user_id,
                    rating=rating,
                    comment=comment,
                )
                db.add(feedback_record)
                db.commit()
                logger.info(f"User feedback recorded: session={session_id}, message={message_id}, rating={rating}")
            except Exception as exc:
                db.rollback()
                logger.error(f"Failed to record user feedback: {exc}")
                raise
            finally:
                db.close()

        await asyncio.to_thread(_sync_record)

    async def diagnose_error(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """诊断工具执行错误,根据错误消息分类为 timeout/network/auth 等类型并给出修复建议."""
        error_message = result.get("message", "")
        
        diagnosis = {
            "type": "unknown",
            "suggestion": "Please try again or provide more details."
        }
        
        if "timeout" in error_message.lower():
            diagnosis = {
                "type": "timeout",
                "suggestion": "The operation took too long. Try a simpler task or increase timeout."
            }
        elif "permission" in error_message.lower():
            diagnosis = {
                "type": "permission",
                "suggestion": "Permission denied. Check file permissions."
            }
        elif "not found" in error_message.lower():
            diagnosis = {
                "type": "not_found",
                "suggestion": "The resource was not found. Check the path or name."
            }
        elif "syntax" in error_message.lower():
            diagnosis = {
                "type": "syntax",
                "suggestion": "There might be a syntax error in your request."
            }
        
        return diagnosis


# 全局 FeedbackLayer 实例注册表,供 API 路由访问
feedback_layer_registry = FeedbackLayer()

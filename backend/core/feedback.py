"""
核心执行编排模块，负责 Agent 主流程中的理解、规划、执行、反馈或记录能力。
这些文件决定了用户请求在内部被如何拆解、编排以及最终落地执行。
"""

import time
from typing import Dict, List, Any
from loguru import logger


class FeedbackLayer:
    """
    封装与FeedbackLayer相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(self):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.memory_manager = None
        logger.info("FeedbackLayer initialized")
    
    def set_memory_manager(self, memory_manager):
        """
        设置memory、manager相关配置或运行状态。
        此类方法通常会直接影响后续执行路径或运行上下文中的关键数据。
        """
        self.memory_manager = memory_manager
    
    async def evaluate_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理evaluate、result相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理generate、response相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        context: Dict[str, Any]
    ):
        """
        更新memory相关数据、配置或状态。
        阅读时需要重点关注覆盖规则、副作用以及更新后的数据一致性。
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
        """
        处理should、persist相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        important_keywords = [
            "remember", "记住", "important", "重要",
            "preference", "偏好", "习惯", "always"
        ]
        
        content_lower = content.lower()
        return any(keyword in content_lower for keyword in important_keywords)
    
    async def diagnose_error(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理diagnose、error相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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

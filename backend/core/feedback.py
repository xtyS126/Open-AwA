from typing import Dict, List, Any
from loguru import logger


class FeedbackLayer:
    def __init__(self):
        self.memory_manager = None
        logger.info("FeedbackLayer initialized")
    
    def set_memory_manager(self, memory_manager):
        self.memory_manager = memory_manager
    
    async def evaluate_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
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
    
    async def generate_response(self, results: List[Dict[str, Any]]) -> str:
        if not results:
            return "No results to report."
        
        responses = []
        for result in results:
            if result.get("status") == "completed":
                if "response" in result:
                    responses.append(result["response"])
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
        
        return "\n\n".join(responses)
    
    async def update_memory(
        self,
        user_input: str,
        response: str,
        context: Dict[str, Any]
    ):
        if not self.memory_manager:
            logger.warning("Memory manager not set, skipping memory update")
            return
        
        try:
            await self.memory_manager.add_short_term_memory(
                session_id=context.get("session_id", "default"),
                role="user",
                content=user_input
            )
            
            await self.memory_manager.add_short_term_memory(
                session_id=context.get("session_id", "default"),
                role="assistant",
                content=response
            )
            
            if self._should_persist(response):
                await self.memory_manager.add_long_term_memory(
                    content=f"User asked: {user_input}\nAssistant responded: {response}",
                    importance=0.7
                )
                
        except Exception as e:
            logger.error(f"Error updating memory: {str(e)}")
    
    def _should_persist(self, content: str) -> bool:
        important_keywords = [
            "remember", "记住", "important", "重要",
            "preference", "偏好", "习惯", "always"
        ]
        
        content_lower = content.lower()
        return any(keyword in content_lower for keyword in important_keywords)
    
    async def diagnose_error(self, result: Dict[str, Any]) -> Dict[str, Any]:
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

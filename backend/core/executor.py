from typing import Dict, Any, Optional, Callable
from loguru import logger
import asyncio
import httpx
from memory.experience_manager import ExperienceManager
from sqlalchemy.orm import Session


class ExecutionLayer:
    def __init__(self):
        self.tools = {}
        self.llm_api_url = None
        self.llm_api_key = None
        logger.info("ExecutionLayer initialized")
    
    def configure_llm(self, api_url: str, api_key: Optional[str] = None):
        self.llm_api_url = api_url
        self.llm_api_key = api_key
        logger.info(f"LLM API configured: {api_url}")
    
    def register_tool(self, name: str, tool_func: Callable[..., Any]):
        self.tools[name] = tool_func
        logger.debug(f"Registered execution tool: {name}")
    
    async def _call_llm_api(self, prompt: str, context: Dict[str, Any]) -> str:
        if not self.llm_api_url:
            return "LLM API not configured. Please set up API configuration."
        
        headers = {
            "Content-Type": "application/json"
        }
        if self.llm_api_key:
            headers["Authorization"] = f"Bearer {self.llm_api_key}"
        
        payload = {
            "prompt": prompt,
            "context": context,
            "max_tokens": 1000
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.llm_api_url,
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                result = response.json()
                return result.get("response", "No response from LLM API")
        except httpx.HTTPError as e:
            logger.error(f"LLM API call failed: {str(e)}")
            return f"LLM API call failed: {str(e)}"
        except Exception as e:
            logger.error(f"Unexpected error in LLM call: {str(e)}")
            return f"Unexpected error: {str(e)}"
    
    async def execute_step(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        action = step.get("action")
        logger.info(f"Executing step: {action}")
        
        try:
            if action == "read_files":
                result = await self._execute_read_files(step)
            elif action == "execute_command":
                result = await self._execute_command(step)
            elif action == "llm_generate":
                result = await self._execute_llm(step, context)
            elif action == "llm_query":
                result = await self._execute_llm_query(step, context)
            elif action == "llm_explain":
                result = await self._execute_llm_explain(step, context)
            elif action == "llm_chat":
                result = await self._execute_llm_chat(step, context)
            else:
                result = {"status": "error", "message": f"Unknown action: {action}"}
            
            result["step"] = step.get("step")
            result["action"] = action
            
            if context.get('relevant_experiences'):
                logger.info(f"Executed step using {len(context['relevant_experiences'])} experiences")
            
            return result
            
        except Exception as e:
            logger.error(f"Error executing step {action}: {str(e)}")
            return {
                "status": "error",
                "message": str(e),
                "step": step.get("step"),
                "action": action
            }
    
    async def _execute_read_files(self, step: Dict[str, Any]) -> Dict[str, Any]:
        files = step.get("targets", [])
        results = {}
        
        for file_path in files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    results[file_path] = {
                        "status": "success",
                        "content": f.read()
                    }
            except FileNotFoundError:
                results[file_path] = {
                    "status": "error",
                    "message": f"File not found: {file_path}"
                }
            except Exception as e:
                results[file_path] = {
                    "status": "error",
                    "message": str(e)
                }
        
        return {
            "status": "completed",
            "results": results
        }
    
    async def _execute_command(self, step: Dict[str, Any]) -> Dict[str, Any]:
        command = step.get("command", "")
        
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=30
            )
            
            return {
                "status": "completed",
                "returncode": proc.returncode,
                "stdout": stdout.decode() if stdout else "",
                "stderr": stderr.decode() if stderr else ""
            }
        except asyncio.TimeoutError:
            return {
                "status": "error",
                "message": "Command execution timeout"
            }
        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }
    
    async def _execute_llm(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        task = step.get("task", "")
        response = await self._call_llm_api(task, context)
        return {
            "status": "completed",
            "response": response,
            "requires_confirmation": True
        }
    
    async def _execute_llm_query(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        query = step.get("query", "")
        response = await self._call_llm_api(query, context)
        return {
            "status": "completed",
            "response": response
        }
    
    async def _execute_llm_explain(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        target = step.get("target", "")
        response = await self._call_llm_api(f"Explain: {target}", context)
        return {
            "status": "completed",
            "response": response
        }
    
    async def _execute_llm_chat(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        message = step.get("message", "")
        response = await self._call_llm_api(message, context)
        return {
            "status": "completed",
            "response": response
        }
    
    async def retry_step(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"Retrying step: {step.get('action')}")
        return await self.execute_step(step, context)
    
    async def record_experience_feedback(
        self,
        experience_id: int,
        success: bool,
        db: Session
    ) -> None:
        """记录经验应用反馈"""
        try:
            manager = ExperienceManager(db)
            await manager.update_experience_quality(
                experience_id=experience_id,
                success=success
            )
        except Exception as e:
            logger.error(f"Error recording experience feedback: {e}")

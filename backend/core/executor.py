"""
核心执行编排模块，负责 Agent 主流程中的理解、规划、执行、反馈或记录能力。
这些文件决定了用户请求在内部被如何拆解、编排以及最终落地执行。
"""

from typing import Dict, Any, Optional, Callable
from loguru import logger
import asyncio
import time
import httpx
from memory.experience_manager import ExperienceManager
from sqlalchemy.orm import Session


class ExecutionLayer:
    """
    封装与ExecutionLayer相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(self):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.tools = {}
        self.llm_api_url = None
        self.llm_api_key = None
        self.default_provider_endpoints = {
            "openai": "https://api.openai.com/v1/chat/completions",
            "anthropic": "https://api.anthropic.com/v1/messages",
            "deepseek": "https://api.deepseek.com/v1/chat/completions",
            "google": "https://generativelanguage.googleapis.com/v1beta/models",
            "alibaba": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            "moonshot": "https://api.moonshot.cn/v1/chat/completions",
            "zhipu": "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        }
        self.provider_api_key_fields = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY"
        }
        logger.info("ExecutionLayer initialized")

    def configure_llm(self, api_url: str, api_key: Optional[str] = None):
        """
        处理configure、llm相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.llm_api_url = api_url
        self.llm_api_key = api_key
        logger.info(f"LLM API configured: {api_url}")

    def register_tool(self, name: str, tool_func: Callable[..., Any]):
        """
        处理register、tool相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.tools[name] = tool_func
        logger.debug(f"Registered execution tool: {name}")

    def _build_error(self, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        处理build、error相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return {
            "code": code,
            "message": message,
            "details": details or {}
        }

    def _extract_response_text(self, response_data: Dict[str, Any]) -> str:
        """
        处理extract、response、text相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if "response" in response_data and response_data["response"] is not None:
            return str(response_data["response"])
        if "content" in response_data and response_data["content"] is not None:
            return str(response_data["content"])

        choices = response_data.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                message = first_choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        return content
                    if isinstance(content, list):
                        parts = []
                        for item in content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                text = item.get("text")
                                if isinstance(text, str):
                                    parts.append(text)
                        if parts:
                            return "\n".join(parts)

                text = first_choice.get("text")
                if isinstance(text, str):
                    return text

        return ""

    def _resolve_llm_configuration(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理resolve、llm、configuration相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        from config.settings import settings

        provider = context.get("provider")
        model = context.get("model")
        db = context.get("db")
        config = None

        if db:
            try:
                from billing.pricing_manager import PricingManager
                pricing_manager = PricingManager(db)
                if provider and model:
                    config = pricing_manager.get_configuration_by_provider_model(provider, model)
                if not config:
                    config = pricing_manager.get_default_configuration()
            except Exception as e:
                logger.error(f"Failed to resolve model configuration from database: {e}")

        if config:
            provider = provider or config.provider
            model = model or config.model
            api_key = config.api_key
            api_endpoint = config.api_endpoint
        else:
            api_key = None
            api_endpoint = None

        provider = (provider or "").strip().lower()
        model = (model or "").strip()

        if not provider:
            return {
                "ok": False,
                "error": self._build_error(
                    "llm_provider_missing",
                    "未配置可用的模型提供商",
                    {
                        "provider": provider,
                        "model": model
                    }
                )
            }

        if not model:
            return {
                "ok": False,
                "error": self._build_error(
                    "llm_model_missing",
                    "未配置可用的模型名称",
                    {
                        "provider": provider,
                        "model": model
                    }
                )
            }

        if not api_endpoint:
            if self.llm_api_url:
                api_endpoint = self.llm_api_url
            else:
                api_endpoint = self.default_provider_endpoints.get(provider)

        if not api_endpoint:
            return {
                "ok": False,
                "error": self._build_error(
                    "llm_endpoint_missing",
                    "未配置模型服务地址",
                    {
                        "provider": provider,
                        "model": model
                    }
                )
            }

        if not api_key:
            if self.llm_api_key:
                api_key = self.llm_api_key
            else:
                field_name = self.provider_api_key_fields.get(provider)
                if field_name:
                    api_key = getattr(settings, field_name, None)

        if not api_key:
            return {
                "ok": False,
                "error": self._build_error(
                    "llm_api_key_missing",
                    "未配置模型 API Key",
                    {
                        "provider": provider,
                        "model": model,
                        "api_endpoint": api_endpoint
                    }
                )
            }

        return {
            "ok": True,
            "provider": provider,
            "model": model,
            "api_endpoint": api_endpoint,
            "api_key": api_key
        }

    async def _call_llm_api(self, prompt: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理call、llm、api相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        record_hook = context.get("_record_hook")
        started_at = time.perf_counter()
        serialized_context = {
            key: value
            for key, value in context.items()
            if key not in {"_record_hook", "db"}
        }
        llm_input_payload = {
            "prompt": prompt,
            "context": serialized_context,
        }

        resolved = self._resolve_llm_configuration(context)
        if not resolved.get("ok"):
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            if callable(record_hook):
                record_hook(
                    node_type="llm_call",
                    user_message=context.get("message", prompt),
                    context=context,
                    status="error",
                    error_message=resolved.get("error", {}).get("message"),
                    llm_input=llm_input_payload,
                    llm_output=resolved,
                    execution_duration_ms=duration_ms,
                    metadata={
                        "phase": "resolve_configuration",
                        "error": resolved.get("error"),
                    }
                )
            return resolved

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {resolved['api_key']}"
        }

        payload = {
            "model": resolved["model"],
            "provider": resolved["provider"],
            "prompt": prompt,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "context": serialized_context,
            "max_tokens": 1000
        }
        llm_input_payload.update({
            "endpoint": resolved["api_endpoint"],
            "headers": {
                "Content-Type": headers.get("Content-Type"),
                "Authorization": "Bearer ***"
            },
            "payload": payload,
        })

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    resolved["api_endpoint"],
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                result = response.json()
                response_text = self._extract_response_text(result)

                if not response_text.strip():
                    output = {
                        "ok": False,
                        "error": self._build_error(
                            "llm_empty_response",
                            "Empty response from model",
                            {
                                "provider": resolved["provider"],
                                "model": resolved["model"],
                                "api_endpoint": resolved["api_endpoint"]
                            }
                        )
                    }
                    duration_ms = int((time.perf_counter() - started_at) * 1000)
                    if callable(record_hook):
                        record_hook(
                            node_type="llm_call",
                            user_message=context.get("message", prompt),
                            context=context,
                            status="error",
                            error_message=output["error"]["message"],
                            llm_input=llm_input_payload,
                            llm_output=output,
                            execution_duration_ms=duration_ms,
                            metadata={
                                "provider": resolved["provider"],
                                "model": resolved["model"],
                                "status_code": response.status_code,
                            }
                        )
                    return output

                output = {
                    "ok": True,
                    "response": response_text,
                    "provider": resolved["provider"],
                    "model": resolved["model"]
                }
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                if callable(record_hook):
                    usage = result.get("usage") if isinstance(result, dict) else None
                    tokens_used = None
                    if isinstance(usage, dict):
                        tokens_used = usage.get("total_tokens")
                    record_hook(
                        node_type="llm_call",
                        user_message=context.get("message", prompt),
                        context=context,
                        status="success",
                        llm_input=llm_input_payload,
                        llm_output=output,
                        llm_tokens_used=tokens_used,
                        execution_duration_ms=duration_ms,
                        metadata={
                            "provider": resolved["provider"],
                            "model": resolved["model"],
                            "status_code": response.status_code,
                        }
                    )
                return output
        except httpx.HTTPStatusError as e:
            logger.error(f"LLM API HTTP status error: {str(e)}")
            response_text = e.response.text[:1000] if e.response.text else ""
            output = {
                "ok": False,
                "error": self._build_error(
                    "llm_http_error",
                    "Model service request failed",
                    {
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                        "api_endpoint": resolved["api_endpoint"],
                        "status_code": e.response.status_code,
                        "response_text": response_text
                    }
                )
            }
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            if callable(record_hook):
                record_hook(
                    node_type="llm_call",
                    user_message=context.get("message", prompt),
                    context=context,
                    status="error",
                    error_message=output["error"]["message"],
                    llm_input=llm_input_payload,
                    llm_output=output,
                    execution_duration_ms=duration_ms,
                    metadata={
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                        "status_code": e.response.status_code,
                    }
                )
            return output
        except httpx.HTTPError as e:
            logger.error(f"LLM API call failed: {str(e)}")
            output = {
                "ok": False,
                "error": self._build_error(
                    "llm_network_error",
                    "Model service network error",
                    {
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                        "api_endpoint": resolved["api_endpoint"],
                        "reason": str(e)
                    }
                )
            }
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            if callable(record_hook):
                record_hook(
                    node_type="llm_call",
                    user_message=context.get("message", prompt),
                    context=context,
                    status="error",
                    error_message=output["error"]["message"],
                    llm_input=llm_input_payload,
                    llm_output=output,
                    execution_duration_ms=duration_ms,
                    metadata={
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                    }
                )
            return output
        except Exception as e:
            logger.error(f"Unexpected error in LLM call: {str(e)}")
            output = {
                "ok": False,
                "error": self._build_error(
                    "llm_unexpected_error",
                    "Unexpected model invocation error",
                    {
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                        "api_endpoint": resolved["api_endpoint"],
                        "reason": str(e)
                    }
                )
            }
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            if callable(record_hook):
                record_hook(
                    node_type="llm_call",
                    user_message=context.get("message", prompt),
                    context=context,
                    status="error",
                    error_message=output["error"]["message"],
                    llm_input=llm_input_payload,
                    llm_output=output,
                    execution_duration_ms=duration_ms,
                    metadata={
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                    }
                )
            return output

    async def execute_step(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理execute、step相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理execute、read、files相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理execute、command相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理execute、llm相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        task = step.get("task", "")
        result = await self._call_llm_api(task, context)
        if not result.get("ok"):
            return {
                "status": "error",
                "message": result["error"]["message"],
                "error": result["error"]
            }

        return {
            "status": "completed",
            "response": result["response"],
            "provider": result.get("provider"),
            "model": result.get("model"),
            "requires_confirmation": True
        }

    async def _execute_llm_query(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理execute、llm、query相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        query = step.get("query", "")
        result = await self._call_llm_api(query, context)
        if not result.get("ok"):
            return {
                "status": "error",
                "message": result["error"]["message"],
                "error": result["error"]
            }

        return {
            "status": "completed",
            "response": result["response"],
            "provider": result.get("provider"),
            "model": result.get("model")
        }

    async def _execute_llm_explain(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理execute、llm、explain相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        target = step.get("target", "")
        result = await self._call_llm_api(f"Explain: {target}", context)
        if not result.get("ok"):
            return {
                "status": "error",
                "message": result["error"]["message"],
                "error": result["error"]
            }

        return {
            "status": "completed",
            "response": result["response"],
            "provider": result.get("provider"),
            "model": result.get("model")
        }

    async def _execute_llm_chat(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理execute、llm、chat相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        message = step.get("message", "")
        result = await self._call_llm_api(message, context)
        if not result.get("ok"):
            return {
                "status": "error",
                "message": result["error"]["message"],
                "error": result["error"]
            }

        return {
            "status": "completed",
            "response": result["response"],
            "provider": result.get("provider"),
            "model": result.get("model")
        }
    
    async def retry_step(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理retry、step相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        logger.info(f"Retrying step: {step.get('action')}")
        return await self.execute_step(step, context)
    
    async def record_experience_feedback(
        self,
        experience_id: int,
        success: bool,
        db: Session
    ) -> None:
        """
        处理record、experience、feedback相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        try:
            manager = ExperienceManager(db)
            await manager.update_experience_quality(
                experience_id=experience_id,
                success=success
            )
        except Exception as e:
            logger.error(f"Error recording experience feedback: {e}")

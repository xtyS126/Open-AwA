"""
核心执行编排模块，负责 Agent 主流程中的理解、规划、执行、反馈或记录能力。
这些文件决定了用户请求在内部被如何拆解、编排以及最终落地执行。
"""

import asyncio
import hashlib
import json
import time
from typing import Dict, Any, Optional, Callable

import httpx
from loguru import logger

from config.logging import get_request_id
from core.metrics import record_model_service_metric, record_tool_execution_metric
from core.model_service import (
    build_provider_request,
    build_standard_error,
    is_retryable_exception,
    send_with_retries,
    send_stream_with_retries,
)
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
        self._tool_execution_cache: Dict[str, Dict[str, Any]] = {}
        self._tool_execution_cache_order: list[str] = []
        self._max_tool_execution_cache = 256
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
        return build_standard_error(
            code=code,
            message=message,
            request_id=get_request_id(),
            details=details,
        )

    def _build_tool_idempotency_key(self, step: Dict[str, Any], context: Dict[str, Any]) -> str:
        """
        为工具执行生成稳定幂等键。
        如果调用方已显式传入幂等键，则优先复用该值。
        """

        explicit_key = str(step.get("idempotency_key") or context.get("idempotency_key") or "").strip()
        if explicit_key:
            return explicit_key

        fingerprint_source = {
            "session_id": context.get("session_id"),
            "user_id": context.get("user_id"),
            "action": step.get("action"),
            "step": step,
        }
        serialized = json.dumps(fingerprint_source, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _get_cached_tool_result(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        """
        读取已缓存的工具执行结果，避免同一幂等键重复触发副作用。
        """

        cached = self._tool_execution_cache.get(idempotency_key)
        if not isinstance(cached, dict):
            return None
        cloned = dict(cached)
        cloned["idempotent_replay"] = True
        return cloned

    def _cache_tool_result(self, idempotency_key: str, result: Dict[str, Any]) -> None:
        """
        缓存工具执行结果，并控制缓存上限，防止内存持续增长。
        """

        self._tool_execution_cache[idempotency_key] = dict(result)
        if idempotency_key in self._tool_execution_cache_order:
            self._tool_execution_cache_order.remove(idempotency_key)
        self._tool_execution_cache_order.append(idempotency_key)

        while len(self._tool_execution_cache_order) > self._max_tool_execution_cache:
            oldest = self._tool_execution_cache_order.pop(0)
            self._tool_execution_cache.pop(oldest, None)

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

        candidates = response_data.get("candidates")
        if isinstance(candidates, list) and candidates:
            first_candidate = candidates[0]
            if isinstance(first_candidate, dict):
                content = first_candidate.get("content")
                if isinstance(content, dict):
                    parts = content.get("parts")
                    if isinstance(parts, list):
                        texts = []
                        for part in parts:
                            if isinstance(part, dict) and isinstance(part.get("text"), str):
                                texts.append(part["text"])
                        if texts:
                            return "\n".join(texts)

        return ""

    def _resolve_max_tokens(self, resolved: Dict[str, Any]) -> int:
        """
        统一解析模型请求使用的 max_tokens。
        仅当配置值为 None 时回退到默认值，保留 0 等显式配置。
        """
        max_tokens = resolved.get("max_tokens")
        if max_tokens is None:
            return 8192
        return max_tokens

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
            max_tokens = getattr(config, "max_tokens", None)
        else:
            api_key = None
            api_endpoint = None
            max_tokens = None

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

        try:
            from billing.pricing_manager import PricingManager
            api_endpoint = PricingManager.build_provider_api_endpoint(provider, api_endpoint, "chat")
        except Exception as e:
            logger.error(f"Failed to normalize provider endpoint: {e}")

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
            "api_key": api_key,
            "max_tokens": max_tokens,
            "request_id": context.get("request_id") or get_request_id(),
            "client_version": context.get("client_version"),
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

        request_spec = build_provider_request(
            provider=resolved["provider"],
            api_endpoint=resolved["api_endpoint"],
            api_key=resolved["api_key"],
            purpose="chat",
            model=resolved["model"],
            prompt=prompt,
            max_tokens=self._resolve_max_tokens(resolved),
            request_id=resolved.get("request_id"),
            client_version=resolved.get("client_version"),
            context=serialized_context,
        )
        llm_input_payload.update({
            "endpoint": request_spec.endpoint,
            "headers": {
                key: ("Bearer ***" if key.lower() == "authorization" else value)
                for key, value in request_spec.headers.items()
            },
            "payload": request_spec.payload,
        })

        try:
            logger.info(
                f"Sending LLM request to {request_spec.endpoint} "
                f"for provider {resolved['provider']}, model {resolved['model']}"
            )
            response = await send_with_retries(request_spec)
            result = response.json()
            logger.info(f"Successfully received response from {request_spec.endpoint}")
            response_text = self._extract_response_text(result)
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            record_model_service_metric(resolved["provider"], "chat", "success", duration_ms)

            if not response_text.strip():
                output = {
                    "ok": False,
                    "error": build_standard_error(
                        "model_service_empty_response",
                        "模型服务返回空响应",
                        request_id=resolved.get("request_id"),
                        details={
                            "provider": resolved["provider"],
                            "model": resolved["model"],
                            "api_endpoint": request_spec.endpoint,
                        },
                        retryable=False,
                    )
                }
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
                "model": resolved["model"],
                "request_id": resolved.get("request_id"),
            }
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
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            record_model_service_metric(resolved["provider"], "chat", "http_error", duration_ms)
            output = {
                "ok": False,
                "error": build_standard_error(
                    "model_service_http_error",
                    "模型服务请求失败",
                    request_id=resolved.get("request_id"),
                    details={
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                        "api_endpoint": request_spec.endpoint,
                        "status_code": e.response.status_code,
                        "response_text": response_text
                    },
                    retryable=is_retryable_exception(e),
                    status_code=e.response.status_code,
                )
            }
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
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            record_model_service_metric(resolved["provider"], "chat", "network_error", duration_ms)
            output = {
                "ok": False,
                "error": build_standard_error(
                    "model_service_network_error",
                    "模型服务网络异常",
                    request_id=resolved.get("request_id"),
                    details={
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                        "api_endpoint": request_spec.endpoint,
                        "reason": str(e)
                    },
                    retryable=is_retryable_exception(e),
                )
            }
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
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            record_model_service_metric(resolved["provider"], "chat", "unexpected_error", duration_ms)
            output = {
                "ok": False,
                "error": build_standard_error(
                    "model_service_unexpected_error",
                    "模型服务调用出现未知异常",
                    request_id=resolved.get("request_id"),
                    details={
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                        "api_endpoint": request_spec.endpoint if "request_spec" in locals() else resolved["api_endpoint"],
                        "reason": str(e)
                    },
                )
            }
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

    async def _call_llm_api_stream(self, prompt: str, context: Dict[str, Any]):
        """
        流式请求模型服务，向外 yield { "content": "...", "reasoning_content": "..." } 结构。
        """
        record_hook = context.get("_record_hook")
        started_at = time.perf_counter()
        serialized_context = {
            key: value
            for key, value in context.items()
            if key not in {"_record_hook", "db"}
        }

        resolved = self._resolve_llm_configuration(context)
        if not resolved.get("ok"):
            yield {"error": resolved.get("error")}
            return

        request_spec = build_provider_request(
            provider=resolved["provider"],
            api_endpoint=resolved["api_endpoint"],
            api_key=resolved["api_key"],
            purpose="chat",
            model=resolved["model"],
            prompt=prompt,
            max_tokens=self._resolve_max_tokens(resolved),
            request_id=resolved.get("request_id"),
            client_version=resolved.get("client_version"),
            context=serialized_context,
            stream=True,
        )

        try:
            logger.info(
                f"Sending streaming LLM request to {request_spec.endpoint} "
                f"for provider {resolved['provider']}, model {resolved['model']}"
            )
            stream_gen = await send_stream_with_retries(request_spec)
            
            full_content = ""
            full_reasoning = ""
            
            async for line in stream_gen:
                line = line.strip()
                if not line or not line.startswith("data: "):
                    continue
                
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                
                try:
                    data = json.loads(data_str)
                    choices = data.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        
                        content = delta.get("content", "")
                        reasoning = delta.get("reasoning_content", "")
                        
                        # Handle Google format if applicable, though usually they return full text in chunks
                        if not content and not reasoning and "candidates" in data:
                            cands = data["candidates"]
                            if cands:
                                parts = cands[0].get("content", {}).get("parts", [])
                                if parts:
                                    content = parts[0].get("text", "")
                                    
                        # Handle Anthropic format if they use SSE with different schema
                        # Note: Anthropic streaming is slightly different, but assuming standard SSE proxy or openai compat for now.
                        if "type" in data and data["type"] == "content_block_delta":
                            content = data.get("delta", {}).get("text", "")
                            
                        if content or reasoning:
                            if content: full_content += content
                            if reasoning: full_reasoning += reasoning
                            
                            yield {
                                "content": content,
                                "reasoning_content": reasoning
                            }
                except json.JSONDecodeError:
                    continue

            duration_ms = int((time.perf_counter() - started_at) * 1000)
            record_model_service_metric(resolved["provider"], "chat_stream", "success", duration_ms)

            if callable(record_hook):
                record_hook(
                    node_type="llm_call",
                    user_message=context.get("message", prompt),
                    context=context,
                    status="success",
                    llm_input={
                        "prompt": prompt,
                        "endpoint": request_spec.endpoint,
                        "context": serialized_context
                    },
                    llm_output={
                        "ok": True,
                        "response": full_content,
                        "reasoning_content": full_reasoning,
                        "provider": resolved["provider"],
                        "model": resolved["model"]
                    },
                    execution_duration_ms=duration_ms,
                    metadata={
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                        "mode": "stream"
                    }
                )

        except Exception as e:
            logger.error(f"Error in LLM stream call: {str(e)}")
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            record_model_service_metric(resolved["provider"], "chat_stream", "error", duration_ms)
            
            output_error = {
                "error": build_standard_error(
                    "model_service_stream_error",
                    "模型流式服务调用出现异常",
                    request_id=resolved.get("request_id"),
                    details={
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                        "reason": str(e)
                    },
                )
            }
            
            if callable(record_hook):
                record_hook(
                    node_type="llm_call",
                    user_message=context.get("message", prompt),
                    context=context,
                    status="error",
                    error_message=output_error["error"]["message"],
                    llm_input={
                        "prompt": prompt,
                        "endpoint": request_spec.endpoint,
                        "context": serialized_context
                    },
                    llm_output=output_error,
                    execution_duration_ms=duration_ms,
                    metadata={
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                        "mode": "stream"
                    }
                )
                
            yield output_error

    async def execute_step(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理execute、step相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        action = step.get("action")
        logger.info(f"Executing step: {action}")
        idempotency_key = self._build_tool_idempotency_key(step, context)
        cached_result = self._get_cached_tool_result(idempotency_key)
        if cached_result is not None:
            cached_result["idempotency_key"] = idempotency_key
            record_tool_execution_metric(str(action or "unknown"), "replayed")
            return cached_result
        
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
            result["idempotency_key"] = idempotency_key
            self._cache_tool_result(idempotency_key, result)
            record_tool_execution_metric(str(action or "unknown"), str(result.get("status") or "completed"))
            
            if context.get('relevant_experiences'):
                logger.info(f"Executed step using {len(context['relevant_experiences'])} experiences")
            
            return result
            
        except Exception as e:
            logger.error(f"Error executing step {action}: {str(e)}")
            record_tool_execution_metric(str(action or "unknown"), "error")
            return {
                "status": "error",
                "message": str(e),
                "step": step.get("step"),
                "action": action,
                "idempotency_key": idempotency_key,
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

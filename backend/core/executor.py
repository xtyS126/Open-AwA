"""
核心执行编排模块，负责 Agent 主流程中的理解、规划、执行、反馈或记录能力。
这些文件决定了用户请求在内部被如何拆解、编排以及最终落地执行。
"""

import asyncio
import hashlib
import json
import re
import time
import urllib.parse
from typing import Dict, Any, Optional, Callable

import httpx
from loguru import logger

from config.logging import get_request_id
from core.metrics import record_model_service_metric, record_tool_execution_metric
from core.model_service import (
    build_standard_error,
)
from core.litellm_adapter import (
    litellm_chat_completion,
    litellm_chat_completion_stream,
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

    def _sanitize_api_endpoint(self, endpoint: Optional[str]) -> Optional[str]:
        """
        对请求端点中的敏感查询参数进行脱敏，避免日志和错误响应泄露密钥。
        """
        normalized = str(endpoint or "").strip()
        if not normalized:
            return endpoint

        parsed = urllib.parse.urlsplit(normalized)
        if not parsed.query:
            return normalized

        redacted_query = urllib.parse.urlencode([
            (
                key,
                "***" if any(marker in key.lower() for marker in ("key", "token", "secret", "auth")) else value,
            )
            for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        ])
        return urllib.parse.urlunsplit(parsed._replace(query=redacted_query))

    def _sanitize_text_excerpt(self, value: Optional[str], limit: int = 200) -> str:
        """
        对返回文本或异常原因进行长度截断与常见敏感片段脱敏。
        """
        excerpt = str(value or "")[:limit]
        excerpt = re.sub(r'(?i)(bearer\s+)[a-z0-9._\-]+', r'\1***', excerpt)
        excerpt = re.sub(
            r'(?i)(api[_-]?key|token|access[_-]?token|refresh[_-]?token|secret)("?\s*[:=]\s*"?)([^"\s,;&]+)',
            r'\1\2***',
            excerpt,
        )
        return excerpt

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

    def _build_agent_capability_system_prompt(self, context: Dict[str, Any]) -> str:
        """
        基于 Agent 注入的运行态能力摘要生成系统提示，避免模型把自己误判成纯文本聊天机器人。
        """
        capabilities = context.get("agent_capabilities")
        if not isinstance(capabilities, dict):
            return ""

        lines = [
            "你是 Open-AwA 平台中的 AI Agent，不是孤立的纯文本聊天模型。",
            "回答关于自身能力的问题时，必须以当前运行态能力清单为准。",
            "不要笼统声称自己不能调用 MCP、技能或插件；要区分平台是否支持、当前会话是否启用、当前是否已有可用工具。",
        ]

        skills_enabled = bool(capabilities.get("skills_enabled", False))
        skills = capabilities.get("skills") if isinstance(capabilities.get("skills"), list) else []
        if skills_enabled:
            if skills:
                lines.append("当前会话可用技能：")
                for skill in skills[:12]:
                    if not isinstance(skill, dict):
                        continue
                    lines.append(
                        f"- 技能 {skill.get('name', '')}: {skill.get('description', '')}"
                    )
            else:
                lines.append("当前会话未发现可用技能。")
        else:
            lines.append("当前会话已关闭技能自动调度。")

        plugins_enabled = bool(capabilities.get("plugins_enabled", False))
        plugins = capabilities.get("plugins") if isinstance(capabilities.get("plugins"), list) else []
        if plugins_enabled:
            if plugins:
                lines.append("当前会话可用插件：")
                for plugin in plugins[:12]:
                    if not isinstance(plugin, dict):
                        continue
                    tools = plugin.get("tools") if isinstance(plugin.get("tools"), list) else []
                    tool_names = [
                        str(tool.get("name", "")).strip()
                        for tool in tools
                        if isinstance(tool, dict) and str(tool.get("name", "")).strip()
                    ]
                    tool_text = "、".join(tool_names) if tool_names else "无显式工具"
                    lines.append(
                        f"- 插件 {plugin.get('name', '')}: {plugin.get('description', '')}。工具: {tool_text}。如需了解参数，优先查看 help 工具。"
                    )
            else:
                lines.append("当前会话未发现可用插件。")
        else:
            lines.append("当前会话已关闭插件自动调度。")

        mcp_capabilities = capabilities.get("mcp") if isinstance(capabilities.get("mcp"), dict) else {}
        if mcp_capabilities.get("platform_supported", False):
            connected_servers = (
                mcp_capabilities.get("connected_servers")
                if isinstance(mcp_capabilities.get("connected_servers"), list)
                else []
            )
            mcp_tools = mcp_capabilities.get("tools") if isinstance(mcp_capabilities.get("tools"), list) else []

            if mcp_tools:
                lines.append("平台当前已连接的 MCP 工具：")
                for tool in mcp_tools[:12]:
                    if not isinstance(tool, dict):
                        continue
                    lines.append(
                        f"- MCP {tool.get('server_name', tool.get('server_id', ''))}/{tool.get('name', '')}: {tool.get('description', '')}"
                    )
            elif connected_servers:
                server_names = [
                    str(server.get("name", "")).strip()
                    for server in connected_servers[:12]
                    if isinstance(server, dict) and str(server.get("name", "")).strip()
                ]
                if server_names:
                    lines.append(
                        "平台已连接 MCP Server，但当前没有可直接说明的 MCP 工具摘要：" + "、".join(server_names)
                    )
                else:
                    lines.append("平台已连接 MCP Server，但当前没有可直接说明的 MCP 工具摘要。")
            else:
                lines.append("平台支持 MCP Server 管理与工具发现，但当前没有已连接的 MCP Server。")

            if not mcp_capabilities.get("chat_dispatch_enabled", False):
                lines.append(
                    "注意：当前聊天链路未直接暴露自动 MCP 调度。不要谎称已经调用了某个 MCP 工具；如果用户询问能力，应说明平台支持 MCP，但本轮会话是否可直接调用取决于已连接 Server 和执行链路配置。"
                )

        lines.extend([
            "规则：",
            "1. 不要捏造已经执行过的技能、插件或 MCP 调用。",
            "2. 不要回答“我没有调用技能/插件/MCP 的能力”这类绝对否定句。",
            "3. 当某类能力当前不可用时，要说明是当前会话未启用、未连接或未暴露，而不是说平台完全不支持。",
        ])

        return "\n".join(lines)

    def _pick_effective_model(
        self,
        provider: str,
        model: str,
        selected_models: Optional[list[str]] = None,
    ) -> str:
        """
        为“provider 级配置”挑选可用模型。
        当配置里保存的是占位值 custom-model 时，优先从 selected_models 中选可用模型。
        """
        normalized_provider = str(provider or "").strip().lower()
        normalized_model = str(model or "").strip()
        candidates = [str(item or "").strip() for item in (selected_models or []) if str(item or "").strip()]

        # provider 级配置常见占位值，不能直接用于真实调用
        if normalized_model.lower() in {"custom-model", "custom_model", "custom", "default-model", "default"} or not normalized_model:
            if normalized_provider == "deepseek":
                if "deepseek-chat" in candidates:
                    return "deepseek-chat"
                if "deepseek-reasoner" in candidates:
                    return "deepseek-reasoner"
                return "deepseek-chat"
            if candidates:
                return candidates[0]

        return normalized_model

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
                logger.opt(exception=True).error(
                    f"Failed to resolve model configuration from database: {e}"
                )

        if config:
            provider = provider or config.provider
            model = model or config.model
            api_key = config.api_key
            api_endpoint = config.api_endpoint
            max_tokens = getattr(config, "max_tokens", None)
            selected_models: list[str] = []
            try:
                from billing.pricing_manager import PricingManager
                selected_models = PricingManager.parse_selected_models(getattr(config, "selected_models", None))
            except Exception:
                selected_models = []
            model = self._pick_effective_model(provider, model, selected_models)
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
                    secret = getattr(settings, field_name, None)
                    # SecretStr 类型需要调用 get_secret_value() 获取明文
                    if secret is not None:
                        api_key = secret.get_secret_value() if hasattr(secret, 'get_secret_value') else secret

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

    def _build_messages_with_history(self, prompt: str, context: Dict[str, Any]) -> list:
        """
        从上下文中提取对话历史，构建包含历史消息的 messages 列表。
        对话历史由 agent 层在调用前注入到 context["conversation_history"] 中。
        """
        messages = []
        system_prompt = self._build_agent_capability_system_prompt(context)
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        conversation_history = context.get("conversation_history", [])
        if conversation_history:
            for msg in conversation_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})
        # 始终追加当前用户输入
        messages.append({"role": "user", "content": prompt})
        return messages

    async def _call_llm_api(self, prompt: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        通过 LiteLLM 统一调用层发起非流式聊天请求。
        支持通过 context["conversation_history"] 注入对话历史。
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

        messages = self._build_messages_with_history(prompt, context)
        llm_input_payload.update({
            "provider": resolved["provider"],
            "model": resolved["model"],
        })

        result = await litellm_chat_completion(
            provider=resolved["provider"],
            model=resolved["model"],
            messages=messages,
            api_key=resolved["api_key"],
            api_base=resolved.get("api_endpoint"),
            max_tokens=self._resolve_max_tokens(resolved),
            request_id=resolved.get("request_id"),
        )

        duration_ms = int((time.perf_counter() - started_at) * 1000)

        if not result.get("ok"):
            record_model_service_metric(resolved["provider"], "chat", "error", duration_ms)
            if callable(record_hook):
                record_hook(
                    node_type="llm_call",
                    user_message=context.get("message", prompt),
                    context=context,
                    status="error",
                    error_message=result.get("error", {}).get("message"),
                    llm_input=llm_input_payload,
                    llm_output=result,
                    execution_duration_ms=duration_ms,
                    metadata={
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                    }
                )
            return result

        record_model_service_metric(resolved["provider"], "chat", "success", duration_ms)

        if callable(record_hook):
            usage = result.get("usage")
            tokens_used = usage.get("total_tokens") if isinstance(usage, dict) else None
            record_hook(
                node_type="llm_call",
                user_message=context.get("message", prompt),
                context=context,
                status="success",
                llm_input=llm_input_payload,
                llm_output=result,
                llm_tokens_used=tokens_used,
                execution_duration_ms=duration_ms,
                metadata={
                    "provider": resolved["provider"],
                    "model": resolved["model"],
                }
            )
        return result

    async def _call_llm_api_stream(self, prompt: str, context: Dict[str, Any]):
        """
        通过 LiteLLM 统一调用层发起流式聊天请求。
        支持通过 context["conversation_history"] 注入对话历史。
        向外 yield { "content": "...", "reasoning_content": "..." } 结构。
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

        messages = self._build_messages_with_history(prompt, context)
        full_content = ""
        full_reasoning = ""

        try:
            stream_gen = litellm_chat_completion_stream(
                provider=resolved["provider"],
                model=resolved["model"],
                messages=messages,
                api_key=resolved["api_key"],
                api_base=resolved.get("api_endpoint"),
                max_tokens=self._resolve_max_tokens(resolved),
                request_id=resolved.get("request_id"),
            )

            async for chunk in stream_gen:
                # 错误事件直接转发
                if "error" in chunk:
                    duration_ms = int((time.perf_counter() - started_at) * 1000)
                    record_model_service_metric(resolved["provider"], "chat_stream", "error", duration_ms)
                    if callable(record_hook):
                        record_hook(
                            node_type="llm_call",
                            user_message=context.get("message", prompt),
                            context=context,
                            status="error",
                            error_message=chunk["error"].get("message"),
                            llm_input={"prompt": prompt, "context": serialized_context},
                            llm_output=chunk,
                            execution_duration_ms=duration_ms,
                            metadata={
                                "provider": resolved["provider"],
                                "model": resolved["model"],
                                "mode": "stream",
                            }
                        )
                    yield chunk
                    return

                content = chunk.get("content", "")
                reasoning = chunk.get("reasoning_content", "")
                if content:
                    full_content += content
                if reasoning:
                    full_reasoning += reasoning
                if content or reasoning:
                    yield {"content": content, "reasoning_content": reasoning}

            duration_ms = int((time.perf_counter() - started_at) * 1000)
            record_model_service_metric(resolved["provider"], "chat_stream", "success", duration_ms)

            if callable(record_hook):
                record_hook(
                    node_type="llm_call",
                    user_message=context.get("message", prompt),
                    context=context,
                    status="success",
                    llm_input={"prompt": prompt, "context": serialized_context},
                    llm_output={
                        "ok": True,
                        "response": full_content,
                        "reasoning_content": full_reasoning,
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                    },
                    execution_duration_ms=duration_ms,
                    metadata={
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                        "mode": "stream",
                    }
                )

        except Exception as e:
            logger.bind(
                event="llm_stream_error",
                module="executor",
                error_type=type(e).__name__,
                provider=resolved.get("provider"),
                model=resolved.get("model"),
            ).opt(exception=True).error(f"LLM 流式调用异常: {e}")
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
                        "reason": str(e),
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
                    llm_input={"prompt": prompt, "context": serialized_context},
                    llm_output=output_error,
                    execution_duration_ms=duration_ms,
                    metadata={
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                        "mode": "stream",
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
            logger.bind(
                event="tool_cache_hit",
                module="executor",
                action=action,
                idempotency_key=idempotency_key[:16],
            ).debug(f"工具执行命中缓存，跳过重复执行: {action}")
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
            logger.bind(
                event="step_execution_error",
                module="executor",
                error_type=type(e).__name__,
                action=action,
            ).opt(exception=True).error(f"步骤执行异常 [{action}]: {e}")
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

        output = {
            "status": "completed",
            "response": result["response"],
            "provider": result.get("provider"),
            "model": result.get("model"),
        }
        # 传递推理内容（如果存在）
        if result.get("reasoning_content"):
            output["reasoning_content"] = result["reasoning_content"]
        return output
    
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
            logger.opt(exception=True).error(f"记录经验反馈失败: {e}")

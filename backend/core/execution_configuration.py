"""ExecutionConfigurationMixin 的单一职责实现。"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Awaitable, Callable, Dict, Optional

from loguru import logger

from config.logging import get_request_id
from config.settings import settings
from core.litellm_adapter import build_standard_error


class ExecutionConfigurationMixin:
    """由 ExecutionLayer 组合的内部协作者。"""

    def _build_error(self, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        构建统一的错误响应字典，自动注入当前请求的 request_id。
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

    def _extract_response_text(self, response_data: Dict[str, Any]) -> str:
        """
        从不同供应商的非流式响应中统一提取文本内容。
        支持 OpenAI choices[0].message.content、Anthropic content blocks、
        Google Gemini candidates[0].content.parts 三种格式。
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
        """兼容入口，委托提示构建协作者。"""
        return self.prompt_builder.build_agent_capability_system_prompt(context)

    def _normalize_subagent_model_selection(
        self,
        provider: Any,
        model: Any,
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """
        规范化子代理模型选择参数，兼容 provider:model 单字段格式。
        """
        normalized_provider = str(provider or "").strip().lower() or None
        normalized_model = str(model or "").strip() or None
        if not normalized_model or normalized_provider:
            return normalized_provider, normalized_model

        provider_candidate = None
        model_candidate = None
        if ":" in normalized_model:
            raw_provider, raw_model = normalized_model.split(":", 1)
            provider_candidate = raw_provider.strip().lower()
            model_candidate = raw_model.strip()
        elif "/" in normalized_model:
            raw_provider, raw_model = normalized_model.split("/", 1)
            known_providers = set(self.default_provider_endpoints) | set(self.provider_api_key_fields) | {"ollama", "qwen"}
            if raw_provider.strip().lower() in known_providers:
                provider_candidate = raw_provider.strip().lower()
                model_candidate = raw_model.strip()

        if provider_candidate and model_candidate:
            return provider_candidate, model_candidate

        catalog = self._get_configured_model_catalog(context or {})
        if normalized_model and not normalized_provider:
            matched_provider = self._find_provider_for_model(
                normalized_model,
                catalog,
                preferred_provider=str((context or {}).get("provider", "") or "").strip().lower() or None,
            )
            if matched_provider:
                return matched_provider, normalized_model

        return normalized_provider, normalized_model

    @staticmethod
    def _get_configured_model_catalog(context: Dict[str, Any]) -> Dict[str, Any]:
        """
        从上下文中提取已配置模型目录。
        """
        catalog = context.get("configured_model_catalog")
        if isinstance(catalog, dict):
            return catalog

        capabilities = context.get("agent_capabilities")
        if isinstance(capabilities, dict):
            nested_catalog = capabilities.get("configured_models")
            if isinstance(nested_catalog, dict):
                return nested_catalog

        return {}

    @staticmethod
    def _pick_catalog_model_for_provider(provider: Optional[str], catalog: Dict[str, Any]) -> Optional[str]:
        """
        从模型目录中挑选指定 provider 的首个可用模型。
        """
        normalized_provider = str(provider or "").strip().lower()
        if not normalized_provider:
            return None

        providers = catalog.get("providers") if isinstance(catalog.get("providers"), list) else []
        for item in providers:
            if not isinstance(item, dict):
                continue
            if str(item.get("provider", "")).strip().lower() != normalized_provider:
                continue
            models = item.get("models") if isinstance(item.get("models"), list) else []
            for model in models:
                normalized_model = str(model or "").strip()
                if normalized_model:
                    return normalized_model

        entries = catalog.get("entries") if isinstance(catalog.get("entries"), list) else []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("provider", "")).strip().lower() != normalized_provider:
                continue
            normalized_model = str(entry.get("model", "")).strip()
            if normalized_model:
                return normalized_model

        return None

    @staticmethod
    def _find_provider_for_model(
        model: Optional[str],
        catalog: Dict[str, Any],
        preferred_provider: Optional[str] = None,
    ) -> Optional[str]:
        """
        在模型目录中查找模型所属 provider。
        若存在多个候选，则优先返回 preferred_provider。
        """
        normalized_model = str(model or "").strip()
        if not normalized_model:
            return None

        matches: list[str] = []
        entries = catalog.get("entries") if isinstance(catalog.get("entries"), list) else []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("model", "")).strip() != normalized_model:
                continue
            provider = str(entry.get("provider", "")).strip().lower()
            if provider and provider not in matches:
                matches.append(provider)

        if preferred_provider and preferred_provider in matches:
            return preferred_provider
        if len(matches) == 1:
            return matches[0]
        return None

    def _resolve_subagent_model_selection(
        self,
        context: Dict[str, Any],
        provider: Any,
        model: Any,
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """
        解析子代理的最终 provider/model。
        若无法确定，返回明确错误信息而不是静默回退。
        """
        catalog = self._get_configured_model_catalog(context)
        provider, model = self._normalize_subagent_model_selection(provider, model, context)
        current_provider, current_model = self._normalize_subagent_model_selection(
            context.get("provider"),
            context.get("model"),
            context,
        )

        if not provider and model:
            provider = self._find_provider_for_model(model, catalog, preferred_provider=current_provider)

        if not provider and current_provider:
            provider = current_provider
        if not model and current_model:
            model = current_model

        if provider and not model:
            model = self._pick_catalog_model_for_provider(provider, catalog)

        if not provider or not model:
            resolved = self._resolve_llm_configuration(
                {
                    **context,
                    "provider": provider or current_provider or context.get("provider"),
                    "model": model,
                }
            )
            if resolved.get("ok"):
                resolved_provider = str(resolved.get("provider", "")).strip().lower() or None
                resolved_model = str(resolved.get("model", "")).strip() or None
                if not provider:
                    provider = resolved_provider
                if not model:
                    model = resolved_model

        if not provider and model:
            provider = self._find_provider_for_model(model, catalog, preferred_provider=current_provider)
        if provider and not model:
            model = self._pick_catalog_model_for_provider(provider, catalog)

        if not provider or not model:
            return None, None, "未能解析子代理模型，请指定 provider/model 参数或确保主会话已配置模型"

        return provider, model, None

    async def _consume_foreground_subagent_stream(
        self,
        stream: Any,
        tool_name: str,
        on_subagent_event: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """
        消费前台子代理生成器，实时转发子代理事件，并返回最终摘要结果。
        """
        agent_id: Optional[str] = None
        agent_type: Optional[str] = None
        summary = ""
        state = "completed"

        try:
            async for chunk in stream:
                if not isinstance(chunk, dict):
                    continue

                chunk_type = str(chunk.get("type") or "").strip()
                if chunk_type in {"subagent_start", "agent_message", "subagent_stop"}:
                    agent_id = str(chunk.get("agent_id") or agent_id or "").strip() or agent_id
                    agent_type = str(chunk.get("agent_type") or agent_type or "").strip() or agent_type
                    if chunk_type == "subagent_stop":
                        summary = str(chunk.get("summary") or summary or "").strip()
                        state = str(chunk.get("state") or state or "completed").strip().lower() or "completed"
                    if callable(on_subagent_event):
                        await on_subagent_event(chunk)
                    continue

                if chunk_type == "error":
                    state = "failed"
                    error_message = str(chunk.get("error") or "子代理执行失败").strip() or "子代理执行失败"
                    summary = summary or error_message
                    # 转发错误事件到前端，确保实时可见
                    if callable(on_subagent_event):
                        await on_subagent_event(chunk)

            if not agent_id:
                return {
                    "ok": False,
                    "error": "前台子代理未返回可追踪的 agent_id",
                    "tool_name": tool_name,
                }

            result_payload = {
                "agent_id": agent_id,
                "agent_type": agent_type,
                "run_mode": "foreground",
                "status": state,
                "summary": summary,
                "message": summary or ("子代理执行完成" if state == "completed" else "子代理执行失败"),
            }

            logger.bind(
                module="executor",
                event="subagent_foreground_completed",
                agent_id=agent_id,
                agent_type=agent_type,
                state=state,
            ).info(f"前台子代理执行结束: {agent_id}")

            if state in {"failed", "error", "stopped", "timeout"}:
                return {
                    "ok": False,
                    "error": summary or "子代理执行失败",
                    "result": result_payload,
                    "tool_name": tool_name,
                }

            return {
                "ok": True,
                "result": result_payload,
                "tool_name": tool_name,
            }
        finally:
            aclose = getattr(stream, "aclose", None)
            if callable(aclose):
                await aclose()

    def _pick_effective_model(
        self,
        provider: str,
        model: str,
        selected_models: Optional[list[str]] = None,
    ) -> str:
        """
        为 provider 挑选可用模型：若传入模型名为空，从 selected_models 中选。
        """
        normalized_provider = str(provider or "").strip().lower()
        normalized_model = str(model or "").strip()
        candidates = [str(item or "").strip() for item in (selected_models or []) if str(item or "").strip()]

        if not normalized_model:
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
        从上下文中解析完整的 LLM 配置（provider/model/api_key/api_endpoint）。
        优先级：DB 精确匹配 → DB 默认配置 → 全局 settings → 内置供应商端点，
        任一环节缺失则返回包含标准错误对象的失败结果。
        """
        from config.settings import settings

        provider = context.get("provider")
        model = context.get("model")
        db = context.get("db")
        config = None

        pricing_manager = None
        if db:
            try:
                from billing.pricing_manager import PricingManager
                pricing_manager = PricingManager(db)
                if provider and model:
                    config = pricing_manager.get_configuration_by_provider_model(provider, model)
                if not config and provider:
                    # 未找到精确的 provider+model 配置，回退到该 provider 的默认配置
                    config = pricing_manager.get_default_provider_configuration(provider)
                if not config:
                    config = pricing_manager.get_default_configuration()
            except Exception as e:
                logger.opt(exception=True).error(
                    f"从数据库解析模型配置失败: {e}"
                )

        if config:
            provider = provider or config.provider
            model = model or config.model
            # 从加密存储中解密 API 密钥
            raw_key = config.api_key or ""
            if raw_key:
                # 旧算法密文已失效（SECRET_KEY 拆分后无法解密），提前返回明确错误，
                # 避免被 decrypt_secret_value 静默吞掉导致空头请求 LLM 网关
                if raw_key.startswith("enc:"):
                    return {
                        "ok": False,
                        "error": self._build_error(
                            "llm_api_key_stale",
                            "API Key 已失效，请在设置页重新录入",
                            {"provider": provider, "model": model}
                        )
                    }
                from config.security import decrypt_secret_value
                api_key = decrypt_secret_value(raw_key)
                # raw_key 非空但解密结果为空，说明密钥损坏或 SECRET_KEY 变更，必须向上报告
                if not api_key:
                    return {
                        "ok": False,
                        "error": self._build_error(
                            "llm_api_key_decrypt_failed",
                            "API Key 解密失败，可能因 SECRET_KEY 变更导致密钥损坏",
                            {
                                "provider": provider,
                                "model": model,
                            }
                        )
                    }
            else:
                # 当 ModelConfiguration 中没有 API Key 时，尝试从 ProviderCredential 表读取
                api_key = None
                try:
                    cred = pricing_manager.get_provider_credential(provider)
                    if cred and cred.api_key:
                        # 旧算法密文已失效，提前返回明确错误，避免被 decrypt 静默吞掉
                        if cred.api_key.startswith("enc:"):
                            return {
                                "ok": False,
                                "error": self._build_error(
                                    "llm_api_key_stale",
                                    "API Key 已失效，请在设置页重新录入",
                                    {"provider": provider, "model": model}
                                )
                            }
                        from config.security import decrypt_secret_value
                        api_key = decrypt_secret_value(cred.api_key)
                        if api_key:
                            logger.info(f"已从 ProviderCredential 表为 {provider} 解析 API Key")
                        else:
                            # 凭据存在但解密失败，密钥损坏，必须向上报告
                            return {
                                "ok": False,
                                "error": self._build_error(
                                    "llm_api_key_decrypt_failed",
                                    "ProviderCredential 中的 API Key 解密失败，可能因 SECRET_KEY 变更导致密钥损坏",
                                    {
                                        "provider": provider,
                                        "model": model,
                                    }
                                )
                            }
                except Exception as e:
                    logger.warning(f"从 ProviderCredential 表解析 API Key 失败: {e}")
            api_endpoint = config.api_endpoint
            max_tokens = getattr(config, "max_tokens_limit", None)
            selected_models: list[str] = []
            try:
                selected_models = PricingManager.parse_selected_models(getattr(config, "selected_models", None))
            except Exception as e:
                logger.warning(f"解析 selected_models 失败，已降级为空列表: {e}")
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

    def _build_auto_execution_system_prompt(self, auto_execution_results: Dict[str, Any]) -> str:
        """兼容入口，委托提示构建协作者。"""
        return self.prompt_builder.build_auto_execution_system_prompt(
            auto_execution_results
        )

    def _build_relevant_memories_system_prompt(self, context: Dict[str, Any]) -> str:
        """兼容入口，委托提示构建协作者。"""
        return self.prompt_builder.build_relevant_memories_system_prompt(context)

    def _build_recent_short_term_memories_system_prompt(
        self, context: Dict[str, Any]
    ) -> str:
        """兼容入口，委托提示构建协作者。"""
        return self.prompt_builder.build_recent_short_term_memories_system_prompt(
            getattr(self, "memory_manager", None),
            context,
        )

    def _build_messages_with_history(self, prompt: str, context: Dict[str, Any]) -> list:
        """兼容入口，委托提示构建协作者。"""
        return self.prompt_builder.build_messages(
            prompt,
            context,
            memory_manager=getattr(self, "memory_manager", None),
        )

"""复用 OpenAwA 主平台模型配置的 OpenBiliClaw LLM 提供者。"""

from __future__ import annotations

from typing import Any

from config.security import decrypt_secret_value
from db.models import SessionLocal

from .base import LLMProvider, LLMProviderError, LLMResponse


class OpenAwAProvider(LLMProvider):
    """按请求读取主平台当前默认模型，避免复制或持久化用户密钥。"""

    @property
    def name(self) -> str:
        return "openawa"

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
        reasoning_effort: str | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        """通过主平台统一调用层执行请求，密钥只在内存中短暂存在。"""
        from billing.pricing_manager import PricingManager
        from core.litellm_adapter import litellm_chat_completion

        db = SessionLocal()
        try:
            pricing_manager = PricingManager(db)
            configuration = pricing_manager.get_default_configuration()
            if configuration is None:
                raise LLMProviderError("OpenAwA 未配置默认聊天模型")

            provider = str(configuration.provider or "").strip().lower()
            configured_model = str(model or configuration.model or "").strip()
            if not provider or not configured_model:
                raise LLMProviderError("OpenAwA 默认模型配置不完整")

            encrypted_key = str(configuration.api_key or "")
            endpoint = configuration.api_endpoint
            if not encrypted_key:
                credential = pricing_manager.get_provider_credential(provider)
                if credential is not None:
                    encrypted_key = str(credential.api_key or "")
                    endpoint = endpoint or credential.api_endpoint

            if not encrypted_key or encrypted_key.startswith("enc:"):
                raise LLMProviderError(f"OpenAwA 供应商 {provider} 未配置可用凭据")
            api_key = decrypt_secret_value(encrypted_key)
            if not api_key:
                raise LLMProviderError(f"OpenAwA 供应商 {provider} 的凭据无法解密")

            result: dict[str, Any] = await litellm_chat_completion(
                provider=provider,
                model=configured_model,
                messages=messages,
                api_key=api_key,
                api_base=endpoint,
                temperature=temperature,
                max_tokens=max_tokens,
                thinking_params={"reasoning_effort": reasoning_effort}
                if reasoning_effort is not None
                else None,
            )
        finally:
            db.close()

        if not result.get("ok"):
            error = result.get("error") or {}
            raise LLMProviderError(str(error.get("message") or "OpenAwA 模型调用失败"))

        return LLMResponse(
            content=str(result.get("response") or ""),
            model=configured_model,
            provider=provider,
            usage=result.get("usage"),
            raw=result,
        )

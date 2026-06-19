"""
OpenRouter Provider 适配器。
通过 OpenRouter API 调用多个 LLM 模型，OpenAI 兼容格式。
"""

import asyncio
import re
import time
from typing import Any, Dict, Optional, Type, TypeVar

import httpx
from loguru import logger
from pydantic import BaseModel

from llm.base import LLMProvider, LLMRequest
from llm.response import LLMResponse, TokenUsage
from llm.exceptions import (
    LLMError,
    RateLimitError,
    StructuredOutputError,
    AuthenticationError,
    TimeoutError as LLMTimeoutError,
)
from llm.json_utils import parse_structured_output

T = TypeVar("T", bound=BaseModel)


class OpenRouterProvider(LLMProvider):
    """
    OpenRouter Provider 适配器。
    通过 OpenRouter API 调用多个 LLM 模型，支持 OpenAI 兼容格式。
    """

    def __init__(
        self,
        model: str = "openai/gpt-4o",
        api_key: str = "",
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: float = 60.0,
        max_retries: int = 3,
        http_referer: str = "",
        app_title: str = "Open-AwA",
        **kwargs,
    ):
        """
        初始化 OpenRouter Provider。

        Args:
            model: 模型名称（如 "openai/gpt-4o", "anthropic/claude-3-opus"）
            api_key: OpenRouter API 密钥
            base_url: OpenRouter API 地址
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
            http_referer: HTTP Referer 头（可选）
            app_title: 应用标题（可选，用于 OpenRouter 统计）
            **kwargs: 其他 Provider 特定参数
        """
        super().__init__(
            provider_name="openrouter",
            model=model,
            api_key=api_key,
            **kwargs,
        )

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if http_referer:
            headers["HTTP-Referer"] = http_referer
        if app_title:
            headers["X-Title"] = app_title

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(timeout),
        )

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """生成文本响应。"""
        started_at = time.perf_counter()

        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "stream": request.stream,
        }

        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.stop_sequences:
            payload["stop"] = request.stop_sequences

        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = await asyncio.wait_for(
                    self._client.post("/chat/completions", json=payload),
                    timeout=self.timeout,
                )

                if response.status_code == 401:
                    raise AuthenticationError(
                        message="OpenRouter API 认证失败",
                        provider=self.provider_name,
                        model=self.model,
                    )

                if response.status_code == 429:
                    raise RateLimitError(
                        message="OpenRouter API 速率限制",
                        provider=self.provider_name,
                        model=self.model,
                    )

                if response.status_code != 200:
                    raise LLMError(
                        f"OpenRouter API 返回错误状态: {response.status_code}",
                        provider=self.provider_name,
                        model=self.model,
                    )

                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

                usage_data = TokenUsage(
                    prompt_tokens=data.get("usage", {}).get("prompt_tokens", 0),
                    completion_tokens=data.get("usage", {}).get("completion_tokens", 0),
                    total_tokens=data.get("usage", {}).get("total_tokens", 0),
                )

                duration_ms = int((time.perf_counter() - started_at) * 1000)

                return LLMResponse(
                    content=content,
                    usage=usage_data,
                    latency_ms=duration_ms,
                    model=self.model,
                    provider=self.provider_name,
                    success=True,
                    raw_response=data,
                )

            except asyncio.TimeoutError:
                last_error = LLMTimeoutError(
                    f"OpenRouter API 请求超时（{self.timeout}秒）",
                    provider=self.provider_name,
                    model=self.model,
                    timeout=self.timeout,
                )
                logger.warning(f"OpenRouter API 超时（尝试 {attempt + 1}/{self.max_retries}）")

            except RateLimitError:
                last_error = RateLimitError(
                    message="OpenRouter API 速率限制",
                    provider=self.provider_name,
                    model=self.model,
                )
                logger.warning(f"OpenRouter API 速率限制（尝试 {attempt + 1}/{self.max_retries}）")

            except AuthenticationError:
                raise

            except Exception as e:
                last_error = LLMError(
                    f"OpenRouter API 调用失败: {e}",
                    provider=self.provider_name,
                    model=self.model,
                )
                logger.warning(f"OpenRouter API 错误（尝试 {attempt + 1}/{self.max_retries}）: {e}")

            if attempt < self.max_retries - 1:
                wait_time = (2 ** attempt) + (0.1 * attempt)
                await asyncio.sleep(wait_time)

        duration_ms = int((time.perf_counter() - started_at) * 1000)
        logger.error(f"OpenRouter API 调用最终失败: {last_error}")

        return LLMResponse.error_response(
            error_msg=str(last_error) if last_error else "未知错误",
            provider=self.provider_name,
            model=self.model,
        )

    async def generate_structured(self, request: LLMRequest, schema: Type[T]) -> T:
        """生成结构化输出。"""
        schema_json = schema.model_json_schema()
        structured_prompt = (
            f"{request.prompt}\n\n"
            f"请以 JSON 格式返回，符合以下 schema：\n"
            f"```json\n{schema_json}\n```\n"
            f"只返回 JSON，不要其他说明文字。"
        )

        structured_request = LLMRequest(
            prompt=structured_prompt,
            system_prompt=request.system_prompt,
            max_tokens=request.max_tokens,
            temperature=request.temperature if request.temperature is not None else 0.0,
            top_p=request.top_p,
            top_k=request.top_k,
            stream=False,
            stop_sequences=request.stop_sequences,
            extra_params=request.extra_params,
        )

        response = await self.generate(structured_request)

        if not response.success:
            raise LLMError(
                f"结构化输出生成失败: {response.error}",
                provider=self.provider_name,
                model=self.model,
            )

        try:
            return parse_structured_output(response.content, schema)
        except StructuredOutputError:
            raise
        except Exception as e:
            raise StructuredOutputError(
                f"结构化输出解析失败: {e}",
                raw_output=response.content,
                reason="parse_error",
                provider=self.provider_name,
                model=self.model,
            )

    async def health_check(self) -> bool:
        """检查 Provider 健康状态。"""
        try:
            test_request = LLMRequest(prompt="Hello", max_tokens=5, temperature=0.0)
            response = await self.generate(test_request)
            return response.success
        except Exception as e:
            logger.warning(f"OpenRouter 健康检查失败: {e}")
            return False

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """清理 HTTP 客户端资源。"""
        await self._client.aclose()
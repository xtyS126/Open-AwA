"""
Ollama 本地模型 Provider 适配器实现。
调用本地 Ollama API（默认 http://localhost:11434）。
"""

import asyncio
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


class OllamaProvider(LLMProvider):
    """
    Ollama 本地模型 Provider 实现。
    支持自定义模型名称和本地 API 调用。
    """

    def __init__(
        self,
        model: str = "llama3",
        api_key: str = "",
        base_url: str = "http://localhost:11434",
        timeout: float = 60.0,
        max_retries: int = 3,
        **kwargs
    ):
        """
        初始化 Ollama Provider。

        Args:
            model: 模型名称（如 "llama3", "qwen2", "mistral"）
            api_key: API 密钥（Ollama 本地通常不需要，保留兼容性）
            base_url: Ollama API 地址（默认 http://localhost:11434）
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
            **kwargs: 其他 Provider 特定参数
        """
        super().__init__(
            provider_name="ollama",
            model=model,
            api_key=api_key,
            **kwargs
        )

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries

        # 初始化 HTTP 客户端
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout),
        )

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """
        生成文本响应。

        Args:
            request: LLM 请求参数

        Returns:
            LLMResponse: 包含生成内容、token 用量等信息

        Raises:
            LLMError: LLM 调用失败
            RateLimitError: 触发速率限制
        """
        started_at = time.perf_counter()

        # 构造消息列表
        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        # 构造请求体
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_predict": request.max_tokens,
            }
        }

        if request.temperature is not None:
            payload["options"]["temperature"] = request.temperature

        if request.top_p is not None:
            payload["options"]["top_p"] = request.top_p

        if request.stop_sequences:
            payload["options"]["stop"] = request.stop_sequences

        # 指数退避重试
        last_error = None
        for attempt in range(self.max_retries):
            try:
                # 发送请求
                response = await asyncio.wait_for(
                    self._client.post("/api/chat", json=payload),
                    timeout=self.timeout
                )

                # 检查响应状态
                if response.status_code == 429:
                    raise RateLimitError(
                        message="Ollama API 速率限制",
                        provider=self.provider_name,
                        model=self.model,
                    )

                if response.status_code != 200:
                    raise LLMError(
                        f"Ollama API 返回错误状态: {response.status_code} - {response.text}",
                        provider=self.provider_name,
                        model=self.model,
                    )

                # 解析响应
                data = response.json()
                content = data.get("message", {}).get("content", "")

                # 提取 token 用量
                usage_data = TokenUsage(
                    prompt_tokens=data.get("prompt_eval_count", 0),
                    completion_tokens=data.get("eval_count", 0),
                    total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
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
                    f"Ollama API 请求超时（{self.timeout}秒）",
                    provider=self.provider_name,
                    model=self.model,
                    timeout=self.timeout,
                )
                logger.warning(
                    f"Ollama API 超时（尝试 {attempt + 1}/{self.max_retries}）"
                )

            except RateLimitError:
                last_error = RateLimitError(
                    message="Ollama API 速率限制",
                    provider=self.provider_name,
                    model=self.model,
                )
                logger.warning(
                    f"Ollama API 速率限制（尝试 {attempt + 1}/{self.max_retries}）"
                )

            except httpx.ConnectError as e:
                last_error = LLMError(
                    f"无法连接到 Ollama 服务（{self.base_url}）: {e}",
                    provider=self.provider_name,
                    model=self.model,
                )
                logger.error(f"Ollama 连接失败: {e}")
                # 连接错误不重试
                break

            except Exception as e:
                last_error = LLMError(
                    f"Ollama API 调用失败: {e}",
                    provider=self.provider_name,
                    model=self.model,
                )
                logger.warning(
                    f"Ollama API 错误（尝试 {attempt + 1}/{self.max_retries}）: {e}"
                )

            # 指数退避等待
            if attempt < self.max_retries - 1:
                wait_time = (2 ** attempt) + (0.1 * attempt)
                await asyncio.sleep(wait_time)

        # 所有重试都失败
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        logger.error(f"Ollama API 调用最终失败: {last_error}")

        return LLMResponse.error_response(
            error_msg=str(last_error) if last_error else "未知错误",
            provider=self.provider_name,
            model=self.model,
        )

    async def generate_structured(
        self, request: LLMRequest, schema: Type[T]
    ) -> T:
        """
        生成结构化输出（JSON 格式）。

        Args:
            request: LLM 请求参数
            schema: Pydantic 模型类，用于验证输出

        Returns:
            T: 符合 schema 的 Pydantic 模型实例

        Raises:
            StructuredOutputError: 结构化输出解析失败
            LLMError: LLM 调用失败
        """
        # 在提示中明确要求 JSON 输出
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

        # 解析 JSON 输出
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
        """
        检查 Provider 健康状态。

        Returns:
            bool: True 表示健康，False 表示不可用
        """
        try:
            # 检查 Ollama 服务是否运行
            response = await asyncio.wait_for(
                self._client.get("/api/tags"),
                timeout=5.0
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"Ollama 健康检查失败: {e}")
            return False

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """清理 HTTP 客户端资源。"""
        await self._client.aclose()

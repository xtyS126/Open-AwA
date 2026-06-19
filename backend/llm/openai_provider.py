"""
OpenAI 兼容 Provider 适配器。

支持 OpenAI API 格式的 LLM 调用，包括：
- 流式和非流式输出
- 扩展思考（thinking）参数
- 结构化输出（JSON 格式）
- 指数退避重试
- Token 用量和延迟统计
"""

import asyncio
import json
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Type, TypeVar

import httpx
from loguru import logger
from pydantic import BaseModel

from llm.base import LLMProvider, LLMRequest
from llm.exceptions import (
    LLMError,
    RateLimitError,
    StructuredOutputError,
    AuthenticationError,
    TimeoutError,
)
from llm.json_utils import parse_structured_output
from llm.response import LLMResponse, TokenUsage

T = TypeVar("T", bound=BaseModel)


class OpenAIProvider(LLMProvider):
    """
    OpenAI 兼容 Provider 适配器。
    
    支持 OpenAI API 格式的 LLM 调用，包括 GPT-4/3.5、DeepSeek 等兼容接口。
    """

    def __init__(
        self,
        provider_name: str,
        model: str,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 60.0,
        max_retries: int = 3,
        **kwargs,
    ):
        """
        初始化 OpenAI Provider。

        Args:
            provider_name: Provider 名称（如 "openai"、"deepseek"）
            model: 模型名称（如 "gpt-4"、"deepseek-chat"）
            api_key: API 密钥
            base_url: API 基础 URL
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
            **kwargs: 其他 Provider 特定参数
        """
        super().__init__(provider_name, model, api_key, **kwargs)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        
        # 创建 httpx 异步客户端
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout),
        )

    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口，关闭客户端"""
        await self.client.aclose()

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """
        生成文本响应。

        支持流式和非流式输出，记录 token 用量和延迟。

        Args:
            request: LLM 请求参数

        Returns:
            LLMResponse: 包含生成内容、token 用量等信息

        Raises:
            LLMError: LLM 调用失败
            RateLimitError: 触发速率限制
        """
        start_time = time.perf_counter()
        
        # 构建 API 请求参数
        api_params = self._build_request_params(request)
        
        # 执行请求（带重试）
        if request.stream:
            return await self._handle_stream_request(api_params, request, start_time)
        else:
            return await self._handle_normal_request(api_params, request, start_time)

    def _build_request_params(self, request: LLMRequest) -> Dict[str, Any]:
        """
        构建 OpenAI API 请求参数。

        Args:
            request: LLM 请求参数

        Returns:
            Dict[str, Any]: API 请求参数字典
        """
        # 构建消息列表
        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        params: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "stream": request.stream,
        }

        # 可选参数
        if request.temperature is not None:
            params["temperature"] = request.temperature
        if request.top_p is not None:
            params["top_p"] = request.top_p
        if request.stop_sequences:
            params["stop"] = request.stop_sequences

        # 扩展思考参数（某些模型支持）
        if request.thinking_enabled and request.thinking_budget_tokens:
            params["thinking"] = {
                "type": "enabled",
                "budget_tokens": request.thinking_budget_tokens,
            }

        # 额外参数透传
        if request.extra_params:
            params.update(request.extra_params)

        return params

    async def _handle_normal_request(
        self, api_params: Dict[str, Any], request: LLMRequest, start_time: float
    ) -> LLMResponse:
        """
        处理非流式请求。

        Args:
            api_params: API 请求参数
            request: LLM 请求参数
            start_time: 请求开始时间

        Returns:
            LLMResponse: LLM 响应

        Raises:
            LLMError: LLM 调用失败
        """
        last_error: Optional[Exception] = None
        
        # 指数退避重试
        for attempt in range(self.max_retries):
            try:
                response = await self.client.post("/chat/completions", json=api_params)
                response.raise_for_status()
                
                data = response.json()
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                
                # 提取响应内容
                choice = data.get("choices", [{}])[0]
                message = choice.get("message", {})
                content = message.get("content", "")
                
                # 提取 thinking 内容（如果存在）
                thinking_content = message.get("reasoning_content")
                
                # 提取 token 用量
                usage_data = data.get("usage", {})
                usage = TokenUsage(
                    prompt_tokens=usage_data.get("prompt_tokens", 0),
                    completion_tokens=usage_data.get("completion_tokens", 0),
                    total_tokens=usage_data.get("total_tokens", 0),
                )
                
                logger.bind(
                    provider=self.provider_name,
                    model=self.model,
                    latency_ms=latency_ms,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                ).debug("OpenAI API 调用成功")
                
                return LLMResponse(
                    content=content,
                    usage=usage,
                    latency_ms=latency_ms,
                    model=data.get("model", self.model),
                    provider=self.provider_name,
                    success=True,
                    thinking_content=thinking_content,
                    raw_response=data,
                    finish_reason=choice.get("finish_reason"),
                )
            
            except httpx.HTTPStatusError as e:
                last_error = e
                status_code = e.response.status_code
                
                # 401 认证失败，不重试
                if status_code == 401:
                    raise AuthenticationError(
                        f"API 认证失败: {e.response.text}",
                        provider=self.provider_name,
                        model=self.model,
                    )
                
                # 429 速率限制，可重试
                if status_code == 429:
                    if attempt < self.max_retries - 1:
                        wait_time = self._calculate_backoff(attempt)
                        logger.bind(
                            provider=self.provider_name,
                            model=self.model,
                            attempt=attempt + 1,
                            wait_time=wait_time,
                        ).warning("触发速率限制，等待重试")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        raise RateLimitError(
                            f"速率限制: {e.response.text}",
                            provider=self.provider_name,
                            model=self.model,
                        )
                
                # 5xx 服务器错误，可重试
                if 500 <= status_code < 600:
                    if attempt < self.max_retries - 1:
                        wait_time = self._calculate_backoff(attempt)
                        logger.bind(
                            provider=self.provider_name,
                            model=self.model,
                            attempt=attempt + 1,
                            wait_time=wait_time,
                            status_code=status_code,
                        ).warning("服务器错误，等待重试")
                        await asyncio.sleep(wait_time)
                        continue
                
                # 其他错误，直接抛出
                raise LLMError(
                    f"API 请求失败 [{status_code}]: {e.response.text}",
                    provider=self.provider_name,
                    model=self.model,
                )
            
            except httpx.TimeoutException as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    wait_time = self._calculate_backoff(attempt)
                    logger.bind(
                        provider=self.provider_name,
                        model=self.model,
                        attempt=attempt + 1,
                        wait_time=wait_time,
                    ).warning("请求超时，等待重试")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    raise TimeoutError(
                        f"请求超时: {e}",
                        provider=self.provider_name,
                        model=self.model,
                        timeout=self.timeout,
                    )
            
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    wait_time = self._calculate_backoff(attempt)
                    logger.bind(
                        provider=self.provider_name,
                        model=self.model,
                        attempt=attempt + 1,
                        wait_time=wait_time,
                    ).warning("请求异常，等待重试")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    raise LLMError(
                        f"LLM 调用失败: {e}",
                        provider=self.provider_name,
                        model=self.model,
                    )
        
        # 所有重试都失败
        raise LLMError(
            f"LLM 调用失败，已重试 {self.max_retries} 次: {last_error}",
            provider=self.provider_name,
            model=self.model,
        )

    async def _handle_stream_request(
        self, api_params: Dict[str, Any], request: LLMRequest, start_time: float
    ) -> LLMResponse:
        """
        处理流式请求。

        读取 SSE 流，拼接完整内容，统计 token 用量。

        Args:
            api_params: API 请求参数
            request: LLM 请求参数
            start_time: 请求开始时间

        Returns:
            LLMResponse: LLM 响应（包含完整流式内容）

        Raises:
            LLMError: LLM 调用失败
        """
        last_error: Optional[Exception] = None
        
        # 指数退避重试
        for attempt in range(self.max_retries):
            try:
                async with self.client.stream("POST", "/chat/completions", json=api_params) as response:
                    response.raise_for_status()
                    
                    # 读取 SSE 流
                    content_parts = []
                    thinking_parts = []
                    usage_data = {}
                    finish_reason = None
                    
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        
                        data_str = line[6:]  # 移除 "data: " 前缀
                        if data_str.strip() == "[DONE]":
                            break
                        
                        try:
                            data = json.loads(data_str)
                            choice = data.get("choices", [{}])[0]
                            delta = choice.get("delta", {})
                            
                            # 提取内容
                            if "content" in delta:
                                content_parts.append(delta["content"])
                            
                            # 提取 thinking 内容
                            if "reasoning_content" in delta:
                                thinking_parts.append(delta["reasoning_content"])
                            
                            # 提取完成原因
                            if "finish_reason" in choice:
                                finish_reason = choice["finish_reason"]
                            
                            # 提取用量（某些 API 在最后一个 chunk 返回）
                            if "usage" in data:
                                usage_data = data["usage"]
                        
                        except json.JSONDecodeError:
                            logger.bind(
                                provider=self.provider_name,
                                model=self.model,
                                data=data_str[:200],
                            ).warning("SSE 数据解析失败")
                            continue
                    
                    latency_ms = int((time.perf_counter() - start_time) * 1000)
                    content = "".join(content_parts)
                    thinking_content = "".join(thinking_parts) if thinking_parts else None
                    
                    # 构建 token 用量
                    usage = TokenUsage(
                        prompt_tokens=usage_data.get("prompt_tokens", 0),
                        completion_tokens=usage_data.get("completion_tokens", 0),
                        total_tokens=usage_data.get("total_tokens", 0),
                    )
                    
                    logger.bind(
                        provider=self.provider_name,
                        model=self.model,
                        latency_ms=latency_ms,
                        stream=True,
                        prompt_tokens=usage.prompt_tokens,
                        completion_tokens=usage.completion_tokens,
                    ).debug("OpenAI API 流式调用成功")
                    
                    return LLMResponse(
                        content=content,
                        usage=usage,
                        latency_ms=latency_ms,
                        model=self.model,
                        provider=self.provider_name,
                        success=True,
                        thinking_content=thinking_content,
                        finish_reason=finish_reason,
                    )
            
            except httpx.HTTPStatusError as e:
                last_error = e
                status_code = e.response.status_code
                
                # 401 认证失败，不重试
                if status_code == 401:
                    raise AuthenticationError(
                        f"API 认证失败: {e.response.text}",
                        provider=self.provider_name,
                        model=self.model,
                    )
                
                # 429 速率限制，可重试
                if status_code == 429:
                    if attempt < self.max_retries - 1:
                        wait_time = self._calculate_backoff(attempt)
                        logger.bind(
                            provider=self.provider_name,
                            model=self.model,
                            attempt=attempt + 1,
                            wait_time=wait_time,
                        ).warning("触发速率限制，等待重试")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        raise RateLimitError(
                            f"速率限制: {e.response.text}",
                            provider=self.provider_name,
                            model=self.model,
                        )
                
                # 5xx 服务器错误，可重试
                if 500 <= status_code < 600:
                    if attempt < self.max_retries - 1:
                        wait_time = self._calculate_backoff(attempt)
                        logger.bind(
                            provider=self.provider_name,
                            model=self.model,
                            attempt=attempt + 1,
                            wait_time=wait_time,
                            status_code=status_code,
                        ).warning("服务器错误，等待重试")
                        await asyncio.sleep(wait_time)
                        continue
                
                # 其他错误，直接抛出
                raise LLMError(
                    f"API 请求失败 [{status_code}]: {e.response.text}",
                    provider=self.provider_name,
                    model=self.model,
                )
            
            except httpx.TimeoutException as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    wait_time = self._calculate_backoff(attempt)
                    logger.bind(
                        provider=self.provider_name,
                        model=self.model,
                        attempt=attempt + 1,
                        wait_time=wait_time,
                    ).warning("请求超时，等待重试")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    raise TimeoutError(
                        f"请求超时: {e}",
                        provider=self.provider_name,
                        model=self.model,
                        timeout=self.timeout,
                    )
            
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    wait_time = self._calculate_backoff(attempt)
                    logger.bind(
                        provider=self.provider_name,
                        model=self.model,
                        attempt=attempt + 1,
                        wait_time=wait_time,
                    ).warning("请求异常，等待重试")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    raise LLMError(
                        f"LLM 调用失败: {e}",
                        provider=self.provider_name,
                        model=self.model,
                    )
        
        # 所有重试都失败
        raise LLMError(
            f"LLM 调用失败，已重试 {self.max_retries} 次: {last_error}",
            provider=self.provider_name,
            model=self.model,
        )

    async def generate_structured(self, request: LLMRequest, schema: Type[T]) -> T:
        """
        生成结构化输出（JSON 格式）。

        使用 json_utils 容错解析，支持 Pydantic schema 验证。

        Args:
            request: LLM 请求参数
            schema: Pydantic 模型类，用于验证输出

        Returns:
            T: 符合 schema 的 Pydantic 模型实例

        Raises:
            StructuredOutputError: 结构化输出解析失败
            LLMError: LLM 调用失败
        """
        # 在 system_prompt 中追加 JSON 输出指令
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)
        json_instruction = (
            f"\n\n你必须以 JSON 格式输出，严格符合以下 schema：\n"
            f"```json\n{schema_json}\n```\n"
            f"只输出 JSON，不要包含任何其他文字。"
        )
        
        if request.system_prompt:
            enhanced_system = request.system_prompt + json_instruction
        else:
            enhanced_system = json_instruction.strip()
        
        # 创建新的请求，增强 system_prompt
        enhanced_request = LLMRequest(
            prompt=request.prompt,
            system_prompt=enhanced_system,
            max_tokens=request.max_tokens,
            temperature=request.temperature if request.temperature is not None else 0.0,
            top_p=request.top_p,
            top_k=request.top_k,
            stream=False,  # 结构化输出禁用流式
            stop_sequences=request.stop_sequences,
            thinking_budget_tokens=request.thinking_budget_tokens,
            thinking_enabled=request.thinking_enabled,
            extra_params=request.extra_params,
        )
        
        # 调用普通 generate
        response = await self.generate(enhanced_request)
        
        if not response.success:
            raise LLMError(
                response.error or "LLM 调用失败",
                provider=self.provider_name,
                model=self.model,
            )
        
        # 使用 json_utils 容错解析
        return parse_structured_output(response.content, schema)

    async def health_check(self) -> bool:
        """
        检查 Provider 健康状态。

        发送一个轻量级请求来验证 API 可用性。

        Returns:
            bool: True 表示健康，False 表示不可用
        """
        try:
            # 发送一个极简请求，验证 API 连通性
            test_request = LLMRequest(
                prompt="Hi",
                max_tokens=1,
                temperature=0,
            )
            
            api_params = self._build_request_params(test_request)
            response = await self.client.post("/chat/completions", json=api_params)
            response.raise_for_status()
            
            data = response.json()
            choices = data.get("choices", [])
            
            return len(choices) > 0
        
        except Exception as e:
            logger.bind(
                provider=self.provider_name,
                model=self.model,
                error=str(e),
            ).warning("Health check 失败")
            return False

    def _calculate_backoff(self, attempt: int) -> float:
        """
        计算指数退避等待时间。

        使用指数退避 + 随机抖动，避免多个客户端同时重试。

        Args:
            attempt: 当前重试次数（从 0 开始）

        Returns:
            float: 等待时间（秒）
        """
        import random
        
        base_time = 1.0  # 基础等待时间 1 秒
        max_time = 10.0  # 最大等待时间 10 秒
        
        # 指数退避：1s, 2s, 4s, 8s...
        exponential_time = base_time * (2 ** attempt)
        
        # 添加随机抖动（±25%）
        jitter = exponential_time * 0.25 * (2 * random.random() - 1)
        wait_time = exponential_time + jitter
        
        # 限制最大等待时间
        return min(wait_time, max_time)

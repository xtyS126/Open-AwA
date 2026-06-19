"""
Google Gemini Provider 适配器实现。
使用 google-generativeai SDK 调用 Gemini 系列模型。
"""

import asyncio
import time
from typing import Any, Dict, Optional, Type, TypeVar

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

# 尝试导入 google-generativeai SDK
try:
    import google.generativeai as genai
    from google.generativeai.types import GenerationConfig
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    genai = None
    GenerationConfig = None


class GeminiProvider(LLMProvider):
    """
    Google Gemini Provider 实现。
    支持 Gemini 1.5/2.0 系列模型。
    """

    def __init__(
        self,
        model: str = "gemini-1.5-flash",
        api_key: str = "",
        base_url: Optional[str] = None,
        timeout: float = 60.0,
        max_retries: int = 3,
        **kwargs
    ):
        """
        初始化 Gemini Provider。

        Args:
            model: 模型名称（如 "gemini-1.5-flash", "gemini-2.0-pro"）
            api_key: Google API 密钥
            base_url: 自定义 API 端点（可选）
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
            **kwargs: 其他 Provider 特定参数
        """
        if not GEMINI_AVAILABLE:
            raise LLMError(
                "google-generativeai 库未安装，请运行: pip install google-generativeai",
                provider="gemini",
                model=model,
            )

        super().__init__(
            provider_name="gemini",
            model=model,
            api_key=api_key,
            **kwargs
        )

        self.timeout = timeout
        self.max_retries = max_retries
        self.base_url = base_url

        # 配置 Google Generative AI
        if api_key:
            genai.configure(api_key=api_key)

        # 初始化模型实例
        self._model = genai.GenerativeModel(model)

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

        # 构造消息内容
        messages = []
        if request.system_prompt:
            # Gemini 不直接支持 system prompt，需要合并到用户消息中
            messages.append(f"系统指令：{request.system_prompt}\n\n用户消息：{request.prompt}")
        else:
            messages.append(request.prompt)

        full_prompt = "\n".join(messages)

        # 构造生成配置
        generation_config = self._build_generation_config(request)

        # 指数退避重试
        last_error = None
        for attempt in range(self.max_retries):
            try:
                # 在线程池中执行同步调用，避免阻塞事件循环
                response = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: self._model.generate_content(
                            full_prompt,
                            generation_config=generation_config,
                        )
                    ),
                    timeout=self.timeout
                )

                # 解析响应
                content = response.text if response.text else ""
                usage_data = self._extract_usage(response)

                duration_ms = int((time.perf_counter() - started_at) * 1000)

                return LLMResponse(
                    content=content,
                    usage=usage_data,
                    latency_ms=duration_ms,
                    model=self.model,
                    provider=self.provider_name,
                    success=True,
                    raw_response={"response": str(response)},
                )

            except asyncio.TimeoutError:
                last_error = LLMTimeoutError(
                    f"Gemini API 请求超时（{self.timeout}秒）",
                    provider=self.provider_name,
                    model=self.model,
                    timeout=self.timeout,
                )
                logger.warning(
                    f"Gemini API 超时（尝试 {attempt + 1}/{self.max_retries}）"
                )

            except Exception as e:
                error_str = str(e).lower()

                # 区分不同类型的错误
                if "rate limit" in error_str or "quota" in error_str:
                    last_error = RateLimitError(
                        message=f"Gemini API 速率限制: {e}",
                        provider=self.provider_name,
                        model=self.model,
                    )
                    logger.warning(
                        f"Gemini API 速率限制（尝试 {attempt + 1}/{self.max_retries}）"
                    )

                elif "api key" in error_str or "authentication" in error_str or "unauthorized" in error_str:
                    last_error = AuthenticationError(
                        message=f"Gemini API 认证失败: {e}",
                        provider=self.provider_name,
                        model=self.model,
                    )
                    # 认证错误不重试
                    break

                else:
                    last_error = LLMError(
                        f"Gemini API 调用失败: {e}",
                        provider=self.provider_name,
                        model=self.model,
                    )
                    logger.warning(
                        f"Gemini API 错误（尝试 {attempt + 1}/{self.max_retries}）: {e}"
                    )

                # 指数退避等待
                if attempt < self.max_retries - 1:
                    wait_time = (2 ** attempt) + (0.1 * attempt)
                    await asyncio.sleep(wait_time)

        # 所有重试都失败
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        logger.error(f"Gemini API 调用最终失败: {last_error}")

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
            # 发送一个简单的测试请求
            test_request = LLMRequest(
                prompt="Hello",
                max_tokens=5,
                temperature=0.0,
            )
            response = await self.generate(test_request)
            return response.success
        except Exception as e:
            logger.warning(f"Gemini 健康检查失败: {e}")
            return False

    def _build_generation_config(self, request: LLMRequest) -> "GenerationConfig":
        """
        根据请求参数构造 Gemini GenerationConfig。

        Args:
            request: LLM 请求参数

        Returns:
            GenerationConfig: Gemini 生成配置
        """
        config_dict = {
            "max_output_tokens": request.max_tokens,
        }

        if request.temperature is not None:
            config_dict["temperature"] = request.temperature

        if request.top_p is not None:
            config_dict["top_p"] = request.top_p

        if request.top_k is not None:
            config_dict["top_k"] = request.top_k

        if request.stop_sequences:
            config_dict["stop_sequences"] = request.stop_sequences

        return GenerationConfig(**config_dict)

    def _extract_usage(self, response: Any) -> TokenUsage:
        """
        从 Gemini 响应中提取 token 用量信息。

        Args:
            response: Gemini API 响应对象

        Returns:
            TokenUsage: token 用量统计
        """
        try:
            usage_metadata = response.usage_metadata
            if usage_metadata:
                return TokenUsage(
                    prompt_tokens=getattr(usage_metadata, "prompt_token_count", 0),
                    completion_tokens=getattr(usage_metadata, "candidates_token_count", 0),
                    total_tokens=getattr(usage_metadata, "total_token_count", 0),
                )
        except Exception as e:
            logger.debug(f"无法提取 Gemini token 用量: {e}")

        return TokenUsage()

"""
LLM 服务层，按任务类型路由到不同 Provider，支持模块级 override。
"""

from typing import Any, Dict, Optional, Type, TypeVar
from loguru import logger
from pydantic import BaseModel
from llm.base import LLMProvider, LLMRequest
from llm.response import LLMResponse, TokenUsage
from llm.registry import LLMRegistry
from llm.exceptions import LLMError, ProviderNotFoundError
from llm.usage_recorder import UsageRecorder

T = TypeVar("T", bound=BaseModel)


class LLMService:
    """
    LLM 服务。
    按 task_type 路由到对应 Provider，支持模块级 override 和用量记录。
    """
    
    def __init__(self, registry: LLMRegistry, task_routing: Dict[str, str], usage_recorder: Optional[UsageRecorder] = None):
        """
        初始化 LLM 服务。
        
        Args:
            registry: Provider 注册表
            task_routing: 任务类型到 Provider 名称的映射（如 {"soul": "claude", "agent": "openai"}）
            usage_recorder: 用量记录器（可选）
        """
        self.registry = registry
        self.task_routing = task_routing
        self.usage_recorder = usage_recorder
        # 模块级 override（运行时可动态修改）
        self._module_overrides: Dict[str, str] = {}
        logger.info(f"LLMService 初始化完成，任务路由: {task_routing}")
    
    def set_module_override(self, module_name: str, provider_name: str) -> None:
        """
        设置模块级 Provider override。
        
        Args:
            module_name: 模块名称（如 "soul"、"discovery"）
            provider_name: Provider 名称
        """
        self._module_overrides[module_name] = provider_name
        logger.info(f"模块 '{module_name}' override 为 Provider '{provider_name}'")
    
    def get_provider_for_task(self, task_type: str) -> str:
        """
        获取任务类型对应的 Provider 名称。
        优先级：模块 override > 任务路由 > 默认 Provider。
        
        Args:
            task_type: 任务类型
        
        Returns:
            str: Provider 名称
        """
        # 1. 检查模块 override
        if task_type in self._module_overrides:
            return self._module_overrides[task_type]
        
        # 2. 检查任务路由
        if task_type in self.task_routing:
            return self.task_routing[task_type]
        
        # 3. 回退到默认 Provider
        healthy = self.registry.get_healthy_providers()
        if healthy:
            return healthy[0]
        
        raise ProviderNotFoundError(f"没有可用的 Provider 来处理任务 '{task_type}'")
    
    async def generate(
        self,
        task_type: str,
        prompt: str,
        user_id: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        """
        生成文本响应。
        
        Args:
            task_type: 任务类型（如 "soul"、"agent"、"discovery"）
            prompt: 提示词
            user_id: 用户 ID（用于用量记录）
            **kwargs: 其他 LLM 请求参数
        
        Returns:
            LLMResponse: 统一响应结构
        """
        # 获取 Provider
        provider_name = self.get_provider_for_task(task_type)
        provider = self.registry.get_provider(provider_name)
        
        # 构建请求
        request = LLMRequest(
            prompt=prompt,
            system_prompt=kwargs.get("system_prompt"),
            max_tokens=kwargs.get("max_tokens", 1000),
            temperature=kwargs.get("temperature"),
            top_p=kwargs.get("top_p"),
            top_k=kwargs.get("top_k"),
            stream=kwargs.get("stream", False),
            stop_sequences=kwargs.get("stop_sequences"),
            thinking_budget_tokens=kwargs.get("thinking_budget_tokens"),
            thinking_enabled=kwargs.get("thinking_enabled", False),
            extra_params=kwargs.get("extra_params", {}),
        )
        
        # 调用 Provider
        import time
        start_time = time.perf_counter()
        
        try:
            response = await provider.generate(request)
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            
            # 记录用量
            if self.usage_recorder and response.success:
                await self.usage_recorder.record(
                    user_id=user_id,
                    task_type=task_type,
                    provider=provider_name,
                    model=provider.model,
                    usage=response.usage,
                    cost=response.cost,
                    latency_ms=latency_ms,
                    success=True,
                )
            
            return response
            
        except LLMError as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            
            # 记录失败
            if self.usage_recorder:
                await self.usage_recorder.record(
                    user_id=user_id,
                    task_type=task_type,
                    provider=provider_name,
                    model=provider.model,
                    usage=TokenUsage(),
                    cost=0.0,
                    latency_ms=latency_ms,
                    success=False,
                    error_message=str(e),
                )
            
            # 标记 Provider 不健康
            self.registry.mark_unhealthy(provider_name)
            raise
    
    async def generate_structured(
        self,
        task_type: str,
        prompt: str,
        schema: Type[T],
        user_id: Optional[str] = None,
        **kwargs
    ) -> T:
        """
        生成结构化输出。
        
        Args:
            task_type: 任务类型
            prompt: 提示词
            schema: Pydantic 模型类
            user_id: 用户 ID
            **kwargs: 其他参数
        
        Returns:
            T: Pydantic 模型实例
        """
        # 获取 Provider
        provider_name = self.get_provider_for_task(task_type)
        provider = self.registry.get_provider(provider_name)
        
        # 构建请求
        request = LLMRequest(
            prompt=prompt,
            system_prompt=kwargs.get("system_prompt"),
            max_tokens=kwargs.get("max_tokens", 1000),
            temperature=kwargs.get("temperature", 0.0),
            top_p=kwargs.get("top_p"),
            top_k=kwargs.get("top_k"),
            stream=False,  # 结构化输出不支持流式
            extra_params=kwargs.get("extra_params", {}),
        )
        
        # 调用 Provider
        import time
        start_time = time.perf_counter()
        
        try:
            result = await provider.generate_structured(request, schema)
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            
            # 记录用量（简化版）
            if self.usage_recorder:
                await self.usage_recorder.record(
                    user_id=user_id,
                    task_type=task_type,
                    provider=provider_name,
                    model=provider.model,
                    usage=TokenUsage(),  # 结构化输出暂不统计 token
                    cost=0.0,
                    latency_ms=latency_ms,
                    success=True,
                )
            
            return result
            
        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            
            if self.usage_recorder:
                await self.usage_recorder.record(
                    user_id=user_id,
                    task_type=task_type,
                    provider=provider_name,
                    model=provider.model,
                    usage=TokenUsage(),
                    cost=0.0,
                    latency_ms=latency_ms,
                    success=False,
                    error_message=str(e),
                )
            
            self.registry.mark_unhealthy(provider_name)
            raise

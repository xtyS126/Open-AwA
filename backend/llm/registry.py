"""
LLM Provider 注册表，管理多个 Provider 实例的健康状态和降级策略。
"""

from typing import Dict, List, Optional
from loguru import logger
from llm.base import LLMProvider
from llm.exceptions import ProviderNotFoundError


class LLMRegistry:
    """
    LLM Provider 注册表。
    负责管理所有 Provider 实例，提供健康检查和降级能力。
    """
    
    def __init__(self):
        """初始化注册表"""
        self._providers: Dict[str, LLMProvider] = {}
        self._health_status: Dict[str, bool] = {}
        logger.info("LLMRegistry 初始化完成")
    
    def register_provider(self, name: str, provider: LLMProvider) -> None:
        """
        注册 Provider。
        
        Args:
            name: Provider 名称（如 "openai"、"claude"）
            provider: Provider 实例
        """
        self._providers[name] = provider
        self._health_status[name] = True  # 初始标记为健康
        logger.info(f"已注册 Provider: {name} ({provider.model})")
    
    def get_provider(self, name: str) -> LLMProvider:
        """
        获取 Provider 实例。
        
        Args:
            name: Provider 名称
        
        Returns:
            LLMProvider: Provider 实例
        
        Raises:
            ProviderNotFoundError: Provider 未注册或已降级
        """
        if name not in self._providers:
            raise ProviderNotFoundError(f"Provider '{name}' 未注册")
        
        # 检查健康状态
        if not self._health_status.get(name, False):
            raise ProviderNotFoundError(f"Provider '{name}' 已降级，暂不可用")
        
        return self._providers[name]
    
    def list_providers(self) -> List[str]:
        """
        获取所有已注册的 Provider 名称列表。
        
        Returns:
            List[str]: Provider 名称列表
        """
        return list(self._providers.keys())
    
    def mark_unhealthy(self, name: str) -> None:
        """
        标记 Provider 为不健康状态（降级）。
        
        Args:
            name: Provider 名称
        """
        if name in self._health_status:
            self._health_status[name] = False
            logger.warning(f"Provider '{name}' 已标记为不健康（降级）")
    
    def mark_healthy(self, name: str) -> None:
        """
        标记 Provider 为健康状态（恢复）。
        
        Args:
            name: Provider 名称
        """
        if name in self._health_status:
            self._health_status[name] = True
            logger.info(f"Provider '{name}' 已恢复健康")
    
    async def health_check_all(self) -> Dict[str, bool]:
        """
        对所有 Provider 执行健康检查。
        
        Returns:
            Dict[str, bool]: Provider 名称到健康状态的映射
        """
        results = {}
        for name, provider in self._providers.items():
            try:
                is_healthy = await provider.health_check()
                self._health_status[name] = is_healthy
                results[name] = is_healthy
                if not is_healthy:
                    logger.warning(f"Provider '{name}' 健康检查失败")
            except Exception as e:
                self._health_status[name] = False
                results[name] = False
                logger.error(f"Provider '{name}' 健康检查异常: {e}")
        
        return results
    
    def get_healthy_providers(self) -> List[str]:
        """
        获取所有健康的 Provider 名称列表。
        
        Returns:
            List[str]: 健康的 Provider 名称列表
        """
        return [name for name, healthy in self._health_status.items() if healthy]
    
    def has_provider(self, name: str) -> bool:
        """
        检查 Provider 是否已注册。
        
        Args:
            name: Provider 名称
        
        Returns:
            bool: 是否已注册
        """
        return name in self._providers

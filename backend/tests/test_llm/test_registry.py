"""
LLM registry 模块测试。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from llm.registry import LLMRegistry
from llm.exceptions import ProviderNotFoundError


class MockProvider:
    """模拟 Provider 用于测试 Registry。"""

    def __init__(self, name: str, model: str, healthy: bool = True):
        self.provider_name = name
        self.model = model
        self._healthy = healthy

    async def health_check(self) -> bool:
        return self._healthy


class TestLLMRegistry:
    """LLMRegistry 单元测试。"""

    def test_register_provider(self):
        """注册 Provider 后可通过名称获取。"""
        registry = LLMRegistry()
        provider = MockProvider("openai", "gpt-4")
        registry.register_provider("openai", provider)
        assert registry.has_provider("openai") is True
        assert registry.get_provider("openai") is provider

    def test_get_provider_not_found(self):
        """获取未注册的 Provider 抛异常。"""
        registry = LLMRegistry()
        with pytest.raises(ProviderNotFoundError):
            registry.get_provider("unknown")

    def test_get_provider_unhealthy(self):
        """获取已降级的 Provider 抛异常。"""
        registry = LLMRegistry()
        provider = MockProvider("openai", "gpt-4")
        registry.register_provider("openai", provider)
        registry.mark_unhealthy("openai")
        with pytest.raises(ProviderNotFoundError):
            registry.get_provider("openai")

    def test_mark_healthy_restores(self):
        """标记恢复后可以正常获取 Provider。"""
        registry = LLMRegistry()
        provider = MockProvider("openai", "gpt-4")
        registry.register_provider("openai", provider)
        registry.mark_unhealthy("openai")
        registry.mark_healthy("openai")
        assert registry.get_provider("openai") is provider

    def test_list_providers(self):
        """list_providers 返回所有已注册的 Provider 名称。"""
        registry = LLMRegistry()
        registry.register_provider("openai", MockProvider("openai", "gpt-4"))
        registry.register_provider("claude", MockProvider("claude", "claude-3"))
        providers = registry.list_providers()
        assert "openai" in providers
        assert "claude" in providers
        assert len(providers) == 2

    def test_list_providers_empty(self):
        """空注册表返回空列表。"""
        registry = LLMRegistry()
        assert registry.list_providers() == []

    def test_has_provider(self):
        """has_provider 正确判断注册状态。"""
        registry = LLMRegistry()
        assert registry.has_provider("openai") is False
        registry.register_provider("openai", MockProvider("openai", "gpt-4"))
        assert registry.has_provider("openai") is True

    def test_get_healthy_providers(self):
        """get_healthy_providers 只返回健康的 Provider。"""
        registry = LLMRegistry()
        registry.register_provider("openai", MockProvider("openai", "gpt-4"))
        registry.register_provider("claude", MockProvider("claude", "claude-3"))
        registry.mark_unhealthy("claude")
        healthy = registry.get_healthy_providers()
        assert "openai" in healthy
        assert "claude" not in healthy

    def test_mark_unhealthy_nonexistent(self):
        """对不存在的 Provider 标记不健康不报错。"""
        registry = LLMRegistry()
        registry.mark_unhealthy("nonexistent")  # 不抛异常

    def test_mark_healthy_nonexistent(self):
        """对不存在的 Provider 标记健康不报错。"""
        registry = LLMRegistry()
        registry.mark_healthy("nonexistent")  # 不抛异常

    @pytest.mark.asyncio
    async def test_health_check_all(self):
        """health_check_all 对所有 Provider 执行健康检查。"""
        registry = LLMRegistry()
        healthy_provider = MockProvider("openai", "gpt-4", healthy=True)
        unhealthy_provider = MockProvider("claude", "claude-3", healthy=False)
        registry.register_provider("openai", healthy_provider)
        registry.register_provider("claude", unhealthy_provider)
        results = await registry.health_check_all()
        assert results["openai"] is True
        assert results["claude"] is False

    @pytest.mark.asyncio
    async def test_health_check_all_exception(self):
        """health_check_all 中异常时标记为不健康。"""
        registry = LLMRegistry()
        bad_provider = MagicMock()
        bad_provider.health_check = AsyncMock(side_effect=RuntimeError("连接失败"))
        bad_provider.model = "test"
        registry.register_provider("bad", bad_provider)
        results = await registry.health_check_all()
        assert results["bad"] is False
"""
Billing 模块单元测试。
测试计费和定价管理功能。
"""

import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy.orm import Session


class TestPricingManager:
    """测试定价管理器"""

    def test_normalize_provider(self):
        """测试供应商名称规范化"""
        from billing.pricing_manager import normalize_provider
        
        assert normalize_provider("OpenAI") == "openai"
        assert normalize_provider("  ANTHropic  ") == "anthropic"
        assert normalize_provider(None) == "unknown"
        assert normalize_provider("") == "unknown"

    def test_calculate_token_cost(self):
        """测试Token成本计算"""
        from billing.pricing_manager import PricingManager
        
        manager = PricingManager()
        
        cost = manager.calculate_cost(
            provider="openai",
            model="gpt-4",
            input_tokens=1000,
            output_tokens=500
        )
        
        assert cost >= 0

    def test_get_pricing_for_provider(self):
        """测试获取供应商定价"""
        from billing.pricing_manager import PricingManager
        
        manager = PricingManager()
        
        pricing = manager.get_pricing("openai", "gpt-4")
        
        assert pricing is not None
        assert "input_price" in pricing or "input" in pricing

    def test_get_pricing_unknown_provider(self):
        """测试获取未知供应商定价"""
        from billing.pricing_manager import PricingManager
        
        manager = PricingManager()
        
        pricing = manager.get_pricing("unknown_provider", "unknown_model")
        
        assert pricing is None or pricing == {}

    def test_list_supported_providers(self):
        """测试列出支持的供应商"""
        from billing.pricing_manager import PricingManager
        
        manager = PricingManager()
        
        providers = manager.list_providers()
        
        assert isinstance(providers, list)
        assert len(providers) > 0


class TestBillingRecord:
    """测试计费记录"""

    def test_create_billing_record(self, mock_db_session: Session):
        """测试创建计费记录"""
        from billing.pricing_manager import PricingManager
        
        manager = PricingManager()
        
        record = manager.create_record(
            db=mock_db_session,
            user_id="test_user",
            provider="openai",
            model="gpt-4",
            input_tokens=100,
            output_tokens=50,
            cost=0.01
        )
        
        mock_db_session.add.assert_called()
        mock_db_session.commit.assert_called()

    def test_get_user_billing_summary(self, mock_db_session: Session):
        """测试获取用户计费摘要"""
        from billing.pricing_manager import PricingManager
        
        manager = PricingManager()
        
        summary = manager.get_user_summary(
            db=mock_db_session,
            user_id="test_user"
        )
        
        assert summary is not None


class TestTokenCounting:
    """测试Token计数"""

    def test_estimate_tokens(self):
        """测试估算Token数量"""
        from billing.pricing_manager import estimate_tokens
        
        text = "Hello, this is a test message."
        tokens = estimate_tokens(text)
        
        assert tokens > 0
        assert isinstance(tokens, int)

    def test_estimate_tokens_empty_string(self):
        """测试空字符串Token估算"""
        from billing.pricing_manager import estimate_tokens
        
        tokens = estimate_tokens("")
        
        assert tokens == 0

    def test_estimate_tokens_long_text(self):
        """测试长文本Token估算"""
        from billing.pricing_manager import estimate_tokens
        
        text = "Hello world! " * 1000
        tokens = estimate_tokens(text)
        
        assert tokens > 1000


@pytest.fixture
def mock_db_session():
    """模拟数据库会话"""
    session = MagicMock(spec=Session)
    session.add = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    return session

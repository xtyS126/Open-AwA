"""
Chat API 集成测试模块。
测试聊天相关的API端点，包括消息发送和历史记录获取。
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch, AsyncMock


class TestChatSendMessage:
    """测试发送消息"""

    def test_send_message_without_auth(self, client: TestClient):
        """测试未认证发送消息"""
        response = client.post(
            "/api/chat",
            json={"message": "Hello", "session_id": "test"}
        )
        
        assert response.status_code == 401

    def test_send_message_with_auth(self, client: TestClient, auth_headers: dict):
        """测试认证后发送消息"""
        with patch('core.agent.AIAgent') as mock_agent:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value={"response": "Hello back"})
            mock_agent.return_value = mock_instance
            
            response = client.post(
                "/api/chat",
                json={"message": "Hello", "session_id": "test"},
                headers=auth_headers
            )
            
            assert response.status_code in [200, 201]

    def test_send_message_with_provider(self, client: TestClient, auth_headers: dict):
        """测试指定供应商发送消息"""
        with patch('core.agent.AIAgent') as mock_agent:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value={"response": "Response"})
            mock_agent.return_value = mock_instance
            
            response = client.post(
                "/api/chat",
                json={
                    "message": "Hello",
                    "session_id": "test",
                    "provider": "openai"
                },
                headers=auth_headers
            )
            
            assert response.status_code in [200, 201]


class TestChatHistory:
    """测试历史记录"""

    def test_get_history_without_auth(self, client: TestClient):
        """测试未认证获取历史"""
        response = client.get("/api/chat/history/test_session")
        
        assert response.status_code == 401

    def test_get_history_with_auth(self, client: TestClient, auth_headers: dict):
        """测试认证后获取历史"""
        response = client.get(
            "/api/chat/history/test_session",
            headers=auth_headers
        )
        
        assert response.status_code in [200, 404]


class TestChatConfirm:
    """测试操作确认"""

    def test_confirm_operation_without_auth(self, client: TestClient):
        """测试未认证确认操作"""
        response = client.post(
            "/api/chat/confirm",
            json={"confirmed": True, "step": {}}
        )
        
        assert response.status_code == 401

    def test_confirm_operation_with_auth(self, client: TestClient, auth_headers: dict):
        """测试认证后确认操作"""
        with patch('core.agent.AIAgent') as mock_agent:
            mock_instance = MagicMock()
            mock_instance.confirm_operation = AsyncMock(return_value={"status": "confirmed"})
            mock_agent.return_value = mock_instance
            
            response = client.post(
                "/api/chat/confirm",
                json={
                    "confirmed": True,
                    "step": {"id": "step1", "action": "test", "params": {}}
                },
                headers=auth_headers
            )
            
            assert response.status_code in [200, 201]


@pytest.fixture
def client():
    """创建测试客户端"""
    from main import app
    return TestClient(app)


@pytest.fixture
def auth_headers(client: TestClient):
    """获取认证头"""
    client.post(
        "/api/auth/register",
        json={"username": "chattestuser", "password": "password123"}
    )
    
    login_response = client.post(
        "/api/auth/login",
        data={"username": "chattestuser", "password": "password123"}
    )
    
    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

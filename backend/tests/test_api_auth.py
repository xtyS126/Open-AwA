"""
Auth API 集成测试模块。
测试认证相关的API端点，包括注册、登录和用户信息获取。
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from sqlalchemy.orm import Session


class TestAuthRegister:
    """测试用户注册"""

    def test_register_success(self, client: TestClient):
        """测试成功注册"""
        response = client.post(
            "/api/auth/register",
            json={"username": "newuser", "password": "newpassword123"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "newuser"
        assert "id" in data

    def test_register_duplicate_username(self, client: TestClient):
        """测试重复用户名注册"""
        client.post(
            "/api/auth/register",
            json={"username": "duplicateuser", "password": "password123"}
        )
        
        response = client.post(
            "/api/auth/register",
            json={"username": "duplicateuser", "password": "password456"}
        )
        
        assert response.status_code == 400

    def test_register_missing_fields(self, client: TestClient):
        """测试缺少必填字段"""
        response = client.post(
            "/api/auth/register",
            json={"username": "testuser"}
        )
        
        assert response.status_code == 422


class TestAuthLogin:
    """测试用户登录"""

    def test_login_success(self, client: TestClient):
        """测试成功登录"""
        client.post(
            "/api/auth/register",
            json={"username": "loginuser", "password": "password123"}
        )
        
        response = client.post(
            "/api/auth/login",
            data={"username": "loginuser", "password": "password123"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password(self, client: TestClient):
        """测试错误密码登录"""
        client.post(
            "/api/auth/register",
            json={"username": "wrongpassuser", "password": "correctpassword"}
        )
        
        response = client.post(
            "/api/auth/login",
            data={"username": "wrongpassuser", "password": "wrongpassword"}
        )
        
        assert response.status_code == 401

    def test_login_nonexistent_user(self, client: TestClient):
        """测试不存在的用户登录"""
        response = client.post(
            "/api/auth/login",
            data={"username": "nonexistent", "password": "password123"}
        )
        
        assert response.status_code == 401


class TestAuthMe:
    """测试获取当前用户信息"""

    def test_me_with_valid_token(self, client: TestClient):
        """测试有效token获取用户信息"""
        client.post(
            "/api/auth/register",
            json={"username": "meuser", "password": "password123"}
        )
        
        login_response = client.post(
            "/api/auth/login",
            data={"username": "meuser", "password": "password123"}
        )
        token = login_response.json()["access_token"]
        
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "meuser"

    def test_me_without_token(self, client: TestClient):
        """测试无token获取用户信息"""
        response = client.get("/api/auth/me")
        
        assert response.status_code == 401

    def test_me_with_invalid_token(self, client: TestClient):
        """测试无效token获取用户信息"""
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid_token"}
        )
        
        assert response.status_code == 401


@pytest.fixture
def client():
    """创建测试客户端"""
    from main import app
    return TestClient(app)

"""
billing 路由鉴权测试，验证受保护端点对未认证请求返回 401。
"""

import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_current_user, get_db
from db.models import Base
from main import app


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)


def override_get_db():
    """提供独立测试数据库会话。"""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def override_get_current_user():
    """提供固定测试用户。"""

    class DummyUser:
        id = "user-1"
        username = "testuser"
        role = "user"

    return DummyUser()


def test_update_provider_selected_models_requires_authentication():
    """验证 update_provider_selected_models 端点未认证时返回 401。"""
    # 仅覆盖数据库依赖，不覆盖用户依赖
    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            payload = {"selected_models": ["gpt-4", "gpt-3.5-turbo"]}
            response = client.put(
                "/api/billing/providers/openai/selected-models",
                json=payload
            )
            assert response.status_code == 401, (
                f"Expected 401, got {response.status_code}: {response.text}"
            )
    finally:
        app.dependency_overrides.clear()


def test_update_retention_requires_authentication():
    """验证 update_retention 端点未认证时返回 401。"""
    # 仅覆盖数据库依赖，不覆盖用户依赖
    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            payload = {"retention_days": 30, "cleanup": False}
            response = client.post(
                "/api/billing/retention",
                json=payload
            )
            assert response.status_code == 401, (
                f"Expected 401, got {response.status_code}: {response.text}"
            )
    finally:
        app.dependency_overrides.clear()


def test_update_provider_selected_models_with_authentication():
    """验证 update_provider_selected_models 端点认证后可以正常访问。"""
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    try:
        with TestClient(app) as client:
            payload = {"selected_models": ["gpt-4", "gpt-3.5-turbo"]}
            response = client.put(
                "/api/billing/providers/openai/selected-models",
                json=payload
            )
            # 认证后应该返回 200 或其他成功状态码，而不是 401
            assert response.status_code != 401, (
                f"Authenticated request should not return 401: {response.text}"
            )
    finally:
        app.dependency_overrides.clear()


def test_update_retention_with_authentication():
    """验证 update_retention 端点认证后可以正常访问。"""
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    try:
        with TestClient(app) as client:
            payload = {"retention_days": 30, "cleanup": False}
            response = client.post(
                "/api/billing/retention",
                json=payload
            )
            # 认证后应该返回 200 或其他成功状态码，而不是 401
            assert response.status_code != 401, (
                f"Authenticated request should not return 401: {response.text}"
            )
    finally:
        app.dependency_overrides.clear()

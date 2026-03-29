import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from db.models import Base, Skill
from api.dependencies import get_db, get_current_user
from config.settings import settings

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

def override_get_current_user():
    class DummyUser:
        id = 1
        username = "testuser"
    return DummyUser()

app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_current_user] = override_get_current_user

client = TestClient(app)

def test_save_and_get_weixin_config():
    with TestClient(app) as client:
        # Test GET config when no skill exists
        response = client.get(f"{settings.API_V1_STR}/skills/weixin/config")
        assert response.status_code == 200
        data = response.json()
        assert data["account_id"] == ""
        assert data["token"] == ""

        # Test POST save config
        payload = {
            "account_id": "test_acc",
            "token": "test_tok",
            "base_url": "https://test.url",
            "timeout_seconds": 30
        }
        response = client.post(f"{settings.API_V1_STR}/skills/weixin/config", json=payload)
        assert response.status_code == 200
        assert response.json() == {"message": "success"}

        # Test GET config after saving
        response = client.get(f"{settings.API_V1_STR}/skills/weixin/config")
        assert response.status_code == 200
        data = response.json()
        assert data["account_id"] == "test_acc"
        assert data["token"] == "test_tok"
        assert data["base_url"] == "https://test.url"
        assert data["timeout_seconds"] == 30

def test_weixin_health_check(monkeypatch):
    with TestClient(app) as client:
        # Mock the WeixinSkillAdapter's check_health method
        def mock_check_health(self, config):
            return {
                "ok": True,
                "issues": [],
                "suggestions": [],
                "diagnostics": {"plugin_root_exists": True}
            }
        
        import skills.weixin_skill_adapter
        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "check_health", mock_check_health)
        
        payload = {
            "account_id": "test_acc",
            "token": "test_tok"
        }
        response = client.post(f"{settings.API_V1_STR}/skills/weixin/health-check", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["diagnostics"]["plugin_root_exists"] is True

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


@pytest.fixture(autouse=True)
def reset_skills_table():
    db = TestingSessionLocal()
    try:
        db.query(Skill).delete()
        db.commit()
    finally:
        db.close()
    yield
    db = TestingSessionLocal()
    try:
        db.query(Skill).delete()
        db.commit()
    finally:
        db.close()


def test_save_and_get_weixin_config():
    with TestClient(app) as client:
        response = client.get(f"{settings.API_V1_STR}/skills/weixin/config")
        assert response.status_code == 200
        data = response.json()
        assert data["account_id"] == ""
        assert data["token"] == ""

        payload = {
            "account_id": "test_acc",
            "token": "test_tok",
            "base_url": "https://test.url",
            "timeout_seconds": 30
        }
        response = client.post(f"{settings.API_V1_STR}/skills/weixin/config", json=payload)
        assert response.status_code == 200
        assert response.json() == {"message": "success"}

        response = client.get(f"{settings.API_V1_STR}/skills/weixin/config")
        assert response.status_code == 200
        data = response.json()
        assert data["account_id"] == "test_acc"
        assert data["token"] == "test_tok"
        assert data["base_url"] == "https://test.url"
        assert data["timeout_seconds"] == 30

def test_weixin_health_check(monkeypatch):
    with TestClient(app) as client:
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


def test_weixin_qr_start_and_wait_confirmed_updates_config(monkeypatch):
    with TestClient(app) as client:
        import skills.weixin_skill_adapter

        async def mock_fetch_login_qrcode(self, base_url, bot_type="3", timeout_seconds=15):
            return {
                "qrcode": "qr-123",
                "qrcode_img_content": "https://example.com/qr.png"
            }

        async def mock_fetch_qrcode_status(self, base_url, qrcode, timeout_seconds=35):
            return {
                "status": "confirmed",
                "bot_token": "bot-token-1",
                "ilink_bot_id": "bot-account-1",
                "baseurl": "https://ilinkai.weixin.qq.com"
            }

        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_login_qrcode", mock_fetch_login_qrcode)
        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_qrcode_status", mock_fetch_qrcode_status)

        start_response = client.post(f"{settings.API_V1_STR}/skills/weixin/qr/start", json={})
        assert start_response.status_code == 200
        start_data = start_response.json()
        assert start_data["status"] == "wait"
        assert start_data["qrcode"] == "qr-123"
        assert start_data["qrcode_url"] == "https://example.com/qr.png"
        assert start_data["session_key"]

        wait_response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/qr/wait",
            json={"session_key": start_data["session_key"]}
        )
        assert wait_response.status_code == 200
        wait_data = wait_response.json()
        assert wait_data["connected"] is True
        assert wait_data["status"] == "confirmed"
        assert wait_data["account_id"] == "bot-account-1"
        assert wait_data["token"] == "bot-token-1"

        config_response = client.get(f"{settings.API_V1_STR}/skills/weixin/config")
        assert config_response.status_code == 200
        config_data = config_response.json()
        assert config_data["account_id"] == "bot-account-1"
        assert config_data["token"] == "bot-token-1"


def test_weixin_qr_start_extracts_qrcode_from_qrcode_url_query(monkeypatch):
    with TestClient(app) as client:
        import skills.weixin_skill_adapter

        async def mock_fetch_login_qrcode(self, base_url, bot_type="3", timeout_seconds=15):
            return {
                "qrcode_img_content": "https://liteapp.weixin.qq.com/q/7GiQu1?qrcode=5bd615dc3e27eb837ca2db2f30ee7b7b&bot_type=3"
            }

        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_login_qrcode", mock_fetch_login_qrcode)

        start_response = client.post(f"{settings.API_V1_STR}/skills/weixin/qr/start", json={})
        assert start_response.status_code == 200
        start_data = start_response.json()
        assert start_data["qrcode"] == "5bd615dc3e27eb837ca2db2f30ee7b7b"
        assert "liteapp.weixin.qq.com" in start_data["qrcode_url"]


def test_weixin_qr_wait_returns_404_when_session_missing():
    with TestClient(app) as client:
        response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/qr/wait",
            json={"session_key": "missing-session"}
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "当前没有进行中的登录，请先发起登录。"


def test_weixin_qr_exit_clears_session_and_config(monkeypatch):
    with TestClient(app) as client:
        import skills.weixin_skill_adapter

        async def mock_fetch_login_qrcode(self, base_url, bot_type="3", timeout_seconds=15):
            return {
                "qrcode": "qr-exit",
                "qrcode_img_content": "https://example.com/qr-exit.png"
            }

        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_login_qrcode", mock_fetch_login_qrcode)

        save_response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/config",
            json={
                "account_id": "keep-account",
                "token": "keep-token",
                "base_url": "https://test.url",
                "timeout_seconds": 18
            }
        )
        assert save_response.status_code == 200

        start_response = client.post(f"{settings.API_V1_STR}/skills/weixin/qr/start", json={})
        assert start_response.status_code == 200
        session_key = start_response.json()["session_key"]

        exit_response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/qr/exit",
            json={"session_key": session_key, "clear_config": True}
        )
        assert exit_response.status_code == 200
        exit_data = exit_response.json()
        assert exit_data["message"] == "success"
        assert exit_data["cleared_sessions"] == 1

        config_response = client.get(f"{settings.API_V1_STR}/skills/weixin/config")
        assert config_response.status_code == 200
        config_data = config_response.json()
        assert config_data["account_id"] == ""
        assert config_data["token"] == ""
        assert config_data["base_url"] == "https://test.url"
        assert config_data["timeout_seconds"] == 18

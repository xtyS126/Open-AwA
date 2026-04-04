import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import app
from db.models import Base, Skill
from api.dependencies import get_db, get_current_user
from config.settings import settings
from skills.weixin_skill_adapter import DEFAULT_QR_BASE_URL

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
        assert data["binding_status"] == "unbound"

        payload = {
            "account_id": "test_acc",
            "token": "test_tok",
            "base_url": "https://test.url",
            "timeout_seconds": 30,
            "user_id": "persisted-user",
            "binding_status": "bound"
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
        assert data["user_id"] == "persisted-user"
        assert data["binding_status"] == "bound"


def test_weixin_health_check(monkeypatch):
    with TestClient(app) as client:
        def mock_check_health(self, config):
            return {
                "ok": True,
                "issues": [],
                "suggestions": [],
                "diagnostics": {
                    "base_url": config.base_url,
                    "account_id": config.account_id,
                    "session_paused": False,
                    "user_id": config.user_id,
                    "binding_status": config.binding_status,
                    "binding_ready": bool(config.account_id and config.token)
                }
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
        assert data["diagnostics"]["account_id"] == "test_acc"
        assert data["diagnostics"]["base_url"] == DEFAULT_QR_BASE_URL
        assert data["diagnostics"]["binding_ready"] is True


def test_weixin_qr_start_and_wait_confirmed_updates_config(monkeypatch):
    with TestClient(app) as client:
        import skills.weixin_skill_adapter

        call_log = []

        async def mock_fetch_login_qrcode(self, base_url, bot_type="3", timeout_seconds=15):
            call_log.append(("start", base_url, bot_type, timeout_seconds))
            return {
                "qrcode": "qr-123",
                "qrcode_img_content": "https://example.com/qr.png"
            }

        async def mock_fetch_qrcode_status(self, base_url, qrcode, timeout_seconds=35):
            call_log.append(("wait", base_url, qrcode, timeout_seconds))
            return {
                "status": "confirmed",
                "bot_token": "bot-token-1",
                "ilink_bot_id": "bot-account-1",
                "ilink_user_id": "wx-user-1",
                "binding_status": "bound",
                "baseurl": "https://ilinkai.weixin.qq.com"
            }

        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_login_qrcode", mock_fetch_login_qrcode)
        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_qrcode_status", mock_fetch_qrcode_status)

        start_response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/qr/start",
            json={"base_url": "https://poll.example.com", "timeout_seconds": 12}
        )
        assert start_response.status_code == 200
        start_data = start_response.json()
        assert start_data["success"] is True
        assert start_data["connected"] is False
        assert start_data["state"] == "pending"
        assert start_data["status"] == "waiting"
        assert start_data["qrcode"] == "qr-123"
        assert start_data["qrcode_url"] == "https://example.com/qr.png"
        assert start_data["session_key"]
        assert call_log[0] == ("start", DEFAULT_QR_BASE_URL, "3", 12)

        wait_response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/qr/wait",
            json={"session_key": start_data["session_key"]}
        )
        assert wait_response.status_code == 200
        wait_data = wait_response.json()
        assert wait_data["success"] is True
        assert wait_data["connected"] is True
        assert wait_data["state"] == "success"
        assert wait_data["status"] == "confirmed"
        assert wait_data["account_id"] == "bot-account-1"
        assert wait_data["token"] == "bot-token-1"
        assert wait_data["user_id"] == "wx-user-1"
        assert wait_data["binding_status"] == "bound"
        assert call_log[1] == ("wait", "https://poll.example.com", "qr-123", 35)

        config_response = client.get(f"{settings.API_V1_STR}/skills/weixin/config")
        assert config_response.status_code == 200
        config_data = config_response.json()
        assert config_data["account_id"] == "bot-account-1"
        assert config_data["token"] == "bot-token-1"
        assert config_data["user_id"] == "wx-user-1"
        assert config_data["binding_status"] == "bound"


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


def test_weixin_qr_wait_updates_poll_base_url_on_redirect(monkeypatch):
    with TestClient(app) as client:
        import skills.weixin_skill_adapter

        call_log = []

        async def mock_fetch_login_qrcode(self, base_url, bot_type="3", timeout_seconds=15):
            return {
                "qrcode": "qr-redirect",
                "qrcode_img_content": "https://example.com/qr-redirect.png"
            }

        async def mock_fetch_qrcode_status(self, base_url, qrcode, timeout_seconds=35):
            call_log.append(base_url)
            if len(call_log) == 1:
                return {
                    "status": "scaned_but_redirect",
                    "redirect_host": "redirect.weixin.qq.com"
                }
            return {
                "status": "confirmed",
                "bot_token": "bot-token-redirect",
                "ilink_bot_id": "bot-account-redirect",
                "baseurl": "https://redirect.weixin.qq.com"
            }

        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_login_qrcode", mock_fetch_login_qrcode)
        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_qrcode_status", mock_fetch_qrcode_status)

        start_response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/qr/start",
            json={"base_url": "https://initial.weixin.qq.com"}
        )
        assert start_response.status_code == 200
        session_key = start_response.json()["session_key"]

        redirect_response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/qr/wait",
            json={"session_key": session_key}
        )
        assert redirect_response.status_code == 200
        redirect_data = redirect_response.json()
        assert redirect_data["success"] is True
        assert redirect_data["connected"] is False
        assert redirect_data["state"] == "half_success"
        assert redirect_data["status"] == "scanned"
        assert redirect_data["redirect_host"] == "redirect.weixin.qq.com"
        assert redirect_data["base_url"] == "https://redirect.weixin.qq.com"

        confirm_response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/qr/wait",
            json={"session_key": session_key}
        )
        assert confirm_response.status_code == 200
        confirm_data = confirm_response.json()
        assert confirm_data["state"] == "success"
        assert confirm_data["status"] == "confirmed"
        assert confirm_data["base_url"] == "https://redirect.weixin.qq.com"
        assert call_log == ["https://initial.weixin.qq.com", "https://redirect.weixin.qq.com"]


def test_weixin_qr_wait_returns_wait_on_upstream_timeout(monkeypatch):
    with TestClient(app) as client:
        import skills.weixin_skill_adapter

        async def mock_fetch_login_qrcode(self, base_url, bot_type="3", timeout_seconds=15):
            return {
                "qrcode": "qr-timeout",
                "qrcode_img_content": "https://example.com/qr-timeout.png"
            }

        async def mock_fetch_qrcode_status(self, base_url, qrcode, timeout_seconds=35):
            return {"status": "wait"}

        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_login_qrcode", mock_fetch_login_qrcode)
        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_qrcode_status", mock_fetch_qrcode_status)

        start_response = client.post(f"{settings.API_V1_STR}/skills/weixin/qr/start", json={})
        assert start_response.status_code == 200
        session_key = start_response.json()["session_key"]

        wait_response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/qr/wait",
            json={"session_key": session_key}
        )
        assert wait_response.status_code == 200
        wait_data = wait_response.json()
        assert wait_data["success"] is True
        assert wait_data["state"] == "pending"
        assert wait_data["status"] == "waiting"
        assert wait_data["connected"] is False


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
                "timeout_seconds": 18,
                "user_id": "bound-user",
                "binding_status": "bound"
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
        assert config_data["user_id"] == ""
        assert config_data["binding_status"] == "unbound"


def test_weixin_qr_exit_only_clears_session_when_clear_config_false(monkeypatch):
    with TestClient(app) as client:
        import skills.weixin_skill_adapter

        async def mock_fetch_login_qrcode(self, base_url, bot_type="3", timeout_seconds=15):
            return {
                "qrcode": "qr-exit-keep-config",
                "qrcode_img_content": "https://example.com/qr-exit-keep-config.png"
            }

        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_login_qrcode", mock_fetch_login_qrcode)

        save_response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/config",
            json={
                "account_id": "keep-account",
                "token": "keep-token",
                "base_url": "https://keep.url",
                "timeout_seconds": 18,
                "user_id": "keep-user",
                "binding_status": "bound"
            }
        )
        assert save_response.status_code == 200

        start_response = client.post(f"{settings.API_V1_STR}/skills/weixin/qr/start", json={})
        assert start_response.status_code == 200
        session_key = start_response.json()["session_key"]

        exit_response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/qr/exit",
            json={"session_key": session_key, "clear_config": False}
        )
        assert exit_response.status_code == 200
        assert exit_response.json()["cleared_sessions"] == 1

        config_response = client.get(f"{settings.API_V1_STR}/skills/weixin/config")
        assert config_response.status_code == 200
        config_data = config_response.json()
        assert config_data["account_id"] == "keep-account"
        assert config_data["token"] == "keep-token"
        assert config_data["base_url"] == "https://keep.url"
        assert config_data["timeout_seconds"] == 18
        assert config_data["user_id"] == "keep-user"
        assert config_data["binding_status"] == "bound"


def test_weixin_qr_wait_returns_uniform_fields_for_half_success(monkeypatch):
    with TestClient(app) as client:
        import skills.weixin_skill_adapter

        async def mock_fetch_login_qrcode(self, base_url, bot_type="3", timeout_seconds=15):
            return {
                "qrcode": "qr-half-success",
                "qrcode_img_content": "https://example.com/qr-half-success.png"
            }

        async def mock_fetch_qrcode_status(self, base_url, qrcode, timeout_seconds=35):
            return {
                "status": "scaned",
                "auth_id": "auth-half-success",
                "ticket": "ticket-half-success",
                "hint": "confirm-in-wechat"
            }

        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_login_qrcode", mock_fetch_login_qrcode)
        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_qrcode_status", mock_fetch_qrcode_status)

        start_response = client.post(f"{settings.API_V1_STR}/skills/weixin/qr/start", json={})
        assert start_response.status_code == 200

        wait_response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/qr/wait",
            json={"session_key": start_response.json()["session_key"]}
        )
        assert wait_response.status_code == 200
        wait_data = wait_response.json()
        assert wait_data["success"] is True
        assert wait_data["connected"] is False
        assert wait_data["state"] == "half_success"
        assert wait_data["status"] == "scanned"
        assert wait_data["session_key"] == start_response.json()["session_key"]
        assert wait_data["qrcode"] == "qr-half-success"
        assert wait_data["qrcode_url"] == "https://example.com/qr-half-success.png"
        assert wait_data["account_id"] == ""
        assert wait_data["token"] == ""
        assert wait_data["user_id"] == ""
        assert wait_data["binding_status"] == "unbound"
        assert wait_data["auth_id"] == "auth-half-success"
        assert wait_data["ticket"] == "ticket-half-success"
        assert wait_data["hint"] == "confirm-in-wechat"
        assert wait_data["redirect_host"] == ""


def test_weixin_qr_wait_maps_pending_with_auth_id_to_scanned(monkeypatch):
    with TestClient(app) as client:
        import skills.weixin_skill_adapter

        async def mock_fetch_login_qrcode(self, base_url, bot_type="3", timeout_seconds=15):
            return {
                "qrcode": "qr-pending",
                "qrcode_img_content": "https://example.com/qr-pending.png"
            }

        async def mock_fetch_qrcode_status(self, base_url, qrcode, timeout_seconds=35):
            return {
                "status": "pending",
                "message": "waiting for confirm",
                "auth_id": "auth-123"
            }

        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_login_qrcode", mock_fetch_login_qrcode)
        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_qrcode_status", mock_fetch_qrcode_status)

        start_response = client.post(f"{settings.API_V1_STR}/skills/weixin/qr/start", json={})
        assert start_response.status_code == 200
        session_key = start_response.json()["session_key"]

        wait_response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/qr/wait",
            json={"session_key": session_key}
        )
        assert wait_response.status_code == 200
        wait_data = wait_response.json()
        assert wait_data["success"] is True
        assert wait_data["connected"] is False
        assert wait_data["state"] == "half_success"
        assert wait_data["status"] == "scanned"
        assert wait_data["message"] == "waiting for confirm"
        assert wait_data["auth_id"] == "auth-123"
        assert wait_data["qrcode_url"] == "https://example.com/qr-pending.png"


def test_weixin_qr_wait_downgrades_confirmed_without_account_or_token_to_half_success(monkeypatch):
    with TestClient(app) as client:
        import skills.weixin_skill_adapter

        async def mock_fetch_login_qrcode(self, base_url, bot_type="3", timeout_seconds=15):
            return {
                "qrcode": "qr-invalid-confirmed",
                "qrcode_img_content": "https://example.com/qr-invalid-confirmed.png"
            }

        async def mock_fetch_qrcode_status(self, base_url, qrcode, timeout_seconds=35):
            return {
                "status": "confirmed",
                "ilink_user_id": "wx-user-missing-token",
                "binding_status": "bound"
            }

        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_login_qrcode", mock_fetch_login_qrcode)
        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_qrcode_status", mock_fetch_qrcode_status)

        start_response = client.post(f"{settings.API_V1_STR}/skills/weixin/qr/start", json={})
        assert start_response.status_code == 200
        session_key = start_response.json()["session_key"]

        wait_response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/qr/wait",
            json={"session_key": session_key}
        )
        assert wait_response.status_code == 200
        wait_data = wait_response.json()
        assert wait_data["success"] is True
        assert wait_data["connected"] is False
        assert wait_data["state"] == "half_success"
        assert wait_data["status"] == "scanned"
        assert wait_data["session_key"] == session_key
        assert wait_data["message"] == "扫码已确认，正在等待上游返回完整凭据"
        assert wait_data["qrcode"] == "qr-invalid-confirmed"
        assert wait_data["qrcode_url"] == "https://example.com/qr-invalid-confirmed.png"
        assert wait_data["base_url"] == "https://ilinkai.weixin.qq.com"
        assert wait_data["account_id"] == ""
        assert wait_data["token"] == ""
        assert wait_data["user_id"] == "wx-user-missing-token"
        assert wait_data["binding_status"] == "bound"
        assert wait_data["auth_id"] == ""
        assert wait_data["ticket"] == ""
        assert wait_data["hint"] == ""
        assert wait_data["redirect_host"] == ""

        config_response = client.get(f"{settings.API_V1_STR}/skills/weixin/config")
        assert config_response.status_code == 200
        config_data = config_response.json()
        assert config_data["account_id"] == ""
        assert config_data["token"] == ""



def test_weixin_config_accepts_json_string_payload():
    with TestClient(app) as client:
        payload = '{"account_id":"string-acc","token":"string-token","base_url":"https://string.url","timeout_seconds":21,"user_id":"string-user","binding_status":"bound"}'
        response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/config",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 200
        assert response.json() == {"message": "success"}

        config_response = client.get(f"{settings.API_V1_STR}/skills/weixin/config")
        assert config_response.status_code == 200
        config_data = config_response.json()
        assert config_data["account_id"] == "string-acc"
        assert config_data["token"] == "string-token"
        assert config_data["base_url"] == "https://string.url"
        assert config_data["timeout_seconds"] == 21
        assert config_data["user_id"] == "string-user"
        assert config_data["binding_status"] == "bound"



def test_weixin_health_check_accepts_form_string_payload(monkeypatch):
    with TestClient(app) as client:
        def mock_check_health(self, config):
            return {
                "ok": True,
                "account_id": config.account_id,
                "token": config.token,
                "base_url": config.base_url,
                "timeout_seconds": config.timeout_seconds
            }

        import skills.weixin_skill_adapter
        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "check_health", mock_check_health)

        response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/health-check",
            data="account_id=form-acc&token=form-token&base_url=https%3A%2F%2Fform.url&timeout_seconds=19",
            headers={"Content-Type": "text/plain"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["account_id"] == "form-acc"
        assert data["token"] == "form-token"
        assert data["base_url"] == "https://form.url"
        assert data["timeout_seconds"] == 19



def test_weixin_qr_wait_accepts_json_string_payload_without_session(monkeypatch):
    with TestClient(app) as client:
        import skills.weixin_skill_adapter

        async def mock_fetch_qrcode_status(self, base_url, qrcode, timeout_seconds=35):
            return {
                "status": "scaned",
                "message": "waiting confirm",
                "auth_id": "auth-from-string"
            }

        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_qrcode_status", mock_fetch_qrcode_status)

        response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/qr/wait",
            data='{"session_key":"string-session","qrcode":"qr-from-string","base_url":"https://string-poll.url","timeout_seconds":22}',
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["session_key"] == "string-session"
        assert data["qrcode"] == "qr-from-string"
        assert data["base_url"] == "https://string-poll.url"
        assert data["status"] == "scanned"
        assert data["state"] == "half_success"
        assert data["auth_id"] == "auth-from-string"



def test_weixin_qr_exit_accepts_form_string_payload(monkeypatch):
    with TestClient(app) as client:
        import skills.weixin_skill_adapter

        async def mock_fetch_login_qrcode(self, base_url, bot_type="3", timeout_seconds=15):
            return {
                "qrcode": "qr-exit-string",
                "qrcode_img_content": "https://example.com/qr-exit-string.png"
            }

        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_login_qrcode", mock_fetch_login_qrcode)

        start_response = client.post(f"{settings.API_V1_STR}/skills/weixin/qr/start", json={})
        assert start_response.status_code == 200
        session_key = start_response.json()["session_key"]

        exit_response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/qr/exit",
            data=f"session_key={session_key}&clear_config=false",
            headers={"Content-Type": "text/plain"}
        )
        assert exit_response.status_code == 200
        exit_data = exit_response.json()
        assert exit_data["message"] == "success"
        assert exit_data["cleared_sessions"] == 1



def test_weixin_qr_start_accepts_json_string_upstream_payload(monkeypatch):
    with TestClient(app) as client:
        import skills.weixin_skill_adapter

        async def mock_fetch_login_qrcode(self, base_url, bot_type="3", timeout_seconds=15):
            return '{"qrcode":"qr-json-payload","qrcode_img_content":"https://example.com/qr-json.png"}'

        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_login_qrcode", mock_fetch_login_qrcode)

        start_response = client.post(f"{settings.API_V1_STR}/skills/weixin/qr/start", json={})
        assert start_response.status_code == 200
        start_data = start_response.json()
        assert start_data["qrcode"] == "qr-json-payload"
        assert start_data["qrcode_url"] == "https://example.com/qr-json.png"



def test_weixin_qr_start_extracts_qrcode_from_key_value_string_payload(monkeypatch):
    with TestClient(app) as client:
        import skills.weixin_skill_adapter

        async def mock_fetch_login_qrcode(self, base_url, bot_type="3", timeout_seconds=15):
            return "qrcode=qr-kv-payload&qrcode_img_content=https%3A%2F%2Fexample.com%2Fqr-kv.png"

        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_login_qrcode", mock_fetch_login_qrcode)

        start_response = client.post(f"{settings.API_V1_STR}/skills/weixin/qr/start", json={})
        assert start_response.status_code == 200
        start_data = start_response.json()
        assert start_data["qrcode"] == "qr-kv-payload"
        assert start_data["qrcode_url"] == "https://example.com/qr-kv.png"



def test_weixin_qr_wait_parses_json_string_status_payload(monkeypatch):
    with TestClient(app) as client:
        import skills.weixin_skill_adapter

        async def mock_fetch_login_qrcode(self, base_url, bot_type="3", timeout_seconds=15):
            return {
                "qrcode": "qr-json-status",
                "qrcode_img_content": "https://example.com/qr-json-status.png"
            }

        async def mock_fetch_qrcode_status(self, base_url, qrcode, timeout_seconds=35):
            return '{"status":"confirmed","bot_token":"json-token","ilink_bot_id":"json-account","ilink_user_id":"json-user","binding_status":"bound","baseurl":"https://ilinkai.weixin.qq.com"}'

        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_login_qrcode", mock_fetch_login_qrcode)
        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_qrcode_status", mock_fetch_qrcode_status)

        start_response = client.post(f"{settings.API_V1_STR}/skills/weixin/qr/start", json={})
        assert start_response.status_code == 200
        session_key = start_response.json()["session_key"]

        wait_response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/qr/wait",
            json={"session_key": session_key}
        )
        assert wait_response.status_code == 200
        data = wait_response.json()
        assert data["status"] == "confirmed"
        assert data["state"] == "success"
        assert data["account_id"] == "json-account"
        assert data["token"] == "json-token"
        assert data["user_id"] == "json-user"
        assert data["binding_status"] == "bound"



def test_weixin_qr_wait_parses_key_value_string_status_payload(monkeypatch):
    with TestClient(app) as client:
        import skills.weixin_skill_adapter

        async def mock_fetch_login_qrcode(self, base_url, bot_type="3", timeout_seconds=15):
            return {
                "qrcode": "qr-kv-status",
                "qrcode_img_content": "https://example.com/qr-kv-status.png"
            }

        async def mock_fetch_qrcode_status(self, base_url, qrcode, timeout_seconds=35):
            return "status=scaned&auth_id=auth-kv&ticket=ticket-kv&hint=confirm-in-wechat"

        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_login_qrcode", mock_fetch_login_qrcode)
        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_qrcode_status", mock_fetch_qrcode_status)

        start_response = client.post(f"{settings.API_V1_STR}/skills/weixin/qr/start", json={})
        assert start_response.status_code == 200
        session_key = start_response.json()["session_key"]

        wait_response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/qr/wait",
            json={"session_key": session_key}
        )
        assert wait_response.status_code == 200
        data = wait_response.json()
        assert data["status"] == "scanned"
        assert data["state"] == "half_success"
        assert data["auth_id"] == "auth-kv"
        assert data["ticket"] == "ticket-kv"
        assert data["hint"] == "confirm-in-wechat"



def test_weixin_qr_wait_preserves_plain_string_status_message(monkeypatch):
    with TestClient(app) as client:
        import skills.weixin_skill_adapter

        async def mock_fetch_login_qrcode(self, base_url, bot_type="3", timeout_seconds=15):
            return {
                "qrcode": "qr-plain-status",
                "qrcode_img_content": "https://example.com/qr-plain-status.png"
            }

        async def mock_fetch_qrcode_status(self, base_url, qrcode, timeout_seconds=35):
            return "waiting for confirm"

        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_login_qrcode", mock_fetch_login_qrcode)
        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_qrcode_status", mock_fetch_qrcode_status)

        start_response = client.post(f"{settings.API_V1_STR}/skills/weixin/qr/start", json={})
        assert start_response.status_code == 200
        session_key = start_response.json()["session_key"]

        wait_response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/qr/wait",
            json={"session_key": session_key}
        )
        assert wait_response.status_code == 200
        data = wait_response.json()
        assert data["status"] == "waiting"
        assert data["state"] == "pending"
        assert data["message"] == "waiting for confirm"



def test_weixin_qr_wait_replays_confirmed_result_idempotently(monkeypatch):
    with TestClient(app) as client:
        import skills.weixin_skill_adapter

        call_count = {"wait": 0}

        async def mock_fetch_login_qrcode(self, base_url, bot_type="3", timeout_seconds=15):
            return {
                "qrcode": "qr-idempotent-confirmed",
                "qrcode_img_content": "https://example.com/qr-idempotent-confirmed.png"
            }

        async def mock_fetch_qrcode_status(self, base_url, qrcode, timeout_seconds=35):
            call_count["wait"] += 1
            return {
                "status": "confirmed",
                "bot_token": "bot-token-idempotent",
                "ilink_bot_id": "bot-account-idempotent",
                "ilink_user_id": "wx-user-idempotent",
                "binding_status": "confirmed",
                "baseurl": "https://redirect.weixin.qq.com"
            }

        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_login_qrcode", mock_fetch_login_qrcode)
        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_qrcode_status", mock_fetch_qrcode_status)

        start_response = client.post(f"{settings.API_V1_STR}/skills/weixin/qr/start", json={})
        assert start_response.status_code == 200
        session_key = start_response.json()["session_key"]

        first_response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/qr/wait",
            json={"session_key": session_key}
        )
        assert first_response.status_code == 200
        first_data = first_response.json()
        assert first_data["success"] is True
        assert first_data["state"] == "success"
        assert first_data["status"] == "confirmed"
        assert first_data["binding_status"] == "bound"

        second_response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/qr/wait",
            json={"session_key": session_key}
        )
        assert second_response.status_code == 200
        assert second_response.json() == first_data
        assert call_count["wait"] == 1

        config_response = client.get(f"{settings.API_V1_STR}/skills/weixin/config")
        assert config_response.status_code == 200
        config_data = config_response.json()
        assert config_data["user_id"] == "wx-user-idempotent"
        assert config_data["binding_status"] == "bound"


def test_weixin_qr_wait_handles_refreshing_status(monkeypatch):
    with TestClient(app) as client:
        import skills.weixin_skill_adapter

        async def mock_fetch_login_qrcode(self, base_url, bot_type="3", timeout_seconds=15):
            return {
                "qrcode": "qr-refreshing",
                "qrcode_img_content": "https://example.com/qr-refreshing.png"
            }

        async def mock_fetch_qrcode_status(self, base_url, qrcode, timeout_seconds=35):
            return {
                "status": "refreshing",
                "message": "二维码已过期，正在刷新"
            }

        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_login_qrcode", mock_fetch_login_qrcode)
        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_qrcode_status", mock_fetch_qrcode_status)

        start_response = client.post(f"{settings.API_V1_STR}/skills/weixin/qr/start", json={})
        assert start_response.status_code == 200
        session_key = start_response.json()["session_key"]

        wait_response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/qr/wait",
            json={"session_key": session_key}
        )
        assert wait_response.status_code == 200
        wait_data = wait_response.json()
        assert wait_data["success"] is True
        assert wait_data["connected"] is False
        assert wait_data["state"] == "half_success"
        assert wait_data["status"] == "refreshing"
        assert wait_data["qrcode"] == "qr-refreshing"
        assert wait_data["qrcode_url"] == "https://example.com/qr-refreshing.png"


def test_weixin_qr_wait_handles_expired_status(monkeypatch):
    with TestClient(app) as client:
        import skills.weixin_skill_adapter

        async def mock_fetch_login_qrcode(self, base_url, bot_type="3", timeout_seconds=15):
            return {
                "qrcode": "qr-expired",
                "qrcode_img_content": "https://example.com/qr-expired.png"
            }

        async def mock_fetch_qrcode_status(self, base_url, qrcode, timeout_seconds=35):
            return {
                "status": "expired",
                "message": "二维码已过期，请重新获取"
            }

        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_login_qrcode", mock_fetch_login_qrcode)
        monkeypatch.setattr(skills.weixin_skill_adapter.WeixinSkillAdapter, "fetch_qrcode_status", mock_fetch_qrcode_status)

        start_response = client.post(f"{settings.API_V1_STR}/skills/weixin/qr/start", json={})
        assert start_response.status_code == 200
        session_key = start_response.json()["session_key"]

        wait_response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/qr/wait",
            json={"session_key": session_key}
        )
        assert wait_response.status_code == 200
        wait_data = wait_response.json()
        assert wait_data["success"] is True
        assert wait_data["connected"] is False
        assert wait_data["state"] == "failed"
        assert wait_data["status"] == "expired"



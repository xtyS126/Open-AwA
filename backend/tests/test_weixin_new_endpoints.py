"""
微信新扩展接口测试。
覆盖消息发送、异步任务与监控接口的基础链路。
"""

import sys
import time
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
import api.routes.skills as skills_routes


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def override_get_current_user():
    class DummyUser:
        id = 1
        username = "test"

    return DummyUser()


app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_current_user] = override_get_current_user


@pytest.fixture(autouse=True)
def _reset_weixin_runtime_state():
    """
    清理微信路由中的全局运行态，避免测试间互相污染。
    """
    with skills_routes.WEIXIN_QR_SESSIONS_LOCK:
        skills_routes.WEIXIN_QR_SESSIONS.clear()
    skills_routes.WEIXIN_TASK_MANAGER = None
    yield
    with skills_routes.WEIXIN_QR_SESSIONS_LOCK:
        skills_routes.WEIXIN_QR_SESSIONS.clear()
    skills_routes.WEIXIN_TASK_MANAGER = None


def _seed_weixin_config() -> None:
    db = TestingSessionLocal()
    try:
        db.query(Skill).delete()
        db.add(
            Skill(
                id="weixin-seed",
                name="weixin_dispatch",
                version="1.0.0",
                description="seed",
                enabled=True,
                category="general",
                tags="[]",
                dependencies="[]",
                author="test",
                config=(
                    "adapter: weixin\n"
                    "weixin:\n"
                    "  account_id: test-account\n"
                    "  token: test-token\n"
                    "  base_url: https://ilinkai.weixin.qq.com\n"
                    "  timeout_seconds: 15\n"
                ),
            )
        )
        db.commit()
    finally:
        db.close()


def test_weixin_message_endpoint(monkeypatch):
    _seed_weixin_config()

    async def mock_send_text_message(config, to_user_id, text, context_token):
        return {
            "request": {"client_id": "msg-1", "to_user_id": to_user_id, "text": text},
            "response": {"ret": 0},
        }

    monkeypatch.setattr("api.routes.skills.send_text_message", mock_send_text_message)

    with TestClient(app) as client:
        response = client.post(
            f"{settings.API_V1_STR}/skills/weixin/message",
            json={"to_user_id": "wxid_xxx@im.wechat", "text": "hello", "context_token": "ctx-token"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message_id"] == "msg-1"


def test_weixin_task_endpoint():
    _seed_weixin_config()
    with TestClient(app) as client:
        create_resp = client.post(
            f"{settings.API_V1_STR}/skills/weixin/task",
            json={"task_type": "deep_research", "params": {"query": "AI"}},
        )
        assert create_resp.status_code == 200
        task_id = create_resp.json()["task_id"]

        status_resp = client.get(f"{settings.API_V1_STR}/skills/weixin/task/{task_id}")
        assert status_resp.status_code == 200
        first_status = status_resp.json()
        assert first_status["task_id"] == task_id
        assert first_status["status"] in {"pending", "running", "completed"}

        time.sleep(1.0)
        final_status = client.get(f"{settings.API_V1_STR}/skills/weixin/task/{task_id}").json()
        assert final_status["status"] in {"completed", "running"}
        assert isinstance(final_status["progress"], int)


def test_weixin_monitor_endpoints(monkeypatch):
    _seed_weixin_config()

    class DummyStatus:
        def to_dict(self):
            return {"account_id": "test-account", "running": True, "state": "running"}

    class DummyMonitor:
        def get_status(self):
            return DummyStatus()

    async def mock_start_monitor(account_id, config, state_manager):
        return DummyMonitor()

    async def mock_stop_monitor(account_id):
        return None

    def mock_get_monitor_status(account_id):
        return {"account_id": account_id, "running": True, "state": "running"}

    def mock_get_all_monitors():
        return {"test-account": {"account_id": "test-account", "running": True, "state": "running"}}

    monkeypatch.setattr("api.routes.skills.start_monitor", mock_start_monitor)
    monkeypatch.setattr("api.routes.skills.stop_monitor", mock_stop_monitor)
    monkeypatch.setattr("api.routes.skills.get_monitor_status", mock_get_monitor_status)
    monkeypatch.setattr("api.routes.skills.get_all_monitors", mock_get_all_monitors)

    with TestClient(app) as client:
        start_resp = client.post(f"{settings.API_V1_STR}/skills/weixin/monitor/start", json={"account_id": "test-account"})
        assert start_resp.status_code == 200
        assert start_resp.json()["success"] is True

        status_resp = client.get(f"{settings.API_V1_STR}/skills/weixin/monitor/status")
        assert status_resp.status_code == 200
        assert "test-account" in status_resp.json()["monitors"]

        stop_resp = client.post(f"{settings.API_V1_STR}/skills/weixin/monitor/stop", json={"account_id": "test-account"})
        assert stop_resp.status_code == 200
        assert stop_resp.json()["success"] is True


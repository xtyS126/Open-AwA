"""
后端接口回归测试，覆盖技能配置一致性、记忆权限链路与日志接口稳定性。
"""

import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_current_user, get_db
from config.logging import _LOG_BUFFER
from config.settings import settings
from db.models import Base, ConversationRecord, LongTermMemory, ShortTermMemory, Skill
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


def _reset_tables():
    """清理本测试文件涉及的表。"""
    db = TestingSessionLocal()
    try:
        db.query(ShortTermMemory).delete()
        db.query(LongTermMemory).delete()
        db.query(ConversationRecord).delete()
        db.query(Skill).delete()
        db.commit()
    finally:
        db.close()
    _LOG_BUFFER.clear()


def setup_function():
    """每个用例前清理测试数据。"""
    _reset_tables()


def teardown_function():
    """每个用例后清理测试数据。"""
    _reset_tables()


@contextmanager
def _test_client():
    """为每个测试用例局部注入依赖覆盖，避免污染其他测试模块。"""
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides = previous_overrides


def test_weixin_config_uses_dict_storage_and_skills_route_returns_normalized_config():
    """验证微信配置写入后采用字典存储，且技能列表返回统一配置结构。"""
    payload = {
        "account_id": "wx-account",
        "token": "wx-token",
        "base_url": "https://wx.example.com",
        "timeout_seconds": 25,
        "user_id": "wx-user",
        "binding_status": "bound",
    }

    with _test_client() as client:
        response = client.post(f"{settings.API_V1_STR}/skills/weixin/config", json=payload)
        assert response.status_code == 200

        db = TestingSessionLocal()
        try:
            skill = db.query(Skill).filter(Skill.name == "weixin_dispatch").first()
            assert skill is not None
            assert isinstance(skill.config, dict)
            assert skill.config["weixin"]["account_id"] == "wx-account"
            assert skill.config["weixin"]["token"] == "wx-token"
        finally:
            db.close()

        skills_response = client.get(f"{settings.API_V1_STR}/skills")
        assert skills_response.status_code == 200
        skills_data = skills_response.json()
        assert len(skills_data) == 1
        assert skills_data[0]["config"]["weixin"]["account_id"] == "wx-account"
        assert skills_data[0]["config"]["weixin"]["binding_status"] == "bound"


def test_get_short_term_default_returns_empty_list_when_session_not_created():
    """验证未建立会话时读取默认短期记忆返回空列表而不是 403。"""
    with _test_client() as client:
        response = client.get(f"{settings.API_V1_STR}/memory/short-term/default")
        assert response.status_code == 200
        assert response.json() == []


def test_get_short_term_returns_403_for_other_users_session():
    """验证已存在且属于其他用户的会话仍然维持 403。"""
    db = TestingSessionLocal()
    try:
        db.add(
            ConversationRecord(
                session_id="shared-session",
                user_id="other-user",
                node_type="chat",
                user_message="hello",
                status="success",
            )
        )
        db.commit()
    finally:
        db.close()

    with _test_client() as client:
        response = client.get(f"{settings.API_V1_STR}/memory/short-term/shared-session")
        assert response.status_code == 403
        assert response.json()["error"]["message"] == "Access denied: session does not belong to current user"


def test_long_term_memory_routes_are_scoped_to_current_user():
    """验证长期记忆列表只返回当前用户数据。"""
    db = TestingSessionLocal()
    try:
        db.add(
            LongTermMemory(
                user_id="user-1",
                content="current-user-memory",
                embedding=[],
                importance=0.9,
            )
        )
        db.add(
            LongTermMemory(
                user_id="other-user",
                content="other-user-memory",
                embedding=[],
                importance=0.1,
            )
        )
        db.commit()
    finally:
        db.close()

    with _test_client() as client:
        response = client.get(f"{settings.API_V1_STR}/memory/long-term")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["content"] == "current-user-memory"


def test_logs_error_summary_accepts_hours_query():
    """验证错误摘要接口支持 hours 参数并返回统计结果。"""
    _LOG_BUFFER.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": "ERROR",
            "module": "tests",
            "event": "route_regression_error",
            "message": "simulated error",
            "request_id": "req-summary",
            "extra": {},
        }
    )
    _LOG_BUFFER.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": "INFO",
            "module": "tests",
            "event": "route_regression_info",
            "message": "simulated info",
            "request_id": "req-info",
            "extra": {},
        }
    )

    with _test_client() as client:
        response = client.get(f"{settings.API_V1_STR}/logs/errors/summary?hours=24")
        assert response.status_code == 200
        data = response.json()
        assert data["total_errors"] == 1
        assert data["error_types"][0]["type"] == "route_regression_error"


def test_client_errors_accepts_extra_fields_that_conflict_with_bind_keywords():
    """验证前端错误上报在 extra 含保留字段时不会抛出 500。"""
    with _test_client() as client:
        response = client.post(
            f"{settings.API_V1_STR}/logs/client-errors",
            json={
                "level": "warning",
                "message": "frontend runtime failure",
                "source": "communication-page",
                "stack": "traceback",
                "url": "http://localhost:5173/communication",
                "user_agent": "pytest",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "extra": {
                    "module": "chat",
                    "event": "frontend_runtime",
                    "request_id": "req-client-error",
                },
            },
        )
        assert response.status_code == 200
        assert response.json() == {"status": "received"}

        assert _LOG_BUFFER
        client_error_logs = [entry for entry in _LOG_BUFFER if entry.get("event") == "client_error"]
        assert client_error_logs
        assert client_error_logs[-1]["extra"]["client_extra"]["module"] == "chat"

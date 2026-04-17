"""
后端接口回归测试，覆盖技能配置一致性、记忆权限链路与日志接口稳定性。
"""

import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.security import decrypt_secret_value
from api.routes import chat as chat_route

from api.dependencies import get_current_user, get_db
from config.logging import _LOG_BUFFER
from config.settings import settings
from db.models import Base, ConversationRecord, LongTermMemory, ShortTermMemory, Skill, init_db
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


def override_get_other_user():
    """提供另一个测试用户，用于验证跨用户访问控制。"""

    class DummyUser:
        id = "user-2"
        username = "otheruser"
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
            # 令牌已加密存储，需解密后校验原始值
            assert decrypt_secret_value(skill.config["weixin"]["token"]) == "wx-token"
        finally:
            db.close()

        skills_response = client.get(f"{settings.API_V1_STR}/skills")
        assert skills_response.status_code == 200
        skills_data = skills_response.json()
        assert len(skills_data) == 1
        assert skills_data[0]["config"]["weixin"]["account_id"] == "wx-account"
        assert skills_data[0]["config"]["weixin"]["binding_status"] == "bound"


def test_init_db_migrates_legacy_skill_yaml_config_for_skills_routes():
    """验证启动初始化会将历史 YAML 技能配置迁移为合法 JSON，避免技能相关接口返回 500。"""
    legacy_yaml = (
        "adapter: weixin\n"
        "description: Weixin Clawbot communication skill\n"
        "name: weixin_dispatch\n"
        "version: 1.0.0\n"
        "weixin:\n"
        "  account_id: wx-account\n"
        "  token: wx-token\n"
        "  base_url: https://wx.example.com\n"
        "  timeout_seconds: 20\n"
        "  user_id: wx-user\n"
        "  binding_status: bound\n"
    )

    db = TestingSessionLocal()
    try:
        db.execute(
            text(
                "INSERT INTO skills (id, name, version, description, config, enabled, tags, dependencies, author, category, usage_count, installed_at) "
                "VALUES (:id, :name, :version, :description, :config, :enabled, :tags, :dependencies, :author, :category, :usage_count, CURRENT_TIMESTAMP)"
            ),
            {
                "id": "legacy-weixin",
                "name": "weixin_dispatch",
                "version": "1.0.0",
                "description": "legacy weixin skill",
                "config": legacy_yaml,
                "enabled": 1,
                "tags": "",
                "dependencies": "",
                "author": "legacy",
                "category": "general",
                "usage_count": 0,
            },
        )
        db.commit()
    finally:
        db.close()

    init_db(bind_engine=engine)

    with _test_client() as client:
        skills_response = client.get(f"{settings.API_V1_STR}/skills")
        assert skills_response.status_code == 200
        skills_data = skills_response.json()
        assert len(skills_data) == 1
        assert skills_data[0]["name"] == "weixin_dispatch"
        assert skills_data[0]["config"]["weixin"]["account_id"] == "wx-account"

        config_response = client.get(f"{settings.API_V1_STR}/skills/weixin/config")
        assert config_response.status_code == 200
        config_data = config_response.json()
        assert config_data["account_id"] == "wx-account"
        # GET 接口应返回解密后的原始令牌
        assert config_data["token"] == "wx-token"
        assert config_data["user_id"] == "wx-user"
        assert config_data["binding_status"] == "bound"


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


def test_chat_uploaded_file_only_accessible_by_owner(tmp_path):
    """聊天附件应仅允许上传者本人访问，避免跨用户文件泄露。"""
    previous_upload_dir = chat_route.UPLOAD_DIR
    chat_route.UPLOAD_DIR = tmp_path

    try:
        with _test_client() as client:
            upload_response = client.post(
                f"{settings.API_V1_STR}/chat/upload",
                files={"file": ("private-note.txt", b"hello owner", "text/plain")},
            )
            assert upload_response.status_code == 200
            uploaded_url = upload_response.json()["url"]

            owner_response = client.get(uploaded_url)
            assert owner_response.status_code == 200
            assert owner_response.content == b"hello owner"

            app.dependency_overrides[get_current_user] = override_get_other_user
            intruder_response = client.get(uploaded_url)
            assert intruder_response.status_code == 403
    finally:
        chat_route.UPLOAD_DIR = previous_upload_dir
        app.dependency_overrides[get_current_user] = override_get_current_user


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

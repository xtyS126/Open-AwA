"""
用户偏好接口回归测试，覆盖 GET/PUT /api/user/preferences 的核心行为。
"""

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
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


class DummyUser:
    """模拟已认证用户，支持 profile_data 属性读写。"""
    id = "user-preferences-test"
    username = "preferences-tester"
    role = "user"
    profile_data = None


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


_shared_user = DummyUser()


def override_get_current_user():
    """返回共享用户实例，确保跨请求状态持久化。"""
    return _shared_user


@app.get("/api/user/preferences-no-auth")
async def _preferences_no_auth_endpoint():
    """直接返回空字典的辅助端点，供 401 测试使用。"""
    pass


@contextmanager
def _test_client():
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides = previous_overrides


def setup_function():
    _shared_user.profile_data = None


def test_get_preferences_returns_empty_when_no_data():
    """无 profile_data 时返回空字典。"""
    _shared_user.profile_data = None
    with _test_client() as client:
        resp = client.get("/api/user/preferences")
    assert resp.status_code == 200
    assert resp.json() == {"preferences": {}}


def test_get_preferences_returns_empty_when_no_preferences_key():
    """profile_data 存在但无 preferences 键时返回空字典。"""
    _shared_user.profile_data = {"generated_at": "2026-01-01T00:00:00"}
    with _test_client() as client:
        resp = client.get("/api/user/preferences")
    assert resp.status_code == 200
    assert resp.json() == {"preferences": {}}


def test_get_preferences_returns_stored_values():
    """有存储偏好时返回完整字典。"""
    _shared_user.profile_data = {"preferences": {"theme": "dark", "language": "zh"}}
    with _test_client() as client:
        resp = client.get("/api/user/preferences")
    assert resp.status_code == 200
    assert resp.json() == {"preferences": {"theme": "dark", "language": "zh"}}


def test_put_preferences_stores_values():
    """PUT 写入偏好后 GET 可读取。"""
    _shared_user.profile_data = None
    with _test_client() as client:
        put_resp = client.put("/api/user/preferences", json={
            "preferences": {"theme": "dark", "selectedModel": "deepseek-chat"}
        })
        assert put_resp.status_code == 200
        put_data = put_resp.json()
        assert put_data["preferences"]["theme"] == "dark"
        assert put_data["preferences"]["selectedModel"] == "deepseek-chat"

        # 通过 GET 验证持久化
        get_resp = client.get("/api/user/preferences")
        assert get_resp.status_code == 200
        get_data = get_resp.json()
        assert get_data["preferences"]["theme"] == "dark"
        assert get_data["preferences"]["selectedModel"] == "deepseek-chat"


def test_put_preferences_does_incremental_merge():
    """增量合并：第二次 PUT 不覆盖已有的其他键。"""
    _shared_user.profile_data = {"preferences": {"theme": "dark", "language": "zh"}}
    with _test_client() as client:
        resp = client.put("/api/user/preferences", json={
            "preferences": {"selectedModel": "gpt-4"}
        })
    assert resp.status_code == 200
    prefs = resp.json()["preferences"]
    assert prefs["theme"] == "dark"
    assert prefs["language"] == "zh"
    assert prefs["selectedModel"] == "gpt-4"


def test_put_preferences_overwrites_existing_keys():
    """同一键的第二次 PUT 覆盖旧值。"""
    _shared_user.profile_data = {"preferences": {"theme": "light"}}
    with _test_client() as client:
        resp = client.put("/api/user/preferences", json={
            "preferences": {"theme": "dark"}
        })
    assert resp.status_code == 200
    assert resp.json()["preferences"]["theme"] == "dark"


def test_put_preserves_non_preference_profile_keys():
    """PUT 不影响 profile_data 中的其他键（如 generated_at）。"""
    _shared_user.profile_data = {
        "generated_at": "2026-01-01T00:00:00",
        "interests": ["coding"],
        "preferences": {"theme": "light"},
    }
    with _test_client() as client:
        client.put("/api/user/preferences", json={
            "preferences": {"theme": "dark"}
        })
    assert _shared_user.profile_data["generated_at"] == "2026-01-01T00:00:00"
    assert _shared_user.profile_data["interests"] == ["coding"]


def test_unauthorized_returns_401():
    """未认证请求返回 401 错误。"""
    with TestClient(app) as client:
        resp = client.get("/api/user/preferences")
    assert resp.status_code == 401

"""
skills/market 错误降级测试。

覆盖场景：
1. 无配置源（settings.SKILL_MARKET_SOURCES = []）→ 返回空列表，不抛异常
2. 所有源失败（httpx 抛 TimeoutError / HTTPError）→ 返回空列表 + source_errors，不抛异常
3. 单源失败 + 单源成功 → 返回可用源 skills + source_errors
4. 路由层错误降级：fetch_market_listing 返回错误时，路由返回 200 + 空列表

测试约定（AGENTS.md §6）：
- 所有注释中文
- 禁止 emoji
- mock 外部服务（httpx、settings），不 mock 内部逻辑
- 使用 pytest.mark.asyncio + 直接 await（Python 3.12）
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from db.models import Base
import billing.models  # 确保计费模型在 create_all 前已注册到 Base.metadata
from api.dependencies import get_db, get_current_user
from skills.pool_manager import SkillPoolManager


# ── 测试用内存数据库与依赖覆盖 ──────────────────────────────────

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    """测试用数据库会话覆盖。"""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def override_get_current_user():
    """测试用单用户覆盖，避免触发真实鉴权链路。"""
    class DummyUser:
        id = 1
        username = "testuser"
    return DummyUser()


@pytest.fixture(autouse=True)
def isolate_dependency_overrides():
    """每个用例独立依赖覆盖，避免污染全局 app 状态。"""
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    try:
        yield
    finally:
        app.dependency_overrides = previous_overrides


# ── SkillPoolManager.fetch_market_listing 单元测试 ──────────────────────


@pytest.mark.asyncio
async def test_fetch_market_listing_empty_sources():
    """无配置源时返回空列表，不抛异常。"""
    pool = SkillPoolManager()
    with patch("config.settings.settings.SKILL_MARKET_SOURCES", []):
        result = await pool.fetch_market_listing()

    assert result["skills"] == []
    assert result["source_errors"] == []


@pytest.mark.asyncio
async def test_fetch_market_listing_all_sources_fail():
    """所有源失败时返回空列表 + source_errors，不抛异常。"""
    pool = SkillPoolManager()
    sources = [{"url": "http://invalid.example.com/api/skills", "name": "test_source"}]

    # 构造一个会抛 TimeoutError 的 mock AsyncClient
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock(side_effect=httpx.TimeoutException("timeout"))

    with patch("config.settings.settings.SKILL_MARKET_SOURCES", sources):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            # async with AsyncClient() as client: __aenter__ 返回 mock_client
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_client_cls.return_value = mock_client

            result = await pool.fetch_market_listing()

    assert result["skills"] == []
    assert len(result["source_errors"]) == 1
    assert result["source_errors"][0]["source"] == "test_source"
    # 错误信息中包含 timeout 关键字（具体文案由 httpx.HTTPError 子类决定）
    assert "timeout" in result["source_errors"][0]["error"].lower() or "http" in result["source_errors"][0]["error"].lower()


@pytest.mark.asyncio
async def test_fetch_market_listing_partial_failure():
    """单源失败时返回可用源数据 + source_errors。"""
    pool = SkillPoolManager()
    sources = [
        {"url": "http://good.example.com/api/skills", "name": "good_source"},
        {"url": "http://bad.example.com/api/skills", "name": "bad_source"},
    ]

    # 成功响应数据
    good_response_data = {
        "skills": [
            {"name": "skill_a", "description": "A skill", "version": "1.0.0", "author": "tester"},
        ]
    }

    async def fake_get(url, headers=None):
        if "good.example.com" in url:
            resp = MagicMock()
            resp.raise_for_status = MagicMock(return_value=None)
            resp.json = MagicMock(return_value=good_response_data)
            return resp
        # 坏源抛 HTTPError
        raise httpx.ConnectError("connection refused")

    with patch("config.settings.settings.SKILL_MARKET_SOURCES", sources):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = fake_get
            mock_client_cls.return_value = mock_client

            result = await pool.fetch_market_listing()

    # 成功源的技能被合并到 skills
    assert len(result["skills"]) == 1
    assert result["skills"][0]["name"] == "skill_a"
    assert result["skills"][0]["source"] == "good_source"
    # 失败源记录到 source_errors
    assert len(result["source_errors"]) == 1
    assert result["source_errors"][0]["source"] == "bad_source"


@pytest.mark.asyncio
async def test_fetch_market_listing_missing_url_in_source():
    """源配置缺少 url 字段时记录到 source_errors，不影响其他源。"""
    pool = SkillPoolManager()
    sources = [
        {"name": "no_url_source"},  # 缺 url
        {"url": "http://good.example.com/api/skills", "name": "good_source"},
    ]

    good_response_data = {"skills": [{"name": "skill_b", "description": "B"}]}

    async def fake_get(url, headers=None):
        resp = MagicMock()
        resp.raise_for_status = MagicMock(return_value=None)
        resp.json = MagicMock(return_value=good_response_data)
        return resp

    with patch("config.settings.settings.SKILL_MARKET_SOURCES", sources):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = fake_get
            mock_client_cls.return_value = mock_client

            result = await pool.fetch_market_listing()

    assert len(result["skills"]) == 1
    assert result["skills"][0]["name"] == "skill_b"
    assert len(result["source_errors"]) == 1
    assert result["source_errors"][0]["source"] == "no_url_source"
    assert "missing url" in result["source_errors"][0]["error"]


# ── 路由层错误降级测试 ──────────────────────────────────────


def test_get_market_skills_route_returns_200_on_all_sources_fail():
    """路由层错误降级：所有源失败时返回 200 + 空列表 + source_errors。"""
    sources = [{"url": "http://invalid.example.com/api/skills", "name": "test_source"}]

    with patch("config.settings.settings.SKILL_MARKET_SOURCES", sources):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client_cls.return_value = mock_client

            with TestClient(app) as client:
                response = client.get("/api/skills/market")

    assert response.status_code == 200
    data = response.json()
    assert data["skills"] == []
    assert data["total"] == 0
    assert len(data["source_errors"]) == 1
    assert data["source_errors"][0]["source"] == "test_source"


def test_get_market_skills_route_returns_200_on_empty_sources():
    """路由层错误降级：无配置源时返回 200 + 空列表。"""
    with patch("config.settings.settings.SKILL_MARKET_SOURCES", []):
        with TestClient(app) as client:
            response = client.get("/api/skills/market")

    assert response.status_code == 200
    data = response.json()
    assert data["skills"] == []
    assert data["total"] == 0
    assert data["source_errors"] == []


def test_get_market_skills_route_returns_partial_skills_on_partial_failure():
    """路由层：单源失败时返回 200 + 可用源 skills + source_errors。"""
    sources = [
        {"url": "http://good.example.com/api/skills", "name": "good_source"},
        {"url": "http://bad.example.com/api/skills", "name": "bad_source"},
    ]
    good_response_data = {
        "skills": [
            {"name": "skill_a", "description": "A", "version": "1.0.0", "author": "tester"},
        ]
    }

    async def fake_get(url, headers=None):
        if "good.example.com" in url:
            resp = MagicMock()
            resp.raise_for_status = MagicMock(return_value=None)
            resp.json = MagicMock(return_value=good_response_data)
            return resp
        raise httpx.ConnectError("refused")

    with patch("config.settings.settings.SKILL_MARKET_SOURCES", sources):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = fake_get
            mock_client_cls.return_value = mock_client

            with TestClient(app) as client:
                response = client.get("/api/skills/market")

    assert response.status_code == 200
    data = response.json()
    assert len(data["skills"]) == 1
    assert data["skills"][0]["name"] == "skill_a"
    assert data["total"] == 1
    assert len(data["source_errors"]) == 1


def test_get_market_skills_route_survives_pool_manager_exception():
    """路由层兜底：fetch_market_listing 抛未预期异常时仍返回 200，不抛 500。"""
    with patch("config.settings.settings.SKILL_MARKET_SOURCES", [{"url": "http://x", "name": "x"}]):
        with patch(
            "skills.pool_manager.SkillPoolManager.fetch_market_listing",
            new_callable=AsyncMock,
            side_effect=RuntimeError("unexpected runtime error"),
        ):
            with TestClient(app) as client:
                response = client.get("/api/skills/market")

    assert response.status_code == 200
    data = response.json()
    assert data["skills"] == []
    assert data["total"] == 0
    assert "unexpected runtime error" in data["error"]

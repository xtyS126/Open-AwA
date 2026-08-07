"""多 Agent 讨论 API 路由层测试。

测试目标：
  覆盖 api/routes/discussions.py 的 6 个端点：
  - POST /api/discussions 创建讨论任务
  - GET /api/discussions 分页查询列表
  - GET /api/discussions/{id} 查询详情
  - POST /api/discussions/{id}/revise 提交修订
  - GET /api/discussions/{id}/stream SSE 流式订阅
  - POST /api/discussions/{id}/force-execute 紧急旁路执行

测试策略：
  - 应用：构造仅注册 discussions.router 的独立 FastAPI 应用，避免加载完整 main.py
  - 数据库：in-memory SQLite + StaticPool，通过 dependency_overrides 替换 get_db
  - 鉴权：通过 dependency_overrides 替换 get_current_user，区分普通用户与 admin
  - 编排器：patch _get_orchestrator 返回测试 orchestrator（mock LLM + 禁用后台触发）
  - SSE：patch _resolve_sse_user 控制鉴权，patch stream_discussion_events 控制流终止

测试隔离：
  每个测试通过 fixture 获取独立 TestClient 与干净数据库；
  模块级 in-memory 数据库保证测试间互不干扰。
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# 将 backend 目录加入 sys.path
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from api.dependencies import get_current_user  # noqa: E402
from api.routes import discussions as discussions_module  # noqa: E402
from api.routes.discussions import router as discussions_router  # noqa: E402
from core.discussion.orchestrator import DiscussionOrchestrator  # noqa: E402
from db.models import AuditLog, Base, DiscussionTask, DiscussionVote, User, get_db  # noqa: E402


# ── 模块级测试数据库 ──────────────────────────────────────────────
_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
# force-execute 审计为 fail-closed 路径，测试库必须含 audit_logs 表
Base.metadata.create_all(
    bind=_engine,
    tables=[AuditLog.__table__, User.__table__, DiscussionTask.__table__, DiscussionVote.__table__],
)


def _db_session_factory():
    """返回测试数据库会话，供 orchestrator 使用（支持上下文管理器协议）。"""
    return _TestingSessionLocal()


def _override_get_db():
    """FastAPI 依赖：提供测试数据库会话。"""
    db = _TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


class _DummyUser:
    """模拟已认证用户，满足路由依赖的最小字段集。"""

    def __init__(self, user_id: str = "u1", username: str = "tester", role: str = "user"):
        self.id = user_id
        self.username = username
        self.role = role


def _override_get_current_user_normal():
    """返回普通用户。"""
    return _DummyUser(user_id="u1", role="user")


def _override_get_current_user_admin():
    """返回管理员用户。"""
    return _DummyUser(user_id="admin-1", username="admin", role="admin")


def _make_llm_caller():
    """构造默认 approve 的 async LLM caller。"""
    async def _caller(messages):
        return '{"vote": "approve", "reason": "测试通过"}'
    return _caller


def _build_test_orchestrator() -> DiscussionOrchestrator:
    """
    构造测试用 orchestrator，禁用后台自动触发。

    _safe_run_discussion_round 与 _safe_execute_approved_action patch 为 AsyncMock，
    保证 create_task/revise/tally 不触发后台任务，测试确定性。
    execute_approved_action 也 patch 为 AsyncMock，避免触发真实 tool_registry。
    """
    orch = DiscussionOrchestrator(
        db_session_factory=_db_session_factory,
        llm_caller=_make_llm_caller(),
    )
    orch._safe_run_discussion_round = AsyncMock(return_value=None)
    orch._safe_execute_approved_action = AsyncMock(return_value=None)
    orch.execute_approved_action = AsyncMock(return_value={"ok": True, "result": "mocked"})
    return orch


def _seed_user(user_id: str = "u1", username: str = "tester", role: str = "user"):
    """插入测试用户记录。"""
    with _TestingSessionLocal() as db:
        user = User(id=user_id, username=username, password_hash="hash", role=role)
        db.add(user)
        db.commit()


def _seed_task(
    *,
    user_id: str = "u1",
    status: str = "created",
    round_num: int = 1,
    max_rounds: int = 3,
    title: str = "测试任务",
    description: str = "测试描述",
) -> str:
    """直接插入讨论任务记录，返回任务 ID。"""
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    with _TestingSessionLocal() as db:
        task = DiscussionTask(
            id=task_id,
            user_id=user_id,
            title=title,
            description=description,
            proposed_action={"type": "tool_call", "payload": {"tool": "test_tool"}},
            context={},
            status=status,
            round=round_num,
            max_rounds=max_rounds,
            created_at=now,
            updated_at=now,
        )
        db.add(task)
        db.commit()
    return task_id


def _seed_vote(
    task_id: str,
    role: str = "critic",
    round_num: int = 1,
    vote: str = "approve",
    reason: str = "通过",
) -> str:
    """直接插入投票记录。"""
    vote_id = str(uuid.uuid4())
    with _TestingSessionLocal() as db:
        db.add(DiscussionVote(
            id=vote_id,
            discussion_id=task_id,
            role=role,
            round=round_num,
            vote=vote,
            reason=reason,
            transcript=[],
        ))
        db.commit()
    return vote_id


# ── fixture ──────────────────────────────────────────────────────


@pytest.fixture
def app() -> FastAPI:
    """构造仅注册 discussions.router 的 FastAPI 应用。"""
    _app = FastAPI()
    _app.include_router(discussions_router)
    return _app


@pytest.fixture
def test_orchestrator():
    """提供测试 orchestrator 实例，patch _get_orchestrator 返回该实例。"""
    orch = _build_test_orchestrator()
    with patch.object(discussions_module, "_get_orchestrator", return_value=orch):
        # 同时 patch SessionLocal，供 force_execute 路由内直接使用
        with patch.object(discussions_module, "SessionLocal", _TestingSessionLocal):
            yield orch


@pytest.fixture
def client(app, test_orchestrator) -> Iterator[TestClient]:
    """提供注入了依赖覆盖的 TestClient，默认以普通用户身份请求。"""
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user_normal
    # 前置清理数据库
    with _TestingSessionLocal() as db:
        db.query(DiscussionVote).delete()
        db.query(DiscussionTask).delete()
        db.query(User).delete()
        db.commit()
    _seed_user()
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides = previous_overrides
        # 后置清理
        with _TestingSessionLocal() as db:
            db.query(DiscussionVote).delete()
            db.query(DiscussionTask).delete()
            db.query(User).delete()
            db.commit()


@pytest.fixture
def admin_client(app, test_orchestrator) -> Iterator[TestClient]:
    """提供 admin 用户的 TestClient。"""
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user_admin
    with _TestingSessionLocal() as db:
        db.query(DiscussionVote).delete()
        db.query(DiscussionTask).delete()
        db.query(User).delete()
        db.commit()
    _seed_user(user_id="admin-1", username="admin", role="admin")
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides = previous_overrides
        with _TestingSessionLocal() as db:
            db.query(DiscussionVote).delete()
            db.query(DiscussionTask).delete()
            db.query(User).delete()
            db.commit()


def _valid_create_payload(**overrides) -> dict:
    """构造合法的创建讨论任务请求体。"""
    payload = {
        "title": "清理临时文件",
        "description": "清理 /tmp 目录下的过期日志文件",
        "proposed_action": {
            "type": "tool_call",
            "payload": {"tool": "file_manager", "parameters": {"path": "/tmp"}},
        },
        "context": {"priority": "low"},
        "max_rounds": 3,
    }
    payload.update(overrides)
    return payload


# ── POST / 创建任务 ──────────────────────────────────────────────


def test_post_create_returns_201_with_discussion_id(client):
    """提交合法请求 -> 201，响应含 discussion_id 与 status: created。"""
    response = client.post("/api/discussions", json=_valid_create_payload())

    assert response.status_code == 201
    body = response.json()
    assert "discussion_id" in body
    assert body["status"] == "created"
    # 校验任务已写入数据库
    with _TestingSessionLocal() as db:
        task = db.get(DiscussionTask, body["discussion_id"])
        assert task is not None


def test_post_create_rejects_empty_title(client):
    """缺 title -> 422。"""
    payload = _valid_create_payload()
    payload["title"] = ""
    response = client.post("/api/discussions", json=payload)
    assert response.status_code == 422


def test_post_create_rejects_too_long_title(client):
    """title 长度 > 200 -> 422。"""
    payload = _valid_create_payload()
    payload["title"] = "x" * 201
    response = client.post("/api/discussions", json=payload)
    assert response.status_code == 422


def test_post_create_rejects_too_long_description(client):
    """description 长度 > 5000 -> 422。"""
    payload = _valid_create_payload()
    payload["description"] = "x" * 5001
    response = client.post("/api/discussions", json=payload)
    assert response.status_code == 422


def test_post_create_rejects_missing_proposed_action_type(client):
    """proposed_action 缺 type 字段 -> 422。"""
    payload = _valid_create_payload()
    payload["proposed_action"] = {"payload": {"tool": "x"}}
    response = client.post("/api/discussions", json=payload)
    assert response.status_code == 422


def test_post_create_rejects_invalid_proposed_action_type(client):
    """proposed_action.type 非法值 -> 422。"""
    payload = _valid_create_payload()
    payload["proposed_action"] = {"type": "invalid_type", "payload": {}}
    response = client.post("/api/discussions", json=payload)
    assert response.status_code == 422


def test_post_create_rejects_max_rounds_over_5(client):
    """max_rounds=10 超过上限 5 -> 422。"""
    payload = _valid_create_payload()
    payload["max_rounds"] = 10
    response = client.post("/api/discussions", json=payload)
    assert response.status_code == 422


def test_post_create_rejects_max_rounds_zero(client):
    """max_rounds=0 低于下限 1 -> 422。"""
    payload = _valid_create_payload()
    payload["max_rounds"] = 0
    response = client.post("/api/discussions", json=payload)
    assert response.status_code == 422


# ── GET / 列表 ──────────────────────────────────────────────────


def test_get_list_returns_paginated_results(client):
    """创建 5 个任务 -> 默认 page=1/page_size=20 -> 返回 5 条。"""
    for i in range(5):
        _seed_task(title=f"任务-{i}")

    response = client.get("/api/discussions")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 5
    assert body["page"] == 1
    assert body["page_size"] == 20


def test_get_list_filters_by_status(client):
    """创建 3 个 created + 2 个 discussing -> ?status=discussing -> 返回 2 条。"""
    for _ in range(3):
        _seed_task(status="created")
    for _ in range(2):
        _seed_task(status="discussing")

    response = client.get("/api/discussions?status=discussing")

    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    for item in body["items"]:
        assert item["status"] == "discussing"


def test_get_list_respects_page_size(client):
    """创建 25 个任务 -> ?page_size=10 -> 返回 10 条。"""
    for i in range(25):
        _seed_task(title=f"任务-{i}")

    response = client.get("/api/discussions?page_size=10")

    body = response.json()
    assert body["total"] == 25
    assert len(body["items"]) == 10


def test_get_list_returns_only_own_tasks(app, client):
    """用户 A 创建 2 个任务 -> 用户 B 调用 -> 返回 0 条。"""
    # 用户 A 创建任务
    _seed_user(user_id="userA", username="alice")
    _seed_task(user_id="userA", title="A 的任务1")
    _seed_task(user_id="userA", title="A 的任务2")
    # 用户 B 请求
    _seed_user(user_id="userB", username="bob")
    app.dependency_overrides[get_current_user] = lambda: _DummyUser(user_id="userB", role="user")
    response = client.get("/api/discussions")

    body = response.json()
    assert body["total"] == 0
    assert len(body["items"]) == 0


def test_get_list_includes_vote_summary(client):
    """列表项应含 vote_summary 聚合各角色最新投票。"""
    task_id = _seed_task(status="discussing")
    _seed_vote(task_id, role="critic", round_num=1, vote="reject")
    _seed_vote(task_id, role="validator", round_num=1, vote="approve")

    response = client.get("/api/discussions")

    body = response.json()
    item = body["items"][0]
    assert item["vote_summary"]["critic"] is not None
    assert item["vote_summary"]["critic"]["vote"] == "reject"
    assert item["vote_summary"]["validator"]["vote"] == "approve"
    assert item["vote_summary"]["approver"] is None


# ── GET /{id} 详情 ──────────────────────────────────────────────


def test_get_detail_returns_full_task(client):
    """创建任务 -> GET /{id} -> 返回完整字段。"""
    task_id = _seed_task()

    response = client.get(f"/api/discussions/{task_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == task_id
    assert body["title"] == "测试任务"
    assert body["description"] == "测试描述"
    assert body["status"] == "created"
    assert body["round"] == 1
    assert body["max_rounds"] == 3
    assert "proposed_action" in body
    assert body["proposed_action"]["type"] == "tool_call"


def test_get_detail_returns_404_for_unknown_id(client):
    """GET 不存在的 id -> 404。"""
    response = client.get("/api/discussions/nonexistent-id")
    assert response.status_code == 404


def test_get_detail_returns_403_for_other_users_task(app, test_orchestrator):
    """任务属于用户 A -> 用户 B 访问 -> 403。"""
    _seed_user(user_id="userA", username="alice")
    task_id = _seed_task(user_id="userA")
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = lambda: _DummyUser(user_id="userB", role="user")
    with TestClient(app) as b_client:
        response = b_client.get(f"/api/discussions/{task_id}")

    assert response.status_code == 403


def test_get_detail_includes_votes_grouped_by_round(client):
    """创建任务 + mock 3 个 vote -> 返回 votes 按 round 分组（列表含全部投票）。"""
    task_id = _seed_task(status="discussing")
    _seed_vote(task_id, role="critic", round_num=1, vote="reject")
    _seed_vote(task_id, role="validator", round_num=1, vote="approve")
    _seed_vote(task_id, role="approver", round_num=1, vote="approve")

    response = client.get(f"/api/discussions/{task_id}")

    body = response.json()
    assert len(body["votes"]) == 3
    roles = {v["role"] for v in body["votes"]}
    assert roles == {"critic", "validator", "approver"}


# ── POST /{id}/revise ───────────────────────────────────────────


def test_post_revise_succeeds_when_in_discussing(client, test_orchestrator):
    """状态 discussing -> revise -> 200，round+1。"""
    task_id = _seed_task(status="discussing", round_num=1, max_rounds=3)

    response = client.post(
        f"/api/discussions/{task_id}/revise",
        json={
            "proposed_action": {"type": "tool_call", "payload": {"tool": "new_tool"}},
            "reason": "根据反馈调整工具",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["round"] == 2


def test_post_revise_succeeds_when_in_pending_approval(client, test_orchestrator):
    """状态 pending_approval -> revise -> 200。"""
    task_id = _seed_task(status="pending_approval", round_num=1, max_rounds=3)

    response = client.post(
        f"/api/discussions/{task_id}/revise",
        json={
            "proposed_action": {"type": "tool_call", "payload": {"tool": "x"}},
            "reason": "修订重试",
        },
    )

    assert response.status_code == 200


def test_post_revise_returns_409_when_in_approved(client):
    """状态 approved -> revise -> 409。"""
    task_id = _seed_task(status="approved", round_num=1, max_rounds=3)

    response = client.post(
        f"/api/discussions/{task_id}/revise",
        json={
            "proposed_action": {"type": "tool_call", "payload": {}},
            "reason": "尝试修订已批准任务",
        },
    )

    assert response.status_code == 409


def test_post_revise_returns_422_when_exceeding_max_rounds(client):
    """round=max_rounds -> revise -> 422。"""
    task_id = _seed_task(status="discussing", round_num=3, max_rounds=3)

    response = client.post(
        f"/api/discussions/{task_id}/revise",
        json={
            "proposed_action": {"type": "tool_call", "payload": {}},
            "reason": "尝试超过轮次上限",
        },
    )

    assert response.status_code == 422


def test_post_revise_returns_404_for_unknown_id(client):
    """不存在 -> revise -> 404。"""
    response = client.post(
        "/api/discussions/nonexistent-id/revise",
        json={
            "proposed_action": {"type": "tool_call", "payload": {}},
            "reason": "测试",
        },
    )
    assert response.status_code == 404


def test_post_revise_returns_422_when_missing_reason(client):
    """缺 reason 字段 -> 422。"""
    task_id = _seed_task(status="discussing", round_num=1, max_rounds=3)

    response = client.post(
        f"/api/discussions/{task_id}/revise",
        json={
            "proposed_action": {"type": "tool_call", "payload": {}},
        },
    )

    assert response.status_code == 422


def test_post_revise_returns_403_for_other_users_task(app, test_orchestrator):
    """任务属于用户 A -> 用户 B 修订 -> 403。"""
    _seed_user(user_id="userA", username="alice")
    task_id = _seed_task(user_id="userA", status="discussing")
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = lambda: _DummyUser(user_id="userB", role="user")
    with TestClient(app) as b_client:
        response = b_client.post(
            f"/api/discussions/{task_id}/revise",
            json={
                "proposed_action": {"type": "tool_call", "payload": {}},
                "reason": "尝试修订他人任务",
            },
        )
    assert response.status_code == 403


# ── GET /{id}/stream SSE ─────────────────────────────────────────


def _patch_sse_user(app, user: _DummyUser):
    """patch _resolve_sse_user 返回指定用户，用于 SSE 鉴权。"""
    return patch.object(discussions_module, "_resolve_sse_user", return_value=user)


async def _mock_stream_events(task_id: str, timeout: float = 300.0):
    """mock 的 SSE 事件生成器，yield 两个事件后终止，避免测试阻塞。"""
    yield {"type": "status_changed", "data": {"task_id": task_id, "status": "discussing"}, "timestamp": 1.0}
    yield {"type": "vote_cast", "data": {"task_id": task_id, "role": "critic", "vote": "approve"}, "timestamp": 2.0}


def test_get_stream_returns_event_stream_content_type(client, test_orchestrator):
    """建立 SSE 连接 -> Content-Type: text/event-stream。"""
    task_id = _seed_task()
    user = _DummyUser(user_id="u1")
    # patch stream 让其快速终止
    test_orchestrator.stream_discussion_events = _mock_stream_events

    with _patch_sse_user(client.app, user):
        response = client.get(f"/api/discussions/{task_id}/stream")

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")


def test_get_stream_returns_401_when_no_cookie(client):
    """无 Cookie 鉴权 -> 401。"""
    task_id = _seed_task()
    # patch _resolve_sse_user 返回 None 模拟无有效 Cookie
    with patch.object(discussions_module, "_resolve_sse_user", return_value=None):
        response = client.get(f"/api/discussions/{task_id}/stream")

    assert response.status_code == 401


def test_get_stream_returns_404_for_unknown_id(client):
    """不存在 -> SSE -> 404。"""
    user = _DummyUser(user_id="u1")
    with _patch_sse_user(client.app, user):
        response = client.get("/api/discussions/nonexistent-id/stream")

    assert response.status_code == 404


def test_get_stream_pushes_events_on_activity(client, test_orchestrator):
    """mock orchestrator 推送事件 -> 客户端收到 SSE data 行。"""
    task_id = _seed_task()
    user = _DummyUser(user_id="u1")
    test_orchestrator.stream_discussion_events = _mock_stream_events

    with _patch_sse_user(client.app, user):
        response = client.get(f"/api/discussions/{task_id}/stream")

    assert response.status_code == 200
    text = response.text
    # SSE 格式应包含 event: 与 data: 行
    assert "event: status_changed" in text
    assert "event: vote_cast" in text
    assert "data:" in text


def test_get_stream_returns_403_for_other_users_task(app, test_orchestrator):
    """任务属于用户 A -> 用户 B 订阅 -> 403。"""
    _seed_user(user_id="userA", username="alice")
    task_id = _seed_task(user_id="userA")
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = lambda: _DummyUser(user_id="userB", role="user")
    user_b = _DummyUser(user_id="userB")
    with _patch_sse_user(app, user_b):
        with TestClient(app) as b_client:
            response = b_client.get(f"/api/discussions/{task_id}/stream")

    assert response.status_code == 403


# ── POST /{id}/force-execute ────────────────────────────────────


def test_post_force_execute_returns_403_for_non_admin(client):
    """普通用户 -> 403。"""
    task_id = _seed_task()

    response = client.post(
        f"/api/discussions/{task_id}/force-execute",
        json={"reason": "测试旁路执行"},
    )

    assert response.status_code == 403


def test_post_force_execute_succeeds_for_admin(admin_client, test_orchestrator):
    """admin 用户 + reason="test" -> 200，响应状态 executing。"""
    # admin_client 已注入 admin 用户，需要先在库中创建 admin 拥有的任务
    task_id = _seed_task(user_id="admin-1", status="pending_approval")

    response = admin_client.post(
        f"/api/discussions/{task_id}/force-execute",
        json={"reason": "紧急旁路执行测试"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "executing"
    assert body["bypassed_by"] == "admin-1"
    # 路由同步部分应将状态置为 approved（execute_approved_action 被 mock 为 no-op 后台任务）
    with _TestingSessionLocal() as db:
        task = db.get(DiscussionTask, task_id)
        assert task.status == "approved"


def test_post_force_execute_fails_closed_when_audit_write_fails(
    admin_client, test_orchestrator, monkeypatch
):
    """审计日志写入失败时 fail-closed：拒绝旁路执行并返回 500，禁止绕过审计放行高危操作。"""
    task_id = _seed_task(user_id="admin-1", status="pending_approval")

    class _FailingAuditLogger:
        """模拟审计写入失败的 AuditLogger。"""

        def __init__(self, db):
            pass

        async def log(self, **kwargs):
            raise RuntimeError("audit write failed")

    # 路由在函数体内 import security.audit.AuditLogger，patch 模块属性即可生效
    monkeypatch.setattr("security.audit.AuditLogger", _FailingAuditLogger)

    response = admin_client.post(
        f"/api/discussions/{task_id}/force-execute",
        json={"reason": "审计失败测试"},
    )

    assert response.status_code == 500
    # 该测试 app 未挂统一错误中间件，FastAPI 默认 detail 结构
    assert "审计" in response.json()["detail"]
    # 任务状态不得被修改：旁路执行被拒绝
    with _TestingSessionLocal() as db:
        task = db.get(DiscussionTask, task_id)
        assert task.status == "pending_approval"


def test_post_force_execute_returns_422_when_missing_reason(admin_client):
    """缺 reason -> 422。"""
    task_id = _seed_task(user_id="admin-1")

    response = admin_client.post(
        f"/api/discussions/{task_id}/force-execute",
        json={},
    )

    assert response.status_code == 422


def test_post_force_execute_returns_404_for_unknown_id(admin_client):
    """不存在 -> force-execute -> 404。"""
    response = admin_client.post(
        "/api/discussions/nonexistent-id/force-execute",
        json={"reason": "测试"},
    )
    assert response.status_code == 404


def test_post_force_execute_returns_403_when_user_not_in_admin_ids(app, test_orchestrator, monkeypatch):
    """普通用户（role 非 admin，且不在 ADMIN_USER_IDS）-> 403。"""
    # 确保环境变量不包含该用户
    monkeypatch.delenv("ADMIN_USER_IDS", raising=False)
    task_id = _seed_task()
    # client fixture 默认注入普通用户（u1, role=user）
    app.dependency_overrides[get_current_user] = lambda: _DummyUser(user_id="u1", role="user")
    with TestClient(app) as normal_client:
        response = normal_client.post(
            f"/api/discussions/{task_id}/force-execute",
            json={"reason": "尝试旁路"},
        )
    assert response.status_code == 403


def test_post_force_execute_allows_admin_via_env_var(app, test_orchestrator, monkeypatch):
    """user.id 在 ADMIN_USER_IDS 环境变量中 -> 允许 force-execute。"""
    monkeypatch.setenv("ADMIN_USER_IDS", "env-admin")
    _seed_user(user_id="env-admin", username="envadmin", role="user")
    task_id = _seed_task(user_id="env-admin", status="pending_approval")
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = lambda: _DummyUser(user_id="env-admin", role="user")
    with TestClient(app) as env_admin_client:
        response = env_admin_client.post(
            f"/api/discussions/{task_id}/force-execute",
            json={"reason": "环境变量管理员旁路"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "executing"

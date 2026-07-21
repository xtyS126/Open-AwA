# -*- coding: utf-8 -*-
"""
ACP API 路由单元测试。

用 mock ACPService 验证 /api/acp/* 端点的契约与安全性。
不依赖 main.py 的 lifespan，通过独立 FastAPI 实例只挂载 acp_router。
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_current_user
from api.routes.acp import (
    OpenCodeStatusResponse,
    _resolve_allowed_workdirs,
    _acp_user_sessions,
    router as acp_router,
)


# ==================== 测试用户与依赖覆盖 ====================


class _DummyUser:
    """测试用 DummyUser，仅暴露 id/username/role 三个字段。"""

    def __init__(self, user_id: str, username: str) -> None:
        self.id = user_id
        self.username = username
        self.role = "user"


_USER_A = _DummyUser("user-a", "alice")
_USER_B = _DummyUser("user-b", "bob")
_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _override_user(user: _DummyUser):
    """生成 get_current_user 的依赖覆盖函数。"""

    def _override() -> _DummyUser:
        return user

    return _override


def _deny_user():
    """模拟未认证：依赖函数抛 401。"""
    from fastapi import HTTPException, status

    def _raise() -> None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    return _raise


# ==================== Mock ACPService ====================


class _FakeConversation:
    """测试用 _Conversation 替身，仅暴露 acp_session_id 与 client.pending_permission。"""

    def __init__(self, acp_session_id: str = "acp-sess-1") -> None:
        self.acp_session_id = acp_session_id
        # client.pending_permission 由测试设置
        self.client = MagicMock()
        self.client.pending_permission = None


class _FakeACPService:
    """测试用 ACPService 替身，所有方法返回预设结果。

    通过 patch acp_host.get_acp_service 返回本类的实例，让路由调用时使用替身。
    """

    def __init__(self) -> None:
        self.run_turn = AsyncMock(return_value={"status": "completed"})
        self.resume_permission = AsyncMock(return_value={"status": "completed"})
        self.close_chat_session = AsyncMock(return_value=None)
        self.cancel_turn = AsyncMock(return_value=True)
        self.get_session = AsyncMock(return_value=None)
        self.get_pending_permission = AsyncMock(return_value=None)
        # 记录 run_turn 调用参数，便于断言
        self.run_turn_calls: List[Dict[str, Any]] = []
        self.cancel_turn_calls: List[Dict[str, Any]] = []
        self.close_chat_session_calls: List[Dict[str, Any]] = []

        # 包装 run_turn/cancel_turn/close_chat_session 以记录调用
        original_run = self.run_turn

        async def _run_turn_recorder(**kwargs: Any) -> Dict[str, Any]:
            self.run_turn_calls.append(kwargs)
            return await original_run(**kwargs)

        self.run_turn = _run_turn_recorder

        original_cancel = self.cancel_turn

        async def _cancel_recorder(**kwargs: Any) -> bool:
            self.cancel_turn_calls.append(kwargs)
            return await original_cancel(**kwargs)

        self.cancel_turn = _cancel_recorder

        original_close = self.close_chat_session

        async def _close_recorder(**kwargs: Any) -> None:
            self.close_chat_session_calls.append(kwargs)
            return await original_close(**kwargs)

        self.close_chat_session = _close_recorder


# ==================== 公共 fixture ====================


@pytest.fixture(autouse=True)
def _reset_acp_sessions() -> Any:
    """每个测试前后清空 _acp_user_sessions 字典，避免测试间状态污染。"""
    _acp_user_sessions.clear()
    yield
    _acp_user_sessions.clear()


@contextmanager
def _test_client(user: Optional[_DummyUser] = None, fake_service: Optional[_FakeACPService] = None):
    """构造测试用 TestClient，注入用户依赖与 mock service。

    Args:
        user: 注入的测试用户；为 None 时模拟未认证（依赖抛 401）。
        fake_service: 替换 acp_host.get_acp_service 返回值的 _FakeACPService 实例。

    Yields:
        TestClient 实例。
    """
    app = FastAPI()
    app.include_router(acp_router)

    if user is not None:
        app.dependency_overrides[get_current_user] = _override_user(user)
    else:
        app.dependency_overrides[get_current_user] = _deny_user()

    # patch acp_host.get_acp_service 让路由使用 fake_service
    patcher = patch("api.routes.acp.get_acp_service", return_value=fake_service)
    patcher.start()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        patcher.stop()
        app.dependency_overrides.clear()


# ==================== 测试用例 ====================


class TestListAgents:
    """GET /api/acp/agents 测试。"""

    def test_returns_four_agents(self) -> None:
        """验证返回 4 个 agent。"""
        with _test_client(user=_USER_A) as client:
            response = client.get("/api/acp/agents")

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 4
        assert len(body["agents"]) == 4

    def test_includes_all_four_expected_agent_ids(self) -> None:
        """验证包含 claude_code/codex/openclaw/opencode 4 个 agent。"""
        with _test_client(user=_USER_A) as client:
            response = client.get("/api/acp/agents")

        assert response.status_code == 200
        agent_ids = {agent["id"] for agent in response.json()["agents"]}
        assert agent_ids == {"claude_code", "codex", "openclaw", "opencode"}


class TestAllowedWorkdirs:
    """ACP 默认工作目录白名单测试。"""

    def test_default_roots_include_project_for_local_node_install(self) -> None:
        """验证未配置时可以在当前 Open-AwA 项目内安装本地 Node.js Agent。"""
        with patch("api.routes.acp.settings.ACP_ALLOWED_WORKDIRS", ""):
            roots = _resolve_allowed_workdirs()

        project_root = Path(__file__).resolve().parents[3]
        assert str((project_root / "var" / "workspace").resolve()) in roots
        assert str(project_root.resolve()) in roots


class TestCreateSession:
    """POST /api/acp/sessions 测试。"""

    def test_create_returns_session_id(self) -> None:
        """验证创建会话返回 session_id 与空 config_options。"""
        body = {"agent": "claude_code", "cwd": str(_BACKEND_ROOT)}
        with _test_client(user=_USER_A) as client:
            response = client.post("/api/acp/sessions", json=body)

        assert response.status_code == 200, response.text
        data = response.json()
        assert "session_id" in data
        assert isinstance(data["session_id"], str)
        assert len(data["session_id"]) > 0
        assert data["config_options"] == []

    def test_create_returns_validated_cwd(self) -> None:
        """验证创建会话会返回后端校验后的工作目录。"""
        body = {"agent": "claude_code", "cwd": str(_BACKEND_ROOT)}
        with _test_client(user=_USER_A) as client:
            response = client.post("/api/acp/sessions", json=body)

        assert response.status_code == 200, response.text
        assert response.json()["cwd"] == str(_BACKEND_ROOT.resolve())

    def test_unknown_agent_returns_404(self) -> None:
        """验证未知 agent 返回 404。"""
        body = {"agent": "nonexistent-agent", "cwd": os.getcwd()}
        with _test_client(user=_USER_A) as client:
            response = client.post("/api/acp/sessions", json=body)

        assert response.status_code == 404, response.text

    def test_cwd_outside_workspace_returns_400(self) -> None:
        """验证 cwd 越权时返回 400。"""
        # /etc 是典型的不允许路径（Windows 上 C:\Windows 也越权）
        body = {"agent": "claude_code", "cwd": "/etc/nonexistent/path"}
        with _test_client(user=_USER_A) as client:
            response = client.post("/api/acp/sessions", json=body)

        assert response.status_code == 400, response.text


class TestListSessions:
    """GET /api/acp/sessions 测试。"""

    def test_lists_current_user_sessions(self) -> None:
        """验证列出当前用户的活动会话。"""
        # 为用户 A 创建一个会话
        _acp_user_sessions[("user-a", "sess-a-1")] = {
            "agent": "claude_code",
            "cwd": os.getcwd(),
            "created_at": "2025-01-01T00:00:00+00:00",
        }
        with _test_client(user=_USER_A) as client:
            response = client.get("/api/acp/sessions")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["sessions"][0]["session_id"] == "sess-a-1"
        assert data["sessions"][0]["agent"] == "claude_code"

    def test_cross_user_isolation(self) -> None:
        """验证用户 A 看不到用户 B 的会话。"""
        # 用户 A 与 B 各创建一个会话
        _acp_user_sessions[("user-a", "sess-a-1")] = {
            "agent": "claude_code",
            "cwd": os.getcwd(),
            "created_at": "2025-01-01T00:00:00+00:00",
        }
        _acp_user_sessions[("user-b", "sess-b-1")] = {
            "agent": "codex",
            "cwd": os.getcwd(),
            "created_at": "2025-01-01T00:00:00+00:00",
        }
        # 用户 A 查询应只看到 sess-a-1
        with _test_client(user=_USER_A) as client:
            response = client.get("/api/acp/sessions")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["sessions"][0]["session_id"] == "sess-a-1"
        assert data["sessions"][0]["agent"] == "claude_code"


class TestPromptSession:
    """POST /api/acp/sessions/{session_id}/prompt 测试。"""

    def test_returns_text_event_stream_content_type(self) -> None:
        """验证 prompt 端点返回 text/event-stream Content-Type。"""
        # 预创建会话
        _acp_user_sessions[("user-a", "sess-a-1")] = {
            "agent": "claude_code",
            "cwd": os.getcwd(),
            "created_at": "2025-01-01T00:00:00+00:00",
        }
        fake_service = _FakeACPService()
        # run_turn 默认返回 {"status": "completed"}
        body = {"prompt": "hello", "restart": False}
        with _test_client(user=_USER_A, fake_service=fake_service) as client:
            response = client.post("/api/acp/sessions/sess-a-1/prompt", json=body)

        assert response.status_code == 200, response.text
        assert "text/event-stream" in response.headers.get("content-type", "")
        # 验证 run_turn 被调用
        assert len(fake_service.run_turn_calls) == 1
        call = fake_service.run_turn_calls[0]
        assert call["chat_id"] == "user-a:sess-a-1"
        assert call["agent"] == "claude_code"
        assert call["restart"] is False

    def test_unknown_session_returns_404(self) -> None:
        """验证未知 session_id 返回 404。"""
        fake_service = _FakeACPService()
        body = {"prompt": "hello"}
        with _test_client(user=_USER_A, fake_service=fake_service) as client:
            response = client.post("/api/acp/sessions/unknown/prompt", json=body)

        assert response.status_code == 404, response.text


class TestRespondPermission:
    """POST /api/acp/sessions/{session_id}/permission 测试。"""

    def test_returns_status(self) -> None:
        """验证响应权限请求返回 status 字段。"""
        # 预创建会话
        _acp_user_sessions[("user-a", "sess-a-1")] = {
            "agent": "claude_code",
            "cwd": os.getcwd(),
            "created_at": "2025-01-01T00:00:00+00:00",
        }
        fake_service = _FakeACPService()
        # get_session 返回 _Conversation 替身（含 acp_session_id）
        fake_service.get_session = AsyncMock(return_value=_FakeConversation(acp_session_id="acp-sess-1"))
        # get_pending_permission 返回非 None 表示存在挂起的权限
        fake_service.get_pending_permission = AsyncMock(return_value={"agent": "claude_code"})
        # resume_permission 返回 completed
        fake_service.resume_permission = AsyncMock(return_value={"status": "completed"})

        body = {"option_id": "allow_once"}
        with _test_client(user=_USER_A, fake_service=fake_service) as client:
            response = client.post("/api/acp/sessions/sess-a-1/permission", json=body)

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "completed"

    def test_no_pending_permission_returns_400(self) -> None:
        """验证无挂起权限请求时返回 400。"""
        _acp_user_sessions[("user-a", "sess-a-1")] = {
            "agent": "claude_code",
            "cwd": os.getcwd(),
            "created_at": "2025-01-01T00:00:00+00:00",
        }
        fake_service = _FakeACPService()
        # get_session 返回会话但 pending_permission 为 None
        fake_service.get_session = AsyncMock(return_value=_FakeConversation(acp_session_id="acp-sess-1"))
        fake_service.get_pending_permission = AsyncMock(return_value=None)

        body = {"option_id": "allow_once"}
        with _test_client(user=_USER_A, fake_service=fake_service) as client:
            response = client.post("/api/acp/sessions/sess-a-1/permission", json=body)

        assert response.status_code == 400, response.text


class TestCancelSession:
    """POST /api/acp/sessions/{session_id}/cancel 测试。"""

    def test_returns_cancelled(self) -> None:
        """验证取消端点返回 cancelled 字段。"""
        _acp_user_sessions[("user-a", "sess-a-1")] = {
            "agent": "claude_code",
            "cwd": os.getcwd(),
            "created_at": "2025-01-01T00:00:00+00:00",
        }
        fake_service = _FakeACPService()
        # cancel_turn 默认返回 True
        with _test_client(user=_USER_A, fake_service=fake_service) as client:
            response = client.post("/api/acp/sessions/sess-a-1/cancel")

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["cancelled"] is True
        # 验证 cancel_turn 用对了 chat_id/agent
        assert len(fake_service.cancel_turn_calls) == 1
        call = fake_service.cancel_turn_calls[0]
        assert call["chat_id"] == "user-a:sess-a-1"
        assert call["agent"] == "claude_code"


class TestCloseSession:
    """DELETE /api/acp/sessions/{session_id} 测试。"""

    def test_returns_closed(self) -> None:
        """验证关闭端点返回 closed 字段并清理会话元数据。"""
        _acp_user_sessions[("user-a", "sess-a-1")] = {
            "agent": "claude_code",
            "cwd": os.getcwd(),
            "created_at": "2025-01-01T00:00:00+00:00",
        }
        fake_service = _FakeACPService()
        with _test_client(user=_USER_A, fake_service=fake_service) as client:
            response = client.delete("/api/acp/sessions/sess-a-1")

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["closed"] is True
        # 验证 _acp_user_sessions 中对应条目已被移除
        assert ("user-a", "sess-a-1") not in _acp_user_sessions
        # 验证 close_chat_session 被调用
        assert len(fake_service.close_chat_session_calls) == 1
        call = fake_service.close_chat_session_calls[0]
        assert call["chat_id"] == "user-a:sess-a-1"
        assert call["agent"] == "claude_code"


class TestOpenCodeInstall:
    """OpenCode 项目内安装接口测试。"""

    def test_rejects_install_without_explicit_confirmation(self, tmp_path: Path) -> None:
        """验证安装接口必须携带显式确认标记。"""
        with patch("api.routes.acp._ALLOWED_WORKSPACE_ROOTS", [str(tmp_path)]):
            with _test_client(user=_USER_A) as client:
                response = client.post(
                    "/api/acp/opencode/install",
                    json={"cwd": str(tmp_path), "confirm_install": False},
                )

        assert response.status_code == 400
        assert "明确确认" in response.json()["detail"]

    def test_rejects_directory_without_package_json(self, tmp_path: Path) -> None:
        """验证安装目标必须是白名单内的 Node.js 项目。"""
        with patch("api.routes.acp._ALLOWED_WORKSPACE_ROOTS", [str(tmp_path)]):
            with _test_client(user=_USER_A) as client:
                response = client.post(
                    "/api/acp/opencode/install",
                    json={"cwd": str(tmp_path), "confirm_install": True},
                )

        assert response.status_code == 400
        assert "package.json" in response.json()["detail"]

    def test_installs_fixed_package_and_runs_audit(self, tmp_path: Path) -> None:
        """验证接口不接收任意命令，只安装固定包并执行审计。"""
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        status_result = OpenCodeStatusResponse(
            cwd=str(tmp_path),
            package_json_exists=True,
            project_installed=True,
            available=True,
            command=str(tmp_path / "node_modules" / ".bin" / "opencode.cmd"),
        )
        with patch("api.routes.acp._ALLOWED_WORKSPACE_ROOTS", [str(tmp_path)]), \
             patch(
                 "api.routes.acp._run_npm_command",
                 new=AsyncMock(side_effect=[(0, "installed"), (0, "audit ok")]),
             ) as run_npm, \
             patch(
                 "api.routes.acp._get_opencode_status",
                 new=AsyncMock(return_value=status_result),
             ):
            with _test_client(user=_USER_A) as client:
                response = client.post(
                    "/api/acp/opencode/install",
                    json={"cwd": str(tmp_path), "confirm_install": True},
                )

        assert response.status_code == 200, response.text
        assert response.json()["installed"] is True
        assert run_npm.await_args_list[0].args[1] == [
            "install", "--save-dev", "opencode-ai@latest", "--no-audit", "--no-fund",
        ]
        assert run_npm.await_args_list[1].args[1] == [
            "audit", "--audit-level=high", "--json",
        ]


class TestAuthentication:
    """认证测试：未认证访问应返回 401。"""

    def test_unauthenticated_agents_returns_401(self) -> None:
        """验证未认证访问 GET /agents 返回 401。"""
        with _test_client(user=None) as client:
            response = client.get("/api/acp/agents")

        assert response.status_code == 401, response.text

    def test_unauthenticated_create_session_returns_401(self) -> None:
        """验证未认证访问 POST /sessions 返回 401。"""
        body = {"agent": "claude_code", "cwd": os.getcwd()}
        with _test_client(user=None) as client:
            response = client.post("/api/acp/sessions", json=body)

        assert response.status_code == 401, response.text

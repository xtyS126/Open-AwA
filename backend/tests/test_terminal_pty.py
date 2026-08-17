"""
PTY 持久化终端会话单元测试。

覆盖：
- PTYTerminalSession 实例化
- WebSocket 连接（mock PTYSession）
- 输入消息处理
- resize 消息处理
- 输出消息推送
- 连接时推送 scrollback + snapshot
- 断线重连后屏幕恢复
- 命令黑名单拦截 `rm -rf /`
- snapshot 端点返回网格
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.routes.terminal as terminal_route
import core.terminal.pty_session as pty_session_module
from api.dependencies import get_current_user, get_db
from api.routes.terminal import (
    MAX_PTY_SESSIONS,
    PTYTerminalSession,
    TerminalSession,
    _is_command_safe,
    _pty_sessions,
)
from core.terminal.pty_session import PTYSession as CorePTYSession


app = FastAPI()
app.include_router(terminal_route.router, prefix="/api")


class TestTerminalSessionTimeoutCleanup:
    """普通终端命令超时后的进程清理测试。"""

    @pytest.mark.asyncio
    async def test_execute_timeout_does_not_wait_forever_after_kill(self, monkeypatch) -> None:
        """子进程被 kill 后仍不退出时应在限定等待后返回超时结果。"""
        class FakeProcess:
            def __init__(self) -> None:
                self.killed = False

            async def communicate(self):
                await asyncio.Event().wait()

            async def wait(self):
                await asyncio.Event().wait()

            def kill(self) -> None:
                self.killed = True

        process = FakeProcess()

        async def fake_create_subprocess_exec(*_args, **_kwargs):
            return process

        async def fake_wait_for(awaitable, timeout):
            awaitable.close()
            raise asyncio.TimeoutError()

        monkeypatch.setattr(terminal_route.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
        monkeypatch.setattr(terminal_route.asyncio, "wait_for", fake_wait_for)

        session = TerminalSession("timeout-test", cwd=".")
        result = await session.execute("echo hello", timeout=1)

        assert result["ok"] is False
        assert "超时" in result["error"]
        assert process.killed is True


# ----------------------------------------------------------------------
# Mock 工具
# ----------------------------------------------------------------------

class FakePTY:
    """
    PTYSession 的 mock 实现，避免在测试中启动真实 PTY 子进程。
    通过直接驱动 pyte.Stream.feed 来模拟 PTY 输出。

    终端序列解析逻辑与 PTYSession 保持一致（pyte.HistoryScreen + pyte.Stream），
    但跳过真实 PTY 子进程管理，仅用于测试 PTYTerminalSession 的 WebSocket 协议层。
    """

    def __init__(
        self,
        command: List[str],
        cwd: str,
        cols: int = 80,
        rows: int = 24,
        on_output: Optional[Any] = None,
        output_filter: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        self.command: List[str] = list(command)
        self.cwd: str = cwd
        self.cols: int = cols
        self.rows: int = rows
        self._on_output = on_output
        self._output_filter = output_filter
        self._closed: bool = False
        self._started: bool = False
        # 复用 pyte.HistoryScreen + pyte.Stream 模拟 PTY 输出解析
        # 与 PTYSession 的终端逻辑保持镜像，便于 feed_output 驱动屏幕状态
        import pyte
        self.vt_screen = pyte.HistoryScreen(columns=cols, lines=rows, history=1000)
        self._stream = pyte.Stream(self.vt_screen)
        self.written_data: List[str] = []

    async def start(self) -> None:
        self._started = True

    async def write(self, data: str) -> None:
        self.written_data.append(data)

    async def resize(self, cols: int, rows: int) -> None:
        self.cols = cols
        self.rows = rows
        # pyte Screen.resize 第一个参数是 lines，第二个是 columns
        self.vt_screen.resize(lines=rows, columns=cols)

    def get_snapshot(self) -> List[List[str]]:
        return [list(line) for line in self.vt_screen.display]

    def get_scrollback(self, limit: int = 100) -> List[str]:
        if limit <= 0:
            return []
        history_top = self.vt_screen.history.top
        total = len(history_top)
        start = max(0, total - limit)
        columns = self.vt_screen.columns
        result: List[str] = []
        for i in range(start, total):
            line = history_top[i]
            result.append("".join(line[c].data for c in range(columns)))
        return result

    def is_alive(self) -> bool:
        return not self._closed

    async def close(self) -> None:
        self._closed = True

    def feed_output(self, data: str) -> None:
        """测试辅助：模拟 PTY 子进程输出数据。"""
        if self._output_filter is not None:
            data = self._output_filter(data)
        self._stream.feed(data)
        if self._on_output is not None:
            self._on_output(data)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _override_pty(monkeypatch):
    """覆盖 PTYSession 为 FakePTY，并清理会话表。"""
    monkeypatch.setattr(terminal_route, "PTYSession", FakePTY)
    _pty_sessions.clear()
    yield
    _pty_sessions.clear()


@pytest.fixture(autouse=True)
def _override_auth(monkeypatch):
    """覆盖认证、WebSocket 用户加载与 Origin 校验，避免访问真实数据库。"""
    fake_user = SimpleNamespace(id="user-1", username="tester", role="user")

    class FakeProjectService:
        def __init__(self, db, path_policy):
            self.db = db
            self.path_policy = path_policy

        def resolve_project_root(self, *, user_id, user_role, project_id):
            return Path(".")

    class FakeRegistry:
        async def acquire(self, **kwargs):
            result = kwargs["verify_project"]()
            if inspect.isawaitable(result):
                await result

        async def release(self, **kwargs):
            return None

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return fake_user

    class FakeSession:
        def query(self, *args, **kwargs):
            return FakeQuery()

        def close(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    # WS 鉴权已统一走 api.security.ws_auth.resolve_ws_user_from_token（API Key + JWT 双路径），
    # 注意：terminal.py 是绑定导入（from ... import ...），必须 patch 模块内绑定名
    # 才能覆盖实际调用点（patch ws_auth 模块属性对绑定导入不生效）
    monkeypatch.setattr(
        terminal_route,
        "resolve_ws_user_from_token",
        lambda token: fake_user,
    )
    monkeypatch.setattr(terminal_route, "SessionLocal", lambda: FakeSession())
    # 测试环境跳过 Origin 校验（Origin 检查由独立的 Origin 校验测试覆盖）
    # 终端路由已改为从 api.security.ws_auth 导入 validate_ws_origin，patch 模块内的引用即可生效
    monkeypatch.setattr(terminal_route, "validate_ws_origin", lambda origin: True)
    monkeypatch.setattr(terminal_route, "WorkbenchProjectService", FakeProjectService)

    # 覆盖 HTTP 依赖（WebSocket 用自己的鉴权）
    def _override_user():
        return fake_user

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[terminal_route.get_terminal_workbench_path_policy] = lambda: object()
    app.dependency_overrides[terminal_route.get_terminal_runtime_registry] = FakeRegistry
    yield
    app.dependency_overrides.clear()


# ----------------------------------------------------------------------
# 测试：PTYTerminalSession 实例化
# ----------------------------------------------------------------------

class TestPTYTerminalSessionInstantiation:
    """PTYTerminalSession 类基础测试。"""

    def test_instantiate_with_default_command(self) -> None:
        """不指定 command 时使用平台默认命令。"""
        session = PTYTerminalSession(
            session_id="test-1",
            cwd=".",
            cols=80,
            rows=24,
        )
        assert session.session_id == "test-1"
        assert session.active is True
        # 应至少有一个 command
        assert len(session.command) >= 1
        assert session.pty is not None
        assert session.pty.cols == 80
        assert session.pty.rows == 24

    @pytest.mark.asyncio
    async def test_core_pty_filters_output_before_vt_screen(self, monkeypatch) -> None:
        """底层 PTY 必须在 VT 解析前过滤输出，不能只净化回调消息。"""
        project_root = str(Path(".").resolve())
        callback_output: list[str] = []
        chunks = iter([f"{project_root}\r\n".encode("utf-8"), b""])
        session = CorePTYSession(
            command=["fake-shell"],
            cwd=project_root,
            cols=120,
            rows=4,
            on_output=callback_output.append,
            output_filter=lambda text: text.replace(project_root, "."),
        )

        async def _fake_read_once(_loop) -> bytes:
            return next(chunks)

        monkeypatch.setattr(session, "_read_once", _fake_read_once)
        await session._reader_loop()

        snapshot_text = "\n".join("".join(row) for row in session.get_snapshot())
        assert project_root not in snapshot_text
        assert all(project_root not in item for item in callback_output)

    @pytest.mark.parametrize(
        ("is_windows", "expected_pid"),
        [(False, 4100), (True, 4200)],
    )
    def test_core_pty_returns_platform_root_process_pid(
        self,
        monkeypatch,
        is_windows: bool,
        expected_pid: int,
    ) -> None:
        """POSIX asyncio process 与 Windows pywinpty 都应暴露真实根 PID。"""
        session = CorePTYSession(command=["fake-shell"], cwd=".")
        session.process = SimpleNamespace(pid=4100)
        session._winpty_proc = SimpleNamespace(pid=4200)
        monkeypatch.setattr(pty_session_module, "_is_windows", is_windows)

        assert session.get_root_pid() == expected_pid

    def test_instantiate_with_custom_command(self) -> None:
        """指定 command 时使用自定义命令。"""
        session = PTYTerminalSession(
            session_id="test-2",
            cwd=".",
            command=["/bin/zsh"],
            cols=120,
            rows=40,
        )
        assert session.command == ["/bin/zsh"]
        assert session.pty.cols == 120
        assert session.pty.rows == 40

    def test_pty_output_redactor_handles_bound_root_split_across_chunks(self) -> None:
        """绑定根跨两个 PTY 读取块时也不能在屏幕或广播中重组。"""
        project_root = str(Path(".").resolve())
        split_at = max(1, len(project_root) // 2)
        session = PTYTerminalSession(
            session_id="split-root-output",
            cwd=project_root,
            command=["fake-shell"],
            cols=120,
            rows=4,
        )
        subscriber = session.subscribe()

        session.pty.feed_output(project_root[:split_at])
        session.pty.feed_output(project_root[split_at:])

        snapshot_text = "\n".join(
            "".join(row) for row in session.get_snapshot()["grid"]
        )
        broadcast_text = "".join(
            subscriber.get_nowait()["data"]
            for _ in range(subscriber.qsize())
        )
        assert project_root not in snapshot_text
        assert project_root not in broadcast_text

    def test_subscribe_returns_queue(self) -> None:
        """subscribe 应返回 asyncio.Queue。"""
        session = PTYTerminalSession(session_id="test-3", cwd=".")
        q = session.subscribe()
        assert isinstance(q, asyncio.Queue)
        assert q in session._subscribers

    def test_unsubscribe_removes_queue(self) -> None:
        """unsubscribe 应从订阅者列表移除队列。"""
        session = PTYTerminalSession(session_id="test-4", cwd=".")
        q = session.subscribe()
        session.unsubscribe(q)
        assert q not in session._subscribers


# ----------------------------------------------------------------------
# 测试：WebSocket 协议
# ----------------------------------------------------------------------

class TestPTYWebSocketProtocol:
    """PTY WebSocket 协议测试。"""

    def test_websocket_connect_pushes_initial_messages(self) -> None:
        """连接时应依次推送 shell_info、scrollback、snapshot。"""
        # 预先创建一个 PTY 会话（设置 owner_user_id 以通过 IDOR 校验）
        session = PTYTerminalSession(
            session_id="ws-test-1",
            cwd=".",
            command=["/bin/bash"],
            cols=80,
            rows=24,
            owner_user_id="user-1",
            project_id="project-1",
        )
        asyncio.run(session.start())
        _pty_sessions["ws-test-1"] = session

        with TestClient(app) as client:
            with client.websocket_connect(
                "/api/terminal/ws/pty/ws-test-1",
                subprotocols=["bearer.fake-token"],
            ) as websocket:
                # 第一条消息：shell_info
                shell_info = websocket.receive_json()
                assert shell_info["type"] == "shell_info"
                assert shell_info["shell"] == "/bin/bash"

                # 第二条消息：scrollback
                scrollback_msg = websocket.receive_json()
                assert scrollback_msg["type"] == "scrollback"
                assert isinstance(scrollback_msg["lines"], list)

                # 第三条消息：snapshot
                snapshot_msg = websocket.receive_json()
                assert snapshot_msg["type"] == "snapshot"
                assert isinstance(snapshot_msg["grid"], list)
                assert snapshot_msg["cols"] == 80
                assert snapshot_msg["rows"] == 24

    def test_websocket_input_message_forwarded_to_pty(self) -> None:
        """input 消息应被转发到 PTY.stdin。"""
        session = PTYTerminalSession(
            session_id="ws-test-2",
            cwd=".",
            command=["/bin/bash"],
            owner_user_id="user-1",
            project_id="project-1",
        )
        asyncio.run(session.start())
        _pty_sessions["ws-test-2"] = session

        with TestClient(app) as client:
            with client.websocket_connect(
                "/api/terminal/ws/pty/ws-test-2",
                subprotocols=["bearer.fake-token"],
            ) as websocket:
                # 消费前三条初始消息
                for _ in range(3):
                    websocket.receive_json()

                websocket.send_json({"type": "input", "data": "echo hello\n"})

                # 给后台任务一点时间处理
                import time
                time.sleep(0.1)

        # PTY 应收到该输入
        assert any("echo hello" in d for d in session.pty.written_data)

    def test_websocket_resize_message_handled(self) -> None:
        """resize 消息应触发 PTY.resize 并回送 resize_ack。"""
        session = PTYTerminalSession(
            session_id="ws-test-3",
            cwd=".",
            command=["/bin/bash"],
            cols=80,
            rows=24,
            owner_user_id="user-1",
            project_id="project-1",
        )
        asyncio.run(session.start())
        _pty_sessions["ws-test-3"] = session

        with TestClient(app) as client:
            with client.websocket_connect(
                "/api/terminal/ws/pty/ws-test-3",
                subprotocols=["bearer.fake-token"],
            ) as websocket:
                # 消费前三条初始消息
                for _ in range(3):
                    websocket.receive_json()

                websocket.send_json({"type": "resize", "cols": 100, "rows": 30})

                # 读取响应消息，应包含 resize_ack
                ack_received = False
                for _ in range(10):
                    msg = websocket.receive_json()
                    if msg.get("type") == "resize_ack":
                        assert msg["cols"] == 100
                        assert msg["rows"] == 30
                        ack_received = True
                        break
                assert ack_received, "未收到 resize_ack"

        # PTY 尺寸应被更新
        assert session.pty.cols == 100
        assert session.pty.rows == 30

    def test_websocket_output_pushed_to_client(self) -> None:
        """PTY 输出应通过 output 消息推送给客户端。"""
        session = PTYTerminalSession(
            session_id="ws-test-4",
            cwd=".",
            command=["/bin/bash"],
            owner_user_id="user-1",
            project_id="project-1",
        )
        asyncio.run(session.start())
        _pty_sessions["ws-test-4"] = session

        with TestClient(app) as client:
            with client.websocket_connect(
                "/api/terminal/ws/pty/ws-test-4",
                subprotocols=["bearer.fake-token"],
            ) as websocket:
                # 消费前三条初始消息
                for _ in range(3):
                    websocket.receive_json()

                # 模拟 PTY 输出
                session.pty.feed_output("hello world\n")

                # 应收到 output 消息
                output_received = False
                for _ in range(10):
                    msg = websocket.receive_json()
                    if msg.get("type") == "output" and "hello world" in msg.get("data", ""):
                        output_received = True
                        break
                assert output_received, "未收到 output 消息"

    def test_websocket_command_blocked_rm_rf(self) -> None:
        """首次 stdin 中包含 rm -rf / 应被拦截并回送 command_blocked。"""
        session = PTYTerminalSession(
            session_id="ws-test-5",
            cwd=".",
            command=["/bin/bash"],
            owner_user_id="user-1",
            project_id="project-1",
        )
        asyncio.run(session.start())
        _pty_sessions["ws-test-5"] = session

        with TestClient(app) as client:
            with client.websocket_connect(
                "/api/terminal/ws/pty/ws-test-5",
                subprotocols=["bearer.fake-token"],
            ) as websocket:
                # 消费前三条初始消息
                for _ in range(3):
                    websocket.receive_json()

                # 发送危险命令
                websocket.send_json({"type": "input", "data": "rm -rf /\n"})

                blocked_received = False
                for _ in range(10):
                    msg = websocket.receive_json()
                    if msg.get("type") == "command_blocked":
                        assert "rm" in msg.get("command", "")
                        blocked_received = True
                        break
                assert blocked_received, "未收到 command_blocked 消息"

        # PTY 不应收到任何写入
        assert session.pty.written_data == []

    def test_websocket_redacts_bound_root_from_all_pty_projections(self, monkeypatch) -> None:
        """PTY 的 shell、输出、历史、快照和拦截事件都不得投影绑定项目绝对根。"""
        project_root = Path(".").resolve()
        root_text = str(project_root)

        class AbsoluteProjectService:
            def __init__(self, db, path_policy) -> None:
                pass

            def resolve_project_root(self, *, user_id, user_role, project_id):
                return project_root

        monkeypatch.setattr(terminal_route, "WorkbenchProjectService", AbsoluteProjectService)
        session = PTYTerminalSession(
            session_id="ws-redacted-root",
            cwd=root_text,
            command=[str(project_root / "bin" / "fake-shell")],
            cols=120,
            rows=2,
            owner_user_id="user-1",
            project_id="project-1",
        )
        asyncio.run(session.start())
        session.pty.feed_output(f"{root_text}\nline-1\nline-2\n{root_text}")
        _pty_sessions[session.session_id] = session

        with TestClient(app) as client:
            with client.websocket_connect(
                f"/api/terminal/ws/pty/{session.session_id}",
                subprotocols=["bearer.fake-token"],
            ) as websocket:
                shell_info = websocket.receive_json()
                scrollback = websocket.receive_json()
                snapshot = websocket.receive_json()
                assert root_text not in shell_info["shell"]
                assert root_text not in "\n".join(scrollback["lines"])
                snapshot_text = "\n".join(
                    "".join(row) for row in snapshot["grid"]
                )
                assert root_text not in snapshot_text

                session.pty.feed_output(f"output={root_text}\\src\n")
                output = websocket.receive_json()
                assert output["type"] == "output"
                assert root_text not in output["data"]

                websocket.send_json({
                    "type": "input",
                    "data": f"rm -rf / {root_text}\\src\n",
                })
                blocked = websocket.receive_json()
                assert blocked["type"] == "command_blocked"
                assert root_text not in blocked["command"]
                assert root_text not in blocked["message"]


# ----------------------------------------------------------------------
# 测试：断线重连
# ----------------------------------------------------------------------

class TestPTYReconnect:
    """PTY 断线重连测试。"""

    def test_reconnect_restores_screen_state(self) -> None:
        """断线重连后应推送当前屏幕快照与 scrollback。"""
        session = PTYTerminalSession(
            session_id="reconnect-1",
            cwd=".",
            command=["/bin/bash"],
            cols=80,
            rows=24,
            owner_user_id="user-1",
            project_id="project-1",
        )
        asyncio.run(session.start())
        # 在没有 WebSocket 客户端时模拟 PTY 输出
        session.pty.feed_output("Hello PTY\n")
        # 触发一次滚动，让 scrollback 非空
        for i in range(30):
            session.pty.feed_output(f"line {i}\n")
        _pty_sessions["reconnect-1"] = session

        # 第一次连接
        with TestClient(app) as client:
            with client.websocket_connect(
                "/api/terminal/ws/pty/reconnect-1",
                subprotocols=["bearer.fake-token"],
            ) as websocket:
                # 消费初始消息
                shell_info = websocket.receive_json()
                assert shell_info["type"] == "shell_info"
                scrollback_msg = websocket.receive_json()
                assert scrollback_msg["type"] == "scrollback"
                snapshot_msg = websocket.receive_json()
                assert snapshot_msg["type"] == "snapshot"

                # 推送一些输出
                session.pty.feed_output("ongoing output\n")
                output_received = False
                for _ in range(10):
                    msg = websocket.receive_json()
                    if msg.get("type") == "output":
                        output_received = True
                        break
                assert output_received

            # WebSocket 断开后 PTY 会话应保留
            assert "reconnect-1" in _pty_sessions
            assert session.active is True

        # 第二次连接（断线重连）
        with TestClient(app) as client:
            with client.websocket_connect(
                "/api/terminal/ws/pty/reconnect-1",
                subprotocols=["bearer.fake-token"],
            ) as websocket:
                shell_info = websocket.receive_json()
                assert shell_info["type"] == "shell_info"

                scrollback_msg = websocket.receive_json()
                assert scrollback_msg["type"] == "scrollback"
                # scrollback 应包含之前推送过的行
                scrollback_text = "\n".join(scrollback_msg["lines"])
                assert "Hello PTY" in scrollback_text or "line" in scrollback_text

                snapshot_msg = websocket.receive_json()
                assert snapshot_msg["type"] == "snapshot"
                assert isinstance(snapshot_msg["grid"], list)


# ----------------------------------------------------------------------
# 测试：snapshot 端点
# ----------------------------------------------------------------------

class TestPTYSnapshotEndpoint:
    """PTY snapshot 端点测试。"""

    def test_snapshot_endpoint_returns_grid(self) -> None:
        """GET /sessions/{id}/snapshot 应返回当前屏幕网格。"""
        session = PTYTerminalSession(
            session_id="snap-1",
            cwd=".",
            command=["/bin/bash"],
            cols=10,
            rows=3,
            owner_user_id="user-1",
            project_id="project-1",
        )
        asyncio.run(session.start())
        # 写入一些内容到屏幕
        session.pty.feed_output("hello")
        _pty_sessions["snap-1"] = session

        with TestClient(app) as client:
            response = client.get("/api/terminal/sessions/snap-1/snapshot")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert isinstance(data["grid"], list)
        assert data["cols"] == 10
        assert data["rows"] == 3
        # 第一行前 5 个字符应为 hello
        assert "".join(data["grid"][0][:5]) == "hello"

    def test_snapshot_endpoint_pty_path(self) -> None:
        """GET /sessions/pty/{id}/snapshot 应返回相同结构。"""
        session = PTYTerminalSession(
            session_id="snap-2",
            cwd=".",
            command=["/bin/bash"],
            cols=20,
            rows=4,
            owner_user_id="user-1",
            project_id="project-1",
        )
        asyncio.run(session.start())
        _pty_sessions["snap-2"] = session

        with TestClient(app) as client:
            response = client.get("/api/terminal/sessions/pty/snap-2/snapshot")

        assert response.status_code == 200
        data = response.json()
        assert data["cols"] == 20
        assert data["rows"] == 4

    def test_snapshot_endpoint_404_for_missing_session(self) -> None:
        """不存在的 session_id 应返回 404。"""
        with TestClient(app) as client:
            response = client.get("/api/terminal/sessions/nonexistent/snapshot")

        assert response.status_code == 404


# ----------------------------------------------------------------------
# 测试：会话创建/列表/关闭
# ----------------------------------------------------------------------

class TestPTYSessionManagement:
    """PTY 会话管理端点测试。"""

    def test_create_pty_session_endpoint(self) -> None:
        """POST /sessions/pty 应创建 PTY 会话。"""
        with TestClient(app) as client:
            response = client.post(
                "/api/terminal/sessions/pty",
                json={"project_id": "project-1", "cols": 80, "rows": 24, "command": ["/bin/bash"]},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "session_id" in data
        assert data["shell"] == "/bin/bash"
        assert data["cols"] == 80
        assert data["rows"] == 24

        # 清理
        _pty_sessions.pop(data["session_id"], None)

    def test_list_pty_sessions_endpoint(self) -> None:
        """GET /sessions/pty 应列出活跃会话。"""
        session = PTYTerminalSession(
            session_id="list-1",
            cwd=".",
            command=["/bin/bash"],
            owner_user_id="user-1",
            project_id="project-1",
        )
        asyncio.run(session.start())
        _pty_sessions["list-1"] = session

        with TestClient(app) as client:
            response = client.get("/api/terminal/sessions/pty")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        session_ids = [s["session_id"] for s in data["sessions"]]
        assert "list-1" in session_ids

    def test_close_pty_session_endpoint(self) -> None:
        """DELETE /sessions/pty/{id} 应关闭会话。"""
        session = PTYTerminalSession(
            session_id="close-1",
            cwd=".",
            command=["/bin/bash"],
            owner_user_id="user-1",
            project_id="project-1",
        )
        asyncio.run(session.start())
        _pty_sessions["close-1"] = session

        with TestClient(app) as client:
            response = client.delete("/api/terminal/sessions/pty/close-1")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "close-1" not in _pty_sessions

    def test_max_pty_sessions_enforced(self) -> None:
        """配额已满且无可淘汰空闲会话时，应拒绝创建。"""
        # 预填满会话（设置 owner_user_id="user-1" 以计入当前用户配额）
        # 全部模拟活跃 WS 连接（subscribe），确保没有空闲会话可淘汰
        for i in range(MAX_PTY_SESSIONS):
            session = PTYTerminalSession(
                session_id=f"max-{i}",
                cwd=".",
                command=["/bin/bash"],
                owner_user_id="user-1",
                project_id="project-1",
            )
            asyncio.run(session.start())
            session.subscribe()
            _pty_sessions[f"max-{i}"] = session

        try:
            with TestClient(app) as client:
                response = client.post(
                    "/api/terminal/sessions/pty",
                    json={"project_id": "project-1", "cols": 80, "rows": 24, "command": ["/bin/bash"]},
                )
            data = response.json()
            assert data["ok"] is False
            assert "最大" in data["error"]
        finally:
            _pty_sessions.clear()

    def test_max_pty_sessions_evicts_idle(self) -> None:
        """配额已满时优先淘汰无活跃 WS 连接的空闲会话，新会话创建成功。"""
        # 预填满会话：前 4 个有订阅者（活跃连接），最后 1 个无订阅者（孤儿）
        for i in range(MAX_PTY_SESSIONS):
            session = PTYTerminalSession(
                session_id=f"idle-{i}",
                cwd=".",
                command=["/bin/bash"],
                owner_user_id="user-1",
                project_id="project-1",
            )
            asyncio.run(session.start())
            if i < MAX_PTY_SESSIONS - 1:
                # 模拟活跃 WS 连接：订阅一个输出队列
                session.subscribe()
            _pty_sessions[f"idle-{i}"] = session

        try:
            with TestClient(app) as client:
                response = client.post(
                    "/api/terminal/sessions/pty",
                    json={"project_id": "project-1", "cols": 80, "rows": 24, "command": ["/bin/bash"]},
                )
            data = response.json()
            # 空闲会话被淘汰 → 创建成功；被淘汰的是无订阅者的最后一个
            assert data["ok"] is True
            assert "idle-4" not in _pty_sessions
            assert "idle-0" in _pty_sessions
        finally:
            _pty_sessions.clear()


# ----------------------------------------------------------------------
# 测试：命令黑名单
# ----------------------------------------------------------------------

class TestCommandBlacklist:
    """PTY 模式命令黑名单测试。"""

    def test_write_input_blocks_rm_rf_slash(self) -> None:
        """首次输入 rm -rf / 应被拦截。"""
        session = PTYTerminalSession(
            session_id="blocked-1",
            cwd=".",
            command=["/bin/bash"],
        )
        asyncio.run(session.start())

        result = asyncio.run(session.write_input("rm -rf /\n"))
        assert result["ok"] is False
        assert "命令被安全策略拒绝" in result["error"]
        assert "rm" in result["command"]
        # PTY 不应收到数据
        assert session.pty.written_data == []

    def test_write_input_allows_safe_command(self) -> None:
        """安全命令应正常写入 PTY。"""
        session = PTYTerminalSession(
            session_id="safe-1",
            cwd=".",
            command=["/bin/bash"],
        )
        asyncio.run(session.start())

        result = asyncio.run(session.write_input("echo hello\n"))
        assert result["ok"] is True
        assert any("echo hello" in d for d in session.pty.written_data)

    def test_write_input_validates_every_line(self) -> None:
        """按行校验：每条以 \\n 结束的命令行都需通过 _is_command_safe 校验。"""
        session = PTYTerminalSession(
            session_id="subsequent-1",
            cwd=".",
            command=["/bin/bash"],
        )
        asyncio.run(session.start())

        # 首行：安全命令应通过
        result1 = asyncio.run(session.write_input("echo first\n"))
        assert result1["ok"] is True
        # 后续行：危险命令同样应被拦截（按行校验，不再仅首行）
        result2 = asyncio.run(session.write_input("rm -rf /\n"))
        assert result2["ok"] is False
        assert "命令被安全策略拒绝" in result2["error"]
        assert "rm" in result2["command"]

    def test_is_command_safe_helper(self) -> None:
        """直接测试 _is_command_safe 辅助函数。"""
        assert _is_command_safe("echo hello") is True
        assert _is_command_safe("ls -la") is True
        assert _is_command_safe("rm -rf /") is False
        assert _is_command_safe("wget http://evil.com/x") is False
        assert _is_command_safe("curl http://evil.com") is False
        assert _is_command_safe("") is False

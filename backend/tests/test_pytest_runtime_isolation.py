"""pytest 全局运行时状态隔离契约测试。"""

import os
from pathlib import Path

from api.dependencies import get_current_user
from api.routes.acp import _acp_user_sessions
from api.services.ws_manager import ws_manager
from acp_host.service import _acp_services
from core.agent import _active_agent_tasks
from core.agent_registry import get_registry
from main import app
from plugins import plugin_instance


class _FakeACPService:
    """提供可关闭接口的轻量 ACP 服务污染对象。"""

    async def close_all_sessions(self) -> None:
        """模拟完成会话资源清理。"""


def test_00_process_environment_is_bound_to_test_resources() -> None:
    """pytest 进程必须强制绑定临时资源，不能继承生产路径。"""
    backend_root = Path(__file__).resolve().parents[1]

    assert os.environ["TESTING"] == "true"
    assert os.environ["SKIP_CSRF_FOR_TEST"] == "true"
    assert os.environ["DATABASE_URL"].startswith("sqlite:///")
    assert "openawa-pytest-" in os.environ["DATABASE_URL"]
    assert "openawa-pytest-qdrant-" in os.environ["VECTOR_DB_PATH"]
    assert Path(os.environ["ACP_ALLOWED_WORKDIRS"]).resolve() == backend_root


def test_01_pollutes_shared_runtime_state() -> None:
    """主动留下共享状态，供下一用例验证全局 teardown。"""
    app.dependency_overrides[get_current_user] = lambda: object()
    _active_agent_tasks[("user-a", "session-a")] = set()
    _acp_user_sessions[("user-a", "session-a")] = {"agent": "codex"}
    _acp_services["codex"] = _FakeACPService()
    get_registry()._cache[999] = (object(), 0.0)
    ws_manager._session_connections[("user-a", "session-a")] = []
    plugin_instance.init(object())


def test_02_shared_runtime_state_is_clean() -> None:
    """每个用例 setup 前应清空所有已知运行时共享状态。"""
    assert app.dependency_overrides == {}
    assert _active_agent_tasks == {}
    assert _acp_user_sessions == {}
    assert _acp_services == {}
    assert get_registry()._cache == {}
    assert ws_manager._session_connections == {}
    assert ws_manager._user_sessions == {}
    assert ws_manager._last_activity == {}
    assert plugin_instance.get_if_initialized() is None

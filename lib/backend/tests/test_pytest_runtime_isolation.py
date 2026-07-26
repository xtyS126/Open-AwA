"""pytest 全局运行时状态隔离契约测试。"""

import os
from pathlib import Path

from api.dependencies import get_current_user
from api.routes.acp import _acp_user_sessions
from api.services.ws_manager import ws_manager
from acp_host.service import _acp_services
from core.agent_task_registry import _active_agent_tasks
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
    assert "openawa-pytest-logs-" in os.environ["LOG_DIR"]
    assert Path(os.environ["ACP_ALLOWED_WORKDIRS"]).resolve() == backend_root


def test_pollutes_shared_runtime_state() -> None:
    """主动留下共享状态，供下一用例验证全局 teardown。"""
    app.dependency_overrides[get_current_user] = lambda: object()
    _active_agent_tasks[("user-a", "session-a")] = set()
    _acp_user_sessions[("user-a", "session-a")] = {"agent": "codex"}
    _acp_services["codex"] = _FakeACPService()
    get_registry()._cache[999] = (object(), 0.0)
    ws_manager._session_connections[("user-a", "session-a")] = []
    plugin_instance.init(object())
    # 显式断言副作用已生效（消除"无断言用例"反模式）
    assert get_current_user in app.dependency_overrides
    assert ("user-a", "session-a") in _active_agent_tasks
    assert ("user-a", "session-a") in _acp_user_sessions
    assert "codex" in _acp_services
    assert 999 in get_registry()._cache
    assert ("user-a", "session-a") in ws_manager._session_connections


def test_shared_runtime_state_is_clean_at_setup() -> None:
    """每个用例 setup 前应清空所有已知运行时共享状态。

    本用例不依赖 test_pollutes_shared_runtime_state 先执行——用例开始时
    所有共享状态应已为空（由 conftest fixture 的全局 teardown 保证）。
    若 conftest 未清理，本用例会因前序用例残留而失败。
    """
    # 用例开始时所有共享状态应已为空（由 conftest fixture 保证）
    assert app.dependency_overrides == {}
    assert _active_agent_tasks == {}
    assert _acp_user_sessions == {}
    assert _acp_services == {}
    assert get_registry()._cache == {}
    assert ws_manager._session_connections == {}
    assert ws_manager._user_sessions == {}
    assert ws_manager._last_activity == {}
    assert plugin_instance.get_if_initialized() is None

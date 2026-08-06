"""关键稳定性路径回归测试。"""

import asyncio
import json
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import main
from api.services.chat_protocol import build_sse_response


@pytest.mark.asyncio
async def test_sse_cancellation_propagates_without_done_frame() -> None:
    """SSE 客户端断开时必须继续向上游传播取消信号。"""

    async def cancelled_stream():
        raise asyncio.CancelledError()
        yield {}

    response = await build_sse_response(cancelled_stream())

    with pytest.raises(asyncio.CancelledError):
        await anext(response.body_iterator)


@pytest.mark.asyncio
async def test_optional_startup_failure_keeps_service_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """可选组件初始化失败不能阻止基础服务进入可用状态。"""

    async def succeed(*_args, **_kwargs) -> None:
        return None

    async def fail(*_args, **_kwargs) -> None:
        raise RuntimeError("插件系统不可用")

    registry = MagicMock()
    monkeypatch.setattr(main, "get_registry", lambda: registry)
    monkeypatch.setattr(main, "_startup_infrastructure", succeed)
    monkeypatch.setattr(main, "_startup_data_init", succeed)
    monkeypatch.setattr(main, "_startup_owner_user_init", succeed)
    monkeypatch.setattr(main, "prewarm_agent_memory", succeed)
    monkeypatch.setattr(main, "_startup_plugin_system", fail)
    monkeypatch.setattr(main, "_startup_background_tasks", succeed)
    monkeypatch.setattr(main.task_runtime, "initialize", succeed)
    monkeypatch.setattr(main, "_startup_autonomous_mode", succeed)
    monkeypatch.setattr(main, "_startup_acp_service", succeed)
    monkeypatch.setattr(main, "_startup_mcp_sse_origin", lambda _profiler: None)
    monkeypatch.setattr(main, "_startup_mcp_preheat", succeed)
    monkeypatch.setattr(main, "_shutdown_plugin_system", succeed)
    monkeypatch.setattr(main, "_shutdown_autonomous_mode", succeed)
    monkeypatch.setattr(main, "_shutdown_acp_service", succeed)
    monkeypatch.setattr(main.task_runtime, "shutdown", succeed)
    monkeypatch.setattr(main.scheduled_task_manager, "stop", succeed)
    monkeypatch.setattr(main, "close_shared_client", succeed)

    lifespan = main.lifespan(main.app)
    await anext(lifespan)
    try:
        assert main.app.state.startup_failures == {"plugin_system": "RuntimeError"}
    finally:
        with pytest.raises(StopAsyncIteration):
            await anext(lifespan)


@pytest.mark.asyncio
async def test_lifespan_prewarms_memory_runtime_before_serving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """应用进入可用状态前必须完成共享向量运行时预热。"""

    async def succeed(*_args, **_kwargs) -> None:
        return None

    prewarm_calls = []

    async def record_prewarm(session_factory) -> None:
        prewarm_calls.append(session_factory)

    registry = MagicMock()
    monkeypatch.setattr(main, "get_registry", lambda: registry)
    monkeypatch.setattr(main, "_startup_infrastructure", succeed)
    monkeypatch.setattr(main, "_startup_data_init", succeed)
    monkeypatch.setattr(main, "_startup_owner_user_init", succeed)
    monkeypatch.setattr(main, "_startup_plugin_system", succeed)
    monkeypatch.setattr(main, "_startup_background_tasks", succeed)
    monkeypatch.setattr(main.task_runtime, "initialize", succeed)
    monkeypatch.setattr(main, "_startup_autonomous_mode", succeed)
    monkeypatch.setattr(main, "_startup_acp_service", succeed)
    monkeypatch.setattr(main, "_startup_mcp_sse_origin", lambda _profiler: None)
    monkeypatch.setattr(main, "_startup_mcp_preheat", succeed)
    monkeypatch.setattr(main, "prewarm_agent_memory", record_prewarm, raising=False)
    monkeypatch.setattr(main, "_shutdown_plugin_system", succeed)
    monkeypatch.setattr(main, "_shutdown_autonomous_mode", succeed)
    monkeypatch.setattr(main, "_shutdown_acp_service", succeed)
    monkeypatch.setattr(main.task_runtime, "shutdown", succeed)
    monkeypatch.setattr(main.scheduled_task_manager, "stop", succeed)
    monkeypatch.setattr(main, "close_shared_client", succeed)

    lifespan = main.lifespan(main.app)
    await anext(lifespan)
    try:
        assert prewarm_calls == [main.SessionLocal]
    finally:
        with pytest.raises(StopAsyncIteration):
            await anext(lifespan)


def test_litellm_uses_local_cost_map_by_default() -> None:
    """离线启动默认不得请求远程 LiteLLM 价格表。"""

    child_env = os.environ.copy()
    child_env.pop("LITELLM_LOCAL_MODEL_COST_MAP", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os; import core.litellm_adapter; "
                "print(os.environ.get('LITELLM_LOCAL_MODEL_COST_MAP', ''))"
            ),
        ],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=child_env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )

    assert result.stdout.strip().endswith("True")


@pytest.mark.asyncio
async def test_timeout_response_is_classified_without_internal_detail() -> None:
    """超时响应必须具备可重试的语义且不泄露内部异常内容。"""

    request = SimpleNamespace(
        state=SimpleNamespace(request_id="test-request"),
        method="GET",
        url=SimpleNamespace(path="/api/test"),
    )

    response = await main.unhandled_exception_handler(
        request, asyncio.TimeoutError("内部超时细节")
    )
    payload = json.loads(response.body)

    assert response.status_code == 504
    assert payload["error"]["code"] == "request_timeout"
    assert payload["error"]["retryable"] is True
    assert "内部超时细节" not in response.body.decode("utf-8")

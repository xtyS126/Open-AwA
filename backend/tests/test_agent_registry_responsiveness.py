"""Agent 注册表事件循环响应性回归测试。"""

import asyncio
import importlib
import sys
import time
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

@pytest.mark.asyncio
async def test_agent_memory_warmup_keeps_event_loop_responsive(
    monkeypatch,
) -> None:
    """共享向量运行时冷启动较慢时不得冻结服务事件循环。"""

    module_path = Path(__file__).resolve().parents[1] / "core" / "agent_runtime_warmup.py"
    assert module_path.is_file(), "缺少异步 Agent 运行时预热适配器"

    warmup_module = importlib.import_module("core.agent_runtime_warmup")

    class SlowMemoryManager:
        def __init__(self, session_factory) -> None:
            time.sleep(0.05)

    monkeypatch.setattr(warmup_module, "MemoryManager", SlowMemoryManager)
    heartbeat_completed = asyncio.Event()

    async def heartbeat() -> None:
        await asyncio.sleep(0.01)
        heartbeat_completed.set()

    heartbeat_task = asyncio.create_task(heartbeat())
    await warmup_module.prewarm_agent_memory(lambda: None)

    await heartbeat_task
    assert heartbeat_completed.is_set() is True

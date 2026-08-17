# -*- coding: utf-8 -*-
"""_get_owner_from_settings_async 异步包装测试。

验证 spec fix-performance-remaining-issues 模块 B 的 TTFB 优化点：
- 异步包装函数应返回同步函数的结果
- 同步函数返回 None 时异步包装也返回 None
- 通过 asyncio.to_thread 在线程池执行，不阻塞事件循环
- 同步函数抛异常时异常正常传播（不静默吞）
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import (  # noqa: E402
    _get_owner_from_settings,
    _get_owner_from_settings_async,
)


@pytest.mark.asyncio
async def test_get_owner_from_settings_async_returns_user():
    """异步包装函数应返回同步函数的结果。"""
    mock_user = MagicMock()
    mock_user.id = 1
    mock_user.username = "admin"

    with patch("api.dependencies._get_owner_from_settings", return_value=mock_user):
        result = await _get_owner_from_settings_async()

    assert result is mock_user
    assert result.id == 1
    assert result.username == "admin"


@pytest.mark.asyncio
async def test_get_owner_from_settings_async_returns_none_when_no_owner():
    """同步函数返回 None 时，异步包装也应返回 None。"""
    with patch("api.dependencies._get_owner_from_settings", return_value=None):
        result = await _get_owner_from_settings_async()

    assert result is None


@pytest.mark.asyncio
async def test_get_owner_from_settings_async_runs_in_thread_pool():
    """异步包装函数应通过 asyncio.to_thread 在线程池执行，不阻塞事件循环。

    通过在 to_thread 调用期间检查当前事件循环是否空闲来验证：
    若同步函数在线程池中执行，主事件循环线程与执行线程不应是同一个。
    """
    executed_thread_ids: list[int] = []

    def _capture_thread() -> Optional[object]:
        # 记录同步函数实际执行所在的线程 ID
        import threading

        executed_thread_ids.append(threading.get_ident())
        return None

    main_thread_id_before = _get_main_thread_id()

    with patch("api.dependencies._get_owner_from_settings", side_effect=_capture_thread):
        await _get_owner_from_settings_async()

    assert len(executed_thread_ids) == 1
    # 同步函数应在非主事件循环线程中执行（asyncio.to_thread 默认使用线程池）
    assert executed_thread_ids[0] != main_thread_id_before


def _get_main_thread_id() -> int:
    """获取主线程 ID，用于断言线程池执行是否发生。"""
    import threading

    return threading.main_thread().ident or 0


@pytest.mark.asyncio
async def test_get_owner_from_settings_async_propagates_exceptions():
    """同步函数抛异常时，异步包装应传播异常（不静默吞）。

    注意：_get_owner_from_settings 内部已 try/except 包裹并返回 None，
    此用例 mock 直接替换同步函数绕过内部 try/except，验证包装层不吞异常。
    """
    expected_error = RuntimeError("DB connection failed")
    with patch(
        "api.dependencies._get_owner_from_settings", side_effect=expected_error
    ):
        with pytest.raises(RuntimeError, match="DB connection failed"):
            await _get_owner_from_settings_async()


@pytest.mark.asyncio
async def test_get_owner_from_settings_async_is_coroutine():
    """异步包装函数应是协程函数，可直接 await。"""
    import inspect

    assert inspect.iscoroutinefunction(_get_owner_from_settings_async)


@pytest.mark.asyncio
async def test_get_owner_from_settings_async_does_not_call_sync_directly_in_event_loop():
    """验证包装函数不会在事件循环线程中直接调用同步函数。

    通过追踪 _get_owner_from_settings 是否在主事件循环线程中同步执行：
    若 asyncio.to_thread 正确生效，同步函数应在工作线程中执行。
    """
    import threading

    call_thread_ids: list[int] = []

    def _record_thread() -> None:
        call_thread_ids.append(threading.get_ident())
        return None

    main_thread_id = threading.main_thread().ident or 0

    with patch("api.dependencies._get_owner_from_settings", side_effect=_record_thread):
        await _get_owner_from_settings_async()

    assert len(call_thread_ids) == 1
    # 关键断言：同步函数不在主线程执行，证明确实放到了线程池
    assert call_thread_ids[0] != main_thread_id


def test_get_owner_from_settings_sync_function_unchanged():
    """约束验证：同步函数 _get_owner_from_settings 本身未被修改，仍可调用。

    spec 要求：不修改 _get_owner_from_settings 同步函数本身（仅包装）。
    此用例确认同步函数仍以原签名存在。
    """
    import inspect

    # 同步函数不应是协程函数
    assert not inspect.iscoroutinefunction(_get_owner_from_settings)
    # 函数名保持不变
    assert _get_owner_from_settings.__name__ == "_get_owner_from_settings"

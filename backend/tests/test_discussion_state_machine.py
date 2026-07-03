"""讨论任务状态机单元测试。

测试目标：
  覆盖 core/discussion/state_machine.py 的 validate_transition() 与 is_terminal() 两个纯函数。
  - validate_transition(current, target)：校验状态转换合法性，返回 bool
  - is_terminal(status)：判断是否为终态（completed/failed）

测试策略：
  - 合法转换：assert validate_transition(...) is True
  - 非法转换：assert validate_transition(...) is False
    [NOTE] validate_transition 本身返回 bool 不抛异常；
    orchestrator 在调用方依据返回值手动抛 DiscussionStateError。
    此处断言 False 以覆盖非法转换分支，对应"错误条件"测试命名。
  - 终态判断：assert is_terminal(...) == 预期布尔值

测试隔离：
  纯函数测试，无外部依赖，无需 fixture。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 将 backend 目录加入 sys.path，确保可导入 core.discussion 模块
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from core.discussion.definitions import DiscussionError, DiscussionStateError  # noqa: E402
from core.discussion.state_machine import (  # noqa: E402
    VALID_TRANSITIONS,
    is_terminal,
    validate_transition,
)


# ── 合法转换测试 ──────────────────────────────────────────────────


def test_validate_transition_created_to_discussing():
    """created -> discussing 为合法首轮讨论转换。"""
    assert validate_transition("created", "discussing") is True


def test_validate_transition_discussing_to_pending_approval():
    """discussing -> pending_approval 为合法投票汇总转换。"""
    assert validate_transition("discussing", "pending_approval") is True


def test_validate_transition_pending_approval_to_approved():
    """pending_approval -> approved 为合法一致通过转换。"""
    assert validate_transition("pending_approval", "approved") is True


def test_validate_transition_pending_approval_to_rejected():
    """pending_approval -> rejected 为合法驳回转换。"""
    assert validate_transition("pending_approval", "rejected") is True


def test_validate_transition_approved_to_executing():
    """approved -> executing 为合法执行启动转换。"""
    assert validate_transition("approved", "executing") is True


def test_validate_transition_executing_to_completed():
    """executing -> completed 为合法执行成功终态转换。"""
    assert validate_transition("executing", "completed") is True


def test_validate_transition_executing_to_failed():
    """executing -> failed 为合法执行失败终态转换。"""
    assert validate_transition("executing", "failed") is True


def test_validate_transition_rejected_to_discussing():
    """rejected -> discussing 为合法修订重试转换（状态机支持）。"""
    assert validate_transition("rejected", "discussing") is True


def test_validate_transition_pending_approval_to_discussing():
    """pending_approval -> discussing 为合法重新讨论转换。"""
    assert validate_transition("pending_approval", "discussing") is True


def test_validate_transition_approved_to_completed():
    """approved -> completed 为合法空操作直接完成转换。"""
    assert validate_transition("approved", "completed") is True


# ── 非法转换测试 ──────────────────────────────────────────────────
# validate_transition 返回 False 表示非法转换；orchestrator 依据 False 抛 DiscussionStateError


def test_validate_transition_created_to_approved_raises():
    """created -> approved 跳过讨论与审批，为非法转换，返回 False。

    [NOTE] validate_transition 返回 False 而非抛异常；
    orchestrator 调用方依据该返回值抛 DiscussionStateError。
    """
    assert validate_transition("created", "approved") is False


def test_validate_transition_created_to_executing_raises():
    """created -> executing 跳过讨论与批准，为非法转换，返回 False。"""
    assert validate_transition("created", "executing") is False


def test_validate_transition_completed_to_anything_raises():
    """completed 为终态，不可再转换，返回 False。"""
    assert validate_transition("completed", "discussing") is False


def test_validate_transition_failed_to_anything_raises():
    """failed 为终态，不可再转换，返回 False。"""
    assert validate_transition("failed", "discussing") is False


def test_validate_transition_discussing_to_approved_raises():
    """discussing -> approved 跳过 pending_approval，为非法转换，返回 False。"""
    assert validate_transition("discussing", "approved") is False


def test_validate_transition_executing_to_approved_raises():
    """executing -> approved 回退状态，为非法转换，返回 False。"""
    assert validate_transition("executing", "approved") is False


# ── 终态测试 ──────────────────────────────────────────────────────


def test_is_terminal_completed_returns_true():
    """completed 为终态，is_terminal 返回 True。"""
    assert is_terminal("completed") is True


def test_is_terminal_failed_returns_true():
    """failed 为终态，is_terminal 返回 True。"""
    assert is_terminal("failed") is True


def test_is_terminal_created_returns_false():
    """created 为初始态，is_terminal 返回 False。"""
    assert is_terminal("created") is False


def test_is_terminal_discussing_returns_false():
    """discussing 为进行态，is_terminal 返回 False。"""
    assert is_terminal("discussing") is False


def test_is_terminal_pending_approval_returns_false():
    """pending_approval 为等待态，is_terminal 返回 False。"""
    assert is_terminal("pending_approval") is False


def test_is_terminal_approved_returns_false():
    """approved 为已批准态，is_terminal 返回 False。"""
    assert is_terminal("approved") is False


def test_is_terminal_rejected_returns_false():
    """rejected 可经修订回到 discussing，非终态，is_terminal 返回 False。"""
    assert is_terminal("rejected") is False


# ── 异常层级与转换表完整性测试 ──────────────────────────────────────


def test_discussion_state_error_is_subclass_of_discussion_error():
    """DiscussionStateError 应继承 DiscussionError，保证异常族可被统一捕获。"""
    assert issubclass(DiscussionStateError, DiscussionError)


def test_valid_transitions_covers_all_statuses():
    """VALID_TRANSITIONS 应覆盖全部 8 个状态键，避免遗漏导致 KeyError。"""
    expected_statuses = {
        "created",
        "discussing",
        "pending_approval",
        "approved",
        "rejected",
        "executing",
        "completed",
        "failed",
    }
    assert set(VALID_TRANSITIONS.keys()) == expected_statuses


def test_validate_transition_unknown_current_returns_false():
    """未知当前状态应返回 False（不抛 KeyError），保证健壮性。"""
    assert validate_transition("unknown_status", "discussing") is False


def test_validate_transition_unknown_target_returns_false():
    """未知目标状态应返回 False，保证健壮性。"""
    assert validate_transition("created", "unknown_status") is False

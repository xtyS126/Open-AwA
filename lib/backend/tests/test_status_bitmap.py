"""下载状态位图与失败重试单元测试。

覆盖 ``status.py`` 的：
- :class:`SubTask` 枚举：5 个子任务的索引值（Cover=0 / Video=1 / Nfo=2 /
  Danmaku=3 / Subtitle=4）
- :class:`SubTaskState` 枚举：4 态（Skipped=0 / Succeeded=1 / Ignored=2 /
  Failed=3）
- :func:`get_subtask_status`：从 status 整数读取指定子任务的状态
- :func:`set_subtask_status`：写入状态，返回新值（不可变）
- :func:`all_succeeded`：判断所有子任务是否均为 Succeeded
- :func:`has_failed`：判断是否有任一子任务为 Failed
- :func:`should_retry`：判断是否需要重试（has_failed + retry_count < max_retry）
- :func:`summary`：返回所有子任务状态字典
- 模块常量 :data:`MAX_RETRY` / :data:`INITIAL_STATUS`

位图布局：每子任务 2 bit，bit_offset = subtask.value * 2，5 子任务共 10 bit。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 注入 backend 目录到 sys.path，便于直接 import 被测模块
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from plugins.bilibili_toolkit_builtin.status import (  # noqa: E402
    INITIAL_STATUS,
    MAX_RETRY,
    SubTask,
    SubTaskState,
    all_succeeded,
    get_subtask_status,
    has_failed,
    set_subtask_status,
    should_retry,
    summary,
)


# ---------------------------------------------------------------------------
# SubTask 枚举值测试
# ---------------------------------------------------------------------------


def test_subtask_cover_value_zero():
    """SubTask.Cover 值应为 0。"""
    assert SubTask.Cover == 0
    assert int(SubTask.Cover) == 0


def test_subtask_video_value_one():
    """SubTask.Video 值应为 1。"""
    assert SubTask.Video == 1
    assert int(SubTask.Video) == 1


def test_subtask_nfo_value_two():
    """SubTask.Nfo 值应为 2。"""
    assert SubTask.Nfo == 2
    assert int(SubTask.Nfo) == 2


def test_subtask_danmaku_value_three():
    """SubTask.Danmaku 值应为 3。"""
    assert SubTask.Danmaku == 3
    assert int(SubTask.Danmaku) == 3


def test_subtask_subtitle_value_four():
    """SubTask.Subtitle 值应为 4。"""
    assert SubTask.Subtitle == 4
    assert int(SubTask.Subtitle) == 4


def test_subtask_has_five_members():
    """SubTask 应恰好包含 5 个成员。"""
    assert len(list(SubTask)) == 5


def test_subtask_member_order():
    """枚举顺序应为 Cover / Video / Nfo / Danmaku / Subtitle。"""
    expected = [SubTask.Cover, SubTask.Video, SubTask.Nfo, SubTask.Danmaku, SubTask.Subtitle]
    assert list(SubTask) == expected


# ---------------------------------------------------------------------------
# SubTaskState 枚举值测试
# ---------------------------------------------------------------------------


def test_subtask_state_skipped_zero():
    """SubTaskState.Skipped 值应为 0。"""
    assert SubTaskState.Skipped == 0
    assert int(SubTaskState.Skipped) == 0


def test_subtask_state_succeeded_one():
    """SubTaskState.Succeeded 值应为 1。"""
    assert SubTaskState.Succeeded == 1
    assert int(SubTaskState.Succeeded) == 1


def test_subtask_state_ignored_two():
    """SubTaskState.Ignored 值应为 2。"""
    assert SubTaskState.Ignored == 2
    assert int(SubTaskState.Ignored) == 2


def test_subtask_state_failed_three():
    """SubTaskState.Failed 值应为 3。"""
    assert SubTaskState.Failed == 3
    assert int(SubTaskState.Failed) == 3


def test_subtask_state_has_four_members():
    """SubTaskState 应恰好包含 4 个成员。"""
    assert len(list(SubTaskState)) == 4


def test_subtask_state_values_fit_two_bits():
    """4 个状态值应在 0-3 范围内（2 bit 表示）。"""
    for state in SubTaskState:
        assert 0 <= int(state) <= 3


# ---------------------------------------------------------------------------
# 模块常量测试
# ---------------------------------------------------------------------------


def test_max_retry_is_three():
    """MAX_RETRY 应为 3。"""
    assert MAX_RETRY == 3


def test_initial_status_is_zero():
    """INITIAL_STATUS 应为 0。"""
    assert INITIAL_STATUS == 0


# ---------------------------------------------------------------------------
# get_subtask_status 测试
# ---------------------------------------------------------------------------


def test_get_subtask_status_initial_all_skipped():
    """status=0 时所有子任务应为 Skipped。"""
    for subtask in SubTask:
        assert get_subtask_status(0, subtask) == SubTaskState.Skipped


def test_get_subtask_status_cover_succeeded():
    """status=0b01 时 Cover 应为 Succeeded。"""
    # 0b01: Cover=Succeeded(0b01), 其他=Skipped(0b00)
    status = 0b0000000001  # bit 0-1 = 01
    assert get_subtask_status(status, SubTask.Cover) == SubTaskState.Succeeded


def test_get_subtask_status_video_failed():
    """status=0b1100 时 Video 应为 Failed。"""
    # 0b1100: Video=Failed(0b11 << 2), 其他=Skipped
    status = 0b0000001100
    assert get_subtask_status(status, SubTask.Video) == SubTaskState.Failed


def test_get_subtask_status_nfo_ignored():
    """status=0b100000 时 Nfo 应为 Ignored。"""
    # 0b100000: Nfo=Ignored(0b10 << 4)
    status = 0b0000100000
    assert get_subtask_status(status, SubTask.Nfo) == SubTaskState.Ignored


def test_get_subtask_status_danmaku_succeeded():
    """status 中 Danmaku 位为 Succeeded。"""
    # 0b01000000: Danmaku=Succeeded(0b01 << 6)
    status = 0b01000000
    assert get_subtask_status(status, SubTask.Danmaku) == SubTaskState.Succeeded


def test_get_subtask_status_subtitle_failed():
    """status 中 Subtitle 位为 Failed。"""
    # 0b1100000000: Subtitle=Failed(0b11 << 8)
    status = 0b1100000000
    assert get_subtask_status(status, SubTask.Subtitle) == SubTaskState.Failed


def test_get_subtask_status_returns_subtaskstate_enum():
    """返回值应为 SubTaskState 枚举实例。"""
    result = get_subtask_status(0, SubTask.Cover)
    assert isinstance(result, SubTaskState)


def test_get_subtask_status_all_states_round_trip():
    """对 Cover 设置全部 4 种状态后读取应一致。"""
    for state in SubTaskState:
        status = set_subtask_status(0, SubTask.Cover, state)
        assert get_subtask_status(status, SubTask.Cover) == state


def test_get_subtask_status_does_not_modify_input():
    """get_subtask_status 不应修改入参 status（int 不可变，但确保返回值正确）。"""
    status = 0b1101
    _ = get_subtask_status(status, SubTask.Cover)
    _ = get_subtask_status(status, SubTask.Video)
    assert status == 0b1101


# ---------------------------------------------------------------------------
# set_subtask_status 测试
# ---------------------------------------------------------------------------


def test_set_subtask_status_cover_succeeded():
    """写入 Cover=Succeeded 应得到 status=1。"""
    result = set_subtask_status(0, SubTask.Cover, SubTaskState.Succeeded)
    assert result == 1


def test_set_subtask_status_video_failed():
    """写入 Video=Failed 应得到 status=0b1100=12。"""
    result = set_subtask_status(0, SubTask.Video, SubTaskState.Failed)
    assert result == 0b1100
    assert result == 12


def test_set_subtask_status_returns_new_value():
    """set_subtask_status 应返回新值，不修改入参。"""
    original = 0
    result = set_subtask_status(original, SubTask.Cover, SubTaskState.Succeeded)
    assert original == 0
    assert result == 1


def test_set_subtask_status_chained_writes():
    """先 Cover=Succeeded 再 Video=Failed 应得到 status=13。"""
    s = set_subtask_status(0, SubTask.Cover, SubTaskState.Succeeded)
    s = set_subtask_status(s, SubTask.Video, SubTaskState.Failed)
    # Cover=0b01, Video=0b1100 << 2 = 0b1100, 合计 0b1101 = 13
    assert s == 0b1101
    assert s == 13


def test_set_subtask_status_overwrite():
    """覆盖写入应清空旧状态。"""
    # 先 Video=Failed(0b1100)
    s = set_subtask_status(0, SubTask.Video, SubTaskState.Failed)
    assert s == 0b1100
    # 再 Video=Succeeded(0b0100)，应覆盖为 4
    s = set_subtask_status(s, SubTask.Video, SubTaskState.Succeeded)
    assert s == 0b0100
    assert s == 4


def test_set_subtask_status_overwrite_clears_high_bits():
    """覆盖写入时高位状态应被清零。"""
    # Video=Failed(0b11) 写入到 bit 2-3
    s = set_subtask_status(0, SubTask.Video, SubTaskState.Failed)
    assert s == 0b1100
    # Video=Skipped(0b00) 覆盖
    s = set_subtask_status(s, SubTask.Video, SubTaskState.Skipped)
    assert s == 0


def test_set_subtask_status_all_succeeded():
    """所有子任务设为 Succeeded 应得到固定值。"""
    # 每 2 bit = 01, 5 子任务共 10 bit = 0b0101010101
    expected = 0b0101010101
    s = 0
    for subtask in SubTask:
        s = set_subtask_status(s, subtask, SubTaskState.Succeeded)
    assert s == expected


def test_set_subtask_status_all_failed():
    """所有子任务设为 Failed 应得到固定值。"""
    # 每 2 bit = 11, 5 子任务共 10 bit = 0b1111111111
    expected = 0b1111111111
    s = 0
    for subtask in SubTask:
        s = set_subtask_status(s, subtask, SubTaskState.Failed)
    assert s == expected


def test_set_subtask_status_does_not_affect_other_subtasks():
    """写入一个子任务不应影响其他子任务状态。"""
    # 先把所有子任务设为 Succeeded
    s = 0
    for subtask in SubTask:
        s = set_subtask_status(s, subtask, SubTaskState.Succeeded)
    # 把 Video 设为 Failed
    s = set_subtask_status(s, SubTask.Video, SubTaskState.Failed)
    # 其他子任务仍应为 Succeeded
    assert get_subtask_status(s, SubTask.Cover) == SubTaskState.Succeeded
    assert get_subtask_status(s, SubTask.Video) == SubTaskState.Failed
    assert get_subtask_status(s, SubTask.Nfo) == SubTaskState.Succeeded
    assert get_subtask_status(s, SubTask.Danmaku) == SubTaskState.Succeeded
    assert get_subtask_status(s, SubTask.Subtitle) == SubTaskState.Succeeded


def test_set_subtask_status_returns_int():
    """返回值应为 int 类型。"""
    result = set_subtask_status(0, SubTask.Cover, SubTaskState.Succeeded)
    assert isinstance(result, int)


# ---------------------------------------------------------------------------
# all_succeeded 测试
# ---------------------------------------------------------------------------


def test_all_succeeded_zero_status():
    """status=0 时（全 Skipped）应返回 False。"""
    assert all_succeeded(0) is False


def test_all_succeeded_all_set():
    """所有子任务为 Succeeded 时应返回 True。"""
    s = 0
    for subtask in SubTask:
        s = set_subtask_status(s, subtask, SubTaskState.Succeeded)
    assert all_succeeded(s) is True


def test_all_succeeded_one_missing():
    """任一子任务非 Succeeded 时应返回 False。"""
    s = 0
    for subtask in SubTask:
        s = set_subtask_status(s, subtask, SubTaskState.Succeeded)
    # 把 Video 改为 Skipped
    s = set_subtask_status(s, SubTask.Video, SubTaskState.Skipped)
    assert all_succeeded(s) is False


def test_all_succeeded_one_failed():
    """任一子任务 Failed 时应返回 False。"""
    s = 0
    for subtask in SubTask:
        s = set_subtask_status(s, subtask, SubTaskState.Succeeded)
    s = set_subtask_status(s, SubTask.Subtitle, SubTaskState.Failed)
    assert all_succeeded(s) is False


def test_all_succeeded_one_ignored():
    """任一子任务 Ignored 时应返回 False。"""
    s = 0
    for subtask in SubTask:
        s = set_subtask_status(s, subtask, SubTaskState.Succeeded)
    s = set_subtask_status(s, SubTask.Danmaku, SubTaskState.Ignored)
    assert all_succeeded(s) is False


def test_all_succeeded_returns_bool():
    """返回值应为 bool 类型。"""
    assert isinstance(all_succeeded(0), bool)


# ---------------------------------------------------------------------------
# has_failed 测试
# ---------------------------------------------------------------------------


def test_has_failed_zero_status():
    """status=0 时（全 Skipped）应返回 False。"""
    assert has_failed(0) is False


def test_has_failed_one_failed():
    """任一子任务 Failed 时应返回 True。"""
    s = set_subtask_status(0, SubTask.Video, SubTaskState.Failed)
    assert has_failed(s) is True


def test_has_failed_all_succeeded():
    """所有子任务 Succeeded 时应返回 False。"""
    s = 0
    for subtask in SubTask:
        s = set_subtask_status(s, subtask, SubTaskState.Succeeded)
    assert has_failed(s) is False


def test_has_failed_all_ignored():
    """所有子任务 Ignored 时应返回 False。"""
    s = 0
    for subtask in SubTask:
        s = set_subtask_status(s, subtask, SubTaskState.Ignored)
    assert has_failed(s) is False


def test_has_failed_mixed_with_one_failed():
    """混合状态中含一个 Failed 时应返回 True。"""
    s = 0
    s = set_subtask_status(s, SubTask.Cover, SubTaskState.Succeeded)
    s = set_subtask_status(s, SubTask.Video, SubTaskState.Skipped)
    s = set_subtask_status(s, SubTask.Nfo, SubTaskState.Failed)
    s = set_subtask_status(s, SubTask.Danmaku, SubTaskState.Ignored)
    s = set_subtask_status(s, SubTask.Subtitle, SubTaskState.Succeeded)
    assert has_failed(s) is True


def test_has_failed_subtitle_failed():
    """Subtitle 单独 Failed 时也应返回 True。"""
    s = set_subtask_status(0, SubTask.Subtitle, SubTaskState.Failed)
    assert has_failed(s) is True


def test_has_failed_returns_bool():
    """返回值应为 bool 类型。"""
    assert isinstance(has_failed(0), bool)


# ---------------------------------------------------------------------------
# should_retry 测试
# ---------------------------------------------------------------------------


def test_should_retry_no_failure():
    """无 Failed 子任务时应返回 False。"""
    assert should_retry(0, 0) is False


def test_should_retry_failure_zero_retries():
    """有 Failed 且 retry_count=0 时应返回 True。"""
    s = set_subtask_status(0, SubTask.Video, SubTaskState.Failed)
    assert should_retry(s, 0) is True


def test_should_retry_failure_below_max():
    """有 Failed 且 retry_count < max_retry 时应返回 True。"""
    s = set_subtask_status(0, SubTask.Video, SubTaskState.Failed)
    assert should_retry(s, 1) is True
    assert should_retry(s, 2) is True


def test_should_retry_failure_at_max():
    """有 Failed 且 retry_count == max_retry 时应返回 False。"""
    s = set_subtask_status(0, SubTask.Video, SubTaskState.Failed)
    assert should_retry(s, MAX_RETRY) is False


def test_should_retry_failure_above_max():
    """有 Failed 且 retry_count > max_retry 时应返回 False。"""
    s = set_subtask_status(0, SubTask.Video, SubTaskState.Failed)
    assert should_retry(s, MAX_RETRY + 1) is False
    assert should_retry(s, 100) is False


def test_should_retry_custom_max_retry():
    """自定义 max_retry 参数应生效。"""
    s = set_subtask_status(0, SubTask.Video, SubTaskState.Failed)
    # max_retry=5: retry_count=4 时应重试, retry_count=5 时不重试
    assert should_retry(s, 4, max_retry=5) is True
    assert should_retry(s, 5, max_retry=5) is False


def test_should_retry_zero_max_retry():
    """max_retry=0 时即使有 Failed 也不应重试。"""
    s = set_subtask_status(0, SubTask.Video, SubTaskState.Failed)
    assert should_retry(s, 0, max_retry=0) is False


def test_should_retry_no_failure_high_retry():
    """无 Failed 时即使 retry_count 很大也不应重试。"""
    assert should_retry(0, 100) is False


def test_should_retry_returns_bool():
    """返回值应为 bool 类型。"""
    s = set_subtask_status(0, SubTask.Video, SubTaskState.Failed)
    assert isinstance(should_retry(s, 0), bool)


# ---------------------------------------------------------------------------
# summary 测试
# ---------------------------------------------------------------------------


def test_summary_zero_status_all_skipped():
    """status=0 时所有子任务状态应为 Skipped。"""
    result = summary(0)
    assert len(result) == 5
    for subtask in SubTask:
        assert result[subtask] == SubTaskState.Skipped


def test_summary_contains_all_subtasks():
    """summary 应包含 5 个子任务的键。"""
    result = summary(0)
    assert set(result.keys()) == set(SubTask)


def test_summary_mixed_states():
    """混合状态应正确反映到 summary。"""
    s = 0
    s = set_subtask_status(s, SubTask.Cover, SubTaskState.Succeeded)
    s = set_subtask_status(s, SubTask.Video, SubTaskState.Failed)
    s = set_subtask_status(s, SubTask.Nfo, SubTaskState.Ignored)
    s = set_subtask_status(s, SubTask.Danmaku, SubTaskState.Skipped)
    s = set_subtask_status(s, SubTask.Subtitle, SubTaskState.Succeeded)
    result = summary(s)
    assert result[SubTask.Cover] == SubTaskState.Succeeded
    assert result[SubTask.Video] == SubTaskState.Failed
    assert result[SubTask.Nfo] == SubTaskState.Ignored
    assert result[SubTask.Danmaku] == SubTaskState.Skipped
    assert result[SubTask.Subtitle] == SubTaskState.Succeeded


def test_summary_returns_dict():
    """返回值应为 dict 类型。"""
    result = summary(0)
    assert isinstance(result, dict)


def test_summary_keys_are_subtask_enum():
    """dict 键应为 SubTask 枚举实例。"""
    result = summary(0)
    for key in result.keys():
        assert isinstance(key, SubTask)


def test_summary_values_are_subtaskstate_enum():
    """dict 值应为 SubTaskState 枚举实例。"""
    result = summary(0)
    for value in result.values():
        assert isinstance(value, SubTaskState)


def test_summary_consistent_with_get_subtask_status():
    """summary 返回的状态应与 get_subtask_status 一致。"""
    s = set_subtask_status(0, SubTask.Nfo, SubTaskState.Failed)
    result = summary(s)
    for subtask in SubTask:
        assert result[subtask] == get_subtask_status(s, subtask)

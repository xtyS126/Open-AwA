"""下载状态位图与失败重试机制。

使用单个整数字段记录每个视频/分页的 5 个子任务下载状态，
并提供失败重试判断。每子任务占 2 bit，5 子任务共 10 bit，
可压缩为单个 ``INTEGER`` 列存储。

参考实现：``bili-sync/crates/bili_sync/src/extension/src/download_table.rs``
的 ``SubTask`` / ``SubTaskStatus`` 位图布局。

位图布局（bit_offset = subtask_index * 2）::

    子任务          bit_offset    占用 bit
    -----------     -----------   ---------
    Cover           0             0-1
    Video           2             2-3
    Nfo             4             4-5
    Danmaku         6             6-7
    Subtitle        8             8-9

每子任务 4 态（占 2 bit）::

    Skipped     = 0b00   跳过（用户配置 skip_option）
    Succeeded   = 0b01   成功
    Ignored     = 0b10   忽略（如字幕不存在、弹幕为空）
    Failed      = 0b11   失败

调用约定：
- :func:`set_subtask_status` 不可变，返回新 status 值，不修改入参
- :func:`should_retry` 默认 ``max_retry=3``，与 Rust 参考一致
- :data:`INITIAL_STATUS` 为 0，表示所有子任务初始均为 ``Skipped``
"""

from __future__ import annotations

from enum import IntEnum
from typing import Dict


# 每个子任务占用的 bit 宽度
_SUBTASK_BIT_WIDTH: int = 2

# 单子任务状态掩码（0b11），位于 bit_offset 处时需左移
_STATE_MASK: int = 0b11


class SubTask(IntEnum):
    """下载子任务枚举。

    表示一个视频下载流程中可独立追踪状态的 5 个子任务，
    枚举值同时作为位图中的索引（``bit_offset = value * 2``）。

    Attributes:
        Cover: 封面下载（bit 0-1）。
        Video: 视频流下载与合并（bit 2-3）。
        Nfo: NFO 元数据生成（bit 4-5）。
        Danmaku: 弹幕下载与 ASS 渲染（bit 6-7）。
        Subtitle: 字幕下载与 SRT 转换（bit 8-9）。
    """

    Cover = 0
    Video = 1
    Nfo = 2
    Danmaku = 3
    Subtitle = 4


class SubTaskState(IntEnum):
    """下载子任务状态枚举。

    每个子任务在位图中占 2 bit，可取 4 种状态。

    Attributes:
        Skipped: 跳过。用户配置 ``skip_option`` 主动跳过该子任务，
            不计入失败，不触发重试。
        Succeeded: 成功。子任务执行成功。
        Ignored: 忽略。子任务因客观原因未产出，如字幕不存在、
            弹幕为空等。不计入失败，不触发重试。
        Failed: 失败。子任务执行失败，下轮调度自动重试，
            达到 :data:`MAX_RETRY` 后标记为永久失败。
    """

    Skipped = 0
    Succeeded = 1
    Ignored = 2
    Failed = 3


# 默认最大重试次数，与 Rust 参考实现一致
MAX_RETRY: int = 3

# 初始状态：所有子任务均为 ``Skipped``
INITIAL_STATUS: int = 0


def _bit_offset(subtask: SubTask) -> int:
    """计算子任务在位图中的起始 bit 偏移。

    Args:
        subtask: 子任务枚举值。

    Returns:
        起始 bit 偏移（``subtask.value * 2``）。
    """
    return int(subtask) * _SUBTASK_BIT_WIDTH


def get_subtask_status(status: int, subtask: SubTask) -> SubTaskState:
    """从 status 整数中读取指定子任务的状态。

    Args:
        status: 位图整数值。
        subtask: 要读取的子任务。

    Returns:
        该子任务对应的 :class:`SubTaskState` 枚举值。

    Examples:
        >>> get_subtask_status(0, SubTask.Cover)
        <SubTaskState.Skipped: 0>
        >>> # Cover=Succeeded(0b01), Video=Failed(0b11)
        >>> get_subtask_status(0b1101, SubTask.Cover)
        <SubTaskState.Succeeded: 1>
        >>> get_subtask_status(0b1101, SubTask.Video)
        <SubTaskState.Failed: 3>
    """
    offset = _bit_offset(subtask)
    raw_state = (status >> offset) & _STATE_MASK
    return SubTaskState(raw_state)


def set_subtask_status(
    status: int, subtask: SubTask, state: SubTaskState
) -> int:
    """将指定子任务的状态写入 status 整数，返回新的 status 值。

    不可变操作：不修改入参 ``status``，返回新值。

    实现步骤：
    1. 计算子任务对应的 2 bit 掩码（``0b11 << bit_offset``）
    2. 清零该 2 bit：``status & ~mask``
    3. 写入新状态：``| (state << bit_offset)``

    Args:
        status: 原位图整数值。
        subtask: 要写入的子任务。
        state: 要写入的子任务状态。

    Returns:
        写入后的新 status 整数值。

    Examples:
        >>> set_subtask_status(0, SubTask.Cover, SubTaskState.Succeeded)
        1
        >>> set_subtask_status(0, SubTask.Video, SubTaskState.Failed)
        12
        >>> # 先 Cover=Succeeded(0b01)，再 Video=Failed(0b11 << 2 = 0b1100)
        >>> s = set_subtask_status(0, SubTask.Cover, SubTaskState.Succeeded)
        >>> s = set_subtask_status(s, SubTask.Video, SubTaskState.Failed)
        >>> s
        13
        >>> # 覆盖写入：先 Video=Failed，再 Video=Succeeded
        >>> s = set_subtask_status(0, SubTask.Video, SubTaskState.Failed)
        >>> set_subtask_status(s, SubTask.Video, SubTaskState.Succeeded)
        4
    """
    offset = _bit_offset(subtask)
    mask = _STATE_MASK << offset
    cleared = status & ~mask
    return cleared | (int(state) << offset)


def all_succeeded(status: int) -> bool:
    """判断所有 5 个子任务是否均为 :class:`SubTaskState.Succeeded`。

    Args:
        status: 位图整数值。

    Returns:
        全部成功返回 True，否则返回 False。

    Examples:
        >>> all_succeeded(0)
        False
        >>> # 所有子任务设为 Succeeded
        >>> s = 0
        >>> for t in SubTask:
        ...     s = set_subtask_status(s, t, SubTaskState.Succeeded)
        >>> all_succeeded(s)
        True
    """
    for subtask in SubTask:
        if get_subtask_status(status, subtask) != SubTaskState.Succeeded:
            return False
    return True


def has_failed(status: int) -> bool:
    """判断是否有任一子任务为 :class:`SubTaskState.Failed`。

    用于决定下轮调度是否需要重试。

    Args:
        status: 位图整数值。

    Returns:
        存在 Failed 子任务返回 True，否则返回 False。

    Examples:
        >>> has_failed(0)
        False
        >>> s = set_subtask_status(0, SubTask.Video, SubTaskState.Failed)
        >>> has_failed(s)
        True
    """
    for subtask in SubTask:
        if get_subtask_status(status, subtask) == SubTaskState.Failed:
            return True
    return False


def should_retry(
    status: int, retry_count: int, max_retry: int = MAX_RETRY
) -> bool:
    """判断是否应该重试该视频/分页的下载。

    判断条件：
    1. 存在任一子任务为 :class:`SubTaskState.Failed`（:func:`has_failed`）
    2. 且当前重试次数 ``retry_count`` 小于 ``max_retry``

    Args:
        status: 位图整数值。
        retry_count: 已重试次数。
        max_retry: 最大重试次数，默认 :data:`MAX_RETRY` (3)。

    Returns:
        应重试返回 True，否则返回 False（已达上限或无失败子任务）。

    Examples:
        >>> s = set_subtask_status(0, SubTask.Video, SubTaskState.Failed)
        >>> should_retry(s, 0)
        True
        >>> should_retry(s, 2)
        True
        >>> should_retry(s, 3)
        False
        >>> should_retry(s, 5)
        False
        >>> should_retry(0, 0)
        False
    """
    if not has_failed(status):
        return False
    return retry_count < max_retry


def summary(status: int) -> Dict[SubTask, SubTaskState]:
    """返回所有子任务状态的字典。

    Args:
        status: 位图整数值。

    Returns:
        ``{SubTask: SubTaskState}`` 字典，包含全部 5 个子任务的状态。

    Examples:
        >>> result = summary(0)
        >>> result[SubTask.Cover]
        <SubTaskState.Skipped: 0>
        >>> result[SubTask.Subtitle]
        <SubTaskState.Skipped: 0>
        >>> s = set_subtask_status(0, SubTask.Danmaku, SubTaskState.Ignored)
        >>> summary(s)[SubTask.Danmaku]
        <SubTaskState.Ignored: 2>
    """
    return {
        subtask: get_subtask_status(status, subtask) for subtask in SubTask
    }

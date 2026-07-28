"""ffmpeg 视频流合并模块。

提供 ffmpeg 可用性检测与 DASH 视频流 + 音频流合并为 MP4 文件的能力。

参考实现：``bili-sync/crates/bili_sync/src/download/merger.rs`` 的
``check_ffmpeg`` / ``merge_video_audio`` 逻辑。

调用约定：
- 合并前必须先检测 ffmpeg 可用性，不可用直接抛 :class:`MergeFailedError`
- 合并完成后清理临时视频/音频文件（``try/finally`` 确保异常时也清理）
- ffmpeg 命令：``ffmpeg -i video.tmp -i audio.tmp -c copy -strict unofficial -f mp4 -y output``
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from loguru import logger

# ffmpeg 调用超时（秒），大文件合并可能耗时较长
FFMPEG_MERGE_TIMEOUT_SECONDS: int = 600

# ffmpeg 版本检测超时（秒）
FFMPEG_PROBE_TIMEOUT_SECONDS: int = 5


class MergeFailedError(Exception):
    """流合并失败异常。

    携带 ``reason`` (失败原因标识) 与 ``stderr`` (ffmpeg stderr 输出) 字段，
    供上层下载任务标记为 Failed 并记录失败原因。

    Attributes:
        reason: 失败原因标识，如 ``ffmpeg_unavailable`` / ``ffmpeg_error`` / ``timeout``。
        stderr: ffmpeg 的 stderr 输出内容（失败时），用于诊断。
    """

    def __init__(self, reason: str, stderr: str = "") -> None:
        self.reason: str = reason
        self.stderr: str = stderr
        message = f"流合并失败: reason={reason}"
        if stderr:
            # stderr 可能很长，截断到 500 字符避免日志膨胀
            message += f", stderr={stderr[:500]}"
        super().__init__(message)


async def check_ffmpeg() -> bool:
    """检测 ffmpeg 是否可用。

    调用 ``ffmpeg -version``，返回码为 0 视为可用。

    Returns:
        True 表示 ffmpeg 可用，False 表示不可用（未安装或调用异常）。
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=FFMPEG_PROBE_TIMEOUT_SECONDS,
        )
        return result.returncode == 0
    except FileNotFoundError:
        # ffmpeg 未安装
        return False
    except subprocess.TimeoutExpired:
        # ffmpeg -version 不应超时，超时视为不可用
        return False
    except OSError:
        # 其他 OS 级别异常（权限不足等）
        return False


async def check_ffmpeg_or_warn() -> bool:
    """检测 ffmpeg 是否可用，不可用记录 WARNING 日志。

    与 :func:`check_ffmpeg` 的区别：不可用时通过 logger 记录 WARNING，
    便于在插件初始化时向用户提示 ffmpeg 缺失但不阻塞加载。

    Returns:
        True 表示 ffmpeg 可用，False 表示不可用。
    """
    available = await check_ffmpeg()
    if not available:
        logger.warning(
            "ffmpeg 不可用，bilibili-toolkit-builtin 视频合并功能将无法使用；"
            "请安装 ffmpeg 并确保其在 PATH 中"
        )
    return available


async def merge_video_audio(
    video_tmp: Path,
    audio_tmp: Path,
    output_path: Path,
) -> None:
    """合并 DASH 视频流与音频流为 MP4 文件。

    调用 ffmpeg 将 ``video_tmp`` 与 ``audio_tmp`` 合并为 ``output_path``，
    使用 ``-c copy`` 流复制模式（不重新编码，速度快）。
    合并完成后（无论成功或失败）清理临时文件。

    Args:
        video_tmp: 视频临时文件路径。
        audio_tmp: 音频临时文件路径。
        output_path: 合并后的 MP4 输出路径。

    Raises:
        MergeFailedError: ffmpeg 不可用、调用超时或返回非零退出码时抛出。
    """
    # 1. 检测 ffmpeg 可用性，不可用直接抛异常
    if not await check_ffmpeg():
        raise MergeFailedError(reason="ffmpeg_unavailable")

    # 2. 调用 ffmpeg 合并（try/finally 确保临时文件清理）
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-i", str(video_tmp),
                "-i", str(audio_tmp),
                "-c", "copy",
                "-strict", "unofficial",
                "-f", "mp4",
                "-y", str(output_path),
            ],
            capture_output=True,
            timeout=FFMPEG_MERGE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        # ffmpeg 在检测后仍找不到（极端竞态），记录并抛异常
        raise MergeFailedError(reason="ffmpeg_not_found", stderr=str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise MergeFailedError(
            reason="timeout",
            stderr=f"ffmpeg 合并超时（{FFMPEG_MERGE_TIMEOUT_SECONDS}秒）: {exc}",
        ) from exc
    except OSError as exc:
        raise MergeFailedError(reason="os_error", stderr=str(exc)) from exc
    finally:
        # 无论成功或失败都清理临时文件
        _cleanup_temp_file(video_tmp)
        _cleanup_temp_file(audio_tmp)

    # 3. 检查退出码，非零抛异常
    if result.returncode != 0:
        stderr_output = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
        raise MergeFailedError(reason="ffmpeg_error", stderr=stderr_output)

    logger.info(
        "ffmpeg 合并成功: output={}, video_tmp={}, audio_tmp={}",
        output_path,
        video_tmp,
        audio_tmp,
    )


def _cleanup_temp_file(path: Path) -> None:
    """清理临时文件，文件不存在或删除失败时静默跳过。

    Args:
        path: 待删除的临时文件路径。
    """
    try:
        if path.exists() and path.is_file():
            path.unlink()
    except OSError as exc:
        # 删除失败不阻塞主流程，仅记录 WARNING
        logger.warning(f"清理临时文件失败: path={path}, error={exc}")


def copy_to_final_path(src: Path, dest: Path) -> None:
    """将合并产物从临时路径复制到最终路径。

    当 ``output_path`` 与最终存储路径不同时（如先写入 tmp 再复制到 NAS），
    调用此函数完成迁移。本函数为独立工具函数，``merge_video_audio`` 默认
    直接写入 ``output_path``，仅在需要两阶段写入时由调用方调用此函数。

    Args:
        src: 源文件路径（合并产物）。
        dest: 目标文件路径。

    Raises:
        FileNotFoundError: 源文件不存在时由 ``shutil.copy`` 抛出。
        OSError: 复制过程中 IO 异常。
    """
    shutil.copy(str(src), str(dest))

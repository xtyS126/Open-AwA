"""OpenBiliClaw 的集中式日志初始化。"""

from __future__ import annotations

import logging
import time
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING

from rich.logging import RichHandler

if TYPE_CHECKING:
    from pathlib import Path

    from openbiliclaw.config import Config

logger = logging.getLogger(__name__)
_NOISY_LOGGERS = ("httpx", "httpcore", "openai", "openai._base_client")


def _coerce_level(level_name: str) -> int:
    """将级别名转换为 logging 级别。"""
    level = logging.getLevelName(level_name.upper())
    if isinstance(level, int):
        return level
    return logging.INFO


def _build_file_handler(
    log_file: object,  # Path，但类型放宽以避免 import
    *,
    max_file_size_mb: int,
    backup_count: int,
    level: int,
) -> logging.Handler:
    """启用轮转时返回轮转文件 handler，否则返回普通 handler。

    当活动文件达到 ``max_file_size_mb`` MB 时触发轮转；此时
    ``RotatingFileHandler`` 将其重命名为 ``<name>.1``（更旧的备份
    顺移至 ``.2``、``.3``……），并删除早于 ``backup_count`` 的副本。
    设置 ``backup_count=1`` 可将总磁盘占用封顶在约
    ``2 * max_file_size_mb`` MB。
    """
    from pathlib import Path

    log_path = Path(str(log_file))

    if max_file_size_mb <= 0 or backup_count < 1:
        handler: logging.Handler = logging.FileHandler(log_path, encoding="utf-8")
    else:
        handler = RotatingFileHandler(
            log_path,
            maxBytes=max_file_size_mb * 1024 * 1024,
            backupCount=backup_count,
            encoding="utf-8",
        )

    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    return handler


def _enforce_size_budget_once(log_file: object, max_file_size_mb: int) -> None:
    """启动时截断过大的日志，避免恢复 7 GB 的文件。

    ``RotatingFileHandler`` 仅在*新写入*时轮转，因此已超大的文件
    会持续增长直到下一个轮转边界。启动时若现有文件已超预算，我们会
    主动轮转一次——这正是用户要求的"清理超过 1G 的历史日志"行为。
    """
    from pathlib import Path

    if max_file_size_mb <= 0:
        return

    log_path = Path(str(log_file))
    if not log_path.exists():
        return

    try:
        size = log_path.stat().st_size
    except OSError:
        return

    if size <= max_file_size_mb * 1024 * 1024:
        return

    # 仅保留最多一个"清理前"快照以便仍可调试，
    # 然后删除更多备份。命名与 RotatingFileHandler 一致
    # （<name>.1 是最新备份）。
    snapshot = log_path.with_name(log_path.name + ".1")
    try:
        if snapshot.exists():
            snapshot.unlink()
        log_path.rename(snapshot)
    except OSError:
        # 重命名失败（如跨设备）时回退为截断。
        try:
            log_path.unlink()
        except OSError:
            return


def _is_managed_log(path: Path, managed_filename: str) -> bool:
    """当且仅当 ``path`` 是受轮转管理的文件或其备份之一时返回 True。

    受管 = 完全等于 ``<filename>`` 或 ``<filename>.N``（N 为数字）。
    其他文件（如 ``backend-restart.log``、``init-run.log``）是
    非受管的——由外部脚本或一次性工具创建，因此按非受管清理策略处理。
    """
    name = path.name
    if name == managed_filename:
        return True
    prefix = managed_filename + "."
    if name.startswith(prefix):
        suffix = name[len(prefix) :]
        return suffix.isdigit()
    return False


def _sweep_unmanaged_logs(
    log_dir: Path,
    *,
    managed_filename: str,
    aggregate_budget_mb: int,
    unmanaged_truncate_mb: int,
    unmanaged_max_age_days: int,
) -> None:
    """清理不受 RotatingFileHandler 管控的 ``logs/`` 文件。

    三条策略，按顺序执行：

    1. **截断巨大的非受管文件** —— 若任一 ``*.log`` 文件（非受管文件）
       超过 ``unmanaged_truncate_mb`` MB，截断为 0 字节。捕获
       ``backend-restart.log``（脚本 stdout 重定向）、
       ``openbiliclaw-restart.log`` 等。采用截断（而非删除）以使
       实时 tail 不会丢失 fd。
    2. **删除陈旧非受管文件** —— 早于 ``unmanaged_max_age_days`` 天的
       文件整体删除。针对过往安装 / 调试会话的旧一次性日志。
    3. **封顶目录总大小** —— 汇总 ``logs/`` 中所有文件（受管 +
       非受管）的总字节数。若超过 ``aggregate_budget_mb`` MB，
       按从旧到新删除非受管文件直到回到预算内。受管文件始终保留
       （由 RotatingFileHandler 负责管理）。

    每次删除 / 截断都会输出 INFO 日志，以便用户看到清理内容。
    所有错误都被吞掉——启动绝不应因清理小问题而中止。
    """
    if not log_dir.exists() or not log_dir.is_dir():
        return

    try:
        entries = [(p, p.stat()) for p in log_dir.iterdir() if p.is_file()]
    except OSError:
        return

    now = time.time()
    age_cutoff = now - unmanaged_max_age_days * 86400 if unmanaged_max_age_days > 0 else 0.0

    # 第一遍：截断巨大的非受管文件
    truncate_bytes = unmanaged_truncate_mb * 1024 * 1024
    for path, st in entries:
        if _is_managed_log(path, managed_filename):
            continue
        if unmanaged_truncate_mb > 0 and st.st_size >= truncate_bytes:
            try:
                size_mb = st.st_size / (1024 * 1024)
                with path.open("w", encoding="utf-8") as f:
                    f.write(
                        f"# truncated {time.strftime('%Y-%m-%d %H:%M:%S')} "
                        f"— was {size_mb:.0f} MB, threshold "
                        f"{unmanaged_truncate_mb} MB\n"
                    )
                logger.info(
                    "[log-cleanup] truncated %s (was %.0f MB)",
                    path.name,
                    size_mb,
                )
            except OSError as exc:
                logger.debug("Failed to truncate %s: %s", path, exc)

    # 第二遍：删除陈旧非受管文件（截断后重新 stat）
    if unmanaged_max_age_days > 0:
        for path in [p for p, _ in entries]:
            if _is_managed_log(path, managed_filename):
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            if st.st_mtime < age_cutoff:
                try:
                    path.unlink()
                    logger.info(
                        "[log-cleanup] deleted stale %s (mtime %s)",
                        path.name,
                        time.strftime("%Y-%m-%d", time.localtime(st.st_mtime)),
                    )
                except OSError as exc:
                    logger.debug("Failed to unlink %s: %s", path, exc)

    # 第三遍：通过删除最旧的非受管文件来强制总量预算
    if aggregate_budget_mb <= 0:
        return
    budget_bytes = aggregate_budget_mb * 1024 * 1024
    try:
        current_entries = [(p, p.stat()) for p in log_dir.iterdir() if p.is_file()]
    except OSError:
        return
    total = sum(st.st_size for _, st in current_entries)
    if total <= budget_bytes:
        return
    # 按 mtime 升序排列非受管文件（最旧在前）并裁剪至预算内
    unmanaged = sorted(
        [(p, st) for p, st in current_entries if not _is_managed_log(p, managed_filename)],
        key=lambda item: item[1].st_mtime,
    )
    for path, st in unmanaged:
        if total <= budget_bytes:
            break
        try:
            path.unlink()
            total -= st.st_size
            logger.info(
                "[log-cleanup] deleted %s (%.0f MB) to enforce %d MB budget",
                path.name,
                st.st_size / (1024 * 1024),
                aggregate_budget_mb,
            )
        except OSError as exc:
            logger.debug("Failed to unlink %s: %s", path, exc)


def configure_logging(
    config: Config,
    console_level_override: str | None = None,
    *,
    sweep_unmanaged: bool = True,
) -> None:
    """为控制台和文件输出配置根日志。

    ``sweep_unmanaged=False`` 跳过 v0.3.30+ 的 ``logs/`` 目录清理
    遍历——供 ``logs-prune`` CLI 命令使用，它运行自己的、感知
    dry-run 的清理，不应被全局 Typer callback 内的自动遍历干扰。
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()

    console_level = _coerce_level(console_level_override or config.logging.level)
    file_level = _coerce_level(config.logging.file_level)

    console_handler = RichHandler(rich_tracebacks=True, show_path=False)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(logging.Formatter("%(message)s"))

    log_file = config.logging.file_path
    log_file.parent.mkdir(parents=True, exist_ok=True)

    _enforce_size_budget_once(log_file, config.logging.max_file_size_mb)
    # v0.3.30+：同时清理同一 logs 目录下的非受管文件。
    # 捕获 start 脚本的 stdout 重定向日志、陈旧一次性
    # bootstrap 日志以及总量大小预算。
    if sweep_unmanaged:
        _sweep_unmanaged_logs(
            config.logging.directory_path,
            managed_filename=config.logging.filename,
            aggregate_budget_mb=config.logging.aggregate_budget_mb,
            unmanaged_truncate_mb=config.logging.unmanaged_truncate_mb,
            unmanaged_max_age_days=config.logging.unmanaged_max_age_days,
        )
    file_handler = _build_file_handler(
        log_file,
        max_file_size_mb=config.logging.max_file_size_mb,
        backup_count=config.logging.backup_count,
        level=file_level,
    )

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    for logger_name in _NOISY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

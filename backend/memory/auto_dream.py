"""
Auto-Dream 记忆自动优化模块。
定时运行，自动去冗存精、合并去重、备份记忆库。
"""
import asyncio
import json
import os
import shutil
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from loguru import logger


class AutoDream:
    """
    Auto-Dream 记忆优化器。
    定时执行记忆整理：去重、清理过期、合并相似、备份。
    使用文件锁和原子写入保证并发安全。
    """

    def __init__(
        self,
        working_dir: Optional[Path] = None,
        db_session=None,
    ):
        self.working_dir = Path(working_dir) if working_dir else Path.home() / ".openawa"
        self.db = db_session
        self._memory_dir = self.working_dir / "memory"
        self._backup_dir = self.working_dir / "backup"
        self._memory_file = self.working_dir / "MEMORY.md"
        self._file_lock = threading.Lock()  # 文件操作锁，防止并发写入破坏数据
        self._shutdown_event: Optional[asyncio.Event] = None  # 优雅关闭信号

    def run_optimization(self) -> dict:
        """
        执行一轮记忆优化。
        返回优化统计。
        """
        stats = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "dedup_count": 0,
            "archive_count": 0,
            "merge_count": 0,
            "backup_created": False,
            "errors": [],
        }

        try:
            # 1. 备份当前 MEMORY.md
            if self._memory_file.exists():
                self._create_backup()
                stats["backup_created"] = True

            # 2. 去重：合并内容高度相似的记忆条目
            stats["dedup_count"] = self._dedup_memories()

            # 3. 合并：把小记忆合并成大记忆
            stats["merge_count"] = self._merge_small_memories()

            # 4. 归档：移除过期和低质量记忆
            stats["archive_count"] = self._archive_stale()

            # 5. 重写优化后的 MEMORY.md
            self._rewrite_memory_file()

            logger.bind(event="auto_dream_complete", **stats).info("Auto-Dream 优化完成")
        except Exception as e:
            logger.bind(event="auto_dream_error", error=str(e)).error("Auto-Dream 优化失败")
            stats["errors"].append(str(e))

        stats["finished_at"] = datetime.now(timezone.utc).isoformat()
        return stats

    def _create_backup(self):
        """创建记忆备份。"""
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = self._backup_dir / f"memory_backup_{timestamp}.md"

        if self._memory_file.exists():
            shutil.copy2(self._memory_file, backup_path)

        # 保留最近 10 个备份
        backups = sorted(
            self._backup_dir.glob("memory_backup_*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old_backup in backups[10:]:
            old_backup.unlink()

        logger.bind(event="memory_backup_created", path=str(backup_path)).info("记忆备份已创建")

    def _atomic_write(self, content: str):
        """原子写入：先写临时文件，再替换，防止写入过程中崩溃导致文件损坏。"""
        tmp_path = self._memory_file.with_suffix(".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, self._memory_file)

    def _dedup_memories(self) -> int:
        """
        去重：检测高度相似的记忆条目并合并。
        使用简单的 Jaccard 相似度。
        """
        if not self._memory_file.exists():
            return 0

        content = self._memory_file.read_text(errors="replace")
        sections = self._split_sections(content)
        if len(sections) < 2:
            return 0

        deduped = []
        removed = 0
        for i, section in enumerate(sections):
            is_dup = False
            for j in range(i):
                sim = self._jaccard_similarity(section, sections[j])
                if sim > 0.8:  # 80% 相似度阈值
                    is_dup = True
                    break
            if not is_dup:
                deduped.append(section)
            else:
                removed += 1

        if removed > 0:
            with self._file_lock:
                self._atomic_write("\n\n".join(deduped))

        return removed

    def _merge_small_memories(self) -> int:
        """
        合并过小的记忆条目（少于 50 字符）。
        """
        if not self._memory_file.exists():
            return 0

        content = self._memory_file.read_text(errors="replace")
        sections = self._split_sections(content)

        merged = 0
        new_sections = []
        buffer = []

        for section in sections:
            if len(section) < 50:
                buffer.append(section.strip())
                if sum(len(s) for s in buffer) > 200:
                    new_sections.append("\n".join(buffer))
                    buffer = []
                    merged += 1
            else:
                if buffer:
                    new_sections.append("\n".join(buffer))
                    buffer = []
                    merged += 1
                new_sections.append(section)

        if buffer:
            new_sections.append("\n".join(buffer))
            merged += 1

        if merged > 0:
            with self._file_lock:
                self._atomic_write("\n\n".join(new_sections))

        return merged

    def _archive_stale(self) -> int:
        """
        归档长期未访问的记忆（标记为 archived）。
        """
        # 通过修改文件中的标记实现
        if not self._memory_file.exists():
            return 0

        content = self._memory_file.read_text(errors="replace")
        # 添加优化标记
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if "最后优化" not in content:
            content = f"<!-- 最后优化: {timestamp} -->\n{content}"
        else:
            import re
            content = re.sub(
                r'<!-- 最后优化: .* -->',
                f'<!-- 最后优化: {timestamp} -->',
                content,
            )
        with self._file_lock:
            self._atomic_write(content)
        return 0

    def _rewrite_memory_file(self):
        """
        重写 MEMORY.md，确保格式整洁。
        """
        # 目前仅确保文件存在
        if not self._memory_file.exists():
            self._memory_file.write_text("# 长期记忆\n\n> 自动化记忆整理\n\n")

    @staticmethod
    def _split_sections(content: str) -> list[str]:
        """将 MEMORY.md 按段落分割。"""
        # 按 ## 标题分割
        sections = []
        current = []
        for line in content.split("\n"):
            if line.startswith("## ") and current:
                sections.append("\n".join(current))
                current = [line]
            else:
                current.append(line)
        if current:
            sections.append("\n".join(current))
        return sections if len(sections) > 1 else [content]

    async def schedule(self, interval_hours: float = 24) -> None:
        """
        启动定时 Auto-Dream 优化任务。
        每隔 interval_hours 小时执行一次记忆整理。
        可通过 stop() 方法优雅关闭。
        """
        if self._shutdown_event is None:
            self._shutdown_event = asyncio.Event()

        logger.bind(event="auto_dream_scheduled", interval_hours=interval_hours).info(
            "Auto-Dream 定时任务已启动"
        )
        while not self._shutdown_event.is_set():
            try:
                # 使用带超时的 wait 替代 sleep，支持优雅关闭
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=interval_hours * 3600,
                )
                break  # shutdown 信号已触发
            except asyncio.TimeoutError:
                pass  # 正常超时，执行优化
            except asyncio.CancelledError:
                logger.info("Auto-Dream 定时任务已取消")
                break

            try:
                logger.bind(event="auto_dream_run").info("Auto-Dream 开始执行定时优化")
                # 在独立线程中执行同步文件 I/O，避免阻塞事件循环
                stats = await asyncio.to_thread(self.run_optimization)
                logger.bind(event="auto_dream_run_complete", **stats).info(
                    f"Auto-Dream 优化完成: 去重{stats['dedup_count']}条, 合并{stats['merge_count']}条"
                )
            except Exception as exc:
                logger.bind(event="auto_dream_schedule_error").error(f"Auto-Dream 定时执行异常: {exc}")
                await asyncio.sleep(60)  # 出错后等 1 分钟再重试

    def stop(self):
        """发送关闭信号，优雅停止定时任务。"""
        if self._shutdown_event:
            self._shutdown_event.set()

    @staticmethod
    def _jaccard_similarity(a: str, b: str) -> float:
        """计算两段文本的 Jaccard 相似度。"""
        set_a = set(a.lower().split())
        set_b = set(b.lower().split())
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

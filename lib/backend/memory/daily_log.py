"""
每日日志模块 — 自动创建和维护 memory/YYYY-MM-DD.md 日志文件。
Agent 对话内容按天归档，支持追加写入和自动创建。
"""
import os
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Optional

from loguru import logger


class DailyLogManager:
    """
    每日日志管理器。
    按天创建 Markdown 日志文件，记录对话摘要和关键事件。
    """

    def __init__(self, memory_dir: Optional[Path] = None):
        self.memory_dir = Path(memory_dir) if memory_dir else Path.home() / ".openawa" / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def get_log_path(self, log_date: Optional[date] = None) -> Path:
        """获取指定日期的日志文件路径。"""
        d = log_date or date.today()
        return self.memory_dir / f"{d.isoformat()}.md"

    def ensure_daily_log(self, log_date: Optional[date] = None) -> Path:
        """
        确保当天的日志文件存在，不存在则创建带模板的文件。
        """
        log_path = self.get_log_path(log_date)
        if not log_path.exists():
            d = log_date or date.today()
            weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            weekday = weekday_names[d.weekday()]

            log_path.write_text(
                f"# {d.isoformat()} {weekday}\n\n"
                f"## 对话记录\n\n"
                f"<!-- 以下由 Agent 自动追加 -->\n\n",
                encoding="utf-8",
            )
            logger.bind(event="daily_log_created", date=str(d)).info("每日日志已创建")

        return log_path

    def append_entry(
        self,
        content: str,
        entry_type: str = "conversation",
        log_date: Optional[date] = None,
        metadata: Optional[dict] = None,
    ) -> bool:
        """
        向每日日志追加条目。

        Args:
            content: 日志内容
            entry_type: 条目类型（conversation/task/decision/summary）
            log_date: 日期（默认今天）
            metadata: 附加元数据

        Returns:
            是否写入成功
        """
        log_path = self.ensure_daily_log(log_date)

        now = datetime.now(timezone.utc).strftime("%H:%M")
        timestamp = datetime.now(timezone.utc).isoformat()

        # 构建条目
        lines = []
        if entry_type == "conversation":
            lines.append(f"### {now} 对话")
        elif entry_type == "task":
            lines.append(f"### {now} 任务")
        elif entry_type == "decision":
            lines.append(f"### {now} 决策")
        elif entry_type == "summary":
            lines.append(f"### {now} 摘要")
        else:
            lines.append(f"### {now}")

        lines.append("")
        lines.append(content.strip())
        lines.append("")

        if metadata:
            lines.append(f"<!-- metadata: {timestamp} -->")

        lines.append("")

        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines))
            return True
        except Exception as e:
            logger.bind(event="daily_log_write_error", error=str(e)).error("每日日志写入失败")
            return False

    def append_conversation(
        self,
        user_message: str,
        assistant_response: str,
        session_id: str = "",
        log_date: Optional[date] = None,
    ) -> bool:
        """
        记录一轮对话到每日日志。
        """
        content = (
            f"**用户**: {user_message[:500]}\n\n"
            f"**助手**: {assistant_response[:1000]}"
        )
        if session_id:
            content += f"\n\n> session: {session_id[:12]}"
        return self.append_entry(content, entry_type="conversation", log_date=log_date)

    def get_logs_for_range(
        self,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        """
        获取日期范围内的日志文件。
        """
        logs = []
        current = start_date
        while current <= end_date:
            log_path = self.get_log_path(current)
            if log_path.exists():
                try:
                    content = log_path.read_text(encoding="utf-8")
                    logs.append({
                        "date": current.isoformat(),
                        "file": str(log_path),
                        "size": len(content),
                        "lines": content.count("\n") + 1,
                        "content": content[:2000],
                        "has_more": len(content) > 2000,
                    })
                except Exception:
                    logger.bind(module="daily_log", event="log_read_error", path=str(log_path)).warning(
                        "读取日志文件失败，跳过该文件"
                    )
                    pass
            current = date.fromordinal(current.toordinal() + 1)
        return logs

    def get_recent_logs(self, days: int = 7) -> list[dict]:
        """获取最近 N 天的日志。"""
        today = date.today()
        start = date.fromordinal(today.toordinal() - days + 1)
        return self.get_logs_for_range(start, today)

    def list_logs(self) -> list[str]:
        """列出所有日志文件。"""
        logs = []
        for f in sorted(self.memory_dir.glob("????-??-??.md"), reverse=True):
            logs.append(f.stem)
        return logs

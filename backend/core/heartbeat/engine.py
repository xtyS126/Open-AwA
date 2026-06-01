"""
心跳引擎 — 按配置的间隔执行自检，生成摘要并推送到目标渠道。
"""
import re
from datetime import datetime, timezone, time as dt_time
from pathlib import Path
from typing import Any, Optional, Callable

from loguru import logger

# Cron 解析辅助：简单的五段 cron 支持
_CRON_RE = re.compile(
    r'^(\*|\d+(?:-\d+)?(?:/\d+)?(?:,\d+(?:-\d+)?(?:/\d+)?)*)\s+'
    r'(\*|\d+(?:-\d+)?(?:/\d+)?(?:,\d+(?:-\d+)?(?:/\d+)?)*)\s+'
    r'(\*|\d+(?:-\d+)?(?:/\d+)?(?:,\d+(?:-\d+)?(?:/\d+)?)*)\s+'
    r'(\*|\d+(?:-\d+)?(?:/\d+)?(?:,\d+(?:-\d+)?(?:/\d+)?)*)\s+'
    r'(\*|\d+(?:-\d+)?(?:/\d+)?(?:,\d+(?:-\d+)?(?:/\d+)?)*)$'
)


def _parse_interval(every: str) -> int:
    """
    解析间隔字符串为秒数。
    支持格式: "30s", "5m", "1h", "2h30m", "90s"
    """
    if _CRON_RE.match(every):
        return 0  # Cron 表达式由调度器处理

    total_seconds = 0
    parts = re.findall(r'(\d+)(s|m|h)', every)
    for value, unit in parts:
        v = int(value)
        if unit == 's':
            total_seconds += v
        elif unit == 'm':
            total_seconds += v * 60
        elif unit == 'h':
            total_seconds += v * 3600
    return total_seconds or 21600  # 默认 6 小时


def _is_cron_match(cron_expr: str, dt: datetime) -> bool:
    """
    检查给定时间是否匹配 cron 表达式（简化实现）。
    """
    if not _CRON_RE.match(cron_expr):
        return False
    parts = cron_expr.split()
    # 简化实现：只做每分钟检查
    return True  # 实际调度由 ScheduledTaskManager 处理


class HeartbeatEngine:
    """
    心跳引擎。
    按配置的间隔执行自检：读取 HEARTBEAT.md → 调用 Agent → 发送结果到目标渠道。
    """

    def __init__(
        self,
        workspace_dir: Optional[Path] = None,
        agent_call_fn: Optional[Callable] = None,
    ):
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path.home() / ".openawa" / "workspaces" / "default"
        self._agent_call_fn = agent_call_fn
        self._heartbeat_file = self.workspace_dir / "HEARTBEAT.md"
        self._enabled = False
        self._config = {
            "enabled": False,
            "every": "6h",
            "target": "main",
            "active_hours": {"start": "08:00", "end": "22:00"},
        }

    def configure(self, config: dict):
        """更新心跳配置。"""
        self._config.update(config)
        self._enabled = config.get("enabled", False)
        if self._enabled:
            self._ensure_heartbeat_file()

    def should_run(self, now: Optional[datetime] = None) -> bool:
        """
        判断当前是否应该执行心跳。
        """
        if not self._enabled:
            return False

        now = now or datetime.now(timezone.utc)
        active_hours = self._config.get("active_hours", {})
        if active_hours:
            start = active_hours.get("start", "08:00")
            end = active_hours.get("end", "22:00")
            current_time = now.strftime("%H:%M")
            if not (start <= current_time <= end):
                return False

        return True

    def get_heartbeat_content(self) -> str:
        """
        读取 HEARTBEAT.md 的内容。
        """
        self._ensure_heartbeat_file()
        try:
            return self._heartbeat_file.read_text(errors="replace")
        except Exception:
            return "# Heartbeat\n\n- 检查系统状态\n- 查看待办事项\n"

    def get_schedule_interval(self) -> str:
        """获取心跳间隔。"""
        return self._config.get("every", "6h")

    def get_target(self) -> str:
        """获取目标渠道（main/last/inbox）。"""
        return self._config.get("target", "main")

    def _ensure_heartbeat_file(self):
        """确保 HEARTBEAT.md 存在。"""
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        if not self._heartbeat_file.exists():
            self._heartbeat_file.write_text(
                "# Heartbeat Checklist\n\n"
                "- 扫描紧急消息\n"
                "- 查看待办事项\n"
                "- 检查系统状态\n"
                "若安静超过 8h，轻量 check-in\n"
            )

    def get_config(self) -> dict:
        """获取当前配置。"""
        return dict(self._config)

    def update_heartbeat_file(self, content: str):
        """更新 HEARTBEAT.md 内容。"""
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self._heartbeat_file.write_text(content)
        logger.bind(event="heartbeat_file_updated").info("HEARTBEAT.md 已更新")

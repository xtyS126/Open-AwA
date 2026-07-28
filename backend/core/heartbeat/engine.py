"""
心跳引擎 — 按配置的间隔执行自检，生成摘要并推送到目标渠道。
"""
import re
from datetime import datetime, timezone, time as dt_time
from pathlib import Path
from typing import Any, Optional, Callable

from apscheduler.triggers.cron import CronTrigger
from loguru import logger


def _is_cron_expression(every: str) -> bool:
    """
    判断字符串是否为有效的五段 cron 表达式。
    委托给 APScheduler CronTrigger.from_crontab 进行校验，
    替代原自实现的 _CRON_RE 正则。
    """
    if not every or not isinstance(every, str):
        return False
    try:
        CronTrigger.from_crontab(every, timezone="UTC")
        return True
    except (ValueError, TypeError):
        return False


def _parse_interval(every: str) -> int:
    """
    解析间隔字符串为秒数。
    支持格式: "30s", "5m", "1h", "2h30m", "90s"
    若为 cron 表达式则返回 0（实际调度由 ScheduledTaskManager 内的 APScheduler 处理）。
    """
    # cron 表达式判定委托给 CronTrigger.from_crontab
    if _is_cron_expression(every):
        return 0

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

    async def run(self, context: Optional[dict] = None) -> dict:
        """
        执行一次心跳检查：读取 HEARTBEAT.md → 调用 Agent → 返回结果。
        """
        if not self._enabled:
            return {"success": False, "message": "心跳未启用"}

        try:
            content = self.get_heartbeat_content()
            if self._agent_call_fn:
                result = await self._agent_call_fn(content, context or {})
                return {
                    "success": True,
                    "message": "心跳执行完成",
                    "content": content[:500],
                    "result": result,
                    "target": self.get_target(),
                }
            else:
                return {
                    "success": True,
                    "message": "心跳检查完成（无 Agent 回调）",
                    "content": content[:500],
                    "target": self.get_target(),
                }
        except Exception as exc:
            logger.bind(event="heartbeat_error").error(f"心跳执行失败: {exc}")
            return {"success": False, "message": f"心跳执行失败: {str(exc)}"}


class HeartbeatEngineRegistry:
    """
    心跳引擎注册表 — 按工作空间 ID 管理多个 HeartbeatEngine 实例。
    每个工作空间可以有独立的心跳配置和调度。
    """

    def __init__(self):
        self._engines: dict[str, HeartbeatEngine] = {}

    def get(self, workspace_id: str) -> HeartbeatEngine:
        """获取或创建指定工作空间的心跳引擎。"""
        if workspace_id not in self._engines:
            workspace_dir = Path.home() / ".openawa" / "workspaces" / workspace_id
            self._engines[workspace_id] = HeartbeatEngine(workspace_dir=workspace_dir)
        return self._engines[workspace_id]

    def remove(self, workspace_id: str):
        """移除工作空间的心跳引擎。"""
        self._engines.pop(workspace_id, None)

    def list_workspaces(self) -> list[str]:
        """列出所有已注册的工作空间。"""
        return list(self._engines.keys())

    def get_all_engines(self) -> dict[str, HeartbeatEngine]:
        """获取所有心跳引擎。"""
        return dict(self._engines)


# 全局心跳注册表单例
_heartbeat_registry: Optional[HeartbeatEngineRegistry] = None


def get_heartbeat_registry() -> HeartbeatEngineRegistry:
    """获取心跳引擎注册表单例。"""
    global _heartbeat_registry
    if _heartbeat_registry is None:
        _heartbeat_registry = HeartbeatEngineRegistry()
    return _heartbeat_registry

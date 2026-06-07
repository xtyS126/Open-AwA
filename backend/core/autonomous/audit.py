"""
自主模式审计日志模块。

记录自主运行期间的所有操作，支持 full（全部记录）和 minimal（仅拒绝）两种级别。
日志按天轮转，JSONL 格式写入 .openawa/audit/ 目录。
"""

from __future__ import annotations

import asyncio
import datetime
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from core.autonomous.config import AutonomousConfig, AuditLevel


class AutonomousAuditor:
    """自主模式审计日志记录器。"""

    def __init__(self, config: AutonomousConfig):
        self._audit_level = config.audit_level
        self._enabled = config.autonomous_mode

        if config.workspace_root:
            self._audit_dir = Path(config.workspace_root) / ".openawa" / "audit"
            self._audit_dir.mkdir(parents=True, exist_ok=True)
        else:
            self._audit_dir = None

        self._buffer: list[Dict[str, Any]] = []
        self._buffer_lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None

        logger.info(
            f"审计日志已初始化: level={self._audit_level.value}, "
            f"dir={self._audit_dir}"
        )

    def _get_log_file_path(self) -> Optional[Path]:
        """获取当天的日志文件路径。"""
        if not self._audit_dir:
            return None
        today = datetime.date.today().isoformat()
        return self._audit_dir / f"{today}.jsonl"

    async def record(
        self,
        session_id: str,
        action: str,
        parameters: Dict[str, Any],
        decision: str,
        denied_by: Optional[str] = None,
        workspace_violation: bool = False,
        network_target: Optional[str] = None,
        execution_time_ms: int = 0,
        resource_usage: Optional[Dict[str, Any]] = None,
        checkpoint_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """记录一条审计事件。

        minimal 级别下仅记录 decision != "allowed" 的事件。
        """
        if not self._enabled:
            return

        if self._audit_level == AuditLevel.MINIMAL and decision == "allowed":
            return

        entry = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "session_id": session_id,
            "mode": "autonomous",
            "action": action,
            "parameters": self._sanitize_params(parameters),
            "decision": decision,
            "denied_by": denied_by,
            "workspace_violation": workspace_violation,
            "network_target": network_target,
            "execution_time_ms": execution_time_ms,
            "resource_usage": resource_usage or {},
            "checkpoint_id": checkpoint_id,
            "error": error,
        }

        async with self._buffer_lock:
            self._buffer.append(entry)
            # 缓冲区超过 50 条时触发刷新
            if len(self._buffer) >= 50:
                await self._flush()

    def _sanitize_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """脱敏敏感参数（API Key、Token 等）。"""
        if not params:
            return {}
        sanitized = dict(params)
        for key in list(sanitized.keys()):
            if any(s in key.lower() for s in ("api_key", "token", "secret", "password", "key")):
                sanitized[key] = "***REDACTED***"
        # 截断过长的值
        for key, value in sanitized.items():
            if isinstance(value, str) and len(value) > 1000:
                sanitized[key] = value[:1000] + "...[truncated]"
        return sanitized

    async def _flush(self) -> None:
        """将缓冲区中的日志写入磁盘。"""
        if not self._buffer:
            return

        log_path = self._get_log_file_path()
        if not log_path:
            self._buffer.clear()
            return

        try:
            lines = "\n".join(
                json.dumps(entry, ensure_ascii=False, default=str)
                for entry in self._buffer
            ) + "\n"

            await asyncio.to_thread(
                lambda: log_path.parent.mkdir(parents=True, exist_ok=True)
            )
            await asyncio.to_thread(
                lambda: log_path.open("a", encoding="utf-8").write(lines)
            )
            self._buffer.clear()
        except (OSError, IOError) as e:
            logger.warning(f"审计日志写入失败: {e}")

    async def flush(self) -> None:
        """手动刷新审计日志缓冲区。"""
        async with self._buffer_lock:
            await self._flush()

    async def cleanup_old_logs(self, keep_days: int = 90) -> int:
        """清理超过保留天数的审计日志。"""
        if not self._audit_dir:
            return 0

        cutoff = datetime.date.today() - datetime.timedelta(days=keep_days)
        removed = 0

        try:
            for log_file in self._audit_dir.glob("*.jsonl"):
                try:
                    file_date = datetime.date.fromisoformat(log_file.stem)
                    if file_date < cutoff:
                        await asyncio.to_thread(log_file.unlink)
                        removed += 1
                except (ValueError, OSError):
                    continue
        except OSError as e:
            logger.warning(f"审计日志清理失败: {e}")

        if removed > 0:
            logger.info(f"已清理 {removed} 个过期审计日志文件（保留 {keep_days} 天）")

        return removed

    def schedule_periodic_flush(self, interval_seconds: int = 30) -> asyncio.Task:
        """启动定期刷新任务。

        Args:
            interval_seconds: 刷新间隔（秒）
        """
        async def _flush_loop():
            while True:
                await asyncio.sleep(interval_seconds)
                async with self._buffer_lock:
                    await self._flush()

        self._flush_task = asyncio.create_task(_flush_loop())
        return self._flush_task

    async def stop(self) -> None:
        """停止审计日志记录器。"""
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        async with self._buffer_lock:
            await self._flush()


# 全局默认实例
_default_auditor: Optional[AutonomousAuditor] = None


def get_auditor() -> Optional[AutonomousAuditor]:
    """获取当前 AutonomousAuditor 实例。"""
    return _default_auditor


def set_auditor(auditor: AutonomousAuditor) -> None:
    """设置全局 AutonomousAuditor 实例。"""
    global _default_auditor
    _default_auditor = auditor

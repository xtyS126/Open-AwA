"""
自主运行模式配置模块。
仅通过 .env 环境变量读取，不暴露 API/UI。

所有配置项在 AutonomousConfig 中定义，
通过 from_env() 类方法从环境变量加载并验证。
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import List, Optional, Set

from loguru import logger


def _safe_int(env_key: str, default: int) -> int:
    """安全地从环境变量读取整数值，类型错误时使用默认值并记录警告。"""
    raw = os.getenv(env_key, "")
    if not raw:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        logger.warning(f"环境变量 {env_key} 的值 '{raw}' 不是有效整数，使用默认值 {default}")
        return default
from pydantic import BaseModel, Field, model_validator


class NetworkPolicy(str, Enum):
    """网络出站策略"""
    ALLOW_ALL = "allow_all"
    BLOCK_LOCAL = "block_local"
    ALLOWLIST = "allowlist"


class AuditLevel(str, Enum):
    """审计日志级别"""
    MINIMAL = "minimal"
    FULL = "full"


class AutonomousScope(str, Enum):
    """自主运行生效范围"""
    SCHEDULED = "scheduled"
    CHAT = "chat"
    CI = "ci"


# 内网地址段（RFC 1918 + 回环 + 链路本地）
_DEFAULT_BLOCKED_CIDRS: tuple[str, ...] = (
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "127.0.0.0/8",
    "169.254.0.0/16",
)

# 云元数据端点（始终拒绝）
_CLOUD_METADATA_HOSTS: frozenset = frozenset({
    "169.254.169.254",
    "metadata.google.internal",
})


class AutonomousConfig(BaseModel):
    """自主运行模式完整配置。

    所有字段均来自 .env 环境变量，通过 from_env() 类方法加载。
    """

    # 主开关
    autonomous_mode: bool = False

    # 确认密钥：设置后开启自主模式需同时提供
    confirm_key: str = ""

    # 生效范围
    scope: set[AutonomousScope] = Field(default_factory=set)

    # 工作区根目录（自主模式下必填）
    workspace_root: str = ""

    # 网络策略
    network_policy: NetworkPolicy = NetworkPolicy.ALLOW_ALL
    network_allowlist: list[str] = Field(default_factory=list)

    # 资源限制
    cmd_timeout: int = 120       # 单命令超时（秒）
    task_timeout: int = 1800     # 总任务超时（秒）
    memory_limit: int = 1024     # 内存限制（MB）

    # 自动回滚
    checkpoint_enabled: bool = True

    # 审计日志
    audit_level: AuditLevel = AuditLevel.FULL

    # 通知告警
    alert_webhook: str = ""

    @model_validator(mode="after")
    def validate_consistency(self) -> "AutonomousConfig":
        """跨字段一致性校验。自主模式开启时强制执行必要验证。"""
        if not self.autonomous_mode:
            return self

        errors: list[str] = []

        # 确认密钥已设置时，必须匹配
        expected_key = os.getenv("OPENAWA_AUTONOMOUS_CONFIRM_KEY", "").strip()
        if expected_key and self.confirm_key != expected_key:
            errors.append("OPENAWA_AUTONOMOUS_CONFIRM_KEY 不匹配，自主模式拒绝启动")

        # 生效范围不能为空
        if not self.scope:
            errors.append("OPENAWA_AUTONOMOUS_MODE=true 时 SCOPE 不能为空，请至少指定一个有效范围")

        # 工作区根目录必须存在且可写
        if not self.workspace_root:
            errors.append("OPENAWA_AUTONOMOUS_MODE=true 时 WORKSPACE 必须设置")
        else:
            ws = Path(self.workspace_root)
            if not ws.exists():
                errors.append(f"工作区路径不存在: {self.workspace_root}")
            elif not ws.is_dir():
                errors.append(f"工作区路径不是目录: {self.workspace_root}")
            elif not os.access(str(ws), os.W_OK):
                errors.append(f"工作区路径不可写: {self.workspace_root}")

        # 超时范围校验
        if self.cmd_timeout < 1 or self.cmd_timeout > 600:
            errors.append(f"CMD_TIMEOUT 必须在 1-600 秒之间，当前值: {self.cmd_timeout}")
        if self.task_timeout < 1 or self.task_timeout > 86400:
            errors.append(f"TASK_TIMEOUT 必须在 1-86400 秒之间，当前值: {self.task_timeout}")

        # 内存范围校验
        if self.memory_limit < 1 or self.memory_limit > 16384:
            errors.append(f"MEMORY_LIMIT 必须在 1-16384 MB 之间，当前值: {self.memory_limit}")

        if errors:
            for err in errors:
                logger.error(f"[自主模式配置错误] {err}")
            raise ValueError(f"自主模式配置验证失败: {'; '.join(errors)}")

        return self

    @classmethod
    def from_env(cls) -> "AutonomousConfig":
        """从环境变量加载并解析自主模式配置。"""
        mode = os.getenv("OPENAWA_AUTONOMOUS_MODE", "false").strip().lower()

        # 解析生效范围
        scope_raw = os.getenv("OPENAWA_AUTONOMOUS_SCOPE", "")
        scope_set: set[AutonomousScope] = set()
        if scope_raw:
            for item in scope_raw.split(","):
                item = item.strip().lower()
                try:
                    scope_set.add(AutonomousScope(item))
                except ValueError:
                    logger.warning(f"忽略未知的自主运行范围: {item}")

        # 解析网络白名单
        allowlist_raw = os.getenv("OPENAWA_AUTONOMOUS_NETWORK_ALLOWLIST", "")
        allowlist = [a.strip() for a in allowlist_raw.split(",") if a.strip()] if allowlist_raw else []

        config = cls(
            autonomous_mode=mode in ("true", "1", "yes", "on"),
            confirm_key=os.getenv("OPENAWA_AUTONOMOUS_CONFIRM_KEY", ""),
            scope=scope_set,
            workspace_root=os.getenv("OPENAWA_AUTONOMOUS_WORKSPACE", ""),
            network_policy=NetworkPolicy(
                os.getenv("OPENAWA_AUTONOMOUS_NETWORK_POLICY", "allow_all").strip().lower()
            ),
            network_allowlist=allowlist,
            cmd_timeout=_safe_int("OPENAWA_AUTONOMOUS_CMD_TIMEOUT", 120),
            task_timeout=_safe_int("OPENAWA_AUTONOMOUS_TASK_TIMEOUT", 1800),
            memory_limit=_safe_int("OPENAWA_AUTONOMOUS_MEMORY_LIMIT", 1024),
            checkpoint_enabled=os.getenv("OPENAWA_AUTONOMOUS_CHECKPOINT_ENABLED", "true").strip().lower() in ("true", "1", "yes", "on"),
            audit_level=AuditLevel(
                os.getenv("OPENAWA_AUTONOMOUS_AUDIT_LEVEL", "full").strip().lower()
            ),
            alert_webhook=os.getenv("OPENAWA_AUTONOMOUS_ALERT_WEBHOOK", ""),
        )
        return config

    def is_scope_enabled(self, scope: str) -> bool:
        """检查指定 scope 是否启用自主模式。"""
        try:
            return AutonomousScope(scope.lower()) in self.scope
        except ValueError:
            return False

    def get_effective_summary(self) -> dict:
        """获取当前安全配置摘要（不含密钥）。"""
        return {
            "autonomous_mode": self.autonomous_mode,
            "scope": [s.value for s in self.scope],
            "workspace_root": self.workspace_root,
            "network_policy": self.network_policy.value,
            "network_allowlist": self.network_allowlist if self.network_policy == NetworkPolicy.ALLOWLIST else None,
            "cmd_timeout_s": self.cmd_timeout,
            "task_timeout_s": self.task_timeout,
            "memory_limit_mb": self.memory_limit,
            "checkpoint_enabled": self.checkpoint_enabled,
            "audit_level": self.audit_level.value,
            "alert_webhook_configured": bool(self.alert_webhook),
        }

    @property
    def is_active(self) -> bool:
        """自主模式是否已激活。"""
        return self.autonomous_mode

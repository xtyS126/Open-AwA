"""
自主运行模式模块。

仅通过 .env 环境变量配置，提供四层安全洋葱模型：
- HardDenyChecker: 硬底线（系统破坏命令、敏感路径、自身配置）
- WorkspaceBoundary: 工作区路径边界
- NetworkPolicyChecker: 网络出站策略
- ResourceLimiter: CPU/内存/时间限制

使用方式：
    from core.autonomous import init_autonomous_mode, get_autonomous_manager

    # 在 main.py lifespan 启动时
    manager = init_autonomous_mode()

    # 在 executor 中拦截检查（异步调用）
    am = get_autonomous_manager()
    if am and am.is_autonomous:
        denial = await am.check_all(action, params)
        if denial:
            return denial
"""

from core.autonomous.config import AutonomousConfig, AutonomousScope, NetworkPolicy, AuditLevel
from core.autonomous.manager import (
    AutonomousModeManager,
    get_autonomous_manager,
    set_autonomous_manager,
    init_autonomous_mode,
)
from core.autonomous.hard_deny import HardDenyChecker
from core.autonomous.workspace_boundary import WorkspaceBoundary
from core.autonomous.network_policy import NetworkPolicyChecker
from core.autonomous.resource_limits import ResourceLimiter
from core.autonomous.checkpoint import CheckpointManager
from core.autonomous.audit import AutonomousAuditor

__all__ = [
    "AutonomousConfig",
    "AutonomousScope",
    "NetworkPolicy",
    "AuditLevel",
    "AutonomousModeManager",
    "get_autonomous_manager",
    "set_autonomous_manager",
    "init_autonomous_mode",
    "HardDenyChecker",
    "WorkspaceBoundary",
    "NetworkPolicyChecker",
    "ResourceLimiter",
    "CheckpointManager",
    "AutonomousAuditor",
]

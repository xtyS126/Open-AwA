"""
自主运行模式管理器（单例）。

统一管理自主模式的初始化、安全检查和审计日志。
在 main.py lifespan 启动时初始化，提供全局访问接口。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from loguru import logger

from core.autonomous.audit import AutonomousAuditor, set_auditor
from core.autonomous.checkpoint import CheckpointManager, set_checkpoint_manager
from core.autonomous.config import AutonomousConfig
from core.autonomous.hard_deny import HardDenyChecker, set_hard_deny_checker
from core.autonomous.network_policy import NetworkPolicyChecker, set_network_checker
from core.autonomous.resource_limits import ResourceLimiter, set_resource_limiter
from core.autonomous.workspace_boundary import WorkspaceBoundary, set_workspace_boundary


class AutonomousModeManager:
    """自主运行模式管理器（全局单例）。

    在应用启动时创建并初始化，提供四个安全层的统一入口。

    使用方式：
        config = AutonomousConfig.from_env()
        manager = AutonomousModeManager(config)
        if manager.is_autonomous:
            manager.initialize()

        # 在 executor 中拦截检查（异步调用）
        denial = await manager.check_all("execute_command", {"command": "ls"})
        if denial:
            return denial  # 非阻塞，立即返回
    """

    def __init__(self, config: AutonomousConfig):
        self._config = config
        self._initialized = False

        # 各安全层组件（initialize() 后可用）
        self._hard_deny: Optional[HardDenyChecker] = None
        self._workspace: Optional[WorkspaceBoundary] = None
        self._network: Optional[NetworkPolicyChecker] = None
        self._resource: Optional[ResourceLimiter] = None
        self._checkpoint: Optional[CheckpointManager] = None
        self._auditor: Optional[AutonomousAuditor] = None

    @property
    def is_autonomous(self) -> bool:
        """自主模式是否已激活。"""
        return self._config.autonomous_mode

    @property
    def config(self) -> AutonomousConfig:
        """获取配置。"""
        return self._config

    @property
    def auditor(self) -> Optional[AutonomousAuditor]:
        """获取审计日志记录器。"""
        return self._auditor

    @property
    def checkpoint(self) -> Optional[CheckpointManager]:
        """获取检查点管理器。"""
        return self._checkpoint

    @property
    def resource_limiter(self) -> Optional[ResourceLimiter]:
        """获取资源限制器。"""
        return self._resource

    def is_active_for(self, scope: str) -> bool:
        """检查指定 scope 是否启用了自主模式。"""
        return self._config.is_scope_enabled(scope)

    def initialize(self) -> None:
        """初始化自主模式的所有安全组件。

        必须在 config 验证通过后调用。
        初始化失败将导致应用启动失败。
        """
        if self._initialized:
            return

        try:
            # 1. 硬底线检查器
            self._hard_deny = HardDenyChecker(self._config)
            set_hard_deny_checker(self._hard_deny)

            # 2. 工作区边界
            self._workspace = WorkspaceBoundary(self._config)
            set_workspace_boundary(self._workspace)

            # 3. 网络策略
            self._network = NetworkPolicyChecker(self._config)
            set_network_checker(self._network)

            # 4. 资源限制
            self._resource = ResourceLimiter(self._config)
            set_resource_limiter(self._resource)

            # 5. 检查点
            self._checkpoint = CheckpointManager(self._config)
            set_checkpoint_manager(self._checkpoint)

            # 6. 审计日志
            self._auditor = AutonomousAuditor(self._config)
            set_auditor(self._auditor)
            # 启动定期刷新（每 30 秒）
            self._auditor.schedule_periodic_flush(30)

            self._initialized = True

            logger.warning(
                f"[SECURITY] 自主运行模式已初始化: "
                f"scope={[s.value for s in self._config.scope]}, "
                f"workspace={self._config.workspace_root}, "
                f"network={self._config.network_policy.value}, "
                f"cmd_timeout={self._config.cmd_timeout}s, "
                f"task_timeout={self._config.task_timeout}s, "
                f"checkpoint={self._config.checkpoint_enabled}, "
                f"audit={self._config.audit_level.value}"
            )
        except Exception as e:
            logger.error(f"自主模式初始化失败: {e}")
            raise

    async def shutdown(self) -> None:
        """关闭自主模式管理器。刷新审计日志、清理检查点。"""
        if self._auditor:
            await self._auditor.stop()
        if self._checkpoint:
            await self._checkpoint.cleanup()
        logger.info("自主模式管理器已关闭")

    async def create_checkpoint(self, file_path: str, operation: str = "write") -> Optional[str]:
        """在文件操作前创建检查点。"""
        if not self._checkpoint:
            return None
        return await self._checkpoint.create(file_path, operation)

    async def record_audit(
        self,
        session_id: str,
        action: str,
        params: Dict[str, Any],
        decision: str,
        **kwargs: Any,
    ) -> None:
        """记录审计事件。"""
        if not self._auditor:
            return
        await self._auditor.record(session_id, action, params, decision, **kwargs)

    async def check_all(self, action: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """一站式安全检查（四层洋葱模型）。

        按顺序检查：硬底线 → 工作区边界 → 网络策略 → 资源限制
        任一层次拒绝则立即返回拒绝信息，不继续后续检查。

        Args:
            action: 操作类型（如 'execute_command', 'write_file' 等）
            params: 操作参数

        Returns:
            None 表示全部通过，dict 表示拒绝原因（含 denied_by 和 recoverable）
        """
        if not self.is_autonomous:
            return None

        # 第 1 层：硬底线
        if self._hard_deny:
            denial = self._hard_deny.check_all(action, params)
            if denial:
                return denial

        # 第 2 层：工作区边界（仅检查文件操作）
        path = str(params.get("path") or params.get("file") or params.get("target") or "")
        if path and self._workspace:
            denial = self._workspace.check_all(path)
            if denial:
                return denial

        # 第 3 层：网络策略（现在是异步调用）
        if self._network:
            denial = await self._network.check_all(params)
            if denial:
                return denial

        # 第 4 层：资源限制（超时/内存）
        if self._resource:
            denial = self._resource.check_task_timeout()
            if denial:
                return denial

        return None

    def get_summary(self) -> Dict[str, Any]:
        """获取自主模式配置摘要（不含密钥）。"""
        return {
            **self._config.get_effective_summary(),
            "initialized": self._initialized,
        }


# 全局单例
_manager: Optional[AutonomousModeManager] = None


def get_autonomous_manager() -> Optional[AutonomousModeManager]:
    """获取全局 AutonomousModeManager 实例。"""
    return _manager


def set_autonomous_manager(manager: AutonomousModeManager) -> None:
    """设置全局 AutonomousModeManager 实例。"""
    global _manager
    _manager = manager


def init_autonomous_mode() -> Optional[AutonomousModeManager]:
    """从环境变量初始化自主模式。返回 manager 或 None（未启用时）。"""
    config = AutonomousConfig.from_env()
    if not config.autonomous_mode:
        logger.info("自主运行模式未启用")
        return None

    manager = AutonomousModeManager(config)
    manager.initialize()
    set_autonomous_manager(manager)
    return manager

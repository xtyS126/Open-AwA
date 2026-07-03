# -*- coding: utf-8 -*-
"""
ACP (Agent Client Protocol) 模块初始化文件。

提供 ACP 子系统的公开 API 入口，统一对外暴露核心数据结构、异常类型、权限适配器、
托管客户端与服务接口。

各子模块对外部 `acp` SDK 的依赖通过 try/except 优雅降级：SDK 缺失时仍可正常
导入本模块，仅在实际调用 SDK 相关方法（如 run_turn / _open_conversation）时
抛 ACPConfigurationError("acp SDK not installed")。本文件对 client.py / service.py
的导入再次 try/except，确保即便它们内部初始化出错也不会阻塞核心符号的导出。

注意：本包命名为 `acp_host`，与外部 `acp` Python SDK 解耦，避免本地包遮蔽
外部 SDK 导致的 ImportError。
"""

# 使用相对导入避免与外部 `acp` SDK 同名冲突。
from .core import (
    ACPAgentConfig,
    ACPConfig,
    ACPConfigurationError,
    ACPErrors,
    ACPProtocolError,
    ACPSessionError,
    ACPTransportError,
    SuspendedPermission,
)

# 权限适配器：依赖 acp.schema 中的部分类型，但 permissions.py 内部已处理降级。
try:
    from .permissions import ACPPermissionAdapter
except ImportError:  # pragma: no cover - permissions.py 不应在 SDK 缺失时 ImportError
    ACPPermissionAdapter = None  # type: ignore[assignment]

# 托管客户端：client.py 内部 try/except 处理 acp SDK 缺失，可安全导入。
try:
    from .client import ACPHostedClient
except ImportError:  # pragma: no cover - client.py 不应在导入时 ImportError
    ACPHostedClient = None  # type: ignore[assignment]

# 服务层：service.py 内部 try/except 处理 acp SDK 缺失，可安全导入。
try:
    from .service import (
        ACPService,
        close_acp_service,
        get_acp_service,
        init_acp_service,
    )
except ImportError:  # pragma: no cover - service.py 不应在导入时 ImportError
    ACPService = None  # type: ignore[assignment]
    close_acp_service = None  # type: ignore[assignment]
    get_acp_service = None  # type: ignore[assignment]
    init_acp_service = None  # type: ignore[assignment]


__all__ = [
    # 异常层级
    "ACPErrors",
    "ACPConfigurationError",
    "ACPTransportError",
    "ACPProtocolError",
    "ACPSessionError",
    # 配置数据结构
    "ACPConfig",
    "ACPAgentConfig",
    # 权限数据结构
    "SuspendedPermission",
    # 权限适配器（Task 2）
    "ACPPermissionAdapter",
    # 托管客户端（Task 3）
    "ACPHostedClient",
    # 服务层（Task 5）
    "ACPService",
    "init_acp_service",
    "close_acp_service",
    "get_acp_service",
]

"""按运行会话根进程校验本地监听端口归属。"""

from __future__ import annotations

from typing import Callable, Iterable, Protocol

from loguru import logger

try:
    import psutil
except ImportError:  # pragma: no cover - 由无依赖环境走 fail-closed 分支
    psutil = None  # type: ignore[assignment]


class ProcessLike(Protocol):
    pid: int

    def children(self, *, recursive: bool) -> Iterable["ProcessLike"]: ...


ProcessFactory = Callable[[int], ProcessLike]
ConnectionsProvider = Callable[..., Iterable[object]]


def _connection_port(connection: object) -> int | None:
    address = getattr(connection, "laddr", None)
    if address is None:
        return None
    port = getattr(address, "port", None)
    if port is None and isinstance(address, tuple) and len(address) >= 2:
        port = address[1]
    return port if isinstance(port, int) else None


def process_tree_owns_listener(
    *,
    root_pid: int,
    port: int,
    process_factory: ProcessFactory | None = None,
    connections_provider: ConnectionsProvider | None = None,
) -> bool:
    """只在端口由根进程或其后代监听时返回真，探测异常一律拒绝。"""
    if root_pid <= 0 or not 1 <= port <= 65535 or psutil is None:
        return False
    factory = process_factory or psutil.Process
    provider = connections_provider or psutil.net_connections
    try:
        root = factory(root_pid)
        allowed_pids = {int(root.pid)}
        allowed_pids.update(int(child.pid) for child in root.children(recursive=True))
        listen_status = str(getattr(psutil, "CONN_LISTEN", "LISTEN")).upper()
        for connection in provider(kind="inet"):
            status = str(getattr(connection, "status", "")).upper()
            if status not in {"LISTEN", listen_status}:
                continue
            if getattr(connection, "pid", None) not in allowed_pids:
                continue
            if _connection_port(connection) == port:
                return True
        return False
    except Exception as error:
        logger.bind(
            event="workbench_listener_ownership_check_failed",
            root_pid=root_pid,
            port=port,
            error_type=type(error).__name__,
        ).warning("工作台 listener 归属校验失败，已拒绝预览")
        return False

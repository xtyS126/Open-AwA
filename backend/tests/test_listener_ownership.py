from __future__ import annotations

import importlib
import importlib.util
from types import SimpleNamespace


class FakeProcess:
    def __init__(self, pid: int, child_pids: tuple[int, ...]) -> None:
        self.pid = pid
        self._child_pids = child_pids

    def children(self, *, recursive: bool) -> list[SimpleNamespace]:
        assert recursive is True
        return [SimpleNamespace(pid=pid) for pid in self._child_pids]


def test_listener_must_belong_to_root_or_descendant_process() -> None:
    spec = importlib.util.find_spec("workbench.listener_ownership")
    assert spec is not None, "listener 进程树归属模块尚未实现"
    module = importlib.import_module("workbench.listener_ownership")
    connections = [
        SimpleNamespace(pid=101, status="LISTEN", laddr=SimpleNamespace(port=3000)),
        SimpleNamespace(pid=999, status="LISTEN", laddr=SimpleNamespace(port=4000)),
    ]

    assert module.process_tree_owns_listener(
        root_pid=100,
        port=3000,
        process_factory=lambda pid: FakeProcess(pid, (101, 102)),
        connections_provider=lambda *, kind: connections,
    ) is True
    assert module.process_tree_owns_listener(
        root_pid=100,
        port=4000,
        process_factory=lambda pid: FakeProcess(pid, (101, 102)),
        connections_provider=lambda *, kind: connections,
    ) is False


def test_listener_check_fails_closed_when_process_or_connection_scan_fails() -> None:
    spec = importlib.util.find_spec("workbench.listener_ownership")
    assert spec is not None, "listener 进程树归属模块尚未实现"
    module = importlib.import_module("workbench.listener_ownership")

    def raise_error(*_args, **_kwargs):
        raise PermissionError("denied")

    assert module.process_tree_owns_listener(
        root_pid=100,
        port=3000,
        process_factory=raise_error,
        connections_provider=lambda *, kind: (),
    ) is False
    assert module.process_tree_owns_listener(
        root_pid=100,
        port=3000,
        process_factory=lambda pid: FakeProcess(pid, ()),
        connections_provider=raise_error,
    ) is False

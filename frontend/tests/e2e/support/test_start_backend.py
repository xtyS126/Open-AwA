"""Playwright 隔离后端启动器的端口契约测试。"""

from __future__ import annotations

import os

from frontend.tests.e2e.support import start_backend


def test_configure_environment_exports_effective_backend_port(
    monkeypatch,
    tmp_path,
) -> None:
    """隔离端口必须同步给后端内部健康检查使用。"""
    monkeypatch.setenv("OPENAWA_E2E_BACKEND_PORT", "19001")
    monkeypatch.delenv("BACKEND_PORT", raising=False)
    monkeypatch.delenv("PORT", raising=False)

    effective_port = start_backend._configure_environment(tmp_path)

    assert effective_port == 19001
    assert os.environ["BACKEND_PORT"] == "19001"

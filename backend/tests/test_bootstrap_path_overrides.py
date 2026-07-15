"""首次部署文件路径隔离配置测试。"""

import core.bootstrap as bootstrap_module


def test_bootstrap_paths_default_to_backend_directory(monkeypatch):
    """未设置覆盖变量时保持现有生产路径。"""
    monkeypatch.delenv("OPENAWA_ENV_LOCAL_PATH", raising=False)
    monkeypatch.delenv("OPENAWA_INIT_LOCK_PATH", raising=False)

    assert bootstrap_module._resolve_bootstrap_path(
        "OPENAWA_ENV_LOCAL_PATH",
        bootstrap_module.BACKEND_DIR / ".env.local",
    ) == bootstrap_module.BACKEND_DIR / ".env.local"
    assert bootstrap_module._resolve_bootstrap_path(
        "OPENAWA_INIT_LOCK_PATH",
        bootstrap_module.BACKEND_DIR / ".init.lock",
    ) == bootstrap_module.BACKEND_DIR / ".init.lock"


def test_bootstrap_paths_support_isolated_overrides(monkeypatch, tmp_path):
    """显式覆盖时所有初始化写入可定向到临时目录。"""
    env_path = tmp_path / "config" / ".env.local"
    lock_path = tmp_path / "locks" / ".init.lock"
    monkeypatch.setenv("OPENAWA_ENV_LOCAL_PATH", str(env_path))
    monkeypatch.setenv("OPENAWA_INIT_LOCK_PATH", str(lock_path))

    assert bootstrap_module._resolve_bootstrap_path(
        "OPENAWA_ENV_LOCAL_PATH",
        bootstrap_module.BACKEND_DIR / ".env.local",
    ) == env_path
    assert bootstrap_module._resolve_bootstrap_path(
        "OPENAWA_INIT_LOCK_PATH",
        bootstrap_module.BACKEND_DIR / ".init.lock",
    ) == lock_path

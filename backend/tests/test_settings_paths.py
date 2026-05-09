"""
配置路径回归测试，确保默认数据库地址不再依赖当前工作目录。
"""

import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import Settings, build_default_database_url, preload_environment_variables


def test_build_default_database_url_points_to_backend_db():
    """
    默认数据库地址应稳定指向 backend/openawa.db，避免从仓库根目录启动时连到空库。
    """
    expected_path = (Path(__file__).resolve().parents[1] / "openawa.db").resolve()
    expected_url = f"sqlite:///{expected_path.as_posix()}"
    assert build_default_database_url() == expected_url


def test_settings_ignore_unrelated_env_entries(tmp_path: Path, monkeypatch):
    """
    设置加载应忽略 `.env` 中与 Settings 无关的字段，避免本地用户密码变量打断启动。
    """
    # 清除可能已存在的同名环境变量，确保 dotenv 文件的值被读取
    for key in ("OPENAWA_ADMIN_PASSWORD", "LOG_LEVEL"):
        monkeypatch.delenv(key, raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENAWA_ADMIN_PASSWORD=admin123\nLOG_LEVEL=DEBUG\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.LOG_LEVEL == "DEBUG"
    # 确认与 Settings 无关的字段不会导致加载失败


def test_preload_environment_variables_supports_legacy_getenv_paths(tmp_path: Path, monkeypatch):
    """
    预加载环境文件后，仍依赖 os.getenv 的旧路径也应读取到相同配置。
    """
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    repo_env = tmp_path / ".env"
    backend_env_local = backend_dir / ".env.local"

    repo_env.write_text("LOG_LEVEL=WARNING\nSHARED_FLAG=repo\n", encoding="utf-8")
    backend_env_local.write_text("LOG_LEVEL=DEBUG\nLOCAL_FLAG=backend\n", encoding="utf-8")

    for key in ("LOG_LEVEL", "SHARED_FLAG", "LOCAL_FLAG"):
        monkeypatch.delenv(key, raising=False)

    loaded_files = preload_environment_variables((backend_env_local, repo_env))

    assert loaded_files == (backend_env_local.resolve(), repo_env.resolve())
    assert os.getenv("LOG_LEVEL") == "DEBUG"
    assert os.getenv("SHARED_FLAG") == "repo"
    assert os.getenv("LOCAL_FLAG") == "backend"


def test_settings_rejects_missing_secret_key_in_production_env_file(tmp_path: Path, monkeypatch):
    """
    生产环境配置文件缺少 SECRET_KEY 时，应在 Settings 初始化阶段直接失败。
    """
    for key in ("ENVIRONMENT", "SECRET_KEY"):
        monkeypatch.delenv(key, raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text("ENVIRONMENT=production\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="SECRET_KEY environment variable is required in production environment"):
        Settings(_env_file=env_file)

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


def test_settings_generates_secret_keys_in_production_when_missing(tmp_path: Path, monkeypatch):
    """
    生产环境配置文件缺少 JWT_SECRET_KEY / CSRF_SECRET_KEY / ENCRYPTION_KEY 时，
    应分别自动生成一次性随机密钥保证服务可启动，并各自独立记录 CRITICAL 日志警告
    （遵循 AGENTS.md「自动生成」语义与三密钥独立校验策略）。
    生成的密钥长度应 >= 32 字符。
    """
    # loguru 在导入时已捕获原始 sys.stderr，capsys 无法拦截；
    # 改用 loguru 推荐的 sink 捕获模式（注册临时 handler 收集日志记录）。
    from loguru import logger

    captured_records: list[str] = []
    sink_id = logger.add(
        lambda message: captured_records.append(message.record["message"]),
        level="CRITICAL",
    )

    try:
        # 清除所有可能影响测试的密钥环境变量，确保三个新密钥都未配置
        for key in (
            "ENVIRONMENT",
            "JWT_SECRET_KEY",
            "CSRF_SECRET_KEY",
            "ENCRYPTION_KEY",
            "SECRET_KEY",  # 旧密钥环境变量也清除，避免历史残留影响
        ):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("ALLOW_AUTO_GENERATED_SECRETS", "true")

        env_file = tmp_path / ".env"
        env_file.write_text("ENVIRONMENT=production\n", encoding="utf-8")

        settings_instance = Settings(_env_file=env_file)
    finally:
        logger.remove(sink_id)

    # 三个新密钥各自应生成随机值，长度 >= 32
    assert len(settings_instance.JWT_SECRET_KEY) >= 32
    assert len(settings_instance.CSRF_SECRET_KEY) >= 32
    assert len(settings_instance.ENCRYPTION_KEY) >= 32

    # 应各自独立记录 CRITICAL 警告，包含对应密钥名称与提示语
    joined = "\n".join(captured_records)
    assert "JWT_SECRET_KEY" in joined
    assert "CSRF_SECRET_KEY" in joined
    assert "ENCRYPTION_KEY" in joined
    assert "一次性随机密钥" in joined

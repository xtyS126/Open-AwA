"""
配置路径回归测试，确保默认数据库地址不再依赖当前工作目录。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import build_default_database_url


def test_build_default_database_url_points_to_backend_db():
    """
    默认数据库地址应稳定指向 backend/openawa.db，避免从仓库根目录启动时连到空库。
    """
    expected_path = (Path(__file__).resolve().parents[1] / "openawa.db").resolve()
    expected_url = f"sqlite:///{expected_path.as_posix()}"
    assert build_default_database_url() == expected_url

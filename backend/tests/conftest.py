"""
pytest 全局配置：测试启动前设置测试专用环境变量，禁用 CSRF 校验等安全中间件。
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# 测试专用环境变量名，避免与通用 TESTING 变量冲突
_CSRF_TEST_ENV = "SKIP_CSRF_FOR_TEST"
_TEST_DATABASE_PATH = Path(tempfile.gettempdir()) / f"openawa-pytest-{os.getpid()}.db"
_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def pytest_configure(config):
    """在所有测试收集/运行之前设置测试用环境变量，仅影响 pytest 进程。"""
    os.environ.setdefault(_CSRF_TEST_ENV, "true")
    os.environ.setdefault("TESTING", "true")
    # 全局 app 的 lifespan 会直接使用模块级数据库引擎，必须在收集测试模块前隔离默认数据库
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DATABASE_PATH.as_posix()}")
    # ACP 路由测试只允许后端测试工作区，不放宽生产环境的默认白名单
    os.environ.setdefault("ACP_ALLOWED_WORKDIRS", str(_BACKEND_ROOT))


def pytest_runtest_setup(item):
    """每个用例设置 fixture 前清空全局 FastAPI 依赖覆盖，阻断跨用例认证污染。"""
    main_module = sys.modules.get("main")
    app = getattr(main_module, "app", None) if main_module is not None else None
    if app is not None:
        app.dependency_overrides.clear()

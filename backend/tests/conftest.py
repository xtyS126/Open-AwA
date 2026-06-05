"""
pytest 全局配置：测试启动前设置测试专用环境变量，禁用 CSRF 校验等安全中间件。
"""

import os

import pytest

# 测试专用环境变量名，避免与通用 TESTING 变量冲突
_CSRF_TEST_ENV = "SKIP_CSRF_FOR_TEST"


def pytest_configure(config):
    """在所有测试收集/运行之前设置测试用环境变量，仅影响 pytest 进程。"""
    os.environ.setdefault(_CSRF_TEST_ENV, "true")

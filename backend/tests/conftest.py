"""
pytest 全局配置：测试启动前设置 TESTING 环境变量，禁用 CSRF 校验。
"""

import os

import pytest


def pytest_configure(config):
    """在所有测试收集/运行之前设置 TESTING 环境变量。"""
    os.environ.setdefault("TESTING", "true")

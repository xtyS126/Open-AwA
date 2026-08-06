"""
局域网 APK 分发页单元测试。

覆盖：
- 分发页返回 200 且包含下载按钮与版本信息
- 样式文件以 text/css 返回（CSP style-src 'self' 同源外链）
- APK 存在时下载返回 application/vnd.android.package-archive
- APK 不存在时下载返回 404 且提示打包
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app

# 指向任意存在的本地文件模拟 APK 产物（测试不依赖真实构建产物）
_FAKE_APK = Path(__file__).resolve().parent / "test_apk_dist.py"


@pytest.fixture
def client():
    """创建 TestClient，不触发 lifespan。"""
    return TestClient(app)


def test_dist_page_renders(client):
    """分发页包含下载按钮与后端版本"""
    resp = client.get("/apk")
    assert resp.status_code == 200
    assert "下载并安装" in resp.text
    assert "Open-AwA" in resp.text


def test_dist_css_served(client):
    """样式文件以 text/css 外链提供，满足 CSP 同源要求"""
    resp = client.get("/apk/dist.css")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/css")
    assert ".download-btn" in resp.text


def test_download_serves_apk(client):
    """APK 存在时以安卓安装包 MIME 下载"""
    with patch("api.routes.apk_dist._APK_PATH", _FAKE_APK):
        resp = client.get("/apk/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/vnd.android.package-archive"
    assert "Open-AwA.apk" in resp.headers.get("content-disposition", "")


def test_download_missing_apk_returns_404(client):
    """APK 未打包时返回 404 与引导文案"""
    with patch("api.routes.apk_dist._APK_PATH", Path("C:/nonexistent/app-debug.apk")):
        resp = client.get("/apk/download")
    assert resp.status_code == 404
    assert "安装包不存在" in resp.text

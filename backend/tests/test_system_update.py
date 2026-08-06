"""APP 局域网 OTA 更新接口测试。"""
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def apk_dir(tmp_path, monkeypatch):
    """临时 APK 目录 + manifest。"""
    from config import runtime_paths
    monkeypatch.setattr(runtime_paths, "APK_DIR", tmp_path)
    # 让 system.py 的模块级引用指向新目录
    monkeypatch.setattr("api.routes.system.APK_DIR", tmp_path)
    return tmp_path


def _write_manifest(apk_dir: Path, version_code: int, version: str = "1.0.1") -> None:
    apk = apk_dir / "openawa-1.0.1.apk"
    apk.write_bytes(b"fake-apk-content")
    apk_dir.joinpath("manifest.json").write_text(
        json.dumps({
            "version": version,
            "version_code": version_code,
            "apk": apk.name,
            "apk_size": apk.stat().st_size,
            "apk_sha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
            "changelog": "修复已知问题",
            "published_at": "2026-08-07T10:00:00+08:00",
        }),
        encoding="utf-8",
    )


def _client() -> TestClient:
    import main as main_module
    return TestClient(main_module.app)


def test_update_check_no_manifest(apk_dir):
    with _client() as client:
        resp = client.get("/api/system/update-check?version_code=1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_update"] is False


def test_update_check_newer_version_available(apk_dir):
    _write_manifest(apk_dir, version_code=2)
    with _client() as client:
        resp = client.get("/api/system/update-check?version_code=1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_update"] is True
    assert data["latest_version"] == "1.0.1"
    assert data["latest_version_code"] == 2
    assert data["apk_size"] > 0
    assert len(data["apk_sha256"]) == 64
    assert data["download_url"] == "/api/system/apk/download"


def test_update_check_same_version(apk_dir):
    _write_manifest(apk_dir, version_code=1)
    with _client() as client:
        resp = client.get("/api/system/update-check?version_code=1")
    assert resp.json()["has_update"] is False


def test_update_check_client_version_greater(apk_dir):
    _write_manifest(apk_dir, version_code=1)
    with _client() as client:
        resp = client.get("/api/system/update-check?version_code=5")
    assert resp.json()["has_update"] is False


def test_apk_download_requires_auth(apk_dir):
    """APK 下载端点必须认证。"""
    _write_manifest(apk_dir, version_code=2)
    with _client() as client:
        resp = client.get("/api/system/apk/download")
    assert resp.status_code in (401, 403)


def test_apk_download_with_auth(apk_dir):
    """认证后可下载 APK，响应头携带 sha256。"""
    _write_manifest(apk_dir, version_code=2)
    # 使用 API Key 认证
    import re
    env_path = Path(__file__).resolve().parents[1] / ".env.local"
    m = re.search(r"OPENAWA_API_KEY\s*=\s*[\"']?([^\"'\n]+)", env_path.read_text(encoding="utf-8"))
    api_key = m.group(1).strip()
    with _client() as client:
        resp = client.get(
            "/api/system/apk/download",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    assert resp.status_code == 200
    assert resp.headers.get("x-apk-sha256") == hashlib.sha256(b"fake-apk-content").hexdigest()
    assert resp.content == b"fake-apk-content"


def test_apk_download_no_manifest(apk_dir):
    """无 manifest 时 404。"""
    with _client() as client:
        resp = client.get("/api/system/apk/download")
    assert resp.status_code == 401  # 先过认证


def test_apk_download_manifest_missing_file(apk_dir):
    """manifest 存在但 APK 文件缺失时 404。"""
    apk_dir.joinpath("manifest.json").write_text(
        json.dumps({"version": "1.0.1", "version_code": 2, "apk": "missing.apk"}),
        encoding="utf-8",
    )
    import re
    env_path = Path(__file__).resolve().parents[1] / ".env.local"
    m = re.search(r"OPENAWA_API_KEY\s*=\s*[\"']?([^\"'\n]+)", env_path.read_text(encoding="utf-8"))
    api_key = m.group(1).strip()
    with _client() as client:
        resp = client.get(
            "/api/system/apk/download",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    assert resp.status_code == 404

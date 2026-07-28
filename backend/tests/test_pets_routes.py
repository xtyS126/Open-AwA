"""
宠物导入路由测试。

验证 /api/pets/import 能正确导入 Codex V1/V2 自定义宠物精灵表，
覆盖完整生命周期、非法清单与权限校验。
"""

import io
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_current_user, get_db
from db.models import Base
from main import app
from pets import asset_pack, catalog

# 内存数据库，所有测试共享同一连接
_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
Base.metadata.create_all(bind=_engine)


def override_get_db():
    """返回测试用数据库会话"""
    db = _TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


class DummyUser:
    """模拟已登录用户，供依赖注入使用"""

    id = "user-1"
    username = "testuser"
    role = "user"


def override_get_current_user():
    """返回固定的模拟用户"""
    return DummyUser()


@pytest.fixture
def client(tmp_path, monkeypatch):
    """构造临时存储目录与鉴权覆盖的 TestClient"""
    monkeypatch.setattr(asset_pack, "PETS_DATA_DIR", tmp_path)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    yield TestClient(app)
    app.dependency_overrides.clear()


def _png_bytes(width, height):
    """用 Pillow 生成纯色 PNG 字节流"""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), (64, 96, 128)).save(buf, format="PNG")
    return buf.getvalue()


def _import_two_files(client, manifest, sprite_bytes, sprite_name="spritesheet.png"):
    """以 pet.json + 精灵表两文件方式提交导入"""
    return client.post(
        "/api/pets/import",
        files={
            "manifest_file": ("pet.json", json.dumps(manifest, ensure_ascii=False).encode("utf-8"), "application/json"),
            "spritesheet_file": (sprite_name, sprite_bytes, "image/png"),
        },
    )


_V2_MANIFEST = {
    "id": "my-v2-pet",
    "displayName": "测试 V2 宠物",
    "description": "V2 合成宠物",
    "spriteVersionNumber": 2,
    "frame": {"width": 192, "height": 208, "columns": 8, "rows": 11},
}


def test_import_v2_custom_pet_full_cycle(client):
    """完整流程：导入 V2 宠物并验证记录、激活与禁用"""
    sprite_bytes = _png_bytes(catalog.SPRITESHEET_WIDTH, catalog.SPRITESHEET_HEIGHT_V2)
    resp = _import_two_files(client, _V2_MANIFEST, sprite_bytes)
    assert resp.status_code == 200, resp.text
    pet = resp.json()["pet"]
    assert pet["pet_id"] == "my-v2-pet"
    assert pet["display_name"] == "测试 V2 宠物"
    assert pet["sprite_version"] == 2
    assert pet["frame_count"] == 8 * 11
    assert pet["is_builtin"] is False
    assert pet["spritesheet_ready"] is True
    record_id = pet["id"]
    assert record_id == "custom:user-1:my-v2-pet"

    # 验证列表与默认未激活
    listing = client.get("/api/pets")
    assert listing.status_code == 200
    imported = next(p for p in listing.json()["pets"] if p["pet_id"] == "my-v2-pet")
    assert imported["id"] == record_id
    assert imported["is_active"] is False

    # 验证精灵表可取回
    sprite = client.get(f"/api/pets/{record_id}/spritesheet")
    assert sprite.status_code == 200
    assert sprite.headers["content-type"] == "image/png"
    assert len(sprite.content) > 0
    # 验证清单结构属于 V2 契约
    manifest_resp = client.get(f"/api/pets/{record_id}/manifest")
    assert manifest_resp.status_code == 200
    assert manifest_resp.json()["frame"]["rows"] == 11

    # 激活宠物
    active = client.put("/api/pets/active", json={"pet_id": record_id})
    assert active.status_code == 200
    assert active.json()["pet_id"] == record_id

    # 列表中应反映激活态
    imported_after = next(p for p in client.get("/api/pets").json()["pets"] if p["pet_id"] == "my-v2-pet")
    assert imported_after["is_active"] is True

    # 查询当前激活
    cur = client.get("/api/pets/active")
    assert cur.status_code == 200
    assert cur.json()["pet_id"] == record_id

    # 关闭宠物
    disabled = client.put("/api/pets/active", json={"pet_id": "disable"})
    assert disabled.status_code == 200
    assert disabled.json()["pet_id"] is None


def test_import_v1_custom_pet(client):
    """导入 V1（1536x1872，9 行）宠物"""
    v1_manifest = {
        "id": "my-v1-pet",
        "displayName": "测试 V1 宠物",
        "description": "V1 合成宠物",
        "spriteVersionNumber": 1,
        "frame": {"width": 192, "height": 208, "columns": 8, "rows": 9},
    }
    sprite_bytes = _png_bytes(catalog.SPRITESHEET_WIDTH, catalog.SPRITESHEET_HEIGHT_V1)
    resp = _import_two_files(client, v1_manifest, sprite_bytes)
    assert resp.status_code == 200, resp.text
    pet = resp.json()["pet"]
    assert pet["pet_id"] == "my-v1-pet"
    assert pet["sprite_version"] == 1
    assert pet["frame_count"] == 8 * 9


def test_import_rejects_wrong_dimensions(client):
    """V2 清单但精灵表尺寸不符应返回 400"""
    bad_sprite = _png_bytes(catalog.SPRITESHEET_WIDTH, catalog.SPRITESHEET_HEIGHT_V1)
    resp = _import_two_files(client, _V2_MANIFEST, bad_sprite)
    assert resp.status_code == 400
    assert "pet" not in resp.json()


def test_import_rejects_missing_files(client):
    """缺少 pet.json 应返回 400"""
    sprite_bytes = _png_bytes(catalog.SPRITESHEET_WIDTH, catalog.SPRITESHEET_HEIGHT_V2)
    resp = client.post(
        "/api/pets/import",
        files={"spritesheet_file": ("spritesheet.png", sprite_bytes, "image/png")},
    )
    assert resp.status_code == 400


def test_import_replaces_existing_custom_pet(client):
    """相同 pet_id 再次导入应替换更新"""
    sprite_bytes = _png_bytes(catalog.SPRITESHEET_WIDTH, catalog.SPRITESHEET_HEIGHT_V2)
    first = _import_two_files(client, _V2_MANIFEST, sprite_bytes)
    assert first.status_code == 200
    updated_manifest = dict(_V2_MANIFEST)
    updated_manifest["displayName"] = "更新后的宠物"
    updated_manifest["description"] = "已更新"
    second = _import_two_files(client, updated_manifest, sprite_bytes)
    assert second.status_code == 200
    pet = second.json()["pet"]
    assert pet["display_name"] == "更新后的宠物"
    assert pet["description"] == "已更新"
    # 替换后仍应只有一个该 pet_id 记录
    pets = [p for p in client.get("/api/pets").json()["pets"] if p["pet_id"] == "my-v2-pet"]
    assert len(pets) == 1


def test_delete_custom_pet_removes_record_and_disk(client):
    """删除自定义宠物同步清理记录与磁盘"""
    import pets.asset_pack as ap

    sprite_bytes = _png_bytes(catalog.SPRITESHEET_WIDTH, catalog.SPRITESHEET_HEIGHT_V2)
    _import_two_files(client, _V2_MANIFEST, sprite_bytes)
    record_id = "custom:user-1:my-v2-pet"
    disk_dir = ap.custom_pet_dir(DummyUser.id, "my-v2-pet")
    assert disk_dir.exists()

    dele = client.delete(f"/api/pets/{record_id}")
    assert dele.status_code == 200
    assert dele.json()["success"] is True

    listing = client.get("/api/pets").json()["pets"]
    assert not any(p["pet_id"] == "my-v2-pet" for p in listing)
    # 删除后磁盘目录应消失
    assert not disk_dir.exists()


def test_pets_endpoints_require_authentication():
    """未登录访问宠物接口应返回 401"""
    app.dependency_overrides.clear()
    client = TestClient(app)
    assert client.get("/api/pets").status_code == 401
    sprite = _png_bytes(catalog.SPRITESHEET_WIDTH, catalog.SPRITESHEET_HEIGHT_V2)
    resp = client.post(
        "/api/pets/import",
        files={
            "manifest_file": ("pet.json", json.dumps(_V2_MANIFEST).encode("utf-8"), "application/json"),
            "spritesheet_file": ("spritesheet.png", sprite, "image/png"),
        },
    )
    assert resp.status_code == 401
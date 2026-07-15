"""
????????????????

?? /api/pets/import ????? Codex V1/V2 ???????????
??????????????????????????????????
????????????????????????
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

# ?????????????????????????
_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
Base.metadata.create_all(bind=_engine)


def override_get_db():
    """????????????"""
    db = _TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


class DummyUser:
    """????????????????????"""

    id = "user-1"
    username = "testuser"
    role = "user"


def override_get_current_user():
    """??????????????????"""
    return DummyUser()


@pytest.fixture
def client(tmp_path, monkeypatch):
    """????????????????? TestClient?"""
    monkeypatch.setattr(asset_pack, "PETS_DATA_DIR", tmp_path)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    yield TestClient(app)
    app.dependency_overrides.clear()


def _png_bytes(width, height):
    """? Pillow ??????? PNG ?????????????"""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), (64, 96, 128)).save(buf, format="PNG")
    return buf.getvalue()


def _import_two_files(client, manifest, sprite_bytes, sprite_name="spritesheet.png"):
    """? pet.json ????????????????"""
    return client.post(
        "/api/pets/import",
        files={
            "manifest_file": ("pet.json", json.dumps(manifest, ensure_ascii=False).encode("utf-8"), "application/json"),
            "spritesheet_file": (sprite_name, sprite_bytes, "image/png"),
        },
    )


_V2_MANIFEST = {
    "id": "my-v2-pet",
    "displayName": "?? V2 ??",
    "description": "????????",
    "spriteVersionNumber": 2,
    "frame": {"width": 192, "height": 208, "columns": 8, "rows": 11},
}


def test_import_v2_custom_pet_full_cycle(client):
    """?????? V2 ??????????????????"""
    sprite_bytes = _png_bytes(catalog.SPRITESHEET_WIDTH, catalog.SPRITESHEET_HEIGHT_V2)
    resp = _import_two_files(client, _V2_MANIFEST, sprite_bytes)
    assert resp.status_code == 200, resp.text
    pet = resp.json()["pet"]
    assert pet["pet_id"] == "my-v2-pet"
    assert pet["display_name"] == "?? V2 ??"
    assert pet["sprite_version"] == 2
    assert pet["frame_count"] == 8 * 11
    assert pet["is_builtin"] is False
    assert pet["spritesheet_ready"] is True
    record_id = pet["id"]
    assert record_id == "custom:user-1:my-v2-pet"

    # ?????????????????
    listing = client.get("/api/pets")
    assert listing.status_code == 200
    imported = next(p for p in listing.json()["pets"] if p["pet_id"] == "my-v2-pet")
    assert imported["id"] == record_id
    assert imported["is_active"] is False

    # ?????????????
    sprite = client.get(f"/api/pets/{record_id}/spritesheet")
    assert sprite.status_code == 200
    assert sprite.headers["content-type"] == "image/png"
    assert len(sprite.content) > 0
    # ??????? V2 ????????
    manifest_resp = client.get(f"/api/pets/{record_id}/manifest")
    assert manifest_resp.status_code == 200
    assert manifest_resp.json()["frame"]["rows"] == 11

    # ?????
    active = client.put("/api/pets/active", json={"pet_id": record_id})
    assert active.status_code == 200
    assert active.json()["pet_id"] == record_id

    # ??????????
    imported_after = next(p for p in client.get("/api/pets").json()["pets"] if p["pet_id"] == "my-v2-pet")
    assert imported_after["is_active"] is True

    # ?????
    cur = client.get("/api/pets/active")
    assert cur.status_code == 200
    assert cur.json()["pet_id"] == record_id

    # ?????
    disabled = client.put("/api/pets/active", json={"pet_id": "disable"})
    assert disabled.status_code == 200
    assert disabled.json()["pet_id"] is None


def test_import_v1_custom_pet(client):
    """?? V1?1536x1872?9 ???????"""
    v1_manifest = {
        "id": "my-v1-pet",
        "displayName": "?? V1 ??",
        "description": "V1 ????",
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
    """V2 manifest ???????????????? 400?"""
    bad_sprite = _png_bytes(catalog.SPRITESHEET_WIDTH, catalog.SPRITESHEET_HEIGHT_V1)
    resp = _import_two_files(client, _V2_MANIFEST, bad_sprite)
    assert resp.status_code == 400
    assert "pet" not in resp.json()


def test_import_rejects_missing_files(client):
    """??????? pet.json ??? 400?"""
    sprite_bytes = _png_bytes(catalog.SPRITESHEET_WIDTH, catalog.SPRITESHEET_HEIGHT_V2)
    resp = client.post(
        "/api/pets/import",
        files={"spritesheet_file": ("spritesheet.png", sprite_bytes, "image/png")},
    )
    assert resp.status_code == 400


def test_import_replaces_existing_custom_pet(client):
    """?????? pet_id ????????"""
    sprite_bytes = _png_bytes(catalog.SPRITESHEET_WIDTH, catalog.SPRITESHEET_HEIGHT_V2)
    first = _import_two_files(client, _V2_MANIFEST, sprite_bytes)
    assert first.status_code == 200
    updated_manifest = dict(_V2_MANIFEST)
    updated_manifest["displayName"] = "??????"
    updated_manifest["description"] = "????"
    second = _import_two_files(client, updated_manifest, sprite_bytes)
    assert second.status_code == 200
    pet = second.json()["pet"]
    assert pet["display_name"] == "??????"
    assert pet["description"] == "????"
    # ??????????? pet_id ??
    pets = [p for p in client.get("/api/pets").json()["pets"] if p["pet_id"] == "my-v2-pet"]
    assert len(pets) == 1


def test_delete_custom_pet_removes_record_and_disk(client):
    """??????????????????????"""
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
    # ??????????
    assert not disk_dir.exists()


def test_pets_endpoints_require_authentication():
    """??????????????????? 401?"""
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

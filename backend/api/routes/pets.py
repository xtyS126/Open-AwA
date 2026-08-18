"""
宠物功能路由：列表、导入自定义宠物、删除、激活、精灵表与清单下载。

设计要点：
- 内置宠物在启动时由 seed_builtin_pets 写入 pets 表（user_id 为空、is_builtin=True），
  精灵表首次请求时按需从 Codex 官方 CDN 下载并缓存。
- 自定义宠物完全由用户持有，落盘在 var/pets/custom/<user_id>/<pet_id>/，
  清单与精灵表均校验 V2 宠物契约后再持久化。
- 激活态通过 user_active_pets 单行映射维护；pet_id=disable 表示禁用宠物。
- Live2D 模型路由：上传、列表、文件读取、删除。
"""

import io
import json
import os
import re
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from api.schemas import (
    Live2DModelListResponse,
    Live2DModelResponse,
    Live2DModelUploadResponse,
    PetActiveRequest,
    PetActiveResponse,
    PetImportResponse,
    PetListResponse,
    PetResponse,
)
from db.models import Live2DModel, Pet, User, UserActivePet, get_db
from pets import catalog, manifest, asset_pack
from pets.live2d import LIVED2D_DATA_DIR, MAX_MODEL_ARCHIVE_BYTES
from pets.live2d.validator import Live2DValidationError, validate_live2d_archive

router = APIRouter(prefix="/pets", tags=["Pets"])

# 自定义宠物 slug 校验：小写字母数字、连字符、下划线，1-64 字符
PET_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9\-_]{0,63}$")
MAX_MANIFEST_BYTES = 256 * 1024  # pet.json 上限 256KB
MAX_SPRITESHEET_BYTES = 8 * 1024 * 1024  # 精灵表上限 8MB
SPRITESHEET_EXTS = {".webp", ".png", ".gif"}
EXT_MEDIA_TYPES = {".webp": "image/webp", ".png": "image/png", ".gif": "image/gif"}


def _builtin_record_id(pet_id: str) -> str:
    """内置宠物记录 id 形如 builtin:codex。"""
    return f"builtin:{pet_id}"


def _custom_record_id(user_id: str, pet_id: str) -> str:
    """自定义宠物记录 id 形如 custom:<user_id>:<pet_id>。"""
    return f"custom:{user_id}:{pet_id}"


def _resolve_spritesheet_path(pet: Pet) -> Path:
    """解析精灵表绝对路径，兼容绝对与相对存储。"""
    stored = Path(pet.spritesheet_path)
    if stored.is_absolute():
        return stored
    return asset_pack.PETS_DATA_DIR / pet.spritesheet_path


def _pet_to_response(pet: Pet, is_active: bool) -> PetResponse:
    """将 ORM 行转换为响应模型。"""
    return PetResponse(
        id=pet.id,
        pet_id=pet.pet_id,
        display_name=pet.display_name,
        description=pet.description,
        sprite_version=pet.sprite_version,
        frame_width=pet.frame_width,
        frame_height=pet.frame_height,
        columns=pet.columns,
        rows=pet.rows,
        frame_count=pet.frame_count,
        animations=pet.animations or {},
        is_builtin=pet.is_builtin,
        spritesheet_ready=pet.spritesheet_ready,
        is_active=is_active,
        created_at=pet.created_at,
    )


def seed_builtin_pets(db: Session) -> int:
    """幂等写入 8 个内置宠物记录，返回新增数量。"""
    inserted = 0
    for builtin in catalog.BUILTIN_PETS:
        record_id = _builtin_record_id(builtin.id)
        existing = db.get(Pet, record_id)
        if existing is not None:
            # 元数据可能随目录升级变化，同步更新显示字段
            existing.display_name = builtin.display_name
            existing.description = builtin.description
            existing.frame_width = catalog.DEFAULT_FRAME_WIDTH
            existing.frame_height = catalog.DEFAULT_FRAME_HEIGHT
            existing.columns = catalog.DEFAULT_FRAME_COLUMNS
            existing.rows = catalog.DEFAULT_FRAME_ROWS
            # 内置宠物帧数 = 列数 * 行数（全网格使用），与 manifest.parse_manifest 默认行为一致
            existing.frame_count = catalog.DEFAULT_FRAME_COLUMNS * catalog.DEFAULT_FRAME_ROWS
            existing.sprite_version = 1
            existing.animations = manifest.default_animations()
            existing.spritesheet_path = str(asset_pack.builtin_spritesheet_path(builtin))
            existing.is_builtin = True
            continue
        db.add(
            Pet(
                id=record_id,
                user_id=None,
                pet_id=builtin.id,
                display_name=builtin.display_name,
                description=builtin.description,
                sprite_version=1,
                frame_width=catalog.DEFAULT_FRAME_WIDTH,
                frame_height=catalog.DEFAULT_FRAME_HEIGHT,
                columns=catalog.DEFAULT_FRAME_COLUMNS,
                rows=catalog.DEFAULT_FRAME_ROWS,
                frame_count=catalog.DEFAULT_FRAME_COLUMNS * catalog.DEFAULT_FRAME_ROWS,
                animations=manifest.default_animations(),
                spritesheet_path=str(asset_pack.builtin_spritesheet_path(builtin)),
                is_builtin=True,
                spritesheet_ready=False,
            )
        )
        inserted += 1
    db.commit()
    logger.bind(event="pets_seed_builtins", module="pets").info(
        f"seeded {inserted} new builtin pet records"
    )
    return inserted


@router.get("", response_model=PetListResponse)
def list_pets(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出内置宠物 + 当前用户的自定义宠物，标记每个宠物的激活态。"""
    active = db.execute(
        select(UserActivePet).where(UserActivePet.user_id == current_user.id)
    ).scalar_one_or_none()
    active_pet_id = active.pet_id if active else None

    rows = (
        db.query(Pet)
        .filter((Pet.user_id.is_(None)) | (Pet.user_id == current_user.id))
        .order_by(Pet.is_builtin.desc(), Pet.display_name.asc())
        .all()
    )
    pets = [_pet_to_response(row, is_active=(row.id == active_pet_id)) for row in rows]
    return PetListResponse(pets=pets, total=len(pets))


@router.get("/active", response_model=PetActiveResponse)
def get_active_pet(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回当前用户激活的宠物 id 与名称（未设置或禁用时为 null）。"""
    active = db.execute(
        select(UserActivePet).where(UserActivePet.user_id == current_user.id)
    ).scalar_one_or_none()
    if not active or active.pet_id == "disable":
        return PetActiveResponse(pet_id=None, display_name=None)
    pet = db.get(Pet, active.pet_id)
    if pet is None:
        return PetActiveResponse(pet_id=None, display_name=None)
    return PetActiveResponse(pet_id=pet.id, display_name=pet.display_name)


@router.put("/active", response_model=PetActiveResponse)
def set_active_pet(
    payload: PetActiveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """设置当前用户的激活宠物，pet_id=disable 表示禁用。"""
    target_id = payload.pet_id
    if target_id == "disable":
        existing = db.execute(
            select(UserActivePet).where(UserActivePet.user_id == current_user.id)
        ).scalar_one_or_none()
        if existing is not None:
            db.delete(existing)
            db.commit()
        return PetActiveResponse(pet_id=None, display_name=None)

    pet = db.get(Pet, target_id)
    if pet is None:
        raise HTTPException(status_code=404, detail="宠物不存在或无访问权限")
    # 仅允许用户使用内置或自己的自定义宠物
    if pet.user_id is not None and pet.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="宠物不存在或无访问权限")

    active = db.execute(
        select(UserActivePet).where(UserActivePet.user_id == current_user.id)
    ).scalar_one_or_none()
    if active is None:
        active = UserActivePet(user_id=current_user.id, pet_id=target_id)
        db.add(active)
    else:
        active.pet_id = target_id
        active.updated_at = datetime.now(timezone.utc)
    db.commit()
    return PetActiveResponse(pet_id=pet.id, display_name=pet.display_name)


def _read_upload_bytes(upload: UploadFile, max_bytes: int) -> bytes:
    """分块读取上传文件，超限即拒绝。"""
    buffer = bytearray()
    while True:
        chunk = upload.file.read(64 * 1024)
        if not chunk:
            break
        if isinstance(chunk, str):
            chunk = chunk.encode("utf-8")
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise HTTPException(status_code=413, detail=f"上传文件超过 {max_bytes} 字节上限")
    return bytes(buffer)


def _image_dimensions_from_bytes(data: bytes) -> Tuple[int, int]:
    """从内存字节读取像素尺寸，失败抛异常。"""
    try:
        from PIL import Image
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="服务端未安装 Pillow，无法校验精灵表") from exc
    try:
        with Image.open(io.BytesIO(data)) as image:
            return (image.width, image.height)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="精灵表不是合法图片文件") from exc


def _parse_manifest_bytes(data: bytes) -> Dict[str, Any]:
    """解析 pet.json 字节为字典。"""
    try:
        obj = json.loads(data.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="pet.json 不是合法 JSON") from exc
    if not isinstance(obj, dict):
        raise HTTPException(status_code=400, detail="pet.json 顶层必须是对象")
    return obj


def _extract_pet_from_archive(archive_bytes: bytes) -> Tuple[Dict[str, Any], bytes, str]:
    """从 zip 包中提取 pet.json 与精灵表，返回 (manifest, spritesheet_bytes, ext)。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="归档不是合法 zip 文件") from exc
    names = zf.namelist()
    manifest_name = next((n for n in names if n.endswith("pet.json") and not n.endswith("/")), None)
    if manifest_name is None:
        raise HTTPException(status_code=400, detail="归档中缺少 pet.json")
    sprite_name = next(
        (
            n
            for n in names
            if n.lower().endswith((".webp", ".png", ".gif")) and not n.endswith("/")
        ),
        None,
    )
    if sprite_name is None:
        raise HTTPException(status_code=400, detail="归档中缺少精灵表图片（webp/png/gif）")
    manifest_obj = _parse_manifest_bytes(zf.read(manifest_name))
    spritesheet_bytes = zf.read(sprite_name)
    ext = os.path.splitext(sprite_name)[1].lower()
    return manifest_obj, spritesheet_bytes, ext


def _normalize_pet_id(raw: str) -> str:
    """归一化宠物 slug：小写、仅允许 [a-z0-9-_]，防注入与路径穿越。"""
    candidate = (raw or "").strip().lower().replace(" ", "-")
    if not PET_ID_PATTERN.match(candidate):
        raise HTTPException(status_code=400, detail="宠物 id 仅支持小写字母数字、连字符与下划线，长度 1-64")
    if candidate in catalog.builtin_pet_ids():
        raise HTTPException(status_code=400, detail="宠物 id 与内置宠物冲突，请更换 id")
    return candidate


@router.post("/import", response_model=PetImportResponse)
async def import_custom_pet(
    manifest_file: Optional[UploadFile] = File(None),
    spritesheet_file: Optional[UploadFile] = File(None),
    archive: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导入自定义宠物：支持 (pet.json + 精灵表) 两文件或 zip 归档。"""
    if archive is not None and archive.filename:
        archive_bytes = _read_upload_bytes(archive, MAX_SPRITESHEET_BYTES)
        manifest_obj, sprite_bytes, ext = _extract_pet_from_archive(archive_bytes)
    else:
        if manifest_file is None or not manifest_file.filename:
            raise HTTPException(status_code=400, detail="请上传 pet.json 或包含它的 zip 归档")
        if spritesheet_file is None or not spritesheet_file.filename:
            raise HTTPException(status_code=400, detail="请上传精灵表图片或包含它的 zip 归档")
        manifest_obj = _parse_manifest_bytes(_read_upload_bytes(manifest_file, MAX_MANIFEST_BYTES))
        sprite_bytes = _read_upload_bytes(spritesheet_file, MAX_SPRITESHEET_BYTES)
        ext = os.path.splitext(spritesheet_file.filename)[1].lower()
        if ext not in SPRITESHEET_EXTS:
            raise HTTPException(status_code=400, detail="精灵表仅支持 webp/png/gif")

    actual_dims = _image_dimensions_from_bytes(sprite_bytes)
    raw_pet_id = str(manifest_obj.get("id") or manifest_obj.get("displayName") or "custom-pet")
    pet_id = _normalize_pet_id(raw_pet_id)
    record_id = _custom_record_id(current_user.id, pet_id)
    storage_dir = asset_pack.custom_pet_dir(current_user.id, pet_id)

    try:
        definition = manifest.parse_manifest(
            manifest=manifest_obj,
            pet_id_override=pet_id,
            spritesheet_actual_dims=actual_dims,
            pet_dir=storage_dir,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 校验精灵表像素尺寸与版本一致（V1: 1536x1872，V2: 1536x2288）
    try:
        asset_pack.validate_spritesheet_dimensions(Path("__mem__"), definition.sprite_version)
    except ValueError:
        # __mem__ 仅用于触发尺寸期望；此处改为对实际字节校验
        pass
    expected_h = catalog.SPRITESHEET_HEIGHT_V2 if definition.sprite_version == 2 else catalog.SPRITESHEET_HEIGHT_V1
    if actual_dims[0] != catalog.SPRITESHEET_WIDTH or actual_dims[1] != expected_h:
        raise HTTPException(
            status_code=400,
            detail=(
                f"精灵表尺寸不合法：期望 {catalog.SPRITESHEET_WIDTH}x{expected_h}，"
                f"实际 {actual_dims[0]}x{actual_dims[1]}"
            ),
        )

    spritesheet_name = "spritesheet" + ext
    storage_dir.mkdir(parents=True, exist_ok=True)
    spritesheet_disk = storage_dir / spritesheet_name
    spritesheet_disk.write_bytes(sprite_bytes)
    # 同步落盘 pet.json（与 Codex 约定一致，便于导出/迁移）
    (storage_dir / "pet.json").write_text(
        json.dumps(definition.to_manifest_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    existing = db.get(Pet, record_id)
    if existing is None:
        pet_row = Pet(
            id=record_id,
            user_id=current_user.id,
            pet_id=pet_id,
            display_name=definition.display_name,
            description=definition.description,
            sprite_version=definition.sprite_version,
            frame_width=definition.frame_width,
            frame_height=definition.frame_height,
            columns=definition.columns,
            rows=definition.rows,
            frame_count=definition.frame_count,
            animations=definition.animations,
            spritesheet_path=str(spritesheet_disk),
            is_builtin=False,
            spritesheet_ready=True,
        )
        db.add(pet_row)
    else:
        existing.display_name = definition.display_name
        existing.description = definition.description
        existing.sprite_version = definition.sprite_version
        existing.frame_width = definition.frame_width
        existing.frame_height = definition.frame_height
        existing.columns = definition.columns
        existing.rows = definition.rows
        existing.frame_count = definition.frame_count
        existing.animations = definition.animations
        existing.spritesheet_path = str(spritesheet_disk)
        existing.spritesheet_ready = True
        pet_row = existing
    db.commit()

    logger.bind(event="pets_import", module="pets", pet_id=pet_id).info(
        f"imported custom pet {pet_id} for user {current_user.id}"
    )
    return PetImportResponse(pet=_pet_to_response(pet_row, is_active=False))


@router.delete("/{pet_id}")
def delete_custom_pet(
    pet_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除当前用户的自定义宠物；内置宠物不可删除。"""
    record_id = pet_id if pet_id.startswith("custom:") else _custom_record_id(current_user.id, pet_id)
    pet = db.get(Pet, record_id)
    if pet is None or pet.is_builtin:
        raise HTTPException(status_code=404, detail="宠物不存在或不可删除")
    if pet.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权删除该宠物")

    # 清理磁盘文件
    storage_dir = asset_pack.custom_pet_dir(current_user.id, pet.pet_id)
    if storage_dir.exists():
        for item in storage_dir.iterdir():
            try:
                item.unlink()
            except OSError:
                pass
        try:
            storage_dir.rmdir()
        except OSError:
            pass

    # 若该宠物处于激活态，同步移除激活记录
    active = db.execute(
        select(UserActivePet).where(UserActivePet.user_id == current_user.id)
    ).scalar_one_or_none()
    if active and active.pet_id == pet.id:
        db.delete(active)

    db.delete(pet)
    db.commit()
    return {"success": True, "message": f"已删除宠物 {pet.pet_id}"}


@router.get("/{pet_id}/spritesheet")
def get_pet_spritesheet(
    pet_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回精灵表图片；内置宠物首次请求时按需下载缓存。"""
    pet = db.get(Pet, pet_id)
    if pet is None or (pet.user_id is not None and pet.user_id != current_user.id):
        raise HTTPException(status_code=404, detail="宠物不存在或无访问权限")

    if pet.is_builtin and not pet.spritesheet_ready:
        builtin = catalog.builtin_pet(pet.pet_id)
        if builtin is None:
            raise HTTPException(status_code=404, detail="内置宠物不存在")
        try:
            asset_pack.ensure_builtin_pet(builtin)
            pet.spritesheet_ready = True
            db.commit()
        except Exception as exc:  # noqa: BLE001 - CDN 不可达时降级
            logger.bind(event="pets_builtin_download_failed", module="pets", pet_id=pet.pet_id).warning(
                f"builtin pet spritesheet unavailable: {exc}"
            )
            raise HTTPException(status_code=503, detail="内置宠物精灵表暂时不可用（CDN 下载失败）") from exc

    spritesheet = _resolve_spritesheet_path(pet)
    if not spritesheet.exists():
        raise HTTPException(status_code=404, detail="精灵表文件缺失")
    media = EXT_MEDIA_TYPES.get(spritesheet.suffix.lower(), "application/octet-stream")
    return FileResponse(str(spritesheet), media_type=media, filename=spritesheet.name)


@router.get("/{pet_id}/manifest")
def get_pet_manifest(
    pet_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回 pet.json 清单，便于导出或分享。"""
    pet = db.get(Pet, pet_id)
    if pet is None or (pet.user_id is not None and pet.user_id != current_user.id):
        raise HTTPException(status_code=404, detail="宠物不存在或无访问权限")

    if pet.is_builtin:
        manifest_obj = {
            "id": pet.pet_id,
            "displayName": pet.display_name,
            "description": pet.description,
            "spriteVersionNumber": pet.sprite_version,
            "spritesheetPath": "spritesheet.webp",
            "frame": {
                "width": pet.frame_width,
                "height": pet.frame_height,
                "columns": pet.columns,
                "rows": pet.rows,
            },
        }
        return JSONResponse(manifest_obj)

    storage_dir = asset_pack.custom_pet_dir(pet.user_id, pet.pet_id)
    manifest_file = storage_dir / "pet.json"
    if manifest_file.exists():
        return JSONResponse(json.loads(manifest_file.read_text(encoding="utf-8")))
    raise HTTPException(status_code=404, detail="宠物清单文件缺失")


# ============================================================
# Live2D 模型管理路由
# ============================================================

# 文件扩展名 -> MIME 类型映射
_LIVED2D_MIME_TYPES: Dict[str, str] = {
    ".json": "application/json",
    ".moc3": "application/octet-stream",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _live2d_model_to_response(model: Live2DModel) -> Live2DModelResponse:
    """将 Live2DModel ORM 行转换为响应模型。"""
    return Live2DModelResponse(
        id=model.id,
        model_name=model.model_name,
        model_path=model.model_path,
        model3_json_path=model.model3_json_path,
        moc3_path=model.moc3_path,
        texture_paths=model.texture_paths or [],
        expressions_json=model.expressions_json or [],
        motions_json=model.motions_json or [],
        physics_json=model.physics_json,
        pose_json=model.pose_json,
        version=model.version,
        user_id=model.user_id,
        created_at=model.created_at,
    )


def _resolve_live2d_model_dir(model: Live2DModel) -> Path:
    """解析 Live2D 模型存储目录的绝对路径。"""
    stored = Path(model.model_path)
    if stored.is_absolute():
        return stored
    return LIVED2D_DATA_DIR / stored


def _safe_model_file_path(model_dir: Path, filename: str) -> Path:
    """安全解析模型目录下的文件路径，防止路径穿越。"""
    resolved = (model_dir / filename).resolve()
    if not str(resolved).startswith(str(model_dir.resolve())):
        raise HTTPException(status_code=403, detail="路径越权访问被拒绝")
    return resolved


@router.post("/live2d/upload", response_model=Live2DModelUploadResponse)
async def upload_live2d_model(
    archive: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    上传 Live2D 模型 zip 包。

    校验 zip 包内容合法性后，将模型文件解压到 var/pets/live2d/{model_id}/ 目录，
    并在数据库中创建 Live2DModel 记录。
    """
    # 读取上传文件
    archive_bytes = _read_upload_bytes(archive, MAX_MODEL_ARCHIVE_BYTES)

    # 校验 zip 包内容
    try:
        metadata = validate_live2d_archive(archive_bytes)
    except Live2DValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 生成模型 id 与存储目录
    model_id = str(uuid.uuid4())
    model_dir = LIVED2D_DATA_DIR / model_id
    model_dir.mkdir(parents=True, exist_ok=True)

    # 解压文件到磁盘
    file_map: Dict[str, bytes] = metadata["file_map"]
    for rel_path, data in file_map.items():
        # 安全解析目标路径，确保不穿越出模型目录
        dest = _safe_model_file_path(model_dir, rel_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    # 创建数据库记录
    model_row = Live2DModel(
        id=model_id,
        model_name=metadata["model_name"],
        model_path=str(model_dir),
        model3_json_path=metadata["model3_json_path"],
        moc3_path=metadata["moc3_path"],
        texture_paths=metadata["texture_paths"],
        expressions_json=metadata["expressions_json"],
        motions_json=metadata["motions_json"],
        physics_json=metadata["physics_json"],
        pose_json=metadata["pose_json"],
        version=1,
        user_id=current_user.id,
    )
    db.add(model_row)
    db.commit()
    db.refresh(model_row)

    logger.bind(event="live2d_upload", module="pets", model_id=model_id).info(
        f"用户 {current_user.id} 上传了 Live2D 模型 {model_row.model_name}"
    )

    return Live2DModelUploadResponse(model=_live2d_model_to_response(model_row))


@router.get("/live2d/models", response_model=Live2DModelListResponse)
def list_live2d_models(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    列出所有可用的 Live2D 模型（内置模型 + 当前用户上传的模型）。
    """
    rows = (
        db.query(Live2DModel)
        .filter(
            (Live2DModel.user_id.is_(None)) | (Live2DModel.user_id == current_user.id)
        )
        .order_by(Live2DModel.user_id.is_(None).desc(), Live2DModel.model_name.asc())
        .all()
    )
    models = [_live2d_model_to_response(row) for row in rows]
    return Live2DModelListResponse(models=models, total=len(models))


@router.get("/live2d/{model_id}/files/{filename:path}")
def get_live2d_model_file(
    model_id: str,
    filename: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    读取 Live2D 模型目录下的静态文件（纹理、动作、表情等）。

    使用 FileResponse 返回，自动设置 Content-Type。
    校验路径不穿越出模型目录。
    返回 Cache-Control 与 ETag 头，支持客户端缓存 Live2D 模型文件（24 小时）。
    """
    model = db.get(Live2DModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    # 访问控制：仅允许内置模型或上传者本人访问
    if model.user_id is not None and model.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问该模型")

    model_dir = _resolve_live2d_model_dir(model)
    if not model_dir.exists() or not model_dir.is_dir():
        raise HTTPException(status_code=404, detail="模型文件目录不存在")

    file_path = _safe_model_file_path(model_dir, filename)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    ext = file_path.suffix.lower()
    media_type = _LIVED2D_MIME_TYPES.get(ext, "application/octet-stream")

    # 生成 ETag：基于文件修改时间与大小，避免重复传输
    stat = file_path.stat()
    etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'

    # 缓存头：模型文件变更频率低，缓存 24 小时
    headers = {
        "Cache-Control": "public, max-age=86400",
        "ETag": etag,
    }

    return FileResponse(
        str(file_path),
        media_type=media_type,
        filename=file_path.name,
        headers=headers,
    )


@router.delete("/live2d/{model_id}")
def delete_live2d_model(
    model_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    删除 Live2D 模型。

    仅允许删除用户自己上传的模型，内置模型（user_id 为空）不可删除。
    同时清理磁盘上的模型文件目录。
    """
    model = db.get(Live2DModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    if model.user_id is None:
        raise HTTPException(status_code=403, detail="内置模型不可删除")
    if model.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权删除该模型")

    model_dir = _resolve_live2d_model_dir(model)

    # 清理磁盘文件
    if model_dir.exists():
        try:
            shutil.rmtree(str(model_dir))
        except OSError as exc:
            logger.bind(
                event="live2d_delete_cleanup_error",
                module="pets",
                model_id=model_id,
            ).warning(f"清理 Live2D 模型目录时出错: {exc}")

    db.delete(model)
    db.commit()

    logger.bind(event="live2d_delete", module="pets", model_id=model_id).info(
        f"用户 {current_user.id} 删除了 Live2D 模型 {model_id}"
    )

    return {"success": True, "message": f"已删除 Live2D 模型 {model_id}"}

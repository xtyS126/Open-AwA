"""
内置宠物精灵表的获取、缓存与尺寸校验，从 Codex asset_pack.rs 移植。

内置宠物不在代码仓库内打包精灵表，而是首次使用时从 Codex 官方 CDN 下载，
校验解码尺寸后原子安装到 var/data/pets/builtin/<pet_id>/ 缓存中。
本模块只负责"缓存中存在一张尺寸合法的精灵表"，更高层决定何时下载与持久化。
"""

from pathlib import Path
from typing import Optional, Tuple

import requests

from . import catalog
from .catalog import BuiltinPet, SPRITESHEET_HEIGHT_V1, SPRITESHEET_HEIGHT_V2, SPRITESHEET_WIDTH

# 宠物资产目录锚定到项目根 var/data/pets
# __file__ = lib/backend/pets/asset_pack.py，parents[3] = 项目根
PETS_DATA_DIR: Path = Path(__file__).resolve().parents[3] / "var" / "data" / "pets"

# 下载安全约束（与 Codex asset_pack.rs 一致）
PET_DOWNLOAD_TIMEOUT_SECONDS: float = 60.0
PET_MAX_DOWNLOAD_BYTES: int = 4 * 1024 * 1024  # 4MB


def builtin_spritesheet_path(pet: BuiltinPet) -> Path:
    """返回内置宠物精灵表的本地缓存路径（可能尚未下载）。"""
    return PETS_DATA_DIR / "builtin" / pet.id / pet.spritesheet_file


def custom_pet_dir(user_id: str, pet_id: str) -> Path:
    """返回自定义宠物目录：var/data/pets/<user_id>/<pet_id>/。"""
    return PETS_DATA_DIR / "custom" / user_id / pet_id


def is_builtin_pet_id(pet_id: str) -> bool:
    """判断是否为内置宠物 id。"""
    return catalog.builtin_pet(pet_id) is not None


def read_image_dimensions(spritesheet_path: Path) -> Optional[Tuple[int, int]]:
    """用 Pillow 读取图片像素尺寸，失败返回 None。"""
    try:
        from PIL import Image  # 延迟导入，避免模块加载即依赖图形库
    except Exception:  # noqa: BLE001 - Pillow 缺失时上层降级
        return None
    try:
        with Image.open(spritesheet_path) as image:
            return (image.width, image.height)
    except Exception:  # noqa: BLE001 - 损坏/非图片文件
        return None


def validate_spritesheet_dimensions(
    spritesheet_path: Path, sprite_version: int
) -> Tuple[int, int]:
    """校验精灵表像素尺寸，返回 (width, height)。

    V1(缺省)要求 1536x1872，V2 要求 1536x2288。尺寸不符或无法解码时抛异常。
    """
    dims = read_image_dimensions(spritesheet_path)
    if dims is None:
        raise ValueError(f"cannot read spritesheet dimensions: {spritesheet_path}")
    width, height = dims
    expected_h = SPRITESHEET_HEIGHT_V2 if sprite_version == 2 else SPRITESHEET_HEIGHT_V1
    if width != SPRITESHEET_WIDTH or height != expected_h:
        raise ValueError(
            f"invalid pet spritesheet dimensions for {spritesheet_path.name}: "
            f"expected {SPRITESHEET_WIDTH}x{expected_h}, got {width}x{height}"
        )
    return (width, height)


def validate_builtin_spritesheet(spritesheet_path: Path) -> Tuple[int, int]:
    """校验内置宠物精灵表尺寸为 1536x1872。"""
    dims = read_image_dimensions(spritesheet_path)
    if dims is None:
        raise ValueError(f"cannot read spritesheet dimensions: {spritesheet_path}")
    width, height = dims
    if width != SPRITESHEET_WIDTH or height != SPRITESHEET_HEIGHT_V1:
        raise ValueError(
            f"invalid builtin pet spritesheet dimensions for {spritesheet_path.name}: "
            f"expected {SPRITESHEET_WIDTH}x{SPRITESHEET_HEIGHT_V1}, got {width}x{height}"
        )
    return (width, height)


def ensure_builtin_pet(pet: BuiltinPet) -> Path:
    """确保内置宠物精灵表已下载并通过尺寸校验，返回缓存路径。"""
    destination = builtin_spritesheet_path(pet)
    if destination.exists():
        try:
            validate_builtin_spritesheet(destination)
            return destination
        except ValueError:
            # 缓存损坏则删除后重新下载
            try:
                destination.unlink()
            except OSError:
                pass

    bytes_payload = _download_bytes_with_limit(pet.spritesheet_url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_suffix(".download" + destination.suffix)
    staging.write_bytes(bytes_payload)
    try:
        validate_builtin_spritesheet(staging)
    except ValueError:
        try:
            staging.unlink()
        except OSError:
            pass
        raise
    staging.replace(destination)
    return destination


def _download_bytes_with_limit(url: str) -> bytes:
    """从固定 HTTPS CDN 下载精灵表，限制超时与体积，防止异常放大。

    URL 来源于内置目录常量，非用户可控，额外再做 https 校验以保持防御深度。
    """
    if not url.lower().startswith("https://"):
        raise ValueError(f"unsupported pet asset download URL scheme: {url}")
    response = requests.get(url, timeout=PET_DOWNLOAD_TIMEOUT_SECONDS, stream=True)
    response.raise_for_status()
    content_length = response.headers.get("content-length")
    if content_length and int(content_length) > PET_MAX_DOWNLOAD_BYTES:
        raise ValueError(
            f"pet asset download from {url} exceeded {PET_MAX_DOWNLOAD_BYTES} bytes"
        )
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > PET_MAX_DOWNLOAD_BYTES:
            raise ValueError(
                f"pet asset download from {url} exceeded {PET_MAX_DOWNLOAD_BYTES} bytes"
            )
        chunks.append(chunk)
    return b"".join(chunks)

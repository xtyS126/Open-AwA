"""
内置宠物目录配置，从 Codex 官方 avatar 目录移植而来。

内置宠物与自定义宠物的核心差异在于资产所有权：内置宠物的精灵表由 Codex 官方
CDN 托管，首次使用时按需下载到受管理的本地缓存；自定义宠物则完全由用户持有，
直接落盘在 var/data/pets/<user_id>/<pet_id>/ 目录下。本模块只负责声明目录元数据与
精灵表几何常量，不负责下载或持久化。
"""

from dataclasses import dataclass
from typing import List, Optional

# ---- 精灵表几何常量（与 Codex V2 契约一致）----
# V2 图集为 8 列 x 11 行、192x208 单元，整体尺寸 1536x2288
DEFAULT_FRAME_WIDTH: int = 192
DEFAULT_FRAME_HEIGHT: int = 208
DEFAULT_FRAME_COLUMNS: int = 8
DEFAULT_FRAME_ROWS: int = 9  # V1 标准动画行数；V2 额外包含两行注视方向
V2_FRAME_ROWS: int = 11
SPRITESHEET_WIDTH: int = DEFAULT_FRAME_WIDTH * DEFAULT_FRAME_COLUMNS
SPRITESHEET_HEIGHT_V1: int = DEFAULT_FRAME_HEIGHT * DEFAULT_FRAME_ROWS
SPRITESHEET_HEIGHT_V2: int = DEFAULT_FRAME_HEIGHT * V2_FRAME_ROWS

# 内置宠物官方 CDN 基址，可在不修改代码的情况下通过版本化文件名升级
PET_CDN_BASE_URL: str = "https://persistent.oaistatic.com/codex/pets/v1"


@dataclass(frozen=True)
class BuiltinPet:
    """内置宠物元数据。"""

    id: str
    display_name: str
    description: str
    spritesheet_file: str

    @property
    def spritesheet_url(self) -> str:
        """拼装内置宠物精灵表的 CDN 下载地址。"""
        return f"{PET_CDN_BASE_URL}/{self.spritesheet_file}"


# Codex 官方内置宠物目录（8 个）
BUILTIN_PETS: List[BuiltinPet] = [
    BuiltinPet("codex", "Codex", "The original Codex companion", "codex-spritesheet-v4.webp"),
    BuiltinPet("dewey", "Dewey", "A tidy duck for calm workspace days", "dewey-spritesheet-v4.webp"),
    BuiltinPet("fireball", "Fireball", "Hot path energy for fast iteration", "fireball-spritesheet-v4.webp"),
    BuiltinPet("rocky", "Rocky", "A steady rock when the diff gets large", "rocky-spritesheet-v4.webp"),
    BuiltinPet("seedy", "Seedy", "Small green shoots for new ideas", "seedy-spritesheet-v4.webp"),
    BuiltinPet("stacky", "Stacky", "A balanced stack for deep work", "stacky-spritesheet-v4.webp"),
    BuiltinPet("bsod", "BSOD", "A tiny blue-screen gremlin", "bsod-spritesheet-v4.webp"),
    BuiltinPet("null-signal", "Null Signal", "Quiet signal from the void", "null-signal-spritesheet-v4.webp"),
]


def builtin_pet(pet_id: str) -> Optional[BuiltinPet]:
    """按 id 查找内置宠物。"""
    for pet in BUILTIN_PETS:
        if pet.id == pet_id:
            return pet
    return None


def builtin_pet_ids() -> List[str]:
    """返回所有内置宠物 id 列表。"""
    return [pet.id for pet in BUILTIN_PETS]

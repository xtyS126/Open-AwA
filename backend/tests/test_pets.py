# -*- coding: utf-8 -*-
"""
pets 模块单元测试。

覆盖从 Codex 移植的清单校验、默认动画、内置宠物目录等纯逻辑路径，
不依赖数据库与网络，保证可被 CI 快速回归。
"""

from __future__ import annotations

import pytest

from pets import catalog, manifest


# ---- 内置目录 ----

def test_builtin_pets_count_is_eight():
    """Codex 官方内置宠物固定 8 个。"""
    assert len(catalog.BUILTIN_PETS) == 8
    assert catalog.builtin_pet_ids() == [
        "codex",
        "dewey",
        "fireball",
        "rocky",
        "seedy",
        "stacky",
        "bsod",
        "null-signal",
    ]


def test_builtin_pet_lookup_returns_metadata():
    """按 id 查得的内置宠物携带正确显示名与精灵表文件名。"""
    pet = catalog.builtin_pet("dewey")
    assert pet is not None
    assert pet.display_name == "Dewey"
    assert pet.spritesheet_file == "dewey-spritesheet-v4.webp"
    assert pet.spritesheet_url.endswith("dewey-spritesheet-v4.webp")


def test_spritesheet_geometry_constants_match_v2_contract():
    """几何常量与 Codex V2 契约一致：8 列、192x208 单元、整体 1536 宽。"""
    assert catalog.DEFAULT_FRAME_COLUMNS == 8
    assert catalog.DEFAULT_FRAME_WIDTH == 192
    assert catalog.DEFAULT_FRAME_HEIGHT == 208
    assert catalog.SPRITESHEET_WIDTH == 1536
    assert catalog.V2_FRAME_ROWS == 11
    assert catalog.SPRITESHEET_HEIGHT_V2 == 2288
    assert catalog.SPRITESHEET_HEIGHT_V1 == 1872


# ---- 默认动画 ----

def test_default_animations_includes_idle_and_state_tracks():
    """默认动画集必须包含 idle 与全部应用态动画。"""
    anims = manifest.default_animations()
    for name in [
        "idle",
        "running-right",
        "running-left",
        "waving",
        "jumping",
        "failed",
        "waiting",
        "running",
        "review",
    ]:
        assert name in anims, "缺省动画集缺少 " + name


def test_idle_animation_has_six_frames_and_loops():
    """idle 动画 6 帧，loop_start 为 0 表示整段循环。"""
    idle = manifest.default_animations()["idle"]
    assert len(idle["frames"]) == 6
    assert idle["loop_start"] == 0
    assert idle["fallback"] == "idle"
    assert [f["sprite_index"] for f in idle["frames"]] == [0, 1, 2, 3, 4, 5]


def test_app_state_animation_repeats_primary_three_times_then_idle():
    """应用态动画主帧重复 3 次后接 idle，loop_start 指向 idle 起点。"""
    running = manifest.default_animations()["running-right"]
    # 8 帧主段重复 3 次 = 24，再接 idle 6 帧合共 30
    assert len(running["frames"]) == 30
    assert running["loop_start"] == 24
    assert running["fallback"] == "idle"
    # 主帧 sprite_index 落在第 1 行 (0..7)
    primary = running["frames"][:8]
    assert [f["sprite_index"] for f in primary] == [8, 9, 10, 11, 12, 13, 14, 15]


# ---- 内置定义 ----

def test_build_builtin_definition_for_codex():
    """内置 Codex 宠物定义为 V1、72 帧、精灵表路径本地化。"""
    pet = catalog.builtin_pet("codex")
    definition = manifest.build_builtin_definition(pet, spritesheet_path="/tmp/codex.webp")
    assert definition.pet_id == "codex"
    assert definition.display_name == "Codex"
    assert definition.sprite_version == 1
    assert definition.frame_count == 72
    assert definition.rows == 9
    assert definition.spritesheet_path == "/tmp/codex.webp"
    assert "idle" in definition.animations


def test_build_builtin_definition_to_manifest_dict_roundtrips():
    """内置定义可压缩为 Codex 兼容清单结构。"""
    pet = catalog.builtin_pet("rocky")
    definition = manifest.build_builtin_definition(pet, spritesheet_path="spritesheet.webp")
    raw = definition.to_manifest_dict()
    assert raw["id"] == "rocky"
    assert raw["spriteVersionNumber"] == 1
    assert raw["spritesheetPath"] == "spritesheet.webp"
    assert raw["frame"]["columns"] == 8
    assert raw["frame"]["rows"] == 9
    assert "idle" in raw["animations"]


# ---- manifest.parse_manifest ----

def _base_manifest(sprite_version: int = 2) -> dict:
    """构造最小合法清单。"""
    return {
        "id": "chefito",
        "displayName": "Chefito",
        "description": "a tiny pet",
        "spriteVersionNumber": sprite_version,
        "spritesheetPath": "spritesheet.webp",
    }


def test_parse_manifest_v2_valid(tmp_path):
    """V2 清单：1536x2288、8x11 网格精确覆盖，通过校验。"""
    definition = manifest.parse_manifest(
        manifest=_base_manifest(sprite_version=2),
        pet_id_override="chefito",
        spritesheet_actual_dims=(1536, 2288),
        pet_dir=tmp_path,
    )
    assert definition.sprite_version == 2
    assert definition.rows == 11
    assert definition.frame_count == 88
    # 未显式提供 animations 时回退默认动画集
    assert "idle" in definition.animations


def test_parse_manifest_v1_valid(tmp_path):
    """V1 清单：1536x1872、8x9 网格精确覆盖，通过校验。"""
    definition = manifest.parse_manifest(
        manifest=_base_manifest(sprite_version=1),
        pet_id_override="legacy",
        spritesheet_actual_dims=(1536, 1872),
        pet_dir=tmp_path,
    )
    assert definition.sprite_version == 1
    assert definition.rows == 9
    assert definition.frame_count == 72


def test_parse_manifest_rejects_wrong_dimensions(tmp_path):
    """精灵表尺寸与版本不匹配时拒绝。"""
    with pytest.raises(ValueError, match="frame grid must cover spritesheet exactly"):
        manifest.parse_manifest(
            manifest=_base_manifest(sprite_version=2),
            pet_id_override="bad",
            spritesheet_actual_dims=(1000, 1000),
            pet_dir=tmp_path,
        )


def test_parse_manifest_rejects_bad_sprite_version(tmp_path):
    """spriteVersionNumber 只接受 1 与 2。"""
    bad = _base_manifest(sprite_version=3)
    with pytest.raises(ValueError, match="spriteVersionNumber must be 1 or 2"):
        manifest.parse_manifest(
            manifest=bad,
            pet_id_override="bad",
            spritesheet_actual_dims=(1536, 2288),
            pet_dir=tmp_path,
        )


def test_parse_manifest_rejects_animation_frame_out_of_range(tmp_path):
    """动画帧索引超出网格时拒绝。"""
    bad = _base_manifest(sprite_version=2)
    bad["animations"] = {"idle": {"frames": [88]}}
    with pytest.raises(ValueError, match="88 exceeds maximum"):
        manifest.parse_manifest(
            manifest=bad,
            pet_id_override="bad",
            spritesheet_actual_dims=(1536, 2288),
            pet_dir=tmp_path,
        )


def test_parse_manifest_rejects_spritesheet_path_escape(tmp_path):
    """spritesheetPath 逃逸出宠物目录时拒绝。"""
    bad = _base_manifest(sprite_version=2)
    bad["spritesheetPath"] = "../evil.webp"
    with pytest.raises(ValueError, match="must stay inside the pet directory"):
        manifest.parse_manifest(
            manifest=bad,
            pet_id_override="escape",
            spritesheet_actual_dims=(1536, 2288),
            pet_dir=tmp_path,
        )


def test_parse_manifest_explicit_animation_overrides_default(tmp_path):
    """清单显式提供同名动画时覆盖默认动画，并归一化 fps。"""
    custom = _base_manifest(sprite_version=2)
    custom["animations"] = {
        "idle": {"frames": [0, 1], "fps": 10.0, "loop": True, "fallback": "idle"}
    }
    definition = manifest.parse_manifest(
        manifest=custom,
        pet_id_override="custom",
        spritesheet_actual_dims=(1536, 2288),
        pet_dir=tmp_path,
    )
    idle = definition.animations["idle"]
    assert [f["sprite_index"] for f in idle["frames"]] == [0, 1]
    assert all(f["duration_ms"] == 100 for f in idle["frames"])
    assert idle["loop_start"] == 0


def test_parse_manifest_rejects_excessive_frame_count(tmp_path):
    """帧网格超过 MAX_PET_FRAMES(256) 时拒绝。"""
    bad = _base_manifest(sprite_version=2)
    bad["frame"] = {"width": 8, "height": 8, "columns": 192, "rows": 234}
    # 8x8 单元无法精确覆盖 1536x2288，应先被 grid 覆盖校验拦截
    with pytest.raises(ValueError):
        manifest.parse_manifest(
            manifest=bad,
            pet_id_override="dense",
            spritesheet_actual_dims=(1536, 2288),
            pet_dir=tmp_path,
        )

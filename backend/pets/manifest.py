"""
宠物清单（pet.json）加载与校验，从 Codex model.rs 移植而来。

核心不变量：每个返回的 PetDefinition 都指向一个已存在且尺寸合法的本地精灵表，
且其帧网格能精确覆盖该精灵表。资产获取（下载/落盘）不在本模块职责内，
调用方需先把精灵表准备好再交给本模块解析。

V2 宠物契约（1536x2288、8x11、192x208）通过 spriteVersionNumber 标识；
缺省 frame.rows 时，V2 自动取 11 行、V1 自动取 9 行，与 Codex 行为一致。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .catalog import (
    DEFAULT_FRAME_COLUMNS,
    DEFAULT_FRAME_HEIGHT,
    DEFAULT_FRAME_ROWS,
    DEFAULT_FRAME_WIDTH,
    V2_FRAME_ROWS,
    BuiltinPet,
)

# 与 Codex 运行时一致的硬性上限
MAX_PET_FRAMES: int = 256
MAX_ANIMATION_FPS: float = 60.0
DEFAULT_ANIMATION_FPS: float = 8.0


@dataclass
class PetDefinition:
    """归一化后的宠物定义，可直接用于渲染或持久化。"""

    pet_id: str
    display_name: str
    description: str
    sprite_version: int
    frame_width: int
    frame_height: int
    columns: int
    rows: int
    frame_count: int
    animations: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    spritesheet_path: str = ""

    def to_manifest_dict(self) -> Dict[str, Any]:
        """输出与 Codex pet.json 兼容的清单结构。"""
        return {
            "id": self.pet_id,
            "displayName": self.display_name,
            "description": self.description,
            "spriteVersionNumber": self.sprite_version,
            "spritesheetPath": "spritesheet.webp",
            "frame": {
                "width": self.frame_width,
                "height": self.frame_height,
                "columns": self.columns,
                "rows": self.rows,
            },
            "animations": self._animations_to_manifest(),
        }

    def _animations_to_manifest(self) -> Dict[str, Any]:
        """将内部动画结构压缩为清单可读形式（帧索引数组 + fps）。"""
        out: Dict[str, Any] = {}
        for name, anim in self.animations.items():
            frames = anim.get("frames", [])
            sprite_indices = [f["sprite_index"] for f in frames]
            is_loop = anim.get("loop_start") is not None
            out[name] = {
                "frames": sprite_indices,
                "loop": is_loop,
                "fallback": anim.get("fallback", "idle"),
            }
        return out


# ---- 默认动画（镜像 Codex default_animations / idle_animation / app_state_animation）----


def _idle_animation() -> Dict[str, Any]:
    """idle 动画：第 0 行前 6 帧，整段循环。"""
    durations = [1680, 660, 660, 840, 840, 1920]
    return {
        "frames": [
            {"sprite_index": idx, "duration_ms": dur}
            for idx, dur in enumerate(durations)
        ],
        "loop_start": 0,
        "fallback": "idle",
    }


def _app_state_animation(
    row_index: int,
    frame_count: int,
    frame_duration_ms: int,
    final_frame_duration_ms: int,
) -> Dict[str, Any]:
    """应用态动画：主帧重复 3 次后接 idle，从主帧结束处循环 idle 尾部。"""
    primary: List[Dict[str, Any]] = []
    for column_index in range(frame_count):
        duration = final_frame_duration_ms if column_index == frame_count - 1 else frame_duration_ms
        primary.append(
            {
                "sprite_index": row_index * DEFAULT_FRAME_COLUMNS + column_index,
                "duration_ms": duration,
            }
        )
    frames: List[Dict[str, Any]] = []
    for _ in range(3):
        frames.extend(primary)
    frames.extend(_idle_animation()["frames"])
    primary_frame_count = len(primary) * 3
    return {
        "frames": frames,
        "loop_start": primary_frame_count,
        "fallback": "idle",
    }


def default_animations() -> Dict[str, Dict[str, Any]]:
    """内置宠物默认动画集，与 Codex default_animations 完全一致。"""
    return {
        "idle": _idle_animation(),
        "running-right": _app_state_animation(1, 8, 120, 220),
        "running-left": _app_state_animation(2, 8, 120, 220),
        "waving": _app_state_animation(3, 4, 140, 280),
        "jumping": _app_state_animation(4, 5, 140, 280),
        "failed": _app_state_animation(5, 8, 140, 240),
        "waiting": _app_state_animation(6, 6, 150, 260),
        "running": _app_state_animation(7, 6, 120, 220),
        "review": _app_state_animation(8, 6, 150, 280),
        # 下列为 Codex 同义别名，保留以兼容旧调用方
        "move_right": _app_state_animation(1, 8, 120, 220),
        "move_left": _app_state_animation(2, 8, 120, 220),
        "wave": _app_state_animation(3, 4, 140, 280),
        "bounce": _app_state_animation(4, 5, 140, 280),
        "sad": _app_state_animation(5, 8, 140, 240),
    }


def default_frame_spec(sprite_version: int) -> Dict[str, int]:
    """按精灵表版本返回默认帧网格：V2 取 11 行，否则 9 行。"""
    rows = V2_FRAME_ROWS if sprite_version == 2 else DEFAULT_FRAME_ROWS
    return {
        "width": DEFAULT_FRAME_WIDTH,
        "height": DEFAULT_FRAME_HEIGHT,
        "columns": DEFAULT_FRAME_COLUMNS,
        "rows": rows,
    }


def build_builtin_definition(pet: BuiltinPet, spritesheet_path: str) -> PetDefinition:
    """构建内置宠物定义：9 行网格、72 帧、默认动画集。"""
    return PetDefinition(
        pet_id=pet.id,
        display_name=pet.display_name,
        description=pet.description,
        sprite_version=1,
        frame_width=DEFAULT_FRAME_WIDTH,
        frame_height=DEFAULT_FRAME_HEIGHT,
        columns=DEFAULT_FRAME_COLUMNS,
        rows=DEFAULT_FRAME_ROWS,
        frame_count=DEFAULT_FRAME_COLUMNS * DEFAULT_FRAME_ROWS,
        animations=default_animations(),
        spritesheet_path=spritesheet_path,
    )


def parse_manifest(
    manifest: Dict[str, Any],
    pet_id_override: str,
    spritesheet_actual_dims: Optional[Tuple[int, int]],
    pet_dir: Optional[Path] = None,
) -> PetDefinition:
    """解析并校验自定义宠物清单，返回归一化定义。

    参数 spritesheet_actual_dims 为 PIL 读取到的真实像素尺寸，用于校验帧网格精确覆盖。
    """
    raw_id = str(manifest.get("id") or "").strip() or pet_id_override
    display_name = str(manifest.get("displayName") or manifest.get("display_name") or raw_id).strip()
    description = str(manifest.get("description") or "").strip()
    sprite_version = int(manifest.get("spriteVersionNumber") or manifest.get("sprite_version") or 1)
    if sprite_version not in (1, 2):
        raise ValueError(f"pet spriteVersionNumber must be 1 or 2, got {sprite_version}")

    frame_spec_in = manifest.get("frame") or {}
    spec = default_frame_spec(sprite_version)
    spec["width"] = int(frame_spec_in.get("width", spec["width"]))
    spec["height"] = int(frame_spec_in.get("height", spec["height"]))
    spec["columns"] = int(frame_spec_in.get("columns", spec["columns"]))
    spec["rows"] = int(frame_spec_in.get("rows", spec["rows"]))
    if min(spec["width"], spec["height"], spec["columns"], spec["rows"]) <= 0:
        raise ValueError("pet frame dimensions and grid counts must be non-zero")

    frame_count = spec["columns"] * spec["rows"]
    if frame_count > MAX_PET_FRAMES:
        raise ValueError(
            f"pet frame count {frame_count} exceeds maximum {MAX_PET_FRAMES}"
        )

    # 校验帧网格精确覆盖真实精灵表尺寸
    if spritesheet_actual_dims is not None:
        actual_w, actual_h = spritesheet_actual_dims
        if spec["width"] * spec["columns"] != actual_w or spec["height"] * spec["rows"] != actual_h:
            raise ValueError(
                "pet frame grid must cover spritesheet exactly: "
                f"got {spec['width']*spec['columns']}x{spec['height']*spec['rows']} grid, "
                f"spritesheet is {actual_w}x{actual_h}"
            )

    animations = _normalize_animations(manifest.get("animations") or {}, frame_count)

    spritesheet_rel = str(manifest.get("spritesheetPath") or manifest.get("spritesheet_path") or "spritesheet.webp")
    # 防止 spritesheet 路径逃逸出宠物目录
    if pet_dir is not None:
        resolved = (pet_dir / spritesheet_rel).resolve()
        try:
            resolved.relative_to(pet_dir.resolve())
        except ValueError as exc:
            raise ValueError("spritesheet path must stay inside the pet directory") from exc

    return PetDefinition(
        pet_id=raw_id,
        display_name=display_name,
        description=description,
        sprite_version=sprite_version,
        frame_width=spec["width"],
        frame_height=spec["height"],
        columns=spec["columns"],
        rows=spec["rows"],
        frame_count=frame_count,
        animations=animations,
        spritesheet_path=spritesheet_rel,
    )


def _normalize_animations(
    specs: Dict[str, Any], frame_count: int
) -> Dict[str, Dict[str, Any]]:
    """归一化清单中的动画声明，未提供时使用默认动画集。"""
    animations: Dict[str, Dict[str, Any]] = dict(default_animations())
    if not specs:
        _validate_animation_indices(animations, frame_count)
        return animations

    for name, raw in specs.items():
        raw_frames = list((raw or {}).get("frames") or [])
        if not raw_frames:
            raise ValueError(f"animation {name} must include at least one frame")
        for sprite_index in raw_frames:
            if int(sprite_index) >= frame_count:
                raise ValueError(
                    f"animation {name} references sprite index {sprite_index}, "
                    f"but pet has {frame_count} frames"
                )

        fps_raw = (raw or {}).get("fps")
        if fps_raw is None:
            fps = DEFAULT_ANIMATION_FPS
            fps_provided = False
        else:
            try:
                fps = float(fps_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"animation {name} fps must be finite and between 0 and {MAX_ANIMATION_FPS}, got {fps_raw}"
                ) from exc
            fps_provided = True
            if not (fps > 0.0 and fps <= MAX_ANIMATION_FPS and fps == fps):
                raise ValueError(
                    f"animation {name} fps must be finite and between 0 and {MAX_ANIMATION_FPS}, got {fps}"
                )
        duration_ms = int(round(1000.0 / fps))

        fallback = str((raw or {}).get("fallback") or "") or "idle"
        loop_raw = (raw or {}).get("loop")
        is_loop = True if loop_raw is None else bool(loop_raw)
        loop_start = 0 if is_loop else None

        frames = [
            {"sprite_index": int(idx), "duration_ms": duration_ms}
            for idx in raw_frames
        ]
        animations[name] = {"frames": frames, "loop_start": loop_start, "fallback": fallback}

    # 确保 idle 总是存在
    animations.setdefault("idle", _idle_animation())
    _validate_animation_indices(animations, frame_count)
    return animations


def _validate_animation_indices(
    animations: Dict[str, Dict[str, Any]], frame_count: int
) -> None:
    """校验所有动画的帧索引与回退目标均合法。"""
    for name, anim in animations.items():
        frames = anim.get("frames") or []
        if not frames:
            raise ValueError(f"animation {name} must include at least one frame")
        for frame in frames:
            if int(frame["sprite_index"]) >= frame_count:
                raise ValueError(
                    f"animation {name} references sprite index {frame['sprite_index']}, "
                    f"but pet has {frame_count} frames"
                )
        fallback = anim.get("fallback") or "idle"
        if fallback not in animations:
            raise ValueError(f"animation {name} fallback {fallback} does not exist")

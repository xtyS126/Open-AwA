"""
精灵表帧切片工具，从 Codex frames.rs 移植。

Web 端通常直接用 canvas 按网格切割整张精灵表，本模块主要服务于"单帧预览图"
场景：按帧索引从精灵表切出一张 PNG，供不支持 canvas 切割的兜底渲染或缩略图使用。
"""

from pathlib import Path
from typing import Optional, Tuple


def slice_frame_to_png(
    spritesheet_path: Path,
    frame_index: int,
    frame_width: int,
    frame_height: int,
    columns: int,
    out_path: Path,
) -> Path:
    """从精灵表按线性帧索引切出单帧，写为 PNG（Web 端不依赖此方法）。"""
    row = frame_index // columns
    column = frame_index % columns
    return slice_cell_to_png(
        spritesheet_path,
        x=column * frame_width,
        y=row * frame_height,
        width=frame_width,
        height=frame_height,
        out_path=out_path,
    )


def slice_cell_to_png(
    spritesheet_path: Path, x: int, y: int, width: int, height: int, out_path: Path
) -> Path:
    """按像素区域切出单帧 PNG。"""
    from PIL import Image  # 延迟导入

    with Image.open(spritesheet_path) as image:
        frame = image.crop((x, y, x + width, y + height))
        # 统一转 RGBA 以保留透明通道（V2 要求背景透明）
        if frame.mode != "RGBA":
            frame = frame.convert("RGBA")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        frame.save(out_path, format="PNG")
    return out_path

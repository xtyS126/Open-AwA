"""
Live2D 模型 zip 包校验模块：负责解析上传的 zip 包，校验文件结构与内容合法性。

校验流程：
1. 检查 zip 包大小不超过 MAX_MODEL_ARCHIVE_BYTES
2. 检查是否存在 .model3.json 入口文件
3. 校验 .model3.json 引用的 .moc3 文件存在
4. 校验所有文件扩展名在 VALID_MODEL_EXTENSIONS 白名单内
5. 校验路径穿越攻击（所有路径必须在 zip 根目录内）
6. 解析 .model3.json 中的 Groups（动作组）、Expressions（表情）、Physics（物理）、Pose（姿势）定义
7. 返回校验后的模型元数据 dict
"""

import io
import json
import os
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pets.live2d import MAX_MODEL_ARCHIVE_BYTES, VALID_MODEL_EXTENSIONS


class Live2DValidationError(ValueError):
    """Live2D 模型校验异常，携带用户可读的错误描述。"""
    pass


def _validate_path_traversal(archive_path: str) -> str:
    """校验 zip 条目路径不穿越根目录，返回归一化后的路径。"""
    # 拒绝绝对路径
    if os.path.isabs(archive_path):
        raise Live2DValidationError(f"zip 包内不允许绝对路径: {archive_path}")
    # 归一化路径并检查穿越
    normalized = os.path.normpath(archive_path)
    if normalized.startswith("..") or os.path.isabs(normalized):
        raise Live2DValidationError(f"zip 包内路径穿越被拒绝: {archive_path}")
    # 逐段检查，防止 ../ 变体
    parts = Path(archive_path).parts
    if ".." in parts:
        raise Live2DValidationError(f"zip 包内路径穿越被拒绝: {archive_path}")
    return normalized


def _validate_extension(filename: str) -> None:
    """校验文件扩展名在允许的白名单内。"""
    ext = os.path.splitext(filename)[1].lower()
    if not ext:
        raise Live2DValidationError(f"文件缺少扩展名: {filename}")
    if ext not in VALID_MODEL_EXTENSIONS:
        raise Live2DValidationError(
            f"不支持的文件类型 .{ext}: {filename}，仅允许: {', '.join(sorted(VALID_MODEL_EXTENSIONS))}"
        )


def _find_model3_json(zf: zipfile.ZipFile) -> Tuple[str, Dict[str, Any]]:
    """在 zip 包中查找 .model3.json 入口文件并解析，返回 (文件名, 解析后的 JSON)。"""
    names = zf.namelist()
    model3_json_names = [
        n for n in names
        if n.lower().endswith(".model3.json") and not n.endswith("/")
    ]
    if not model3_json_names:
        raise Live2DValidationError("zip 包中缺少 .model3.json 入口文件")
    if len(model3_json_names) > 1:
        raise Live2DValidationError(
            f"zip 包中存在多个 .model3.json 文件: {model3_json_names}"
        )

    model3_name = model3_json_names[0]
    try:
        raw = zf.read(model3_name)
        model3_data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise Live2DValidationError(f".model3.json 不是合法 JSON: {exc}") from exc
    if not isinstance(model3_data, dict):
        raise Live2DValidationError(".model3.json 顶层必须是 JSON 对象")

    return model3_name, model3_data


def _validate_moc3_reference(
    zf: zipfile.ZipFile,
    model3_data: Dict[str, Any],
    model3_dir: str,
) -> str:
    """校验 .model3.json 中引用的 .moc3 文件存在，返回 moc3 文件名。"""
    # Cubism 5: FileReferences.Moc 字段
    file_refs = model3_data.get("FileReferences", {})
    moc_path = file_refs.get("Moc", "")
    if not moc_path:
        raise Live2DValidationError(".model3.json 中未找到 FileReferences.Moc 字段")

    # 相对于 model3.json 所在目录解析 moc3 路径
    moc_abs = os.path.normpath(
        os.path.join(model3_dir, moc_path)
    ) if model3_dir else moc_path

    # 校验路径穿越
    _validate_path_traversal(moc_abs)

    # 检查文件在 zip 中存在
    if moc_abs not in zf.namelist():
        # 尝试不带目录前缀的匹配
        found = False
        for name in zf.namelist():
            if name.endswith("/" + moc_path) or name == moc_path:
                moc_abs = name
                found = True
                break
        if not found:
            raise Live2DValidationError(f".model3.json 引用的 .moc3 文件不存在: {moc_path}")

    # 校验扩展名
    if not moc_abs.lower().endswith(".moc3"):
        raise Live2DValidationError(f"Moc 引用不是 .moc3 文件: {moc_path}")

    return moc_abs


def _resolve_referenced_path(
    model3_dir: str,
    ref_path: str,
    namelist: List[str],
) -> Optional[str]:
    """解析 .model3.json 中引用的文件路径，返回 zip 内的实际路径或 None。"""
    if not ref_path:
        return None
    # 相对于 model3.json 所在目录解析
    resolved = os.path.normpath(
        os.path.join(model3_dir, ref_path)
    ) if model3_dir else ref_path
    _validate_path_traversal(resolved)
    if resolved in namelist:
        return resolved
    # 尝试模糊匹配（忽略目录层级）
    for name in namelist:
        if name.endswith("/" + ref_path) or name == ref_path:
            return name
    return None


def validate_live2d_archive(archive_bytes: bytes) -> Dict[str, Any]:
    """
    校验 Live2D 模型 zip 包，返回模型元数据 dict。

    返回的 dict 包含：
    - model_name: 模型名称
    - model3_json_path: .model3.json 在 zip 内的路径
    - moc3_path: .moc3 在 zip 内的路径
    - texture_paths: 纹理文件列表
    - expressions_json: 表情定义
    - motions_json: 动作组定义
    - physics_json: 物理定义文件名（可选）
    - pose_json: 姿势定义文件名（可选）
    - file_map: {zip内路径: 文件字节数据} 用于后续解压

    异常：
    - Live2DValidationError: 校验失败时抛出
    """
    # 1. 校验总大小
    if len(archive_bytes) > MAX_MODEL_ARCHIVE_BYTES:
        raise Live2DValidationError(
            f"zip 包大小 {len(archive_bytes)} 字节超过上限 {MAX_MODEL_ARCHIVE_BYTES} 字节"
        )

    # 2. 打开 zip
    try:
        zf = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except zipfile.BadZipFile as exc:
        raise Live2DValidationError("上传文件不是合法的 zip 包") from exc

    namelist = [n for n in zf.namelist() if not n.endswith("/")]

    # 3. 校验所有文件扩展名
    for name in namelist:
        _validate_extension(name)

    # 4. 校验所有路径无穿越
    for name in namelist:
        _validate_path_traversal(name)

    # 5. 查找并解析 .model3.json
    model3_name, model3_data = _find_model3_json(zf)
    model3_dir = os.path.dirname(model3_name) if "/" in model3_name else ""

    # 6. 校验 .moc3 引用
    moc3_name = _validate_moc3_reference(zf, model3_data, model3_dir)

    # 7. 解析纹理引用
    file_refs = model3_data.get("FileReferences", {})
    textures = file_refs.get("Textures", [])
    if isinstance(textures, str):
        textures = [textures]
    texture_paths: List[str] = []
    for tex in textures:
        resolved = _resolve_referenced_path(model3_dir, tex, namelist)
        if resolved is None:
            raise Live2DValidationError(f".model3.json 引用的纹理文件不存在: {tex}")
        texture_paths.append(resolved)

    # 8. 解析 Expressions（表情）
    expressions = model3_data.get("Expressions", [])
    if isinstance(expressions, list):
        expressions_json = expressions
    else:
        expressions_json = []

    # 9. 解析 Groups（动作组）
    groups = model3_data.get("Groups", [])
    if isinstance(groups, list):
        motions_json = groups
    else:
        motions_json = []

    # 10. 解析 Physics（物理）
    physics_ref = file_refs.get("Physics", "")
    physics_json: Optional[str] = _resolve_referenced_path(model3_dir, physics_ref, namelist)

    # 11. 解析 Pose（姿势）
    pose_ref = file_refs.get("Pose", "")
    pose_json: Optional[str] = _resolve_referenced_path(model3_dir, pose_ref, namelist)

    # 12. 提取模型名称
    model_name = model3_data.get("Name", "") or os.path.splitext(
        os.path.basename(model3_name)
    )[0].replace(".model3", "")

    # 13. 构建 file_map（zip 内所有文件 -> 字节数据）
    file_map: Dict[str, bytes] = {}
    for name in namelist:
        file_map[name] = zf.read(name)

    return {
        "model_name": model_name,
        "model3_json_path": model3_name,
        "moc3_path": moc3_name,
        "texture_paths": texture_paths,
        "expressions_json": expressions_json,
        "motions_json": motions_json,
        "physics_json": physics_json,
        "pose_json": pose_json,
        "file_map": file_map,
    }
"""
宠物模块：将 Codex 终端 Ambient Pet 功能移植到 Open-AwA Web 平台。

本模块按职责拆分为：
- catalog.py：内置宠物目录与精灵表几何常量（镜像 Codex catalog.rs）
- manifest.py：pet.json 清单加载、校验与默认动画（镜像 model.rs）
- asset_pack.py：内置宠物精灵表的 CDN 下载、缓存与尺寸校验（镜像 asset_pack.rs）
- spritesheet.py：精灵表帧切片工具

自定义宠物完全由用户持有，落盘在 data/pets/<user_id>/<pet_id>/ 下，
清单结构与 Codex V2 宠物契约一致，支持导入官方 hatch-pet 产物。
"""

__all__ = ["catalog", "manifest", "asset_pack", "spritesheet"]

"""
Live2D 模型管理模块：负责 Cubism 模型文件的存储、校验与静态资源服务。

本模块按职责拆分为：
- validator.py：zip 包校验、清单解析与路径穿越防护

模块级常量定义 Live2D 模型文件约束与存储路径。
"""

from pathlib import Path

from config.runtime_paths import PETS_DATA_DIR

# ---- Live2D 模型文件结构常量 ----

# 允许的模型文件扩展名白名单
VALID_MODEL_EXTENSIONS: set[str] = {".moc3", ".json", ".png", ".webp"}

# 模型入口文件（Cubism 5+ 使用 .model3.json 作为入口）
REQUIRED_MODEL_FILES: list[str] = ["model3.json"]

# 上传 zip 包最大 50MB
MAX_MODEL_ARCHIVE_BYTES: int = 50 * 1024 * 1024

# Live2D 模型数据落盘目录
LIVED2D_DATA_DIR: Path = PETS_DATA_DIR / "live2d"

__all__ = [
    "VALID_MODEL_EXTENSIONS",
    "REQUIRED_MODEL_FILES",
    "MAX_MODEL_ARCHIVE_BYTES",
    "LIVED2D_DATA_DIR",
    "validator",
]
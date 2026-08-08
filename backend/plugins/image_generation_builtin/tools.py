"""生图内置插件的工具定义注册表与 handler。

Agent 通过 ``image_generate`` 工具选择生图模型并生成图片：

- 生图模型候选来自模型配置表（标记 ``is_image_generation=True`` 的配置），
  其用途/限制描述（``image_generation_usage``）已注入系统提示的模型目录
  （``image_entries``），本工具 description 说明参数契约，AI 按目录选型。
- handler 由 PluginManager 的 ``execute_registered_tool_async`` 直接调用，
  ``db`` 与 ``user_id`` 由执行层注入。
- 返回结果仅携带文件路径与元数据（避免大 base64 污染模型上下文）；
  需要图片 base64 的调用方（如 REST 路由）直接调用核心生图服务。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from core.image_generation import generate_image


async def image_generate(
    db: Session,
    user_id: int,
    prompt: str,
    config_id: Optional[int] = None,
    size: str = "1024x1024",
    n: int = 1,
    quality: Optional[str] = None,
) -> dict:
    """调用生图服务按指定（或默认）生图模型生成图片。

    Args:
        db: 数据库会话（由 PluginManager 注入）。
        user_id: 调用方用户 ID（用于日志关联）。
        prompt: 生图提示词。
        config_id: 生图模型配置 ID；缺省时自动选择第一个启用的生图模型。
        size: 图片尺寸（宽x高，如 1024x1024）。
        n: 生成数量（1-6，SD 支持多张；GPT-Image 固定 1 张）。
        quality: 质量参数（仅 OpenAI 兼容协议支持，如 high）。

    Returns:
        成功返回 ``{"ok": True, "model": ..., "protocol": ..., "size": ...,
        "n": ..., "images": [{"file_path", "format", "bytes"}], "message": ...}``；
        失败时异常向上传播（无兜底）。
    """
    if db is None:
        raise ValueError("生图工具缺少数据库会话注入，无法解析生图模型配置")

    result = await generate_image(
        db,
        prompt=prompt,
        config_id=config_id,
        size=size,
        n=n,
        quality=quality,
    )

    images = result["images"]
    paths = "、".join(image["file_path"] for image in images)
    return {
        "ok": True,
        "model": result["model"],
        "protocol": result["protocol"],
        "size": result["size"],
        "n": result["n"],
        "images": [
            {
                "file_path": image["file_path"],
                "format": image["format"],
                "bytes": image["bytes"],
            }
            for image in images
        ],
        "message": f"生图完成，共 {len(images)} 张，已保存: {paths}",
    }


# 工具定义注册表（供 plugin.py:get_tools() 引用）
# parameters 字段为 JSON Schema 格式，供 LLM 调用时参考
IMAGE_GENERATION_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "image_generate",
        "description": (
            "使用已配置的生图模型生成图片（SD / GPT-Image / Qwen-Image 系列）。"
            "生图模型候选及其用途/限制见系统提示中的可用生图模型目录；"
            "多模型并存时按目录描述选择最合适的模型并传对应 config_id。"
            "GPT-Image 系列固定生成 1 张；SD 与 Qwen-Image 支持一次多张（n）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "生图提示词，应描述主体、风格、场景、光线等细节",
                },
                "config_id": {
                    "type": "integer",
                    "description": "生图模型配置 ID（来自生图模型目录）；缺省时系统自动选择第一个启用的生图模型",
                },
                "size": {
                    "type": "string",
                    "description": "图片尺寸，宽x高（如 1024x1024 / 1536x1024 / 1024x1536）",
                    "enum": ["1024x1024", "1536x1024", "1024x1536", "512x512", "768x768"],
                },
                "n": {
                    "type": "integer",
                    "description": "生成数量（1-6，默认 1）；GPT-Image 固定 1 张",
                    "minimum": 1,
                    "maximum": 6,
                },
                "quality": {
                    "type": "string",
                    "description": "质量参数（仅 OpenAI 兼容协议支持，如 high）；SD / Qwen-Image 忽略",
                },
            },
            "required": ["prompt"],
        },
        "handler": image_generate,
    },
]

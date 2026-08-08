"""image-generation-builtin 内置插件 REST API 路由。

暴露生图模型列表与手动生图两个端点，前缀 ``/image-generation``，
由 ``main.py`` 挂载到 ``/api/image-generation``。

设计要点：
- 所有端点均通过 ``Depends(get_current_user)`` 鉴权，未认证返回 401
- 数据库会话通过 ``Depends(get_db)`` 注入，与 Open-AwA 主业务一致
- 生图失败时返回显式结构化错误（HTTPException），异常自然传播不静默降级
- 生图响应含图片 base64（供前端直接展示）与本地保存路径（var/data/generated）
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from core.image_generation import generate_image, list_image_models
from db.models import User

router = APIRouter(prefix="/image-generation", tags=["image-generation"])


class ImageGenerationGenerateRequest(BaseModel):
    """生图请求体。"""

    prompt: str = Field(..., min_length=1, max_length=4000, description="生图提示词")
    config_id: Optional[int] = Field(None, description="生图模型配置 ID；缺省时自动选择第一个启用的生图模型")
    size: str = Field("1024x1024", description="图片尺寸（宽x高，如 1024x1024）")
    n: int = Field(1, ge=1, le=6, description="生成数量（1-6）")
    quality: Optional[str] = Field(None, description="质量参数（仅 OpenAI 兼容协议支持）")


@router.get("/models")
def get_image_models(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """列出已启用且标记为生图模型的配置（含用途/限制描述），供前端展示与 AI 选型。"""
    models = list_image_models(db)
    logger.bind(
        event="image_models_listed",
        module="image_generation",
        user_id=current_user.id,
        count=len(models),
    ).info(f"查询生图模型列表: {len(models)} 个")
    return {"ok": True, "models": models}


@router.post("/generate")
async def generate_image_route(
    payload: ImageGenerationGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """手动生图：按配置（或默认生图模型）生成图片，返回 base64 与保存路径。"""
    try:
        result = await generate_image(
            db,
            prompt=payload.prompt,
            config_id=payload.config_id,
            size=payload.size,
            n=payload.n,
            quality=payload.quality,
        )
    except ValueError as exc:
        # 参数或配置错误：显式 400，携带可读错误信息
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # 上游接口异常：显式 502，避免把内部堆栈暴露给调用方
        logger.bind(
            event="image_generation_failed",
            module="image_generation",
            user_id=current_user.id,
            error_type=type(exc).__name__,
        ).error(f"生图失败: {exc}")
        raise HTTPException(status_code=502, detail=f"生图失败: {exc}") from exc

    logger.bind(
        event="image_generation_succeeded",
        module="image_generation",
        user_id=current_user.id,
        model=result["model"]["label"],
        count=result["n"],
    ).info(f"生图成功: {result['model']['label']} 共 {result['n']} 张")
    return result

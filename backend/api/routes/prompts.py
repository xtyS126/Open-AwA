"""
后端接口路由模块，负责接收请求、校验输入并协调业务层返回统一响应。
这些路由函数通常是前端或外部调用与后端内部能力之间的第一层行为边界。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from db.models import get_db, PromptConfig
from api.dependencies import get_current_user
from api.schemas import PromptConfigCreate, PromptConfigUpdate, PromptConfigResponse
import uuid


router = APIRouter(prefix="/prompts", tags=["Prompts"])


@router.get(
    "",
    response_model=List[PromptConfigResponse],
    summary="获取提示词配置列表",
    description="返回当前系统中的全部提示词配置。"
)
async def get_prompts(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取prompts相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    prompts = db.query(PromptConfig).all()
    return prompts


@router.get(
    "/active",
    response_model=PromptConfigResponse,
    summary="获取当前生效的提示词配置",
    description="返回当前被标记为启用状态的提示词配置。"
)
async def get_active_prompt(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取active、prompt相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    prompt = db.query(PromptConfig).filter(PromptConfig.is_active == True).first()
    if prompt:
        return prompt

    # 原子操作：先停用所有已激活的提示词，再激活回退项
    db.query(PromptConfig).filter(PromptConfig.is_active == True).update({"is_active": False})

    fallback_prompt = db.query(PromptConfig).order_by(PromptConfig.updated_at.desc()).first()
    if fallback_prompt:
        fallback_prompt.is_active = True
        db.commit()
        db.refresh(fallback_prompt)
        return fallback_prompt

    default_prompt = PromptConfig(
        id=str(uuid.uuid4()),
        name="System Prompt",
        content="",
        variables="{}",
        is_active=True
    )
    db.add(default_prompt)
    db.commit()
    db.refresh(default_prompt)
    return default_prompt


@router.get(
    "/{prompt_id}",
    response_model=PromptConfigResponse,
    summary="获取单个提示词配置",
    description="根据提示词配置 ID 返回对应的提示词详情。"
)
async def get_prompt(
    prompt_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取prompt相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    prompt = db.query(PromptConfig).filter(PromptConfig.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return prompt


@router.post("", response_model=PromptConfigResponse)
async def create_prompt(
    prompt: PromptConfigCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    创建prompt相关对象、记录或执行结果。
    实现过程中往往会涉及初始化、组装、持久化或返回统一结构。
    """
    new_prompt = PromptConfig(
        id=str(uuid.uuid4()),
        name=prompt.name,
        content=prompt.content,
        variables=prompt.variables,
        is_active=False
    )
    
    db.add(new_prompt)
    db.commit()
    db.refresh(new_prompt)
    
    return new_prompt


@router.put("/{prompt_id}", response_model=PromptConfigResponse)
async def update_prompt(
    prompt_id: str,
    prompt_update: PromptConfigUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    更新prompt相关数据、配置或状态。
    阅读时需要重点关注覆盖规则、副作用以及更新后的数据一致性。
    """
    prompt = db.query(PromptConfig).filter(PromptConfig.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    
    if prompt_update.name is not None:
        prompt.name = prompt_update.name
    if prompt_update.content is not None:
        prompt.content = prompt_update.content
    if prompt_update.variables is not None:
        prompt.variables = prompt_update.variables
    if prompt_update.is_active is not None:
        if prompt_update.is_active:
            db.query(PromptConfig).filter(
                PromptConfig.is_active == True
            ).update({"is_active": False})
        prompt.is_active = prompt_update.is_active
    
    db.commit()
    db.refresh(prompt)
    
    return prompt


@router.delete(
    "/{prompt_id}",
    summary="删除提示词配置",
    description="删除指定的提示词配置。"
)
async def delete_prompt(
    prompt_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    删除prompt相关对象或持久化记录。
    实现中通常还会同时处理资源释放、状态回收或关联数据清理。
    """
    prompt = db.query(PromptConfig).filter(PromptConfig.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    
    db.delete(prompt)
    db.commit()
    
    return {"message": "Prompt deleted successfully"}

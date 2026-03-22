from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from db.models import get_db, PromptConfig
from api.dependencies import get_current_user
from api.schemas import PromptConfigCreate, PromptConfigUpdate, PromptConfigResponse
import uuid


router = APIRouter(prefix="/prompts", tags=["Prompts"])


@router.get("", response_model=List[PromptConfigResponse])
async def get_prompts(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    prompts = db.query(PromptConfig).all()
    return prompts


@router.get("/active", response_model=PromptConfigResponse)
async def get_active_prompt(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    prompt = db.query(PromptConfig).filter(PromptConfig.is_active == True).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="No active prompt found")
    return prompt


@router.get("/{prompt_id}", response_model=PromptConfigResponse)
async def get_prompt(
    prompt_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
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


@router.delete("/{prompt_id}")
async def delete_prompt(
    prompt_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    prompt = db.query(PromptConfig).filter(PromptConfig.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    
    db.delete(prompt)
    db.commit()
    
    return {"message": "Prompt deleted successfully"}

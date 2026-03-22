from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from db.models import get_db, Skill
from api.dependencies import get_current_user, get_current_admin_user
from api.schemas import SkillCreate, SkillResponse
import yaml
import uuid


router = APIRouter(prefix="/skills", tags=["Skills"])


@router.get("", response_model=List[SkillResponse])
async def get_skills(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    skills = db.query(Skill).all()
    return skills


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


@router.post("", response_model=SkillResponse)
async def install_skill(
    skill: SkillCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    existing_skill = db.query(Skill).filter(Skill.name == skill.name).first()
    if existing_skill:
        raise HTTPException(status_code=400, detail="Skill already installed")
    
    try:
        config_dict = yaml.safe_load(skill.config)
    except:
        raise HTTPException(status_code=400, detail="Invalid YAML configuration")
    
    new_skill = Skill(
        id=str(uuid.uuid4()),
        name=skill.name,
        version=skill.version,
        description=skill.description,
        config=yaml.dump(config_dict),
        enabled=True
    )
    
    db.add(new_skill)
    db.commit()
    db.refresh(new_skill)
    
    return new_skill


@router.delete("/{skill_id}")
async def uninstall_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    
    db.delete(skill)
    db.commit()
    
    return {"message": "Skill uninstalled successfully"}


@router.put("/{skill_id}/toggle")
async def toggle_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    
    skill.enabled = not skill.enabled
    db.commit()
    
    return {"message": f"Skill {'enabled' if skill.enabled else 'disabled'}"}

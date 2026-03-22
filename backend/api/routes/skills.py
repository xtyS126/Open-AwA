from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from db.models import get_db, Skill, ExperienceMemory, ExperienceExtractionLog
from api.dependencies import get_current_user, get_current_admin_user
from api.schemas import SkillCreate, SkillResponse
import yaml
import uuid
import json


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


@router.post("/experiences/extract")
async def extract_experience(
    session_id: str,
    user_goal: str,
    execution_steps: List[Dict[str, Any]],
    final_result: str,
    status: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """从会话中提取经验"""
    from skills.experience_extractor import ExperienceExtractor

    extractor = ExperienceExtractor()
    experience = await extractor.extract_from_session(
        user_goal=user_goal,
        execution_steps=execution_steps,
        final_result=final_result,
        status=status,
        session_id=session_id
    )

    if not experience:
        return {"status": "no_experience", "message": "未发现值得提取的经验"}

    new_experience = ExperienceMemory(
        experience_type=experience['experience_type'],
        title=experience['title'],
        content=experience['content'],
        trigger_conditions=experience['trigger_conditions'],
        confidence=experience['confidence'],
        source_task=experience.get('source_task', 'general'),
        experience_metadata=experience.get('metadata', '{}')
    )
    db.add(new_experience)

    log = ExperienceExtractionLog(
        session_id=session_id,
        task_summary=user_goal,
        extracted_experience=json.dumps(experience),
        extraction_trigger='auto' if status == 'success' else 'failure',
        extraction_quality=experience['confidence']
    )
    db.add(log)

    db.commit()
    db.refresh(new_experience)

    return {
        "status": "extracted",
        "experience": {
            "id": new_experience.id,
            "type": new_experience.experience_type,
            "title": new_experience.title
        }
    }

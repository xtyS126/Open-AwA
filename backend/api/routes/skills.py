from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from db.models import get_db, Skill, ExperienceMemory, ExperienceExtractionLog
from api.dependencies import get_current_user, get_current_admin_user
from api.schemas import SkillCreate, SkillResponse, SkillUpdate, SkillExecute, SkillConfigResponse, SkillValidationResult, SkillValidationRequest
from skills.skill_engine import SkillEngine
from skills.skill_validator import SkillValidator
from loguru import logger
import yaml
import uuid
import json
import zipfile
import io


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
    except yaml.YAMLError as e:
        logger.error(f"YAML parsing error in skill config: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid YAML configuration")
    except Exception as e:
        logger.error(f"Unexpected error parsing skill config: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
    
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


@router.put("/{skill_id}", response_model=SkillResponse)
async def update_skill(
    skill_id: str,
    skill_update: SkillUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    if skill_update.name is not None:
        skill.name = skill_update.name
    if skill_update.version is not None:
        skill.version = skill_update.version
    if skill_update.description is not None:
        skill.description = skill_update.description
    if skill_update.enabled is not None:
        skill.enabled = skill_update.enabled
    if skill_update.config is not None:
        try:
            yaml.safe_load(skill_update.config)
            skill.config = skill_update.config
        except yaml.YAMLError as e:
            logger.error(f"YAML parsing error in skill update: {str(e)}")
            raise HTTPException(status_code=400, detail="Invalid YAML configuration")
        except Exception as e:
            logger.error(f"Unexpected error parsing skill update: {str(e)}")
            raise HTTPException(status_code=500, detail="Internal server error")

    db.commit()
    db.refresh(skill)

    logger.info(f"Skill '{skill_id}' updated by user '{current_user.username}'")

    return skill


@router.post("/{skill_id}/execute")
async def execute_skill(
    skill_id: str,
    execution_data: SkillExecute,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    if not skill.enabled:
        raise HTTPException(status_code=400, detail="Skill is disabled")

    try:
        skill_engine = SkillEngine(db)
        skill_config = yaml.safe_load(skill.config)

        result = await skill_engine.execute_skill(
            skill_name=skill.name,
            inputs=execution_data.inputs,
            context=execution_data.context
        )

        logger.info(f"Skill '{skill.name}' executed by user '{current_user.username}'")

        return {
            "status": "success" if result.get("success") else "error",
            "skill_id": skill_id,
            "skill_name": skill.name,
            "result": result
        }

    except Exception as e:
        logger.error(f"Error executing skill '{skill.name}': {str(e)}")
        raise HTTPException(status_code=500, detail=f"Skill execution failed: {str(e)}")


@router.get("/{skill_id}/config", response_model=SkillConfigResponse)
async def get_skill_config(
    skill_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    try:
        config_dict = yaml.safe_load(skill.config)
    except yaml.YAMLError as e:
        logger.error(f"YAML parsing error getting skill config: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to parse skill configuration")
    except Exception as e:
        logger.error(f"Unexpected error getting skill config: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return SkillConfigResponse(
        skill_id=skill.id,
        name=skill.name,
        version=skill.version,
        description=skill.description,
        config=config_dict,
        enabled=skill.enabled,
        installed_at=skill.installed_at
    )


@router.post("/validate", response_model=SkillValidationResult)
async def validate_skill(
    validation_request: SkillValidationRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    try:
        yaml.safe_load(validation_request.yaml_content)
    except yaml.YAMLError as e:
        return SkillValidationResult(
            valid=False,
            errors=[f"Invalid YAML format: {str(e)}"],
            warnings=[]
        )

    try:
        config = yaml.safe_load(validation_request.yaml_content)

        if not isinstance(config, dict):
            return SkillValidationResult(
                valid=False,
                errors=["Configuration must be a dictionary"],
                warnings=[]
            )

        validator = SkillValidator()
        result = validator.validate_skill_config(config)

        return SkillValidationResult(
            valid=result.valid,
            errors=result.errors,
            warnings=result.warnings,
            skill_name=config.get("name"),
            version=config.get("version")
        )

    except Exception as e:
        logger.error(f"Error validating skill configuration: {str(e)}")
        return SkillValidationResult(
            valid=False,
            errors=[f"Validation error: {str(e)}"],
            warnings=[]
        )

@router.post("/parse-upload")
async def parse_skill_upload(
    file: UploadFile = File(...),
    current_user = Depends(get_current_user)
):
    content = await file.read()
    filename = file.filename
    
    skill_content = ""
    
    if filename.endswith('.zip') or filename.endswith('.skill'):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                if 'SKILL.md' in z.namelist():
                    skill_content = z.read('SKILL.md').decode('utf-8')
                else:
                    md_files = [f for f in z.namelist() if f.endswith('.md')]
                    if md_files:
                        skill_content = z.read(md_files[0]).decode('utf-8')
                    else:
                        raise HTTPException(status_code=400, detail="No SKILL.md found in the archive")
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid zip file")
    elif filename.endswith('.md') or filename.endswith('.yaml') or filename.endswith('.yml'):
        skill_content = content.decode('utf-8')
    else:
        raise HTTPException(status_code=400, detail="Unsupported file format")
        
    name = filename.split('.')[0]
    description = ""
    instructions = skill_content
    
    try:
        if skill_content.startswith('---'):
            parts = skill_content.split('---', 2)
            if len(parts) >= 3:
                frontmatter = yaml.safe_load(parts[1])
                name = frontmatter.get('name', name)
                description = frontmatter.get('description', description)
                instructions = parts[2].strip()
        else:
            data = yaml.safe_load(skill_content)
            if isinstance(data, dict):
                name = data.get('name', name)
                description = data.get('description', description)
                instructions = data.get('instructions', skill_content)
    except Exception:
        pass
        
    return {
        "name": name,
        "description": description,
        "instructions": instructions
    }

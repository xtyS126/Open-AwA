from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from db.models import get_db, Skill, ExperienceExtractionLog
from api.dependencies import get_current_user
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


from pydantic import BaseModel
from typing import Optional

class WeixinConfigReq(BaseModel):
    account_id: str
    token: str
    base_url: Optional[str] = "https://ilinkai.weixin.qq.com"
    timeout_seconds: Optional[int] = 15

@router.post("/weixin/health-check")
async def weixin_health_check(config: WeixinConfigReq):
    from skills.weixin_skill_adapter import WeixinSkillAdapter, WeixinRuntimeConfig
    adapter = WeixinSkillAdapter()
    runtime_config = WeixinRuntimeConfig(
        account_id=config.account_id,
        token=config.token,
        base_url=config.base_url or "https://ilinkai.weixin.qq.com",
        bot_type="3",
        channel_version="1.0.2",
        timeout_seconds=config.timeout_seconds or 15,
        plugin_root=adapter.default_plugin_root,
        require_node=True,
        min_node_major=22
    )
    result = adapter.check_health(runtime_config)
    return result

@router.post("/weixin/config")
async def save_weixin_config(
    config: WeixinConfigReq,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    skill_name = "weixin_dispatch"
    skill = db.query(Skill).filter(Skill.name == skill_name).first()
    
    config_dict = {
        "name": skill_name,
        "version": "1.0.0",
        "description": "Weixin Clawbot communication skill",
        "adapter": "weixin",
        "weixin": {
            "account_id": config.account_id,
            "token": config.token,
            "base_url": config.base_url or "https://ilinkai.weixin.qq.com",
            "timeout_seconds": config.timeout_seconds or 15
        }
    }
    config_yaml = yaml.dump(config_dict)
    
    if skill:
        skill.config = config_yaml
    else:
        skill = Skill(
            id=str(uuid.uuid4()),
            name=skill_name,
            version="1.0.0",
            description="Weixin Clawbot communication skill",
            config=config_yaml,
            category="general",
            tags="[]",
            dependencies="[]",
            author="system",
            enabled=True
        )
        db.add(skill)
        
    db.commit()
    return {"message": "success"}

@router.get("/weixin/config")
async def get_weixin_config(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    skill = db.query(Skill).filter(Skill.name == "weixin_dispatch").first()
    if not skill:
        return {"account_id": "", "token": "", "base_url": "https://ilinkai.weixin.qq.com", "timeout_seconds": 15}
    
    try:
        config_dict = yaml.safe_load(skill.config)
        wx_config = config_dict.get("weixin", {})
        return {
            "account_id": wx_config.get("account_id", ""),
            "token": wx_config.get("token", ""),
            "base_url": wx_config.get("base_url", "https://ilinkai.weixin.qq.com"),
            "timeout_seconds": wx_config.get("timeout_seconds", 15)
        }
    except:
        return {"account_id": "", "token": "", "base_url": "https://ilinkai.weixin.qq.com", "timeout_seconds": 15}

@router.get(
    "",
    response_model=List[SkillResponse],
    summary="获取技能列表",
    description="返回系统中已安装的技能列表。"
)
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


@router.post(
    "",
    response_model=SkillResponse,
    summary="安装技能",
    description="安装新的技能配置；若同名技能已存在则返回错误。"
)
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

    log = ExperienceExtractionLog(
        user_id=current_user.id,
        session_id=session_id,
        task_summary=user_goal,
        extracted_experience=json.dumps(experience, ensure_ascii=False),
        extraction_trigger='auto' if status == 'success' else 'failure',
        extraction_quality=experience['confidence']
    )
    db.add(log)
    db.commit()

    return {
        "status": "extracted",
        "experience": {
            "type": experience['experience_type'],
            "title": experience['title'],
            "confidence": experience['confidence'],
            "file": experience.get('save_result')
        }
    }



@router.put(
    "/{skill_id}",
    response_model=SkillResponse,
    summary="更新技能",
    description="更新技能的名称、版本、描述、配置或启用状态。"
)
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


@router.post(
    "/{skill_id}/execute",
    summary="执行技能",
    description="按输入参数执行指定技能，并返回执行结果。"
)
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


@router.post(
    "/validate",
    response_model=SkillValidationResult,
    summary="校验技能配置",
    description="校验上传或输入的技能 YAML 配置是否合法。"
)
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
    
    if not filename or filename.endswith('.zip') or filename.endswith('.skill'):
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
    elif filename and (filename.endswith('.md') or filename.endswith('.yaml') or filename.endswith('.yml')):
        skill_content = content.decode('utf-8')
    else:
        raise HTTPException(status_code=400, detail="Unsupported file format")
        
    name = (filename or "").split('.')[0]
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

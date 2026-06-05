"""
后端接口路由模块，负责接收请求、校验输入并协调业务层返回统一响应。
这些路由函数通常是前端或外部调用与后端内部能力之间的第一层行为边界。
"""

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from db.models import get_db, Skill, ExperienceExtractionLog, SkillExecutionLog
from api.dependencies import get_current_user
from api.schemas import SkillCreate, SkillResponse, SkillUpdate, SkillExecute, SkillConfigResponse, SkillValidationResult, SkillValidationRequest
from skills.skill_engine import SkillEngine
from skills.skill_validator import SkillValidator
from skills.skill_security import SkillSecurityScanner
from config.logging import sanitize_for_logging
from loguru import logger
import yaml
import uuid
import json
import zipfile
import io


router = APIRouter(prefix="/skills", tags=["Skills"])


MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB
MAX_ZIP_FILES = 100
MAX_ZIP_EXTRACTION_SIZE = 200 * 1024 * 1024  # 200MB


def _deserialize_skill_config(config_value: Any) -> Dict[str, Any]:
    """
    统一解析 Skill.config，兼容 JSON 列中的字典对象以及历史遗留的 YAML/JSON 字符串。
    此函数被 skills.py 和 weixin_skill.py 共享使用。
    """
    if isinstance(config_value, dict):
        return dict(config_value)
    if config_value is None:
        return {}

    text = str(config_value or "").strip()
    if not text:
        return {}

    try:
        loaded = json.loads(text)
    except Exception:
        loaded = None
    if isinstance(loaded, dict):
        return loaded

    try:
        loaded = yaml.safe_load(text)
    except Exception:
        return {}
    if isinstance(loaded, dict):
        return loaded
    return {}


def _build_skill_response(skill: Skill) -> SkillResponse:
    """
    将 ORM Skill 统一转换为响应模型，避免配置字段因历史格式差异触发序列化异常。
    """
    return SkillResponse(
        id=skill.id,
        name=skill.name,
        version=skill.version,
        description=skill.description,
        config=_deserialize_skill_config(skill.config),
        enabled=skill.enabled,
        installed_at=skill.installed_at,
    )


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
    """
    获取skills相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    try:
        skills = db.query(Skill).all()
        return [_build_skill_response(skill) for skill in skills]
    except Exception as e:
        logger.bind(
            event="skills_list_error",
            module="skills",
            error_type=type(e).__name__,
            error_message=sanitize_for_logging(str(e)),
        ).opt(exception=True).error(f"获取技能列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取技能列表失败: {str(e)}")


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取skill相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    try:
        skill = db.query(Skill).filter(Skill.id == skill_id).first()
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")
        return _build_skill_response(skill)
    except HTTPException:
        raise
    except Exception as e:
        logger.bind(
            event="skill_get_error",
            module="skills",
            skill_id=skill_id,
            error_type=type(e).__name__,
            error_message=sanitize_for_logging(str(e)),
        ).opt(exception=True).error(f"获取技能详情失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取技能详情失败: {str(e)}")


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
    """
    处理install、skill相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    existing_skill = db.query(Skill).filter(Skill.name == skill.name).first()
    if existing_skill:
        raise HTTPException(status_code=400, detail="Skill already installed")
    
    try:
        config_dict = yaml.safe_load(skill.config)
    except yaml.YAMLError as e:
        logger.bind(
            event="skill_install_invalid_yaml",
            module="skills",
            action="install_skill",
            status="failure",
            skill_name=skill.name,
            error_type=type(e).__name__,
            error_message=sanitize_for_logging(str(e)),
        ).error("skill install yaml parsing failed")
        raise HTTPException(status_code=400, detail="Invalid YAML configuration")
    except Exception as e:
        logger.bind(
            event="skill_install_error",
            module="skills",
            action="install_skill",
            status="failure",
            skill_name=skill.name,
            error_type=type(e).__name__,
            error_message=sanitize_for_logging(str(e)),
        ).error("unexpected skill install error")
        raise HTTPException(status_code=500, detail="Internal server error")
    
    new_skill = Skill(
        id=str(uuid.uuid4()),
        name=skill.name,
        version=skill.version or "1.0.0",
        description=skill.description or "",
        config=config_dict,
        category=str(config_dict.get("category") or "general"),
        tags=config_dict.get("tags") if isinstance(config_dict.get("tags"), list) else [],
        dependencies=config_dict.get("dependencies") if isinstance(config_dict.get("dependencies"), list) else [],
        author=str(config_dict.get("author") or "unknown"),
        enabled=True
    )
    
    db.add(new_skill)
    db.commit()
    db.refresh(new_skill)

    logger.bind(
        event="skill_installed",
        module="skills",
        action="install_skill",
        status="success",
        skill_id=new_skill.id,
        skill_name=new_skill.name,
        user_id=current_user.id,
    ).info("skill installed")
    
    return _build_skill_response(new_skill)


@router.delete("/{skill_id}")
async def uninstall_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    处理uninstall、skill相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
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
    """
    处理toggle、skill相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
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
    """
    处理extract、experience相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    from skills.experience_extractor import ExperienceExtractor

    try:
        extractor = ExperienceExtractor()
        experience = await extractor.extract_from_session(
            user_goal=user_goal,
            execution_steps=execution_steps,
            final_result=final_result,
            status=status,
            session_id=session_id
        )
    except Exception as exc:
        logger.bind(
            event="experience_extraction_error",
            module="skills",
            session_id=session_id,
        ).error(f"经验提取失败: {exc}")
        return {"status": "error", "message": f"经验提取失败: {str(exc)}"}

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
    """
    更新skill相关数据、配置或状态。
    阅读时需要重点关注覆盖规则、副作用以及更新后的数据一致性。
    """
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
            parsed_config = yaml.safe_load(skill_update.config)
            if parsed_config is None:
                parsed_config = {}
            if not isinstance(parsed_config, dict):
                raise HTTPException(status_code=400, detail="Skill configuration must be an object")
            skill.config = parsed_config
        except yaml.YAMLError as e:
            logger.bind(
                event="skill_update_config_invalid_yaml",
                module="skills",
                action="update_skill",
                status="failure",
                skill_id=skill_id,
                error_type=type(e).__name__,
                error_message=sanitize_for_logging(str(e)),
            ).error("skill update yaml parsing failed")
            raise HTTPException(status_code=400, detail="Invalid YAML configuration")
        except HTTPException:
            raise
        except Exception as e:
            logger.bind(
                event="skill_update_config_error",
                module="skills",
                action="update_skill",
                status="failure",
                skill_id=skill_id,
                error_type=type(e).__name__,
                error_message=sanitize_for_logging(str(e)),
            ).error("unexpected skill update config error")
            raise HTTPException(status_code=500, detail="Internal server error")

    db.commit()
    db.refresh(skill)

    logger.bind(
        event="skill_updated",
        module="skills",
        action="update_skill",
        status="success",
        skill_id=skill_id,
        skill_name=skill.name,
        user_id=current_user.id,
    ).info("skill updated")

    return _build_skill_response(skill)


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
    """
    处理execute、skill相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    if not skill.enabled:
        raise HTTPException(status_code=400, detail="Skill is disabled")

    logger.bind(
        event="skill_execute_started",
        module="skills",
        action="execute_skill",
        status="start",
        skill_id=skill_id,
        skill_name=skill.name,
        user_id=current_user.id,
    ).info("skill execute started")

    try:
        skill_engine = SkillEngine(db)

        result = await skill_engine.execute_skill(
            skill_name=skill.name,
            inputs=execution_data.inputs,
            context=execution_data.context
        )

        result_status = "success" if result.get("success") else "error"
        logger.bind(
            event="skill_execute_finished",
            module="skills",
            action="execute_skill",
            status=result_status,
            skill_id=skill_id,
            skill_name=skill.name,
            user_id=current_user.id,
            success=bool(result.get("success")),
        ).info("skill execute finished")

        return {
            "status": result_status,
            "skill_id": skill_id,
            "skill_name": skill.name,
            "result": result
        }

    except Exception as e:
        logger.bind(
            event="skill_execute_failed",
            module="skills",
            action="execute_skill",
            status="failure",
            skill_id=skill_id,
            skill_name=skill.name,
            user_id=current_user.id,
            error_type=type(e).__name__,
            error_message=sanitize_for_logging(str(e)),
        ).exception("skill execute failed")
        raise HTTPException(status_code=500, detail=f"Skill execution failed: {str(e)}")


@router.get("/{skill_id}/config", response_model=SkillConfigResponse)
async def get_skill_config(
    skill_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取skill、config相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    config_dict = _deserialize_skill_config(skill.config)

    return SkillConfigResponse(
        skill_id=skill.id,
        name=skill.name,
        version=skill.version,
        description=skill.description,
        config=config_dict,
        enabled=skill.enabled
    )


@router.post("/validate", response_model=SkillValidationResult)
async def validate_skill(skill_data: SkillValidationRequest):
    """
    校验skill相关输入、规则或结构是否合法。
    返回结果通常用于阻止非法输入继续流入后续链路。
    """
    validator = SkillValidator()
    try:
        config_dict = yaml.safe_load(skill_data.yaml_content)
        if not isinstance(config_dict, dict):
            return SkillValidationResult(
                valid=False,
                errors=["YAML 内容必须是一个字典/对象"],
                warnings=[],
            )
    except yaml.YAMLError as e:
        return SkillValidationResult(
            valid=False,
            errors=[f"YAML 解析失败: {str(e)}"],
            warnings=[],
        )
    validation_result = validator.validate_skill_config(config_dict)
    return SkillValidationResult(
        valid=validation_result.valid,
        errors=validation_result.errors,
        warnings=validation_result.warnings,
        skill_name=config_dict.get("name"),
        version=config_dict.get("version"),
    )


@router.post("/install-from-package")
async def install_skill_from_package(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    处理install、skill、from、package相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    try:
        if file.content_type and file.content_type not in ["application/zip", "application/x-zip-compressed"]:
            raise HTTPException(status_code=400, detail="Only ZIP files are allowed")
        if file.size is not None and file.size > MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=400, detail=f"文件大小超过限制 ({MAX_UPLOAD_SIZE // (1024*1024)}MB)")
        content = await file.read()
        if len(content) > MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=400, detail=f"文件大小超过限制 ({MAX_UPLOAD_SIZE // (1024*1024)}MB)")
        zip_file = zipfile.ZipFile(io.BytesIO(content))
        
        if len(zip_file.namelist()) > MAX_ZIP_FILES:
            raise HTTPException(status_code=400, detail=f"ZIP文件中文件数量超过限制 ({MAX_ZIP_FILES})")
        
        for member in zip_file.namelist():
            if member.startswith('/') or '..' in member:
                raise HTTPException(status_code=400, detail="非法的ZIP文件路径")
            info = zip_file.getinfo(member)
            if info.file_size > MAX_UPLOAD_SIZE:
                raise HTTPException(status_code=400, detail=f"ZIP中单个文件大小超过限制 ({MAX_UPLOAD_SIZE // (1024*1024)}MB)")
        
        config_files = [name for name in zip_file.namelist() if name.endswith('skill.yaml') or name.endswith('skill.yml')]
        if not config_files:
            raise HTTPException(status_code=400, detail="技能包中未找到skill.yaml配置文件")
        
        config_content = zip_file.read(config_files[0]).decode('utf-8')
        config_dict = yaml.safe_load(config_content)
        
        required_fields = ['name', 'version', 'description', 'adapter']
        for field in required_fields:
            if field not in config_dict:
                raise HTTPException(status_code=400, detail=f"技能配置缺少必需字段: {field}")

        # 安装前安全扫描
        scanner = SkillSecurityScanner()
        scan_result = scanner.scan_skill_config(config_dict)
        if not scan_result.is_safe:
            threat_descriptions = [t.description for t in scan_result.threats]
            logger.bind(
                event="skill_security_blocked",
                module="skills",
                skill_name=config_dict.get('name'),
                threats=threat_descriptions,
                user_id=current_user.id,
            ).warning("技能安装被安全扫描拦截")
            raise HTTPException(
                status_code=400,
                detail=f"技能安全扫描未通过: {'; '.join(threat_descriptions)}",
            )
        if scan_result.threats:
            logger.bind(
                event="skill_security_warning",
                module="skills",
                skill_name=config_dict.get('name'),
                threat_count=len(scan_result.threats),
            ).info(f"技能通过安全扫描，但存在 {len(scan_result.threats)} 个低级别警告")

        existing_skill = db.query(Skill).filter(Skill.name == config_dict['name']).first()
        if existing_skill:
            raise HTTPException(status_code=400, detail=f"技能 '{config_dict['name']}' 已存在")
        
        new_skill = Skill(
            id=str(uuid.uuid4()),
            name=config_dict['name'],
            version=config_dict['version'],
            description=config_dict['description'],
            config=config_content,
            category=config_dict.get('category', 'general'),
            tags=config_dict.get('tags', []),
            dependencies=config_dict.get('dependencies', []),
            author=config_dict.get('author', 'unknown'),
            enabled=True
        )
        
        db.add(new_skill)
        db.commit()
        db.refresh(new_skill)
        
        logger.bind(
            event="skill_installed_from_package",
            module="skills",
            action="install_from_package",
            status="success",
            skill_name=new_skill.name,
            user_id=current_user.id,
        ).info("skill installed from package")
        
        return {
            "message": f"技能 '{new_skill.name}' 安装成功",
            "skill": new_skill
        }
        
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="无效的ZIP文件")
    except yaml.YAMLError as e:
        logger.bind(
            event="skill_install_package_invalid_yaml",
            module="skills",
            action="install_from_package",
            status="failure",
            error_type=type(e).__name__,
            error_message=sanitize_for_logging(str(e)),
        ).error("skill package yaml parsing failed")
        raise HTTPException(status_code=400, detail="技能配置文件格式错误")
    except HTTPException:
        raise
    except Exception as e:
        logger.bind(
            event="skill_install_package_error",
            module="skills",
            action="install_from_package",
            status="failure",
            error_type=type(e).__name__,
            error_message=sanitize_for_logging(str(e)),
        ).exception("skill install from package failed")
        raise HTTPException(status_code=500, detail=f"安装技能失败: {str(e)}")


# ---- 技能市场端点 ----

class MarketSkillInstallRequest(BaseModel):
    """技能市场安装请求。"""
    name: str
    source: Optional[str] = "clawhub"
    source_url: Optional[str] = None


def _calculate_security_rating(skill: Dict[str, Any]) -> int:
    """
    根据技能元数据计算安全评级（0-100分）。
    扣分项：高危来源、无描述、依赖过多、下载量过低。
    """
    score = 85  # 基础分

    # 来源信任度
    source = skill.get("source", "")
    source_trust = {"clawhub": 0, "skills.sh": 0, "github": -10, "unknown": -15}
    score += source_trust.get(source, -5)

    # 描述质量
    desc = skill.get("description", "")
    if not desc or len(desc) < 20:
        score -= 15

    # 下载量信号
    downloads = skill.get("downloads", 0)
    if downloads < 10:
        score -= 5
    elif downloads > 1000:
        score += 5

    # 作者信誉
    author = skill.get("author", "").lower()
    if author in ("community", "unknown", ""):
        score -= 5

    return max(0, min(100, score))


@router.get("/market")
def get_market_skills(
    search: Optional[str] = None,
    source: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """
    获取技能市场中的可用技能列表。
    支持按关键词搜索和按来源筛选，返回结果包含安全评级。
    """
    from skills.pool_manager import SkillPoolManager

    pool = SkillPoolManager()
    skills = pool.fetch_market_listing()

    # 筛选
    if source:
        skills = [s for s in skills if s["source"] == source]
    if search:
        keyword = search.lower()
        skills = [
            s for s in skills
            if keyword in s["name"].lower() or keyword in s["description"].lower()
        ]

    # 附加安全评级
    for skill in skills:
        skill["security_score"] = _calculate_security_rating(skill)

    return {"skills": skills, "total": len(skills)}


@router.post("/market/install")
def install_market_skill(
    body: MarketSkillInstallRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """
    从技能市场安装技能到技能池。
    """
    from skills.pool_manager import SkillPoolManager

    pool = SkillPoolManager()
    url = body.source_url
    if not url:
        # 从市场 URL 构造导入地址
        if body.source == "clawhub":
            url = f"https://clawhub.ai/api/skills/{body.name}/download"
        elif body.source == "skills.sh":
            url = f"https://skills.sh/api/skills/{body.name}/download"
        else:
            url = f"https://github.com/anthropics/skills/tree/main/skills/{body.name}"

    result = pool.import_from_url(url)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "安装失败"))

    return {"message": f"技能 {body.name} 安装成功", "result": result}


# ---- 技能执行分析端点 ----

@router.get("/analytics/overview")
def get_skill_analytics_overview(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    获取技能执行的全局统计概览。
    包含执行次数、成功率、平均耗时和 Top 技能排行。
    """
    total = db.query(func.count(SkillExecutionLog.id)).scalar() or 0
    success_count = db.query(func.count(SkillExecutionLog.id)).filter(
        SkillExecutionLog.status == "success"
    ).scalar() or 0
    fail_count = total - success_count
    success_rate = round(success_count / total * 100, 1) if total > 0 else 0.0

    avg_time = db.query(func.avg(SkillExecutionLog.execution_time)).scalar() or 0.0
    max_time = db.query(func.max(SkillExecutionLog.execution_time)).scalar() or 0.0

    # Top 5 最多执行的技能
    top_skills = (
        db.query(
            SkillExecutionLog.skill_name,
            func.count(SkillExecutionLog.id).label("count"),
            func.avg(SkillExecutionLog.execution_time).label("avg_time"),
            func.sum(
                func.case((SkillExecutionLog.status == "success", 1), else_=0)
            ).label("successes"),
        )
        .group_by(SkillExecutionLog.skill_name)
        .order_by(func.count(SkillExecutionLog.id).desc())
        .limit(5)
        .all()
    )

    return {
        "total_executions": total,
        "success_count": success_count,
        "fail_count": fail_count,
        "success_rate": success_rate,
        "avg_execution_time": round(float(avg_time), 3),
        "max_execution_time": round(float(max_time), 3),
        "top_skills": [
            {
                "skill_name": s.skill_name,
                "executions": s.count,
                "success_rate": round(s.successes / s.count * 100, 1) if s.count > 0 else 0,
                "avg_time": round(float(s.avg_time or 0), 3),
            }
            for s in top_skills
        ],
    }


@router.get("/analytics/logs")
def get_skill_execution_logs(
    skill_name: Optional[str] = Query(None, description="按技能名称筛选"),
    status: Optional[str] = Query(None, description="按状态筛选(success/error)"),
    days: int = Query(7, ge=1, le=90, description="最近N天"),
    limit: int = Query(50, ge=1, le=500, description="返回条数"),
    offset: int = Query(0, ge=0, description="偏移量"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    获取技能执行日志列表，支持按技能名称/状态/时间范围筛选和分页。
    """
    query = db.query(SkillExecutionLog)

    if skill_name:
        query = query.filter(SkillExecutionLog.skill_name == skill_name)
    if status:
        query = query.filter(SkillExecutionLog.status == status)

    cutoff = datetime.utcnow() - timedelta(days=days)
    query = query.filter(SkillExecutionLog.created_at >= cutoff)

    total = query.count()
    logs = (
        query.order_by(SkillExecutionLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "logs": [
            {
                "id": log.id,
                "skill_id": log.skill_id,
                "skill_name": log.skill_name,
                "status": log.status,
                "execution_time": log.execution_time,
                "error_message": log.error_message[:200] if log.error_message else "",
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    }

"""
技能系统模块，负责技能注册、加载、校验、执行或适配外部能力。
当 Agent 需要调用外部能力时，通常会经过这一层完成查找、验证与执行。
"""

import json
import uuid
from typing import Dict, List, Optional
from loguru import logger

from db.models import Skill


class SkillRegistry:
    """
    封装与SkillRegistry相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(self, db_session):
        """初始化技能注册表：绑定数据库会话，初始化内存缓存字典。"""
        self.db = db_session
        self._cache: Dict[str, Skill] = {}

    def register(self, skill_config: Dict) -> Skill:
        """注册新技能：若同名技能已存在则更新，否则创建新记录并加入缓存。"""
        skill_name = skill_config.get('name') or ""
        existing_skill = self.get(skill_name or "")
        if existing_skill:
            logger.warning(f"Skill '{skill_name}' already exists, updating existing skill")
            return self._update_skill(existing_skill, skill_config)

        skill_id = str(uuid.uuid4())
        skill = Skill(
            id=skill_id,
            name=skill_name,
            version=skill_config.get('version', '1.0.0'),
            description=skill_config.get('description', ''),
            config=json.dumps(skill_config.get('config', {})),
            enabled=skill_config.get('enabled', True),
            usage_count=0
        )

        self.db.add(skill)
        self.db.commit()
        self.db.refresh(skill)

        self._cache[skill_name] = skill
        logger.info(f"Skill '{skill_name}' registered successfully with id {skill_id}")

        return skill

    def _update_skill(self, skill: Skill, skill_config: Dict) -> Skill:
        """更新已有技能：合并配置字段并刷新数据库和缓存。"""
        if 'version' in skill_config:
            skill.version = skill_config['version']
        if 'description' in skill_config:
            skill.description = skill_config['description']
        if 'config' in skill_config:
            skill.config = json.dumps(skill_config['config'])
        if 'enabled' in skill_config:
            skill.enabled = skill_config['enabled']

        self.db.commit()
        self.db.refresh(skill)

        self._cache[skill.name] = skill
        logger.info(f"Skill '{skill.name}' updated successfully")

        return skill

    def unregister(self, skill_name: str) -> bool:
        """注销指定技能：从数据库和缓存中移除。"""
        skill = self.get(skill_name)
        if not skill:
            logger.warning(f"Skill '{skill_name}' not found for unregistration")
            return False

        self.db.delete(skill)
        self.db.commit()

        if skill_name in self._cache:
            del self._cache[skill_name]

        logger.info(f"Skill '{skill_name}' unregistered successfully")
        return True

    def get(self, skill_name: str) -> Optional[Skill]:
        """按名称获取技能：优先从缓存读取，缓存未命中时查数据库。"""
        if skill_name in self._cache:
            logger.debug(f"Skill '{skill_name}' retrieved from cache")
            return self._cache[skill_name]

        skill = self.db.query(Skill).filter(Skill.name == skill_name).first()
        if skill:
            self._cache[skill_name] = skill
            logger.debug(f"Skill '{skill_name}' retrieved from database and cached")
        else:
            logger.debug(f"Skill '{skill_name}' not found")

        return skill

    def list_all(self, filters: Optional[Dict] = None) -> List[Skill]:
        """
        列出all相关内容，便于调用方查看、筛选或批量处理。
        返回结果通常会被页面展示、审计流程或后续操作复用。
        """
        query = self.db.query(Skill)

        if filters:
            if 'enabled' in filters:
                query = query.filter(Skill.enabled == filters['enabled'])
            if 'min_usage_count' in filters:
                query = query.filter(Skill.usage_count >= filters['min_usage_count'])
            if 'name_contains' in filters:
                query = query.filter(Skill.name.contains(filters['name_contains']))

        skills = query.all()
        # 预热缓存：将本次查询的所有技能填入内存缓存，
        # 避免后续 get(skill_name) 调用对每个技能都触发数据库查询。
        for skill in skills:
            self._cache[skill.name] = skill
        logger.debug(f"Listed {len(skills)} skills with filters: {filters}")
        return skills

    def enable(self, skill_name: str) -> bool:
        """启用指定技能：设置 enabled=True 并持久化。"""
        skill = self.get(skill_name)
        if not skill:
            logger.warning(f"Skill '{skill_name}' not found for enabling")
            return False

        if skill.enabled:
            logger.info(f"Skill '{skill_name}' is already enabled")
            return True

        skill.enabled = True
        self.db.commit()
        self._cache[skill_name] = skill
        logger.info(f"Skill '{skill_name}' enabled successfully")
        return True

    def disable(self, skill_name: str) -> bool:
        """禁用指定技能：设置 enabled=False 并持久化。"""
        skill = self.get(skill_name)
        if not skill:
            logger.warning(f"Skill '{skill_name}' not found for disabling")
            return False

        if not skill.enabled:
            logger.info(f"Skill '{skill_name}' is already disabled")
            return True

        skill.enabled = False
        self.db.commit()
        self._cache[skill_name] = skill
        logger.info(f"Skill '{skill_name}' disabled successfully")
        return True

    def increment_usage(self, skill_name: str) -> bool:
        """
        处理increment、usage相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        skill = self.get(skill_name)
        if not skill:
            logger.warning(f"Skill '{skill_name}' not found for usage increment")
            return False

        skill.usage_count += 1
        self.db.commit()
        self._cache[skill_name] = skill
        logger.debug(f"Skill '{skill_name}' usage count incremented to {skill.usage_count}")
        return True

    def get_usage_count(self, skill_name: str) -> Optional[int]:
        """
        获取usage、count相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        skill = self.get(skill_name)
        if not skill:
            logger.warning(f"Skill '{skill_name}' not found for usage count retrieval")
            return None
        return skill.usage_count

    def clear_cache(self) -> None:
        """
        处理clear、cache相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._cache.clear()
        logger.info("Skill cache cleared")

    def refresh_cache(self) -> int:
        """
        处理refresh、cache相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._cache.clear()
        skills = self.db.query(Skill).all()
        for skill in skills:
            self._cache[skill.name] = skill
        logger.info(f"Skill cache refreshed with {len(skills)} skills")
        return len(skills)

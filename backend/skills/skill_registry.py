import json
import uuid
from typing import Dict, List, Optional, Any
from loguru import logger

from db.models import Skill


class SkillRegistry:
    def __init__(self, db_session):
        self.db = db_session
        self._cache: Dict[str, Skill] = {}

    def register(self, skill_config: Dict) -> Skill:
        skill_name = skill_config.get('name')
        existing_skill = self.get(skill_name)
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

    def list_all(self, filters: Dict = None) -> List[Skill]:
        query = self.db.query(Skill)

        if filters:
            if 'enabled' in filters:
                query = query.filter(Skill.enabled == filters['enabled'])
            if 'min_usage_count' in filters:
                query = query.filter(Skill.usage_count >= filters['min_usage_count'])
            if 'name_contains' in filters:
                query = query.filter(Skill.name.contains(filters['name_contains']))

        skills = query.all()
        logger.debug(f"Listed {len(skills)} skills with filters: {filters}")
        return skills

    def enable(self, skill_name: str) -> bool:
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
        skill = self.get(skill_name)
        if not skill:
            logger.warning(f"Skill '{skill_name}' not found for usage count retrieval")
            return None
        return skill.usage_count

    def clear_cache(self) -> None:
        self._cache.clear()
        logger.info("Skill cache cleared")

    def refresh_cache(self) -> int:
        self._cache.clear()
        skills = self.db.query(Skill).all()
        for skill in skills:
            self._cache[skill.name] = skill
        logger.info(f"Skill cache refreshed with {len(skills)} skills")
        return len(skills)

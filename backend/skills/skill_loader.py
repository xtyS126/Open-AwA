import yaml
import time
import uuid
from typing import Dict, List, Optional, Any
from datetime import datetime

from loguru import logger
from db.models import Skill


class SkillLoader:
    def __init__(self, db_session):
        self.db_session = db_session
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl: int = 300
        self._cache_timestamps: Dict[str, float] = {}

    def _get_cache_key(self, identifier: str, source: str) -> str:
        return f"{source}:{identifier}"

    def _is_cache_valid(self, cache_key: str) -> bool:
        if cache_key not in self._cache_timestamps:
            return False
        return (time.time() - self._cache_timestamps[cache_key]) < self._cache_ttl

    def _set_cache(self, cache_key: str, value: Dict[str, Any]) -> None:
        self._cache[cache_key] = value
        self._cache_timestamps[cache_key] = time.time()

    def _get_from_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        if self._is_cache_valid(cache_key):
            return self._cache.get(cache_key)
        return None

    def _clear_cache(self, cache_key: Optional[str] = None) -> None:
        if cache_key:
            self._cache.pop(cache_key, None)
            self._cache_timestamps.pop(cache_key, None)
        else:
            self._cache.clear()
            self._cache_timestamps.clear()

    def load_from_file(self, file_path: str) -> Dict[str, Any]:
        cache_key = self._get_cache_key(file_path, "file")
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            logger.info(f"Loaded skill config from cache: {file_path}")
            return cached

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                yaml_content = f.read()
            config = self.parse_config(yaml_content)
            self._set_cache(cache_key, config)
            logger.info(f"Loaded skill config from file: {file_path}")
            return config
        except FileNotFoundError:
            logger.error(f"Skill config file not found: {file_path}")
            raise
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse YAML file {file_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to load skill config from file {file_path}: {e}")
            raise

    def load_from_db(self, skill_name: str) -> Optional[Dict]:
        cache_key = self._get_cache_key(skill_name, "db")
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            logger.info(f"Loaded skill from database cache: {skill_name}")
            return cached

        skill_record = self.db_session.query(Skill).filter(Skill.name == skill_name).first()
        if not skill_record:
            logger.warning(f"Skill not found in database: {skill_name}")
            return None

        if not skill_record.enabled:
            logger.info(f"Skill is disabled: {skill_name}")
            return None

        try:
            config = yaml.safe_load(skill_record.config) if skill_record.config else {}
            self._set_cache(cache_key, config)
            logger.info(f"Loaded skill from database: {skill_name}")
            return config
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse skill config from database for {skill_name}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to load skill from database {skill_name}: {e}")
            return None

    def parse_config(self, yaml_content: str) -> Dict[str, Any]:
        try:
            config = yaml.safe_load(yaml_content)
            if config is None:
                logger.warning("Empty YAML content")
                return {}
            if not isinstance(config, dict):
                logger.error("YAML content must be a dictionary")
                raise ValueError("YAML content must be a dictionary")
            logger.debug(f"Parsed YAML config with {len(config)} keys")
            return config
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse YAML content: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error parsing YAML: {e}")
            raise

    def convert_to_skill_model(self, config: Dict) -> Skill:
        skill_id = config.get('id') or str(uuid.uuid4())
        name = config.get('name')
        if not name:
            raise ValueError("Skill name is required in config")

        version = config.get('version', '1.0.0')
        description = config.get('description', '')
        config_text = yaml.dump(config)

        existing_skill = self.db_session.query(Skill).filter(Skill.name == name).first()

        if existing_skill:
            existing_skill.version = version
            existing_skill.description = description
            existing_skill.config = config_text
            logger.info(f"Updated existing skill: {name}")
            return existing_skill
        else:
            skill = Skill(
                id=skill_id,
                name=name,
                version=version,
                description=description,
                config=config_text,
                enabled=True,
                installed_at=datetime.utcnow()
            )
            self.db_session.add(skill)
            logger.info(f"Created new skill: {name}")
            return skill

    def list_skills(self, include_disabled: bool = False) -> List[Dict[str, Any]]:
        query = self.db_session.query(Skill)
        if not include_disabled:
            query = query.filter(Skill.enabled == True)

        skills = query.all()
        result = []
        for skill in skills:
            try:
                config = yaml.safe_load(skill.config) if skill.config else {}
                result.append({
                    'id': skill.id,
                    'name': skill.name,
                    'version': skill.version,
                    'description': skill.description,
                    'enabled': skill.enabled,
                    'installed_at': skill.installed_at.isoformat() if skill.installed_at else None,
                    'config': config
                })
            except yaml.YAMLError as e:
                logger.warning(f"Failed to parse config for skill {skill.name}: {e}")
                result.append({
                    'id': skill.id,
                    'name': skill.name,
                    'version': skill.version,
                    'description': skill.description,
                    'enabled': skill.enabled,
                    'installed_at': skill.installed_at.isoformat() if skill.installed_at else None,
                    'config': {}
                })

        return result

    def delete_skill(self, skill_name: str) -> bool:
        skill = self.db_session.query(Skill).filter(Skill.name == skill_name).first()
        if not skill:
            logger.warning(f"Skill not found for deletion: {skill_name}")
            return False

        cache_key = self._get_cache_key(skill_name, "db")
        self._clear_cache(cache_key)

        self.db_session.delete(skill)
        logger.info(f"Deleted skill: {skill_name}")
        return True

    def enable_skill(self, skill_name: str) -> bool:
        skill = self.db_session.query(Skill).filter(Skill.name == skill_name).first()
        if not skill:
            logger.warning(f"Skill not found for enabling: {skill_name}")
            return False

        skill.enabled = True
        cache_key = self._get_cache_key(skill_name, "db")
        self._clear_cache(cache_key)
        logger.info(f"Enabled skill: {skill_name}")
        return True

    def disable_skill(self, skill_name: str) -> bool:
        skill = self.db_session.query(Skill).filter(Skill.name == skill_name).first()
        if not skill:
            logger.warning(f"Skill not found for disabling: {skill_name}")
            return False

        skill.enabled = False
        cache_key = self._get_cache_key(skill_name, "db")
        self._clear_cache(cache_key)
        logger.info(f"Disabled skill: {skill_name}")
        return True

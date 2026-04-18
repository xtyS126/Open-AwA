"""
技能系统模块，负责技能注册、加载、校验、执行或适配外部能力。
当 Agent 需要调用外部能力时，通常会经过这一层完成查找、验证与执行。
"""

import yaml
import time
import uuid
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

from loguru import logger
from db.models import Skill


class SkillLoader:
    """
    封装与SkillLoader相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(self, db_session):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.db_session = db_session
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl: int = 300
        self._cache_timestamps: Dict[str, float] = {}

    def _get_cache_key(self, identifier: str, source: str) -> str:
        """
        处理get、cache、key相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return f"{source}:{identifier}"

    def _is_cache_valid(self, cache_key: str) -> bool:
        """
        处理is、cache、valid相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if cache_key not in self._cache_timestamps:
            return False
        return (time.time() - self._cache_timestamps[cache_key]) < self._cache_ttl

    def _set_cache(self, cache_key: str, value: Dict[str, Any]) -> None:
        """
        处理set、cache相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._cache[cache_key] = value
        self._cache_timestamps[cache_key] = time.time()

    def _get_from_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """
        处理get、from、cache相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if self._is_cache_valid(cache_key):
            return self._cache.get(cache_key)
        return None

    def _clear_cache(self, cache_key: Optional[str] = None) -> None:
        """
        处理clear、cache相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if cache_key:
            self._cache.pop(cache_key, None)
            self._cache_timestamps.pop(cache_key, None)
        else:
            self._cache.clear()
            self._cache_timestamps.clear()

    def load_from_file(self, file_path: str) -> Dict[str, Any]:
        """
        加载from、file相关资源或运行时对象。
        它通常负责把外部配置、持久化内容或缓存状态转换为内部可用结构。
        """
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
        """
        加载from、db相关资源或运行时对象。
        它通常负责把外部配置、持久化内容或缓存状态转换为内部可用结构。
        """
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
            if isinstance(skill_record.config, dict):
                config = skill_record.config
            else:
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
        """
        解析config相关输入内容，并转换为内部可用结构。
        它常用于屏蔽外部协议差异并统一上层业务使用的数据格式。
        """
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
        """
        处理convert、to、skill、model相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        skill_id = config.get('id') or str(uuid.uuid4())
        name = config.get('name')
        if not name:
            raise ValueError("Skill name is required in config")

        version = config.get('version', '1.0.0')
        description = config.get('description', '')
        config_text = yaml.dump(config)
        tags = config.get('tags', [])
        dependencies = config.get('dependencies', [])
        author = config.get('author', 'Open-AwA')
        category = config.get('category', 'general')

        existing_skill = self.db_session.query(Skill).filter(Skill.name == name).first()

        if existing_skill:
            existing_skill.version = version
            existing_skill.description = description
            existing_skill.config = config_text
            existing_skill.tags = tags
            existing_skill.dependencies = dependencies
            existing_skill.author = author
            existing_skill.category = category
            logger.info(f"Updated existing skill: {name}")
            return existing_skill
        else:
            skill = Skill(
                id=skill_id,
                name=name,
                version=version,
                description=description,
                config=config_text,
                tags=tags,
                dependencies=dependencies,
                author=author,
                category=category,
                enabled=True,
                usage_count=0,
                installed_at=datetime.now(timezone.utc)
            )
            self.db_session.add(skill)
            logger.info(f"Created new skill: {name}")
            return skill

    def list_skills(self, include_disabled: bool = False) -> List[Dict[str, Any]]:
        """
        列出skills相关内容，便于调用方查看、筛选或批量处理。
        返回结果通常会被页面展示、审计流程或后续操作复用。
        """
        query = self.db_session.query(Skill)
        if not include_disabled:
            query = query.filter(Skill.enabled == True)

        skills = query.all()
        result = []
        for skill in skills:
            try:
                if isinstance(skill.config, dict):
                    config = skill.config
                else:
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
        """
        删除skill相关对象或持久化记录。
        实现中通常还会同时处理资源释放、状态回收或关联数据清理。
        """
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
        """
        处理enable、skill相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理disable、skill相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        skill = self.db_session.query(Skill).filter(Skill.name == skill_name).first()
        if not skill:
            logger.warning(f"Skill not found for disabling: {skill_name}")
            return False

        skill.enabled = False
        cache_key = self._get_cache_key(skill_name, "db")
        self._clear_cache(cache_key)
        logger.info(f"Disabled skill: {skill_name}")
        return True

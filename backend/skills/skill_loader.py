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
    技能加载器，从数据库或YAML文件加载技能配置，支持配置解析和缓存。
    """
    def __init__(self, db_session):
        """
        初始化技能加载器，绑定数据库会话并创建内存缓存。
        """
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

    async def load_from_url(self, url: str, skill_name: Optional[str] = None) -> Dict[str, Any]:
        """
        从远程 Git URL 拉取技能配置（预留接口）。

        当前实现返回占位结果，标记来源为 remote，
        实际拉取逻辑将在后续版本中通过 git clone 或 HTTP 下载实现。

        Args:
            url: 远程 Git 仓库 URL 或技能文件 URL
            skill_name: 可选技能名称，不传则从 URL 路径推断

        Returns:
            包含 source、url、skill_name 和 status 的占位字典
        """
        cache_key = self._get_cache_key(url, "url")
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            logger.info(f"远程技能已缓存: {url}")
            return cached

        logger.info(f"远程技能源加载预留接口: url={url}, skill_name={skill_name}")
        # 预留：实际拉取逻辑将在后续版本中实现
        # 当前返回占位结果，确保接口契约不变
        result = {
            "source": "remote",
            "url": url,
            "skill_name": skill_name or "",
            "status": "placeholder",
            "message": "远程技能源加载接口已预留，实际拉取逻辑将在后续版本实现",
        }
        # 缓存较短时间，避免频繁重复日志
        self._set_cache(cache_key, result)
        return result

    async def discover_remote_skills(self, repo_url: str) -> List[Dict[str, Any]]:
        """
        从远程仓库发现技能列表（预留接口）。

        扫描远程 Git 仓库中的 SKILL.md 或 skills/ 目录，
        返回可安装的技能摘要列表。

        Args:
            repo_url: 远程 Git 仓库 URL

        Returns:
            技能摘要列表，每个包含 name、path 和 description
        """
        logger.info(f"远程技能发现预留接口: repo_url={repo_url}")
        # 预留：实际发现逻辑将在后续版本中实现
        return []

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
                # 解析失败不静默替换为空配置：条目带显式 config_error 字段，调用方可感知
                logger.error(f"Failed to parse config for skill {skill.name}: {e}")
                result.append({
                    'id': skill.id,
                    'name': skill.name,
                    'version': skill.version,
                    'description': skill.description,
                    'enabled': skill.enabled,
                    'installed_at': skill.installed_at.isoformat() if skill.installed_at else None,
                    'config': {},
                    'config_error': f"配置 YAML 解析失败: {e}",
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

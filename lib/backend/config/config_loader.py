"""
配置加载器模块

负责从 JSON 配置文件异步加载、缓存、校验计费相关的配置数据。
支持文件变更自动检测、TTL 缓存失效、数据 Schema 校验等特性。

配置文件目录结构：
    config/pricing/
        pricing_data.json           - 模型价格数据
        model_capabilities.json     - 模型能力参数
        default_configurations.json - 默认模型配置
        legacy_config_keys.json     - 待清理的旧模型列表
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).resolve().parent / "pricing"

CONFIG_FILES = {
    "pricing_data": "pricing_data.json",
    "model_capabilities": "model_capabilities.json",
    "default_configurations": "default_configurations.json",
    "legacy_config_keys": "legacy_config_keys.json",
}

DEFAULT_CACHE_TTL = 300


class ConfigLoadError(Exception):
    """配置加载失败异常"""


class ConfigValidationError(ConfigLoadError):
    """配置数据校验失败异常"""


class ConfigLoader:
    """配置加载器（单例）
    
    负责 JSON 配置文件的异步加载、缓存、校验和变更检测。
    所有计费相关的配置数据通过本类统一管理。
    """
    
    _instance: Optional["ConfigLoader"] = None
    
    def __new__(cls) -> "ConfigLoader":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        
        self._config_dir = _CONFIG_DIR
        self._cache: Dict[str, Tuple[Any, float, float]] = {}
        self._cache_ttl: float = DEFAULT_CACHE_TTL
    
    def set_cache_ttl(self, ttl_seconds: float) -> None:
        self._cache_ttl = ttl_seconds
    
    def load_pricing_data(self) -> List[Dict[str, Any]]:
        return self._load_sync("pricing_data")
    
    def load_model_capabilities(self) -> Dict[Tuple[str, str], Dict[str, Any]]:
        raw = self._load_sync("model_capabilities")
        return self._build_capability_dict(raw)
    
    def load_default_configurations(self) -> List[Dict[str, Any]]:
        return self._load_sync("default_configurations")
    
    def load_legacy_config_keys(self) -> List[Tuple[str, str]]:
        raw = self._load_sync("legacy_config_keys")
        return [tuple(item) for item in raw]
    
    async def load_pricing_data_async(self) -> List[Dict[str, Any]]:
        return await self._load_async("pricing_data")
    
    async def load_model_capabilities_async(self) -> Dict[Tuple[str, str], Dict[str, Any]]:
        raw = await self._load_async("model_capabilities")
        return self._build_capability_dict(raw)
    
    async def load_default_configurations_async(self) -> List[Dict[str, Any]]:
        return await self._load_async("default_configurations")
    
    async def load_legacy_config_keys_async(self) -> List[Tuple[str, str]]:
        raw = await self._load_async("legacy_config_keys")
        return [tuple(item) for item in raw]
    
    def get_raw_json(self, config_name: str) -> Any:
        """获取原始 JSON 数据（供 API 直接输出）"""
        return self._load_sync(config_name)
    
    async def get_raw_json_async(self, config_name: str) -> Any:
        """异步获取原始 JSON 数据（供 API 直接输出）"""
        return await self._load_async(config_name)
    
    def invalidate_cache(self, config_name: Optional[str] = None) -> None:
        if config_name:
            self._cache.pop(config_name, None)
        else:
            self._cache.clear()
    
    def _get_file_path(self, config_name: str) -> Path:
        filename = CONFIG_FILES.get(config_name)
        if not filename:
            raise ConfigValidationError(f"未知配置名称: {config_name}")
        return self._config_dir / filename
    
    def _is_cache_valid(self, config_name: str, file_path: Path) -> bool:
        cached = self._cache.get(config_name)
        if not cached:
            return False
        
        _, cached_mtime, loaded_at = cached
        
        if time.time() - loaded_at > self._cache_ttl:
            return False
        
        try:
            current_mtime = os.path.getmtime(file_path)
            if current_mtime > cached_mtime:
                return False
        except OSError:
            return False
        
        return True
    
    def _load_sync(self, config_name: str) -> Any:
        file_path = self._get_file_path(config_name)
        
        if self._is_cache_valid(config_name, file_path):
            return self._cache[config_name][0]
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            current_mtime = os.path.getmtime(file_path)
            self._cache[config_name] = (data, current_mtime, time.time())
            return data
        except FileNotFoundError:
            logger.warning("配置文件未找到: %s", file_path)
            raise ConfigValidationError(f"配置文件未找到: {file_path}")
        except json.JSONDecodeError as e:
            logger.error("配置文件 JSON 解析失败: %s, 错误: %s", file_path, e)
            raise ConfigValidationError(f"配置文件 JSON 解析失败: {file_path}: {e}")
        except OSError as e:
            logger.error("配置文件读取失败: %s, 错误: %s", file_path, e)
            raise ConfigValidationError(f"配置文件读取失败: {file_path}: {e}")
    
    async def _load_async(self, config_name: str) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._load_sync, config_name)
    
    @staticmethod
    def _build_capability_dict(
        raw: List[Dict[str, Any]]
    ) -> Dict[Tuple[str, str], Dict[str, Any]]:
        result: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for item in raw:
            provider = item.get("provider", "")
            model_name = item.get("model", "")
            key = (provider, model_name)
            
            entry = {
                "temperature": item.get("temperature", 0.7),
                "top_k": item.get("top_k", 0.9),
                "supports_temperature": item.get("supports_temperature", True),
                "supports_top_k": item.get("supports_top_k", True),
                "supports_vision": item.get("supports_vision", False),
                "is_multimodal": item.get("is_multimodal", False),
                "model_spec": json.dumps(item.get("model_spec", {}), ensure_ascii=False),
                "status": item.get("status", "active"),
            }
            result[key] = entry
        return result


config_loader = ConfigLoader()

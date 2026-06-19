"""
LLM 配置加载器，支持从配置文件读取 Provider 配置和任务路由。
"""

from typing import Any, Dict, List, Optional
from pathlib import Path
from loguru import logger
from config.settings import settings


class LLMConfig:
    """
    LLM 配置加载器。
    负责从配置文件或环境变量加载 Provider 配置和任务路由。
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置加载器。
        
        Args:
            config_path: 配置文件路径（可选，默认从 settings 读取）
        """
        self.config_path = config_path
        self._config: Dict[str, Any] = {}
        self._load_config()
    
    def _load_config(self) -> None:
        """加载配置"""
        # 优先从 settings 读取
        if hasattr(settings, 'LLM_CONFIG'):
            self._config = settings.LLM_CONFIG
            logger.info("从 settings.LLM_CONFIG 加载 LLM 配置")
            return
        
        # 尝试从配置文件加载
        if self.config_path:
            config_file = Path(self.config_path)
            if config_file.exists():
                import yaml
                with open(config_file, 'r', encoding='utf-8') as f:
                    self._config = yaml.safe_load(f)
                logger.info(f"从配置文件加载 LLM 配置: {config_file}")
                return
        
        # 使用默认配置
        self._config = self._get_default_config()
        logger.info("使用默认 LLM 配置")
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            'providers': {},
            'task_routing': {
                'agent': 'openai',  # 默认使用 OpenAI
                'soul': 'openai',
                'discovery': 'openai',
                'recommendation': 'openai',
                'evaluation': 'openai',
            },
        }
    
    def get_provider_config(self, provider_name: str) -> Optional[Dict[str, Any]]:
        """
        获取指定 Provider 的配置。
        
        Args:
            provider_name: Provider 名称
        
        Returns:
            Dict[str, Any]: Provider 配置，不存在时返回 None
        """
        providers = self._config.get('providers', {})
        return providers.get(provider_name)
    
    def get_all_provider_configs(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有 Provider 配置。
        
        Returns:
            Dict[str, Dict[str, Any]]: Provider 名称到配置的映射
        """
        return self._config.get('providers', {})
    
    def get_task_routing(self) -> Dict[str, str]:
        """
        获取任务路由配置。
        
        Returns:
            Dict[str, str]: 任务类型到 Provider 名称的映射
        """
        return self._config.get('task_routing', {})
    
    def get_task_provider(self, task_type: str) -> Optional[str]:
        """
        获取任务类型对应的 Provider 名称。
        
        Args:
            task_type: 任务类型
        
        Returns:
            Optional[str]: Provider 名称，未配置时返回 None
        """
        routing = self.get_task_routing()
        return routing.get(task_type)
    
    def set_task_provider(self, task_type: str, provider_name: str) -> None:
        """
        设置任务类型对应的 Provider（运行时修改）。
        
        Args:
            task_type: 任务类型
            provider_name: Provider 名称
        """
        if 'task_routing' not in self._config:
            self._config['task_routing'] = {}
        self._config['task_routing'][task_type] = provider_name
        logger.info(f"任务路由更新: {task_type} -> {provider_name}")
    
    def add_provider_config(self, provider_name: str, config: Dict[str, Any]) -> None:
        """
        添加 Provider 配置（运行时修改）。
        
        Args:
            provider_name: Provider 名称
            config: Provider 配置
        """
        if 'providers' not in self._config:
            self._config['providers'] = {}
        self._config['providers'][provider_name] = config
        logger.info(f"已添加 Provider 配置: {provider_name}")
    
    def reload(self) -> None:
        """重新加载配置"""
        self._load_config()
        logger.info("LLM 配置已重新加载")
    
    def get_config_value(self, key: str, default: Any = None) -> Any:
        """
        获取配置值（支持点号分隔的嵌套键）。
        
        Args:
            key: 配置键（如 "providers.openai.api_key"）
            default: 默认值
        
        Returns:
            Any: 配置值
        """
        keys = key.split('.')
        value = self._config
        
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        
        return value

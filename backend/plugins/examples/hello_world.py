"""
插件系统模块，负责插件定义、加载、校验、沙箱隔离、生命周期或扩展协议处理。
这一层通常同时涉及可扩展性、安全性与运行时状态管理。
"""

from typing import Dict, Any, List, Optional
from loguru import logger
from backend.plugins.base_plugin import BasePlugin


class HelloWorldPlugin(BasePlugin):
    """
    封装与HelloWorldPlugin相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    name: str = "hello_world"
    version: str = "1.0.0"
    description: str = "Hello World示例插件"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        super().__init__(config)
        self.greeting = self.config.get('greeting', 'Hello')

    async def initialize(self) -> bool:
        """
        处理initialize相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        logger.info(f"Initializing {self.name} plugin v{self.version}")
        if not self.validate_config(self.config):
            logger.error("Plugin configuration validation failed")
            return False
        logger.info(f"Plugin initialized with greeting: {self.greeting}")
        return True

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        处理execute相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        name = kwargs.get('name', 'World')
        logger.info(f"Executing say_hello for: {name}")
        return {
            "message": f"{self.greeting}, {name}!",
            "plugin": self.name,
            "version": self.version
        }

    def get_tools(self) -> List[Dict[str, Any]]:
        """
        获取tools相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        return [
            {
                "name": "say_hello",
                "description": "打招呼",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "要打招呼的人的名字"
                        }
                    },
                    "required": []
                }
            }
        ]

    def validate_config(self, config: Dict[str, Any]) -> bool:
        """
        校验config相关输入、规则或结构是否合法。
        返回结果通常用于阻止非法输入继续流入后续链路。
        """
        if not isinstance(config, dict):
            logger.error("Config must be a dictionary")
            return False
        if 'greeting' in config and not isinstance(config['greeting'], str):
            logger.error("greeting must be a string")
            return False
        return True

    def validate(self) -> bool:
        """
        处理validate相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return self.validate_config(self.config)

from typing import Dict, Any, List
from loguru import logger
from backend.plugins.base_plugin import BasePlugin


class HelloWorldPlugin(BasePlugin):
    name: str = "hello_world"
    version: str = "1.0.0"
    description: str = "Hello World示例插件"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.greeting = self.config.get('greeting', 'Hello')

    async def initialize(self) -> bool:
        logger.info(f"Initializing {self.name} plugin v{self.version}")
        if not self.validate_config(self.config):
            logger.error("Plugin configuration validation failed")
            return False
        logger.info(f"Plugin initialized with greeting: {self.greeting}")
        return True

    async def execute(self, **kwargs) -> Dict[str, Any]:
        name = kwargs.get('name', 'World')
        logger.info(f"Executing say_hello for: {name}")
        return {
            "message": f"{self.greeting}, {name}!",
            "plugin": self.name,
            "version": self.version
        }

    def get_tools(self) -> List[Dict[str, Any]]:
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
        if not isinstance(config, dict):
            logger.error("Config must be a dictionary")
            return False
        if 'greeting' in config and not isinstance(config['greeting'], str):
            logger.error("greeting must be a string")
            return False
        return True

    def validate(self) -> bool:
        return self.validate_config(self.config)

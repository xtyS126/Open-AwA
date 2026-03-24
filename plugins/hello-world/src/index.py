from typing import Any, Dict, List, Optional
from loguru import logger
from backend.plugins.base_plugin import BasePlugin


class HelloWorldPlugin(BasePlugin):
    name: str = "hello-world"
    version: str = "1.0.0"
    description: str = "最简示例插件，演示插件生命周期与日志输出"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._greeting = self.config.get("greeting", "你好")

    def initialize(self) -> bool:
        logger.info(f"[{self.name}] 插件初始化开始，版本 {self.version}")
        logger.info(f"[{self.name}] 配置的问候语：{self._greeting}")
        self._initialized = True
        logger.info(f"[{self.name}] 插件初始化完成")
        return True

    def execute(self, *args, **kwargs) -> Dict[str, Any]:
        target_name = kwargs.get("name", "World")
        logger.info(f"[{self.name}] 执行 say_hello，目标：{target_name}")
        message = f"{self._greeting}，{target_name}！"
        logger.debug(f"[{self.name}] 生成消息：{message}")
        return {
            "status": "success",
            "message": message,
            "plugin": self.name,
            "version": self.version
        }

    def validate(self) -> bool:
        greeting = self.config.get("greeting", "你好")
        if not isinstance(greeting, str):
            logger.error(f"[{self.name}] 配置项 'greeting' 必须是字符串")
            return False
        if len(greeting) == 0:
            logger.error(f"[{self.name}] 配置项 'greeting' 不能为空")
            return False
        return True

    def cleanup(self) -> None:
        logger.info(f"[{self.name}] 插件正在卸载")
        super().cleanup()
        logger.info(f"[{self.name}] 插件已卸载")

    def on_enabled(self) -> None:
        logger.info(f"[{self.name}] 插件已启用")
        super().on_enabled()

    def on_disabled(self) -> None:
        logger.info(f"[{self.name}] 插件已禁用")
        super().on_disabled()

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "say_hello",
                "description": "向指定名称的用户打招呼，返回问候消息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "要打招呼的人的名字，默认为 World"
                        }
                    },
                    "required": []
                }
            }
        ]

from typing import Any, Dict, List, Optional
from loguru import logger
from backend.plugins.base_plugin import BasePlugin

VALID_THEMES = {"light", "dark", "system"}

DEFAULT_THEME_TOKENS: Dict[str, Dict[str, str]] = {
    "light": {
        "--color-bg-primary": "#ffffff",
        "--color-bg-secondary": "#f5f5f5",
        "--color-text-primary": "#1a1a1a",
        "--color-text-secondary": "#666666",
        "--color-accent": "#4f6ef7",
        "--color-border": "#e0e0e0",
    },
    "dark": {
        "--color-bg-primary": "#1a1a2e",
        "--color-bg-secondary": "#16213e",
        "--color-text-primary": "#e0e0e0",
        "--color-text-secondary": "#a0a0b0",
        "--color-accent": "#7b8ff7",
        "--color-border": "#2a2a4a",
    },
    "system": {},
}


class ThemeSwitcherPlugin(BasePlugin):
    name: str = "theme-switcher"
    version: str = "1.0.0"
    description: str = "演示存储API与UI扩展点的主题切换插件"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._current_theme: str = self.config.get("default_theme", "light")
        self._custom_tokens: Dict[str, str] = self.config.get("custom_tokens", {})
        self._theme_history: List[str] = []

    def initialize(self) -> bool:
        logger.info(f"[{self.name}] 初始化主题切换插件，默认主题：{self._current_theme}")
        if self._current_theme not in VALID_THEMES:
            logger.error(f"[{self.name}] 无效的默认主题：{self._current_theme}，将回退到 light")
            self._current_theme = "light"
        self._theme_history.append(self._current_theme)
        self._initialized = True
        logger.info(f"[{self.name}] 初始化完成，当前主题：{self._current_theme}")
        return True

    def execute(self, *args, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "get_theme")
        logger.debug(f"[{self.name}] 执行动作：{action}，参数：{kwargs}")

        if action == "get_theme":
            return self._get_theme()
        if action == "set_theme":
            return self._set_theme(kwargs.get("theme", ""))
        if action == "ui_theme_hook":
            return self._inject_theme_tokens()

        logger.warning(f"[{self.name}] 未知动作：{action}")
        return {"status": "error", "message": f"未知动作：{action}"}

    def _get_theme(self) -> Dict[str, Any]:
        tokens = {**DEFAULT_THEME_TOKENS.get(self._current_theme, {}), **self._custom_tokens}
        logger.info(f"[{self.name}] 获取当前主题：{self._current_theme}")
        return {
            "status": "success",
            "theme": self._current_theme,
            "tokens": tokens,
            "history": self._theme_history[-5:],
        }

    def _set_theme(self, theme: str) -> Dict[str, Any]:
        if not theme:
            return {"status": "error", "message": "参数 'theme' 不能为空"}
        if theme not in VALID_THEMES:
            return {
                "status": "error",
                "message": f"无效的主题值：{theme}，支持的值：{sorted(VALID_THEMES)}"
            }
        previous = self._current_theme
        self._current_theme = theme
        self._theme_history.append(theme)
        logger.info(f"[{self.name}] 主题从 {previous} 切换为 {theme}")
        return {
            "status": "success",
            "previous_theme": previous,
            "current_theme": self._current_theme,
            "tokens": {**DEFAULT_THEME_TOKENS.get(theme, {}), **self._custom_tokens},
        }

    def _inject_theme_tokens(self) -> Dict[str, Any]:
        tokens = {**DEFAULT_THEME_TOKENS.get(self._current_theme, {}), **self._custom_tokens}
        logger.debug(f"[{self.name}] 注入主题 CSS 变量，共 {len(tokens)} 个")
        return {
            "status": "success",
            "action": "inject_css_variables",
            "theme": self._current_theme,
            "css_variables": tokens,
        }

    def validate(self) -> bool:
        default_theme = self.config.get("default_theme", "light")
        if default_theme not in VALID_THEMES:
            logger.error(f"[{self.name}] 配置项 'default_theme' 无效：{default_theme}")
            return False
        custom_tokens = self.config.get("custom_tokens", {})
        if not isinstance(custom_tokens, dict):
            logger.error(f"[{self.name}] 配置项 'custom_tokens' 必须是字典")
            return False
        return True

    def cleanup(self) -> None:
        logger.info(f"[{self.name}] 清理主题切换插件，共切换了 {len(self._theme_history)} 次")
        self._theme_history.clear()
        self._custom_tokens.clear()
        super().cleanup()

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "get_theme",
                "description": "获取当前激活的主题名称及其 CSS 变量令牌",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "set_theme",
                "description": "切换 UI 主题，支持 light、dark、system 三种模式",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "theme": {
                            "type": "string",
                            "description": "目标主题名称",
                            "enum": ["light", "dark", "system"]
                        }
                    },
                    "required": ["theme"]
                }
            }
        ]

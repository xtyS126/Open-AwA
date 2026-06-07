"""
分层配置管理器，支持多源合并和优先级链。

参考 OpenCode Config 设计：
- 配置优先级：默认值 → 全局配置 → 项目配置 → 环境变量
- 支持 JSON with Comments (jsonc) 格式
- 支持 Markdown Frontmatter 嵌入式配置
- JSON Schema 验证（基于 Pydantic）
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger
from pydantic import BaseModel, Field


class ConfigSourceType(str):
    """配置来源类型"""
    DEFAULT = "default"
    GLOBAL = "global"
    PROJECT = "project"
    ENV = "env"


@dataclass
class ConfigEntry:
    """单条配置项，记录来源和值"""
    key: str
    value: Any
    source: str  # ConfigSourceType
    file_path: Optional[str] = None


class ConfigManager:
    """
    分层配置管理器。

    配置加载顺序（后加载覆盖先加载）：
    1. 默认值（硬编码）
    2. 全局配置（~/.open-awa/config.jsonc）
    3. 项目配置（.open-awa/config.jsonc 或 CLAUDE.md frontmatter）
    4. 环境变量（OPENAWA_* 前缀）

    使用方式：
        config = ConfigManager()
        config.load_defaults({...})
        config.load_global_config()
        config.load_project_config("D:/project")
        config.load_env_variables("OPENAWA_")

        value = config.get("model", "gpt-4")
    """

    def __init__(self):
        self._entries: Dict[str, ConfigEntry] = {}
        self._schema: Optional[Dict[str, Any]] = None
        self._global_config_dir: Optional[Path] = None
        self._loaded_sources: List[str] = []

    def load_defaults(self, defaults: Dict[str, Any]) -> None:
        """加载默认值（最低优先级）"""
        for key, value in defaults.items():
            self._entries[key] = ConfigEntry(
                key=key, value=value, source=ConfigSourceType.DEFAULT
            )
        self._loaded_sources.append(ConfigSourceType.DEFAULT)
        logger.debug(f"已加载 {len(defaults)} 条默认配置")

    def load_global_config(self, config_dir: Optional[str] = None) -> None:
        """
        加载全局配置文件。

        查找路径：
        1. config_dir 参数
        2. ~/.open-awa/config.jsonc
        3. ~/.open-awa/config.json
        """
        if config_dir:
            paths = [Path(config_dir) / "config.jsonc", Path(config_dir) / "config.json"]
        else:
            home = Path.home()
            paths = [
                home / ".open-awa" / "config.jsonc",
                home / ".open-awa" / "config.json",
            ]

        for config_path in paths:
            if config_path.exists():
                data = self._read_jsonc(config_path)
                if data:
                    for key, value in data.items():
                        self._entries[key] = ConfigEntry(
                            key=key, value=value,
                            source=ConfigSourceType.GLOBAL,
                            file_path=str(config_path),
                        )
                    self._global_config_dir = config_path.parent
                    self._loaded_sources.append(ConfigSourceType.GLOBAL)
                    logger.info(f"已加载全局配置: {config_path} ({len(data)} 项)")
                    return

        logger.debug("未找到全局配置文件")

    def load_project_config(self, project_dir: str) -> None:
        """
        加载项目级配置文件。

        查找路径（按优先级）：
        1. {project_dir}/.open-awa/config.jsonc
        2. {project_dir}/CLAUDE.md 的 frontmatter 配置
        3. {project_dir}/AGENTS.md 的 frontmatter 配置
        """
        project_path = Path(project_dir)

        # 1. 项目配置文件
        for config_name in ["config.jsonc", "config.json"]:
            config_file = project_path / ".open-awa" / config_name
            if config_file.exists():
                data = self._read_jsonc(config_file)
                if data:
                    for key, value in data.items():
                        self._entries[key] = ConfigEntry(
                            key=key, value=value,
                            source=ConfigSourceType.PROJECT,
                            file_path=str(config_file),
                        )
                    logger.info(f"已加载项目配置: {config_file} ({len(data)} 项)")

        # 2. Markdown frontmatter 配置
        for md_file in ["CLAUDE.md", "AGENTS.md"]:
            md_path = project_path / md_file
            if md_path.exists():
                try:
                    content = md_path.read_text(encoding="utf-8")
                    frontmatter = self._parse_markdown_frontmatter(content)
                    if frontmatter:
                        for key, value in frontmatter.items():
                            self._entries[key] = ConfigEntry(
                                key=key, value=value,
                                source=ConfigSourceType.PROJECT,
                                file_path=str(md_path),
                            )
                        logger.info(f"已加载 Markdown 配置: {md_path} ({len(frontmatter)} 项)")
                except Exception as e:
                    logger.warning(f"解析 {md_file} 配置失败: {e}")

        self._loaded_sources.append(ConfigSourceType.PROJECT)

    def load_env_variables(self, prefix: str = "OPENAWA_") -> None:
        """
        从环境变量加载配置。

        环境变量格式：OPENAWA_MODEL → model
        OPENAWA_COMPACTION_AUTO → compaction.auto
        """
        count = 0
        for key, value in os.environ.items():
            if not key.startswith(prefix):
                continue
            # 转换：OPENAWA_MODEL → model
            config_key = key[len(prefix):].lower()
            # 转换：OPENAWA_COMPACTION_BUFFER_TOKENS → compaction.buffer_tokens
            config_key = config_key.replace("__", ".").replace("_", "_")

            # 类型转换
            typed_value = self._coerce_env_value(value)
            self._entries[config_key] = ConfigEntry(
                key=config_key, value=typed_value,
                source=ConfigSourceType.ENV,
                file_path=f"env:{key}",
            )
            count += 1

        if count > 0:
            self._loaded_sources.append(ConfigSourceType.ENV)
            logger.info(f"已加载 {count} 条环境变量配置")
        else:
            logger.debug("未找到匹配的环境变量配置")

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        entry = self._entries.get(key)
        return entry.value if entry else default

    def get_int(self, key: str, default: int = 0) -> int:
        """获取整型配置值"""
        value = self.get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """获取布尔配置值"""
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)

    def get_float(self, key: str, default: float = 0.0) -> float:
        """获取浮点配置值"""
        value = self.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def set(self, key: str, value: Any, source: str = "runtime") -> None:
        """运行时设置配置值"""
        self._entries[key] = ConfigEntry(key=key, value=value, source=source)

    def all(self) -> Dict[str, Any]:
        """获取所有配置"""
        return {key: entry.value for key, entry in self._entries.items()}

    def entries(self) -> List[ConfigEntry]:
        """获取所有配置条目（含来源信息）"""
        return list(self._entries.values())

    def get_source(self, key: str) -> Optional[str]:
        """获取配置项的来源"""
        entry = self._entries.get(key)
        return entry.source if entry else None

    def reset(self) -> None:
        """重置所有配置"""
        self._entries.clear()
        self._loaded_sources.clear()

    # ===== 内部工具方法 =====

    @staticmethod
    def _read_jsonc(filepath: Path) -> Optional[Dict[str, Any]]:
        """读取 JSONC（JSON with Comments）文件"""
        try:
            content = filepath.read_text(encoding="utf-8")
            # 移除注释
            cleaned = ConfigManager._strip_json_comments(content)
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.warning(f"解析 JSONC 失败 {filepath}: {e}")
            return None
        except Exception as e:
            logger.warning(f"读取配置文件失败 {filepath}: {e}")
            return None

    @staticmethod
    def _strip_json_comments(content: str) -> str:
        """移除 JSON 中的注释（// 和 /* */）"""
        # 移除多行注释
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        # 移除单行注释（但不移除 URL 中的 //）
        lines = []
        for line in content.split('\n'):
            # 简单处理：移除行末注释
            in_string = False
            result = []
            i = 0
            while i < len(line):
                char = line[i]
                if char == '"' and (i == 0 or line[i-1] != '\\'):
                    in_string = not in_string
                    result.append(char)
                elif char == '/' and not in_string and i + 1 < len(line) and line[i+1] == '/':
                    break  # 行注释，跳过剩余
                else:
                    result.append(char)
                i += 1
            lines.append(''.join(result))
        return '\n'.join(lines)

    @staticmethod
    def _parse_markdown_frontmatter(content: str) -> Optional[Dict[str, Any]]:
        """
        从 Markdown 文件的 YAML frontmatter 中提取配置项。

        支持的配置字段：model, shell, permissions, agents, compaction, skills
        """
        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if not frontmatter_match:
            return None

        try:
            import yaml
            data = yaml.safe_load(frontmatter_match.group(1)) or {}
        except Exception:
            return None

        if not isinstance(data, dict):
            return None

        # 只提取已知的配置字段
        known_fields = {
            "model", "shell", "default_agent", "permissions",
            "agents", "compaction", "skills", "commands",
            "instructions", "references", "plugins",
        }
        return {k: v for k, v in data.items() if k in known_fields}

    @staticmethod
    def _coerce_env_value(value: str) -> Any:
        """将环境变量字符串值转换为合适的 Python 类型"""
        # 布尔值
        if value.lower() in ("true", "false"):
            return value.lower() == "true"
        # 整数
        try:
            return int(value)
        except ValueError:
            pass
        # 浮点数
        try:
            return float(value)
        except ValueError:
            pass
        # JSON 数组/对象
        if value.startswith("[") or value.startswith("{"):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass
        # 字符串
        return value


# 预定义的代理类型配置
DEFAULT_AGENT_CONFIGS = {
    "build": {
        "description": "默认全权限编程代理",
        "mode": "primary",
        "hidden": False,
        "permissions": [
            {"action": "*", "resource": "*", "effect": "allow"},
        ],
    },
    "plan": {
        "description": "只读分析与规划代理",
        "mode": "primary",
        "hidden": False,
        "color": "info",
        "permissions": [
            {"action": "*", "resource": "*", "effect": "deny"},
            {"action": "read", "resource": "*", "effect": "allow"},
            {"action": "glob", "resource": "*", "effect": "allow"},
            {"action": "grep", "resource": "*", "effect": "allow"},
            {"action": "web_search", "resource": "*", "effect": "allow"},
            {"action": "web_fetch", "resource": "*", "effect": "allow"},
            {"action": "skill", "resource": "*", "effect": "allow"},
        ],
    },
    "Explore": {
        "description": "代码探索子代理（只读）",
        "mode": "subagent",
        "hidden": True,
        "permissions": [
            {"action": "*", "resource": "*", "effect": "deny"},
            {"action": "read", "resource": "*", "effect": "allow"},
            {"action": "glob", "resource": "*", "effect": "allow"},
            {"action": "grep", "resource": "*", "effect": "allow"},
            {"action": "web_search", "resource": "*", "effect": "allow"},
            {"action": "web_fetch", "resource": "*", "effect": "allow"},
        ],
    },
    "general-purpose": {
        "description": "通用代理，写操作需用户确认",
        "mode": "all",
        "hidden": False,
        "permissions": [
            {"action": "*", "resource": "*", "effect": "allow"},
            {"action": "edit", "resource": "*", "effect": "ask"},
            {"action": "write", "resource": "*", "effect": "ask"},
            {"action": "bash", "resource": "*", "effect": "ask"},
        ],
    },
}


class AgentMode(str):
    """代理运行模式"""
    PRIMARY = "primary"      # 主代理，用户可直接选择
    SUBAGENT = "subagent"    # 子代理，仅内部调用
    ALL = "all"              # 通用，既可作为主代理也可作为子代理


@dataclass
class AgentConfig:
    """代理配置定义"""
    id: str
    description: str = ""
    mode: AgentMode = AgentMode.PRIMARY
    hidden: bool = False
    color: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    steps: int = 25
    permissions: List[Dict[str, str]] = field(default_factory=list)

    @classmethod
    def from_config(cls, agent_id: str, data: Dict[str, Any]) -> "AgentConfig":
        """从配置字典创建代理配置"""
        return cls(
            id=agent_id,
            description=data.get("description", ""),
            mode=AgentMode(data.get("mode", "primary")),
            hidden=data.get("hidden", False),
            color=data.get("color"),
            model=data.get("model"),
            system_prompt=data.get("system"),
            steps=data.get("steps", 25),
            permissions=data.get("permissions", []),
        )

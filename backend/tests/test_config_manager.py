"""
ConfigManager 和 AgentConfig 单元测试。
测试分层配置合并、优先级链、Markdown frontmatter 解析。
"""

import os
import tempfile
from pathlib import Path
import pytest

from config.config_manager import (
    ConfigManager,
    ConfigEntry,
    ConfigSourceType,
    AgentConfig,
    AgentMode,
    DEFAULT_AGENT_CONFIGS,
)


class TestConfigManager:
    """分层配置管理器测试"""

    @pytest.fixture
    def config(self):
        """创建空配置管理器"""
        mgr = ConfigManager()
        yield mgr
        mgr.reset()

    def test_load_defaults(self, config):
        """加载默认配置"""
        config.load_defaults({"model": "gpt-4", "temperature": 0.7})
        assert config.get("model") == "gpt-4"
        assert config.get("temperature") == 0.7
        assert config.get("nonexistent") is None
        assert config.get("nonexistent", "fallback") == "fallback"

    def test_load_env_variables(self, config):
        """加载环境变量"""
        os.environ["OPENAWA_TEST_MODEL"] = "claude-opus"
        os.environ["OPENAWA_TEST_TEMPERATURE"] = "0.5"
        os.environ["OPENAWA_TEST_AUTO"] = "true"
        os.environ["OPENAWA_TEST_COUNT"] = "42"

        try:
            config.load_env_variables("OPENAWA_TEST_")
            assert config.get("model") == "claude-opus"
            assert config.get("temperature") == 0.5
            assert config.get("auto") is True
            assert config.get("count") == 42
        finally:
            for key in list(os.environ):
                if key.startswith("OPENAWA_TEST_"):
                    del os.environ[key]

    def test_priority_chain(self, config):
        """优先级链测试：默认 < 环境变量"""
        config.load_defaults({"model": "gpt-4"})
        assert config.get("model") == "gpt-4"

        os.environ["OPENAWA_MODEL"] = "claude-opus"
        try:
            config.load_env_variables("OPENAWA_")
            # 环境变量应该覆盖默认值
            assert config.get("model") == "claude-opus"
        finally:
            del os.environ["OPENAWA_MODEL"]

    def test_get_typed_methods(self, config):
        """类型化获取方法"""
        config.load_defaults({
            "count": "42",
            "enabled": "true",
            "rate": "0.75",
            "name": "test",
        })

        assert config.get_int("count") == 42
        assert config.get_bool("enabled") is True
        assert config.get_float("rate") == 0.75
        assert config.get("name") == "test"

        # 默认值回退
        assert config.get_int("missing") == 0
        assert config.get_bool("missing") is False
        assert config.get_float("missing") == 0.0

    def test_set_runtime(self, config):
        """运行时设置配置"""
        config.load_defaults({"key": "original"})
        config.set("key", "overridden", "runtime")
        assert config.get("key") == "overridden"
        assert config.get_source("key") == "runtime"

    def test_all_entries(self, config):
        """获取所有配置条目"""
        config.load_defaults({"a": 1, "b": 2})
        all_config = config.all()
        assert all_config == {"a": 1, "b": 2}

    def test_entries_with_source(self, config):
        """配置条目来源追踪"""
        config.load_defaults({"model": "gpt-4"})
        entries = config.entries()
        assert len(entries) == 1
        assert entries[0].key == "model"
        assert entries[0].source == ConfigSourceType.DEFAULT

    @pytest.mark.parametrize("value,expected", [
        ("true", True),
        ("false", False),
        ("42", 42),
        ("-1", -1),
        ("3.14", 3.14),
        ("hello", "hello"),
        ('["a", "b"]', ["a", "b"]),
        ('{"key": "val"}', {"key": "val"}),
    ])
    def test_coerce_env_value(self, config, value, expected):
        """环境变量值类型转换"""
        result = config._coerce_env_value(value)
        assert result == expected


class TestAgentConfig:
    """代理配置测试"""

    def test_default_build_agent(self):
        """build 代理默认配置"""
        build = DEFAULT_AGENT_CONFIGS["build"]
        assert build["mode"] == "primary"
        assert build["hidden"] is False
        assert build["permissions"][0]["action"] == "*"
        assert build["permissions"][0]["effect"] == "allow"

    def test_default_plan_agent(self):
        """plan 代理默认配置"""
        plan = DEFAULT_AGENT_CONFIGS["plan"]
        assert plan["mode"] == "primary"
        # 第一条规则是 deny all
        assert plan["permissions"][0]["action"] == "*"
        assert plan["permissions"][0]["effect"] == "deny"
        # 第二条规则是 allow read
        assert plan["permissions"][1]["action"] == "read"
        assert plan["permissions"][1]["effect"] == "allow"

    def test_default_explore_agent(self):
        """Explore 子代理默认配置"""
        explore = DEFAULT_AGENT_CONFIGS["Explore"]
        assert explore["mode"] == "subagent"
        assert explore["hidden"] is True

    def test_agent_config_from_config(self):
        """从配置字典创建代理配置"""
        config = AgentConfig.from_config("custom", {
            "description": "自定义代理",
            "mode": "all",
            "hidden": False,
            "color": "#ff6600",
            "steps": 50,
            "permissions": [{"action": "read", "resource": "*", "effect": "allow"}],
        })
        assert config.id == "custom"
        assert config.mode == AgentMode.ALL
        assert config.steps == 50
        assert len(config.permissions) == 1


class TestJSONCParsing:
    """JSONC 解析测试"""

    def test_strip_json_comments_line(self):
        """移除单行注释"""
        content = '{\n  "key": "value", // comment\n  "num": 42\n}'
        cleaned = ConfigManager._strip_json_comments(content)
        assert "// comment" not in cleaned
        assert '"key"' in cleaned

    def test_strip_json_comments_block(self):
        """移除块注释"""
        content = '{\n  /* block comment */\n  "key": "value"\n}'
        cleaned = ConfigManager._strip_json_comments(content)
        assert "block comment" not in cleaned
        assert '"key"' in cleaned

    def test_strip_json_comments_url_safe(self):
        """URL 中的 // 不被移除"""
        content = '{"url": "https://example.com/api"}'
        cleaned = ConfigManager._strip_json_comments(content)
        assert "https://example.com/api" in cleaned


class TestMarkdownFrontmatter:
    """Markdown Frontmatter 配置解析测试"""

    def test_parse_basic_frontmatter(self):
        """基本 frontmatter 解析"""
        content = """---
model: gpt-4
shell: bash
---

# 文档内容"""
        result = ConfigManager._parse_markdown_frontmatter(content)
        assert result is not None
        assert result.get("model") == "gpt-4"
        assert result.get("shell") == "bash"

    def test_parse_no_frontmatter(self):
        """无 frontmatter 的 Markdown"""
        content = "# Just a markdown file"
        result = ConfigManager._parse_markdown_frontmatter(content)
        assert result is None

    def test_parse_invalid_yaml_raises(self):
        """无效 YAML 必须显式抛错（配置损坏不得静默丢失）"""
        content = """---
: invalid: yaml: [
---

Content"""
        with pytest.raises(ValueError, match="Markdown frontmatter 失败"):
            ConfigManager._parse_markdown_frontmatter(content)

    def test_filter_unknown_fields(self):
        """过滤未知配置字段"""
        content = """---
model: gpt-4
unknown_field: should_not_appear
permissions:
  - action: read
    resource: "*"
    effect: allow
---

Content"""
        result = ConfigManager._parse_markdown_frontmatter(content)
        assert result is not None
        assert "model" in result
        assert "permissions" in result
        assert "unknown_field" not in result

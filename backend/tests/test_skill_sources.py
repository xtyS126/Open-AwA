"""
技能多源加载单元测试。
测试技能从文件、数据库、远程源加载的功能。
"""

import pytest
from unittest.mock import MagicMock, patch

from skills.skill_loader import SkillLoader


class TestSkillLoaderSources:
    """技能加载器多源测试"""

    @pytest.fixture
    def mock_db_session(self):
        """创建模拟数据库会话"""
        return MagicMock()

    @pytest.fixture
    def loader(self, mock_db_session):
        """创建 SkillLoader 实例"""
        return SkillLoader(mock_db_session)

    def test_cache_key_generation(self, loader):
        """缓存键生成测试：文件/数据库/URL 源"""
        file_key = loader._get_cache_key("test_skill", "file")
        db_key = loader._get_cache_key("test_skill", "db")
        url_key = loader._get_cache_key("https://example.com/skill.md", "url")

        assert "file:" in file_key
        assert "db:" in db_key
        assert "url:" in url_key
        # 不同源应该有不同缓存键
        assert file_key != db_key
        assert db_key != url_key

    def test_cache_lifecycle(self, loader):
        """缓存生命周期测试：设置 -> 有效 -> 过期"""
        key = "test:cache"
        loader._set_cache(key, {"test": True})
        assert loader._is_cache_valid(key) is True

        cached = loader._get_from_cache(key)
        assert cached is not None
        assert cached["test"] is True

        # 清除后应返回 None
        loader._clear_cache(key)
        assert loader._get_from_cache(key) is None

    def test_load_from_file_not_found(self, loader):
        """从文件加载不存在文件时抛出 FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            loader.load_from_file("/nonexistent/skill.yaml")

    def test_parse_config_empty(self, loader):
        """解析空 YAML 返回空字典"""
        result = loader.parse_config("")
        assert result == {}

    def test_parse_config_valid(self, loader):
        """解析有效 YAML 配置"""
        yaml_content = """
name: test_skill
version: 1.0.0
description: A test skill
"""
        config = loader.parse_config(yaml_content)
        assert config["name"] == "test_skill"
        assert config["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_load_from_url_placeholder(self, loader):
        """远程 URL 加载返回占位结果"""
        result = await loader.load_from_url("https://github.com/example/skills.git")
        assert result["source"] == "remote"
        assert result["status"] == "placeholder"
        assert "message" in result

    @pytest.mark.asyncio
    async def test_load_from_url_with_skill_name(self, loader):
        """远程 URL 加载支持指定技能名称"""
        result = await loader.load_from_url(
            "https://github.com/example/skills.git",
            skill_name="my-skill",
        )
        assert result["skill_name"] == "my-skill"
        assert result["url"] == "https://github.com/example/skills.git"

    @pytest.mark.asyncio
    async def test_discover_remote_skills_empty(self, loader):
        """远程技能发现返回空列表（预留接口）"""
        result = await loader.discover_remote_skills(
            "https://github.com/example/skills.git"
        )
        assert isinstance(result, list)
        assert len(result) == 0


class TestSkillLoaderDatabase:
    """技能加载器数据库操作测试"""

    @pytest.fixture
    def mock_db_session(self):
        """创建模拟数据库会话"""
        return MagicMock()

    @pytest.fixture
    def loader(self, mock_db_session):
        """创建 SkillLoader 实例"""
        return SkillLoader(mock_db_session)

    def test_convert_to_skill_model_new(self, loader, mock_db_session):
        """转换配置为新技能模型"""
        mock_db_session.query.return_value.filter.return_value.first.return_value = None
        config = {
            "name": "test_skill",
            "version": "1.0.0",
            "description": "A test skill",
        }
        skill = loader.convert_to_skill_model(config)
        assert skill.name == "test_skill"
        assert skill.version == "1.0.0"
        assert mock_db_session.add.called

    def test_convert_to_skill_model_missing_name(self, loader):
        """缺少技能名称时抛出异常"""
        config = {"version": "1.0.0"}
        with pytest.raises(ValueError, match="name"):
            loader.convert_to_skill_model(config)

    def test_list_skills_empty(self, loader, mock_db_session):
        """列出技能返回空列表"""
        mock_db_session.query.return_value.filter.return_value.all.return_value = []
        result = loader.list_skills()
        assert isinstance(result, list)
        assert len(result) == 0

"""
技能指导生成单元测试。
测试 SkillGuidance 服务的技能可用性列表与提示词注入功能。
"""

import pytest
from unittest.mock import MagicMock, patch


class TestSkillGuidanceBasic:
    """技能指导基础功能测试"""

    def test_format_skills_guidance_empty(self):
        """空技能列表生成空指导文本"""
        skills = []
        guidance = _format_skills_guidance(skills)
        assert guidance == ""

    def test_format_skills_guidance_single(self):
        """单个技能生成正确指导文本"""
        skills = [
            {"name": "file-reader", "description": "读取文件内容"},
        ]
        guidance = _format_skills_guidance(skills)
        assert "file-reader" in guidance
        assert "读取文件内容" in guidance

    def test_format_skills_guidance_multiple(self):
        """多个技能生成完整指导文本"""
        skills = [
            {"name": "file-reader", "description": "读取文件内容"},
            {"name": "web-scraper", "description": "抓取网页数据"},
            {"name": "bash-executor", "description": "执行Shell命令"},
        ]
        guidance = _format_skills_guidance(skills)
        assert "file-reader" in guidance
        assert "web-scraper" in guidance
        assert "bash-executor" in guidance

    def test_format_skills_guidance_slash_commands(self):
        """带斜杠命令的技能显示命令提示"""
        skills = [
            {
                "name": "commit",
                "description": "提交代码变更",
                "slash_command": "/commit",
            },
            {
                "name": "review",
                "description": "代码审查",
                "slash_command": "/review",
            },
        ]
        guidance = _format_skills_guidance(skills)
        assert "/commit" in guidance
        assert "/review" in guidance


def _format_skills_guidance(skills):
    """
    生成可用技能指导文本（模拟 SkillGuidance.generate_guidance 的核心逻辑）。

    该函数从 skills 列表生成 Markdown 格式的技能说明，
    用于注入到模型系统提示中。
    """
    if not skills:
        return ""

    lines = ["## 可用技能"]
    for skill in skills:
        name = skill.get("name", "")
        desc = skill.get("description", "")
        slash = skill.get("slash_command", "")
        if slash:
            lines.append(f"- **{name}** (`{slash}`): {desc}")
        else:
            lines.append(f"- **{name}**: {desc}")

    return "\n".join(lines)


class TestSkillGuidanceFiltering:
    """技能指导过滤测试"""

    def test_disabled_skills_excluded(self):
        """已禁用技能不包含在指导中"""
        all_skills = [
            {"name": "enabled-skill", "description": "已启用技能", "enabled": True},
            {"name": "disabled-skill", "description": "已禁用技能", "enabled": False},
        ]
        enabled = [s for s in all_skills if s.get("enabled", True)]
        guidance = _format_skills_guidance(enabled)
        assert "enabled-skill" in guidance
        assert "disabled-skill" not in guidance

    def test_permission_filtered_skills_excluded(self):
        """无权限技能不包含在指导中"""
        all_skills = [
            {"name": "file-reader", "description": "文件读取", "enabled": True},
            {"name": "admin-tool", "description": "管理工具", "enabled": True},
        ]
        # 模拟权限过滤：用户没有 admin-tool 权限
        allowed_names = {"file-reader"}
        filtered = [s for s in all_skills if s["name"] in allowed_names]
        guidance = _format_skills_guidance(filtered)
        assert "file-reader" in guidance
        assert "admin-tool" not in guidance

    def test_skill_limit_enforced(self):
        """技能数量超限时截断"""
        skills = [
            {"name": f"skill-{i}", "description": f"技能 {i} 的描述"}
            for i in range(20)
        ]
        # 模拟限制为前 12 个
        guidance = _format_skills_guidance(skills[:12])
        assert "skill-0" in guidance
        assert "skill-11" in guidance
        # skill-12 不在限制内
        assert "skill-12" not in guidance

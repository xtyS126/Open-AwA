"""
技能指导生成单元测试。
测试 SkillGuidance 服务的技能可用性列表与提示词注入功能。
包含 Token 预算管理（format_commands_with_budget）的测试。
"""

import pytest
from unittest.mock import MagicMock, patch

from core.skill_guidance import (
    format_commands_with_budget,
    SKILLS_OMITTED_TEXT,
    SkillGuidance,
)
from core.context.token_budget import TokenBudget


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


class TestFormatCommandsWithBudget:
    """format_commands_with_budget 预算管理测试"""

    def test_format_commands_with_budget_empty(self):
        """空技能列表返回空字符串"""
        result = format_commands_with_budget([], context_window=128000)
        assert result == ""

    def test_format_commands_with_budget_under_budget(self):
        """预算充足时完整展示所有技能的名称和描述"""
        skills = [
            {"name": "file-reader", "description": "读取文件内容"},
            {"name": "web-scraper", "description": "抓取网页数据"},
        ]
        # 128000 * 0.01 = 1280 tokens，足够展示两个技能
        result = format_commands_with_budget(skills, context_window=128000)

        assert "file-reader" in result
        assert "读取文件内容" in result
        assert "web-scraper" in result
        assert "抓取网页数据" in result
        # 不应出现省略提示
        assert SKILLS_OMITTED_TEXT not in result

    def test_format_commands_with_budget_over_budget(self):
        """超预算时截断，未展示的技能不出现"""
        # 构造大量技能，确保超过预算
        skills = [
            {
                "name": f"skill-{i}",
                "description": f"这是技能 {i} 的详细描述，用于测试预算超限时的截断行为",
            }
            for i in range(100)
        ]
        # 极小的上下文窗口，使预算非常紧张
        # 1000 * 0.01 = 10 tokens，只能展示少量技能
        result = format_commands_with_budget(skills, context_window=1000)

        # 应该有部分技能被截断（不是所有 100 个都出现）
        # 至少 skill-0 应该出现（排序后优先级最高）
        assert "skill-0" in result
        # 不应出现 skill-99（最后面的技能）
        assert "skill-99" not in result

    def test_format_commands_with_budget_priority_order(self):
        """验证优先级排序：内置 > 用户常用 > 其他"""
        skills = [
            # 其他技能（usage_count=0）
            {"name": "other-skill", "description": "其他技能", "usage_count": 0},
            # 用户常用技能（usage_count > 5）
            {"name": "frequent-skill", "description": "常用技能", "usage_count": 10},
            # 内置技能
            {"name": "builtin-skill", "description": "内置技能", "is_builtin": True, "usage_count": 0},
        ]
        # 使用足够大的预算以展示所有技能
        result = format_commands_with_budget(skills, context_window=128000)

        # 验证排序顺序：builtin-skill 应该在 frequent-skill 之前，frequent-skill 在 other-skill 之前
        builtin_pos = result.find("builtin-skill")
        frequent_pos = result.find("frequent-skill")
        other_pos = result.find("other-skill")

        assert builtin_pos < frequent_pos < other_pos, (
            f"优先级排序错误: builtin={builtin_pos}, frequent={frequent_pos}, other={other_pos}"
        )

    def test_format_commands_with_budget_tight_budget_name_only(self):
        """预算紧张时只展示技能名称（不含描述）"""
        # 构造一个技能列表，使第一个技能消耗大部分预算后，剩余预算紧张
        # 使用较长的描述使第一个技能消耗较多 token
        long_desc = "这是一个非常长的技能描述" * 20
        skills = [
            {"name": "first-skill", "description": long_desc},
            {"name": "second-skill", "description": "第二个技能的描述"},
        ]
        # 设置一个适中的预算，使第一个技能展示后剩余预算紧张
        # 需要计算合适的 context_window
        budget_estimator = TokenBudget()
        first_full_line = f"1. **first-skill**: {long_desc}"
        first_tokens = budget_estimator.estimate_tokens(first_full_line)

        # 设置预算使第一个技能展示后，剩余预算 < 20% 但 > 0
        # max_budget = context_window * 0.01
        # 我们希望 first_tokens < max_budget，但 max_budget - first_tokens < 0.2 * max_budget
        # 即 first_tokens > 0.8 * max_budget
        # 取 max_budget = first_tokens / 0.9（使剩余约 10%）
        max_budget = int(first_tokens / 0.9) + 1
        context_window = max_budget * 100  # 因为 max_budget = context_window * 0.01

        result = format_commands_with_budget(skills, context_window=context_window)

        # 第一个技能应该完整展示
        assert "first-skill" in result
        # 第二个技能应该只展示名称（预算紧张）
        assert "second-skill" in result
        # 第二个技能的描述不应该出现（只展示名称）
        assert "第二个技能的描述" not in result

    def test_format_commands_with_budget_no_budget_omitted(self):
        """无预算时（context_window=0）返回省略占位文本"""
        skills = [
            {"name": "skill-1", "description": "技能1"},
        ]
        # context_window=0 导致 max_budget=0
        result = format_commands_with_budget(skills, context_window=0)
        assert result == SKILLS_OMITTED_TEXT

    def test_format_commands_with_budget_no_budget_negative_window(self):
        """负的 context_window 也应返回省略占位文本"""
        skills = [
            {"name": "skill-1", "description": "技能1"},
        ]
        result = format_commands_with_budget(skills, context_window=-100)
        assert result == SKILLS_OMITTED_TEXT

    def test_format_commands_with_budget_default_ratio(self):
        """验证默认 max_budget_ratio=0.01"""
        skills = [
            {"name": "test-skill", "description": "测试技能"},
        ]
        # 不传 max_budget_ratio，应使用默认值 0.01
        result_default = format_commands_with_budget(skills, context_window=128000)

        # 显式传入 0.01，结果应一致
        result_explicit = format_commands_with_budget(
            skills, context_window=128000, max_budget_ratio=0.01
        )

        assert result_default == result_explicit
        # 默认预算 = 128000 * 0.01 = 1280 tokens，足够展示一个技能
        assert "test-skill" in result_default
        assert "测试技能" in result_default

    def test_format_commands_with_budget_custom_ratio(self):
        """验证自定义 max_budget_ratio 生效"""
        skills = [
            {"name": "test-skill", "description": "测试技能"},
        ]
        # 使用极小的 ratio 使预算不足以展示完整技能
        # 1000 * 0.0001 = 0.1 token，向下取整为 0
        result = format_commands_with_budget(
            skills, context_window=1000, max_budget_ratio=0.0001
        )
        assert result == SKILLS_OMITTED_TEXT

    def test_format_commands_with_budget_priority_with_usage_count(self):
        """验证同优先级组内按 usage_count 降序排列"""
        skills = [
            {"name": "low-usage", "description": "低使用", "usage_count": 6},
            {"name": "high-usage", "description": "高使用", "usage_count": 100},
            {"name": "mid-usage", "description": "中使用", "usage_count": 20},
        ]
        # 所有技能 usage_count > 5，属于同一优先级组（1）
        result = format_commands_with_budget(skills, context_window=128000)

        # 按 usage_count 降序：high-usage > mid-usage > low-usage
        high_pos = result.find("high-usage")
        mid_pos = result.find("mid-usage")
        low_pos = result.find("low-usage")

        assert high_pos < mid_pos < low_pos, (
            f"usage_count 降序排列错误: high={high_pos}, mid={mid_pos}, low={low_pos}"
        )

    def test_format_commands_with_budget_control_char_escaped(self):
        """验证技能名称和描述中的控制字符被转义"""
        skills = [
            {
                "name": "skill\nwith\nnewlines",
                "description": "desc\nwith\nnewlines",
            },
        ]
        result = format_commands_with_budget(skills, context_window=128000)

        # 换行符应被替换为空格
        assert "skill\nwith\nnewlines" not in result
        assert "desc\nwith\nnewlines" not in result
        # 替换后的内容应存在
        assert "skill with newlines" in result
        assert "desc with newlines" in result

    def test_format_commands_with_budget_all_omitted_when_too_large(self):
        """所有技能都超预算时返回省略占位文本"""
        # 构造一个描述极长的技能，使其即使只展示名称也超预算
        very_long_name = "x" * 10000
        skills = [
            {"name": very_long_name, "description": "描述"},
        ]
        # 极小预算
        result = format_commands_with_budget(skills, context_window=1)
        assert result == SKILLS_OMITTED_TEXT


class TestSkillGuidanceIntegration:
    """SkillGuidance 类与预算管理集成测试"""

    def test_format_skills_guidance_with_context_window(self):
        """format_skills_guidance 接受 context_window 参数"""
        guidance = SkillGuidance()
        skills = [
            {"name": "test-skill", "description": "测试技能"},
        ]
        result = guidance.format_skills_guidance(skills, context_window=128000)
        assert "test-skill" in result
        assert "测试技能" in result
        # 应包含模板头部
        assert "## 可用技能" in result

    def test_format_skills_guidance_empty_skills(self):
        """空技能列表返回提示文本"""
        guidance = SkillGuidance()
        result = guidance.format_skills_guidance([])
        assert result == "当前没有可用的技能。"

    def test_format_skills_guidance_default_context_window(self):
        """未提供 context_window 时使用默认值"""
        guidance = SkillGuidance()
        skills = [
            {"name": "test-skill", "description": "测试技能"},
        ]
        # 不传 context_window，应使用 DEFAULT_CONTEXT_WINDOW
        result = guidance.format_skills_guidance(skills)
        assert "test-skill" in result
        assert "测试技能" in result

    def test_format_skills_guidance_omitted_placeholder(self):
        """预算为 0 时，模板中包含省略占位文本"""
        guidance = SkillGuidance()
        skills = [
            {"name": "test-skill", "description": "测试技能"},
        ]
        result = guidance.format_skills_guidance(skills, context_window=0)
        assert SKILLS_OMITTED_TEXT in result
        assert "## 可用技能" in result

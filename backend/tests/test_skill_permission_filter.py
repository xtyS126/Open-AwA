"""
技能权限过滤单元测试。
测试根据代理权限规则过滤可用技能列表的功能。
"""

import pytest
from unittest.mock import MagicMock

from core.permission_manager import wildcard_match, evaluate_permission, evaluate_effect, PermissionRule, PermissionEffect


class TestWildcardMatch:
    """通配符匹配测试"""

    def test_exact_match(self):
        """完全匹配"""
        assert wildcard_match("skill:read", "skill:read") is True

    def test_global_wildcard(self):
        """全局通配符匹配任意值"""
        assert wildcard_match("*", "skill:read") is True
        assert wildcard_match("*", "anything") is True

    def test_prefix_wildcard(self):
        """前缀通配符匹配"""
        assert wildcard_match("skill:*", "skill:read") is True
        assert wildcard_match("skill:*", "skill:write") is True
        assert wildcard_match("skill:*", "skill:execute") is True

    def test_prefix_wildcard_no_match(self):
        """前缀通配符不匹配不同前缀"""
        assert wildcard_match("skill:*", "plugin:read") is False
        assert wildcard_match("skill:*", "task:execute") is False

    def test_suffix_wildcard(self):
        """后缀通配符匹配"""
        assert wildcard_match("*:read", "skill:read") is True
        assert wildcard_match("*:read", "file:read") is True

    def test_no_match(self):
        """完全不同时不匹配"""
        assert wildcard_match("skill:write", "file:read") is False

    def test_empty_strings(self):
        """空字符串处理"""
        assert wildcard_match("", "skill:read") is False
        assert wildcard_match("skill:read", "") is False


class TestSkillPermissionFilter:
    """技能权限过滤测试"""

    @pytest.fixture
    def mock_skills(self):
        """创建模拟技能列表"""
        return [
            {"name": "file-reader", "description": "读取文件技能", "enabled": True},
            {"name": "file-writer", "description": "写入文件技能", "enabled": True},
            {"name": "web-scraper", "description": "网页抓取技能", "enabled": True},
            {"name": "disabled-skill", "description": "已禁用技能", "enabled": False},
        ]

    def _filter_skills(self, skills, allowed_actions, allowed_resources="*"):
        """根据权限过滤技能（模拟 get_available_skills 的权限过滤逻辑）"""
        rules = [
            PermissionRule(action=action, resource=allowed_resources, effect=PermissionEffect.ALLOW)
            for action in allowed_actions
        ]
        # 添加默认 deny 规则
        rules.append(PermissionRule(action="*", resource="*", effect=PermissionEffect.DENY))

        filtered = []
        for skill in skills:
            if not skill.get("enabled", False):
                continue
            # 使用通配符匹配判断技能是否允许
            effect = evaluate_effect(f"skill:{skill['name']}", allowed_resources, rules)
            if effect == PermissionEffect.ALLOW:
                filtered.append(skill)
        return filtered

    def test_filter_allow_all(self, mock_skills):
        """允许所有技能时返回全部已启用技能"""
        rules = [PermissionRule(action="*", resource="*", effect=PermissionEffect.ALLOW)]
        filtered = []
        for skill in mock_skills:
            if not skill.get("enabled", False):
                continue
            effect = evaluate_effect(f"skill:{skill['name']}", "*", rules)
            if effect == PermissionEffect.ALLOW:
                filtered.append(skill)
        assert len(filtered) == 3  # 3 个已启用技能

    def test_filter_deny_all(self, mock_skills):
        """拒绝所有技能时返回空列表"""
        rules = [PermissionRule(action="*", resource="*", effect=PermissionEffect.DENY)]
        filtered = []
        for skill in mock_skills:
            if not skill.get("enabled", False):
                continue
            effect = evaluate_effect(f"skill:{skill['name']}", "*", rules)
            if effect == PermissionEffect.ALLOW:
                filtered.append(skill)
        assert len(filtered) == 0

    def test_filter_allow_specific(self, mock_skills):
        """只允许特定技能（last-match-wins：后匹配的规则覆盖前面的）"""
        rules = [
            PermissionRule(action="*", resource="*", effect=PermissionEffect.DENY),
            PermissionRule(action="skill:file-reader", resource="*", effect=PermissionEffect.ALLOW),
        ]
        filtered = []
        for skill in mock_skills:
            if not skill.get("enabled", False):
                continue
            effect = evaluate_effect(f"skill:{skill['name']}", "*", rules)
            if effect == PermissionEffect.ALLOW:
                filtered.append(skill)
        assert len(filtered) == 1
        assert filtered[0]["name"] == "file-reader"

    def test_last_match_wins(self, mock_skills):
        """后匹配的规则覆盖前面的规则（last-match-wins）"""
        # 先 deny 所有，再 allow 特定技能
        rules = [
            PermissionRule(action="*", resource="*", effect=PermissionEffect.DENY),
            PermissionRule(action="skill:web-scraper", resource="*", effect=PermissionEffect.ALLOW),
        ]
        filtered = []
        for skill in mock_skills:
            if not skill.get("enabled", False):
                continue
            effect = evaluate_effect(f"skill:{skill['name']}", "*", rules)
            if effect == PermissionEffect.ALLOW:
                filtered.append(skill)
        assert len(filtered) == 1
        assert filtered[0]["name"] == "web-scraper"

    def test_disabled_skills_always_filtered(self, mock_skills):
        """已禁用技能始终被过滤"""
        rules = [PermissionRule(action="*", resource="*", effect=PermissionEffect.ALLOW)]
        filtered = []
        for skill in mock_skills:
            if not skill.get("enabled", False):
                continue
            effect = evaluate_effect(f"skill:{skill['name']}", "*", rules)
            if effect == PermissionEffect.ALLOW:
                filtered.append(skill)
        # 已禁用的技能不应在结果中
        disabled_names = [s["name"] for s in filtered if not s.get("enabled")]
        assert len(disabled_names) == 0


class TestPermissionEvaluation:
    """权限评估优先级测试"""

    def test_global_rules_override_agent_rules(self):
        """全局规则因 last-match-wins 覆盖先匹配的代理规则"""
        agent_rules = [
            PermissionRule(action="write", resource="*", effect=PermissionEffect.DENY),
        ]
        global_rules = [
            PermissionRule(action="*", resource="*", effect=PermissionEffect.ALLOW),
        ]
        # agent_rules 先匹配到 DENY，但后面 global_rules 的 ALLOW 通过 last-match-wins 覆盖
        # 所以最终应该是 ALLOW
        effect = evaluate_effect("write", "file:test", agent_rules, global_rules)
        assert effect == PermissionEffect.ALLOW

    def test_saved_rules_override_all(self):
        """已保存规则覆盖代理和全局规则"""
        agent_rules = [
            PermissionRule(action="*", resource="*", effect=PermissionEffect.DENY),
        ]
        global_rules = [
            PermissionRule(action="*", resource="*", effect=PermissionEffect.DENY),
        ]
        saved_rules = [
            PermissionRule(action="write", resource="*", effect=PermissionEffect.ALLOW),
        ]
        effect = evaluate_effect("write", "file:test", agent_rules, global_rules, saved_rules)
        assert effect == PermissionEffect.ALLOW

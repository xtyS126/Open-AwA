"""
PermissionManager 单元测试。
测试权限评估、请求/回复流程、通配符匹配、持久化。
"""

import asyncio
import pytest

from core.permission_manager import (
    PermissionManager,
    PermissionRule,
    PermissionEffect,
    PermissionDeniedError,
    evaluate_effect,
    evaluate_permission,
    wildcard_match,
)


class TestWildcardMatch:
    """通配符匹配测试"""

    def test_exact_match(self):
        """精确匹配"""
        assert wildcard_match("read", "read") is True
        assert wildcard_match("bash", "read") is False

    def test_glob_match(self):
        """全局通配符匹配"""
        assert wildcard_match("*", "anything") is True
        assert wildcard_match("*", "") is True

    def test_prefix_wildcard(self):
        """前缀通配符匹配"""
        assert wildcard_match("skill:*", "skill:read") is True
        assert wildcard_match("skill:*", "skill:write") is True
        assert wildcard_match("skill:*", "plugin:read") is False
        assert wildcard_match("skill:*", "skill") is False

    def test_suffix_wildcard(self):
        """后缀通配符匹配"""
        assert wildcard_match("*:read", "skill:read") is True
        assert wildcard_match("*:read", "file:read") is True
        assert wildcard_match("*:read", "file:write") is False


class TestEvaluatePermission:
    """权限评估测试"""

    def test_allow_rule(self):
        """允许规则测试"""
        rules = [PermissionRule(action="read", resource="*", effect=PermissionEffect.ALLOW)]
        effect = evaluate_effect("read", "file.txt", rules)
        assert effect == PermissionEffect.ALLOW

    def test_deny_rule(self):
        """拒绝规则测试"""
        rules = [PermissionRule(action="*", resource="*", effect=PermissionEffect.DENY)]
        effect = evaluate_effect("bash", "rm -rf /", rules)
        assert effect == PermissionEffect.DENY

    def test_deny_overrides_allow(self):
        """deny 优先级高于 allow（后匹配覆盖）"""
        rules = [
            PermissionRule(action="*", resource="*", effect=PermissionEffect.ALLOW),
            PermissionRule(action="bash", resource="*", effect=PermissionEffect.DENY),
        ]
        effect = evaluate_effect("bash", "ls", rules)
        assert effect == PermissionEffect.DENY

    def test_no_rule_defaults_to_ask(self):
        """无匹配规则时默认 ASK"""
        rules: list = []
        effect = evaluate_effect("unknown_action", "some_resource", rules)
        assert effect == PermissionEffect.ASK

    def test_multiple_rulesets(self):
        """多规则集合合并测试"""
        agent_rules = [PermissionRule(action="read", resource="*", effect=PermissionEffect.ALLOW)]
        global_rules = [PermissionRule(action="write", resource="*", effect=PermissionEffect.DENY)]

        # read 应该被 agent_rules 允许
        assert evaluate_effect("read", "file", agent_rules, global_rules) == PermissionEffect.ALLOW
        # write 应该被 global_rules 拒绝（后匹配）
        assert evaluate_effect("write", "file", agent_rules, global_rules) == PermissionEffect.DENY


class TestPermissionManager:
    """PermissionManager 集成测试"""

    @pytest.fixture
    def manager(self):
        """创建 PermissionManager 实例"""
        return PermissionManager()

    @pytest.mark.asyncio
    async def test_ask_allow(self, manager):
        """测试 ask 方法 - allow 路径"""
        # plan 代理允许 read 操作
        result = await manager.ask(
            session_id="test-session",
            action="read",
            resources=["file.txt"],
            agent_id="plan",
        )
        assert result["effect"] == "allow"

    @pytest.mark.asyncio
    async def test_ask_deny(self, manager):
        """测试 ask 方法 - deny 路径"""
        # plan 代理拒绝 write 操作
        with pytest.raises(PermissionDeniedError):
            await manager.ask(
                session_id="test-session",
                action="edit",
                resources=["file.txt"],
                agent_id="plan",
            )

    @pytest.mark.asyncio
    async def test_ask_pending(self, manager):
        """测试 ask 方法 - ask 路径（创建待处理请求）"""
        # general-purpose 代理对 write 操作需要确认
        result = await manager.ask(
            session_id="test-session",
            action="edit",
            resources=["file.txt"],
            agent_id="general-purpose",
        )
        assert result["effect"] == "ask"
        assert result["id"].startswith("per_")

        # 验证待处理请求存在
        pending = manager.get_pending_requests("test-session")
        assert len(pending) == 1
        assert pending[0].action == "edit"

    @pytest.mark.asyncio
    async def test_reply_once(self, manager):
        """测试用户回复 - once"""
        result = await manager.ask(
            session_id="test-session",
            action="edit",
            resources=["file.txt"],
            agent_id="general-purpose",
        )
        assert result["effect"] == "ask"

        # 用户回复 once
        await manager.reply(result["id"], "once")
        # 请求应该被清除
        assert len(manager.get_pending_requests("test-session")) == 0

    @pytest.mark.asyncio
    async def test_reply_reject(self, manager):
        """测试用户回复 - reject"""
        result = await manager.ask(
            session_id="test-session",
            action="edit",
            resources=["file.txt"],
            agent_id="general-purpose",
        )

        # 用户拒绝
        await manager.reply(result["id"], "reject")
        assert len(manager.get_pending_requests("test-session")) == 0

    @pytest.mark.asyncio
    async def test_assert_permission_allow(self, manager):
        """测试 assert_permission - allow 路径"""
        # 应该不抛出异常
        await manager.assert_permission(
            session_id="test-session",
            action="read",
            resources=["file.txt"],
            agent_id="plan",
        )

    @pytest.mark.asyncio
    async def test_assert_permission_deny(self, manager):
        """测试 assert_permission - deny 路径"""
        with pytest.raises(PermissionDeniedError):
            await manager.assert_permission(
                session_id="test-session",
                action="edit",
                resources=["file.txt"],
                agent_id="plan",
            )

    @pytest.mark.asyncio
    async def test_build_agent_rules(self, manager):
        """测试各代理类型的默认规则"""
        # plan 代理：只读
        assert await manager.evaluate("read", "file", "plan") == PermissionEffect.ALLOW
        assert await manager.evaluate("edit", "file", "plan") == PermissionEffect.DENY

        # build 代理：全权限
        assert await manager.evaluate("anything", "anywhere", "build") == PermissionEffect.ALLOW

        # general-purpose 代理：写操作需要询问
        assert await manager.evaluate("read", "file", "general-purpose") == PermissionEffect.ALLOW
        assert await manager.evaluate("edit", "file", "general-purpose") == PermissionEffect.ASK

    @pytest.mark.asyncio
    async def test_session_cancel(self, manager):
        """测试取消会话的待处理请求"""
        await manager.ask(
            session_id="session-1",
            action="edit",
            resources=["file1.txt"],
            agent_id="general-purpose",
        )
        await manager.ask(
            session_id="session-2",
            action="write",
            resources=["file2.txt"],
            agent_id="general-purpose",
        )

        # 取消 session-1
        cancelled = manager.cancel_session_requests("session-1")
        assert cancelled == 1
        assert len(manager.get_pending_requests("session-1")) == 0
        assert len(manager.get_pending_requests("session-2")) == 1

    @pytest.mark.asyncio
    async def test_reply_on_nonexistent_request(self, manager):
        """测试回复不存在的权限请求"""
        import pytest
        with pytest.raises(ValueError, match="不存在或已过期"):
            await manager.reply("non_existent_request_id", "once")


class TestEffectPriority:
    """effect 优先级（deny > allow > ask）修复测试"""

    def test_deny_cannot_be_overridden_by_later_allow(self):
        """deny 不可被后置 allow 覆盖（用户 always allow 无法绕过代理 deny）"""
        rules = [
            PermissionRule(action="write", resource="*", effect=PermissionEffect.DENY),
            PermissionRule(action="write", resource="*", effect=PermissionEffect.ALLOW),
        ]
        effect = evaluate_effect("write", "file.txt", rules)
        assert effect == PermissionEffect.DENY

    def test_deny_overrides_allow_in_different_rulesets(self):
        """跨规则集合（代理 deny + 已保存 allow）deny 仍优先"""
        agent_rules = [PermissionRule(action="bash", resource="*", effect=PermissionEffect.DENY)]
        saved_rules = [PermissionRule(action="bash", resource="*", effect=PermissionEffect.ALLOW)]
        effect = evaluate_effect("bash", "rm -rf /", agent_rules, saved_rules)
        assert effect == PermissionEffect.DENY

    def test_deny_overrides_ask(self):
        """deny 优先级高于 ask"""
        rules = [
            PermissionRule(action="*", resource="*", effect=PermissionEffect.ASK),
            PermissionRule(action="bash", resource="*", effect=PermissionEffect.DENY),
        ]
        effect = evaluate_effect("bash", "ls", rules)
        assert effect == PermissionEffect.DENY

    def test_allow_overrides_ask(self):
        """allow 优先级高于 ask"""
        rules = [
            PermissionRule(action="*", resource="*", effect=PermissionEffect.ASK),
            PermissionRule(action="read", resource="*", effect=PermissionEffect.ALLOW),
        ]
        assert evaluate_effect("read", "file", rules) == PermissionEffect.ALLOW

    def test_same_effect_last_match_wins(self):
        """同 effect 下最后一条匹配生效（保持同级 last-match-wins）"""
        rules = [
            PermissionRule(action="*", resource="*", effect=PermissionEffect.ALLOW),
            PermissionRule(action="read", resource="*", effect=PermissionEffect.ALLOW),
        ]
        rule = evaluate_permission("read", "file", rules)
        assert rule.effect == PermissionEffect.ALLOW
        assert rule.action == "read"

    @pytest.mark.asyncio
    async def test_plan_agent_rules_keep_read_allow_write_deny(self):
        """plan 代理在 effect 优先级语义下：只读放行、写操作拒绝"""
        manager = PermissionManager()
        assert await manager.evaluate("read", "file", "plan") == PermissionEffect.ALLOW
        assert await manager.evaluate("glob", "src", "plan") == PermissionEffect.ALLOW
        assert await manager.evaluate("edit", "file", "plan") == PermissionEffect.DENY
        assert await manager.evaluate("write", "file", "plan") == PermissionEffect.DENY
        assert await manager.evaluate("bash", "ls", "plan") == PermissionEffect.DENY
        assert await manager.evaluate("delete", "file", "plan") == PermissionEffect.DENY

    @pytest.mark.asyncio
    async def test_general_purpose_rules_read_allow_write_ask(self):
        """general-purpose 代理：只读放行、写操作 ASK 确认"""
        manager = PermissionManager()
        assert await manager.evaluate("read", "file", "general-purpose") == PermissionEffect.ALLOW
        assert await manager.evaluate("edit", "file", "general-purpose") == PermissionEffect.ASK
        assert await manager.evaluate("write", "file", "general-purpose") == PermissionEffect.ASK
        assert await manager.evaluate("bash", "ls", "general-purpose") == PermissionEffect.ASK

    @pytest.mark.asyncio
    async def test_plan_agent_deny_not_overridden_by_saved_allow(self):
        """plan 代理 deny 不可被用户已保存的 allow 规则覆盖"""
        manager = PermissionManager()
        saved_rules = [
            PermissionRule(action="write", resource="*", effect=PermissionEffect.ALLOW),
            PermissionRule(action="edit", resource="*", effect=PermissionEffect.ALLOW),
        ]
        # 模拟已保存规则作为最后一个规则集合参与评估
        effect = evaluate_effect("edit", "file", manager._get_agent_rules("plan"), saved_rules)
        assert effect == PermissionEffect.DENY

"""
灰度发布功能开关测试。
"""

from config.feature_flags import FeatureFlagManager


def test_feature_flag_allow_and_deny_accounts():
    manager = FeatureFlagManager()
    manager.set_rule(
        name="weixin_ai_interaction_v2",
        enabled=True,
        rollout_percentage=0,
        allow_accounts=["a1"],
        deny_accounts=["d1"],
    )

    assert manager.is_enabled("weixin_ai_interaction_v2", account_id="a1") is True
    assert manager.is_enabled("weixin_ai_interaction_v2", account_id="d1") is False
    assert manager.is_enabled("weixin_ai_interaction_v2", account_id="other") is False


def test_feature_flag_rollout_and_rollback():
    manager = FeatureFlagManager()
    manager.set_rule("weixin_ai_interaction_v2", enabled=True, rollout_percentage=100)
    assert manager.is_enabled("weixin_ai_interaction_v2", account_id="acc", user_id="u") is True

    manager.snapshot("weixin_ai_interaction_v2")
    manager.set_rule("weixin_ai_interaction_v2", enabled=False, rollout_percentage=0)
    assert manager.is_enabled("weixin_ai_interaction_v2", account_id="acc", user_id="u") is False

    assert manager.rollback("weixin_ai_interaction_v2") is True
    assert manager.is_enabled("weixin_ai_interaction_v2", account_id="acc", user_id="u") is True


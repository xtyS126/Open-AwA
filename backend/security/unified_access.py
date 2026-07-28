"""
统一访问控制模块 — 按渠道配置白名单/黑名单/待审批策略。
"""
from enum import Enum
from typing import Optional
from loguru import logger


class AccessPolicy(Enum):
    ALLOW_ALL = "allow_all"
    WHITELIST = "whitelist"
    BLACKLIST = "blacklist"
    PENDING_APPROVAL = "pending_approval"


class UnifiedAccessControl:
    """
    统一访问控制器。
    支持按渠道配置访问策略：白名单、黑名单和待审批模式。
    """

    def __init__(self):
        self._policies: dict[str, dict] = {}

    def configure_channel(
        self,
        channel: str,
        policy: AccessPolicy = AccessPolicy.ALLOW_ALL,
        whitelist: Optional[list[str]] = None,
        blacklist: Optional[list[str]] = None,
        pending_list: Optional[list[str]] = None,
    ):
        """配置渠道访问控制。"""
        self._policies[channel] = {
            "policy": policy,
            "whitelist": set(whitelist or []),
            "blacklist": set(blacklist or []),
            "pending": set(pending_list or []),
        }
        logger.bind(event="access_control_configured", channel=channel, policy=policy.value).info("访问控制已配置")

    def check_access(self, channel: str, user_id: str) -> tuple[bool, str]:
        """
        检查用户是否有权访问指定渠道。
        返回 (allowed, reason)。
        """
        config = self._policies.get(channel, {"policy": AccessPolicy.ALLOW_ALL})
        policy = config.get("policy", AccessPolicy.ALLOW_ALL)

        if policy == AccessPolicy.ALLOW_ALL:
            return True, "allowed"

        if policy == AccessPolicy.BLACKLIST:
            blacklist = config.get("blacklist", set())
            if user_id in blacklist:
                return False, f"用户 {user_id} 在黑名单中"
            return True, "allowed"

        if policy == AccessPolicy.WHITELIST:
            whitelist = config.get("whitelist", set())
            if user_id not in whitelist:
                return False, f"用户 {user_id} 不在白名单中"
            return True, "allowed"

        if policy == AccessPolicy.PENDING_APPROVAL:
            pending = config.get("pending", set())
            whitelist = config.get("whitelist", set())
            if user_id in whitelist:
                return True, "allowed"
            if user_id in pending:
                return False, "pending_approval"
            # 新用户加入待审批列表
            pending.add(user_id)
            config["pending"] = pending
            return False, "pending_approval"

        return False, "unknown_policy"

    def approve_user(self, channel: str, user_id: str):
        """审批通过用户。"""
        config = self._policies.get(channel, {})
        pending = config.get("pending", set())
        pending.discard(user_id)
        whitelist = config.get("whitelist", set())
        whitelist.add(user_id)

    def block_user(self, channel: str, user_id: str):
        """将用户加入黑名单。"""
        config = self._policies.get(channel, {})
        blacklist = config.get("blacklist", set())
        blacklist.add(user_id)
        # 从白名单中移除
        whitelist = config.get("whitelist", set())
        whitelist.discard(user_id)

    def get_pending_approvals(self, channel: str) -> list[str]:
        """获取待审批用户列表。"""
        config = self._policies.get(channel, {})
        return list(config.get("pending", set()))

    def get_config(self, channel: str) -> dict:
        """获取渠道访问配置。"""
        config = self._policies.get(channel, {"policy": AccessPolicy.ALLOW_ALL})
        return {
            "policy": config.get("policy", AccessPolicy.ALLOW_ALL).value,
            "whitelist": list(config.get("whitelist", set())),
            "blacklist": list(config.get("blacklist", set())),
            "pending": list(config.get("pending", set())),
        }


# 全局单例
_unified_access_control: Optional[UnifiedAccessControl] = None


def get_access_control() -> UnifiedAccessControl:
    global _unified_access_control
    if _unified_access_control is None:
        _unified_access_control = UnifiedAccessControl()
    return _unified_access_control

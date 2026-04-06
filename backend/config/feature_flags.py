"""
功能开关与灰度发布配置模块。
提供按账号和用户维度的稳定分流能力，并支持快速回滚。
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class FeatureRule:
    """
    单个功能开关规则。
    """
    enabled: bool = False
    rollout_percentage: int = 0
    allow_accounts: list[str] = field(default_factory=list)
    deny_accounts: list[str] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)


class FeatureFlagManager:
    """
    功能开关管理器。
    """

    def __init__(self) -> None:
        self._rules: Dict[str, FeatureRule] = {}
        self._snapshots: Dict[str, FeatureRule] = {}

    def set_rule(
        self,
        name: str,
        enabled: bool,
        rollout_percentage: int = 0,
        allow_accounts: Optional[list[str]] = None,
        deny_accounts: Optional[list[str]] = None,
    ) -> None:
        self._rules[name] = FeatureRule(
            enabled=bool(enabled),
            rollout_percentage=max(0, min(100, int(rollout_percentage))),
            allow_accounts=list(allow_accounts or []),
            deny_accounts=list(deny_accounts or []),
            updated_at=time.time(),
        )

    def is_enabled(self, name: str, account_id: str = "", user_id: str = "") -> bool:
        rule = self._rules.get(name)
        if rule is None:
            return False
        if not rule.enabled:
            return False
        if account_id and account_id in rule.deny_accounts:
            return False
        if account_id and account_id in rule.allow_accounts:
            return True
        if rule.rollout_percentage >= 100:
            return True
        if rule.rollout_percentage <= 0:
            return False

        bucket_source = f"{name}:{account_id}:{user_id}".encode("utf-8")
        bucket = int(hashlib.md5(bucket_source).hexdigest()[:8], 16) % 100
        return bucket < rule.rollout_percentage

    def snapshot(self, name: str) -> None:
        rule = self._rules.get(name)
        if rule is None:
            return
        self._snapshots[name] = FeatureRule(
            enabled=rule.enabled,
            rollout_percentage=rule.rollout_percentage,
            allow_accounts=list(rule.allow_accounts),
            deny_accounts=list(rule.deny_accounts),
            updated_at=rule.updated_at,
        )

    def rollback(self, name: str) -> bool:
        snapshot = self._snapshots.get(name)
        if snapshot is None:
            return False
        self._rules[name] = FeatureRule(
            enabled=snapshot.enabled,
            rollout_percentage=snapshot.rollout_percentage,
            allow_accounts=list(snapshot.allow_accounts),
            deny_accounts=list(snapshot.deny_accounts),
            updated_at=time.time(),
        )
        return True

    def get_rule(self, name: str) -> Dict[str, Any]:
        rule = self._rules.get(name)
        if rule is None:
            return {}
        return {
            "enabled": rule.enabled,
            "rollout_percentage": rule.rollout_percentage,
            "allow_accounts": list(rule.allow_accounts),
            "deny_accounts": list(rule.deny_accounts),
            "updated_at": rule.updated_at,
        }


feature_flags = FeatureFlagManager()


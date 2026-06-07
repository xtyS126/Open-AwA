"""
网络出站策略执行模块。

根据配置过滤网络出站请求：
- allow_all: 无限制
- block_local: 拒绝内网地址
- allowlist: 仅允许白名单内的 CIDR
"""

from __future__ import annotations

import ipaddress
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from loguru import logger

from core.autonomous.config import AutonomousConfig, NetworkPolicy


# 云元数据端点（始终拒绝，即使 allow_all）
_ALWAYS_BLOCKED_HOSTS: frozenset = frozenset({
    "169.254.169.254",
    "metadata.google.internal",
})


def _parse_host_to_ip(host: str) -> Optional[ipaddress.IPv4Address]:
    """尝试将主机名解析为 IP 地址，失败返回 None。"""
    try:
        # 如果是 IP 地址
        return ipaddress.IPv4Address(host)
    except ValueError:
        # 如果不是 IP，跳过（DNS 解析由操作系统处理，此处不发起网络请求）
        return None


class NetworkPolicyChecker:
    """网络出站策略检查器。"""

    def __init__(self, config: AutonomousConfig):
        self._policy = config.network_policy
        self._allowlist = [
            ipaddress.IPv4Network(cidr.strip())
            for cidr in config.network_allowlist
            if cidr.strip()
        ]
        logger.info(
            f"网络策略已设置: policy={self._policy.value}, "
            f"allowlist={len(self._allowlist)} entries"
        )

    def check(self, url_or_host: str) -> Tuple[bool, str]:
        """检查网络目标是否允许。

        Args:
            url_or_host: 完整的 URL 或纯主机名/IP

        Returns:
            (is_allowed, error_message)
        """
        if not url_or_host:
            return True, ""

        # 提取主机名
        host = url_or_host
        try:
            parsed = urlparse(url_or_host)
            if parsed.hostname:
                host = parsed.hostname
        except Exception:
            pass  # 不是 URL，直接当主机名处理

        # 云元数据端点始终拒绝
        if host in _ALWAYS_BLOCKED_HOSTS or host == "169.254.169.254":
            logger.warning(f"[网络策略] 拒绝访问云元数据端点: {host}")
            return False, (
                f"网络策略拒绝: 目标地址 '{host}' 是云元数据端点，"
                f"在任何网络策略下均被禁止。"
            )

        # allow_all: 其余全部放行
        if self._policy == NetworkPolicy.ALLOW_ALL:
            return True, ""

        # 尝试解析 IP
        ip = _parse_host_to_ip(host)
        if ip is None:
            # 非 IP 地址（纯域名），策略为 block_local 时放行，allowlist 时需谨慎
            if self._policy == NetworkPolicy.BLOCK_LOCAL:
                return True, ""
            # allowlist 模式下，域名无法精确匹配，建议使用 IP
            logger.warning(f"[网络策略] allowlist 模式下无法验证域名: {host}，已放行")
            return True, ""

        # block_local: 拒绝内网地址
        if self._policy == NetworkPolicy.BLOCK_LOCAL:
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                logger.warning(f"[网络策略] 拒绝内网地址: {host}")
                return False, (
                    f"网络策略拒绝: 目标地址 '{host}' 位于禁止的内网段。"
                    f"当前策略: block_local。请使用允许的外部地址。"
                )
            return True, ""

        # allowlist: 仅允许白名单内的地址
        if self._policy == NetworkPolicy.ALLOWLIST:
            for network in self._allowlist:
                if ip in network:
                    return True, ""

            logger.warning(f"[网络策略] 拒绝非白名单地址: {host}")
            return False, (
                f"网络策略拒绝: 目标地址 '{host}' 不在允许的白名单内。"
                f"当前白名单: {[str(n) for n in self._allowlist]}。"
            )

        return True, ""

    def check_all(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """一站式网络策略检查。

        从参数中提取 url / host / endpoint 字段进行检查。

        Returns:
            None 表示通过，dict 表示拒绝原因
        """
        # 尝试多个可能的网络参数字段
        url = str(
            params.get("url") or
            params.get("host") or
            params.get("endpoint") or
            params.get("api_endpoint") or
            ""
        )

        if not url:
            return None

        allowed, reason = self.check(url)
        if not allowed:
            return {
                "ok": False,
                "error": reason,
                "denied_by": "network",
                "recoverable": True,
                "suggestion": (
                    f"当前网络策略: {self._policy.value}。"
                    f"请使用允许范围内的网络地址。"
                ),
            }

        return None


# 全局默认实例
_default_network_checker: Optional[NetworkPolicyChecker] = None


def get_network_checker() -> Optional[NetworkPolicyChecker]:
    """获取当前 NetworkPolicyChecker 实例。"""
    return _default_network_checker


def set_network_checker(checker: NetworkPolicyChecker) -> None:
    """设置全局 NetworkPolicyChecker 实例。"""
    global _default_network_checker
    _default_network_checker = checker

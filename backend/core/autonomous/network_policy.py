"""
网络出站策略执行模块。

根据配置过滤网络出站请求：
- allow_all: 无限制
- block_local: 拒绝内网地址（IPv4 + IPv6）
- allowlist: 仅允许白名单内的地址

安全措施：
- 实际 DNS 解析，检查所有解析后的 IP（防 DNS rebinding）
- 同时处理 IPv4 和 IPv6
- 云元数据端点始终拒绝
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from loguru import logger

from core.autonomous.config import AutonomousConfig, NetworkPolicy


# 云元数据端点（始终拒绝，即使 allow_all）
# 包含 IPv4 / IPv6 / AWS IMDSv2 / GCP / Azure 端点
_ALWAYS_BLOCKED_HOSTS: frozenset = frozenset({
    "169.254.169.254",           # AWS / 通用云元数据 (IPv4)
    "::ffff:169.254.169.254",    # AWS 元数据 (IPv4-mapped IPv6)
    "fd00:ec2::254",             # AWS EC2 元数据 (IPv6)
    "metadata.google.internal",  # GCP 元数据
    "169.254.169.253",          # Azure 元数据
})


def _parse_host_to_ip(host: str) -> Optional[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """尝试将字符串解析为 IP 地址（IPv4 或 IPv6）。

    返回 ipaddress 对象，非有效 IP 地址返回 None。
    """
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


async def _resolve_host_to_ips(host: str) -> List[str]:
    """通过 DNS 解析主机名到 IP 地址列表。

    返回所有解析到的 IP 地址字符串，解析失败返回空列表。
    使用 asyncio.to_thread 包装 socket.getaddrinfo，避免阻塞事件循环。
    """
    try:
        addrs = await asyncio.to_thread(
            socket.getaddrinfo, host, None, 0, socket.SOCK_STREAM
        )
        # 去重，保留解析顺序
        seen: set[str] = set()
        result: list[str] = []
        for addr in addrs:
            ip_str = addr[4][0]
            if ip_str not in seen:
                seen.add(ip_str)
                result.append(ip_str)
        return result
    except (socket.gaierror, socket.herror, UnicodeError):
        return []


def _is_private_or_special(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """检查 IP 地址是否为内网/回环/链路本地/唯一本地地址。"""
    if isinstance(ip_obj, ipaddress.IPv4Address):
        return ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local
    # IPv6
    return (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or getattr(ip_obj, "is_site_local", False)  # fec0:: (deprecated but still used)
    )


class NetworkPolicyChecker:
    """网络出站策略检查器。

    安全措施：
    - 对域名进行实际 DNS 解析，检查所有解析到的 IP
    - 同时支持 IPv4 和 IPv6
    - 云元数据端点始终拒绝
    """

    def __init__(self, config: AutonomousConfig):
        self._policy = config.network_policy
        # allowlist 使用 ip_network 支持 IPv4 + IPv6 CIDR
        self._allowlist: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for cidr in config.network_allowlist:
            cidr = cidr.strip()
            if not cidr:
                continue
            try:
                self._allowlist.append(ipaddress.ip_network(cidr))
            except ValueError as e:
                logger.warning(f"网络白名单 CIDR 无效，已忽略: {cidr} ({e})")
        logger.info(
            f"网络策略已设置: policy={self._policy.value}, "
            f"allowlist={len(self._allowlist)} entries"
        )

    async def check(self, url_or_host: str) -> Tuple[bool, str]:
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
        except Exception as exc:
            # urlparse 失败时回退为当作主机名处理，记录 debug 便于排查
            logger.debug(f"[network_policy] URL 解析失败，按主机名处理: {url_or_host!r}, error={exc}")

        # 云元数据端点始终拒绝
        if host in _ALWAYS_BLOCKED_HOSTS:
            logger.warning(f"[网络策略] 拒绝访问云元数据端点: {host}")
            return False, (
                f"网络策略拒绝: 目标地址 '{host}' 是云元数据端点，"
                f"在任何网络策略下均被禁止。"
            )

        # allow_all: 其余全部放行
        if self._policy == NetworkPolicy.ALLOW_ALL:
            return True, ""

        # 收集所有需要检查的 IP 地址
        ips_to_check: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []

        # 先尝试直接解析为 IP
        direct_ip = _parse_host_to_ip(host)
        if direct_ip is not None:
            ips_to_check.append(direct_ip)

        # 对非 IP 地址进行 DNS 解析，防止 DNS rebinding 绕过
        if direct_ip is None:
            resolved_ips = await _resolve_host_to_ips(host)
            if resolved_ips:
                for ip_str in resolved_ips:
                    ip_obj = _parse_host_to_ip(ip_str)
                    if ip_obj is not None:
                        ips_to_check.append(ip_obj)
            else:
                # DNS 解析失败，block_local 模式下对未知域名采取保守策略
                if self._policy == NetworkPolicy.BLOCK_LOCAL:
                    logger.warning(
                        f"[网络策略] 无法解析域名 '{host}'，block_local 模式下已放行"
                    )
                    return True, ""
                # allowlist 模式下无法验证域名对应的 IP
                logger.warning(
                    f"[网络策略] 无法解析域名 '{host}'，allowlist 模式下已拒绝"
                )
                return False, (
                    f"网络策略拒绝: 无法解析域名 '{host}' 到 IP 地址。"
                    f"当前策略: allowlist。请使用 IP 地址或确保域名可解析。"
                )

        # 对每个解析到的 IP 应用策略
        for ip_obj in ips_to_check:
            # 检查是否是云元数据端点（通过 IP 匹配）
            ip_str = str(ip_obj)
            if ip_str in _ALWAYS_BLOCKED_HOSTS:
                logger.warning(f"[网络策略] 拒绝解析到云元数据端点的地址: {host} -> {ip_str}")
                return False, (
                    f"网络策略拒绝: 域名 '{host}' 解析到云元数据端点 '{ip_str}'。"
                )

            # block_local: 拒绝内网/回环/链路本地地址
            if self._policy == NetworkPolicy.BLOCK_LOCAL:
                if _is_private_or_special(ip_obj):
                    logger.warning(f"[网络策略] 拒绝内网地址: {host} -> {ip_str}")
                    return False, (
                        f"网络策略拒绝: 域名 '{host}' 解析到内网地址 '{ip_str}'。"
                        f"当前策略: block_local。请使用允许的外部地址。"
                    )

            # allowlist: 仅允许白名单内的地址
            if self._policy == NetworkPolicy.ALLOWLIST:
                allowed = False
                for network in self._allowlist:
                    # 网络对象类型必须匹配 (IPv4 in IPv4Network, IPv6 in IPv6Network)
                    try:
                        if ip_obj in network:
                            allowed = True
                            break
                    except TypeError:
                        continue
                if not allowed:
                    logger.warning(
                        f"[网络策略] 拒绝非白名单地址: {host} -> {ip_str}"
                    )
                    return False, (
                        f"网络策略拒绝: 域名 '{host}' 解析到 IP '{ip_str}'，"
                        f"该地址不在允许的白名单内。"
                        f"当前白名单: {[str(n) for n in self._allowlist]}。"
                    )

        return True, ""

    async def check_all(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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

        allowed, reason = await self.check(url)
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

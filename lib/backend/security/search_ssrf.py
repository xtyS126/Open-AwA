"""
搜索 URL 的 SSRF 校验模块。
用于校验搜索 provider 配置的 base_url 是否符合安全策略，
默认拒绝私有/回环/保留地址，可通过 allow_private 开关放行（同时记录审计日志）。
"""

import ipaddress
import socket
from urllib.parse import urlparse

from loguru import logger


# 云元数据地址黑名单（AWS/Azure/GCP 公共元数据服务，存在敏感信息泄露风险）
_CLOUD_METADATA_HOSTS = frozenset({
    "169.254.169.254",
    "metadata.google.internal",
})


def _is_internal_ip(ip_obj: ipaddress._BaseAddress) -> bool:
    """判断 IP 是否属于内部/受限地址（私有、回环、保留、链路本地、组播、未指定）。"""
    return bool(
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_reserved
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_unspecified
    )


def validate_search_url(url: str, allow_private: bool = False) -> tuple[bool, str]:
    """
    校验搜索 provider URL 是否符合安全策略。

    校验规则：
      1. URL 必须可解析
      2. scheme 仅允许 http/https
      3. hostname 非空
      4. 阻止 localhost 字符串与 0.0.0.0
      5. 阻止云元数据地址（169.254.169.254 等）
      6. 默认拒绝私有/回环/保留 IP（直接字面量或域名解析结果）
      7. allow_private=True 时允许内网地址，但记录 WARNING 审计日志

    Args:
        url: 待校验的 URL 字符串
        allow_private: 是否允许内网地址（True 时允许但记录审计日志）

    Returns:
        (is_valid, error_message)
        - 校验通过: (True, "")
        - 校验失败: (False, "拒绝原因")
    """
    # 1. 解析 URL
    try:
        parsed = urlparse(url)
    except Exception as exc:
        return False, f"URL 解析失败: {exc}"

    # 2. 校验 scheme（仅 http/https）
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return False, f"仅允许 http/https 协议，当前协议: {scheme or '空'}"

    # 3. 校验 hostname 非空
    hostname = parsed.hostname
    if not hostname:
        return False, "URL 缺少主机名"

    hostname_lower = hostname.lower().rstrip(".")

    # 6. 阻止 localhost 字符串
    if hostname_lower == "localhost":
        return False, "不允许配置 localhost 地址"

    # 7. 阻止 0.0.0.0
    if hostname_lower == "0.0.0.0":
        return False, "不允许配置 0.0.0.0 地址"

    # 云元数据地址黑名单
    if hostname_lower in _CLOUD_METADATA_HOSTS:
        return False, f"不允许配置云元数据地址: {hostname}"

    # 4. 默认拒绝私有 IP/loopback/reserved（除非 allow_private=True）
    # 5. allow_private=True 时允许，但仍记录审计日志（用 loguru WARNING）
    # 优先按 IP 字面量判定，避免触发 DNS 解析
    try:
        ip_obj = ipaddress.ip_address(hostname)
        is_internal = _is_internal_ip(ip_obj)
        if is_internal:
            if not allow_private:
                return False, f"不允许配置内网地址: {ip_obj}"
            # 允许但记录审计日志
            logger.bind(
                event="search_ssrf_allow_private",
                module="security",
                action="validate_search_url",
                url=url,
                ip=str(ip_obj),
                allow_private=True,
            ).warning(f"允许配置内网地址（allow_private=True）: {ip_obj}")
        return True, ""
    except ValueError:
        # 不是 IP 字面量，是域名，继续走 DNS 解析
        pass

    # 域名解析后的 IP 校验（同步调用 socket.getaddrinfo）
    try:
        addrinfos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        return False, f"域名解析失败: {hostname} ({exc})"

    has_internal_ip = False
    internal_ip_str = ""
    for addrinfo in addrinfos:
        sockaddr = addrinfo[4]
        addr = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(addr)
            if _is_internal_ip(ip_obj):
                has_internal_ip = True
                internal_ip_str = str(ip_obj)
                break
        except ValueError:
            continue

    if has_internal_ip:
        if not allow_private:
            return False, f"域名 {hostname} 解析到内网地址: {internal_ip_str}"
        # 允许但记录审计日志
        logger.bind(
            event="search_ssrf_allow_private",
            module="security",
            action="validate_search_url",
            url=url,
            hostname=hostname,
            ip=internal_ip_str,
            allow_private=True,
        ).warning(f"域名 {hostname} 解析到内网地址（allow_private=True）: {internal_ip_str}")

    return True, ""

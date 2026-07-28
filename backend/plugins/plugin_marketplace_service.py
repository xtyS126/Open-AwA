"""插件市场来源解析服务。"""

from __future__ import annotations

import http.client
import re
import socket
import ssl
import urllib.parse
from typing import Callable, Dict, List, Optional, Tuple


class PluginMarketplaceService:
    """校验并规范化远端插件市场的包坐标。"""

    NPM_PACKAGE_PATTERN = re.compile(
        r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$"
    )
    NPM_VERSION_PATTERN = re.compile(
        r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
        r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
        r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
    )

    def __init__(
        self,
        allowed_download_domains: Optional[set[str]] = None,
        max_download_size: int = 50 * 1024 * 1024,
    ) -> None:
        self.allowed_download_domains = allowed_download_domains or set()
        self.max_download_size = max_download_size

    def validate_remote_url(
        self,
        source_url: str,
        resolve_ips: Callable[[str], List[str]],
    ) -> List[str]:
        """校验来源协议、域名白名单并固定 DNS 解析结果。"""
        parsed = urllib.parse.urlparse(source_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Invalid remote plugin URL")
        hostname = parsed.hostname or ""
        if hostname not in self.allowed_download_domains:
            raise ValueError(
                f"域名 '{hostname}' 不在允许下载的白名单中。"
                f"允许的域名: {sorted(self.allowed_download_domains)}"
            )
        return resolve_ips(hostname)

    def download_via_pinned_ip(
        self,
        source_url: str,
        resolved_ips: List[str],
        timeout: int,
    ) -> Tuple[int, Dict[str, str], bytes]:
        """从已验证 IP 下载 ZIP，避免下载阶段再次触发 DNS 解析。"""
        parsed = urllib.parse.urlparse(source_url)
        hostname = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        request_path = parsed.path or "/"
        if parsed.query:
            request_path = f"{request_path}?{parsed.query}"

        last_error: Optional[Exception] = None
        for resolved_ip in resolved_ips:
            socket_obj: Optional[socket.socket] = None
            response: Optional[http.client.HTTPResponse] = None
            try:
                raw_socket = socket.create_connection((resolved_ip, port), timeout=timeout)
                raw_socket.settimeout(timeout)
                socket_obj = raw_socket
                if parsed.scheme == "https":
                    socket_obj = ssl.create_default_context().wrap_socket(
                        raw_socket,
                        server_hostname=hostname,
                    )
                    socket_obj.settimeout(timeout)
                request_bytes = (
                    f"GET {request_path} HTTP/1.1\r\n"
                    f"Host: {hostname}\r\n"
                    "User-Agent: OpenAwAPluginManager/1.0\r\n"
                    "Accept: application/zip, application/octet-stream\r\n"
                    "Connection: close\r\n\r\n"
                ).encode("ascii")
                socket_obj.sendall(request_bytes)
                response = http.client.HTTPResponse(socket_obj)
                response.begin()
                content_length = response.getheader("Content-Length")
                if content_length is not None and int(content_length) > self.max_download_size:
                    raise ValueError(
                        f"插件包体积 ({content_length} bytes) 超过限制 ({self.max_download_size} bytes)"
                    )
                content = response.read(self.max_download_size + 1)
                if len(content) > self.max_download_size:
                    raise ValueError(
                        f"插件包体积 ({len(content)} bytes) 超过限制 ({self.max_download_size} bytes)"
                    )
                headers = {key.lower(): value for key, value in response.getheaders()}
                return response.status, headers, content
            except Exception as exc:
                last_error = exc
            finally:
                if response is not None:
                    response.close()
                if socket_obj is not None:
                    socket_obj.close()
        raise ValueError(f"远程插件下载失败: {last_error or '未知错误'}") from last_error

    def validate_remote_response(
        self,
        status_code: int,
        response_headers: Dict[str, str],
        response_content: bytes,
    ) -> None:
        """检查下载响应是否为可接受且未超限的 ZIP 内容。"""
        if status_code in (301, 302, 303, 307, 308):
            raise ValueError("远程插件下载不允许重定向，请提供直链地址")
        if status_code >= 400:
            raise ValueError(f"远程插件下载失败，HTTP 状态码: {status_code}")
        if not response_content:
            raise ValueError("Remote plugin package is empty")
        if len(response_content) > self.max_download_size:
            raise ValueError(
                f"插件包体积 ({len(response_content)} bytes) 超过限制 ({self.max_download_size} bytes)"
            )
        content_type = response_headers.get("content-type", "")
        allowed_types = {"application/zip", "application/octet-stream", "application/x-zip-compressed"}
        if content_type and not any(item in content_type for item in allowed_types):
            raise ValueError(f"不支持的内容类型: {content_type}，仅允许 ZIP 文件")

    def validate_npm_package_name(self, package_name: str) -> bool:
        """验证 NPM 包名是否符合允许的精确格式。"""
        return bool(self.NPM_PACKAGE_PATTERN.fullmatch(package_name))

    def validate_npm_version(self, version: str) -> bool:
        """验证 NPM 版本是否为固定的语义化版本。"""
        return bool(self.NPM_VERSION_PATTERN.fullmatch(version))

    def parse_npm_source(self, npm_source: str) -> Dict[str, str]:
        """解析 ``npm:包名@版本`` 并构造官方 registry 的 tarball 地址。"""
        source = npm_source.strip()
        if source.startswith("npm:"):
            source = source[4:]

        if source.startswith("@"):
            version_sep = source.rfind("@")
            if version_sep <= 0:
                raise ValueError("npm source must include package name and version")
            package_name = source[:version_sep]
            version = source[version_sep + 1:]
        else:
            if "@" not in source:
                raise ValueError("npm source must include package name and version")
            package_name, version = source.split("@", 1)

        if not package_name or not version:
            raise ValueError("npm source must include package name and version")
        if not self.validate_npm_package_name(package_name):
            raise ValueError(f"Invalid npm package name: {package_name}")
        if not self.validate_npm_version(version):
            raise ValueError(f"Invalid npm version: {version}")

        encoded_name = package_name.replace("/", "%2f")
        package_base_name = package_name.split("/")[-1]
        return {
            "source": "npm",
            "raw": npm_source,
            "package_name": package_name,
            "version": version,
            "registry": "https://registry.npmjs.org",
            "tarball_url": f"https://registry.npmjs.org/{encoded_name}/-/{package_base_name}-{version}.tgz",
        }

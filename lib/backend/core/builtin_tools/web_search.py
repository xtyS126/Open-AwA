"""
网页搜索工具 - 支持 DuckDuckGo 与 SearXNG 多 Provider 搜索。
DuckDuckGo 实现参考: duckduckgo-search (https://github.com/deedy5/duckduckgo_search)
作者: deedy5
许可: MIT License
"""

import asyncio
import contextlib
import json
import time
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

# 最大返回结果数
MAX_RESULTS = 10
# 请求超时（秒）
REQUEST_TIMEOUT = 15
# provider 配置缓存 TTL（秒），避免每次搜索都查询数据库
_CACHE_TTL_SECONDS = 10.0
# provider 配置内存缓存（结构: {"data": dict|None, "expires_at": float}）
# 使用 time.monotonic() 作为时间戳，避免系统时间回拨影响
_provider_config_cache: Dict[str, Any] = {"data": None, "expires_at": 0.0}


def _load_provider_config() -> Dict[str, Any]:
    """
    从数据库读取激活的搜索 provider 配置，带 10 秒内存缓存。

    Returns:
        包含 provider/base_url/api_key/extra_config 的字典。
        若数据库不可用或无激活配置，返回默认 duckduckgo 配置。
    """
    # 1. 检查缓存是否有效（使用 monotonic 时钟，避免系统时间回拨影响）
    now = time.monotonic()
    if _provider_config_cache["data"] is not None and now < _provider_config_cache["expires_at"]:
        return _provider_config_cache["data"]

    # 2. 默认配置（数据库不可用或无激活配置时使用）
    default_cfg: Dict[str, Any] = {
        "provider": "duckduckgo",
        "base_url": None,
        "api_key": None,
        "extra_config": {},
    }

    # 3. 查询数据库获取激活的 provider 配置
    try:
        # 延迟导入，避免模块加载阶段数据库未初始化
        from db.models import SearchProviderConfig, SessionLocal

        with contextlib.closing(SessionLocal()) as db:
            cfg = (
                db.query(SearchProviderConfig)
                .filter(SearchProviderConfig.enabled == True)  # noqa: E712
                .first()
            )
            if cfg:
                result = {
                    "provider": cfg.provider or "duckduckgo",
                    "base_url": cfg.base_url,
                    "api_key": cfg.api_key,
                    "extra_config": cfg.extra_config or {},
                }
            else:
                # 数据库无激活配置，使用默认 duckduckgo
                result = default_cfg
    except ImportError as e:
        # db.models 模块不可用时降级
        logger.warning(f"无法导入数据库模型，使用默认 duckduckgo 配置: {e}")
        result = default_cfg
    except Exception as e:
        # 数据库查询异常统一降级（可能涉及 SQLAlchemyError/OSError 等多种类型）
        # 此处为缓存兜底函数，必须保证不阻塞搜索功能
        logger.warning(f"读取搜索 provider 配置失败，使用默认 duckduckgo 配置: {e}")
        result = default_cfg

    # 4. 更新缓存
    _provider_config_cache["data"] = result
    _provider_config_cache["expires_at"] = now + _CACHE_TTL_SECONDS
    return result


class WebSearchSkill:
    """
    网页搜索技能。
    使用 DuckDuckGo HTML 搜索接口获取与用户任务相关的网页。
    """
    name: str = "web_search"
    version: str = "1.0.0"
    description: str = "搜索和用户任务相关的网页内容"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """初始化网页搜索技能。"""
        self.config = config or {}
        self.max_results = self.config.get('max_results', MAX_RESULTS)
        self._initialized = False

    async def initialize(self) -> bool:
        """初始化技能。"""
        logger.info(f"WebSearch skill initialized, max_results={self.max_results}")
        self._initialized = True
        return True

    def is_initialized(self) -> bool:
        """检查技能是否已初始化。"""
        return self._initialized

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """执行搜索任务。"""
        if not self._initialized:
            return {"success": False, "error": "技能未初始化"}

        action = kwargs.get('action', 'search')
        if action == 'search':
            return await self._search(kwargs)
        elif action == 'fetch_url':
            return await self._fetch_url(kwargs)
        else:
            return {"success": False, "error": f"未知操作: {action}"}

    async def _search(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行网页搜索。
        根据激活的 provider 配置分发到 SearXNG 或 DuckDuckGo。
        SearXNG 失败时自动降级到 DuckDuckGo。
        """
        import http.client

        query = kwargs.get('query', '').strip()
        max_results = kwargs.get('max_results', self.max_results)

        if not query:
            return {"success": False, "error": "搜索关键词不能为空"}

        # 读取激活的 provider 配置（带 10 秒内存缓存）
        cfg = _load_provider_config()
        provider = cfg.get("provider", "duckduckgo")
        base_url = cfg.get("base_url")
        extra_config = cfg.get("extra_config") or {}

        # SearXNG 路径：配置为 searxng 且提供 base_url 时尝试
        if provider == "searxng" and base_url:
            try:
                results = await asyncio.wait_for(
                    self._searxng_search(
                        query,
                        max_results,
                        base_url,
                        allow_private=bool(extra_config.get("allow_private_network", False)),
                    ),
                    timeout=REQUEST_TIMEOUT,
                )
                logger.info(
                    f"SearXNG search completed: query='{query}', results={len(results)}"
                )
                return {
                    "success": True,
                    "query": query,
                    "results": results,
                    "count": len(results),
                    "provider": "searxng",
                }
            except asyncio.TimeoutError:
                # SearXNG 超时，降级到 DuckDuckGo
                logger.warning(
                    f"SearXNG search timed out, falling back to DuckDuckGo: query='{query}'"
                )
            except (httpx.TimeoutException, httpx.HTTPError) as e:
                # SearXNG HTTP/超时异常，降级到 DuckDuckGo
                logger.warning(
                    f"SearXNG search HTTP error, falling back to DuckDuckGo: {e}"
                )
            except ValueError as e:
                # SearXNG JSON 解析或 SSRF 校验失败，降级到 DuckDuckGo
                logger.warning(
                    f"SearXNG search invalid data, falling back to DuckDuckGo: {e}"
                )
            except OSError as e:
                # SearXNG 网络异常，降级到 DuckDuckGo
                logger.warning(
                    f"SearXNG search network error, falling back to DuckDuckGo: {e}"
                )
            except Exception as e:
                # 未知异常也降级到 DuckDuckGo，确保搜索可用性
                logger.warning(
                    f"SearXNG search unknown error, falling back to DuckDuckGo: {e}"
                )
            # 降级到 DuckDuckGo 路径继续执行

        # DuckDuckGo 路径（默认 provider 或 SearXNG 降级）
        try:
            results = await self._duckduckgo_search(query, max_results)
            logger.info(
                f"DuckDuckGo search completed: query='{query}', results={len(results)}"
            )
            return {
                "success": True,
                "query": query,
                "results": results,
                "count": len(results),
                "provider": "duckduckgo",
            }
        except asyncio.TimeoutError:
            logger.warning(f"Search timed out for query: {query}")
            return {"success": False, "error": "搜索请求超时"}
        except (http.client.HTTPException, OSError) as e:
            # 网络错误：DNS 解析失败、连接被拒、SSL 握手失败等
            logger.error(f"DuckDuckGo search network error: {e}")
            return {"success": False, "error": f"搜索失败: 网络错误 - {str(e)}"}
        except ValueError as e:
            # SSRF 校验失败或 HTML 解析异常
            logger.error(f"DuckDuckGo search invalid data: {e}")
            return {"success": False, "error": f"搜索失败: {str(e)}"}
        except Exception as e:
            # 安全网：捕获未知异常，避免 Agent 崩溃
            logger.error(f"Search unexpected error: {e}")
            return {"success": False, "error": f"搜索失败: {str(e)}"}

    async def _duckduckgo_search(self, query: str, max_results: int) -> List[Dict[str, str]]:
        """
        通过 DuckDuckGo HTML 页面提取搜索结果。
        不依赖第三方搜索库，直接解析 HTML。
        """
        import http.client
        import html

        encoded_query = urllib.parse.quote_plus(query)
        url_path = f"/html/?q={encoded_query}&kl=cn-zh"

        results = []
        try:
            # _http_get 现在是异步函数，直接 await 调用
            raw_html = await asyncio.wait_for(
                self._http_get("html.duckduckgo.com", url_path),
                timeout=REQUEST_TIMEOUT
            )

            # 简单解析HTML提取搜索结果
            results = self._parse_ddg_html(raw_html, max_results)
        except asyncio.TimeoutError:
            logger.warning(f"DuckDuckGo search timed out for query: {query}")
            raise  # 重新抛出 TimeoutError，由上层 _search() 统一处理
        except (http.client.HTTPException, OSError, ValueError) as e:
            # 网络错误/SSRF 校验失败/HTML 解析异常等，原样抛出由上层处理
            logger.error(f"DuckDuckGo search error: {e}")
            raise

        return results

    async def _searxng_search(
        self,
        query: str,
        max_results: int,
        base_url: str,
        allow_private: bool = False,
    ) -> List[Dict[str, str]]:
        """
        通过 SearXNG 实例搜索。

        调用 {base_url}/search?q={query}&format=json&pageno=1，
        解析返回的 JSON results 数组，提取 title/url/content 字段。

        异常由上层 _search() 捕获后降级到 DuckDuckGo。
        """
        # 1. SSRF 校验：若 security.search_ssrf 模块可用则校验 base_url
        #    Task 9 尚未执行时模块不存在，用 ImportError 兜底跳过
        #    安全策略：默认禁止内网/回环/链路本地地址，防止已认证用户探测内网服务
        try:
            from security.search_ssrf import validate_search_url

            is_valid, err = validate_search_url(base_url, allow_private=allow_private)
            if not is_valid:
                raise ValueError(f"SearXNG base_url SSRF 校验失败: {err}")
        except ImportError:
            # security.search_ssrf 模块未找到，跳过 SSRF 校验
            logger.warning(
                "security.search_ssrf 模块未找到，跳过 SearXNG base_url SSRF 校验"
            )

        # 2. 拼接请求 URL（清理 base_url 末尾斜杠）
        search_url = base_url.rstrip('/') + '/search'
        params = {"q": query, "format": "json", "pageno": 1}

        # 3. 请求头（仅含 ISO-8859-1 字符，避免编码异常）
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; Open-AwA/1.0)',
            'Accept': 'application/json',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }

        # 4. 发送请求（httpx.AsyncClient，超时 15 秒，跟随重定向）
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(REQUEST_TIMEOUT),
            follow_redirects=True,
        ) as client:
            response = await client.get(search_url, params=params, headers=headers)
            response.raise_for_status()

            # 5. 解析 JSON
            data = response.json()
            raw_results = data.get("results", [])[:max_results]

            # 6. 转换为统一格式（title/url/snippet）
            results: List[Dict[str, str]] = []
            for r in raw_results:
                results.append({
                    "title": str(r.get("title", "") or ""),
                    "url": str(r.get("url", "") or ""),
                    "snippet": str(r.get("content", "") or ""),
                })

            return results

    async def _http_get(self, host: str, path: str) -> str:
        """异步HTTP GET请求，包含SSRF防护。"""
        import http.client
        import ssl
        import socket
        import ipaddress

        # SSRF防护: 检查主机名是否指向内部地址
        if not host or host.strip() == '':
            raise ValueError("主机名不能为空")

        blocked_hosts = ['localhost', '127.0.0.1', '0.0.0.0', '::1']
        if host.lower() in blocked_hosts:
            raise ValueError("不允许访问本地地址")

        try:
            # 在线程池中执行 DNS 解析，避免阻塞事件循环
            resolved_ips = await asyncio.to_thread(socket.getaddrinfo, host, None)
            for family, socktype, proto, canonname, sockaddr in resolved_ips:
                ip_str = sockaddr[0]
                ip_obj = ipaddress.ip_address(ip_str)
                if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_reserved:
                    raise ValueError(f"不允许访问内部地址: {host}")
        except socket.gaierror:
            raise ValueError(f"无法解析主机名: {host}")

        context = ssl.create_default_context()
        conn = http.client.HTTPSConnection(host, timeout=REQUEST_TIMEOUT, context=context)
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; Open-AwA/1.0)',
                'Accept': 'text/html',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
            }
            conn.request("GET", path, headers=headers)
            response = conn.getresponse()
            data = response.read().decode('utf-8', errors='replace')
            return data
        finally:
            conn.close()

    def _parse_ddg_html(self, html_content: str, max_results: int) -> List[Dict[str, str]]:
        """
        从DuckDuckGo HTML搜索结果中提取链接和摘要。
        使用简单字符串解析，不依赖 BeautifulSoup。
        """
        import html as html_module
        results = []

        # DuckDuckGo HTML 结果通常在 class="result" 的 div 中
        # 链接在 class="result__a" 的 a 标签中
        # 摘要在 class="result__snippet" 的 a 标签中
        search_start = 0
        while len(results) < max_results:
            # 找到结果链接
            link_marker = 'class="result__a"'
            link_pos = html_content.find(link_marker, search_start)
            if link_pos == -1:
                break

            # 提取 href
            href_start = html_content.rfind('href="', max(0, link_pos - 200), link_pos)
            if href_start == -1:
                search_start = link_pos + len(link_marker)
                continue
            href_start += len('href="')
            href_end = html_content.find('"', href_start)
            href = html_content[href_start:href_end]

            # 提取标题
            title_start = html_content.find('>', link_pos) + 1
            title_end = html_content.find('</a>', title_start)
            title = html_content[title_start:title_end] if title_end > title_start else ''
            # 清除HTML标签
            title = self._strip_html_tags(title)
            title = html_module.unescape(title).strip()

            # 提取摘要
            snippet_marker = 'class="result__snippet"'
            snippet_pos = html_content.find(snippet_marker, link_pos)
            snippet = ''
            if snippet_pos != -1 and snippet_pos - link_pos < 2000:
                snippet_start = html_content.find('>', snippet_pos) + 1
                snippet_end = html_content.find('</a>', snippet_start)
                if snippet_end == -1:
                    snippet_end = html_content.find('</span>', snippet_start)
                if snippet_end > snippet_start:
                    snippet = html_content[snippet_start:snippet_end]
                    snippet = self._strip_html_tags(snippet)
                    snippet = html_module.unescape(snippet).strip()

            # 处理 DuckDuckGo 的重定向链接
            if href.startswith('//duckduckgo.com/l/?'):
                parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                actual_url = parsed.get('uddg', [href])[0]
                href = actual_url

            if href and title:
                results.append({
                    "title": title[:200],
                    "url": href,
                    "snippet": snippet[:500]
                })

            search_start = link_pos + len(link_marker)

        return results

    def _strip_html_tags(self, text: str) -> str:
        """移除HTML标签。"""
        import re
        return re.sub(r'<[^>]+>', '', text)

    async def _fetch_url(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """获取指定URL的网页内容（纯文本），包含安全检查。"""
        url = kwargs.get('url', '').strip()
        max_length = kwargs.get('max_length', 10000)

        if not url:
            return {"success": False, "error": "URL不能为空"}

        # 仅允许 http/https 协议
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return {"success": False, "error": "仅支持 http/https 协议"}

        if not parsed.hostname:
            return {"success": False, "error": "URL格式无效"}

        try:
            loop = asyncio.get_event_loop()
            host = parsed.hostname
            path = parsed.path or '/'
            if parsed.query:
                path += '?' + parsed.query

            raw_html = await asyncio.wait_for(
                loop.run_in_executor(None, self._http_get, host, path),
                timeout=REQUEST_TIMEOUT
            )

            # 提取纯文本
            text = self._strip_html_tags(raw_html)
            # 压缩空白
            import re
            text = re.sub(r'\s+', ' ', text).strip()[:max_length]

            return {
                "success": True,
                "url": url,
                "content": text,
                "length": len(text)
            }
        except Exception as e:
            logger.error(f"Fetch URL error: {e}")
            return {"success": False, "error": f"获取网页失败: {str(e)}"}

    def get_tools(self) -> List[Dict[str, Any]]:
        """返回工具定义列表。"""
        return [
            {
                "name": "web_search",
                "description": "搜索和用户任务相关的网页",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词"
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "最大返回结果数，默认10"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "fetch_url",
                "description": "获取指定URL的网页文本内容",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "要获取的URL地址"
                        },
                        "max_length": {
                            "type": "integer",
                            "description": "最大返回内容长度，默认10000"
                        }
                    },
                    "required": ["url"]
                }
            }
        ]

    def cleanup(self):
        """清理技能资源。"""
        self._initialized = False
        logger.info(f"{self.name} skill cleaned up")

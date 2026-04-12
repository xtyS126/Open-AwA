"""
网页搜索工具 - 使用 DuckDuckGo 搜索引擎获取搜索结果。
参考来源: duckduckgo-search (https://github.com/deedy5/duckduckgo_search)
作者: deedy5
许可: MIT License
"""

import asyncio
import urllib.parse
import json
from typing import Dict, Any, List, Optional
from loguru import logger

# 最大返回结果数
MAX_RESULTS = 10
# 请求超时（秒）
REQUEST_TIMEOUT = 15


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
        使用 DuckDuckGo HTML 搜索接口，不需要 API Key。
        """
        query = kwargs.get('query', '').strip()
        max_results = kwargs.get('max_results', self.max_results)

        if not query:
            return {"success": False, "error": "搜索关键词不能为空"}

        try:
            results = await self._duckduckgo_search(query, max_results)
            logger.info(f"Web search completed: query='{query}', results={len(results)}")
            return {
                "success": True,
                "query": query,
                "results": results,
                "count": len(results)
            }
        except Exception as e:
            logger.error(f"Web search error: {e}")
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
            loop = asyncio.get_event_loop()
            raw_html = await asyncio.wait_for(
                loop.run_in_executor(None, self._http_get, "html.duckduckgo.com", url_path),
                timeout=REQUEST_TIMEOUT
            )

            # 简单解析HTML提取搜索结果
            results = self._parse_ddg_html(raw_html, max_results)
        except asyncio.TimeoutError:
            logger.warning(f"DuckDuckGo search timed out for query: {query}")
            raise Exception("搜索请求超时")
        except Exception as e:
            logger.error(f"DuckDuckGo search error: {e}")
            raise

        return results

    def _http_get(self, host: str, path: str) -> str:
        """同步HTTP GET请求。"""
        import http.client
        import ssl

        context = ssl.create_default_context()
        conn = http.client.HTTPSConnection(host, timeout=REQUEST_TIMEOUT, context=context)
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; Open-AwA/1.0)',
            'Accept': 'text/html',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
        }
        conn.request("GET", path, headers=headers)
        response = conn.getresponse()
        data = response.read().decode('utf-8', errors='replace')
        conn.close()
        return data

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
        """获取指定URL的网页内容（纯文本）。"""
        url = kwargs.get('url', '').strip()
        max_length = kwargs.get('max_length', 10000)

        if not url:
            return {"success": False, "error": "URL不能为空"}

        try:
            loop = asyncio.get_event_loop()
            parsed = urllib.parse.urlparse(url)
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

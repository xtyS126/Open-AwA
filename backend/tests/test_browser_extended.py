"""
浏览器扩展工具 (BrowserExtendedSkill) 单元测试。

测试覆盖：
- URL 安全校验（SSRF 防护、协议白名单）
- 快照文本构建（HTML → 纯文本转换）
- 浏览器扩展技能类的初始化和执行
"""
import os
import sys

import pytest

# 将 backend 目录加入 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestURLValidation:
    """测试 URL 安全校验函数 _validate_url"""

    @pytest.mark.asyncio
    async def test_valid_https_url(self):
        """有效 HTTPS URL 应通过校验"""
        from core.builtin_tools.browser_extended import _validate_url
        result = await _validate_url("https://example.com/page")
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_http_url(self):
        """有效 HTTP URL 应通过校验"""
        from core.builtin_tools.browser_extended import _validate_url
        result = await _validate_url("http://example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_block_ftp_protocol(self):
        """FTP 协议应被拦截"""
        from core.builtin_tools.browser_extended import _validate_url
        result = await _validate_url("ftp://example.com/file")
        assert result is not None
        assert "协议" in result

    @pytest.mark.asyncio
    async def test_block_file_protocol(self):
        """file:// 协议应被拦截（防止本地文件读取攻击）"""
        from core.builtin_tools.browser_extended import _validate_url
        result = await _validate_url("file:///etc/passwd")
        assert result is not None

    @pytest.mark.asyncio
    async def test_block_localhost(self):
        """127.0.0.1 应被拦截（SSRF 防护）"""
        from core.builtin_tools.browser_extended import _validate_url
        result = await _validate_url("http://127.0.0.1:8000/admin")
        assert result is not None
        assert "内网" in result

    @pytest.mark.asyncio
    async def test_block_private_ip(self):
        """192.168.x.x 内网 IP 应被拦截"""
        from core.builtin_tools.browser_extended import _validate_url
        result = await _validate_url("http://192.168.1.1/config")
        assert result is not None
        assert "内网" in result

    @pytest.mark.asyncio
    async def test_block_10_network(self):
        """10.0.0.0/8 网段应被拦截"""
        from core.builtin_tools.browser_extended import _validate_url
        result = await _validate_url("http://10.0.0.1/api")
        assert result is not None

    @pytest.mark.asyncio
    async def test_block_169_254_link_local(self):
        """169.254.x.x 链路本地地址应被拦截"""
        from core.builtin_tools.browser_extended import _validate_url
        result = await _validate_url("http://169.254.169.254/latest/meta-data")
        assert result is not None

    @pytest.mark.asyncio
    async def test_block_0_network(self):
        """0.0.0.0 应被拦截"""
        from core.builtin_tools.browser_extended import _validate_url
        result = await _validate_url("http://0.0.0.0:8080")
        assert result is not None

    @pytest.mark.asyncio
    async def test_block_172_16_network(self):
        """172.16.0.0/12 内网段应被拦截"""
        from core.builtin_tools.browser_extended import _validate_url
        result = await _validate_url("http://172.16.0.1/")
        assert result is not None

    @pytest.mark.asyncio
    async def test_invalid_url_format(self):
        """无效 URL 格式应返回错误"""
        from core.builtin_tools.browser_extended import _validate_url
        result = await _validate_url("not-a-valid-url")
        assert result is not None

    @pytest.mark.asyncio
    async def test_url_without_hostname(self):
        """缺少主机名的 URL 应返回错误"""
        from core.builtin_tools.browser_extended import _validate_url
        result = await _validate_url("http:///path")
        assert result is not None
        assert "主机名" in result


class TestIsPrivateHost:
    """测试 _is_private_host SSRF 检测函数"""

    @pytest.mark.asyncio
    async def test_localhost_ip_is_private(self):
        """127.0.0.1 应被识别为私有地址"""
        from core.builtin_tools.browser_extended import _is_private_host
        assert await _is_private_host("127.0.0.1") is True

    @pytest.mark.asyncio
    async def test_private_ip_is_private(self):
        """192.168.1.1 应被识别为私有地址"""
        from core.builtin_tools.browser_extended import _is_private_host
        assert await _is_private_host("192.168.1.1") is True

    @pytest.mark.asyncio
    async def test_ipv6_loopback_is_private(self):
        """::1 IPv6 回环应被识别为私有地址"""
        from core.builtin_tools.browser_extended import _is_private_host
        assert await _is_private_host("::1") is True

    @pytest.mark.asyncio
    async def test_public_ip_is_not_private(self):
        """公网 IP 不应被识别为私有（仅当能解析为合法 IP 时）"""
        from core.builtin_tools.browser_extended import _is_private_host
        # 8.8.8.8 是 Google DNS，公网 IP
        assert await _is_private_host("8.8.8.8") is False


class TestBuildSnapshotText:
    """测试 _build_snapshot_text 页面快照文本构建"""

    def test_strips_html_tags(self):
        """快照文本应去除 HTML 标签"""
        from core.builtin_tools.browser_extended import _build_snapshot_text

        html = "<html><head><title>Test</title></head><body><h1>Hello</h1><p>World</p></body></html>"
        text = _build_snapshot_text(html, "http://example.com")

        assert "Hello" in text
        assert "World" in text
        assert "example.com" in text
        assert "<h1>" not in text

    def test_removes_scripts(self):
        """快照文本应移除 script 标签及其内容"""
        from core.builtin_tools.browser_extended import _build_snapshot_text

        html = '<html><body><script>alert("xss")</script><p>Safe Content</p></body></html>'
        text = _build_snapshot_text(html, "http://example.com")

        assert "alert" not in text
        assert "Safe Content" in text

    def test_removes_styles(self):
        """快照文本应移除 style 标签"""
        from core.builtin_tools.browser_extended import _build_snapshot_text

        html = '<html><style>body { color: red; }</style><body><p>Content</p></body></html>'
        text = _build_snapshot_text(html, "http://example.com")

        assert "color" not in text
        assert "Content" in text

    def test_preserves_link_href(self):
        """快照文本应保留链接的 URL"""
        from core.builtin_tools.browser_extended import _build_snapshot_text

        html = '<html><body><a href="https://example.com/page">Click here</a></body></html>'
        text = _build_snapshot_text(html, "http://example.com")

        assert "Click here" in text
        assert "https://example.com/page" in text

    def test_truncates_long_content(self):
        """超长内容应被截断并显示截断提示"""
        from core.builtin_tools.browser_extended import _build_snapshot_text

        long_text = "A" * 15000
        html = f"<html><body><p>{long_text}</p></body></html>"
        text = _build_snapshot_text(html, "http://example.com")

        assert len(text) < 12000
        assert "已截断" in text

    def test_includes_page_header(self):
        """快照文本头部应包含 URL 信息"""
        from core.builtin_tools.browser_extended import _build_snapshot_text

        html = "<html><body><p>Hello</p></body></html>"
        text = _build_snapshot_text(html, "https://example.com/page")

        assert "# 页面快照" in text
        assert "URL: https://example.com/page" in text

    def test_decodes_html_entities(self):
        """HTML 实体应被解码为对应字符"""
        from core.builtin_tools.browser_extended import _build_snapshot_text

        html = "<html><body><p>Hello &amp; Welcome &lt;3</p></body></html>"
        text = _build_snapshot_text(html, "http://example.com")

        assert "Hello & Welcome <3" in text
        assert "&amp;" not in text  # HTML 实体已被解码
        assert "&lt;" not in text   # HTML 实体已被解码


class TestBrowserExtendedSkill:
    """测试 BrowserExtendedSkill 技能类"""

    @pytest.mark.asyncio
    async def test_initialize(self):
        """初始化应成功并设置 _initialized 标志"""
        from core.builtin_tools.browser_extended import BrowserExtendedSkill

        skill = BrowserExtendedSkill()
        result = await skill.initialize()
        assert result is True
        assert skill.is_initialized() is True

    @pytest.mark.asyncio
    async def test_execute_without_url(self):
        """缺少 URL 时应返回错误"""
        from core.builtin_tools.browser_extended import BrowserExtendedSkill

        skill = BrowserExtendedSkill()
        await skill.initialize()
        result = await skill.execute(action="screenshot")
        assert result["success"] is False
        assert "URL" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_screenshot_blocked_url(self):
        """截图被拦截的内网 URL 时应返回错误"""
        from core.builtin_tools.browser_extended import BrowserExtendedSkill

        skill = BrowserExtendedSkill()
        await skill.initialize()
        result = await skill.execute(action="screenshot", url="http://127.0.0.1/admin")
        assert result["success"] is False
        assert "内网" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_blocked_private_ip(self):
        """快照被拦截的内网 IP 时应返回错误"""
        from core.builtin_tools.browser_extended import BrowserExtendedSkill

        skill = BrowserExtendedSkill()
        await skill.initialize()
        result = await skill.execute(action="snapshot", url="http://192.168.1.1/")
        assert result["success"] is False
        assert "内网" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_unknown_action(self):
        """未知操作名应返回错误"""
        from core.builtin_tools.browser_extended import BrowserExtendedSkill

        skill = BrowserExtendedSkill()
        await skill.initialize()
        result = await skill.execute(action="unknown_action", url="https://example.com")
        assert result["success"] is False
        assert "未知" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_uninitialized(self):
        """未初始化时执行应返回错误"""
        from core.builtin_tools.browser_extended import BrowserExtendedSkill

        skill = BrowserExtendedSkill()
        result = await skill.execute(action="snapshot", url="https://example.com")
        assert result["success"] is False
        assert "未初始化" in result["error"]

    def test_get_tools_returns_all_actions(self):
        """get_tools 应返回三个操作的定义"""
        from core.builtin_tools.browser_extended import BrowserExtendedSkill

        skill = BrowserExtendedSkill()
        tools = skill.get_tools()

        assert len(tools) == 3
        tool_names = [t["name"] for t in tools]
        assert "screenshot" in tool_names
        assert "snapshot" in tool_names
        assert "navigate" in tool_names

    def test_name_and_version(self):
        """技能应有正确的名称和版本"""
        from core.builtin_tools.browser_extended import BrowserExtendedSkill

        skill = BrowserExtendedSkill()
        assert skill.name == "browser_extended"
        assert skill.version == "1.0.0"
        assert len(skill.description) > 0

    def test_cleanup(self):
        """cleanup 应重置 _initialized 标志"""
        from core.builtin_tools.browser_extended import BrowserExtendedSkill

        skill = BrowserExtendedSkill()
        assert skill.is_initialized() is False
        skill.cleanup()
        assert skill.is_initialized() is False

    @pytest.mark.asyncio
    async def test_execute_invalid_protocol(self):
        """非 http/https 协议应被拦截"""
        from core.builtin_tools.browser_extended import BrowserExtendedSkill

        skill = BrowserExtendedSkill()
        await skill.initialize()
        result = await skill.execute(action="snapshot", url="ftp://files.example.com/data")
        assert result["success"] is False
        assert "协议" in result["error"]


@pytest.mark.asyncio
class TestSnapshotWithPlaywright:
    """测试 _snapshot_with_playwright 函数"""

    async def test_playwright_not_installed(self):
        """Playwright 未安装时应返回错误"""
        import sys
        from unittest.mock import patch

        # 使用已导入的模块，模拟 playwright 不可用
        with patch.dict(sys.modules, {"playwright": None, "playwright.async_api": None}, clear=False):
            from core.builtin_tools.browser_extended import _snapshot_with_playwright
            result = await _snapshot_with_playwright("https://example.com")
            assert result["success"] is False
            assert "Playwright 未安装" in result["error"]

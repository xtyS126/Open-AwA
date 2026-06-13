"""
NetworkPolicyChecker 网络策略单元测试。
"""

import pytest

from core.autonomous.config import AutonomousConfig, AutonomousScope, NetworkPolicy
from core.autonomous.network_policy import NetworkPolicyChecker


class TestNetworkPolicyCheck:
    """网络策略检查测试"""

    @pytest.fixture
    def checker_allow_all(self, tmp_path):
        config = AutonomousConfig(
            autonomous_mode=True,
            scope={AutonomousScope.CHAT},
            workspace_root=str(tmp_path),
            network_policy=NetworkPolicy.ALLOW_ALL,
        )
        return NetworkPolicyChecker(config)

    @pytest.fixture
    def checker_block_local(self, tmp_path):
        config = AutonomousConfig(
            autonomous_mode=True,
            scope={AutonomousScope.CHAT},
            workspace_root=str(tmp_path),
            network_policy=NetworkPolicy.BLOCK_LOCAL,
        )
        return NetworkPolicyChecker(config)

    @pytest.fixture
    def checker_allowlist(self, tmp_path):
        config = AutonomousConfig(
            autonomous_mode=True,
            scope={AutonomousScope.CHAT},
            workspace_root=str(tmp_path),
            network_policy=NetworkPolicy.ALLOWLIST,
            network_allowlist=["8.8.8.8/32", "1.1.1.1/32"],
        )
        return NetworkPolicyChecker(config)

    @pytest.mark.asyncio
    async def test_allow_all_allows_anything(self, checker_allow_all):
        """allow_all 允许任何目标"""
        allowed, _ = await checker_allow_all.check("https://google.com")
        assert allowed is True

        allowed, _ = await checker_allow_all.check("10.0.0.1:8080")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_block_local_blocks_private(self, checker_block_local):
        """block_local 拒绝内网地址"""
        # RFC 1918 地址
        allowed, reason = await checker_block_local.check("10.0.0.1")
        assert allowed is False
        assert "内网" in reason

        allowed, reason = await checker_block_local.check("192.168.1.1")
        assert allowed is False

    @pytest.mark.asyncio
    async def test_block_local_allows_public(self, checker_block_local):
        """block_local 允许公网地址"""
        # 公网 IP 应通过
        allowed, _ = await checker_block_local.check("8.8.8.8")
        assert allowed is True
        allowed, _ = await checker_block_local.check("1.1.1.1")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_block_local_blocks_loopback(self, checker_block_local):
        """block_local 拒绝回环地址"""
        allowed, _ = await checker_block_local.check("127.0.0.1")
        assert allowed is False

    @pytest.mark.asyncio
    async def test_allowlist_allows_listed(self, checker_allowlist):
        """allowlist 允许白名单内的地址"""
        allowed, _ = await checker_allowlist.check("8.8.8.8")
        assert allowed is True

        allowed, _ = await checker_allowlist.check("1.1.1.1")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_allowlist_blocks_unlisted(self, checker_allowlist):
        """allowlist 拒绝白名单外的地址"""
        allowed, reason = await checker_allowlist.check("8.8.4.4")
        assert allowed is False
        assert "白名单" in reason

    @pytest.mark.asyncio
    async def test_cloud_metadata_always_blocked(self, checker_allow_all):
        """云元数据端点始终被拒绝（包括 allow_all）"""
        for host in ["169.254.169.254", "metadata.google.internal", "fd00:ec2::254"]:
            allowed, reason = await checker_allow_all.check(host)
            assert allowed is False, f"应拒绝 {host}"

    @pytest.mark.asyncio
    async def test_ipv6_private_address_blocked(self, checker_block_local):
        """block_local 拒绝 IPv6 内网地址"""
        # IPv6 回环地址
        allowed, _ = await checker_block_local.check("::1")
        assert allowed is False

    @pytest.mark.asyncio
    async def test_dns_resolution_bypass_prevented(self, checker_block_local):
        """域名解析为内网 IP 时被拒绝（防 DNS rebinding）"""
        # localhost 总是解析到 127.0.0.1 或 ::1
        allowed, reason = await checker_block_local.check("localhost")
        assert allowed is False
        assert "内网地址" in reason or "localhost" in reason.lower()

    @pytest.mark.asyncio
    async def test_url_parsing(self, checker_allow_all):
        """URL 自动提取主机名"""
        allowed, _ = await checker_allow_all.check("https://api.example.com/v1/chat")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_empty_target_passes(self, checker_allow_all):
        """空目标通过检查"""
        allowed, _ = await checker_allow_all.check("")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_check_all_returns_denial(self, checker_block_local):
        """check_all 返回拒绝结构"""
        result = await checker_block_local.check_all({"url": "http://10.0.0.1/api"})
        assert result is not None
        assert result["ok"] is False
        assert result["denied_by"] == "network"
        assert result["recoverable"] is True

    @pytest.mark.asyncio
    async def test_check_all_passes(self, checker_allow_all):
        """check_all 通过允许的目标"""
        result = await checker_allow_all.check_all({"url": "https://api.openai.com"})
        assert result is None

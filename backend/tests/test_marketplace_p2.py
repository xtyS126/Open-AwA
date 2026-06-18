"""
插件市场 P2 增强测试：版本管理、下载器、社区功能。
"""
import asyncio
import hashlib
import io
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from plugins.marketplace.version_manager import (
    parse_version,
    compare_versions,
    is_compatible,
    validate_version_bump,
    ParsedVersion,
    InvalidVersionError,
)
from plugins.marketplace.downloader import (
    compute_sha256,
    download_plugin_package,
    extract_plugin_package,
    DownloadError,
    DownloadChecksumError,
    DownloadSizeError,
    DownloadSecurityError,
)
from plugins.marketplace.community import (
    validate_rating_score,
    InvalidRatingError,
    CommunityError,
)


# ── 版本管理器测试 ──────────────────────────────────────────


class TestVersionParsing:
    """版本号解析测试。"""

    def test_parse_simple_version(self):
        pv = parse_version("1.2.3")
        assert pv.major == 1
        assert pv.minor == 2
        assert pv.patch == 3
        assert pv.prerelease is None
        assert not pv.is_prerelease
        assert pv.channel == "stable"

    def test_parse_prerelease_version(self):
        pv = parse_version("1.0.0-beta.1")
        assert pv.prerelease == "beta.1"
        assert pv.is_prerelease
        assert pv.channel == "beta"

    def test_parse_alpha_version(self):
        pv = parse_version("0.1.0-alpha")
        assert pv.channel == "alpha"

    def test_parse_rc_version(self):
        pv = parse_version("2.0.0-rc.1")
        assert pv.channel == "rc"

    def test_parse_dev_version(self):
        pv = parse_version("1.0.0-dev.20260618")
        assert pv.channel == "dev"

    def test_parse_with_build_metadata(self):
        pv = parse_version("1.0.0+build.123")
        assert pv.build == "build.123"
        assert not pv.is_prerelease

    def test_parse_invalid_version_raises(self):
        with pytest.raises(InvalidVersionError):
            parse_version("1.2")
        with pytest.raises(InvalidVersionError):
            parse_version("v1.2.3")
        with pytest.raises(InvalidVersionError):
            parse_version("1.2.3.4")
        with pytest.raises(InvalidVersionError):
            parse_version("")


class TestVersionComparison:
    """版本比较测试。"""

    def test_equal_versions(self):
        assert compare_versions("1.0.0", "1.0.0") == 0

    def test_major_version_difference(self):
        assert compare_versions("2.0.0", "1.0.0") == 1
        assert compare_versions("1.0.0", "2.0.0") == -1

    def test_minor_version_difference(self):
        assert compare_versions("1.2.0", "1.1.0") == 1
        assert compare_versions("1.1.0", "1.2.0") == -1

    def test_patch_version_difference(self):
        assert compare_versions("1.0.2", "1.0.1") == 1
        assert compare_versions("1.0.1", "1.0.2") == -1

    def test_prerelease_lower_than_release(self):
        assert compare_versions("1.0.0-beta", "1.0.0") == -1
        assert compare_versions("1.0.0", "1.0.0-beta") == 1

    def test_prerelease_channel_priority(self):
        # alpha < beta < rc
        assert compare_versions("1.0.0-alpha", "1.0.0-beta") == -1
        assert compare_versions("1.0.0-beta", "1.0.0-rc") == -1
        assert compare_versions("1.0.0-rc", "1.0.0-alpha") == 1

    def test_same_channel_prerelease(self):
        assert compare_versions("1.0.0-beta.1", "1.0.0-beta.2") == -1
        assert compare_versions("1.0.0-beta.2", "1.0.0-beta.1") == 1


class TestVersionCompatibility:
    """版本兼容性检查测试。"""

    def test_compatible_no_constraints(self):
        assert is_compatible("1.0.0") is True

    def test_compatible_min_platform(self):
        assert is_compatible("1.5.0", min_platform="1.0.0") is True
        assert is_compatible("0.9.0", min_platform="1.0.0") is False

    def test_compatible_max_platform(self):
        assert is_compatible("1.0.0", max_platform="2.0.0") is True
        assert is_compatible("2.5.0", max_platform="2.0.0") is False

    def test_compatible_both_constraints(self):
        assert is_compatible("1.5.0", min_platform="1.0.0", max_platform="2.0.0") is True
        assert is_compatible("0.5.0", min_platform="1.0.0", max_platform="2.0.0") is False
        assert is_compatible("2.5.0", min_platform="1.0.0", max_platform="2.0.0") is False

    def test_compatible_invalid_version(self):
        assert is_compatible("invalid") is False


class TestVersionBump:
    """版本升级校验测试。"""

    def test_valid_bump(self):
        assert validate_version_bump("1.0.0", "1.0.1") is True
        assert validate_version_bump("1.0.0", "2.0.0") is True

    def test_invalid_bump_same_version(self):
        assert validate_version_bump("1.0.0", "1.0.0") is False

    def test_invalid_bump_downgrade(self):
        assert validate_version_bump("1.2.0", "1.1.0") is False

    def test_invalid_bump_invalid_version(self):
        assert validate_version_bump("1.0.0", "invalid") is False


# ── 下载器测试 ──────────────────────────────────────────


class TestSHA256:
    """SHA256 计算测试。"""

    def test_compute_sha256(self, tmp_path):
        test_file = tmp_path / "test.txt"
        content = b"hello world"
        test_file.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert compute_sha256(test_file) == expected

    def test_compute_sha256_empty_file(self, tmp_path):
        test_file = tmp_path / "empty.txt"
        test_file.write_bytes(b"")
        expected = hashlib.sha256(b"").hexdigest()
        assert compute_sha256(test_file) == expected


class TestDownloadSecurity:
    """下载安全校验测试。"""

    @pytest.mark.asyncio
    async def test_download_invalid_scheme(self, tmp_path):
        with pytest.raises(DownloadSecurityError):
            await download_plugin_package("ftp://example.com/plugin.zip", None, tmp_path)

    @pytest.mark.asyncio
    async def test_download_missing_host(self, tmp_path):
        with pytest.raises(DownloadSecurityError):
            await download_plugin_package("https:///plugin.zip", None, tmp_path)


class TestExtractPackage:
    """插件包解压测试。"""

    def test_extract_valid_zip(self, tmp_path):
        # 创建测试 ZIP 文件
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("plugin.py", "# test plugin")
            zf.writestr("README.md", "# Test Plugin")

        target_dir = tmp_path / "extracted"
        result = extract_plugin_package(zip_path, target_dir)
        assert result == target_dir
        assert (target_dir / "plugin.py").exists()
        assert (target_dir / "README.md").exists()
        assert (target_dir / "plugin.py").read_text() == "# test plugin"

    def test_extract_path_traversal_blocked(self, tmp_path):
        # 创建包含路径穿越的 ZIP
        zip_path = tmp_path / "malicious.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("../../../etc/passwd", "malicious")

        target_dir = tmp_path / "target"
        # 路径穿越被检测后抛出 DownloadError（包装 DownloadSecurityError）
        with pytest.raises(DownloadError):
            extract_plugin_package(zip_path, target_dir)

    def test_extract_bad_zip(self, tmp_path):
        bad_file = tmp_path / "bad.zip"
        bad_file.write_bytes(b"not a zip file")
        target_dir = tmp_path / "target"
        with pytest.raises(DownloadError):
            extract_plugin_package(bad_file, target_dir)


# ── 社区功能测试 ──────────────────────────────────────────


class TestRatingValidation:
    """评分校验测试。"""

    def test_valid_scores(self):
        for score in [1, 2, 3, 4, 5]:
            validate_rating_score(score)  # 不抛异常即通过

    def test_score_too_low(self):
        with pytest.raises(InvalidRatingError):
            validate_rating_score(0)

    def test_score_too_high(self):
        with pytest.raises(InvalidRatingError):
            validate_rating_score(6)

    def test_score_not_integer(self):
        with pytest.raises(InvalidRatingError):
            validate_rating_score(3.5)  # type: ignore


class TestCommunityHelpers:
    """社区功能辅助函数测试。"""

    def test_validate_rating_score_boundary(self):
        # 边界值测试
        validate_rating_score(1)
        validate_rating_score(5)

    def test_invalid_rating_negative(self):
        with pytest.raises(InvalidRatingError):
            validate_rating_score(-1)


# ── 集成测试：API 路由加载 ──────────────────────────────────────────


class TestMarketplaceRoutes:
    """市场路由加载测试。"""

    def test_routes_loaded(self):
        from api.routes.marketplace import router
        # 验证新增端点已注册
        route_paths = [route.path for route in router.routes]
        assert "/api/marketplace/plugins/{plugin_id}/versions" in route_paths
        assert "/api/marketplace/plugins/{plugin_id}/versions/{version}" in route_paths
        assert "/api/marketplace/plugins/{plugin_id}/update-check" in route_paths
        assert "/api/marketplace/plugins/{plugin_id}/upgrade" in route_paths
        assert "/api/marketplace/plugins/{plugin_id}/rate" in route_paths
        assert "/api/marketplace/plugins/{plugin_id}/rating" in route_paths
        assert "/api/marketplace/plugins/{plugin_id}/reviews" in route_paths
        assert "/api/marketplace/reviews/{review_id}" in route_paths

    def test_route_count(self):
        from api.routes.marketplace import router
        # 原有 5 个 + 新增 8 个 = 13 个（部分路径有多个方法）
        assert len(router.routes) >= 13


# ── 数据库模型测试 ──────────────────────────────────────────


class TestMarketplaceModels:
    """市场数据模型测试。"""

    def test_plugin_version_model_exists(self):
        from db.models import PluginVersion
        assert PluginVersion.__tablename__ == "plugin_versions"

    def test_plugin_rating_model_exists(self):
        from db.models import PluginRating
        assert PluginRating.__tablename__ == "plugin_ratings"

    def test_plugin_review_model_exists(self):
        from db.models import PluginReview
        assert PluginReview.__tablename__ == "plugin_reviews"

    def test_plugin_download_log_model_exists(self):
        from db.models import PluginDownloadLog
        assert PluginDownloadLog.__tablename__ == "plugin_download_logs"

    def test_models_registered_in_metadata(self):
        from db.models import Base
        assert "plugin_versions" in Base.metadata.tables
        assert "plugin_ratings" in Base.metadata.tables
        assert "plugin_reviews" in Base.metadata.tables
        assert "plugin_download_logs" in Base.metadata.tables

"""
插件版本管理器。

提供语义化版本比较、兼容性检查、升级检测与回滚支持。
"""
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PluginVersion


# 语义化版本正则：MAJOR.MINOR.PATCH[-prerelease]
SEMVER_PATTERN = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?"
    r"(?:\+(?P<build>[0-9A-Za-z.-]+))?$"
)

# 预发布通道优先级（越小越优先发布）
PRERELEASE_PRIORITY = {"alpha": 1, "beta": 2, "rc": 3, "dev": 0}


class VersionError(Exception):
    """版本操作基础异常。"""


class InvalidVersionError(VersionError):
    """无效的版本号格式。"""


class IncompatibleVersionError(VersionError):
    """版本不兼容当前平台。"""


@dataclass(frozen=True)
class ParsedVersion:
    """解析后的语义化版本。"""
    major: int
    minor: int
    patch: int
    prerelease: Optional[str] = None
    build: Optional[str] = None

    @property
    def is_prerelease(self) -> bool:
        return self.prerelease is not None

    @property
    def channel(self) -> str:
        """推断发布通道。"""
        if not self.prerelease:
            return "stable"
        lower = self.prerelease.lower()
        for key in PRERELEASE_PRIORITY:
            if key in lower:
                return key
        return "dev"


def parse_version(version: str) -> ParsedVersion:
    """
    解析语义化版本字符串。

    Raises:
        InvalidVersionError: 版本号格式不合法
    """
    match = SEMVER_PATTERN.match(version.strip())
    if not match:
        raise InvalidVersionError(f"无效的版本号格式: {version}")
    return ParsedVersion(
        major=int(match.group("major")),
        minor=int(match.group("minor")),
        patch=int(match.group("patch")),
        prerelease=match.group("prerelease"),
        build=match.group("build"),
    )


def compare_versions(v1: str, v2: str) -> int:
    """
    比较两个语义化版本。

    Returns:
        -1 if v1 < v2, 0 if v1 == v2, 1 if v1 > v2
    """
    pv1 = parse_version(v1)
    pv2 = parse_version(v2)

    # 主.次.修 数字比较
    for a, b in [(pv1.major, pv2.major), (pv1.minor, pv2.minor), (pv1.patch, pv2.patch)]:
        if a < b:
            return -1
        if a > b:
            return 1

    # 预发布版本低于正式版本
    if pv1.prerelease and not pv2.prerelease:
        return -1
    if not pv1.prerelease and pv2.prerelease:
        return 1
    if pv1.prerelease and pv2.prerelease:
        # 按通道优先级比较
        ch1 = PRERELEASE_PRIORITY.get(pv1.channel, 0)
        ch2 = PRERELEASE_PRIORITY.get(pv2.channel, 0)
        if ch1 < ch2:
            return -1
        if ch1 > ch2:
            return 1
        # 同通道按字符串比较
        if pv1.prerelease < pv2.prerelease:
            return -1
        if pv1.prerelease > pv2.prerelease:
            return 1

    return 0


def is_compatible(
    version: str,
    min_platform: Optional[str] = None,
    max_platform: Optional[str] = None,
) -> bool:
    """
    检查插件版本是否兼容当前平台版本。

    Args:
        version: 插件版本
        min_platform: 平台最低版本要求
        max_platform: 平台最高版本限制
    """
    try:
        pv = parse_version(version)
    except InvalidVersionError:
        return False

    if min_platform:
        try:
            min_pv = parse_version(min_platform)
            if (pv.major, pv.minor, pv.patch) < (min_pv.major, min_pv.minor, min_pv.patch):
                return False
        except InvalidVersionError:
            pass

    if max_platform:
        try:
            max_pv = parse_version(max_platform)
            if (pv.major, pv.minor, pv.patch) > (max_pv.major, max_pv.minor, max_pv.patch):
                return False
        except InvalidVersionError:
            pass

    return True


async def list_versions(
    db: AsyncSession,
    plugin_id: str,
    include_unpublished: bool = False,
) -> List[PluginVersion]:
    """列出插件的所有版本，按发布时间倒序。"""
    stmt = select(PluginVersion).where(PluginVersion.plugin_id == plugin_id)
    if not include_unpublished:
        stmt = stmt.where(PluginVersion.is_published == True)  # noqa: E712
    stmt = stmt.order_by(PluginVersion.published_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_latest_version(
    db: AsyncSession,
    plugin_id: str,
    channel: str = "stable",
) -> Optional[PluginVersion]:
    """
    获取插件的最新版本。

    Args:
        db: 数据库会话
        plugin_id: 插件 ID
        channel: 发布通道（stable/beta/dev），stable 仅返回正式版本
    """
    versions = await list_versions(db, plugin_id, include_unpublished=False)
    if not versions:
        return None

    # 按通道过滤
    if channel == "stable":
        candidates = [v for v in versions if not parse_version(v.version).is_prerelease]
    else:
        candidates = [v for v in versions if parse_version(v.version).channel == channel]

    if not candidates:
        return None

    # 按版本号排序取最新（使用元组键避免 ParsedVersion 不可比较的问题）
    candidates.sort(
        key=lambda v: parse_version(v.version).major,
        reverse=True,
    )
    # 多次排序保证主.次.修 依次降序
    for attr in ("minor", "patch"):
        candidates.sort(
            key=lambda v: getattr(parse_version(v.version), attr),
            reverse=True,
        )
    # 预发布版本排在正式版本之后
    candidates.sort(
        key=lambda v: 0 if parse_version(v.version).is_prerelease else 1,
        reverse=True,
    )
    return candidates[0]


async def check_for_update(
    db: AsyncSession,
    plugin_id: str,
    current_version: str,
    channel: str = "stable",
) -> Tuple[bool, Optional[PluginVersion]]:
    """
    检查插件是否有可用更新。

    Returns:
        (是否有更新, 最新版本对象)
    """
    latest = await get_latest_version(db, plugin_id, channel)
    if not latest:
        return False, None
    has_update = compare_versions(latest.version, current_version) > 0
    return has_update, latest


async def get_version_detail(
    db: AsyncSession,
    plugin_id: str,
    version: str,
) -> Optional[PluginVersion]:
    """获取指定版本的详情。"""
    stmt = select(PluginVersion).where(
        PluginVersion.plugin_id == plugin_id,
        PluginVersion.version == version,
    )
    result = await db.execute(stmt)
    return result.scalars().first()


def validate_version_bump(old_version: str, new_version: str) -> bool:
    """
    校验版本号是否为有效的升级（新版本必须大于旧版本）。
    """
    try:
        return compare_versions(new_version, old_version) > 0
    except InvalidVersionError:
        return False


def format_changelog(version: str, changes: List[str]) -> str:
    """格式化版本变更日志。"""
    if not changes:
        return f"## {version}\n\n无变更说明"
    lines = [f"## {version}", ""]
    for change in changes:
        lines.append(f"- {change}")
    return "\n".join(lines)

"""
插件 bundle 格式检测器。

OpenClaw 自动检测并映射多种兼容 bundle 格式（不验证 openclaw.plugin.json schema）：
- OpenClaw bundle: openclaw.plugin.json
- Codex bundle: .codex-plugin/plugin.json
- Claude bundle: .claude-plugin/plugin.json
- Cursor bundle: .cursor-plugin/plugin.json

本模块负责扫描插件目录，识别其所属的 bundle 格式，并路由到对应的解析器。
目前 OpenClaw/Codex/Claude/Cursor 四种格式的 manifest 结构相似（均含 id/name/version 等字段），
统一通过 OpenClawAdapter 进行适配；若未来需要差异化处理，可在 BundleFormat 枚举上扩展。

参考: https://docs.openclaw.ai/plugins/manifest
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from .openclaw_adapter import (
    AdaptedManifest,
    OpenClawAdapter,
    OpenClawManifest,
    OpenClawManifestError,
)


# ---------------------------------------------------------------------------
# Bundle 格式枚举
# ---------------------------------------------------------------------------

class BundleFormat(str, Enum):
    """
    支持的插件 bundle 格式。

    每种格式对应一个 manifest 文件路径约定。
    """
    OPENCLAW = "openclaw"  # openclaw.plugin.json
    CODEX = "codex"        # .codex-plugin/plugin.json
    CLAUDE = "claude"      # .claude-plugin/plugin.json
    CURSOR = "cursor"      # .cursor-plugin/plugin.json
    OPENAWA = "openawa"    # Open-AwA 原生 manifest.json（向后兼容）


# 各 bundle 格式的 manifest 文件路径（相对插件根目录）
BUNDLE_MANIFEST_PATHS: Dict[BundleFormat, str] = {
    BundleFormat.OPENCLAW: "openclaw.plugin.json",
    BundleFormat.CODEX: ".codex-plugin/plugin.json",
    BundleFormat.CLAUDE: ".claude-plugin/plugin.json",
    BundleFormat.CURSOR: ".cursor-plugin/plugin.json",
    BundleFormat.OPENAWA: "manifest.json",
}


# ---------------------------------------------------------------------------
# 检测结果
# ---------------------------------------------------------------------------

@dataclass
class BundleDetectionResult:
    """
    bundle 格式检测结果。

    format 为 None 表示未识别到任何已知 bundle 格式。
    """
    format: Optional[BundleFormat]
    manifest_path: Optional[Path]
    plugin_dir: Path

    @property
    def detected(self) -> bool:
        """是否检测到已知 bundle 格式。"""
        return self.format is not None and self.manifest_path is not None


# ---------------------------------------------------------------------------
# 检测器
# ---------------------------------------------------------------------------

class BundleDetector:
    """
    插件 bundle 格式检测器。

    用法:
        detector = BundleDetector()
        result = detector.detect(Path("/path/to/plugin"))
        if result.detected:
            adapter = BundleManifestAdapter()
            manifest = adapter.adapt(result)
    """

    def detect(self, plugin_dir: Path) -> BundleDetectionResult:
        """
        检测插件目录的 bundle 格式。

        按优先级顺序检查各格式的 manifest 文件：
        1. Open-AwA 原生 manifest.json（最高优先级，避免误适配原生插件）
        2. OpenClaw openclaw.plugin.json
        3. Codex .codex-plugin/plugin.json
        4. Claude .claude-plugin/plugin.json
        5. Cursor .cursor-plugin/plugin.json

        Args:
            plugin_dir: 插件根目录。

        Returns:
            BundleDetectionResult 实例。
        """
        if not plugin_dir.is_dir():
            return BundleDetectionResult(
                format=None,
                manifest_path=None,
                plugin_dir=plugin_dir,
            )

        # 按优先级检查（Open-AwA 原生优先，避免误适配）
        check_order = [
            BundleFormat.OPENAWA,
            BundleFormat.OPENCLAW,
            BundleFormat.CODEX,
            BundleFormat.CLAUDE,
            BundleFormat.CURSOR,
        ]

        for fmt in check_order:
            manifest_rel = BUNDLE_MANIFEST_PATHS[fmt]
            manifest_path = plugin_dir / manifest_rel
            if manifest_path.exists() and manifest_path.is_file():
                logger.debug(f"检测到 {fmt.value} bundle 格式: {manifest_path}")
                return BundleDetectionResult(
                    format=fmt,
                    manifest_path=manifest_path,
                    plugin_dir=plugin_dir,
                )

        return BundleDetectionResult(
            format=None,
            manifest_path=None,
            plugin_dir=plugin_dir,
        )


# ---------------------------------------------------------------------------
# 统一适配器
# ---------------------------------------------------------------------------

class BundleManifestAdapter:
    """
    统一的 bundle manifest 适配器。

    根据 BundleDetectionResult 的格式类型，将 manifest 转换为 Open-AwA 内部格式。
    目前 OpenClaw/Codex/Claude/Cursor 四种格式结构相似，统一走 OpenClawAdapter；
    Open-AwA 原生格式直接返回字典（已在内部格式中）。
    """

    def __init__(self) -> None:
        """初始化 bundle 适配器：复用 OpenClawAdapter 处理兼容格式。"""
        self._openclaw_adapter = OpenClawAdapter()

    def adapt(self, detection: BundleDetectionResult) -> Optional[AdaptedManifest]:
        """
        根据检测结果适配 manifest。

        Args:
            detection: BundleDetector.detect() 的返回值。

        Returns:
            AdaptedManifest 实例；若格式未识别或适配失败则返回 None。
            对于 Open-AwA 原生格式，返回的 AdaptedManifest 中 executable=True。
        """
        if not detection.detected or detection.manifest_path is None:
            return None

        fmt = detection.format
        assert fmt is not None  # detected=True 时 format 必非 None

        if fmt == BundleFormat.OPENAWA:
            return self._adapt_openawa_native(detection.manifest_path)

        # OpenClaw/Codex/Claude/Cursor 统一走 OpenClaw 适配器
        # 这些格式的 manifest 结构与 OpenClaw 兼容（id/name/version/contracts 等字段）
        return self._adapt_compatible_bundle(detection.manifest_path, fmt)

    def _adapt_openawa_native(self, manifest_path: Path) -> Optional[AdaptedManifest]:
        """
        适配 Open-AwA 原生 manifest.json。

        原生格式已经是内部格式，直接解析并包装为 AdaptedManifest。
        """
        try:
            data = self._load_json(manifest_path)
        except BundleLoadError as e:
            logger.error(f"加载 Open-AwA 原生 manifest 失败: {manifest_path} — {e}")
            return None

        if not isinstance(data, dict):
            logger.error(f"Open-AwA 原生 manifest 顶层不是对象: {manifest_path}")
            return None

        name = data.get("name")
        version = data.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            logger.error(f"Open-AwA 原生 manifest 缺少 name/version: {manifest_path}")
            return None

        return AdaptedManifest(
            name=name,
            version=version,
            plugin_api_version=data.get("pluginApiVersion", "1.0.0"),
            description=data.get("description", ""),
            author=data.get("author", "unknown"),
            extensions=data.get("extensions", []),
            permissions=data.get("permissions", []),
            auto_authorize_permissions=data.get("auto_authorize_permissions", False),
            executable=True,  # 原生插件可执行
        )

    def _adapt_compatible_bundle(
        self,
        manifest_path: Path,
        fmt: BundleFormat,
    ) -> Optional[AdaptedManifest]:
        """
        适配 OpenClaw 兼容 bundle（OpenClaw/Codex/Claude/Cursor）。

        这些格式的 manifest 结构相似，统一通过 OpenClawAdapter 解析。
        若 manifest 缺少 OpenClaw 必填字段（如 id），会尝试用文件名或目录名作为 id。
        """
        try:
            data = self._load_json(manifest_path)
        except BundleLoadError as e:
            logger.error(f"加载 {fmt.value} bundle manifest 失败: {manifest_path} — {e}")
            return None

        if not isinstance(data, dict):
            logger.error(f"{fmt.value} bundle manifest 顶层不是对象: {manifest_path}")
            return None

        # 兼容处理：部分 bundle 格式可能用 "name" 而非 "id" 作为唯一标识
        # OpenClawAdapter 要求 id 字段，这里做兼容补全
        if "id" not in data:
            # 尝试用 name 或目录名作为 id
            fallback_id = data.get("name") or manifest_path.parent.name
            if isinstance(fallback_id, str) and fallback_id.strip():
                data = {**data, "id": fallback_id}
                logger.debug(
                    f"{fmt.value} bundle 缺少 'id' 字段，使用 '{fallback_id}' 作为 id: {manifest_path}"
                )
            else:
                logger.error(f"{fmt.value} bundle 缺少 'id' 且无法推断: {manifest_path}")
                return None

        try:
            manifest = self._openclaw_adapter.parse_manifest_dict(data)
            adapted = self._openclaw_adapter.adapt(manifest)
            # 标记 bundle 来源格式
            adapted.openclaw_raw["_bundle_format"] = fmt.value
            return adapted
        except OpenClawManifestError as e:
            logger.error(f"{fmt.value} bundle 适配失败: {manifest_path} — {e}")
            return None

    @staticmethod
    def _load_json(path: Path) -> Any:
        """
        加载 JSON 文件。

        Raises:
            BundleLoadError: 文件读取或 JSON 解析失败。
        """
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise BundleLoadError(f"读取文件失败: {path} — {e}") from e

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise BundleLoadError(f"JSON 解析失败: {path} — {e}") from e


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------

class BundleLoadError(Exception):
    """bundle manifest 加载失败时抛出。"""

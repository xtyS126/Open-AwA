"""
OpenClaw 插件 manifest 适配器。

将 OpenClaw 的 openclaw.plugin.json 格式转换为 Open-AwA 内部 manifest 格式，
使 PluginManager 能够识别并加载 OpenClaw 风格的插件。

OpenClaw manifest 核心字段（参考 https://docs.openclaw.ai/plugins/manifest）：
- id: 插件唯一标识（必填）
- configSchema: 插件配置的 JSON Schema（必填）
- name/description/version: 元数据
- providers/channels/cliBackends: 声明拥有的 provider/channel/backend id
- contracts: 静态能力所有权快照（tools/embeddings/speech 等）
- toolMetadata: contracts.tools 中工具的可用性元数据（如 optional: true）
- skills: 要加载的 skill 目录（相对插件根）
- requiresPlugins: 依赖的其他插件 id
- kind: 声明独占插件类型（memory/context-engine）

转换策略：
- id → name（内部 manifest 用 name 作为插件名）
- version → version
- description → description
- contracts.tools → extensions 中 point=tool 的扩展点
- configSchema → 扩展点 config
- requiresPlugins → dependencies
- 保留原始 manifest 到 _openclaw_raw 字段以便回溯

注意：OpenClaw 插件入口是 TypeScript ESM 代码（通过 package.json 的 openclaw.extensions 声明），
Open-AwA 作为 Python 后端无法直接执行其代码。本适配器仅做 manifest 解析与元数据提取，
使插件能在 Open-AwA 中被"发现、展示、配置"，实际执行需通过外部进程或桥接机制。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# OpenClaw manifest 文件名
OPENCLAW_MANIFEST_FILENAME = "openclaw.plugin.json"

# OpenClaw contracts 中支持的能力键
OPENCLAW_CONTRACT_KEYS = (
    "tools",
    "embeddings",
    "speech",
    "media-understanding",
    "image-generation",
    "video-generation",
    "music-generation",
    "web-fetch",
    "web-search",
)

# OpenClaw kind 字段合法值
OPENCLAW_KIND_VALUES = ("memory", "context-engine")

# 内部 manifest 的 pluginApiVersion 默认值（OpenClaw 插件未声明此字段，使用占位）
DEFAULT_PLUGIN_API_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class OpenClawManifest:
    """
    OpenClaw 插件 manifest 的解析结果。

    仅保留 Open-AwA 关心的字段，其余字段可通过 raw 访问。
    """
    id: str
    name: str
    version: str
    description: str = ""
    config_schema: Dict[str, Any] = field(default_factory=dict)
    contracts: Dict[str, Any] = field(default_factory=dict)
    tool_metadata: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    skills: List[str] = field(default_factory=list)
    requires_plugins: List[str] = field(default_factory=list)
    providers: List[str] = field(default_factory=list)
    channels: List[str] = field(default_factory=list)
    kind: Optional[str] = None
    enabled_by_default: bool = False
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AdaptedManifest:
    """
    适配后的 Open-AwA 内部 manifest 格式。

    符合 backend/plugins/schema_validator.py 中 MANIFEST_SCHEMA 的结构。
    """
    name: str
    version: str
    plugin_api_version: str
    description: str
    author: str
    extensions: List[Dict[str, Any]] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    auto_authorize_permissions: bool = False
    # OpenClaw 专有元数据（供 PluginManager 决策使用）
    openclaw_id: Optional[str] = None
    openclaw_kind: Optional[str] = None
    openclaw_providers: List[str] = field(default_factory=list)
    openclaw_channels: List[str] = field(default_factory=list)
    openclaw_skills: List[str] = field(default_factory=list)
    openclaw_raw: Dict[str, Any] = field(default_factory=dict)
    # 是否仅可发现不可执行（OpenClaw TS 代码无法在 Python 进程内执行）
    executable: bool = False

    def to_manifest_dict(self) -> Dict[str, Any]:
        """
        转换为符合 MANIFEST_SCHEMA 的字典。

        注意：openclaw_* 和 executable 字段不在 MANIFEST_SCHEMA 中，
        调用方若需严格校验应使用 to_manifest_dict_strict()。
        """
        return {
            "name": self.name,
            "version": self.version,
            "pluginApiVersion": self.plugin_api_version,
            "description": self.description,
            "author": self.author,
            "extensions": self.extensions,
            "permissions": self.permissions,
            "auto_authorize_permissions": self.auto_authorize_permissions,
            # 扩展字段（schema_validator 的 additionalProperties=False 会拒绝这些，
            # 因此 PluginManager 在校验前应先剥离这些字段）
            "_openclaw_id": self.openclaw_id,
            "_openclaw_kind": self.openclaw_kind,
            "_openclaw_providers": self.openclaw_providers,
            "_openclaw_channels": self.openclaw_channels,
            "_openclaw_skills": self.openclaw_skills,
            "_openclaw_raw": self.openclaw_raw,
            "_executable": self.executable,
        }

    def to_manifest_dict_strict(self) -> Dict[str, Any]:
        """返回严格符合 MANIFEST_SCHEMA 的字典（剥离扩展字段）。"""
        return {
            "name": self.name,
            "version": self.version,
            "pluginApiVersion": self.plugin_api_version,
            "description": self.description,
            "author": self.author,
            "extensions": self.extensions,
            "permissions": self.permissions,
            "auto_authorize_permissions": self.auto_authorize_permissions,
        }


# ---------------------------------------------------------------------------
# 解析异常
# ---------------------------------------------------------------------------

class OpenClawManifestError(Exception):
    """OpenClaw manifest 解析或校验失败时抛出。"""


# ---------------------------------------------------------------------------
# 适配器
# ---------------------------------------------------------------------------

class OpenClawAdapter:
    """
    OpenClaw 插件 manifest 适配器。

    用法:
        adapter = OpenClawAdapter()
        manifest = adapter.parse_manifest_file(Path("/path/to/openclaw.plugin.json"))
        adapted = adapter.adapt(manifest)
        internal_dict = adapted.to_manifest_dict_strict()
    """

    def parse_manifest_file(self, manifest_path: Path) -> OpenClawManifest:
        """
        从文件解析 OpenClaw manifest。

        Args:
            manifest_path: openclaw.plugin.json 文件路径。

        Raises:
            OpenClawManifestError: 文件不存在、JSON 解析失败或必填字段缺失。

        Returns:
            OpenClawManifest 实例。
        """
        if not manifest_path.exists() or not manifest_path.is_file():
            raise OpenClawManifestError(f"manifest 文件不存在: {manifest_path}")

        try:
            content = manifest_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise OpenClawManifestError(f"读取 manifest 失败: {manifest_path} — {e}") from e

        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise OpenClawManifestError(f"manifest JSON 解析失败: {manifest_path} — {e}") from e

        return self.parse_manifest_dict(data)

    def parse_manifest_dict(self, data: Dict[str, Any]) -> OpenClawManifest:
        """
        从字典解析 OpenClaw manifest。

        Args:
            data: manifest 的字典表示。

        Raises:
            OpenClawManifestError: 必填字段缺失或类型错误。

        Returns:
            OpenClawManifest 实例。
        """
        if not isinstance(data, dict):
            raise OpenClawManifestError("manifest 顶层必须是 JSON 对象")

        # 必填字段校验
        plugin_id = data.get("id")
        if not isinstance(plugin_id, str) or not plugin_id.strip():
            raise OpenClawManifestError("manifest 缺少必填字段 'id' 或类型非字符串")

        config_schema = data.get("configSchema")
        if config_schema is None:
            # configSchema 在 OpenClaw 规范中是必填，但允许空对象
            config_schema = {}
        if not isinstance(config_schema, dict):
            raise OpenClawManifestError("'configSchema' 必须是 JSON 对象")

        # 可选字段提取（带类型保护）
        name = data.get("name") or plugin_id
        if not isinstance(name, str):
            name = plugin_id

        version = data.get("version", "1.0.0")
        if not isinstance(version, str):
            version = "1.0.0"

        description = data.get("description", "")
        if not isinstance(description, str):
            description = ""

        contracts = data.get("contracts", {})
        if not isinstance(contracts, dict):
            contracts = {}

        tool_metadata = data.get("toolMetadata", {})
        if not isinstance(tool_metadata, dict):
            tool_metadata = {}

        skills = data.get("skills", [])
        if not isinstance(skills, list):
            skills = []

        requires_plugins = data.get("requiresPlugins", [])
        if not isinstance(requires_plugins, list):
            requires_plugins = []

        providers = data.get("providers", [])
        if not isinstance(providers, list):
            providers = []

        channels = data.get("channels", [])
        if not isinstance(channels, list):
            channels = []

        kind = data.get("kind")
        if kind is not None and kind not in OPENCLAW_KIND_VALUES:
            logger.warning(
                f"OpenClaw manifest 中 kind 值 '{kind}' 不合法，"
                f"合法值: {OPENCLAW_KIND_VALUES}，已忽略"
            )
            kind = None

        enabled_by_default = data.get("enabledByDefault", False)
        if not isinstance(enabled_by_default, bool):
            enabled_by_default = False

        return OpenClawManifest(
            id=plugin_id.strip(),
            name=name.strip(),
            version=version.strip(),
            description=description,
            config_schema=config_schema,
            contracts=contracts,
            tool_metadata=tool_metadata,
            skills=[str(s) for s in skills],
            requires_plugins=[str(p) for p in requires_plugins],
            providers=[str(p) for p in providers],
            channels=[str(c) for c in channels],
            kind=kind,
            enabled_by_default=enabled_by_default,
            raw=data,
        )

    def adapt(self, manifest: OpenClawManifest) -> AdaptedManifest:
        """
        将 OpenClaw manifest 转换为 Open-AwA 内部 manifest 格式。

        转换规则：
        - id → name（若 name 缺失）
        - version → version
        - contracts.tools 中每个工具 → extensions 中 point=tool 的扩展点
        - configSchema → 每个 tool 扩展点的 config
        - requiresPlugins → permissions（以 "plugin:require:<id>" 形式）
        - providers/channels → openclaw_providers/openclaw_channels 元数据
        - executable 标记为 False（TS 代码无法在 Python 进程内执行）

        Args:
            manifest: 解析后的 OpenClawManifest。

        Returns:
            AdaptedManifest 实例。
        """
        extensions = self._build_extensions(manifest)
        permissions = self._build_permissions(manifest)

        return AdaptedManifest(
            name=manifest.name,
            version=manifest.version,
            plugin_api_version=DEFAULT_PLUGIN_API_VERSION,
            description=manifest.description or f"OpenClaw plugin: {manifest.id}",
            author="openclaw",
            extensions=extensions,
            permissions=permissions,
            auto_authorize_permissions=False,
            openclaw_id=manifest.id,
            openclaw_kind=manifest.kind,
            openclaw_providers=manifest.providers,
            openclaw_channels=manifest.channels,
            openclaw_skills=manifest.skills,
            openclaw_raw=manifest.raw,
            executable=False,
        )

    def _build_extensions(self, manifest: OpenClawManifest) -> List[Dict[str, Any]]:
        """
        从 contracts.tools 构建 tool 扩展点列表。

        OpenClaw 的 contracts.tools 是工具名列表，如:
            "contracts": { "tools": ["image_generate", "image_edit"] }

        转换为 Open-AwA 扩展点:
            {
                "point": "tool",
                "name": "image_generate",
                "version": "<manifest.version>",
                "config": {
                    "optional": false,
                    "config_schema": <manifest.config_schema>,
                    "tool_metadata": <manifest.tool_metadata.get(name, {})>
                }
            }
        """
        extensions: List[Dict[str, Any]] = []

        contracts = manifest.contracts
        tools = contracts.get("tools", [])
        if not isinstance(tools, list):
            logger.warning(f"OpenClaw manifest contracts.tools 不是列表，跳过工具扩展点构建")
            return extensions

        for tool_name in tools:
            if not isinstance(tool_name, str) or not tool_name.strip():
                continue

            tool_meta = manifest.tool_metadata.get(tool_name, {})
            if not isinstance(tool_meta, dict):
                tool_meta = {}

            optional = bool(tool_meta.get("optional", False))

            extensions.append({
                "point": "tool",
                "name": tool_name.strip(),
                "version": manifest.version,
                "config": {
                    "optional": optional,
                    "config_schema": manifest.config_schema,
                    "tool_metadata": tool_meta,
                    "openclaw_source": manifest.id,
                },
            })

        # 若 contracts 中无 tools 但有其他能力键，注册一个 data_provider 扩展点作为占位
        # 这样插件至少能在 Open-AwA 中被发现和展示
        if not extensions:
            other_contracts = {
                k: v for k, v in contracts.items()
                if k in OPENCLAW_CONTRACT_KEYS and k != "tools"
            }
            if other_contracts:
                extensions.append({
                    "point": "data_provider",
                    "name": f"{manifest.id}-capabilities",
                    "version": manifest.version,
                    "config": {
                        "capabilities": other_contracts,
                        "openclaw_source": manifest.id,
                    },
                })

        # 若仍无扩展点，注册一个占位 event_handler 以满足 MANIFEST_SCHEMA 的 minItems: 1
        if not extensions:
            extensions.append({
                "point": "event_handler",
                "name": f"{manifest.id}-lifecycle",
                "version": manifest.version,
                "config": {
                    "openclaw_source": manifest.id,
                    "note": "OpenClaw 插件，能力通过 TypeScript 代码注册，需外部执行环境",
                },
            })

        return extensions

    def _build_permissions(self, manifest: OpenClawManifest) -> List[str]:
        """
        从 requiresPlugins 构建权限列表。

        转换为 "plugin:require:<id>" 形式的权限声明，
        供 PluginManager 在授权阶段处理插件间依赖。
        """
        permissions: List[str] = []
        for required_id in manifest.requires_plugins:
            if isinstance(required_id, str) and required_id.strip():
                permissions.append(f"plugin:require:{required_id.strip()}")
        return permissions

    def detect_and_adapt(self, plugin_dir: Path) -> Optional[AdaptedManifest]:
        """
        检测目录中是否存在 OpenClaw manifest，若存在则解析并适配。

        Args:
            plugin_dir: 插件根目录。

        Returns:
            AdaptedManifest 实例；若目录中无 OpenClaw manifest 则返回 None。

        Raises:
            OpenClawManifestError: manifest 存在但解析或适配失败时抛出，
                由调用方显式处理，不静默跳过发现。
        """
        manifest_path = plugin_dir / OPENCLAW_MANIFEST_FILENAME
        if not manifest_path.exists():
            return None

        manifest = self.parse_manifest_file(manifest_path)
        return self.adapt(manifest)

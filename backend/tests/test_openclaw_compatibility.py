"""
OpenClaw 兼容适配测试模块。

覆盖三个核心适配场景：
1. SkillMarkdownLoader 解析 OpenClaw gating 字段（metadata.openclaw）
2. OpenClawAdapter 将 openclaw.plugin.json 转换为内部 manifest 格式
3. BundleDetector 识别 OpenClaw/Codex/Claude/Cursor 四种 bundle 格式
4. PluginManager 集成 bundle 检测，发现并标记不可执行的 bundle 插件
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest

from plugins.bundle_detector import (
    BUNDLE_MANIFEST_PATHS,
    BundleDetector,
    BundleFormat,
    BundleManifestAdapter,
)
from plugins.openclaw_adapter import (
    AdaptedManifest,
    OpenClawAdapter,
    OpenClawManifest,
    OpenClawManifestError,
)
from skills.skill_md_loader import (
    SkillMarkdownLoader,
    SkillMetadata,
    SkillOpenClawGating,
)


# ---------------------------------------------------------------------------
# SkillMarkdownLoader OpenClaw gating 解析测试
# ---------------------------------------------------------------------------

class TestSkillOpenClawGating:
    """验证 SkillOpenClawGating 从 metadata 字段的解析行为。"""

    def test_from_metadata_returns_empty_when_none(self) -> None:
        """metadata 为 None 时应返回空 gating 实例。"""
        gating = SkillOpenClawGating.from_metadata(None)
        assert gating.has_requirements is False
        assert gating.required_bins == []

    def test_from_metadata_returns_empty_when_not_dict(self) -> None:
        """metadata 不是字典时应返回空 gating 实例。"""
        gating = SkillOpenClawGating.from_metadata("not a dict")
        assert gating.has_requirements is False

    def test_from_metadata_returns_empty_when_no_openclaw_key(self) -> None:
        """metadata 不含 openclaw 键时应返回空 gating 实例。"""
        gating = SkillOpenClawGating.from_metadata({"author": "someone"})
        assert gating.has_requirements is False

    def test_from_metadata_parses_full_gating(self) -> None:
        """完整解析 metadata.openclaw 中的 requires 字段。"""
        metadata = {
            "openclaw": {
                "requires": {
                    "bins": ["uv", "node"],
                    "anyBins": ["python3", "python"],
                    "env": ["GEMINI_API_KEY"],
                    "config": ["browser.enabled"],
                },
                "primaryEnv": "GEMINI_API_KEY",
                "install": [{"type": "brew", "package": "uv"}],
            }
        }
        gating = SkillOpenClawGating.from_metadata(metadata)

        assert gating.required_bins == ["uv", "node"]
        assert gating.required_any_bins == ["python3", "python"]
        assert gating.required_env == ["GEMINI_API_KEY"]
        assert gating.required_config == ["browser.enabled"]
        assert gating.primary_env == "GEMINI_API_KEY"
        assert len(gating.install) == 1
        assert gating.has_requirements is True

    def test_from_metadata_falls_back_to_clawdbot_key(self) -> None:
        """旧版 metadata.clawdbot 键应被兼容识别。"""
        metadata = {
            "clawdbot": {
                "requires": {"bins": ["legacy-tool"]},
            }
        }
        gating = SkillOpenClawGating.from_metadata(metadata)
        assert gating.required_bins == ["legacy-tool"]
        assert gating.has_requirements is True

    def test_to_dict_roundtrip(self) -> None:
        """to_dict 应正确序列化所有 gating 字段。"""
        gating = SkillOpenClawGating(
            required_bins=["go"],
            required_env=["GOPATH"],
            primary_env="GOPATH",
        )
        d = gating.to_dict()
        assert d["required_bins"] == ["go"]
        assert d["required_env"] == ["GOPATH"]
        assert d["primary_env"] == "GOPATH"


class TestSkillMarkdownLoaderOpenClawFields:
    """验证 SkillMarkdownLoader 解析 OpenClaw 扩展 frontmatter 字段。"""

    @pytest.fixture
    def loader(self) -> SkillMarkdownLoader:
        """提供 SkillMarkdownLoader 实例。"""
        return SkillMarkdownLoader()

    def _write_skill_md(self, tmp_path: Path, frontmatter: Dict[str, Any], body: str = "# 指令") -> Path:
        """在临时目录写入 SKILL.md 文件并返回路径。"""
        # 手动构造 YAML frontmatter（避免依赖 PyYAML 序列化格式）
        lines = ["---"]
        for key, value in frontmatter.items():
            if key == "metadata":
                # metadata 必须是单行 JSON（OpenClaw 规范要求）
                lines.append(f"metadata: {json.dumps(value, ensure_ascii=False)}")
            elif isinstance(value, bool):
                lines.append(f"{key}: {str(value).lower()}")
            elif isinstance(value, list):
                lines.append(f"{key}:")
                for item in value:
                    lines.append(f"  - {item}")
            else:
                lines.append(f"{key}: {value}")
        lines.append("---")
        lines.append("")
        lines.append(body)

        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("\n".join(lines), encoding="utf-8")
        return skill_dir

    def test_load_metadata_parses_openclaw_gating(self, loader: SkillMarkdownLoader, tmp_path: Path) -> None:
        """应正确解析 metadata.openclaw 中的 gating 字段。"""
        skill_dir = self._write_skill_md(
            tmp_path,
            {
                "name": "image-lab",
                "description": "Generate images",
                "metadata": {
                    "openclaw": {
                        "requires": {"bins": ["uv"], "env": ["GEMINI_API_KEY"]},
                        "primaryEnv": "GEMINI_API_KEY",
                    }
                },
            },
        )

        meta = loader.load_metadata(skill_dir)

        assert meta is not None
        assert meta.name == "image-lab"
        assert meta.openclaw_gating.required_bins == ["uv"]
        assert meta.openclaw_gating.required_env == ["GEMINI_API_KEY"]
        assert meta.openclaw_gating.primary_env == "GEMINI_API_KEY"
        assert meta.openclaw_gating.has_requirements is True

    def test_load_metadata_parses_command_dispatch_tool(self, loader: SkillMarkdownLoader, tmp_path: Path) -> None:
        """应正确解析 command-dispatch: tool 模式。"""
        skill_dir = self._write_skill_md(
            tmp_path,
            {
                "name": "quick-action",
                "description": "Quick action skill",
                "command-dispatch": "tool",
                "command-tool": "run_action",
                "command-arg-mode": "json",
            },
        )

        meta = loader.load_metadata(skill_dir)

        assert meta is not None
        assert meta.command_dispatch == "tool"
        assert meta.command_tool == "run_action"
        assert meta.command_arg_mode == "json"

    def test_load_metadata_ignores_invalid_command_dispatch(self, loader: SkillMarkdownLoader, tmp_path: Path) -> None:
        """非法 command-dispatch 值应被忽略并回退为 None。"""
        skill_dir = self._write_skill_md(
            tmp_path,
            {
                "name": "bad-dispatch",
                "description": "Invalid dispatch",
                "command-dispatch": "invalid-value",
            },
        )

        meta = loader.load_metadata(skill_dir)

        assert meta is not None
        assert meta.command_dispatch is None

    def test_load_metadata_ignores_command_tool_without_dispatch(self, loader: SkillMarkdownLoader, tmp_path: Path) -> None:
        """command-dispatch 不是 tool 时，command-tool 应被忽略。"""
        skill_dir = self._write_skill_md(
            tmp_path,
            {
                "name": "orphan-tool",
                "description": "Orphan tool ref",
                "command-tool": "run_action",
            },
        )

        meta = loader.load_metadata(skill_dir)

        assert meta is not None
        assert meta.command_dispatch is None
        assert meta.command_tool is None

    def test_load_metadata_parses_user_invocable_false(self, loader: SkillMarkdownLoader, tmp_path: Path) -> None:
        """应正确解析 user-invocable: false。"""
        skill_dir = self._write_skill_md(
            tmp_path,
            {
                "name": "hidden-skill",
                "description": "Not user invocable",
                "user-invocable": False,
                "disable-model-invocation": True,
                "always": True,
            },
        )

        meta = loader.load_metadata(skill_dir)

        assert meta is not None
        assert meta.user_invocable is False
        assert meta.disable_model_invocation is True
        assert meta.always is True

    def test_load_metadata_parses_os_filter(self, loader: SkillMarkdownLoader, tmp_path: Path) -> None:
        """应正确解析 os 平台过滤字段。"""
        skill_dir = self._write_skill_md(
            tmp_path,
            {
                "name": "mac-only",
                "description": "macOS only skill",
                "os": "darwin",
                "homepage": "https://example.com",
            },
        )

        meta = loader.load_metadata(skill_dir)

        assert meta is not None
        assert meta.os_filter == "darwin"
        assert meta.homepage == "https://example.com"

    def test_load_metadata_ignores_invalid_os(self, loader: SkillMarkdownLoader, tmp_path: Path) -> None:
        """非法 os 值应被忽略。"""
        skill_dir = self._write_skill_md(
            tmp_path,
            {
                "name": "bad-os",
                "description": "Invalid OS",
                "os": "freebsd",
            },
        )

        meta = loader.load_metadata(skill_dir)

        assert meta is not None
        assert meta.os_filter is None

    def test_to_skill_config_includes_openclaw_fields(self, loader: SkillMarkdownLoader, tmp_path: Path) -> None:
        """to_skill_config 应包含 OpenClaw 扩展字段。"""
        skill_dir = self._write_skill_md(
            tmp_path,
            {
                "name": "config-test",
                "description": "Config test",
                "command-dispatch": "tool",
                "command-tool": "execute",
            },
        )

        meta = loader.load_metadata(skill_dir)
        assert meta is not None

        config = meta.to_skill_config()
        assert config["command_dispatch"] == "tool"
        assert config["command_tool"] == "execute"
        assert config["user_invocable"] is True
        assert config["always"] is False

    def test_to_skill_config_omits_empty_gating(self, loader: SkillMarkdownLoader, tmp_path: Path) -> None:
        """无 gating 要求时，to_skill_config 中 openclaw_gating 应为 None。"""
        skill_dir = self._write_skill_md(
            tmp_path,
            {"name": "no-gating", "description": "No gating"},
        )

        meta = loader.load_metadata(skill_dir)
        assert meta is not None

        config = meta.to_skill_config()
        assert config["openclaw_gating"] is None


# ---------------------------------------------------------------------------
# OpenClawAdapter 测试
# ---------------------------------------------------------------------------

class TestOpenClawAdapter:
    """验证 OpenClawAdapter 解析与适配行为。"""

    @pytest.fixture
    def adapter(self) -> OpenClawAdapter:
        """提供 OpenClawAdapter 实例。"""
        return OpenClawAdapter()

    def test_parse_manifest_dict_requires_id(self, adapter: OpenClawAdapter) -> None:
        """缺少 id 字段应抛出 OpenClawManifestError。"""
        with pytest.raises(OpenClawManifestError, match="id"):
            adapter.parse_manifest_dict({"configSchema": {}})

    def test_parse_manifest_dict_requires_config_schema(self, adapter: OpenClawAdapter) -> None:
        """configSchema 类型错误应抛出异常。"""
        with pytest.raises(OpenClawManifestError, match="configSchema"):
            adapter.parse_manifest_dict({"id": "test", "configSchema": "not a dict"})

    def test_parse_manifest_dict_accepts_empty_config_schema(self, adapter: OpenClawAdapter) -> None:
        """configSchema 缺失时应默认为空字典。"""
        manifest = adapter.parse_manifest_dict({"id": "test"})
        assert manifest.config_schema == {}

    def test_parse_manifest_dict_parses_full_manifest(self, adapter: OpenClawAdapter) -> None:
        """应完整解析所有 OpenClaw manifest 字段。"""
        data = {
            "id": "voice-call",
            "name": "Voice Call",
            "version": "2.1.0",
            "description": "Voice calling plugin",
            "configSchema": {"type": "object", "properties": {"apiKey": {"type": "string"}}},
            "contracts": {"tools": ["voice_dial", "voice_hangup"]},
            "toolMetadata": {"voice_hangup": {"optional": True}},
            "skills": ["voice-assistant"],
            "requiresPlugins": ["audio-codec"],
            "providers": ["twilio"],
            "channels": ["voice"],
            "kind": "memory",
            "enabledByDefault": True,
        }

        manifest = adapter.parse_manifest_dict(data)

        assert manifest.id == "voice-call"
        assert manifest.name == "Voice Call"
        assert manifest.version == "2.1.0"
        assert manifest.contracts == {"tools": ["voice_dial", "voice_hangup"]}
        assert manifest.tool_metadata == {"voice_hangup": {"optional": True}}
        assert manifest.skills == ["voice-assistant"]
        assert manifest.requires_plugins == ["audio-codec"]
        assert manifest.providers == ["twilio"]
        assert manifest.channels == ["voice"]
        assert manifest.kind == "memory"
        assert manifest.enabled_by_default is True

    def test_parse_manifest_dict_ignores_invalid_kind(self, adapter: OpenClawAdapter) -> None:
        """非法 kind 值应被忽略。"""
        manifest = adapter.parse_manifest_dict({"id": "test", "kind": "invalid"})
        assert manifest.kind is None

    def test_adapt_contracts_tools_to_extensions(self, adapter: OpenClawAdapter) -> None:
        """contracts.tools 应转换为 tool 扩展点。"""
        manifest = OpenClawManifest(
            id="image-gen",
            name="image-gen",
            version="1.0.0",
            contracts={"tools": ["image_generate", "image_edit"]},
            tool_metadata={"image_edit": {"optional": True}},
            config_schema={"type": "object"},
        )

        adapted = adapter.adapt(manifest)

        assert len(adapted.extensions) == 2
        tool_exts = [e for e in adapted.extensions if e["point"] == "tool"]
        assert len(tool_exts) == 2

        gen_ext = next(e for e in tool_exts if e["name"] == "image_generate")
        assert gen_ext["config"]["optional"] is False
        assert gen_ext["config"]["openclaw_source"] == "image-gen"

        edit_ext = next(e for e in tool_exts if e["name"] == "image_edit")
        assert edit_ext["config"]["optional"] is True

    def test_adapt_marks_non_executable(self, adapter: OpenClawAdapter) -> None:
        """适配后的 manifest 应标记为不可执行（TS 代码无法在 Python 进程内执行）。"""
        manifest = OpenClawManifest(id="test", name="test", version="1.0.0")
        adapted = adapter.adapt(manifest)
        assert adapted.executable is False

    def test_adapt_requires_plugins_to_permissions(self, adapter: OpenClawAdapter) -> None:
        """requiresPlugins 应转换为 plugin:require:<id> 权限。"""
        manifest = OpenClawManifest(
            id="dependent",
            name="dependent",
            version="1.0.0",
            requires_plugins=["base-plugin", "core-lib"],
        )
        adapted = adapter.adapt(manifest)
        assert "plugin:require:base-plugin" in adapted.permissions
        assert "plugin:require:core-lib" in adapted.permissions

    def test_adapt_fallback_extension_when_no_tools(self, adapter: OpenClawAdapter) -> None:
        """contracts 无 tools 但有其他能力时应注册 data_provider 占位。"""
        manifest = OpenClawManifest(
            id="embedder",
            name="embedder",
            version="1.0.0",
            contracts={"embeddings": ["text-embedding"]},
        )
        adapted = adapter.adapt(manifest)
        assert len(adapted.extensions) == 1
        assert adapted.extensions[0]["point"] == "data_provider"

    def test_adapt_fallback_extension_when_no_contracts(self, adapter: OpenClawAdapter) -> None:
        """无任何 contracts 时应注册 event_handler 占位以满足 minItems: 1。"""
        manifest = OpenClawManifest(id="empty", name="empty", version="1.0.0")
        adapted = adapter.adapt(manifest)
        assert len(adapted.extensions) == 1
        assert adapted.extensions[0]["point"] == "event_handler"

    def test_to_manifest_dict_strict_strips_openclaw_fields(self, adapter: OpenClawAdapter) -> None:
        """to_manifest_dict_strict 应剥离 OpenClaw 扩展字段。"""
        manifest = OpenClawManifest(id="test", name="test", version="1.0.0")
        adapted = adapter.adapt(manifest)
        strict = adapted.to_manifest_dict_strict()

        assert "_openclaw_id" not in strict
        assert "_executable" not in strict
        assert "name" in strict
        assert "extensions" in strict

    def test_parse_manifest_file_handles_missing_file(self, adapter: OpenClawAdapter, tmp_path: Path) -> None:
        """文件不存在时应抛出 OpenClawManifestError。"""
        with pytest.raises(OpenClawManifestError, match="不存在"):
            adapter.parse_manifest_file(tmp_path / "nonexistent.json")

    def test_parse_manifest_file_handles_invalid_json(self, adapter: OpenClawAdapter, tmp_path: Path) -> None:
        """JSON 解析失败时应抛出 OpenClawManifestError。"""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid json", encoding="utf-8")
        with pytest.raises(OpenClawManifestError, match="JSON 解析失败"):
            adapter.parse_manifest_file(bad_file)

    def test_detect_and_adapt_returns_none_when_no_manifest(self, adapter: OpenClawAdapter, tmp_path: Path) -> None:
        """目录中无 openclaw.plugin.json 时应返回 None。"""
        assert adapter.detect_and_adapt(tmp_path) is None

    def test_detect_and_adapt_parses_existing_manifest(self, adapter: OpenClawAdapter, tmp_path: Path) -> None:
        """目录中存在 openclaw.plugin.json 时应成功适配。"""
        plugin_dir = tmp_path / "my-plugin"
        plugin_dir.mkdir()
        manifest_path = plugin_dir / "openclaw.plugin.json"
        manifest_path.write_text(
            json.dumps({
                "id": "my-plugin",
                "name": "My Plugin",
                "version": "1.2.0",
                "contracts": {"tools": ["do_thing"]},
            }),
            encoding="utf-8",
        )

        adapted = adapter.detect_and_adapt(plugin_dir)

        assert adapted is not None
        assert adapted.name == "My Plugin"
        assert adapted.openclaw_id == "my-plugin"
        assert len(adapted.extensions) == 1


# ---------------------------------------------------------------------------
# BundleDetector 测试
# ---------------------------------------------------------------------------

class TestBundleDetector:
    """验证 BundleDetector 识别多种 bundle 格式。"""

    @pytest.fixture
    def detector(self) -> BundleDetector:
        """提供 BundleDetector 实例。"""
        return BundleDetector()

    def test_detect_openclaw_format(self, detector: BundleDetector, tmp_path: Path) -> None:
        """应识别 openclaw.plugin.json。"""
        plugin_dir = tmp_path / "openclaw-plugin"
        plugin_dir.mkdir()
        (plugin_dir / "openclaw.plugin.json").write_text('{"id": "test"}', encoding="utf-8")

        result = detector.detect(plugin_dir)

        assert result.detected is True
        assert result.format == BundleFormat.OPENCLAW

    def test_detect_codex_format(self, detector: BundleDetector, tmp_path: Path) -> None:
        """应识别 .codex-plugin/plugin.json。"""
        plugin_dir = tmp_path / "codex-plugin"
        plugin_dir.mkdir()
        codex_dir = plugin_dir / ".codex-plugin"
        codex_dir.mkdir()
        (codex_dir / "plugin.json").write_text('{"id": "codex-test"}', encoding="utf-8")

        result = detector.detect(plugin_dir)

        assert result.detected is True
        assert result.format == BundleFormat.CODEX

    def test_detect_claude_format(self, detector: BundleDetector, tmp_path: Path) -> None:
        """应识别 .claude-plugin/plugin.json。"""
        plugin_dir = tmp_path / "claude-plugin"
        plugin_dir.mkdir()
        claude_dir = plugin_dir / ".claude-plugin"
        claude_dir.mkdir()
        (claude_dir / "plugin.json").write_text('{"id": "claude-test"}', encoding="utf-8")

        result = detector.detect(plugin_dir)

        assert result.detected is True
        assert result.format == BundleFormat.CLAUDE

    def test_detect_cursor_format(self, detector: BundleDetector, tmp_path: Path) -> None:
        """应识别 .cursor-plugin/plugin.json。"""
        plugin_dir = tmp_path / "cursor-plugin"
        plugin_dir.mkdir()
        cursor_dir = plugin_dir / ".cursor-plugin"
        cursor_dir.mkdir()
        (cursor_dir / "plugin.json").write_text('{"id": "cursor-test"}', encoding="utf-8")

        result = detector.detect(plugin_dir)

        assert result.detected is True
        assert result.format == BundleFormat.CURSOR

    def test_detect_openawa_native_format(self, detector: BundleDetector, tmp_path: Path) -> None:
        """应识别 Open-AwA 原生 manifest.json。"""
        plugin_dir = tmp_path / "native-plugin"
        plugin_dir.mkdir()
        (plugin_dir / "manifest.json").write_text(
            json.dumps({"name": "native", "version": "1.0.0"}),
            encoding="utf-8",
        )

        result = detector.detect(plugin_dir)

        assert result.detected is True
        assert result.format == BundleFormat.OPENAWA

    def test_detect_returns_none_for_unknown_directory(self, detector: BundleDetector, tmp_path: Path) -> None:
        """无任何已知 manifest 的目录应返回未检测到。"""
        plugin_dir = tmp_path / "empty-plugin"
        plugin_dir.mkdir()

        result = detector.detect(plugin_dir)

        assert result.detected is False
        assert result.format is None

    def test_detect_returns_none_for_nonexistent_directory(self, detector: BundleDetector, tmp_path: Path) -> None:
        """不存在的目录应返回未检测到。"""
        result = detector.detect(tmp_path / "does-not-exist")
        assert result.detected is False

    def test_openawa_format_takes_priority(self, detector: BundleDetector, tmp_path: Path) -> None:
        """同时存在多种 manifest 时，Open-AwA 原生格式应优先。"""
        plugin_dir = tmp_path / "mixed-plugin"
        plugin_dir.mkdir()
        (plugin_dir / "manifest.json").write_text('{"name": "native"}', encoding="utf-8")
        (plugin_dir / "openclaw.plugin.json").write_text('{"id": "openclaw"}', encoding="utf-8")

        result = detector.detect(plugin_dir)

        assert result.format == BundleFormat.OPENAWA


class TestBundleManifestAdapter:
    """验证 BundleManifestAdapter 统一适配行为。"""

    @pytest.fixture
    def adapter(self) -> BundleManifestAdapter:
        """提供 BundleManifestAdapter 实例。"""
        return BundleManifestAdapter()

    def test_adapt_openclaw_bundle(self, adapter: BundleManifestAdapter, tmp_path: Path) -> None:
        """应适配 OpenClaw bundle 为内部 manifest 格式。"""
        plugin_dir = tmp_path / "openclaw-plugin"
        plugin_dir.mkdir()
        (plugin_dir / "openclaw.plugin.json").write_text(
            json.dumps({
                "id": "oc-plugin",
                "name": "OC Plugin",
                "version": "1.0.0",
                "contracts": {"tools": ["run"]},
            }),
            encoding="utf-8",
        )

        detection = BundleDetector().detect(plugin_dir)
        adapted = adapter.adapt(detection)

        assert adapted is not None
        assert adapted.name == "OC Plugin"
        assert adapted.executable is False
        assert adapted.openclaw_id == "oc-plugin"

    def test_adapt_codex_bundle_with_name_as_id(self, adapter: BundleManifestAdapter, tmp_path: Path) -> None:
        """Codex bundle 缺少 id 时应回退用 name 作为 id。"""
        plugin_dir = tmp_path / "codex-plugin"
        plugin_dir.mkdir()
        codex_dir = plugin_dir / ".codex-plugin"
        codex_dir.mkdir()
        (codex_dir / "plugin.json").write_text(
            json.dumps({"name": "codex-fallback", "version": "1.0.0"}),
            encoding="utf-8",
        )

        detection = BundleDetector().detect(plugin_dir)
        adapted = adapter.adapt(detection)

        assert adapted is not None
        assert adapted.openclaw_id == "codex-fallback"

    def test_adapt_openawa_native_executable(self, adapter: BundleManifestAdapter, tmp_path: Path) -> None:
        """Open-AwA 原生格式应标记为可执行。"""
        plugin_dir = tmp_path / "native-plugin"
        plugin_dir.mkdir()
        (plugin_dir / "manifest.json").write_text(
            json.dumps({
                "name": "native",
                "version": "1.0.0",
                "pluginApiVersion": "1.0.0",
                "extensions": [{"point": "tool", "name": "native_tool", "version": "1.0.0"}],
            }),
            encoding="utf-8",
        )

        detection = BundleDetector().detect(plugin_dir)
        adapted = adapter.adapt(detection)

        assert adapted is not None
        assert adapted.executable is True
        assert adapted.name == "native"

    def test_adapt_returns_none_for_undetected(self, adapter: BundleManifestAdapter, tmp_path: Path) -> None:
        """未检测到格式的目录应返回 None。"""
        plugin_dir = tmp_path / "empty"
        plugin_dir.mkdir()
        detection = BundleDetector().detect(plugin_dir)
        assert adapter.adapt(detection) is None


# ---------------------------------------------------------------------------
# PluginManager 集成测试
# ---------------------------------------------------------------------------

class TestPluginManagerBundleIntegration:
    """验证 PluginManager 能发现 bundle 格式插件。"""

    def test_discover_finds_openclaw_bundle_plugin(self, tmp_path: Path) -> None:
        """PluginManager 应发现 OpenClaw bundle 插件。"""
        from plugins.plugin_manager import PluginManager

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        plugin_dir = plugins_dir / "openclaw-demo"
        plugin_dir.mkdir()
        (plugin_dir / "openclaw.plugin.json").write_text(
            json.dumps({
                "id": "openclaw-demo",
                "name": "OpenClaw Demo",
                "version": "1.0.0",
                "description": "Demo OpenClaw plugin",
                "contracts": {"tools": ["demo_action"]},
            }),
            encoding="utf-8",
        )

        manager = PluginManager(plugins_dir=str(plugins_dir))
        discovered = manager.discover_plugins()

        assert len(discovered) == 1
        plugin_info = discovered[0]
        assert plugin_info["name"] == "OpenClaw Demo"
        assert plugin_info["bundle_format"] == "openclaw"
        assert plugin_info["executable"] is False
        assert plugin_info["openclaw_id"] == "openclaw-demo"

    def test_discover_finds_claude_bundle_plugin(self, tmp_path: Path) -> None:
        """PluginManager 应发现 Claude bundle 插件。"""
        from plugins.plugin_manager import PluginManager

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        plugin_dir = plugins_dir / "claude-demo"
        plugin_dir.mkdir()
        claude_dir = plugin_dir / ".claude-plugin"
        claude_dir.mkdir()
        (claude_dir / "plugin.json").write_text(
            json.dumps({
                "id": "claude-demo",
                "name": "Claude Demo",
                "version": "2.0.0",
                "contracts": {"tools": ["claude_action"]},
            }),
            encoding="utf-8",
        )

        manager = PluginManager(plugins_dir=str(plugins_dir))
        discovered = manager.discover_plugins()

        assert len(discovered) == 1
        assert discovered[0]["bundle_format"] == "claude"
        assert discovered[0]["name"] == "Claude Demo"

    def test_load_plugin_rejects_non_executable_bundle(self, tmp_path: Path) -> None:
        """load_plugin 应拒绝加载不可执行的 bundle 插件。"""
        from plugins.plugin_manager import PluginManager

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        plugin_dir = plugins_dir / "openclaw-demo"
        plugin_dir.mkdir()
        (plugin_dir / "openclaw.plugin.json").write_text(
            json.dumps({
                "id": "openclaw-demo",
                "name": "OpenClaw Demo",
                "version": "1.0.0",
                "contracts": {"tools": ["demo_action"]},
            }),
            encoding="utf-8",
        )

        manager = PluginManager(plugins_dir=str(plugins_dir))
        manager.discover_plugins()

        # 尝试加载应失败（bundle 插件不可执行）
        result = manager.load_plugin("OpenClaw Demo")
        assert result is False

    def test_discover_mixed_python_and_bundle_plugins(self, tmp_path: Path) -> None:
        """PluginManager 应同时发现 Python 插件和 bundle 插件。"""
        from plugins.plugin_manager import PluginManager

        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        # 创建一个简单的 Python 插件
        py_plugin_dir = plugins_dir / "py-plugin"
        py_plugin_dir.mkdir()
        (py_plugin_dir / "manifest.json").write_text(
            json.dumps({"name": "py-plugin", "version": "1.0.0"}),
            encoding="utf-8",
        )
        (py_plugin_dir / "__init__.py").write_text("", encoding="utf-8")
        (py_plugin_dir / "main.py").write_text(
            'from plugins.base_plugin import BasePlugin\n'
            'class PyPlugin(BasePlugin):\n'
            '    name = "py-plugin"\n'
            '    version = "1.0.0"\n'
            '    description = "Python plugin"\n'
            '    def initialize(self): return True\n'
            '    def execute(self, *args, **kwargs): return {"ok": True}\n'
            '    def cleanup(self): pass\n',
            encoding="utf-8",
        )

        # 创建一个 OpenClaw bundle 插件
        oc_plugin_dir = plugins_dir / "oc-plugin"
        oc_plugin_dir.mkdir()
        (oc_plugin_dir / "openclaw.plugin.json").write_text(
            json.dumps({
                "id": "oc-plugin",
                "name": "OC Plugin",
                "version": "1.0.0",
                "contracts": {"tools": ["oc_action"]},
            }),
            encoding="utf-8",
        )

        manager = PluginManager(plugins_dir=str(plugins_dir))
        discovered = manager.discover_plugins()

        # 应发现两个插件
        names = {p["name"] for p in discovered}
        assert "py-plugin" in names
        assert "OC Plugin" in names

        # bundle 插件应标记为不可执行
        oc_plugin = next(p for p in discovered if p["name"] == "OC Plugin")
        assert oc_plugin["executable"] is False
        assert oc_plugin["bundle_format"] == "openclaw"

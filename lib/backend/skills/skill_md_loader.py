"""
SKILL.md 标准格式加载器 — 支持 Anthropic Agent Skills 开放标准。

实现渐进式加载（L1/L2/L3）：
- L1 元数据：仅解析 YAML frontmatter 中的 name + description，~100 tokens/技能
- L2 指令体：加载 SKILL.md 的 Markdown 正文，仅在技能触发时加载
- L3 资源文件：按需加载 scripts/、references/、assets/ 中的文件

兼容策略：优先 SKILL.md → 回退 skill.yaml → 最后 DB config 字段。

OpenClaw 扩展兼容：
- 解析 metadata.openclaw 中的 gating 字段（requires.bins/env/config、primaryEnv、install）
- 支持 command-dispatch: tool 模式（slash 命令绕过模型直接派发到工具）
- 支持 user-invocable、disable-model-invocation、always 等 OpenClaw 专有字段

Task 16 扩展：
- 支持 execution-mode 字段（steps / prompt / fork），默认 steps 保持向后兼容
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import yaml
from loguru import logger


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SKILL_MD_FILENAME = "SKILL.md"
LEGACY_CONFIG_FILENAMES = ("skill.yaml", "skill.yml")

# SKILL.md 规范约束
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_INSTRUCTIONS_LENGTH = 5000  # tokens 估算，实际按字符数近似
RECOMMENDED_SUBDIRS = ("scripts", "references", "assets")

# execution-mode 合法值（Task 16: Skill 双模执行）
EXECUTION_MODE_VALUES = ("steps", "prompt", "fork")

# YAML frontmatter 正则：匹配开头的 --- ... --- 块
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# OpenClaw command-dispatch 合法值
OPENCLAW_COMMAND_DISPATCH_VALUES = {"tool"}
# OpenClaw command-arg-mode 合法值
OPENCLAW_COMMAND_ARG_MODE_VALUES = {"raw", "quoted", "json"}
# OpenClaw os 过滤合法值
OPENCLAW_OS_VALUES = {"darwin", "linux", "win32"}


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class SkillOpenClawGating:
    """
    OpenClaw 专有的 gating 字段（来自 metadata.openclaw）。
    用于声明 skill 启用前的环境要求。

    字段对应 OpenClaw 官方规范：
    - requires.bins: 所有二进制必须在 PATH 上
    - requires.anyBins: 至少一个二进制在 PATH 上
    - requires.env: 每个环境变量必须存在或通过 config 提供
    - requires.config: 每个 openclaw.json 路径必须为 truthy
    - primaryEnv: 与 skills.entries.<name>.apiKey 关联的环境变量名
    - install: 安装器规格数组（brew/node/go/uv/download）
    """
    required_bins: List[str] = field(default_factory=list)
    required_any_bins: List[str] = field(default_factory=list)
    required_env: List[str] = field(default_factory=list)
    required_config: List[str] = field(default_factory=list)
    primary_env: Optional[str] = None
    install: List[Dict[str, Any]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_metadata(cls, metadata: Any) -> "SkillOpenClawGating":
        """
        从 frontmatter 的 metadata 字段解析 OpenClaw gating。

        Args:
            metadata: frontmatter 中 metadata 字段的值（可能是 dict 或 None）。

        Returns:
            SkillOpenClawGating 实例。若 metadata 不是字典或不含 openclaw 键，返回空实例。
        """
        if not isinstance(metadata, dict):
            return cls()

        # OpenClaw gating 位于 metadata.openclaw；旧版兼容 metadata.clawdbot
        openclaw_meta = metadata.get("openclaw")
        if not isinstance(openclaw_meta, dict):
            openclaw_meta = metadata.get("clawdbot")
        if not isinstance(openclaw_meta, dict):
            return cls()

        requires = openclaw_meta.get("requires", {}) or {}
        if not isinstance(requires, dict):
            requires = {}

        required_bins = requires.get("bins", []) or []
        required_any_bins = requires.get("anyBins", []) or []
        required_env = requires.get("env", []) or []
        required_config = requires.get("config", []) or []

        # 确保列表类型安全
        def _as_str_list(value: Any) -> List[str]:
            if isinstance(value, list):
                return [str(item) for item in value]
            return []

        install = openclaw_meta.get("install", []) or []
        if not isinstance(install, list):
            install = []

        return cls(
            required_bins=_as_str_list(required_bins),
            required_any_bins=_as_str_list(required_any_bins),
            required_env=_as_str_list(required_env),
            required_config=_as_str_list(required_config),
            primary_env=openclaw_meta.get("primaryEnv") if isinstance(openclaw_meta.get("primaryEnv"), str) else None,
            install=[item for item in install if isinstance(item, dict)],
            raw=openclaw_meta,
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典表示，用于持久化或日志。"""
        return {
            "required_bins": self.required_bins,
            "required_any_bins": self.required_any_bins,
            "required_env": self.required_env,
            "required_config": self.required_config,
            "primary_env": self.primary_env,
            "install": self.install,
        }

    @property
    def has_requirements(self) -> bool:
        """是否声明了任何 gating 要求。"""
        return bool(
            self.required_bins
            or self.required_any_bins
            or self.required_env
            or self.required_config
        )


@dataclass
class SkillMetadata:
    """
    L1 元数据：始终加载，token 成本极低。
    对应 Anthropic 标准中 SKILL.md 的 YAML frontmatter。

    兼容 OpenClaw 扩展字段：
    - user_invocable: 是否暴露为用户 slash 命令（默认 True）
    - disable_model_invocation: 为 True 时不进入 agent system prompt
    - command_dispatch: 设为 "tool" 时 slash 命令绕过模型直接派发到工具
    - command_tool: command_dispatch=tool 时要调用的工具名
    - command_arg_mode: 工具派发时原始参数字符串转发方式
    - always: 为 True 时跳过所有 gate，总是包含
    - os_filter: 平台过滤
    - openclaw_gating: OpenClaw 专有 gating 字段

    Task 16 扩展字段：
    - execution_mode: 技能执行模式（steps / prompt / fork），默认 steps
    """
    name: str
    description: str
    version: str = "1.0.0"
    license: Optional[str] = None
    compatibility: Optional[str] = None
    author: Optional[str] = None
    category: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    allowed_tools: Optional[str] = None  # 实验性：安全沙箱声明
    raw_frontmatter: Dict[str, Any] = field(default_factory=dict)
    # OpenClaw 扩展字段
    user_invocable: bool = True
    disable_model_invocation: bool = False
    command_dispatch: Optional[str] = None
    command_tool: Optional[str] = None
    command_arg_mode: str = "raw"
    always: bool = False
    os_filter: Optional[str] = None
    homepage: Optional[str] = None
    openclaw_gating: SkillOpenClawGating = field(default_factory=SkillOpenClawGating)
    # Task 16: Skill 双模执行字段
    execution_mode: Literal["steps", "prompt", "fork"] = "steps"

    def to_skill_config(self) -> Dict[str, Any]:
        """将元数据转换为内部 skill_config 格式（兼容现有系统）。"""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author or "unknown",
            "category": self.category or "general",
            "tags": self.tags,
            "license": self.license,
            "compatibility": self.compatibility,
            "allowed_tools": self.allowed_tools,
            # OpenClaw 扩展字段（向后兼容：旧消费者可忽略）
            "user_invocable": self.user_invocable,
            "disable_model_invocation": self.disable_model_invocation,
            "command_dispatch": self.command_dispatch,
            "command_tool": self.command_tool,
            "command_arg_mode": self.command_arg_mode,
            "always": self.always,
            "os_filter": self.os_filter,
            "homepage": self.homepage,
            "openclaw_gating": self.openclaw_gating.to_dict() if self.openclaw_gating.has_requirements else None,
            # Task 16: 执行模式字段
            "execution_mode": self.execution_mode,
        }


@dataclass
class SkillInstructions:
    """
    L2 指令体：SKILL.md 中 frontmatter 之后的 Markdown 正文。
    仅在技能被触发时加载。
    """
    name: str
    content: str  # Markdown 指令正文
    estimated_tokens: int = 0

    def __post_init__(self):
        if not self.estimated_tokens:
            # 粗略估算：1 token ≈ 4 字符（英文）或 1.5 字符（中文）
            self.estimated_tokens = len(self.content) // 2


@dataclass
class SkillResource:
    """
    L3 资源文件：按需加载的外部文件。
    """
    name: str
    relative_path: str
    content: str
    resource_type: str  # "script", "reference", "asset"


# ---------------------------------------------------------------------------
# 加载器
# ---------------------------------------------------------------------------

class SkillMarkdownLoader:
    """
    Anthropic Agent Skills 开放标准（agentskills.io）的 SKILL.md 加载器。

    用法:
        loader = SkillMarkdownLoader()
        meta = loader.load_metadata(Path("/path/to/skill"))
        if meta:
            instructions = loader.load_instructions(Path("/path/to/skill"))
            resource = loader.load_resource(Path("/path/to/skill"), "references/api.md")
    """

    # ------------------------------------------------------------------
    # YAML Frontmatter 解析
    # ------------------------------------------------------------------

    @staticmethod
    def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
        """
        解析 SKILL.md 的 YAML frontmatter 和 Markdown 正文。

        Args:
            content: SKILL.md 文件的完整文本内容。

        Returns:
            (frontmatter_dict, body_text) 元组。
            若无 frontmatter，frontmatter_dict 为空字典，body_text 为全文。
        """
        match = _FRONTMATTER_RE.match(content)
        if not match:
            logger.debug("SKILL.md 未检测到 YAML frontmatter，返回全文作为正文")
            return {}, content.strip()

        yaml_text = match.group(1)
        body_text = content[match.end():].strip()

        try:
            frontmatter = yaml.safe_load(yaml_text)
        except yaml.YAMLError as e:
            logger.warning(f"SKILL.md YAML frontmatter 解析失败: {e}")
            return {}, content.strip()

        if not isinstance(frontmatter, dict):
            logger.warning("SKILL.md YAML frontmatter 不是字典格式")
            return {}, content.strip()

        return frontmatter, body_text

    # ------------------------------------------------------------------
    # L1：元数据加载（始终加载，~100 tokens/技能）
    # ------------------------------------------------------------------

    def load_metadata(self, skill_dir: Path) -> Optional[SkillMetadata]:
        """
        L1 加载：仅解析 YAML frontmatter 中的 name 和 description。
        始终加载，token 成本极低（~100 tokens/技能）。

        优先 SKILL.md，若不存在则回退到 skill.yaml。
        """
        skill_md_path = skill_dir / SKILL_MD_FILENAME

        if skill_md_path.exists():
            return self._load_metadata_from_skill_md(skill_md_path)

        # 回退：尝试旧版 skill.yaml
        for legacy_name in LEGACY_CONFIG_FILENAMES:
            legacy_path = skill_dir / legacy_name
            if legacy_path.exists():
                logger.info(f"使用旧版配置文件: {legacy_path}")
                return self._load_metadata_from_legacy(legacy_path)

        logger.warning(f"技能目录中未找到 SKILL.md 或 skill.yaml: {skill_dir}")
        return None

    def _load_metadata_from_skill_md(self, file_path: Path) -> Optional[SkillMetadata]:
        """从 SKILL.md 加载 L1 元数据（含 OpenClaw 扩展字段与 execution-mode）。"""
        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.error(f"读取 SKILL.md 失败: {file_path} — {e}")
            return None

        frontmatter, _ = self.parse_frontmatter(content)

        name = frontmatter.get("name", "")
        description = frontmatter.get("description", "")

        if not name:
            logger.warning(f"SKILL.md 缺少必需字段 'name': {file_path}")
            return None

        if not description:
            logger.warning(f"SKILL.md 缺少 'description' 字段，将使用空描述: {file_path}")

        # 解析 OpenClaw 扩展字段
        user_invocable = frontmatter.get("user-invocable", True)
        if not isinstance(user_invocable, bool):
            user_invocable = True

        disable_model_invocation = frontmatter.get("disable-model-invocation", False)
        if not isinstance(disable_model_invocation, bool):
            disable_model_invocation = False

        command_dispatch = frontmatter.get("command-dispatch")
        if command_dispatch not in OPENCLAW_COMMAND_DISPATCH_VALUES:
            if command_dispatch is not None:
                logger.warning(
                    f"SKILL.md 中 command-dispatch 值 '{command_dispatch}' 不合法，"
                    f"合法值: {OPENCLAW_COMMAND_DISPATCH_VALUES}，已忽略"
                )
            command_dispatch = None

        command_tool = frontmatter.get("command-tool")
        if not isinstance(command_tool, str):
            command_tool = None
        elif command_dispatch != "tool":
            logger.warning(
                f"SKILL.md 中 command-tool='{command_tool}' 但 command-dispatch 不是 'tool'，已忽略"
            )
            command_tool = None

        command_arg_mode = frontmatter.get("command-arg-mode", "raw")
        if command_arg_mode not in OPENCLAW_COMMAND_ARG_MODE_VALUES:
            logger.warning(
                f"SKILL.md 中 command-arg-mode 值 '{command_arg_mode}' 不合法，"
                f"合法值: {OPENCLAW_COMMAND_ARG_MODE_VALUES}，回退为 'raw'"
            )
            command_arg_mode = "raw"

        always = frontmatter.get("always", False)
        if not isinstance(always, bool):
            always = False

        os_filter = frontmatter.get("os")
        if os_filter is not None and os_filter not in OPENCLAW_OS_VALUES:
            logger.warning(
                f"SKILL.md 中 os 值 '{os_filter}' 不合法，合法值: {OPENCLAW_OS_VALUES}，已忽略"
            )
            os_filter = None

        homepage = frontmatter.get("homepage")
        if not isinstance(homepage, str):
            homepage = None

        # 解析 OpenClaw gating（metadata.openclaw）
        openclaw_gating = SkillOpenClawGating.from_metadata(frontmatter.get("metadata"))

        # author 兼容：顶层 author 或 metadata.author
        metadata_field = frontmatter.get("metadata")
        metadata_author = None
        if isinstance(metadata_field, dict):
            metadata_author = metadata_field.get("author")
            if not isinstance(metadata_author, str):
                metadata_author = None

        # Task 16: 解析 execution-mode 字段（默认 steps 保持向后兼容）
        execution_mode = frontmatter.get("execution-mode", "steps")
        if execution_mode not in EXECUTION_MODE_VALUES:
            logger.warning(
                f"SKILL.md 中 execution-mode 值 '{execution_mode}' 不合法，"
                f"合法值: {EXECUTION_MODE_VALUES}，回退为 'steps'"
            )
            execution_mode = "steps"

        return SkillMetadata(
            name=str(name).strip(),
            description=str(description).strip(),
            version=str(frontmatter.get("version", "1.0.0")).strip(),
            license=frontmatter.get("license"),
            compatibility=frontmatter.get("compatibility"),
            author=frontmatter.get("author") or metadata_author,
            category=frontmatter.get("category", "general"),
            tags=frontmatter.get("tags", []) if isinstance(frontmatter.get("tags"), list) else [],
            allowed_tools=frontmatter.get("allowed-tools"),
            raw_frontmatter=frontmatter,
            user_invocable=user_invocable,
            disable_model_invocation=disable_model_invocation,
            command_dispatch=command_dispatch,
            command_tool=command_tool,
            command_arg_mode=command_arg_mode,
            always=always,
            os_filter=os_filter,
            homepage=homepage,
            openclaw_gating=openclaw_gating,
            execution_mode=execution_mode,
        )

    def _load_metadata_from_legacy(self, file_path: Path) -> Optional[SkillMetadata]:
        """从旧版 skill.yaml 加载元数据（向后兼容）。"""
        try:
            config = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as e:
            logger.error(f"读取旧版技能配置失败: {file_path} — {e}")
            return None

        if not isinstance(config, dict):
            return None

        name = config.get("name", "")
        if not name:
            logger.warning(f"旧版技能配置缺少 'name': {file_path}")
            return None

        return SkillMetadata(
            name=str(name).strip(),
            description=str(config.get("description", "")).strip(),
            version=str(config.get("version", "1.0.0")).strip(),
            author=config.get("author"),
            category=config.get("category", "general"),
            tags=config.get("tags", []) if isinstance(config.get("tags"), list) else [],
            raw_frontmatter=config,
        )

    # ------------------------------------------------------------------
    # L2：指令体加载（触发时加载，< 5000 tokens）
    # ------------------------------------------------------------------

    def load_instructions(self, skill_dir: Path) -> Optional[SkillInstructions]:
        """
        L2 加载：加载 SKILL.md 的 Markdown 指令正文。
        仅在技能被触发/匹配时调用，建议正文 < 5000 tokens。
        """
        skill_md_path = skill_dir / SKILL_MD_FILENAME

        if not skill_md_path.exists():
            # 回退：旧版 skill.yaml 无指令体概念，返回空
            for legacy_name in LEGACY_CONFIG_FILENAMES:
                if (skill_dir / legacy_name).exists():
                    return SkillInstructions(
                        name=skill_dir.name,
                        content="",
                        estimated_tokens=0,
                    )
            return None

        try:
            content = skill_md_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.error(f"读取 SKILL.md 指令体失败: {skill_md_path} — {e}")
            return None

        frontmatter, body = self.parse_frontmatter(content)
        name = frontmatter.get("name", skill_dir.name)

        return SkillInstructions(
            name=str(name).strip(),
            content=body,
        )

    # ------------------------------------------------------------------
    # L3：资源文件加载（按需加载）
    # ------------------------------------------------------------------

    def load_resource(self, skill_dir: Path, resource_path: str) -> Optional[SkillResource]:
        """
        L3 加载：按需加载 scripts/、references/、assets/ 中的资源文件。

        Args:
            skill_dir: 技能根目录。
            resource_path: 相对于技能根目录的资源路径（如 "references/api.md"）。

        Returns:
            SkillResource 实例，若文件不存在或读取失败则返回 None。
        """
        full_path = (skill_dir / resource_path).resolve()

        # 路径遍历防护：确保资源路径在技能目录内
        try:
            full_path.relative_to(skill_dir.resolve())
        except ValueError:
            logger.warning(f"资源路径超出技能目录范围: {resource_path}")
            return None

        if not full_path.exists() or not full_path.is_file():
            logger.warning(f"资源文件不存在: {full_path}")
            return None

        try:
            content = full_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.error(f"读取资源文件失败: {full_path} — {e}")
            return None

        # 根据父目录推断资源类型
        parent_name = full_path.parent.name
        if parent_name in RECOMMENDED_SUBDIRS:
            resource_type = parent_name.rstrip("s")  # "scripts" → "script"
        else:
            resource_type = "asset"

        return SkillResource(
            name=full_path.name,
            relative_path=resource_path,
            content=content,
            resource_type=resource_type,
        )

    def list_resources(self, skill_dir: Path) -> List[str]:
        """
        列出技能目录中所有可用的 L3 资源文件（相对路径）。
        扫描 scripts/、references/、assets/ 子目录。
        """
        resources: List[str] = []
        skill_path = skill_dir.resolve()

        for subdir in RECOMMENDED_SUBDIRS:
            subdir_path = skill_path / subdir
            if not subdir_path.is_dir():
                continue
            for file_path in subdir_path.rglob("*"):
                if file_path.is_file():
                    try:
                        rel_path = file_path.relative_to(skill_path)
                        resources.append(str(rel_path).replace("\\", "/"))
                    except ValueError:
                        continue

        return sorted(resources)

    # ------------------------------------------------------------------
    # 格式校验
    # ------------------------------------------------------------------

    def validate_skill_md(self, skill_dir: Path) -> Dict[str, Any]:
        """
        校验 SKILL.md 格式的合规性。

        Returns:
            {"valid": bool, "errors": [...], "warnings": [...]}
        """
        errors: List[str] = []
        warnings: List[str] = []

        skill_md_path = skill_dir / SKILL_MD_FILENAME

        if not skill_md_path.exists():
            errors.append(f"缺少 {SKILL_MD_FILENAME} 文件")
            return {"valid": False, "errors": errors, "warnings": warnings}

        try:
            content = skill_md_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            errors.append(f"无法读取 {SKILL_MD_FILENAME}: {e}")
            return {"valid": False, "errors": errors, "warnings": warnings}

        frontmatter, body = self.parse_frontmatter(content)

        # 必需字段校验
        name = frontmatter.get("name", "")
        if not name:
            errors.append("YAML frontmatter 缺少必需字段 'name'")
        elif not isinstance(name, str):
            errors.append("'name' 必须是字符串")
        elif not re.match(r'^[a-z0-9][a-z0-9-]*$', str(name)):
            warnings.append(f"'name' 格式不规范: 建议仅使用小写字母、数字和连字符")
        elif len(str(name)) > MAX_NAME_LENGTH:
            errors.append(f"'name' 长度超过 {MAX_NAME_LENGTH} 字符上限")

        description = frontmatter.get("description", "")
        if not description:
            errors.append("YAML frontmatter 缺少必需字段 'description'")
        elif isinstance(description, str) and len(description) > MAX_DESCRIPTION_LENGTH:
            warnings.append(f"'description' 建议不超过 {MAX_DESCRIPTION_LENGTH} 字符")

        if not body.strip():
            warnings.append("SKILL.md 正文为空，技能缺少执行指令")

        # 推荐目录结构
        missing_dirs = [
            d for d in RECOMMENDED_SUBDIRS
            if not (skill_dir / d).is_dir()
        ]
        if missing_dirs:
            warnings.append(f"建议创建目录: {', '.join(missing_dirs)}")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    # 兼容性：批量加载元数据（用于技能发现/列表）
    # ------------------------------------------------------------------

    def load_all_metadata(self, base_dir: Path) -> List[SkillMetadata]:
        """
        批量加载目录下所有技能的 L1 元数据。
        用于 Agent 启动时的技能发现阶段。

        Args:
            base_dir: 技能根目录（如 ~/.openawa/skill_pool/）。

        Returns:
            SkillMetadata 列表，按名称排序。
        """
        metadata_list: List[SkillMetadata] = []

        if not base_dir.is_dir():
            logger.warning(f"技能目录不存在: {base_dir}")
            return metadata_list

        for skill_dir in sorted(base_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            meta = self.load_metadata(skill_dir)
            if meta:
                metadata_list.append(meta)

        logger.info(f"从 {base_dir} 发现了 {len(metadata_list)} 个技能")
        return metadata_list

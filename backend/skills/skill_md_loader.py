"""
SKILL.md 标准格式加载器 — 支持 Anthropic Agent Skills 开放标准。

实现渐进式加载（L1/L2/L3）：
- L1 元数据：仅解析 YAML frontmatter 中的 name + description，~100 tokens/技能
- L2 指令体：加载 SKILL.md 的 Markdown 正文，仅在技能触发时加载
- L3 资源文件：按需加载 scripts/、references/、assets/ 中的文件

兼容策略：优先 SKILL.md → 回退 skill.yaml → 最后 DB config 字段。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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

# YAML frontmatter 正则：匹配开头的 --- ... --- 块
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class SkillMetadata:
    """
    L1 元数据：始终加载，token 成本极低。
    对应 Anthropic 标准中 SKILL.md 的 YAML frontmatter。
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
        """从 SKILL.md 加载 L1 元数据。"""
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

        return SkillMetadata(
            name=str(name).strip(),
            description=str(description).strip(),
            version=str(frontmatter.get("version", "1.0.0")).strip(),
            license=frontmatter.get("license"),
            compatibility=frontmatter.get("compatibility"),
            author=frontmatter.get("author") or frontmatter.get("metadata", {}).get("author"),
            category=frontmatter.get("category", "general"),
            tags=frontmatter.get("tags", []) if isinstance(frontmatter.get("tags"), list) else [],
            allowed_tools=frontmatter.get("allowed-tools"),
            raw_frontmatter=frontmatter,
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

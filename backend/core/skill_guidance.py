"""
技能指导注入服务，将可用技能编译为 Agent 系统提示的一部分。

参考 OpenCode SkillGuidance 设计：
- 收集当前会话可用的技能列表
- 根据代理权限过滤不可用的技能
- 格式化技能列表注入到系统提示中
- 支持远程技能源（Git URL）和内嵌技能
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from loguru import logger
from pydantic import BaseModel, Field


class SkillSource(BaseModel):
    """技能来源定义"""
    type: str = Field(description="来源类型: directory/url/embedded")
    path: Optional[str] = Field(default=None, description="本地目录路径")
    url: Optional[str] = Field(default=None, description="远程 Git URL")
    name: Optional[str] = Field(default=None, description="内嵌技能名称")


class SkillMarkdownInfo(BaseModel):
    """从 Markdown + Frontmatter 解析的技能信息"""
    name: str
    description: Optional[str] = None
    slash: bool = False  # 是否作为斜杠命令
    location: Optional[str] = None
    content: str = ""


@dataclass
class SkillGuidanceResult:
    """技能指导生成结果"""
    skills_text: str = ""
    available_count: int = 0
    total_count: int = 0
    filtered_by_permission: int = 0


class SkillGuidance:
    """
    技能指导服务。

    负责：
    1. 从多个来源收集可用技能
    2. 根据代理权限过滤技能
    3. 生成格式化的技能列表提示
    """

    # 技能指导模板
    GUIDANCE_TEMPLATE = """## 可用技能

以下技能可在当前会话中使用。每个技能都有特定的能力范围，请根据任务需求选择合适的技能。

{skills_list}

使用技能时，请调用 `skill` 工具并指定技能名称和输入参数。"""

    def __init__(self, skill_engine=None):
        self._skill_engine = skill_engine
        self._custom_sources: List[SkillSource] = []

    def add_source(self, source: SkillSource) -> None:
        """添加额外的技能来源"""
        if source not in self._custom_sources:
            self._custom_sources.append(source)

    async def get_available_skills(
        self,
        agent_permissions: Optional[List[Dict[str, str]]] = None,
        agent_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取当前代理可用的技能列表。

        Args:
            agent_permissions: 代理权限规则列表
            agent_type: 代理类型

        Returns:
            过滤后的可用技能列表
        """
        if not self._skill_engine:
            return []

        try:
            # 权限过滤（复用 permission_manager 的 last-match-wins 策略）
            from core.permission_manager import evaluate_effect, PermissionRule, PermissionEffect, wildcard_match

            # 将 dict 格式的 agent_permissions 转为 PermissionRule 列表
            parsed_rules: List[PermissionRule] = []
            if agent_permissions:
                for rule in agent_permissions:
                    try:
                        parsed_rules.append(PermissionRule(
                            action=rule.get("action", "*"),
                            resource=rule.get("resource", "*"),
                            effect=PermissionEffect(rule.get("effect", "ask")),
                        ))
                    except ValueError:
                        # 无效的 effect 值，跳过该规则
                        logger.warning(f"跳过无效权限规则: {rule}")
                        continue

            # 获取所有技能
            registry = self._skill_engine.registry
            all_skills = registry.list_all()

            # 权限过滤
            available: List[Dict[str, Any]] = []
            for skill in all_skills:
                if not skill.enabled:
                    continue

                # 使用 evaluate_effect 保持与 PermissionManager 一致的权限判断
                if parsed_rules:
                    effect = evaluate_effect("skill", skill.name, parsed_rules)
                    if effect == PermissionEffect.DENY:
                        continue

                available.append({
                    "name": skill.name,
                    "version": skill.version,
                    "description": skill.description,
                    "enabled": skill.enabled,
                })

            return available
        except Exception as e:
            logger.warning(f"获取可用技能列表失败: {e}")
            return []

    def format_skills_guidance(
        self,
        skills: List[Dict[str, Any]],
    ) -> str:
        """
        格式化技能列表为系统提示文本。

        Args:
            skills: 可用技能列表

        Returns:
            格式化的技能指导文本
        """
        if not skills:
            return "当前没有可用的技能。"

        lines = []
        for i, skill in enumerate(skills, 1):
            name = skill.get("name") or "unknown"
            desc = skill.get("description") or ""
            # 转义控制字符防止系统提示注入
            name = name.replace("\n", " ").replace("\r", "")
            desc = desc.replace("\n", " ").replace("\r", "")
            lines.append(f"{i}. **{name}**: {desc}")

        skills_list = "\n".join(lines)
        return self.GUIDANCE_TEMPLATE.format(skills_list=skills_list)

    async def generate_guidance(
        self,
        agent_permissions: Optional[List[Dict[str, str]]] = None,
        agent_type: Optional[str] = None,
    ) -> SkillGuidanceResult:
        """
        生成完整的技能指导文本。

        Args:
            agent_permissions: 代理权限规则
            agent_type: 代理类型

        Returns:
            SkillGuidanceResult 包含指导文本和统计信息
        """
        try:
            total_skills = 0
            if self._skill_engine:
                total_skills = len(self._skill_engine.registry.list_all())

            available_skills = await self.get_available_skills(
                agent_permissions=agent_permissions,
                agent_type=agent_type,
            )

            skills_text = self.format_skills_guidance(available_skills)

            return SkillGuidanceResult(
                skills_text=skills_text,
                available_count=len(available_skills),
                total_count=total_skills,
                filtered_by_permission=total_skills - len(available_skills),
            )
        except Exception as e:
            logger.error(f"生成技能指导失败: {e}")
            return SkillGuidanceResult(
                skills_text="技能列表暂时不可用。",
                available_count=0,
                total_count=0,
                filtered_by_permission=0,
            )

    @staticmethod
    def parse_markdown_skill(content: str, filepath: Optional[str] = None) -> Optional[SkillMarkdownInfo]:
        """
        从 Markdown + Frontmatter 解析技能定义。

        支持的 Frontmatter 字段：
        - name: 技能名称
        - description: 技能描述
        - slash: 是否作为斜杠命令

        格式示例：
        ```markdown
        ---
        name: my-skill
        description: 我的自定义技能
        slash: true
        ---

        技能内容（Markdown 格式的系统提示）
        ```
        """
        # 解析 YAML frontmatter
        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
        if not frontmatter_match:
            # 尝试仅匹配第一个 --- 块
            frontmatter_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
            if not frontmatter_match:
                return None
            body = ""
        else:
            body = frontmatter_match.group(2).strip()

        try:
            import yaml
            frontmatter = yaml.safe_load(frontmatter_match.group(1)) or {}
        except (ImportError, Exception):
            return None

        name = frontmatter.get("name")
        if not name:
            # 从文件名推断
            if filepath:
                import os
                name = os.path.splitext(os.path.basename(filepath))[0]
            else:
                return None

        return SkillMarkdownInfo(
            name=name,
            description=frontmatter.get("description"),
            slash=bool(frontmatter.get("slash", False)),
            location=filepath,
            content=body or content,
        )

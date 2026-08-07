"""
技能指导注入服务，将可用技能编译为 Agent 系统提示的一部分。

参考 OpenCode SkillGuidance 设计：
- 收集当前会话可用的技能列表
- 根据代理权限过滤不可用的技能
- 格式化技能列表注入到系统提示中
- 支持远程技能源（Git URL）和内嵌技能
- 基于 Token 预算管理技能列表长度，避免占用过多上下文窗口
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from loguru import logger
from pydantic import BaseModel, Field

from core.context.token_budget import TokenBudget


# 预算紧张阈值：剩余预算低于最大预算的 20% 时只展示技能名称
TIGHT_BUDGET_THRESHOLD_RATIO = 0.2

# 无预算或全部技能被截断时的占位文本
SKILLS_OMITTED_TEXT = "[技能列表因预算限制已省略]"


def _skill_priority_key(skill: Dict[str, Any]) -> tuple:
    """
    计算技能排序优先级键。

    排序规则：
    1. 内置技能（is_builtin=True）优先级最高
    2. 用户常用技能（usage_count > 5）次之
    3. 其他技能最后

    同优先级组内按 usage_count 降序排列。

    Args:
        skill: 技能字典

    Returns:
        可比较的优先级键元组（值越小优先级越高）
    """
    is_builtin = bool(skill.get("is_builtin", False))
    usage_count = int(skill.get("usage_count", 0) or 0)

    if is_builtin:
        priority_group = 0
    elif usage_count > 5:
        priority_group = 1
    else:
        priority_group = 2

    # usage_count 取负值实现降序排列
    return (priority_group, -usage_count)


def format_commands_with_budget(
    skills: List[Dict[str, Any]],
    context_window: int,
    max_budget_ratio: float = 0.01,
) -> str:
    """
    在 Token 预算内格式化技能命令列表。

    算法流程：
    1. 计算 max_budget = context_window * max_budget_ratio
    2. 按优先级排序技能（内置 > 用户常用 > 其他）
    3. 逐个添加技能描述，累计 token 数
    4. 预算紧张时（剩余 < 20%），只展示技能名称
    5. 超预算时停止添加

    Args:
        skills: 技能列表，每个技能可包含 name、description、is_builtin、usage_count 字段
        context_window: 上下文窗口大小（token 数）
        max_budget_ratio: 最大预算占比，默认 0.01（1%）

    Returns:
        格式化后的技能列表文本；无预算或空列表时返回占位提示
    """
    if not skills:
        return ""

    # 计算最大 token 预算
    max_budget = int(context_window * max_budget_ratio)
    if max_budget <= 0:
        return SKILLS_OMITTED_TEXT

    budget_estimator = TokenBudget()
    tight_budget_threshold = max_budget * TIGHT_BUDGET_THRESHOLD_RATIO

    # 按优先级排序：内置 > 用户常用 > 其他
    sorted_skills = sorted(skills, key=_skill_priority_key)

    lines: List[str] = []
    used_tokens = 0

    for index, skill in enumerate(sorted_skills, 1):
        name = skill.get("name") or "unknown"
        desc = skill.get("description") or ""
        # 转义控制字符防止系统提示注入
        name = name.replace("\n", " ").replace("\r", "")
        desc = desc.replace("\n", " ").replace("\r", "")

        remaining_budget = max_budget - used_tokens

        # 预算紧张时只展示技能名称
        if remaining_budget < tight_budget_threshold:
            name_only_line = f"{index}. **{name}**"
            name_only_tokens = budget_estimator.estimate_tokens(name_only_line)
            if used_tokens + name_only_tokens > max_budget:
                break
            lines.append(name_only_line)
            used_tokens += name_only_tokens
            continue

        # 预算充足时完整展示
        full_line = f"{index}. **{name}**: {desc}"
        full_tokens = budget_estimator.estimate_tokens(full_line)

        if used_tokens + full_tokens > max_budget:
            # 完整展示超预算，尝试降级为只展示名称
            name_only_line = f"{index}. **{name}**"
            name_only_tokens = budget_estimator.estimate_tokens(name_only_line)
            if used_tokens + name_only_tokens <= max_budget:
                lines.append(name_only_line)
                used_tokens += name_only_tokens
            # 当前技能已无法完整展示，后续技能更不可能，停止添加
            break

        lines.append(full_line)
        used_tokens += full_tokens

    if not lines:
        return SKILLS_OMITTED_TEXT

    return "\n".join(lines)


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

    # 默认上下文窗口大小（用于未显式传入 context_window 的兼容场景）
    DEFAULT_CONTEXT_WINDOW = 128000

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
                    "is_builtin": bool(getattr(skill, "is_builtin", False)),
                    "usage_count": int(getattr(skill, "usage_count", 0) or 0),
                })

            return available
        except Exception as e:
            logger.warning(f"获取可用技能列表失败: {e}")
            raise

    def format_skills_guidance(
        self,
        skills: List[Dict[str, Any]],
        context_window: Optional[int] = None,
        max_budget_ratio: float = 0.01,
    ) -> str:
        """
        格式化技能列表为系统提示文本。

        当提供 context_window 时，使用基于 Token 预算的 format_commands_with_budget
        来管理技能列表长度；未提供时使用默认窗口大小以保持兼容。

        Args:
            skills: 可用技能列表
            context_window: 上下文窗口大小（token 数），未提供时使用默认值
            max_budget_ratio: 最大预算占比，默认 0.01

        Returns:
            格式化的技能指导文本
        """
        if not skills:
            return "当前没有可用的技能。"

        # 使用预算管理生成技能列表文本
        window = context_window if context_window is not None else self.DEFAULT_CONTEXT_WINDOW
        skills_list = format_commands_with_budget(
            skills,
            context_window=window,
            max_budget_ratio=max_budget_ratio,
        )

        # 预算管理返回占位文本时，直接使用占位文本作为技能列表
        return self.GUIDANCE_TEMPLATE.format(skills_list=skills_list)

    async def generate_guidance(
        self,
        agent_permissions: Optional[List[Dict[str, str]]] = None,
        agent_type: Optional[str] = None,
        context_window: Optional[int] = None,
        max_budget_ratio: float = 0.01,
    ) -> SkillGuidanceResult:
        """
        生成完整的技能指导文本。

        Args:
            agent_permissions: 代理权限规则
            agent_type: 代理类型
            context_window: 上下文窗口大小（token 数），用于预算管理
            max_budget_ratio: 最大预算占比，默认 0.01

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

            skills_text = self.format_skills_guidance(
                available_skills,
                context_window=context_window,
                max_budget_ratio=max_budget_ratio,
            )

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

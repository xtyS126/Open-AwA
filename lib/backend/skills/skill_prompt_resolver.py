"""
Skill Prompt 解析器（Task 16.2）。

为 prompt 模式的技能提供 prompt 文本解析与模板变量替换能力。

核心功能：
- get_prompt_for_command: 根据 skill_id 加载技能内容，返回作为 prompt 的文本
- 支持 {variable_name} 形式的模板变量，用 context 中的值替换

设计要点：
- 模板变量替换采用正则匹配，仅替换 {identifier} 形式且存在于 context 中的变量
- 未匹配的 {placeholder} 保留原样，避免误伤 JSON/代码片段中的花括号
- 若技能未配置 prompt 字段，回退到 description 字段
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from loguru import logger


# 模板变量正则：匹配 {identifier} 形式的占位符
# identifier 仅允许字母、数字、下划线，且不以数字开头
_TEMPLATE_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _replace_template_variables(template: str, context: Dict[str, Any]) -> str:
    """
    替换模板中的 {variable} 占位符为 context 中对应的值。

    仅替换 {identifier} 形式且 identifier 存在于 context 中的占位符；
    未匹配的占位符保留原样，避免误伤 JSON 或代码片段中的花括号。

    Args:
        template: 包含 {variable} 占位符的模板字符串。
        context: 提供变量值的上下文字典。

    Returns:
        替换后的字符串。
    """
    def _replacer(match: re.Match[str]) -> str:
        var_name = match.group(1)
        if var_name in context:
            return str(context[var_name])
        # 未在 context 中找到变量，保留原占位符
        return match.group(0)

    return _TEMPLATE_VAR_RE.sub(_replacer, template)


def get_prompt_for_command(
    skill_id: str,
    context: Dict[str, Any],
    skill_config: Optional[Dict[str, Any]] = None,
) -> str:
    """
    根据 skill_id 加载技能内容，返回作为 prompt 的文本。

    算法：
    1. 从传入的 skill_config 或技能存储加载技能内容
    2. 提取 prompt 文本（优先 prompt 字段，回退到 description 字段）
    3. 如果技能有模板变量，用 context 中的值替换
    4. 返回格式化的 prompt 字符串

    Args:
        skill_id: 技能标识符（技能名称）。
        context: 包含模板变量值的上下文字典。
        skill_config: 可选的技能配置字典。若提供则直接使用，
                      否则需要调用方自行加载（当前实现依赖此参数）。

    Returns:
        格式化后的 prompt 字符串。若技能无 prompt 和 description，返回空字符串。
    """
    if skill_config is None:
        # 当前实现依赖调用方传入 skill_config（SkillEngine 已加载）
        # 若未来需要独立加载，可在此处接入 SkillLoader
        logger.warning(
            f"get_prompt_for_command 未传入 skill_config，"
            f"skill_id={skill_id!r}，返回空 prompt"
        )
        return ""

    # 优先使用 prompt 字段，回退到 description 字段
    prompt_text = skill_config.get("prompt")
    if not prompt_text:
        prompt_text = skill_config.get("description", "")
        logger.debug(
            f"技能 {skill_id!r} 未配置 prompt 字段，回退到 description"
        )

    if not prompt_text:
        logger.warning(f"技能 {skill_id!r} 无 prompt 和 description，返回空字符串")
        return ""

    # 替换模板变量
    if context:
        prompt_text = _replace_template_variables(prompt_text, context)

    return prompt_text

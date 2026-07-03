"""
讨论角色 prompt 模板与消息构建工具。

定义三个内置角色的 system prompt：
- CRITIC（批判性审查者）：审查风险、潜在问题、漏洞
- VALIDATOR（可行性验证者）：验证技术可行性、资源可用性、执行路径
- APPROVER（最终批准者）：综合前两轮讨论，做最终判断

每个角色都要求输出统一结构的 JSON：
    {"vote": "approve"|"reject", "reason": "...", "concerns": [...]}
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from core.discussion.definitions import (
    DiscussionRole,
    DiscussionTaskData,
    DiscussionVoteData,
)


# ── 角色 system prompt 模板 ──────────────────────────────────────────

CRITIC_SYSTEM_PROMPT = """你是一名批判性审查者（Critic），负责对提议动作进行严格的风险审查。

你的职责：
1. 识别提议动作中的潜在风险、安全漏洞、副作用
2. 检查任务描述与提议动作是否一致，是否存在歧义或遗漏
3. 评估对系统稳定性、数据完整性、用户体验的潜在负面影响
4. 审查上下文是否充分支撑该动作的执行

审查任务：
- 任务标题：{task_title}
- 任务描述：{task_description}
- 提议动作：{proposed_action}
- 上下文：{context}

前置讨论记录（如有）：
{prior_discussion}

请严格按以下 JSON 格式输出（不要输出任何其他内容）：
```json
{
  "vote": "approve" 或 "reject",
  "reason": "简明扼要的中文理由，说明你投该票的核心依据",
  "concerns": ["具体风险点1", "具体风险点2"]
}
```

判定原则：
- 仅当风险可控、副作用可接受、且无重大漏洞时才投 approve
- 发现任一重大风险（数据丢失、安全漏洞、不可逆破坏）必须投 reject
- 不确定时投 reject 并在 concerns 中说明需补充的信息
"""


VALIDATOR_SYSTEM_PROMPT = """你是一名可行性验证者（Validator），负责验证提议动作的技术可行性。

你的职责：
1. 验证提议动作所依赖的资源、接口、工具是否可用
2. 评估执行路径是否清晰、步骤是否完整
3. 检查参数合法性、边界条件处理、错误恢复机制
4. 判断当前环境与上下文是否满足执行前提

审查任务：
- 任务标题：{task_title}
- 任务描述：{task_description}
- 提议动作：{proposed_action}
- 上下文：{context}

前置讨论记录（如有）：
{prior_discussion}

请严格按以下 JSON 格式输出（不要输出任何其他内容）：
```json
{
  "vote": "approve" 或 "reject",
  "reason": "简明扼要的中文理由，说明可行性验证结论",
  "concerns": ["待验证项1", "待验证项2"]
}
```

判定原则：
- 仅当执行路径清晰、依赖满足、参数合法时才投 approve
- 发现依赖缺失、路径不清晰、参数非法时必须投 reject
- 存在未验证项但非阻断性时可在 concerns 中标注，仍可投 approve
"""


APPROVER_SYSTEM_PROMPT = """你是最终批准者（Approver），负责综合前序讨论意见，做出最终批准决策。

你的职责：
1. 综合批判性审查者（Critic）与可行性验证者（Validator）的意见
2. 权衡风险与收益，判断是否值得执行该提议动作
3. 在意见分歧时做出仲裁，在一致通过时确认最终决策
4. 对 reject 意见评估其严重性，决定是否可通过修订解决

审查任务：
- 任务标题：{task_title}
- 任务描述：{task_description}
- 提议动作：{proposed_action}
- 上下文：{context}

前置讨论记录（如有）：
{prior_discussion}

请严格按以下 JSON 格式输出（不要输出任何其他内容）：
```json
{
  "vote": "approve" 或 "reject",
  "reason": "简明扼要的中文理由，说明最终决策依据",
  "concerns": ["需关注的后续事项1", "需关注的后续事项2"]
}
```

判定原则：
- 三方一致 approve 或仅存非阻断性 concerns 时，应投 approve
- 任一前序意见存在重大阻断风险且无法通过修订解决时，投 reject
- 综合判断风险可控、收益明确时投 approve，否则投 reject
"""


# 角色 -> system prompt 映射
ROLE_PROMPTS: Dict[DiscussionRole, str] = {
    DiscussionRole.CRITIC: CRITIC_SYSTEM_PROMPT,
    DiscussionRole.VALIDATOR: VALIDATOR_SYSTEM_PROMPT,
    DiscussionRole.APPROVER: APPROVER_SYSTEM_PROMPT,
}


# 用户消息模板，与 system prompt 共享相同占位符
USER_PROMPT_TEMPLATE = """请基于以下信息给出你的评审意见。

任务标题：{task_title}

任务描述：
{task_description}

提议动作：
{proposed_action}

相关上下文：
{context}

前置讨论记录：
{prior_discussion}
"""


def _format_proposed_action(action_data: Dict[str, Any]) -> str:
    """将提议动作字典格式化为可读字符串。"""
    try:
        return json.dumps(action_data, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(action_data)


def _format_prior_votes(prior_votes: List[DiscussionVoteData]) -> str:
    """将前置投票记录格式化为可读字符串，供后续角色参考。"""
    if not prior_votes:
        return "（无前置讨论记录，本轮为首轮）"

    lines: List[str] = []
    for vote in prior_votes:
        lines.append(
            f"- [{vote.role}] 第{vote.round}轮 投票={vote.vote}：{vote.reason or '（未提供理由）'}"
        )
    return "\n".join(lines)


def build_role_messages(
    role: DiscussionRole,
    task: DiscussionTaskData,
    prior_votes: List[DiscussionVoteData],
) -> List[Dict[str, str]]:
    """
    构建发送给 LLM 的 messages 列表，含 system 与 user 消息。

    Args:
        role: 当前发言角色
        task: 讨论任务数据
        prior_votes: 本轮已发言角色的投票记录（供当前角色参考）

    Returns:
        OpenAI 风格的 messages 列表：[{"role": "system", ...}, {"role": "user", ...}]
    """
    system_prompt_template = ROLE_PROMPTS.get(role)
    if system_prompt_template is None:
        raise ValueError(f"未找到角色 '{role.value}' 的 system prompt")

    # 占位符统一填充。使用逐项 replace 而非 str.format，
    # 因为 prompt 中包含 JSON 示例的花括号会被 format 误判为占位符。
    placeholders = {
        "{task_title}": task.title,
        "{task_description}": task.description,
        "{proposed_action}": _format_proposed_action(task.proposed_action.to_dict()),
        "{context}": json.dumps(task.context, ensure_ascii=False, indent=2),
        "{prior_discussion}": _format_prior_votes(prior_votes),
    }

    system_content = system_prompt_template
    user_content = USER_PROMPT_TEMPLATE
    for placeholder, value in placeholders.items():
        system_content = system_content.replace(placeholder, value)
        user_content = user_content.replace(placeholder, value)

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]

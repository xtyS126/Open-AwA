"""
抽取层：把用户的自然语言消息解析为结构化的心智评估。

对应 NSP-roleplay 架构中的「抽取 LLM」——用轻量快速模型（Haiku 档）解析
对话，输出 OCC 评估、受影响信念的加权误差、新记忆与认知更新，交由
确定性心智引擎（companion.mental_engine）计算人格演化。

设计：LLM 是「声音」，本层只负责解析，不直接参与后续人格计算。
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from billing.model_tier import EXTRACTION_TIER, resolve_tier_llm_config
from companion.appraisal import Appraisal
from companion.memory import CompanionMemory, sanitize_memory_content
from companion.mental_engine import MentalEngine, MentalExtraction


# 记忆类型白名单
VALID_MEMORY_TYPES = {
    "first_meeting",
    "emotional_moment",
    "shared_experience",
    "milestone",
    "user_preference",
    "inside_joke",
}

# 抽取响应中，加权误差的合理范围 [-1, 1]
WEIGHTED_ERROR_BOUND = 1.0


EXTRACTION_SYSTEM_PROMPT = """你是 AI 陪伴系统的「抽取层」。你的唯一职责是：阅读用户最新一条消息，输出结构化的心理评估 JSON，供确定性心智引擎计算人格演化。你不是在回复用户，不要输出任何 JSON 以外的内容。

输出 JSON 结构（严格遵循，所有数值在 [-1,1] 或 [0,1] 范围内）：
{
  "appraisal": {
    "relevance": 0.5,        // [0,1] 这条消息对角色是否重要
    "desirability": 0.0,     // [-1,1] 对角色目标是好是坏
    "controllability": 0.5,  // [0,1] 角色能否影响这件事
    "novelty": 0.5           // [0,1] 有多出乎意料
  },
  "weighted_errors": {        // 仅列出本条消息确实影响到的信念维度
    "self_worth": -0.3        // 正值=强化信念，负值=动摇信念，范围 [-1,1]
  },
  "new_memory": {             // 若本条消息值得被记住才给出，否则 null
    "content": "用户说……",
    "memory_type": "shared_experience",
    "emotional_intensity": 0.5,  // [0,1]
    "personality_impact": 0.5,   // [0,1]
    "keywords": ["关键词"]
  },
  "cognition_updates": [      // 角色的知识状态变化，可为空数组
    {"fact_id": "事实标识", "event_type": "hint"}
  ],
  "current_keywords": ["当前话题关键词"],
  "rational_cue": "冷通道（理性）如何行动的一句描述",
  "emotional_cue": "热通道（情感）如何行动的一句描述"
}

memory_type 只能取：first_meeting / emotional_moment / shared_experience / milestone / user_preference / inside_joke。
cognition_updates 的 event_type 只能取：hint / reveal / full_reveal / confirm / misleading / threat / breakdown / accept / cooldown / forget / remind / correct / challenge。
直接输出 JSON，不要用 ```json 代码块包裹。"""


def _clamp(value: Any, low: float = -1.0, high: float = 1.0) -> float:
    """安全转换为浮点并钳制到 [low, high]。"""
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return 0.0


def build_extraction_prompt(
    user_message: str,
    beliefs: Dict[str, float],
    context: str = "",
) -> str:
    """构建抽取层用户提示：注入当前信念维度与用户消息。"""
    belief_lines = "\n".join(f"- {name}: {value:.3f}" for name, value in beliefs.items())
    context_block = f"\n最近对话上下文：\n{context}" if context else ""
    return (
        f"角色当前信念维度（[0,1]）：\n{belief_lines}\n"
        f"{context_block}\n"
        f"用户最新消息：\n{user_message}\n\n"
        f"请输出上述结构的 JSON 心理评估。"
    )


def parse_mental_extraction(response_text: str) -> MentalExtraction:
    """把抽取层的 JSON 响应解析为 MentalExtraction，解析失败返回中性默认。"""
    text = (response_text or "").strip()
    # 剥离可能的 ```json 代码块包裹
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    data: Dict[str, Any] = {}
    try:
        # 尝试取首个 { 到末尾 } 的 JSON 对象
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            data = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, TypeError):
        logger.bind(event="companion_extract_parse_failed", module="companion").warning(
            f"抽取层响应无法解析为 JSON: {text[:200]}"
        )
        return MentalExtraction()

    if not isinstance(data, dict):
        return MentalExtraction()

    appraisal_data = data.get("appraisal") or {}
    new_memory = None
    memory_data = data.get("new_memory")
    if isinstance(memory_data, dict) and memory_data.get("content"):
        memory_type = str(memory_data.get("memory_type", "shared_experience"))
        if memory_type not in VALID_MEMORY_TYPES:
            memory_type = "shared_experience"
        new_memory = CompanionMemory(
            id=str(uuid.uuid4()),
            content=sanitize_memory_content(str(memory_data.get("content", "")).strip()),
            memory_type=memory_type,
            emotional_intensity=_clamp(memory_data.get("emotional_intensity", 0.5), 0.0, 1.0),
            personality_impact=_clamp(memory_data.get("personality_impact", 0.5), 0.0, 1.0),
            keywords=[str(k) for k in memory_data.get("keywords", []) or []],
        )

    cognition_updates: List[tuple] = []
    for item in (data.get("cognition_updates") or []):
        if isinstance(item, dict) and item.get("fact_id"):
            cognition_updates.append((str(item["fact_id"]), str(item.get("event_type", "hint"))))

    return MentalExtraction(
        appraisal=Appraisal(
            relevance=_clamp(appraisal_data.get("relevance", 0.5), 0.0, 1.0),
            desirability=_clamp(appraisal_data.get("desirability", 0.0), -1.0, 1.0),
            controllability=_clamp(appraisal_data.get("controllability", 0.5), 0.0, 1.0),
            novelty=_clamp(appraisal_data.get("novelty", 0.5), 0.0, 1.0),
        ),
        weighted_errors={
            str(name): _clamp(value, -WEIGHTED_ERROR_BOUND, WEIGHTED_ERROR_BOUND)
            for name, value in (data.get("weighted_errors") or {}).items()
        },
        cognition_updates=cognition_updates,
        new_memory=new_memory,
        current_keywords=[str(k) for k in (data.get("current_keywords") or [])],
        rational_cue=str(data.get("rational_cue", "") or ""),
        emotional_cue=str(data.get("emotional_cue", "") or ""),
    )


async def extract_mental_state(
    db: Session,
    user_message: str,
    engine: MentalEngine,
    context: str = "",
) -> MentalExtraction:
    """
    调用 Haiku 档模型解析用户消息，返回供心智引擎使用的 MentalExtraction。

    Args:
        db: 数据库会话
        user_message: 用户最新消息
        engine: 当前心智引擎（用于读取信念维度）
        context: 最近对话上下文（可选）

    Returns:
        MentalExtraction 结构化评估

    Raises:
        RuntimeError: 档位模型配置缺失或 LLM 调用失败（显式失败，由调用方处理）
    """
    from core.litellm_adapter import litellm_chat_completion

    config = resolve_tier_llm_config(db, EXTRACTION_TIER)

    beliefs = {
        name: node.value for name, node in engine.network.nodes.items()
    }
    user_prompt = build_extraction_prompt(user_message, beliefs, context)

    result = await litellm_chat_completion(
        provider=config["provider"],
        model=config["model"],
        api_key=config["api_key"],
        api_base=config.get("api_endpoint") or None,
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=2048,
        temperature=0.2,
        timeout=60.0,
        num_retries=1,
    )

    if not result.get("ok"):
        raise RuntimeError(f"抽取层 LLM 调用失败: {result.get('error', {})}")

    extraction = parse_mental_extraction(result.get("response", "") or "")
    logger.bind(
        event="companion_extracted",
        module="companion",
        tier=EXTRACTION_TIER,
        model=config["model"],
        emotion=extraction.appraisal.desirability,
    ).debug("抽取层完成心智评估")
    return extraction
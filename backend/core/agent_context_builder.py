"""AIAgent 上下文准备函数集合，从 core/agent.py 迁移以便独立测试与演进。

本模块包含以下 4 个纯函数：
- strip_reasoning_content: 递归移除对外响应中的思维链字段
- apply_scheduled_execution_defaults: 为定时任务执行场景补齐隔离开关
- build_multimodal_context: 根据附件构建多模态消息内容
- build_thinking_context: 根据思考参数构建上下文

core/agent.py 中对应的方法保留为薄包装，仅用于兼容既有测试
AIAgent._xxx(...) 调用，待 fix-test-implementation-coupling spec 落地后移除。
"""

from __future__ import annotations

# 标准库
from typing import Any, Dict

# 第三方库
# （暂无需要）

# 项目内部
# （build_multimodal_message / build_thinking_params 在函数体内延迟导入，避免循环依赖）


def strip_reasoning_content(payload: Any) -> Any:
    """
    递归移除对外响应中的思维链字段，避免 final_only 只在顶层生效。
    """
    if isinstance(payload, dict):
        return {
            key: strip_reasoning_content(value)
            for key, value in payload.items()
            if key != "reasoning_content"
        }
    if isinstance(payload, list):
        return [strip_reasoning_content(item) for item in payload]
    return payload


def apply_scheduled_execution_defaults(context: Dict[str, Any]) -> None:
    """
    为定时任务执行场景补齐隔离开关，避免污染聊天记录、记忆与经验链路。
    """
    if not context.get("scheduled_execution_isolated"):
        return

    context.setdefault("disable_behavior_logging", True)
    context.setdefault("disable_conversation_record", True)
    context.setdefault("disable_memory_update", True)
    context.setdefault("retrieve_experiences", False)
    context.setdefault("retrieve_long_term_memory", False)
    context.setdefault("enable_skill_plugin", False)
    context.setdefault("extract_experience", False)
    context.setdefault("output_mode", "final_only")


def build_multimodal_context(user_input: str, context: Dict[str, Any]) -> None:
    """
    根据上下文中的 attachments 构建多模态消息内容。
    若存在附件且 provider 支持多模态，则生成 content parts 数组；
    否则保持纯文本格式以保证向后兼容。
    """
    attachments = context.get("attachments")
    if not attachments:
        return
    provider = context.get("provider", "")
    model = context.get("model", "")
    from core.litellm_adapter import build_multimodal_message
    multimodal_content = build_multimodal_message(user_input, attachments, provider)
    context["_multimodal_content"] = multimodal_content


def build_thinking_context(context: Dict[str, Any]) -> None:
    """
    根据上下文中的 thinking_enabled 和 thinking_depth 构建思考参数。
    """
    thinking_enabled = context.get("thinking_enabled")
    thinking_depth = context.get("thinking_depth", 0)
    provider = context.get("provider", "")
    model = context.get("model", "")
    from core.litellm_adapter import build_thinking_params
    thinking_params = build_thinking_params(provider, model, thinking_depth, thinking_enabled)
    if thinking_params:
        context["_thinking_params"] = thinking_params

"""
LLM 工具函数，从旧 model_service.py 迁移的通用工具。
"""

from typing import Any, Dict, List, Optional, Union


def build_thinking_params(
    provider: str,
    model: str,
    thinking_depth: int,
    thinking_enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    根据厂商和模型映射思考深度到具体的 API 参数字典。
    深度 0-5 映射策略：
    - OpenAI (o1/o3/o4/gpt-5): reasoning_effort（0-1->low, 2-3->medium, 4-5->high）
    - Anthropic (Claude 4.6/4.7): thinking.type=adaptive + output_config.effort（low/medium/high/xhigh/max）
    - Anthropic (Claude旧版): thinking.type=enabled + budget_tokens（深度*4000，最低1024）
    - DeepSeek (V4/R1): extra_body.thinking.type=enabled/disabled + reasoning_effort（high/max）
    - Gemini (2.5/3.0): reasoning_effort（none/low/medium/high）
    - Zhipu GLM: thinking.type=enabled/disabled
    - Aliyun Qwen/QwQ: extra_body={"enable_thinking": True/False}
    - 其他模型返回空字典
    """
    from billing.pricing_manager import PricingManager

    normalized = PricingManager.normalize_provider(provider)
    if not model:
        return {}

    model_lower = model.lower()

    # 处理明确关闭思考的情况
    if thinking_enabled is False:
        if normalized == "deepseek" or "deepseek" in model_lower:
            # V4 系列不支持 thinking 参数，关闭思考时需用 reasoning_effort
            if any(v4_prefix in model_lower for v4_prefix in ("deepseek-v4", "deepseek_v4")):
                return {"extra_body": {"reasoning_effort": "none"}}
            return {"extra_body": {"thinking": {"type": "disabled"}}}
        if normalized == "google" or "gemini" in model_lower:
            return {"reasoning_effort": "none"}
        if normalized == "zhipu" and "glm" in model_lower:
            return {"thinking": {"type": "disabled"}}
        if normalized == "aliyun" or "qwen" in model_lower or "qwq" in model_lower:
            return {"extra_body": {"enable_thinking": False}}
        return {}

    # 如果没有开启思考，且 depth < 1，返回空
    if thinking_depth < 1 and thinking_enabled is not True:
        return {}

    # OpenAI (o系列/gpt-5)
    if normalized in ("openai",) and any(
        model_lower.startswith(prefix) for prefix in ("o1", "o3", "o4", "gpt-5")
    ):
        if thinking_depth <= 1:
            effort = "low"
        elif thinking_depth <= 3:
            effort = "medium"
        else:
            effort = "high"
        return {"reasoning_effort": effort}

    # Anthropic (Claude)
    if normalized == "anthropic":
        # 新版 Claude 4.6/4.7 系列使用 Adaptive thinking
        if any(v in model_lower for v in ("claude-opus-4-6", "claude-sonnet-4-6", "claude-opus-4-7")):
            if thinking_depth <= 1:
                effort = "low"
            elif thinking_depth == 2:
                effort = "medium"
            elif thinking_depth == 3:
                effort = "high"
            elif thinking_depth == 4:
                effort = "xhigh"
            else:
                effort = "max"
            return {"thinking": {"type": "adaptive"}, "output_config": {"effort": effort}}
        else:
            # 旧版使用 budget_tokens
            budget_tokens = max(1024, thinking_depth * 4000 if thinking_depth > 0 else 4000)
            return {"thinking": {"type": "enabled", "budget_tokens": budget_tokens}}

    # DeepSeek 推理模型
    if normalized == "deepseek" or "deepseek" in model_lower:
        if thinking_depth <= 3:
            effort = "high"
        else:
            effort = "max"
        # V4 系列模型：仅支持 reasoning_effort，不支持 thinking 参数（thinking 为 R1 独有）
        if any(v4_prefix in model_lower for v4_prefix in ("deepseek-v4", "deepseek_v4")):
            return {"extra_body": {"reasoning_effort": effort}}
        # R1/旧版推理模型：同时需要 thinking 和 reasoning_effort
        return {
            "extra_body": {
                "thinking": {"type": "enabled"},
                "reasoning_effort": effort,
            }
        }

    # Gemini (2.5/3.0)
    if normalized == "google" or "gemini" in model_lower:
        if thinking_depth <= 1:
            effort = "low"
        elif thinking_depth <= 3:
            effort = "medium"
        else:
            effort = "high"
        return {"reasoning_effort": effort}

    # Zhipu GLM 推理模型
    if normalized == "zhipu" and "glm" in model_lower:
        return {"thinking": {"type": "enabled"}}

    # 阿里云 Qwen/QwQ 推理模型
    if normalized == "aliyun" or "qwen" in model_lower or "qwq" in model_lower:
        return {"extra_body": {"enable_thinking": True}}

    return {}


def build_multimodal_message(
    text: str,
    attachments: Optional[List[Dict[str, Any]]] = None,
    provider: str = "",
) -> Union[str, List[Dict[str, Any]]]:
    """
    根据 provider 将文本和附件构建为多模态消息格式。
    无附件时返回纯文本字符串以保证向后兼容。
    """
    from billing.pricing_manager import PricingManager

    if not attachments:
        return text

    normalized = PricingManager.normalize_provider(provider)

    if normalized == "anthropic":
        # Anthropic content blocks 格式
        content_blocks: List[Dict[str, Any]] = []
        if text:
            content_blocks.append({"type": "text", "text": text})
        for att in attachments:
            att_type = att.get("type", "")
            mime = att.get("mime_type", "")
            data = att.get("data", "")
            if att_type == "image":
                content_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": data,
                    },
                })
            elif att_type == "audio":
                content_blocks.append({
                    "type": "audio",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": data,
                    },
                })
            elif att_type == "video":
                content_blocks.append({
                    "type": "video",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": data,
                    },
                })
        return content_blocks

    if normalized == "google":
        # Google Gemini parts 格式
        parts: List[Dict[str, Any]] = []
        if text:
            parts.append({"text": text})
        for att in attachments:
            att_type = att.get("type", "")
            mime = att.get("mime_type", "")
            data = att.get("data", "")
            if att_type == "image":
                parts.append({"inline_data": {"mime_type": mime, "data": data}})
            elif att_type == "audio":
                parts.append({"inline_data": {"mime_type": mime, "data": data}})
            elif att_type == "video":
                parts.append({"inline_data": {"mime_type": mime, "data": data}})
        return parts

    # OpenAI 兼容格式（OpenAI / DeepSeek / Alibaba / Moonshot / Zhipu）
    content_parts: List[Dict[str, Any]] = []
    if text:
        content_parts.append({"type": "text", "text": text})
    for att in attachments:
        att_type = att.get("type", "")
        mime = att.get("mime_type", "")
        data = att.get("data", "")
        if att_type == "image":
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{data}"},
            })
        elif att_type == "audio":
            content_parts.append({
                "type": "audio_url",
                "audio_url": {"url": f"data:{mime};base64,{data}"},
            })
        elif att_type == "video":
            content_parts.append({
                "type": "video_url",
                "video_url": {"url": f"data:{mime};base64,{data}"},
            })
    return content_parts


def extract_reasoning_content(response_data: Dict[str, Any], provider: str = "") -> str:
    """
    从模型非流式响应中提取推理内容（思维链）。
    不同 Provider 的响应格式不同，需分别处理：
    - OpenAI/DeepSeek: choices[0].message.reasoning_content
    - Anthropic: content blocks 中 type 为 "thinking" 的 block
    """
    # OpenAI / DeepSeek 兼容格式
    choices = response_data.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, dict):
            message = first_choice.get("message")
            if isinstance(message, dict):
                reasoning = message.get("reasoning_content")
                if isinstance(reasoning, str) and reasoning:
                    return reasoning

    # Anthropic 格式：content 列表中 type 为 "thinking" 的 block
    content = response_data.get("content")
    if isinstance(content, list):
        thinking_parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "thinking":
                text = block.get("thinking", "")
                if isinstance(text, str) and text:
                    thinking_parts.append(text)
        if thinking_parts:
            return "\n".join(thinking_parts)

    return ""


def normalize_provider_name(provider: str) -> str:
    """
    标准化 Provider 名称。
    将各种别名统一为规范名称。

    Args:
        provider: 原始 Provider 名称

    Returns:
        str: 标准化后的名称
    """
    provider = provider.lower().strip()

    # 别名映射
    aliases = {
        "anthropic": "claude",
        "google": "gemini",
        "deepseek": "openai",  # DeepSeek 兼容 OpenAI 格式
        "azure": "openai",
    }

    return aliases.get(provider, provider)

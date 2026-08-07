"""
记忆巩固 LLM 提炼器。

Spec memory-quality-and-short-term-recovery 阶段 2 的核心配套模块。
提供 :func:`make_default_extract_callback` 工厂，用于在 ``core/agent.py``
装配时注入 :class:`memory.consolidation_runner.ConsolidationRunner`。

设计要点：
- 工厂接收 ``session_factory``，每次调用时通过独立 db session 解析模型配置，
  避免在 fire-and-forget 后台任务中持有请求级 session。
- 复用 ``PricingManager.get_default_configuration`` 解析 provider/model/api_key/api_endpoint，
  与 executor 的 LLM 配置解析路径保持一致。
- 通过 :func:`core.litellm_adapter.litellm_chat_completion` 发起非流式 LLM 调用。
- 失败时返回空列表：让上层 watermark 仍推进，不阻塞巩固流程（与 spec 中
  "LLM 提炼失败 → 跳过提炼但仍记录 fingerprint" 的回退策略一致）。

LLM 提炼 prompt 设计：
- 系统消息要求 LLM 扮演"记忆提炼助手"，从短期记忆中提取用户偏好/事实/决策
- 用户消息附带 JSON 格式的短期记忆列表
- 要求 LLM 返回严格 JSON 数组，每项含 content/importance/source_type/source_short_term_memory_id
- 通过 ``json.loads`` 解析失败时返回空列表
"""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional

from loguru import logger


ExtractCallback = Callable[
    [List[Dict[str, Any]], Optional[str]],
    Awaitable[List[Dict[str, Any]]],
]


# LLM 提炼系统提示词：要求模型从短期记忆中提炼高价值信息并返回严格 JSON
_EXTRACT_SYSTEM_PROMPT = """你是记忆提炼助手。你的任务是从用户的近期对话记录中提炼高价值信息，写入长期记忆库。

提炼规则：
1. 只提取值得长期记住的事实、用户偏好、关键决策、技术知识
2. 跳过寒暄、闲聊、过场对话、临时调试信息
3. 每条提炼内容 ≤ 200 字，已提炼的事实/偏好/知识，不要原文对话片段
4. 不要包含 API key、密码、身份证号等敏感信息（已自动脱敏）
5. importance 范围 0.0-1.0：关键决策/重要偏好 ≥ 0.7，普通事实 0.4-0.6，边缘信息 < 0.4
6. source_type 从 {"preference", "fact", "decision", "knowledge", "other"} 中选择

返回格式（严格 JSON，不要任何 markdown 标记或额外说明）：
[
  {
    "content": "提炼后的事实/偏好/知识（≤200字）",
    "importance": 0.7,
    "source_type": "preference",
    "source_short_term_memory_id": 123
  }
]

若无值得提炼的内容，返回空数组 []。"""


def _build_extract_user_prompt(messages: List[Dict[str, Any]]) -> str:
    """
    构造 LLM 提炼用户消息（含短期记忆 JSON）。

    Args:
        messages: 短期记忆列表，每项含 id / role / content / session_id

    Returns:
        用户消息文本
    """
    # 压缩为 LLM 友好格式：仅保留 id/role/content，session_id 转为短哈希避免泄露
    compact: List[Dict[str, Any]] = []
    for m in messages:
        entry: Dict[str, Any] = {
            "id": m.get("id"),
            "role": m.get("role", "user"),
            "content": (m.get("content") or "")[:500],  # 单条截断 500 字
        }
        # 多模态记忆：携带图片附件 URL（如有）。视觉理解模型配置后，
        # LLM 可基于图片 URL 理解内容并在提炼结果中附带 caption；
        # 未配置视觉模型时 URL 仅作为文本引用，不影响提炼流程
        images = m.get("images")
        if isinstance(images, list) and images:
            entry["images"] = [
                {"url": img.get("url", "")} for img in images if isinstance(img, dict) and img.get("url")
            ]
        compact.append(entry)
    return f"请从以下短期记忆中提炼高价值信息：\n\n{json.dumps(compact, ensure_ascii=False)}"


def _extract_json_array(text: str) -> List[Dict[str, Any]]:
    """
    从 LLM 回复文本中提取 JSON 数组。

    LLM 可能返回带 markdown 代码块或前后说明文字，需要容错处理。

    Args:
        text: LLM 回复文本

    Returns:
        解析后的字典列表；解析失败返回空列表
    """
    if not text:
        return []
    text = text.strip()
    # 1. 直接尝试解析
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [_normalize_extract_item(item) for item in data if isinstance(item, dict)]
    except json.JSONDecodeError:
        pass
    # 2. 提取 ```json ... ``` 代码块
    match = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, list):
                return [_normalize_extract_item(item) for item in data if isinstance(item, dict)]
        except json.JSONDecodeError:
            pass
    # 3. 提取首个 [ 到末尾 ] 的子串
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, list):
                return [_normalize_extract_item(item) for item in data if isinstance(item, dict)]
        except json.JSONDecodeError:
            pass
    return []


def _normalize_extract_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    规范化 LLM 返回的单条提炼结果，确保字段类型与下游期望一致。
    """
    content = str(item.get("content", "")).strip()
    if not content:
        return {}
    try:
        importance = float(item.get("importance", 0.5))
    except (TypeError, ValueError):
        importance = 0.5
    importance = max(0.0, min(1.0, importance))
    source_type = str(item.get("source_type", "llm_extracted") or "llm_extracted").strip()
    source_id = item.get("source_short_term_memory_id")
    if not (isinstance(source_id, int) and source_id > 0):
        source_id = None
    return {
        "content": content[:200],  # 五因子中 completeness 要求 ≤200 字
        "importance": importance,
        "source_type": source_type,
        "source_short_term_memory_id": source_id,
    }


def _resolve_llm_config(session_factory, preferred_provider: str, preferred_model: str) -> Optional[Dict[str, Any]]:
    """
    通过 PricingManager 解析 LLM 配置。

    优先级：
    1. settings 中显式配置的 CONSOLIDATION_EXTRACT_PROVIDER/MODEL
    2. DB 默认配置（PricingManager.get_default_configuration）

    Returns:
        含 provider/model/api_key/api_endpoint 的字典，解析失败返回 None
    """
    from config.settings import settings
    from config.security import decrypt_secret_value

    try:
        with session_factory() as db:
            from billing.pricing_manager import PricingManager
            pricing_manager = PricingManager(db)

            provider = (preferred_provider or "").strip() or None
            model = (preferred_model or "").strip() or None
            config = None
            if provider and model:
                config = pricing_manager.get_configuration_by_provider_model(provider, model)
            if not config and provider:
                config = pricing_manager.get_default_provider_configuration(provider)
            if not config:
                config = pricing_manager.get_default_configuration()

            if not config:
                return None

            provider = provider or config.provider
            model = model or config.model
            api_endpoint = config.api_endpoint

            # 解密 API Key：优先 ModelConfiguration.api_key，回退到 ProviderCredential；
            # api_endpoint 同样从 credential 回退（model_configurations 可能未冗余 endpoint）
            raw_key = config.api_key or ""
            api_key = ""
            cred = None
            try:
                cred = pricing_manager.get_provider_credential(provider)
            except Exception as exc:
                logger.warning(f"巩固提炼解析 ProviderCredential 失败 provider={provider}: {exc}")
            if raw_key:
                if raw_key.startswith("enc:"):
                    # 旧算法密文，跳过（与 executor 行为一致）
                    logger.warning(
                        f"巩固提炼模型 {provider}/{model} 的 api_key 为旧算法密文，已跳过"
                    )
                else:
                    api_key = decrypt_secret_value(raw_key)
            if not api_key and cred and cred.api_key:
                if cred.api_key.startswith("enc:"):
                    logger.warning(
                        f"巩固提炼模型 {provider}/{model} 的 ProviderCredential api_key 为旧算法密文，已跳过"
                    )
                else:
                    api_key = decrypt_secret_value(cred.api_key)
            # endpoint 回退：config.api_endpoint 为空时使用 ProviderCredential.api_endpoint
            if not api_endpoint and cred and cred.api_endpoint:
                api_endpoint = cred.api_endpoint

            if not api_key:
                logger.warning(
                    f"巩固提炼模型 {provider}/{model} 未解析到可用 API Key，跳过提炼"
                )
                return None

            return {
                "provider": provider,
                "model": model,
                "api_key": api_key,
                "api_endpoint": api_endpoint,
                "max_tokens": getattr(config, "max_tokens", None),
            }
    except Exception as exc:
        logger.opt(exception=True).warning(f"巩固提炼 LLM 配置解析失败: {exc}")
        return None


def make_default_extract_callback(
    session_factory,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> ExtractCallback:
    """
    创建默认的 LLM 提炼回调。

    Args:
        session_factory: SQLAlchemy session 工厂，每次调用时创建独立 db session
        provider: 可选的显式 provider 覆盖（来自 settings.CONSOLIDATION_EXTRACT_PROVIDER）
        model: 可选的显式 model 覆盖（来自 settings.CONSOLIDATION_EXTRACT_MODEL）

    Returns:
        async callback，签名与 :data:`ExtractCallback` 一致

    使用示例::

        callback = make_default_extract_callback(
            SessionLocal,
            provider=settings.CONSOLIDATION_EXTRACT_PROVIDER or None,
            model=settings.CONSOLIDATION_EXTRACT_MODEL or None,
        )
        runner.set_extract_callback(callback)
    """
    from config.settings import settings as _settings
    from core.litellm_adapter import litellm_chat_completion

    preferred_provider = (provider or _settings.CONSOLIDATION_EXTRACT_PROVIDER or "").strip() or None
    preferred_model = (model or _settings.CONSOLIDATION_EXTRACT_MODEL or "").strip() or None
    max_tokens = int(_settings.CONSOLIDATION_EXTRACT_MAX_TOKENS)

    async def _callback(
        messages: List[Dict[str, Any]],
        user_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        if not messages:
            return []

        # 每次调用时独立解析配置，避免持有长期 db session
        config = _resolve_llm_config(session_factory, preferred_provider, preferred_model)
        if config is None:
            logger.warning(
                f"巩固提炼跳过 LLM 阶段：未解析到可用模型配置 user_id={user_id}"
            )
            return []

        try:
            result = await litellm_chat_completion(
                provider=config["provider"],
                model=config["model"],
                api_key=config["api_key"],
                api_base=config.get("api_endpoint") or None,
                messages=[
                    {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
                    {"role": "user", "content": _build_extract_user_prompt(messages)},
                ],
                max_tokens=max_tokens,
                temperature=0.3,
                timeout=60.0,
                num_retries=1,
            )
        except Exception as exc:
            logger.opt(exception=True).warning(
                f"巩固提炼 LLM 调用异常 user_id={user_id}: {exc}"
            )
            return []

        if not result.get("ok"):
            logger.warning(
                f"巩固提炼 LLM 调用失败 user_id={user_id}: {result.get('error', {})}"
            )
            return []

        response_text = result.get("response", "") or ""
        extracted = _extract_json_array(response_text)
        if not extracted:
            logger.debug(
                f"巩固提炼未提取到高价值信息 user_id={user_id} messages={len(messages)}"
            )
        return extracted

    return _callback

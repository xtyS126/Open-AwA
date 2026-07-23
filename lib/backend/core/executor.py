"""
核心执行编排模块，负责 Agent 主流程中的理解、规划、执行、反馈或记录能力。
这些文件决定了用户请求在内部被如何拆解、编排以及最终落地执行。
"""

import asyncio
import hashlib
import json
import re
import time
import urllib.parse
from collections import OrderedDict
from typing import Awaitable, Dict, Any, Optional, Callable, List, Tuple

import httpx
from loguru import logger
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from config.logging import generate_request_id, get_request_id, sanitize_for_logging
from config.settings import settings
from core.metrics import record_model_service_metric, record_tool_execution_metric
from core.litellm_adapter import (
    build_standard_error,
    litellm_chat_completion,
    litellm_chat_completion_stream,
)
from core.tool_use_context import ToolUseContext, coerce_tool_context
from billing.token_counter import (
    TokenBreakdown,
    count_from_stream,
    count_from_usage,
)
from memory.experience_manager import ExperienceManager
from mcp.manager import MCPManager
from soul.profile import OnionProfile

# tool_result 在序列化后允许的最大字符数，超出部分将被截断。
# 防止 plugin_/mcp_/task_ 等无内置截断的工具返回超大结果，导致 messages 列表无限膨胀。
MAX_TOOL_RESULT_CHARS = 8_000

# tool_events 中每个事件 result 字段的最大字符数（前端展示用）。
MAX_TOOL_EVENT_RESULT_CHARS = 2_000


def resolve_max_tool_call_rounds(context: Dict[str, Any]) -> int:
    """解析工具调用回环上限，默认从 settings 读取，上限 100 轮。"""
    from config.settings import settings
    raw_value = context.get("max_tool_call_rounds")
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return settings.MAX_TOOL_CALL_ROUNDS
    return max(1, min(100, value))


def validate_parameters_against_schema(
    parameters: Dict[str, Any],
    schema: Optional[Dict[str, Any]],
    tool_name: str,
) -> Optional[str]:
    """
    校验工具调用参数是否匹配其声明的 JSON Schema。
    返回 None 表示校验通过，返回字符串表示错误信息。
    """
    if not schema or not isinstance(schema, dict):
        return None

    properties = schema.get("properties", {})
    required = schema.get("required", [])
    param_type = schema.get("type", "object")

    # 校验 type（只校验 object 类型）
    if param_type != "object":
        return None

    # 检查必填参数
    for field in required:
        if field not in parameters or parameters[field] is None:
            return f"缺少必填参数: {field}"

    # 检查参数类型（基础类型校验）
    for key, value in parameters.items():
        field_schema = properties.get(key)
        if not field_schema or value is None:
            continue
        expected_type = field_schema.get("type", "")
        if expected_type == "string" and not isinstance(value, str):
            return f"参数 {key} 期望类型为 string，实际为 {type(value).__name__}"
        if expected_type == "integer" and not isinstance(value, int):
            return f"参数 {key} 期望类型为 integer，实际为 {type(value).__name__}"
        if expected_type == "number" and not isinstance(value, (int, float)):
            return f"参数 {key} 期望类型为 number，实际为 {type(value).__name__}"
        if expected_type == "boolean" and not isinstance(value, bool):
            return f"参数 {key} 期望类型为 boolean，实际为 {type(value).__name__}"
        if expected_type == "array" and not isinstance(value, (list, tuple)):
            return f"参数 {key} 期望类型为 array，实际为 {type(value).__name__}"
        if expected_type == "object" and not isinstance(value, dict):
            return f"参数 {key} 期望类型为 object，实际为 {type(value).__name__}"

    return None


def _handle_audit_task_result(task: asyncio.Task) -> None:
    """
    检查审计日志后台任务的执行结果。
    审计日志是安全合规关键证据，不能 fire-and-forget 后丢失。
    对取消和异常情况记录告警日志，避免静默失败。
    """
    try:
        if task.cancelled():
            logger.warning("[审计日志] 任务被取消")
            return
        exc = task.exception()
        if exc is not None:
            logger.warning(f"[审计日志] 任务执行失败: {exc}")
            return
        task.result()
    except Exception as e:
        logger.warning(f"[审计日志] 任务执行失败: {e}")


def _load_onion_profile(user_id: str, db: Session) -> Optional[OnionProfile]:
    """
    加载用户 OnionProfile 画像对象，供画像摘要与事实去重共用。

    从 user_profiles 表反序列化 OnionProfile。未建立画像或加载失败时返回 None，
    不阻塞主流程。抽出此方法是避免 _build_profile_context 与 _build_profile_facts_context
    重复执行 load_profile 数据库查询。

    Args:
        user_id: 用户 ID
        db: 数据库 session

    Returns:
        Optional[OnionProfile]: 反序列化后的画像对象；未命中或失败时返回 None
    """
    if not user_id or db is None:
        return None

    try:
        from soul.persistence import load_profile

        return load_profile(db, user_id)
    except SQLAlchemyError as exc:
        logger.bind(user_id=user_id).opt(exception=True).warning(
            f"读取用户画像数据库查询失败: {exc}"
        )
        return None
    except (ImportError, AttributeError, ValueError, TypeError) as exc:
        logger.bind(user_id=user_id).opt(exception=True).warning(
            f"加载用户画像失败: {exc}"
        )
        return None


def _build_profile_context(user_id: str, db: Session) -> str:
    """
    构建 OnionProfile 五层摘要，用于注入 system prompt。

    从 user_profiles 表读取 OnionProfile，按 surface/interest/role/values/core
    五层结构生成简短摘要文本。未建立画像或读取失败时返回空字符串，不阻塞主流程。

    Args:
        user_id: 用户 ID
        db: 数据库 session

    Returns:
        格式化的画像摘要文本，未建立画像时返回空字符串
    """
    profile = _load_onion_profile(user_id, db)
    if profile is None:
        return ""

    parts = ["[用户画像]"]

    # 五层洋葱模型：surface / interest / role / values / core
    layer_labels = {
        "surface": "行为偏好",
        "interest": "兴趣偏好",
        "role": "角色认同",
        "values": "价值观",
        "core": "人格特征",
    }

    for layer_name, label in layer_labels.items():
        layer = getattr(profile, layer_name, None)
        if layer is None:
            continue
        description = getattr(layer, "description", None)
        if description:
            parts.append(f"- {label}: {description}")

    if len(parts) <= 1:
        return ""

    return "\n".join(parts)


def _build_onion_fact_set(onion_profile: Optional[OnionProfile]) -> set:
    """
    遍历 OnionProfile 五层 structured_data，构建 (fact_key, str(fact_value)) 集合。

    用于 ProfileFact 去重：OnionProfile 的 description 本就来自 ProfileFact 拼接，
    若不去重会导致 LLM 上下文中同一事实被注入两次（一次在画像摘要，一次在事实列表）。

    Args:
        onion_profile: 用户 OnionProfile 画像对象，可为 None

    Returns:
        set: 包含 (fact_key, str(fact_value)) 元组的集合；构建失败时返回空集合，
             降级为不去重以保证注入不中断
    """
    if onion_profile is None:
        return set()

    try:
        fact_set: set = set()
        # 五层洋葱模型：surface / interest / role / values / core
        for layer_name in ("surface", "interest", "role", "values", "core"):
            layer = getattr(onion_profile, layer_name, None)
            if layer is None:
                continue
            structured_data = getattr(layer, "structured_data", None)
            if not isinstance(structured_data, dict):
                continue
            for key, value in structured_data.items():
                if key is None:
                    continue
                fact_set.add((str(key), str(value)))
        return fact_set
    except (AttributeError, TypeError) as exc:
        logger.opt(exception=True).warning(
            f"构建 OnionProfile 事实集合失败，降级为不去重: {exc}"
        )
        return set()


def _build_profile_facts_context(
    user_id: str,
    db: Session,
    onion_profile: Optional[OnionProfile] = None,
) -> str:
    """
    构建高置信度 ProfileFact 摘要，用于注入 system prompt。

    从 profile_facts 表读取 confidence >= 0.7 且 is_active 的事实，按置信度
    降序取前 20 条。若同时传入 OnionProfile，会过滤掉已在五层 structured_data
    中表达的事实，避免与画像摘要重复注入。无事实或读取失败时返回空字符串，
    不阻塞主流程。

    Args:
        user_id: 用户 ID
        db: 数据库 session
        onion_profile: 可选的 OnionProfile 对象，用于事实去重；
                       为 None 时保持原行为（不去重）

    Returns:
        格式化的事实摘要文本，无事实时返回空字符串
    """
    if not user_id or db is None:
        return ""

    try:
        from db.models import ProfileFact

        facts = (
            db.query(ProfileFact)
            .filter(
                ProfileFact.user_id == user_id,
                ProfileFact.is_active.is_(True),
                ProfileFact.confidence >= 0.7,
            )
            .order_by(ProfileFact.confidence.desc())
            .limit(20)
            .all()
        )
    except SQLAlchemyError as exc:
        logger.bind(user_id=user_id).opt(exception=True).warning(
            f"读取用户画像事实数据库查询失败: {exc}"
        )
        return ""
    except (ImportError, AttributeError) as exc:
        logger.bind(user_id=user_id).opt(exception=True).warning(
            f"加载 ProfileFact 模型失败: {exc}"
        )
        return ""

    if not facts:
        return ""

    # 构建 OnionProfile 五层 structured_data 的事实集合，用于去重；
    # 构建失败时返回空集合，降级为不去重，保证注入不阻塞
    onion_fact_set = _build_onion_fact_set(onion_profile)

    parts = ["[用户画像事实]"]
    for fact in facts:
        fact_key = getattr(fact, "fact_key", "")
        fact_value = getattr(fact, "fact_value", "")
        confidence = getattr(fact, "confidence", 0.0)
        if not fact_key or not fact_value:
            continue
        # 去重：跳过已在 OnionProfile 五层 structured_data 中表达的事实
        if (fact_key, str(fact_value)) in onion_fact_set:
            continue
        parts.append(f"- {fact_key}: {fact_value} (置信度: {float(confidence):.0%})")

    if len(parts) <= 1:
        return ""

    return "\n".join(parts)


class ExecutionLayer:
    """
    封装与ExecutionLayer相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(self):
        """
        初始化执行层：注册默认供应商端点映射、API Key 字段映射、
        工具执行幂等缓存（LRU，上限由 settings.TOOL_EXECUTION_CACHE_SIZE 控制）。
        """
        self.tools = {}
        self.llm_api_url = None
        self.llm_api_key = None
        self.default_provider_endpoints = {
            "openai": "https://api.openai.com/v1/chat/completions",
            "anthropic": "https://api.anthropic.com/v1/messages",
            "deepseek": "https://api.deepseek.com/v1/chat/completions",
            "google": "https://generativelanguage.googleapis.com/v1beta/models",
            "alibaba": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            "moonshot": "https://api.moonshot.cn/v1/chat/completions",
            "zhipu": "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        }
        self.provider_api_key_fields = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY"
        }
        self._tool_execution_cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        from config.settings import settings as _exec_settings
        self._max_tool_execution_cache = _exec_settings.TOOL_EXECUTION_CACHE_SIZE
        logger.info("ExecutionLayer initialized")

    def configure_llm(self, api_url: str, api_key: Optional[str] = None):
        """
        配置执行层的 LLM API 连接参数（端点 URL 和 API Key）。
        可用于在运行时动态切换后端模型服务。
        """
        self.llm_api_url = api_url
        self.llm_api_key = api_key
        logger.info(f"LLM API configured: {api_url}")

    def register_tool(self, name: str, tool_func: Callable[..., Any]):
        """
        注册一个命名工具到执行层的工具注册表，供 execute_step 按 action 名称分发调用。
        """
        self.tools[name] = tool_func
        logger.debug(f"Registered execution tool: {name}")

    def _build_error(self, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        构建统一的错误响应字典，自动注入当前请求的 request_id。
        """
        return build_standard_error(
            code=code,
            message=message,
            request_id=get_request_id(),
            details=details,
        )

    def _sanitize_api_endpoint(self, endpoint: Optional[str]) -> Optional[str]:
        """
        对请求端点中的敏感查询参数进行脱敏，避免日志和错误响应泄露密钥。
        """
        normalized = str(endpoint or "").strip()
        if not normalized:
            return endpoint

        parsed = urllib.parse.urlsplit(normalized)
        if not parsed.query:
            return normalized

        redacted_query = urllib.parse.urlencode([
            (
                key,
                "***" if any(marker in key.lower() for marker in ("key", "token", "secret", "auth")) else value,
            )
            for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        ])
        return urllib.parse.urlunsplit(parsed._replace(query=redacted_query))

    def _sanitize_text_excerpt(self, value: Optional[str], limit: int = 200) -> str:
        """
        对返回文本或异常原因进行长度截断与常见敏感片段脱敏。
        """
        excerpt = str(value or "")[:limit]
        excerpt = re.sub(r'(?i)(bearer\s+)[a-z0-9._\-]+', r'\1***', excerpt)
        excerpt = re.sub(
            r'(?i)(api[_-]?key|token|access[_-]?token|refresh[_-]?token|secret)("?\s*[:=]\s*"?)([^"\s,;&]+)',
            r'\1\2***',
            excerpt,
        )
        return excerpt

    @staticmethod
    def build_assistant_tool_call_message(
        content: Optional[str],
        reasoning_content: Optional[str] = None,
        tool_calls: Optional[list[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        构造发回模型的 assistant 工具调用消息。

        某些开启思考模式的模型在 tool call 之后继续续写时，
        要求把上一轮 assistant 的 `reasoning_content` 原样回传。
        """
        if tool_calls is not None and not isinstance(tool_calls, list):
            raise ValueError("tool_calls must be a list")

        if reasoning_content is not None and not isinstance(reasoning_content, str):
            reasoning_content = str(reasoning_content)

        assistant_message: Dict[str, Any] = {
            "role": "assistant",
            "content": content or None,
        }
        if reasoning_content:
            assistant_message["reasoning_content"] = reasoning_content
        if tool_calls:
            assistant_message["tool_calls"] = tool_calls
        return assistant_message

    def _validate_step_params(self, action: str, step: Dict[str, Any]) -> Optional[str]:
        """
        校验步骤参数是否完整有效。
        返回 None 表示通过，返回字符串表示错误信息。
        """
        action_schemas = {
            "read_files": {
                "param_key": "files",
                "param_aliases": (),
                "param_type": list,
                "label": "文件路径列表",
            },
            "execute_command": {
                "param_key": "command",
                "param_aliases": (),
                "param_type": str,
                "label": "命令",
            },
            "llm_generate": {
                "param_key": "prompt",
                "param_aliases": ("task",),
                "param_type": str,
                "label": "提示词",
            },
            "llm_query": {
                "param_key": "prompt",
                "param_aliases": ("query",),
                "param_type": str,
                "label": "查询提示词",
            },
            "llm_explain": {
                "param_key": "prompt",
                "param_aliases": ("target",),
                "param_type": str,
                "label": "解释提示词",
            },
            "llm_chat": {
                "param_key": "message",
                "param_aliases": (),
                "param_type": str,
                "label": "聊天消息",
            },
        }

        schema = action_schemas.get(action)
        if not schema:
            return None

        param_key = schema["param_key"]
        param_value = self._resolve_step_param(
            step,
            param_key,
            *schema.get("param_aliases", ()),
        )

        if param_value is None or param_value == "":
            return f"缺少必填参数 '{param_key}' ({schema['label']})"

        if schema["param_type"] is list and not isinstance(param_value, list):
            return f"参数 '{param_key}' 应为 {schema['param_type'].__name__} 类型，实际为 {type(param_value).__name__}"

        if schema["param_type"] is str and not isinstance(param_value, str):
            return f"参数 '{param_key}' 应为 {schema['param_type'].__name__} 类型，实际为 {type(param_value).__name__}"

        return None

    @staticmethod
    def _resolve_step_param(step: Dict[str, Any], *param_keys: str) -> Any:
        """统一从步骤根字段或 parameters 中解析参数，并兼容历史别名。"""
        parameters = step.get("parameters")
        for param_key in param_keys:
            if not param_key:
                continue
            direct_value = step.get(param_key)
            if direct_value is not None and direct_value != "":
                return direct_value
            if isinstance(parameters, dict):
                nested_value = parameters.get(param_key)
                if nested_value is not None and nested_value != "":
                    return nested_value
        return None

    def _build_tool_idempotency_key(self, step: Dict[str, Any], context: Dict[str, Any]) -> str:
        """构建工具执行的幂等键，如果调用方已显式传入幂等键，则优先复用该值。"""

        explicit_key = str(step.get("idempotency_key") or context.get("idempotency_key") or "").strip()
        if explicit_key:
            return explicit_key

        fingerprint_source = {
            "session_id": context.get("session_id"),
            "user_id": context.get("user_id"),
            "action": step.get("action"),
            "step": step,
        }
        serialized = json.dumps(fingerprint_source, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _get_cached_tool_result(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        """
        读取已缓存的工具执行结果，避免同一幂等键重复触发副作用。
        """

        cached = self._tool_execution_cache.get(idempotency_key)
        if not isinstance(cached, dict):
            return None
        cloned = dict(cached)
        cloned["idempotent_replay"] = True
        return cloned

    def _cache_tool_result(self, idempotency_key: str, result: Dict[str, Any]) -> None:
        """
        缓存工具执行结果，并控制缓存上限，防止内存持续增长。
        使用 OrderedDict 实现 O(1) 的 LRU 淘汰。
        """

        # 若已存在则先移除，重新插入到末尾以标记为最近使用
        if idempotency_key in self._tool_execution_cache:
            self._tool_execution_cache.move_to_end(idempotency_key)
        self._tool_execution_cache[idempotency_key] = dict(result)

        while len(self._tool_execution_cache) > self._max_tool_execution_cache:
            self._tool_execution_cache.popitem(last=False)

    def _extract_response_text(self, response_data: Dict[str, Any]) -> str:
        """
        从不同供应商的非流式响应中统一提取文本内容。
        支持 OpenAI choices[0].message.content、Anthropic content blocks、
        Google Gemini candidates[0].content.parts 三种格式。
        """
        if "response" in response_data and response_data["response"] is not None:
            return str(response_data["response"])
        if "content" in response_data and response_data["content"] is not None:
            return str(response_data["content"])

        choices = response_data.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                message = first_choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        return content
                    if isinstance(content, list):
                        parts = []
                        for item in content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                text = item.get("text")
                                if isinstance(text, str):
                                    parts.append(text)
                        if parts:
                            return "\n".join(parts)

                text = first_choice.get("text")
                if isinstance(text, str):
                    return text

        candidates = response_data.get("candidates")
        if isinstance(candidates, list) and candidates:
            first_candidate = candidates[0]
            if isinstance(first_candidate, dict):
                content = first_candidate.get("content")
                if isinstance(content, dict):
                    parts = content.get("parts")
                    if isinstance(parts, list):
                        texts = []
                        for part in parts:
                            if isinstance(part, dict) and isinstance(part.get("text"), str):
                                texts.append(part["text"])
                        if texts:
                            return "\n".join(texts)

        return ""

    def _resolve_max_tokens(self, resolved: Dict[str, Any]) -> int:
        """
        统一解析模型请求使用的 max_tokens。
        仅当配置值为 None 时回退到默认值，保留 0 等显式配置。
        """
        max_tokens = resolved.get("max_tokens")
        if max_tokens is None:
            return 8192
        return max_tokens

    def _build_agent_capability_system_prompt(self, context: Dict[str, Any]) -> str:
        """
        基于 Agent 注入的运行态能力摘要生成系统提示，避免模型把自己误判成纯文本聊天机器人。
        """
        capabilities = context.get("agent_capabilities")
        if not isinstance(capabilities, dict):
            return ""

        lines = [
            "你是 Open-AwA 平台中的 AI Agent，不是孤立的纯文本聊天模型。",
            "回答关于自身能力的问题时，必须以当前运行态能力清单为准。",
            "不要笼统声称自己不能调用 MCP、技能或插件；要区分平台是否支持、当前会话是否启用、当前是否已有可用工具。",
        ]

        skills_enabled = bool(capabilities.get("skills_enabled", False))
        skills = capabilities.get("skills") if isinstance(capabilities.get("skills"), list) else []
        if skills_enabled:
            if skills:
                lines.append("当前会话可用技能：")
                for skill in skills[:12]:
                    if not isinstance(skill, dict):
                        continue
                    lines.append(
                        f"- 技能 {skill.get('name', '')}: {skill.get('description', '')}"
                    )
            else:
                lines.append("当前会话未发现可用技能。")
        else:
            lines.append("当前会话已关闭技能自动调度。")

        plugins_enabled = bool(capabilities.get("plugins_enabled", False))
        plugins = capabilities.get("plugins") if isinstance(capabilities.get("plugins"), list) else []
        if plugins_enabled:
            if plugins:
                lines.append("当前会话可用插件：")
                for plugin in plugins[:12]:
                    if not isinstance(plugin, dict):
                        continue
                    tools = plugin.get("tools") if isinstance(plugin.get("tools"), list) else []
                    tool_names = [
                        str(tool.get("name", "")).strip()
                        for tool in tools
                        if isinstance(tool, dict) and str(tool.get("name", "")).strip()
                    ]
                    tool_text = "、".join(tool_names) if tool_names else "无显式工具"
                    lines.append(
                        f"- 插件 {plugin.get('name', '')}: {plugin.get('description', '')}。工具: {tool_text}。如需了解参数，优先查看 help 工具。"
                    )
            else:
                lines.append("当前会话未发现可用插件。")
        else:
            lines.append("当前会话已关闭插件自动调度。")

        configured_model_catalog = (
            capabilities.get("configured_models")
            if isinstance(capabilities.get("configured_models"), dict)
            else {}
        )
        configured_model_entries = (
            configured_model_catalog.get("entries")
            if isinstance(configured_model_catalog.get("entries"), list)
            else []
        )
        if configured_model_entries:
            lines.append("当前可用于派生子代理的已配置模型：")
            for entry in configured_model_entries[:12]:
                if not isinstance(entry, dict):
                    continue
                label = str(entry.get("label", "")).strip()
                if not label:
                    continue
                lines.append(f"- {label}")
            lines.append(
                "调用 task_spawn_agent 时，优先同时传 provider 和 model；也支持把 model 写成 provider:model。仅传 provider 时，系统会自动选用该 provider 的默认或已选模型。"
            )
        else:
            lines.append("当前未提供已配置模型目录；派生子代理时若省略 provider/model，将回退到系统默认模型配置。")

        mcp_capabilities = capabilities.get("mcp") if isinstance(capabilities.get("mcp"), dict) else {}
        if mcp_capabilities.get("platform_supported", False):
            connected_servers = (
                mcp_capabilities.get("connected_servers")
                if isinstance(mcp_capabilities.get("connected_servers"), list)
                else []
            )
            mcp_tools = mcp_capabilities.get("tools") if isinstance(mcp_capabilities.get("tools"), list) else []

            if mcp_tools:
                lines.append("平台当前已连接的 MCP 工具：")
                for tool in mcp_tools[:12]:
                    if not isinstance(tool, dict):
                        continue
                    lines.append(
                        f"- MCP {tool.get('server_name', tool.get('server_id', ''))}/{tool.get('name', '')}: {tool.get('description', '')}"
                    )
            elif connected_servers:
                server_names = [
                    str(server.get("name", "")).strip()
                    for server in connected_servers[:12]
                    if isinstance(server, dict) and str(server.get("name", "")).strip()
                ]
                if server_names:
                    lines.append(
                        "平台已连接 MCP Server，但当前没有可直接说明的 MCP 工具摘要：" + "、".join(server_names)
                    )
                else:
                    lines.append("平台已连接 MCP Server，但当前没有可直接说明的 MCP 工具摘要。")
            else:
                lines.append("平台支持 MCP Server 管理与工具发现，但当前没有已连接的 MCP Server。")

            if not mcp_capabilities.get("chat_dispatch_enabled", False):
                lines.append(
                    "注意：当前聊天链路未直接暴露自动 MCP 调度。不要谎称已经调用了某个 MCP 工具；如果用户询问能力，应说明平台支持 MCP，但本轮会话是否可直接调用取决于已连接 Server 和执行链路配置。"
                )

        lines.extend([
            "规则：",
            "1. 不要捏造已经执行过的技能、插件或 MCP 调用。",
            "2. 不要回答“我没有调用技能/插件/MCP 的能力”这类绝对否定句。",
            "3. 当某类能力当前不可用时，要说明是当前会话未启用、未连接或未暴露，而不是说平台完全不支持。",
        ])

        return "\n".join(lines)

    def _normalize_subagent_model_selection(
        self,
        provider: Any,
        model: Any,
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """
        规范化子代理模型选择参数，兼容 provider:model 单字段格式。
        """
        normalized_provider = str(provider or "").strip().lower() or None
        normalized_model = str(model or "").strip() or None
        if not normalized_model or normalized_provider:
            return normalized_provider, normalized_model

        provider_candidate = None
        model_candidate = None
        if ":" in normalized_model:
            raw_provider, raw_model = normalized_model.split(":", 1)
            provider_candidate = raw_provider.strip().lower()
            model_candidate = raw_model.strip()
        elif "/" in normalized_model:
            raw_provider, raw_model = normalized_model.split("/", 1)
            known_providers = set(self.default_provider_endpoints) | set(self.provider_api_key_fields) | {"ollama", "qwen"}
            if raw_provider.strip().lower() in known_providers:
                provider_candidate = raw_provider.strip().lower()
                model_candidate = raw_model.strip()

        if provider_candidate and model_candidate:
            return provider_candidate, model_candidate

        catalog = self._get_configured_model_catalog(context or {})
        if normalized_model and not normalized_provider:
            matched_provider = self._find_provider_for_model(
                normalized_model,
                catalog,
                preferred_provider=str((context or {}).get("provider", "") or "").strip().lower() or None,
            )
            if matched_provider:
                return matched_provider, normalized_model

        return normalized_provider, normalized_model

    @staticmethod
    def _get_configured_model_catalog(context: Dict[str, Any]) -> Dict[str, Any]:
        """
        从上下文中提取已配置模型目录。
        """
        catalog = context.get("configured_model_catalog")
        if isinstance(catalog, dict):
            return catalog

        capabilities = context.get("agent_capabilities")
        if isinstance(capabilities, dict):
            nested_catalog = capabilities.get("configured_models")
            if isinstance(nested_catalog, dict):
                return nested_catalog

        return {}

    @staticmethod
    def _pick_catalog_model_for_provider(provider: Optional[str], catalog: Dict[str, Any]) -> Optional[str]:
        """
        从模型目录中挑选指定 provider 的首个可用模型。
        """
        normalized_provider = str(provider or "").strip().lower()
        if not normalized_provider:
            return None

        providers = catalog.get("providers") if isinstance(catalog.get("providers"), list) else []
        for item in providers:
            if not isinstance(item, dict):
                continue
            if str(item.get("provider", "")).strip().lower() != normalized_provider:
                continue
            models = item.get("models") if isinstance(item.get("models"), list) else []
            for model in models:
                normalized_model = str(model or "").strip()
                if normalized_model:
                    return normalized_model

        entries = catalog.get("entries") if isinstance(catalog.get("entries"), list) else []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("provider", "")).strip().lower() != normalized_provider:
                continue
            normalized_model = str(entry.get("model", "")).strip()
            if normalized_model:
                return normalized_model

        return None

    @staticmethod
    def _find_provider_for_model(
        model: Optional[str],
        catalog: Dict[str, Any],
        preferred_provider: Optional[str] = None,
    ) -> Optional[str]:
        """
        在模型目录中查找模型所属 provider。
        若存在多个候选，则优先返回 preferred_provider。
        """
        normalized_model = str(model or "").strip()
        if not normalized_model:
            return None

        matches: list[str] = []
        entries = catalog.get("entries") if isinstance(catalog.get("entries"), list) else []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("model", "")).strip() != normalized_model:
                continue
            provider = str(entry.get("provider", "")).strip().lower()
            if provider and provider not in matches:
                matches.append(provider)

        if preferred_provider and preferred_provider in matches:
            return preferred_provider
        if len(matches) == 1:
            return matches[0]
        return None

    def _resolve_subagent_model_selection(
        self,
        context: Dict[str, Any],
        provider: Any,
        model: Any,
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """
        解析子代理的最终 provider/model。
        若无法确定，返回明确错误信息而不是静默回退。
        """
        catalog = self._get_configured_model_catalog(context)
        provider, model = self._normalize_subagent_model_selection(provider, model, context)
        current_provider, current_model = self._normalize_subagent_model_selection(
            context.get("provider"),
            context.get("model"),
            context,
        )

        if not provider and model:
            provider = self._find_provider_for_model(model, catalog, preferred_provider=current_provider)

        if not provider and current_provider:
            provider = current_provider
        if not model and current_model:
            model = current_model

        if provider and not model:
            model = self._pick_catalog_model_for_provider(provider, catalog)

        if not provider or not model:
            resolved = self._resolve_llm_configuration(
                {
                    **context,
                    "provider": provider or current_provider or context.get("provider"),
                    "model": model,
                }
            )
            if resolved.get("ok"):
                resolved_provider = str(resolved.get("provider", "")).strip().lower() or None
                resolved_model = str(resolved.get("model", "")).strip() or None
                if not provider:
                    provider = resolved_provider
                if not model:
                    model = resolved_model

        if not provider and model:
            provider = self._find_provider_for_model(model, catalog, preferred_provider=current_provider)
        if provider and not model:
            model = self._pick_catalog_model_for_provider(provider, catalog)

        if not provider or not model:
            return None, None, "未能解析子代理模型，请指定 provider/model 参数或确保主会话已配置模型"

        return provider, model, None

    async def _consume_foreground_subagent_stream(
        self,
        stream: Any,
        tool_name: str,
        on_subagent_event: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """
        消费前台子代理生成器，实时转发子代理事件，并返回最终摘要结果。
        """
        agent_id: Optional[str] = None
        agent_type: Optional[str] = None
        summary = ""
        state = "completed"

        try:
            async for chunk in stream:
                if not isinstance(chunk, dict):
                    continue

                chunk_type = str(chunk.get("type") or "").strip()
                if chunk_type in {"subagent_start", "agent_message", "subagent_stop"}:
                    agent_id = str(chunk.get("agent_id") or agent_id or "").strip() or agent_id
                    agent_type = str(chunk.get("agent_type") or agent_type or "").strip() or agent_type
                    if chunk_type == "subagent_stop":
                        summary = str(chunk.get("summary") or summary or "").strip()
                        state = str(chunk.get("state") or state or "completed").strip().lower() or "completed"
                    if callable(on_subagent_event):
                        await on_subagent_event(chunk)
                    continue

                if chunk_type == "error":
                    state = "failed"
                    error_message = str(chunk.get("error") or "子代理执行失败").strip() or "子代理执行失败"
                    summary = summary or error_message
                    # 转发错误事件到前端，确保实时可见
                    if callable(on_subagent_event):
                        await on_subagent_event(chunk)

            if not agent_id:
                return {
                    "ok": False,
                    "error": "前台子代理未返回可追踪的 agent_id",
                    "tool_name": tool_name,
                }

            result_payload = {
                "agent_id": agent_id,
                "agent_type": agent_type,
                "run_mode": "foreground",
                "status": state,
                "summary": summary,
                "message": summary or ("子代理执行完成" if state == "completed" else "子代理执行失败"),
            }

            logger.bind(
                module="executor",
                event="subagent_foreground_completed",
                agent_id=agent_id,
                agent_type=agent_type,
                state=state,
            ).info(f"前台子代理执行结束: {agent_id}")

            if state in {"failed", "error", "stopped", "timeout"}:
                return {
                    "ok": False,
                    "error": summary or "子代理执行失败",
                    "result": result_payload,
                    "tool_name": tool_name,
                }

            return {
                "ok": True,
                "result": result_payload,
                "tool_name": tool_name,
            }
        finally:
            aclose = getattr(stream, "aclose", None)
            if callable(aclose):
                await aclose()

    def _pick_effective_model(
        self,
        provider: str,
        model: str,
        selected_models: Optional[list[str]] = None,
    ) -> str:
        """
        为 provider 挑选可用模型：若传入模型名为空，从 selected_models 中选。
        """
        normalized_provider = str(provider or "").strip().lower()
        normalized_model = str(model or "").strip()
        candidates = [str(item or "").strip() for item in (selected_models or []) if str(item or "").strip()]

        if not normalized_model:
            if normalized_provider == "deepseek":
                if "deepseek-chat" in candidates:
                    return "deepseek-chat"
                if "deepseek-reasoner" in candidates:
                    return "deepseek-reasoner"
                return "deepseek-chat"
            if candidates:
                return candidates[0]

        return normalized_model

    def _resolve_llm_configuration(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        从上下文中解析完整的 LLM 配置（provider/model/api_key/api_endpoint）。
        优先级：DB 精确匹配 → DB 默认配置 → 全局 settings → 内置供应商端点，
        任一环节缺失则返回包含标准错误对象的失败结果。
        """
        from config.settings import settings

        provider = context.get("provider")
        model = context.get("model")
        db = context.get("db")
        config = None

        pricing_manager = None
        if db:
            try:
                from billing.pricing_manager import PricingManager
                pricing_manager = PricingManager(db)
                if provider and model:
                    config = pricing_manager.get_configuration_by_provider_model(provider, model)
                if not config and provider:
                    # 未找到精确的 provider+model 配置，回退到该 provider 的默认配置
                    config = pricing_manager.get_default_provider_configuration(provider)
                if not config:
                    config = pricing_manager.get_default_configuration()
            except Exception as e:
                logger.opt(exception=True).error(
                    f"从数据库解析模型配置失败: {e}"
                )

        if config:
            provider = provider or config.provider
            model = model or config.model
            # 从加密存储中解密 API 密钥
            raw_key = config.api_key or ""
            if raw_key:
                # 旧算法密文已失效（SECRET_KEY 拆分后无法解密），提前返回明确错误，
                # 避免被 decrypt_secret_value 静默吞掉导致空头请求 LLM 网关
                if raw_key.startswith("enc:"):
                    return {
                        "ok": False,
                        "error": self._build_error(
                            "llm_api_key_stale",
                            "API Key 已失效，请在设置页重新录入",
                            {"provider": provider, "model": model}
                        )
                    }
                from config.security import decrypt_secret_value
                api_key = decrypt_secret_value(raw_key)
                # raw_key 非空但解密结果为空，说明密钥损坏或 SECRET_KEY 变更，必须向上报告
                if not api_key:
                    return {
                        "ok": False,
                        "error": self._build_error(
                            "llm_api_key_decrypt_failed",
                            "API Key 解密失败，可能因 SECRET_KEY 变更导致密钥损坏",
                            {
                                "provider": provider,
                                "model": model,
                            }
                        )
                    }
            else:
                # 当 ModelConfiguration 中没有 API Key 时，尝试从 ProviderCredential 表读取
                api_key = None
                try:
                    cred = pricing_manager.get_provider_credential(provider)
                    if cred and cred.api_key:
                        # 旧算法密文已失效，提前返回明确错误，避免被 decrypt 静默吞掉
                        if cred.api_key.startswith("enc:"):
                            return {
                                "ok": False,
                                "error": self._build_error(
                                    "llm_api_key_stale",
                                    "API Key 已失效，请在设置页重新录入",
                                    {"provider": provider, "model": model}
                                )
                            }
                        from config.security import decrypt_secret_value
                        api_key = decrypt_secret_value(cred.api_key)
                        if api_key:
                            logger.info(f"已从 ProviderCredential 表为 {provider} 解析 API Key")
                        else:
                            # 凭据存在但解密失败，密钥损坏，必须向上报告
                            return {
                                "ok": False,
                                "error": self._build_error(
                                    "llm_api_key_decrypt_failed",
                                    "ProviderCredential 中的 API Key 解密失败，可能因 SECRET_KEY 变更导致密钥损坏",
                                    {
                                        "provider": provider,
                                        "model": model,
                                    }
                                )
                            }
                except Exception as e:
                    logger.warning(f"从 ProviderCredential 表解析 API Key 失败: {e}")
            api_endpoint = config.api_endpoint
            max_tokens = getattr(config, "max_tokens_limit", None)
            selected_models: list[str] = []
            try:
                selected_models = PricingManager.parse_selected_models(getattr(config, "selected_models", None))
            except Exception as e:
                logger.warning(f"解析 selected_models 失败，已降级为空列表: {e}")
                selected_models = []
            model = self._pick_effective_model(provider, model, selected_models)
        else:
            api_key = None
            api_endpoint = None
            max_tokens = None

        provider = (provider or "").strip().lower()
        model = (model or "").strip()

        if not provider:
            return {
                "ok": False,
                "error": self._build_error(
                    "llm_provider_missing",
                    "未配置可用的模型提供商",
                    {
                        "provider": provider,
                        "model": model
                    }
                )
            }

        if not model:
            return {
                "ok": False,
                "error": self._build_error(
                    "llm_model_missing",
                    "未配置可用的模型名称",
                    {
                        "provider": provider,
                        "model": model
                    }
                )
            }

        if not api_endpoint:
            if self.llm_api_url:
                api_endpoint = self.llm_api_url
            else:
                api_endpoint = self.default_provider_endpoints.get(provider)

        try:
            api_endpoint = PricingManager.build_provider_api_endpoint(provider, api_endpoint, "chat")
        except Exception as e:
            logger.error(f"Failed to normalize provider endpoint: {e}")

        if not api_endpoint:
            return {
                "ok": False,
                "error": self._build_error(
                    "llm_endpoint_missing",
                    "未配置模型服务地址",
                    {
                        "provider": provider,
                        "model": model
                    }
                )
            }

        if not api_key:
            if self.llm_api_key:
                api_key = self.llm_api_key
            else:
                field_name = self.provider_api_key_fields.get(provider)
                if field_name:
                    secret = getattr(settings, field_name, None)
                    # SecretStr 类型需要调用 get_secret_value() 获取明文
                    if secret is not None:
                        api_key = secret.get_secret_value() if hasattr(secret, 'get_secret_value') else secret

        if not api_key:
            return {
                "ok": False,
                "error": self._build_error(
                    "llm_api_key_missing",
                    "未配置模型 API Key",
                    {
                        "provider": provider,
                        "model": model,
                        "api_endpoint": api_endpoint
                    }
                )
            }

        return {
            "ok": True,
            "provider": provider,
            "model": model,
            "api_endpoint": api_endpoint,
            "api_key": api_key,
            "max_tokens": max_tokens,
            "request_id": context.get("request_id") or get_request_id(),
            "client_version": context.get("client_version"),
        }

    def _build_auto_execution_system_prompt(self, auto_execution_results: Dict[str, Any]) -> str:
        lines = []
        skills = auto_execution_results.get("skills", []) or []
        plugins = auto_execution_results.get("plugins", []) or []

        if not skills and not plugins:
            return ""

        if skills:
            lines.append("平台已在生成当前回答前自动执行了部分技能：")
            for skill in skills:
                lines.append(f"- {skill.get('skill_name', 'unknown')}")
            lines.append("")

        # 处理插件结果
        for plugin in plugins:
            plugin_name = plugin.get("plugin_name", "unknown")
            tool = plugin.get("tool", "unknown")
            result = plugin.get("result", {}) or {}

            if result.get("summary_mode") == "current_model":
                lines.append(f"平台已在生成当前回答前自动执行了插件 {plugin_name}/{tool}：")
                lines.append("")

                if result.get("summary_role"):
                    lines.append(result["summary_role"])

                if result.get("summary_guidance"):
                    lines.append(result["summary_guidance"])

                if result.get("summary_output_rules"):
                    lines.append("")
                    lines.append("输出规则：")
                    for rule in result["summary_output_rules"]:
                        lines.append(f"- {rule}")

                if result.get("summary_priority_rules"):
                    lines.append("")
                    lines.append("优先级规则：")
                    for rule in result["summary_priority_rules"]:
                        lines.append(f"- {rule}")

                if result.get("summary_context"):
                    lines.append("")
                    lines.append(result["summary_context"])

                if result.get("digest"):
                    lines.append("")
                    lines.append("推文摘要：")
                    for item in result["digest"]:
                        lines.append(f"- {item}")

                if result.get("top_tweets"):
                    lines.append("")
                    lines.append("高价值候选推文：")
                    for tweet in result["top_tweets"]:
                        lines.append(f"- {tweet.get('text', '')}")

                lines.append("")
                lines.append("不要输出 JSON、代码块或额外调度指令，直接基于以上素材回答用户。")
            else:
                if not lines:
                    lines.append("平台已在生成当前回答前自动执行了部分技能或插件：")
                lines.append(f"- {plugin_name}/{tool}")

        if lines and "不要输出 JSON" not in lines[-1]:
            lines.append("")
            lines.append("不要再输出任何插件、技能或 MCP 调用 JSON。")

        return "\n".join(lines).strip()

    def _build_relevant_memories_system_prompt(self, context: Dict[str, Any]) -> str:
        """
        将 agent 层检索到的相关长期记忆格式化为 system prompt 片段。
        仅在 context["vector_retrieved_memories"] 非空时生成内容，否则返回空串。
        记忆来源：agent._retrieve_relevant_memories（混合检索关键词 + 向量）。
        """
        memories = context.get("vector_retrieved_memories")
        if not isinstance(memories, list) or not memories:
            return ""

        lines = [
            "以下是与当前用户请求可能相关的长期记忆，回答时可参考但不要逐字复述：",
        ]
        for idx, memory in enumerate(memories, start=1):
            if not isinstance(memory, dict):
                continue
            content = str(memory.get("content", "")).strip()
            if not content:
                continue
            importance = memory.get("importance")
            confidence = memory.get("confidence")
            meta_parts: list[str] = []
            if isinstance(importance, (int, float)):
                meta_parts.append(f"重要度={float(importance):.2f}")
            if isinstance(confidence, (int, float)):
                meta_parts.append(f"置信度={float(confidence):.2f}")
            meta_text = f"（{', '.join(meta_parts)}）" if meta_parts else ""
            lines.append(f"{idx}. {content}{meta_text}")

        return "\n".join(lines)

    def _build_messages_with_history(self, prompt: str, context: Dict[str, Any]) -> list:
        """
        从上下文中提取对话历史，构建包含历史消息的 messages 列表。
        对话历史由 agent 层在调用前注入到 context["conversation_history"] 中。
        支持多模态内容：若 context 含 _multimodal_content 则使用数组格式。
        同时注入 context["vector_retrieved_memories"] 作为相关长期记忆 system 片段，
        避免 agent 层检索到的记忆仅用于统计计数而未参与 LLM 上下文。
        """
        messages = []
        system_prompt = self._build_agent_capability_system_prompt(context)
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # 注入用户画像（五层 OnionProfile 摘要 + 高置信度 ProfileFact）
        # 放在能力描述之后、长期记忆之前：用户身份是较稳定的上下文，优先级高于请求级记忆
        # 先加载 OnionProfile 对象，再传给 _build_profile_facts_context 用于事实去重，
        # 避免画像摘要（来自 ProfileFact 拼接）与事实列表重复注入同一信息
        user_id = context.get("user_id")
        db = context.get("db")
        onion_profile = _load_onion_profile(user_id, db)
        profile_context = _build_profile_context(user_id, db)
        profile_facts_context = _build_profile_facts_context(
            user_id, db, onion_profile=onion_profile
        )
        if profile_context or profile_facts_context:
            profile_block = "\n\n".join(
                part for part in (profile_context, profile_facts_context) if part
            )
            if profile_block:
                messages.append({"role": "system", "content": profile_block})

        # 注入检索到的相关长期记忆（在能力描述之后、自动执行结果之前，保持语义层级清晰）
        memories_prompt = self._build_relevant_memories_system_prompt(context)
        if memories_prompt:
            messages.append({"role": "system", "content": memories_prompt})

        auto_execution_results = context.get("auto_execution_results")
        if auto_execution_results:
            auto_prompt = self._build_auto_execution_system_prompt(auto_execution_results)
            if auto_prompt:
                messages.append({"role": "system", "content": auto_prompt})

        conversation_history = context.get("conversation_history", [])
        if conversation_history:
            for msg in conversation_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})
        # 始终追加当前用户输入；若有多模态内容则使用数组格式
        multimodal_content = context.get("_multimodal_content")
        if multimodal_content:
            messages.append({"role": "user", "content": multimodal_content})
        else:
            messages.append({"role": "user", "content": prompt})
        return messages

    async def _call_llm_api(self, prompt: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        通过 LiteLLM 统一调用层发起非流式聊天请求。
        支持通过 context["conversation_history"] 注入对话历史。
        """
        record_hook = context.get("_record_hook")
        started_at = time.perf_counter()
        serialized_context = {
            key: value
            for key, value in context.items()
            if key not in {"_record_hook", "db"}
        }
        llm_input_payload = {
            "prompt": prompt,
            "context": serialized_context,
        }

        resolved = await asyncio.to_thread(self._resolve_llm_configuration, context)
        if not resolved.get("ok"):
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            if callable(record_hook):
                record_hook(
                    node_type="llm_call",
                    user_message=context.get("message", prompt),
                    context=context,
                    status="error",
                    error_message=resolved.get("error", {}).get("message"),
                    llm_input=llm_input_payload,
                    llm_output=resolved,
                    execution_duration_ms=duration_ms,
                    metadata={
                        "phase": "resolve_configuration",
                        "error": resolved.get("error"),
                    }
                )
            return resolved

        messages = self._build_messages_with_history(prompt, context)
        llm_input_payload.update({
            "provider": resolved["provider"],
            "model": resolved["model"],
        })

        _tools = context.get("_tools")
        _thinking_params = context.get("_thinking_params")
        step_timeout = context.get("step_timeout", settings.AGENT_STEP_TIMEOUT_SECONDS)
        try:
            result = await asyncio.wait_for(
                litellm_chat_completion(
                    provider=resolved["provider"],
                    model=resolved["model"],
                    messages=messages,
                    api_key=resolved["api_key"],
                    api_base=resolved.get("api_endpoint"),
                    max_tokens=self._resolve_max_tokens(resolved),
                    request_id=resolved.get("request_id"),
                    tools=_tools,
                    thinking_params=_thinking_params,
                ),
                timeout=step_timeout,
            )
        except asyncio.TimeoutError:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            record_model_service_metric(resolved["provider"], "chat", "error", duration_ms)
            logger.bind(
                event="llm_call_timeout",
                module="executor",
                provider=resolved["provider"],
                model=resolved["model"],
                timeout_seconds=step_timeout,
            ).warning(f"LLM 调用超时 ({step_timeout}s)")
            return {
                "ok": False,
                "error": {"message": f"LLM 调用超时 ({step_timeout}s)", "type": "timeout"},
            }

        # 支持 tool_calls 循环：检测到工具调用时自动执行并将结果回传 LLM
        max_rounds = resolve_max_tool_call_rounds(context)
        round_count = 0
        consecutive_errors = 0
        max_consecutive_errors = 3
        tool_events = []

        while round_count < max_rounds:
            tool_calls = result.get("tool_calls")
            if not tool_calls:
                break

            round_count += 1
            assistant_msg = self.build_assistant_tool_call_message(
                content=result.get("response"),
                reasoning_content=result.get("reasoning_content"),
                tool_calls=tool_calls,
            )
            messages.append(assistant_msg)

            _abort = False
            # 使用 StreamingToolExecutor 并发调度工具调用
            # 只读并发安全工具可同时执行，破坏性工具串行执行
            ordered_results = await self._execute_tool_calls_concurrent(
                tool_calls, context
            )
            for tc, exec_result in ordered_results:
                if exec_result.get("ok"):
                    consecutive_errors = 0
                else:
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        logger.bind(
                            event="tool_calls_max_consecutive_errors",
                            module="executor",
                            consecutive_errors=consecutive_errors,
                            threshold=max_consecutive_errors,
                        ).warning(f"工具调用连续失败 {consecutive_errors} 次，终止 tool_calls 循环")
                        _abort = True
                        break
                # 前端展示用结果摘要，截断防止 tool_events 过大
                _raw_result = exec_result.get("result", exec_result.get("error"))
                _result_str = json.dumps(_raw_result, ensure_ascii=False, default=str)
                if len(_result_str) > MAX_TOOL_EVENT_RESULT_CHARS:
                    _result_str = _result_str[:MAX_TOOL_EVENT_RESULT_CHARS] + "..."
                tool_events.append({
                    "name": tc.get("function", {}).get("name", "unknown"),
                    "status": "completed" if exec_result.get("ok") else "error",
                    "result": _result_str,
                })
                tool_message = self._build_tool_message(tc, exec_result)
                messages.append(tool_message)
            if _abort:
                break

            try:
                result = await asyncio.wait_for(
                    litellm_chat_completion(
                        provider=resolved["provider"],
                        model=resolved["model"],
                        messages=messages,
                        api_key=resolved["api_key"],
                        api_base=resolved.get("api_endpoint"),
                        max_tokens=self._resolve_max_tokens(resolved),
                        request_id=resolved.get("request_id"),
                        tools=_tools,
                        thinking_params=_thinking_params,
                    ),
                    timeout=step_timeout,
                )
            except asyncio.TimeoutError:
                logger.bind(
                    event="llm_call_timeout",
                    module="executor",
                    provider=resolved["provider"],
                    model=resolved["model"],
                    timeout_seconds=step_timeout,
                    round=round_count,
                ).warning(f"工具调用循环中 LLM 调用超时 ({step_timeout}s)，第 {round_count} 轮")
                result = {
                    "ok": False,
                    "error": {"message": f"LLM 调用超时 ({step_timeout}s)", "type": "timeout"},
                }

            if not result.get("ok"):
                break

        # 将 tool_events 注入到返回结果中
        if tool_events:
            result["tool_events"] = tool_events

        duration_ms = int((time.perf_counter() - started_at) * 1000)

        if not result.get("ok"):
            record_model_service_metric(resolved["provider"], "chat", "error", duration_ms)
            if callable(record_hook):
                record_hook(
                    node_type="llm_call",
                    user_message=context.get("message", prompt),
                    context=context,
                    status="error",
                    error_message=result.get("error", {}).get("message"),
                    llm_input=llm_input_payload,
                    llm_output=result,
                    execution_duration_ms=duration_ms,
                    metadata={
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                    }
                )
            return result

        record_model_service_metric(resolved["provider"], "chat", "success", duration_ms)

        if callable(record_hook):
            usage = result.get("usage")
            token_breakdown = count_from_usage(usage if isinstance(usage, dict) else None)
            record_hook(
                node_type="llm_call",
                user_message=context.get("message", prompt),
                context=context,
                status="success",
                llm_input=llm_input_payload,
                llm_output=result,
                token_breakdown=token_breakdown,
                llm_tokens_used=token_breakdown.total_tokens,
                execution_duration_ms=duration_ms,
                metadata={
                    "provider": resolved["provider"],
                    "model": resolved["model"],
                }
            )
        return result

    async def _call_llm_api_stream(self, prompt: str, context: Dict[str, Any]):
        """
        通过 LiteLLM 统一调用层发起流式聊天请求。
        支持通过 context["conversation_history"] 注入对话历史。
        向外 yield { "content": "...", "reasoning_content": "..." } 结构。
        """
        record_hook = context.get("_record_hook")
        started_at = time.perf_counter()
        serialized_context = {
            key: value
            for key, value in context.items()
            if key not in {"_record_hook", "db"}
        }

        resolved = await asyncio.to_thread(self._resolve_llm_configuration, context)
        if not resolved.get("ok"):
            yield {"error": resolved.get("error")}
            return

        messages = self._build_messages_with_history(prompt, context)
        tool_messages = context.get("_tool_messages", [])
        if tool_messages:
            messages.extend(tool_messages)
        _tools = context.get("_tools")
        full_content = ""
        full_reasoning = ""
        # 收集流式 chunk 用于后续 token 计数（count_from_stream 会查找 usage 字段）
        stream_chunks: List[Dict[str, Any]] = []

        try:
            _thinking_params = context.get("_thinking_params")
            stream_gen = litellm_chat_completion_stream(
                provider=resolved["provider"],
                model=resolved["model"],
                messages=messages,
                api_key=resolved["api_key"],
                api_base=resolved.get("api_endpoint"),
                max_tokens=self._resolve_max_tokens(resolved),
                request_id=resolved.get("request_id"),
                tools=_tools,
                thinking_params=_thinking_params,
            )

            # 流式整体超时控制：每个 chunk 之间最长等待 STREAM_CHUNK_TIMEOUT_SECONDS
            # 防止 LLM 服务 hang 住但不断开连接导致永久阻塞
            STREAM_CHUNK_TIMEOUT_SECONDS = 120.0
            stream_iter = stream_gen.__aiter__()
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        stream_iter.__anext__(),
                        timeout=STREAM_CHUNK_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    duration_ms = int((time.perf_counter() - started_at) * 1000)
                    record_model_service_metric(resolved["provider"], "chat_stream", "timeout", duration_ms)
                    logger.bind(
                        event="llm_stream_timeout",
                        module="executor",
                        provider=resolved["provider"],
                        model=resolved["model"],
                        timeout_seconds=STREAM_CHUNK_TIMEOUT_SECONDS,
                    ).error(f"流式 LLM 调用超时（{STREAM_CHUNK_TIMEOUT_SECONDS}s 无响应）")
                    yield {
                        "error": {
                            "message": f"流式响应超时（{STREAM_CHUNK_TIMEOUT_SECONDS}s 无数据）",
                            "type": "timeout",
                        }
                    }
                    return
                except StopAsyncIteration:
                    break

                # 收集 chunk 用于后续 token 计数（count_from_stream 查找 usage 字段）
                if isinstance(chunk, dict):
                    stream_chunks.append(chunk)

                # 错误事件直接转发
                if "error" in chunk:
                    duration_ms = int((time.perf_counter() - started_at) * 1000)
                    record_model_service_metric(resolved["provider"], "chat_stream", "error", duration_ms)
                    if callable(record_hook):
                        record_hook(
                            node_type="llm_call",
                            user_message=context.get("message", prompt),
                            context=context,
                            status="error",
                            error_message=chunk["error"].get("message"),
                            llm_input={"prompt": prompt, "context": serialized_context},
                            llm_output=chunk,
                            execution_duration_ms=duration_ms,
                            metadata={
                                "provider": resolved["provider"],
                                "model": resolved["model"],
                                "mode": "stream",
                            }
                        )
                    yield chunk
                    return

                if chunk.get("type") == "tool_calls":
                    yield chunk
                    return

                content = chunk.get("content", "")
                reasoning = chunk.get("reasoning_content", "")
                if content:
                    full_content += content
                if reasoning:
                    full_reasoning += reasoning
                if content or reasoning:
                    yield {"content": content, "reasoning_content": reasoning}

            duration_ms = int((time.perf_counter() - started_at) * 1000)
            record_model_service_metric(resolved["provider"], "chat_stream", "success", duration_ms)

            if callable(record_hook):
                token_breakdown = count_from_stream(stream_chunks)
                record_hook(
                    node_type="llm_call",
                    user_message=context.get("message", prompt),
                    context=context,
                    status="success",
                    llm_input={"prompt": prompt, "context": serialized_context},
                    llm_output={
                        "ok": True,
                        "response": full_content,
                        "reasoning_content": full_reasoning,
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                    },
                    token_breakdown=token_breakdown,
                    llm_tokens_used=token_breakdown.total_tokens,
                    execution_duration_ms=duration_ms,
                    metadata={
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                        "mode": "stream",
                    }
                )

        except Exception as e:
            logger.bind(
                event="llm_stream_error",
                module="executor",
                error_type=type(e).__name__,
                provider=resolved.get("provider"),
                model=resolved.get("model"),
            ).opt(exception=True).error(f"LLM 流式调用异常: {e}")
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            record_model_service_metric(resolved["provider"], "chat_stream", "error", duration_ms)

            output_error = {
                "error": build_standard_error(
                    "model_service_stream_error",
                    "模型流式服务调用出现异常",
                    request_id=resolved.get("request_id"),
                    details={
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                        "reason": str(e),
                    },
                )
            }

            if callable(record_hook):
                record_hook(
                    node_type="llm_call",
                    user_message=context.get("message", prompt),
                    context=context,
                    status="error",
                    error_message=output_error["error"]["message"],
                    llm_input={"prompt": prompt, "context": serialized_context},
                    llm_output=output_error,
                    execution_duration_ms=duration_ms,
                    metadata={
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                        "mode": "stream",
                    }
                )

            yield output_error

    async def _request_user_permission(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        """
        当工具执行因权限不足被拒绝时，通过实时推送队列请求用户授权。
        调用 security 路由的 enqueue_permission_request 将请求推送到前端，
        然后阻塞等待用户回复（once/always/reject）。
        超时后自动返回 "reject"。

        返回:
            str - 用户回复值: "once" / "always" / "reject"
        """
        try:
            from api.routes.security import enqueue_permission_request
        except ImportError:
            logger.bind(
                module="executor",
                event="permission_module_import_failed",
                tool_name=tool_name,
            ).warning("权限请求模块导入失败，默认拒绝")
            return "reject"

        user_id = str(context.get("user_id", ""))
        session_id = str(context.get("session_id", ""))

        if not user_id:
            logger.bind(
                module="executor",
                event="permission_request_no_user",
                tool_name=tool_name,
            ).warning("无法获取用户 ID，默认拒绝权限请求")
            return "reject"

        # 从工具参数中提取资源路径
        resources: list[str] = []
        for key in ("path", "file", "files", "command", "url", "directory"):
            value = tool_args.get(key)
            if isinstance(value, str) and value:
                resources.append(value)
            elif isinstance(value, list):
                resources.extend(str(v) for v in value if v)

        if not resources:
            resources = [tool_name]

        # 构建可持久化的权限规则名
        save_rules: list[str] = []
        # 从工具名推断 action 类型
        if "write" in tool_name or "edit" in tool_name:
            save_rules.append(f"write:{resources[0]}" if resources else "write:*")
        elif "delete" in tool_name:
            save_rules.append(f"delete:{resources[0]}" if resources else "delete:*")
        elif "execute" in tool_name or "bash" in tool_name or "terminal" in tool_name:
            save_rules.append(f"execute:{resources[0]}" if resources else "execute:*")
        elif "read" in tool_name:
            save_rules.append(f"read:{resources[0]}" if resources else "read:*")
        else:
            save_rules.append(f"{tool_name}:*")

        # 推断 action 显示名称
        if "write" in tool_name or "edit" in tool_name:
            action = "write"
        elif "delete" in tool_name:
            action = "delete"
        elif "execute" in tool_name or "bash" in tool_name or "terminal" in tool_name:
            action = "execute"
        elif "read" in tool_name:
            action = "read"
        else:
            action = tool_name

        logger.bind(
            module="executor",
            event="permission_request_sent",
            tool_name=tool_name,
            user_id=user_id,
            session_id=session_id,
            action=action,
            resources=resources,
        ).info(f"权限请求已发送: {tool_name} ({action})")

        # 入队并等待用户回复
        reply_future = enqueue_permission_request(
            user_id=user_id,
            session_id=session_id,
            action=action,
            resources=resources,
            save=save_rules,
            metadata={
                "tool_name": tool_name,
                "tool_args": {
                    k: v for k, v in tool_args.items()
                    if k in ("path", "file", "command", "url", "content")
                },
            },
            agent=context.get("agent_name"),
            timeout=120.0,
        )

        reply = await reply_future
        logger.bind(
            module="executor",
            event="permission_reply_received",
            tool_name=tool_name,
            reply=reply,
        ).info(f"权限请求回复: {tool_name} -> {reply}")
        return reply

    async def _apply_post_tool_use_hooks(
        self,
        result: Dict[str, Any],
        tool_name: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        应用 PostToolUse 钩子（hook_manager 系统）。

        处理 MODIFY_OUTPUT 和 PREVENT_CONTINUATION 结果类型：
        - MODIFY_OUTPUT: 使用 hook_updated_output 修改后的输出替换原始结果
        - PREVENT_CONTINUATION: 在结果中设置 prevent_continuation 标志位
        """
        try:
            from core.hook_manager import (
                HookContext as _HookContext,
                HookName as _HookName,
                HookResultType as _HookResultType,
                hook_manager as _hook_manager,
                hook_updated_output as _hook_updated_output,
            )
            _post_results = await _hook_manager.trigger(
                _HookName.TOOL_AFTER_EXECUTE,
                data={
                    "tool_name": tool_name,
                    "result": result,
                    "context": context,
                },
                context=_HookContext(
                    hook_name=_HookName.TOOL_AFTER_EXECUTE.value,
                    session_id=str(context.get("session_id", "") or "") or None,
                    user_id=str(context.get("user_id", "") or "") or None,
                ),
            )
            # 应用 MODIFY_OUTPUT：最后一个非 None 的 modified_output 生效
            result = _hook_updated_output(_post_results, result)
            # 检查 PREVENT_CONTINUATION：设置标志位
            for _post_result in _post_results:
                if _post_result.result_type == _HookResultType.PREVENT_CONTINUATION:
                    if isinstance(result, dict):
                        result["prevent_continuation"] = True
                        if _post_result.reason:
                            result["prevent_continuation_reason"] = _post_result.reason
                    break
        except ImportError:
            logger.warning("[PostToolUse] hook_manager 模块导入失败，跳过 PostToolUse 钩子")
        return result

    def _build_tool_use_context(self, context: Dict[str, Any]) -> ToolUseContext:
        """
        从执行上下文 Dict 构造 ToolUseContext 实例，用于显式依赖注入到工具 execute 函数。

        渐进式迁移：将散乱的 context Dict 中的标识字段、中止控制器、内容替换状态与回调
        集中到 ToolUseContext，工具可通过 coerce_tool_context 适配器获取。

        Args:
            context: 执行上下文 Dict，包含 session_id/user_id/agent_id 等字段

        Returns:
            构造完成的 ToolUseContext 实例
        """
        return ToolUseContext(
            session_id=str(context.get("session_id", "") or ""),
            user_id=str(context.get("user_id", "") or ""),
            agent_id=str(context.get("agent_id", context.get("session_id", "")) or ""),
            abort_controller=context.get("abort_controller"),
            content_replacement_state=context.get("content_replacement_state"),
            record_usage=context.get("record_usage"),
            record_latency=context.get("record_latency"),
            spawn_subagent=context.get("spawn_subagent"),
            metadata={
                k: v for k, v in context.items()
                if k not in {
                    "session_id", "user_id", "agent_id",
                    "abort_controller", "content_replacement_state",
                    "record_usage", "record_latency", "spawn_subagent",
                    "_tool_use_context",
                }
            },
        )

    async def _execute_tool_call(
        self,
        tool_call: Dict[str, Any],
        context: Dict[str, Any],
        on_subagent_event: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """
        执行单个工具调用，根据 function name 分发到对应的处理器。
        """
        _tool_start_time = time.time()
        func_name = tool_call.get("function", {}).get("name", "")
        raw_func_name = func_name
        func_args_str = tool_call.get("function", {}).get("arguments", "{}")

        try:
            func_args = json.loads(func_args_str) if isinstance(func_args_str, str) else func_args_str
        except json.JSONDecodeError:
            return {"ok": False, "error": f"Invalid JSON in tool_call arguments: {func_args_str[:200]}"}

        if not func_name:
            return {"ok": False, "error": "tool_call missing function name"}

        # 构造 ToolUseContext，供工具 execute 函数通过显式依赖注入访问
        # 不直接修改 context，避免污染传入 spawn_agent 等下游调用方的上下文
        _tool_use_context = self._build_tool_use_context(context)

        # 自主模式：四层安全洋葱检查（非阻塞，拒绝即返回）
        try:
            from core.autonomous import get_autonomous_manager
            am = get_autonomous_manager()
            if am and am.is_autonomous:
                # 推断当前 scope
                scope = str(context.get("scope") or context.get("execution_mode") or "chat")
                if am.is_active_for(scope):
                    denial = await am.check_all(func_name, func_args)
                    if denial:
                        # 记录审计日志（fire-and-forget，不阻塞工具拒绝返回）
                        # 添加 done_callback 防止审计证据静默丢失
                        session_id = str(context.get("session_id", "") or "")
                        audit_task = asyncio.create_task(am.record_audit(
                            session_id=session_id,
                            action=func_name,
                            params=func_args,
                            decision="denied",
                            denied_by=denial.get("denied_by", "unknown"),
                            error=denial.get("error"),
                        ))
                        audit_task.add_done_callback(_handle_audit_task_result)
                        return denial
                    # 文件写入/删除操作：自动创建检查点
                    if func_name in ("builtin_write_file", "builtin_delete_file", "write_file", "delete_file"):
                        file_path = str(func_args.get("path") or func_args.get("file") or "")
                        if file_path:
                            cp_id = await am.create_checkpoint(file_path,
                                "delete" if "delete" in func_name else "write")
                            if cp_id:
                                logger.debug(f"[自主模式] 文件操作前检查点已创建: {cp_id}")
                    # 记录允许执行的审计日志（fire-and-forget，不阻塞工具执行）
                    # 添加 done_callback 防止审计证据静默丢失
                    session_id = str(context.get("session_id", "") or "")
                    audit_task = asyncio.create_task(am.record_audit(
                        session_id=session_id,
                        action=func_name,
                        params=func_args,
                        decision="allowed",
                    ))
                    audit_task.add_done_callback(_handle_audit_task_result)
        except ImportError:
            logger.warning("[自主模式] 安全检查模块导入失败，自主模式安全校验已跳过")
        except (TypeError, ValueError, KeyError) as exc:
            # 参数解析异常：安全模块内部数据异常应阻止操作（fail-closed）
            logger.error(f"[自主模式] 安全检查参数异常，拒绝执行: {exc}")
            return {"ok": False, "error": f"安全检查失败: {exc}", "denied_by": "security"}

        # 部分模型会把工具前缀首字母错误大写成 Task_/Plugin_/Builtin_/Mcp_，
        # 这里仅归一化已知前缀，避免破坏后续名称解析。
        if "_" in func_name:
            prefix, remainder = func_name.split("_", 1)
            normalized_prefix = prefix.lower()
            if normalized_prefix in {"plugin", "mcp", "builtin", "task"}:
                func_name = f"{normalized_prefix}_{remainder}"
                if func_name != raw_func_name:
                    logger.bind(
                        module="executor",
                        event="tool_name_prefix_normalized",
                        raw_tool_name=raw_func_name,
                        normalized_tool_name=func_name,
                    ).warning(f"检测到工具名前缀大小写异常，已自动归一化: {raw_func_name} -> {func_name}")

        # PreToolUse 钩子：分发前校验工具调用权限
        try:
            from core.task_runtime.hook_dispatcher import hook_dispatcher, HOOK_PRE_TOOL_USE
            results = await hook_dispatcher.dispatch(HOOK_PRE_TOOL_USE, {
                "tool_name": func_name,
                "tool_args": func_args,
                "context": context,
            })
            deny_result = hook_dispatcher.has_deny(results)
            if deny_result:
                return {"ok": False, "error": deny_result.reason or f"工具调用被阻止: {func_name}",
                        "blocked_by_hook": True}
            # 合并钩子对参数的覆写
            updated_input = hook_dispatcher.get_updated_input(results)
            if updated_input:
                func_args = {**func_args, **updated_input}
        except ImportError:
            logger.warning("[PreToolUse] 钩子调度模块导入失败，工具调用前校验已跳过")

        # PreToolUse 钩子（hook_manager 系统）：支持 APPROVE/DENY/MODIFY_INPUT/REPLACE_RESULT/ERROR
        try:
            from core.hook_manager import (
                HookContext as _HookContext,
                HookName as _HookName,
                HookResultType as _HookResultType,
                hook_manager as _hook_manager,
                hook_updated_input as _hook_updated_input,
            )
            _pre_results = await _hook_manager.trigger(
                _HookName.TOOL_BEFORE_EXECUTE,
                data={
                    "tool_name": func_name,
                    "tool_args": func_args,
                    "context": context,
                },
                context=_HookContext(
                    hook_name=_HookName.TOOL_BEFORE_EXECUTE.value,
                    session_id=str(context.get("session_id", "") or "") or None,
                    user_id=str(context.get("user_id", "") or "") or None,
                ),
            )
            for _pre_result in _pre_results:
                if _pre_result.result_type == _HookResultType.DENY:
                    return {
                        "ok": False,
                        "error": _pre_result.reason or f"工具调用被钩子拒绝: {func_name}",
                        "blocked_by_hook": True,
                        "tool_name": func_name,
                    }
                if _pre_result.result_type == _HookResultType.ERROR:
                    return {
                        "ok": False,
                        "error": _pre_result.error_message or "PreToolUse 钩子执行错误",
                        "blocked_by_hook": True,
                        "tool_name": func_name,
                    }
                if _pre_result.result_type == _HookResultType.REPLACE_RESULT:
                    return {
                        "ok": True,
                        "result": _pre_result.replace_result,
                        "tool_name": func_name,
                        "replaced_by_hook": True,
                    }
            # 合并所有 MODIFY_INPUT 结果到 func_args
            func_args = _hook_updated_input(_pre_results, func_args)
        except ImportError:
            logger.warning("[PreToolUse] hook_manager 模块导入失败，跳过 hook_manager 钩子校验")

        if func_name.startswith("plugin_"):
            remaining = func_name[len("plugin_"):]
            if "__" in remaining:
                plugin_name, plugin_method = remaining.split("__", 1)
            else:
                return {"ok": False, "error": f"plugin tool name missing '__' separator: {func_name}"}
            from plugins import plugin_instance
            try:
                pm = plugin_instance.get()
                candidate_names = []
                for candidate in (
                    plugin_name,
                    plugin_name.replace("_", "-"),
                    plugin_name.replace("-", "_"),
                ):
                    if candidate and candidate not in candidate_names:
                        candidate_names.append(candidate)

                if not any(pm.has_plugin(candidate) for candidate in candidate_names):
                    discovered = pm.discover_plugins()
                    logger.bind(
                        module="executor",
                        event="plugin_metadata_refreshed",
                        requested_plugin=plugin_name,
                        discovered_count=len(discovered) if isinstance(discovered, list) else None,
                    ).debug(f"工具调用前刷新插件元数据: {plugin_name}")

                resolved_plugin_name = next(
                    (
                        candidate
                        for candidate in candidate_names
                        if pm.has_plugin(candidate) or pm.is_plugin_loaded(candidate)
                    ),
                    plugin_name,
                )

                if (
                    resolved_plugin_name not in pm.loaded_plugins
                    and not pm.load_plugin(resolved_plugin_name)
                ):
                    return {"ok": False, "error": f"Failed to load plugin: {resolved_plugin_name}"}
                result = await pm.execute_registered_tool_async(
                    resolved_plugin_name,
                    plugin_method,
                    db=context.get("db"),
                    user_id=context.get("user_id"),
                    **func_args,
                )
                # 检查插件返回结果状态，非成功状态标记为失败
                if isinstance(result, dict) and result.get("status") == "error":
                    return {"ok": False, "error": result.get("message", "Plugin returned error"), "result": result, "tool_name": func_name}
                _plugin_output = {"ok": True, "result": result, "tool_name": func_name}
                return await self._apply_post_tool_use_hooks(_plugin_output, func_name, context)
            except Exception as exc:
                logger.bind(
                    module="executor",
                    event="plugin_execution_error",
                    plugin_name=plugin_name,
                    plugin_method=plugin_method,
                ).error(f"插件执行异常: {exc}")
                return {"ok": False, "error": f"Plugin execution error: {str(exc)}"}

        if func_name.startswith("mcp_"):
            remaining = func_name[len("mcp_"):]
            if "__" in remaining:
                server_id, mcp_tool_name = remaining.split("__", 1)
            else:
                return {"ok": False, "error": f"MCP tool name missing '__' separator: {func_name}"}
            try:
                manager = MCPManager()
                result = await manager.call_tool(server_id, mcp_tool_name, func_args)
                _mcp_output = {"ok": True, "result": result, "tool_name": func_name}
                return await self._apply_post_tool_use_hooks(_mcp_output, func_name, context)
            except Exception as exc:
                logger.bind(
                    module="executor",
                    event="mcp_execution_error",
                    server_id=server_id,
                    tool_name=mcp_tool_name,
                ).error(f"MCP工具执行异常: {exc}")
                return {"ok": False, "error": f"MCP tool execution error: {str(exc)}"}

        if func_name.startswith("builtin_"):
            builtin_name = func_name[len("builtin_"):]
            # ask_user 特殊处理：注入 user_id 和 session_id 到工具参数
            # AskUserTool 需要这些信息创建与用户会话关联的 Future
            if builtin_name == "ask_user":
                func_args.setdefault("user_id", str(context.get("user_id", "") or ""))
                func_args.setdefault("session_id", str(context.get("session_id", "") or ""))
            # 构造包含 ToolUseContext 的工具执行上下文副本，避免污染原 context
            tool_exec_context = {**context, "_tool_use_context": _tool_use_context}
            # 优先通过 ToolRegistry 执行（支持权限检查、截断、统计等）
            _tool_reg = None
            try:
                from core.tool_registry import tool_registry as _tool_reg
            except ImportError:
                pass  # ToolRegistry 不可用时回退到直接执行
            if _tool_reg is not None:
                try:
                    registered_tool = _tool_reg.get(func_name)
                    if registered_tool and registered_tool.execute:
                        exec_result = await _tool_reg.execute(func_name, func_args, tool_exec_context)
                        _builtin_reg_output = {
                            "ok": exec_result.status.value == "completed",
                            "result": exec_result.result,
                            "error": exec_result.error,
                            "tool_name": func_name,
                            "truncated": exec_result.truncated,
                            "output_path": exec_result.output_path,
                            "execution_time_ms": exec_result.execution_time_ms,
                        }
                        return await self._apply_post_tool_use_hooks(_builtin_reg_output, func_name, context)
                except ImportError:
                    pass  # ToolRegistry 模块不可用时回退到直接执行
                except PermissionError:
                    # 权限拒绝：尝试通过实时推送队列请求用户授权
                    reply = await self._request_user_permission(
                        tool_name=func_name,
                        tool_args=func_args,
                        context=context,
                    )
                    if reply == "reject":
                        return {
                            "ok": False,
                            "error": f"用户拒绝权限: {func_name}",
                            "tool_name": func_name,
                            "denied_by": "user",
                        }
                    # 用户允许（once/always），重新执行工具
                    try:
                        exec_result = await _tool_reg.execute(func_name, func_args, tool_exec_context)
                        _builtin_reg_output = {
                            "ok": exec_result.status.value == "completed",
                            "result": exec_result.result,
                            "error": exec_result.error,
                            "tool_name": func_name,
                            "truncated": exec_result.truncated,
                            "output_path": exec_result.output_path,
                            "execution_time_ms": exec_result.execution_time_ms,
                        }
                        return await self._apply_post_tool_use_hooks(_builtin_reg_output, func_name, context)
                    except PermissionError:
                        # 用户授权后仍被拒绝（可能是 always 规则尚未持久化生效）
                        return {
                            "ok": False,
                            "error": f"权限不足: {func_name}",
                            "tool_name": func_name,
                            "denied_by": "security",
                        }
                except Exception:
                    # ToolRegistry 执行意外失败时记录日志并拒绝执行，
                    # 不得回退到未经过权限检查的 builtin_tool_manager 路径
                    logger.bind(
                        module="executor",
                        event="tool_registry_execution_failed",
                        tool_name=func_name,
                    ).exception(f"ToolRegistry 执行异常，已拒绝回退到直接执行: {func_name}")
                    return {
                        "ok": False,
                        "error": f"Tool registry execution failed for {func_name}",
                        "tool_name": func_name,
                    }
            # 回退：直接通过 builtin_tool_manager 执行（仅当 ToolRegistry 完全不可用时）
            from core.builtin_tools.manager import builtin_tool_manager
            try:
                result = await builtin_tool_manager.execute_tool(builtin_name, func_args)
                ok = bool(result.get("success"))
                _builtin_output = {"ok": ok, "result": result, "tool_name": func_name}
                return await self._apply_post_tool_use_hooks(_builtin_output, func_name, context)
            except Exception as exc:
                logger.bind(
                    module="executor",
                    event="builtin_execution_error",
                    tool_name=builtin_name,
                ).error(f"内置工具执行异常: {exc}")
                return {"ok": False, "error": f"Builtin tool execution error: {str(exc)}"}

        # 任务运行时工具（task_spawn_agent / task_send_message / task_stop_agent / task_create_team 等）
        if func_name.startswith("task_"):
            task_action = func_name[len("task_"):]
            from core.task_runtime import task_runtime

            await task_runtime.initialize()

            if task_action == "spawn_agent":
                agent_type = func_args.get("agent_type", "Explore")
                prompt = func_args.get("prompt", "")
                description = func_args.get("description", "")
                provider, model, model_error = self._resolve_subagent_model_selection(
                    context,
                    func_args.get("provider"),
                    func_args.get("model"),
                )
                if model_error:
                    logger.bind(
                        module="executor",
                        event="subagent_model_resolution_failed",
                        agent_type=agent_type,
                    ).warning(model_error)
                    return {"ok": False, "error": model_error, "tool_name": func_name}

                background = func_args.get("background", False)
                logger.bind(
                    module="executor",
                    event="subagent_spawn_requested",
                    agent_type=agent_type,
                    provider=provider,
                    model=model,
                    background=background,
                ).info(f"准备启动子代理: {agent_type}")
                result = await task_runtime.spawn_agent(
                    agent_type=agent_type,
                    prompt=prompt,
                    description=description,
                    provider=provider,
                    model=model,
                    background=background,
                    root_chat_session_id=context.get("session_id"),
                    context=context,
                )
                if isinstance(result, dict):
                    return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}
                return await self._consume_foreground_subagent_stream(
                    result,
                    func_name,
                    on_subagent_event=on_subagent_event,
                )

            elif task_action == "send_message":
                to = func_args.get("to", "")
                message = func_args.get("message", "")
                result = await task_runtime.send_message(to=to, message=message)
                return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}

            elif task_action == "stop_agent":
                agent_id = func_args.get("agent_id", "")
                result = await task_runtime.stop_agent(agent_id)
                return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}

            elif task_action == "list_agents":
                agent_type_filter = func_args.get("agent_type")
                state_filter = func_args.get("state")
                result = await task_runtime.list_agents(state=state_filter)
                return {"ok": True, "result": {"agents": result}, "tool_name": func_name}

            elif task_action == "list_agent_types":
                result = await task_runtime.list_agent_types()
                return {"ok": True, "result": {"agent_types": result}, "tool_name": func_name}

            elif task_action == "create_task":
                result = await task_runtime.create_task_item(
                    list_id=func_args.get("list_id"),
                    subject=func_args.get("subject", ""),
                    description=func_args.get("description"),
                    dependencies=func_args.get("dependencies"),
                    owner_agent_id=func_args.get("owner_agent_id"),
                )
                return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}

            elif task_action == "list_tasks":
                result = await task_runtime.list_task_items(
                    list_id=func_args.get("list_id"),
                    status=func_args.get("status"),
                )
                return {"ok": True, "result": {"tasks": result}, "tool_name": func_name}

            elif task_action == "update_task":
                result = await task_runtime.update_task_item(
                    func_args.get("task_id", ""),
                    status=func_args.get("status"),
                    subject=func_args.get("subject"),
                    owner_agent_id=func_args.get("owner_agent_id"),
                    result_summary=func_args.get("result_summary"),
                )
                return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}

            elif task_action == "claim_task":
                task_id = func_args.get("task_id", "")
                agent_id = context.get("agent_id", context.get("session_id", "unknown"))
                result = await task_runtime.claim_task_item(task_id=task_id, agent_id=agent_id)
                return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}

            elif task_action == "get_task":
                task_id = func_args.get("task_id", "")
                result = await task_runtime.get_task_item(task_id)
                if not result:
                    return {"ok": False, "error": f"任务不存在: {task_id}"}
                return {"ok": True, "result": result, "tool_name": func_name}

            elif task_action == "create_team":
                result = await task_runtime.create_team(
                    lead_agent_id=func_args.get("lead_agent_id", ""),
                    name=func_args.get("name", ""),
                    teammate_agent_ids=func_args.get("teammate_agent_ids"),
                    task_list_id=func_args.get("task_list_id"),
                )
                return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}

            elif task_action == "delete_team":
                result = await task_runtime.delete_team(func_args.get("team_id", ""))
                return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}

            elif task_action == "list_teams":
                result = await task_runtime.list_teams(state=func_args.get("state"))
                return {"ok": True, "result": {"teams": result}, "tool_name": func_name}

            elif task_action == "get_team":
                result = await task_runtime.get_team(func_args.get("team_id", ""))
                if not result:
                    return {"ok": False, "error": f"团队不存在: {func_args.get('team_id')}"}
                return {"ok": True, "result": result, "tool_name": func_name}

            elif task_action == "add_teammate":
                result = await task_runtime.add_teammate(
                    func_args.get("team_id", ""),
                    func_args.get("agent_id", ""),
                    func_args.get("name", ""),
                )
                return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}

            elif task_action == "remove_teammate":
                result = await task_runtime.remove_teammate(
                    func_args.get("team_id", ""),
                    func_args.get("agent_id", ""),
                )
                return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}

            elif task_action == "get_mailbox":
                result = await task_runtime.get_mailbox(
                    agent_id=func_args.get("agent_id", ""),
                    unread_only=func_args.get("unread_only", False),
                )
                return {"ok": True, "result": {"messages": result}, "tool_name": func_name}

            elif task_action == "todo_write":
                result = await task_runtime.sync_todo_snapshot(
                    list_id=func_args.get("list_id"),
                    todos=func_args.get("todos", []),
                )
                return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}

            else:
                return {"ok": False, "error": f"未知任务运行时工具: {task_action}"}

        output = {"ok": False, "error": f"No handler for tool: {func_name}"}

        # 收集工具调用数据
        try:
            from data.collector import data_collector
            await data_collector.collect_tool_call({
                "conversation_id": context.get("session_id", ""),
                "role_id": context.get("role_id", ""),
                "tool_name": func_name,
                "tool_params": func_args,
                "result_summary": str(output.get("response", ""))[:500],
                "success": output.get("ok", False),
                "duration_ms": int((time.time() - _tool_start_time) * 1000),
            })
        except Exception as e:
            # 数据收集不影响主流程，但记录日志便于排查
            logger.warning("工具数据收集失败", exc_info=e)

        return output

    async def _execute_tool_calls_concurrent(
        self,
        tool_calls: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """
        使用 StreamingToolExecutor 并发调度工具调用。

        调度策略：
        - 只读且并发安全的工具可同时执行
        - 破坏性工具串行执行
        - 队列中有破坏性工具时阻塞其他工具

        返回结果按原始 tool_calls 顺序排列，保持与同步执行相同的接口契约。

        Args:
            tool_calls: 工具调用列表
            context: 执行上下文

        Returns:
            (tool_call, exec_result) 元组列表，按原始顺序排列
        """
        from core.streaming_tool_executor import StreamingToolExecutor
        from core.tool_registry import tool_registry as global_tool_registry

        streaming_executor = StreamingToolExecutor(
            tool_registry=global_tool_registry,
            max_concurrent=5,
        )

        # 提交所有工具调用到调度队列
        for tc in tool_calls:
            tc_id = tc.get("id", "")
            func_name = tc.get("function", {}).get("name", "")
            func_args_str = tc.get("function", {}).get("arguments", "{}")
            try:
                func_args = json.loads(func_args_str) if isinstance(func_args_str, str) else func_args_str
            except json.JSONDecodeError:
                func_args = {}
            streaming_executor.submit(tc_id, func_name, func_args)

        # 工具执行函数：构造合成 tool_call 并委托给 _execute_tool_call
        async def _execute_fn(tool_name: str, input_params: dict) -> Dict[str, Any]:
            synthetic_tc = {
                "id": "",
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(input_params, ensure_ascii=False),
                },
            }
            return await self._execute_tool_call(synthetic_tc, context)

        # 启动调度循环（后台任务，与 yield_completed 并发运行）
        schedule_task = asyncio.create_task(
            streaming_executor.process_queue(_execute_fn)
        )

        # 收集结果，按 tool_call_id 映射
        results_by_id: Dict[str, Any] = {}
        async for tracked in streaming_executor.yield_completed():
            results_by_id[tracked.tool_call_id] = tracked

        # 确保调度任务完成
        await schedule_task

        # 按原始顺序构建结果列表，保持与同步执行相同的接口契约
        ordered_results: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        for tc in tool_calls:
            tc_id = tc.get("id", "")
            tracked = results_by_id.get(tc_id)
            if tracked is None:
                # 防御性处理：结果丢失视为失败
                exec_result = {"ok": False, "error": f"工具结果丢失: {tc_id}"}
            elif tracked.error is not None:
                exec_result = {
                    "ok": False,
                    "error": str(tracked.error),
                    "tool_name": tracked.tool_name,
                }
            elif isinstance(tracked.result, dict):
                exec_result = tracked.result
            else:
                exec_result = {
                    "ok": True,
                    "result": tracked.result,
                    "tool_name": tracked.tool_name,
                }
            ordered_results.append((tc, exec_result))

        return ordered_results

    @staticmethod
    def _build_tool_message(tool_call: Dict[str, Any], exec_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据工具调用及其执行结果构建 tool role 消息，用于后续 LLM 轮次。
        对过大的工具结果进行截断，防止消息列表无限膨胀导致 OOM 或 token 超限。
        """
        result_str = json.dumps(exec_result, ensure_ascii=False, default=str)
        if len(result_str) > MAX_TOOL_RESULT_CHARS:
            result_str = (
                result_str[:MAX_TOOL_RESULT_CHARS]
                + f"\n[工具输出已截断，原始长度: {len(result_str)} 字符，超出部分已丢弃]"
            )
        return {
            "role": "tool",
            "tool_call_id": tool_call.get("id", ""),
            "content": result_str,
        }

    async def execute_step(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行单个规划步骤：根据 action 类型分发给对应处理函数（read_files/execute_command/llm_* 等）。
        执行前校验参数 Schema，执行后通过幂等键缓存结果防止重复执行。
        """
        action = step.get("action")
        if action is None:
            logger.bind(
                event="execute_step_missing_action",
                module="executor",
                step_keys=list(step.keys()) if isinstance(step, dict) else None,
            ).warning("execute_step 收到 action=None 的步骤，跳过执行")
            return {
                "status": "error",
                "error": "步骤缺少 action 字段",
                "step": step.get("step"),
                "action": None,
            }
        logger.info(f"Executing step: {action}")
        idempotency_key = self._build_tool_idempotency_key(step, context)
        cached_result = self._get_cached_tool_result(idempotency_key)
        if cached_result is not None:
            cached_result["idempotency_key"] = idempotency_key
            record_tool_execution_metric(str(action or "unknown"), "replayed")
            logger.bind(
                event="tool_cache_hit",
                module="executor",
                action=action,
                idempotency_key=idempotency_key[:16],
            ).debug(f"工具执行命中缓存，跳过重复执行: {action}")
            return cached_result
        
        # 执行前的参数 Schema 校验
        validation_error = self._validate_step_params(action, step)
        if validation_error:
            logger.bind(
                event="tool_param_validation_failed",
                module="executor",
                action=action,
            ).warning(f"步骤参数校验失败: {validation_error}")
            result = {
                "status": "error",
                "error": validation_error,
                "action": action,
                "step": step.get("step"),
                "idempotency_key": idempotency_key,
            }
            record_tool_execution_metric(str(action or "unknown"), "validation_error")
            return result

        try:
            if action == "read_files":
                result = await self._execute_read_files(step)
            elif action == "execute_command":
                result = await self._execute_command(step)
            elif action == "llm_generate":
                result = await self._execute_llm(step, context)
            elif action == "llm_query":
                result = await self._execute_llm_query(step, context)
            elif action == "llm_explain":
                result = await self._execute_llm_explain(step, context)
            elif action == "llm_chat":
                result = await self._execute_llm_chat(step, context)
            else:
                result = {"status": "error", "message": f"Unknown action: {action}"}
            
            result["step"] = step.get("step")
            result["action"] = action
            result["idempotency_key"] = idempotency_key
            self._cache_tool_result(idempotency_key, result)
            record_tool_execution_metric(str(action or "unknown"), str(result.get("status") or "completed"))
            
            if context.get('relevant_experiences'):
                logger.info(f"Executed step using {len(context['relevant_experiences'])} experiences")
            
            return result
            
        except Exception as e:
            logger.bind(
                event="step_execution_error",
                module="executor",
                error_type=type(e).__name__,
                action=action,
            ).opt(exception=True).error(f"步骤执行异常 [{action}]: {e}")
            record_tool_execution_metric(str(action or "unknown"), "error")
            return {
                "status": "error",
                "message": str(e),
                "step": step.get("step"),
                "action": action,
                "idempotency_key": idempotency_key,
            }
    
    async def _execute_read_files(self, step: Dict[str, Any]) -> Dict[str, Any]:
        """
        读取指定文件列表的内容。包含路径穿越防护：所有文件路径限制在工作区目录内。
        支持 workspace 环境变量 OPENAWA_WORKSPACE 自定义工作区根路径。
        """
        files = step.get("targets", [])
        results = {}

        from pathlib import Path as _Path
        import os as _os
        _workspace = _Path(_os.environ.get("OPENAWA_WORKSPACE", _os.getcwd())).resolve()
        for file_path in files:
            # 路径穿越防护：使用 Path.resolve() + relative_to() 替代 startswith
            # startswith 可被符号链接或 .. 序列绕过，relative_to 是项目硬约束
            try:
                resolved = (_workspace / str(file_path).lstrip("/\\")).resolve()
                # 触发 relative_to 校验，不在工作区内则抛 ValueError
                resolved.relative_to(_workspace)
            except (ValueError, OSError):
                results[file_path] = {
                    "status": "error",
                    "message": "Path traversal denied"
                }
                continue
            try:
                # 将同步文件读取包装到 asyncio.to_thread，
                # 避免在异步协程中阻塞事件循环。
                def _read_file(path: str) -> str:
                    with open(path, 'r', encoding='utf-8') as _f:
                        return _f.read()
                content = await asyncio.to_thread(_read_file, resolved)
                results[file_path] = {
                    "status": "success",
                    "content": content
                }
            except FileNotFoundError:
                results[file_path] = {
                    "status": "error",
                    "message": f"File not found: {file_path}"
                }
            except Exception as e:
                results[file_path] = {
                    "status": "error",
                    "message": str(e)
                }
        
        return {
            "status": "completed",
            "results": results
        }
    
    async def _execute_command(self, step: Dict[str, Any]) -> Dict[str, Any]:
        """
        在沙箱中异步执行 Shell 命令。包含三层安全防护：
        命令长度限制（512 字符）、security.sandbox 白名单校验、30 秒超时自动终止。
        """
        command = step.get("command", "")

        # 命令长度限制，防止超长命令被注入
        if len(command) > 512:
            return {
                "status": "error",
                "message": f"Command too long: {len(command)} characters (max 512)"
            }

        import shlex
        proc = None
        try:
            args = shlex.split(command)
            if not args:
                return {
                    "status": "error",
                    "message": "Empty command"
                }

            # 使用白名单校验可执行文件，防止任意命令执行
            from security.sandbox import validate_command_safety
            is_safe, err_msg = validate_command_safety(args[0], args[1:] if len(args) > 1 else [])
            if not is_safe:
                return {
                    "status": "error",
                    "message": err_msg or "Command rejected by security policy"
                }

            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=30
            )

            return {
                "status": "completed",
                "returncode": proc.returncode,
                "stdout": stdout.decode() if stdout else "",
                "stderr": stderr.decode() if stderr else ""
            }
        except asyncio.TimeoutError:
            if proc is not None:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    logger.bind(module="executor", event="process_kill_timeout_error", pid=proc.pid).warning(
                        "超时进程清理失败"
                    )
            return {
                "status": "error",
                "message": "Command execution timeout"
            }
        except Exception as e:
            if proc is not None:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    logger.bind(module="executor", event="process_kill_error", pid=proc.pid).warning(
                        "异常进程清理失败"
                    )
            return {
                "status": "error",
                "message": str(e)
            }
    
    async def _execute_llm(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        通过 LLM 生成内容（llm_generate 动作的处理函数）。
        调用 _call_llm_api 发起非流式请求，返回结果标记 requires_confirmation 用于人工审核。
        """
        prompt = self._resolve_step_param(step, "prompt", "task") or ""
        result = await self._call_llm_api(prompt, context)
        if not result.get("ok"):
            return {
                "status": "error",
                "message": result["error"]["message"],
                "error": result["error"]
            }

        return {
            "status": "completed",
            "response": result["response"],
            "provider": result.get("provider"),
            "model": result.get("model"),
            "requires_confirmation": True
        }

    async def _execute_llm_query(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        通过 LLM 执行查询（llm_query 动作的处理函数）。
        与 _execute_llm 的区别：不标记 requires_confirmation，适用于只读查询场景。
        """
        prompt = self._resolve_step_param(step, "prompt", "query") or ""
        result = await self._call_llm_api(prompt, context)
        if not result.get("ok"):
            return {
                "status": "error",
                "message": result["error"]["message"],
                "error": result["error"]
            }

        return {
            "status": "completed",
            "response": result["response"],
            "provider": result.get("provider"),
            "model": result.get("model")
        }

    async def _execute_llm_explain(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        通过 LLM 解释内容（llm_explain 动作的处理函数）。
        支持 target 参数作为备选输入源，自动构造 "Explain: {target}" 提示词。
        """
        prompt = self._resolve_step_param(step, "prompt")
        if prompt is None or prompt == "":
            target = self._resolve_step_param(step, "target") or ""
            prompt = f"Explain: {target}" if target else ""
        result = await self._call_llm_api(prompt, context)
        if not result.get("ok"):
            return {
                "status": "error",
                "message": result["error"]["message"],
                "error": result["error"]
            }

        return {
            "status": "completed",
            "response": result["response"],
            "provider": result.get("provider"),
            "model": result.get("model")
        }

    async def _execute_llm_chat(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        通过 LLM 进行自由对话（llm_chat 动作的处理函数）。
        与 _execute_llm 的区别：不需要人工确认，适用于对话式交互场景。
        """
        message = step.get("message", "")
        result = await self._call_llm_api(message, context)
        if not result.get("ok"):
            return {
                "status": "error",
                "message": result["error"]["message"],
                "error": result["error"]
            }

        output = {
            "status": "completed",
            "response": result["response"],
            "provider": result.get("provider"),
            "model": result.get("model"),
        }
        # 传递推理内容（如果存在）
        if result.get("reasoning_content"):
            output["reasoning_content"] = result["reasoning_content"]
        return output
    
    async def retry_step(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """使用指数退避策略重试失败的执行步骤。"""
        from core.retry import RetryPolicy, execute_with_retry

        policy = RetryPolicy(max_attempts=3)
        # 仅对瞬态 I/O 故障重试；业务校验、权限错误和编程错误必须立即向上返回。
        retryable_exceptions = (TimeoutError, ConnectionError, OSError)
        result = await execute_with_retry(
            self.execute_step,
            step,
            context,
            policy=policy,
            retryable_exceptions=retryable_exceptions,
        )

        if result.success:
            return result.result

        return {
            "status": "failed",
            "response": f"重试 {result.attempts} 次后仍然失败: {result.last_error}",
            "error": str(result.last_error),
        }
    
    async def record_experience_feedback(
        self,
        experience_id: int,
        success: bool
    ) -> None:
        """
        更新经验条目的质量评分：根据执行成功/失败反馈调整经验的 success_metrics 置信度。
        ExperienceManager 内部通过 asyncio.to_thread 使用独立会话，无需外部传入 db。
        """
        try:
            manager = ExperienceManager(db=None)
            await manager.update_experience_quality(
                experience_id=experience_id,
                success=success
            )
        except Exception as e:
            logger.opt(exception=True).error(f"记录经验反馈失败: {e}")


# ExecutionLayer 的别名，用于对外暴露统一的执行器名称
Executor = ExecutionLayer

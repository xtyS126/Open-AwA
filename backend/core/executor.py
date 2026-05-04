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
from typing import Dict, Any, Optional, Callable

import httpx
from loguru import logger

from config.logging import generate_request_id, get_request_id, sanitize_for_logging
from config.settings import settings
from core.metrics import record_model_service_metric, record_tool_execution_metric
from core.model_service import (
    build_standard_error,
)
from core.litellm_adapter import (
    litellm_chat_completion,
    litellm_chat_completion_stream,
)
from memory.experience_manager import ExperienceManager
from mcp.manager import MCPManager
from sqlalchemy.orm import Session


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


class ExecutionLayer:
    """
    封装与ExecutionLayer相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(self):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
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
        self._tool_execution_cache: Dict[str, Dict[str, Any]] = {}
        self._tool_execution_cache_order: list[str] = []
        self._max_tool_execution_cache = 256
        logger.info("ExecutionLayer initialized")

    def configure_llm(self, api_url: str, api_key: Optional[str] = None):
        """
        处理configure、llm相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.llm_api_url = api_url
        self.llm_api_key = api_key
        logger.info(f"LLM API configured: {api_url}")

    def register_tool(self, name: str, tool_func: Callable[..., Any]):
        """
        处理register、tool相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.tools[name] = tool_func
        logger.debug(f"Registered execution tool: {name}")

    def _build_error(self, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        处理build、error相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
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
                "param_type": list,
                "label": "文件路径列表",
            },
            "execute_command": {
                "param_key": "command",
                "param_type": str,
                "label": "命令",
            },
            "llm_generate": {
                "param_key": "prompt",
                "param_type": str,
                "label": "提示词",
            },
            "llm_query": {
                "param_key": "prompt",
                "param_type": str,
                "label": "查询提示词",
            },
            "llm_explain": {
                "param_key": "prompt",
                "param_type": str,
                "label": "解释提示词",
            },
            "llm_chat": {
                "param_key": "message",
                "param_type": str,
                "label": "聊天消息",
            },
        }

        schema = action_schemas.get(action)
        if not schema:
            return None

        param_key = schema["param_key"]
        param_value = step.get(param_key) or step.get("parameters", {}).get(param_key)

        if param_value is None or param_value == "":
            return f"缺少必填参数 '{param_key}' ({schema['label']})"

        if schema["param_type"] is list and not isinstance(param_value, list):
            return f"参数 '{param_key}' 应为 {schema['param_type'].__name__} 类型，实际为 {type(param_value).__name__}"

        if schema["param_type"] is str and not isinstance(param_value, str):
            return f"参数 '{param_key}' 应为 {schema['param_type'].__name__} 类型，实际为 {type(param_value).__name__}"

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
        """

        self._tool_execution_cache[idempotency_key] = dict(result)
        if idempotency_key in self._tool_execution_cache_order:
            self._tool_execution_cache_order.remove(idempotency_key)
        self._tool_execution_cache_order.append(idempotency_key)

        while len(self._tool_execution_cache_order) > self._max_tool_execution_cache:
            oldest = self._tool_execution_cache_order.pop(0)
            self._tool_execution_cache.pop(oldest, None)

    def _extract_response_text(self, response_data: Dict[str, Any]) -> str:
        """
        处理extract、response、text相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
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

    def _pick_effective_model(
        self,
        provider: str,
        model: str,
        selected_models: Optional[list[str]] = None,
    ) -> str:
        """
        为“provider 级配置”挑选可用模型。
        当配置里保存的是占位值 custom-model 时，优先从 selected_models 中选可用模型。
        """
        normalized_provider = str(provider or "").strip().lower()
        normalized_model = str(model or "").strip()
        candidates = [str(item or "").strip() for item in (selected_models or []) if str(item or "").strip()]

        # provider 级配置常见占位值，不能直接用于真实调用
        if normalized_model.lower() in {"custom-model", "custom_model", "custom", "default-model", "default"} or not normalized_model:
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
        处理resolve、llm、configuration相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        from config.settings import settings

        provider = context.get("provider")
        model = context.get("model")
        db = context.get("db")
        config = None

        if db:
            try:
                from billing.pricing_manager import PricingManager
                pricing_manager = PricingManager(db)
                if provider and model:
                    config = pricing_manager.get_configuration_by_provider_model(provider, model)
                if not config and provider:
                    # 当聊天页传入的是 selected_models 中的真实模型名时，
                    # 数据库里通常只保存 provider 级的 custom-model 配置。
                    config = pricing_manager.get_default_provider_configuration(provider)
                if not config:
                    config = pricing_manager.get_default_configuration()
            except Exception as e:
                logger.opt(exception=True).error(
                    f"Failed to resolve model configuration from database: {e}"
                )

        if config:
            provider = provider or config.provider
            model = model or config.model
            api_key = config.api_key
            api_endpoint = config.api_endpoint
            max_tokens = getattr(config, "max_tokens_limit", None)
            selected_models: list[str] = []
            try:
                from billing.pricing_manager import PricingManager
                selected_models = PricingManager.parse_selected_models(getattr(config, "selected_models", None))
            except Exception:
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
            from billing.pricing_manager import PricingManager
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
                lines.append(f"- {skill.get('name', 'unknown')}")
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

    def _build_messages_with_history(self, prompt: str, context: Dict[str, Any]) -> list:
        """
        从上下文中提取对话历史，构建包含历史消息的 messages 列表。
        对话历史由 agent 层在调用前注入到 context["conversation_history"] 中。
        支持多模态内容：若 context 含 _multimodal_content 则使用数组格式。
        """
        messages = []
        system_prompt = self._build_agent_capability_system_prompt(context)
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

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

        resolved = self._resolve_llm_configuration(context)
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
        result = await litellm_chat_completion(
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

        # 支持 tool_calls 循环：检测到工具调用时自动执行并将结果回传 LLM
        max_rounds = 5
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
            for tc in tool_calls:
                exec_result = await self._execute_tool_call(tc, context)
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
                tool_events.append({
                    "name": tc.get("function", {}).get("name", "unknown"),
                    "status": "completed" if exec_result.get("ok") else "error",
                    "result": exec_result.get("result", exec_result.get("error")),
                })
                tool_message = self._build_tool_message(tc, exec_result)
                messages.append(tool_message)
            if _abort:
                break

            result = await litellm_chat_completion(
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
            tokens_used = usage.get("total_tokens") if isinstance(usage, dict) else None
            record_hook(
                node_type="llm_call",
                user_message=context.get("message", prompt),
                context=context,
                status="success",
                llm_input=llm_input_payload,
                llm_output=result,
                llm_tokens_used=tokens_used,
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

        resolved = self._resolve_llm_configuration(context)
        if not resolved.get("ok"):
            yield {"error": resolved.get("error")}
            return

        messages = self._build_messages_with_history(prompt, context)
        tool_messages = context.get("_tool_messages", [])
        if tool_messages:
            messages.extend(tool_messages)
            context.pop("_tool_messages", None)
        _tools = context.get("_tools")
        full_content = ""
        full_reasoning = ""

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

            async for chunk in stream_gen:
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

    async def _execute_tool_call(self, tool_call: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行单个工具调用，根据 function name 分发到对应的处理器。
        """
        func_name = tool_call.get("function", {}).get("name", "")
        func_args_str = tool_call.get("function", {}).get("arguments", "{}")

        try:
            func_args = json.loads(func_args_str) if isinstance(func_args_str, str) else func_args_str
        except json.JSONDecodeError:
            return {"ok": False, "error": f"Invalid JSON in tool_call arguments: {func_args_str[:200]}"}

        if not func_name:
            return {"ok": False, "error": "tool_call missing function name"}

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
            pass

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

                if not any(candidate in getattr(pm, "plugin_metadata", {}) for candidate in candidate_names):
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
                        if candidate in getattr(pm, "plugin_metadata", {}) or candidate in getattr(pm, "loaded_plugins", {})
                    ),
                    plugin_name,
                )

                if (
                    resolved_plugin_name not in pm.loaded_plugins
                    and not pm.load_plugin(resolved_plugin_name)
                ):
                    return {"ok": False, "error": f"Failed to load plugin: {resolved_plugin_name}"}
                result = await pm.execute_plugin_async(resolved_plugin_name, plugin_method, **func_args)
                return {"ok": True, "result": result, "tool_name": func_name}
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
                return {"ok": True, "result": result, "tool_name": func_name}
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
            from core.builtin_tools.manager import builtin_tool_manager
            try:
                result = await builtin_tool_manager.execute_tool(builtin_name, func_args)
                ok = bool(result.get("success"))
                return {"ok": ok, "result": result, "tool_name": func_name}
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
                model = func_args.get("model")
                background = func_args.get("background", False)
                result = await task_runtime.spawn_agent(
                    agent_type=agent_type,
                    prompt=prompt,
                    description=description,
                    model=model,
                    background=background,
                    context=context,
                )
                if isinstance(result, dict):
                    return {"ok": result.get("ok", True), "result": result, "tool_name": func_name}
                # 前台模式返回 AsyncGenerator，暂不支持在工具调用中直接消费
                return {"ok": True, "result": {"message": "前台子代理已启动，通过 SSE 流获取结果"}, "tool_name": func_name}

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

        return {"ok": False, "error": f"No handler for tool: {func_name}"}

    @staticmethod
    def _build_tool_message(tool_call: Dict[str, Any], exec_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据工具调用及其执行结果构建 tool role 消息，用于后续 LLM 轮次。
        """
        return {
            "role": "tool",
            "tool_call_id": tool_call.get("id", ""),
            "content": json.dumps(exec_result, ensure_ascii=False, default=str),
        }

    async def execute_step(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理execute、step相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
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
        处理execute、read、files相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        files = step.get("targets", [])
        results = {}
        
        import os as _os
        _workspace = _os.path.abspath(_os.environ.get("OPENAWA_WORKSPACE", _os.getcwd()))
        for file_path in files:
            resolved = _os.path.abspath(_os.path.join(_workspace, str(file_path).lstrip("/\\")))
            if not resolved.startswith(_workspace + _os.sep) and resolved != _workspace:
                results[file_path] = {
                    "status": "error",
                    "message": "Path traversal denied"
                }
                continue
            try:
                with open(resolved, 'r', encoding='utf-8') as f:
                    results[file_path] = {
                        "status": "success",
                        "content": f.read()
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
        处理execute、command相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        command = step.get("command", "")
        
        # 命令长度限制，防止超长命令被注入
        if len(command) > 512:
            return {
                "status": "error",
                "message": f"Command too long: {len(command)} characters (max 512)"
            }
        
        # 过滤危险shell字符，防止命令注入
        dangerous_chars = ["&", "|", ";", "`", "$", "(", ")", "{", "}", "<", ">", "\n", "\r"]
        for ch in dangerous_chars:
            if ch in command:
                return {
                    "status": "error",
                    "message": f"Command contains dangerous shell character: {repr(ch)}"
                }
        
        import shlex
        proc = None
        try:
            args = shlex.split(command)
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
                    pass
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
                    pass
            return {
                "status": "error",
                "message": str(e)
            }
    
    async def _execute_llm(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理execute、llm相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        task = step.get("task", "")
        result = await self._call_llm_api(task, context)
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
        处理execute、llm、query相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        query = step.get("query", "")
        result = await self._call_llm_api(query, context)
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
        处理execute、llm、explain相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        target = step.get("target", "")
        result = await self._call_llm_api(f"Explain: {target}", context)
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
        处理execute、llm、chat相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
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
        """
        处理retry、step相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        logger.info(f"Retrying step: {step.get('action')}")
        return await self.execute_step(step, context)
    
    async def record_experience_feedback(
        self,
        experience_id: int,
        success: bool,
        db: Session
    ) -> None:
        """
        处理record、experience、feedback相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        try:
            manager = ExperienceManager(db)
            await manager.update_experience_quality(
                experience_id=experience_id,
                success=success
            )
        except Exception as e:
            logger.opt(exception=True).error(f"记录经验反馈失败: {e}")

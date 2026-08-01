"""执行层稳定兼容门面，只负责协作者装配与旧入口代理。"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Callable, Dict, Optional

from loguru import logger

from core.execution_configuration import ExecutionConfigurationMixin
from core.execution_model_runtime import ExecutionModelRuntimeMixin
from core.execution_prompt_builder import (
    ExecutionPromptBuilder,
    _build_onion_fact_set,
    _build_profile_context,
    _build_profile_facts_context,
    _load_onion_profile,
    build_recent_short_term_memories_prompt,
)
from core.execution_step_runtime import ExecutionStepRuntimeMixin
from core.execution_support import (
    MAX_TOOL_EVENT_RESULT_CHARS,
    MAX_TOOL_RESULT_CHARS,
    _handle_audit_task_result,
    resolve_max_tool_call_rounds,
    validate_parameters_against_schema,
)
from core.execution_tool_runtime import ExecutionToolRuntimeMixin
from core.litellm_adapter import litellm_chat_completion, litellm_chat_completion_stream


class ExecutionLayer(
    ExecutionConfigurationMixin,
    ExecutionModelRuntimeMixin,
    ExecutionToolRuntimeMixin,
    ExecutionStepRuntimeMixin,
):
    """保留既有执行层接口，并把具体职责委托给内部协作者。"""

    def __init__(self):
        """
        初始化执行层：注册默认供应商端点映射、API Key 字段映射、
        工具执行幂等缓存（LRU，上限由 settings.TOOL_EXECUTION_CACHE_SIZE 控制）。
        """
        self.prompt_builder = ExecutionPromptBuilder()
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

    @staticmethod
    def _get_llm_completion_callable():
        """返回当前模块暴露的非流式模型调用函数，保留测试替换能力。"""
        return litellm_chat_completion

    @staticmethod
    def _get_llm_stream_callable():
        """返回当前模块暴露的流式模型调用函数，保留测试替换能力。"""
        return litellm_chat_completion_stream


Executor = ExecutionLayer

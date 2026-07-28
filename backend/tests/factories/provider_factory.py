"""
测试供应商配置数据工厂，生成标准化的供应商/模型配置字典。
用于模拟 API 配置页的供应商数据。
"""
import uuid
from typing import Optional, Dict, Any, List


DEFAULT_PROVIDERS = ["openai", "deepseek", "anthropic", "google", "zhipu", "qwen"]


def create_test_provider_config(
    provider_id: Optional[str] = None,
    provider_name: Optional[str] = None,
    api_endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
    selected_models: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    创建测试供应商配置字典。

    参数：
        provider_id: 供应商 ID（如 openai/deepseek）
        provider_name: 供应商显示名称
        api_endpoint: API 端点 URL
        api_key: API 密钥
        selected_models: 已选模型列表
    """
    pid = provider_id or "openai"
    name = provider_name or pid.capitalize()
    default_endpoints = {
        "openai": "https://api.openai.com/v1",
        "deepseek": "https://api.deepseek.com/v1",
        "anthropic": "https://api.anthropic.com/v1",
        "google": "https://generativelanguage.googleapis.com/v1",
        "zhipu": "https://open.bigmodel.cn/api/paas/v4",
        "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    }
    default_models = {
        "openai": ["gpt-4o", "gpt-4o-mini"],
        "deepseek": ["deepseek-chat", "deepseek-reasoner"],
        "anthropic": ["claude-sonnet-4-20250514"],
        "google": ["gemini-2.5-flash"],
        "zhipu": ["glm-4-flash"],
        "qwen": ["qwen-turbo"],
    }
    return {
        "provider_id": pid,
        "provider_name": name,
        "api_endpoint": api_endpoint or default_endpoints.get(pid, "https://api.example.com/v1"),
        "api_key": api_key or f"sk-test-{uuid.uuid4().hex[:16]}",
        "selected_models": selected_models or default_models.get(pid, ["default-model"]),
        "custom_model": None,
        "icon_url": None,
    }


def create_test_provider_config_dict(
    provider_id: str = "openai",
    api_endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """创建轻量供应商配置字典（用于 API 请求体）。"""
    return create_test_provider_config(
        provider_id=provider_id,
        api_endpoint=api_endpoint,
        api_key=api_key,
    )

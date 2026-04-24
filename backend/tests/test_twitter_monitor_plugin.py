"""
Twitter 监控插件的单元测试。
覆盖摘要素材输出模式与通用帮助信息行为。
"""

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_plugin_path = Path(__file__).resolve().parents[2] / "plugins" / "twitter-monitor" / "src" / "index.py"
_spec = importlib.util.spec_from_file_location("twitter_monitor_plugin", _plugin_path)
_module = importlib.util.module_from_spec(_spec)
sys.modules["backend.plugins.base_plugin"] = importlib.import_module("plugins.base_plugin")
_spec.loader.exec_module(_module)
TwitterMonitorPlugin = _module.TwitterMonitorPlugin


@pytest.fixture
def plugin(tmp_path: Path):
    """创建隔离数据目录下的插件实例。"""
    plugin_instance = TwitterMonitorPlugin(
        config={
            "twitter_api_key": "",
            "monitored_users": "OpenAI,AnthropicAI",
            "tweets_per_user": 8,
            "storage_mode": "both",
        }
    )
    plugin_instance.data_dir = tmp_path / "data"
    plugin_instance.daily_dir = plugin_instance.data_dir / "daily"
    plugin_instance.latest_path = plugin_instance.data_dir / "latest.json"
    plugin_instance.initialize()
    return plugin_instance


def _build_tweet(tweet_id: str, user_name: str, text: str, likes: int, retweets: int, replies: int) -> dict:
    """构造测试用推文数据。"""
    return {
        "id": tweet_id,
        "text": text,
        "created_at": f"2026-04-1{tweet_id}T08:00:00",
        "url": f"https://x.com/{user_name}/status/{tweet_id}",
        "author": {
            "user_name": user_name,
            "name": user_name,
        },
        "metrics": {
            "likes": likes,
            "retweets": retweets,
            "replies": replies,
        },
    }


def test_summarize_twitter_tweets_returns_inline_summary_context(plugin):
    """总结工具应返回给当前模型直接使用的摘要素材，而不是调用独立总结模型。"""
    tweets = [
        _build_tweet("1", "OpenAI", "发布了新的 API 更新说明", 12, 5, 2),
        _build_tweet("2", "AnthropicAI", "发布了新版 Claude 工具能力", 30, 11, 4),
    ]
    plugin._write_json_payload(plugin.latest_path, "latest", tweets)

    result = plugin.summarize_twitter_tweets(source_type="latest", limit=10)

    assert result["status"] == "success"
    assert result["summary_mode"] == "current_model"
    assert "不要再调用额外总结模型" in result["summary_guidance"]
    assert "AI 行业速报编辑" in result["summary_role"]
    assert any("新开源模型" in rule for rule in result["summary_priority_rules"])
    assert any("第一部分只输出整体结论" in rule for rule in result["summary_output_rules"])
    assert any("全中文输出" in rule for rule in result["summary_language_rules"])
    assert "示例输出" in result["summary_prompt_template"]
    assert "只在推文直接提及或明显暗示发布" in result["summary_context"]
    assert result["count"] == 2
    assert len(result["digest"]) == 2
    assert result["top_tweets"][0]["id"] == "2"
    assert result["tweets"][0]["id"] == "1"


def test_get_help_masks_sensitive_config_and_lists_tools(plugin):
    """通用帮助输出应隐藏敏感配置，并列出插件工具。"""
    plugin.config["twitter_api_key"] = "secret-value"

    result = plugin.get_help()

    assert result["status"] == "success"
    assert result["plugin"] == "twitter-monitor"
    assert result["configuration"]["twitter_api_key"]["configured"] is True
    assert result["configuration"]["twitter_api_key"]["masked"] == "***"
    assert any(tool["name"] == "fetch_twitter_tweets" for tool in result["tools"])
    assert any(tool["name"] == "summarize_twitter_tweets" for tool in result["tools"])
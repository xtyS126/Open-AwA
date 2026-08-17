"""执行层提示构建协作者的架构契约测试。"""

from __future__ import annotations

import inspect

from core.executor import ExecutionLayer


def test_execution_layer_installs_prompt_builder_collaborator() -> None:
    """执行层必须显式持有独立提示构建协作者。"""
    layer = ExecutionLayer()

    assert layer.prompt_builder.__class__.__name__ == "ExecutionPromptBuilder"


def test_execution_layer_message_builder_is_compatibility_delegate() -> None:
    """兼容方法只负责委托，不得重新承载提示拼装职责。"""
    source = inspect.getsource(ExecutionLayer._build_messages_with_history)

    assert "self.prompt_builder.build_messages(" in source
    assert len(source.splitlines()) <= 8


def test_prompt_cache_applied_for_anthropic() -> None:
    """验证 Anthropic 供应商的消息被附加 cache_control。"""
    from core.execution_prompt_builder import _apply_prompt_cache

    messages = [
        {"role": "system", "content": "系统提示"},
        {"role": "user", "content": "用户消息"},
    ]
    context = {"provider": "anthropic"}

    _apply_prompt_cache(messages, context)

    # 首个 system 消息应转为 content blocks 格式并附带 cache_control
    assert isinstance(messages[0]["content"], list)
    assert messages[0]["content"][0]["cache_control"] == {"type": "ephemeral"}

    # 最后 user 消息应附带 cache_control
    assert isinstance(messages[1]["content"], list)
    assert messages[1]["content"][0]["cache_control"] == {"type": "ephemeral"}


def test_prompt_cache_skipped_for_non_anthropic() -> None:
    """验证非 Anthropic 供应商不附加 cache_control。"""
    from core.execution_prompt_builder import _apply_prompt_cache

    messages = [
        {"role": "system", "content": "系统提示"},
        {"role": "user", "content": "用户消息"},
    ]
    context = {"provider": "openai"}

    _apply_prompt_cache(messages, context)

    # 消息内容应保持原始字符串格式
    assert isinstance(messages[0]["content"], str)
    assert isinstance(messages[1]["content"], str)


def test_prompt_cache_reset_baseline() -> None:
    """验证缓存基线重置时插入空 system 断点。"""
    from core.execution_prompt_builder import _apply_prompt_cache

    messages = [
        {"role": "system", "content": "系统提示"},
        {"role": "user", "content": "用户消息"},
    ]
    context = {"provider": "anthropic", "_reset_cache_baseline": True}

    _apply_prompt_cache(messages, context)

    # 首个 system 消息前应插入空 system 断点（含 cache_control）
    assert messages[0]["role"] == "system"
    assert messages[0]["content"][0]["text"] == ""
    assert messages[0]["content"][0]["cache_control"] == {"type": "ephemeral"}

    # 原始 system 消息仍在（索引 1），作为新缓存基线起点，不附加 cache_control
    assert messages[1]["role"] == "system"
    assert messages[1]["content"] == "系统提示"

    # user 消息仍被标记 cache_control
    assert isinstance(messages[2]["content"], list)
    assert messages[2]["content"][0]["cache_control"] == {"type": "ephemeral"}


def test_prompt_cache_empty_messages() -> None:
    """验证空消息列表不抛异常。"""
    from core.execution_prompt_builder import _apply_prompt_cache

    messages: list = []
    context = {"provider": "anthropic"}

    _apply_prompt_cache(messages, context)
    assert messages == []


def test_prompt_cache_already_content_blocks() -> None:
    """验证已是 content blocks 格式的消息不被重复包装。"""
    from core.execution_prompt_builder import _apply_prompt_cache

    messages = [
        {"role": "system", "content": [{"type": "text", "text": "已格式化"}]},
        {"role": "user", "content": "用户消息"},
    ]
    context = {"provider": "anthropic"}

    _apply_prompt_cache(messages, context)

    # 已是 content blocks 的 system 消息保持不变
    assert isinstance(messages[0]["content"], list)
    assert len(messages[0]["content"]) == 1

    # user 消息仍被转换
    assert isinstance(messages[1]["content"], list)
    assert messages[1]["content"][0]["cache_control"] == {"type": "ephemeral"}

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

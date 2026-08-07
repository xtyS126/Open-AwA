"""
魔术命令 fail-closed 测试（删除兜底后的错误路径）。

覆盖：
- trigger_compact 的 LLM 调用显式失败（非 ok 结果）时，_compaction_llm_call
  抛错向上传播（不再返回空串）；CompactionManager 的 generate_summary 以断路器
  契约捕获后返回结构化失败，路由层显式返回 success=False 而非假成功。
  （magic_commands.py 曾以 "" 静默降级，摘要为空仍报 success=True。）
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core.context.token_budget as token_budget_module  # noqa: E402
import core.executor as executor_module  # noqa: E402
import memory.manager as memory_manager_module  # noqa: E402
from api.routes.magic_commands import (  # noqa: E402
    MagicCommandCompactRequest,
    trigger_compact,
)


class _FakeMessage:
    """模拟短期记忆消息对象。"""

    def __init__(self, role: str, content: str) -> None:
        self.role = role
        self.content = content


class _FakeMemoryManager:
    """返回大量消息，确保触发压缩分支。"""

    async def get_short_term_memories(self, session_id: str, limit: int = 100):
        return [
            _FakeMessage("user", f"这是第 {i} 条用于触发上下文压缩的对话内容，内容足够长以超过缓冲阈值")
            for i in range(100)
        ]


class _FakeTokenBudget:
    """小窗口模型：任何历史都超过压缩阈值。

    注意：compaction_manager 在路由内懒加载导入，其模块级 _token_budget
    会拿到本 fake 实例，因此必须提供 estimate_tokens。
    """

    max_tokens = 2000

    def __init__(self, *args, **kwargs) -> None:
        pass

    def count_messages(self, history) -> int:
        return 5000

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


class _FakeExecutionLayer:
    """LLM 调用显式失败（非 ok 结果）。"""

    async def _call_llm_api(self, prompt: str, ctx: dict):
        return {"ok": False, "error": "model unavailable"}


async def test_trigger_compact_returns_false_when_llm_call_fails(monkeypatch):
    """LLM 调用显式失败时返回 success=False（禁止空串静默降级为假成功）。"""
    monkeypatch.setattr(memory_manager_module, "MemoryManager", _FakeMemoryManager)
    monkeypatch.setattr(token_budget_module, "TokenBudget", _FakeTokenBudget)
    monkeypatch.setattr(executor_module, "ExecutionLayer", _FakeExecutionLayer)

    body = MagicCommandCompactRequest(session_id="default")
    current_user = SimpleNamespace(id="user-1", username="tester")

    result = await trigger_compact(body, current_user=current_user)

    assert result["success"] is False
    assert result["compressed"] is False
    assert "摘要生成失败" in result["message"]

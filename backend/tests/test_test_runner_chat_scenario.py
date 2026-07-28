"""测试场景执行器的非流式聊天判定测试。"""

from types import SimpleNamespace

import core.agent as agent_module
from api.routes.test_runner import _run_chat_nonstream, _timed_run


def test_chat_scenario_accepts_completed_response(monkeypatch) -> None:
    """只有成功终态且正文非空时，聊天场景才应通过。"""

    class FakeAgent:
        async def process(self, user_input, context):
            return {"status": "completed", "response": "功能测试通过"}

    monkeypatch.setattr(agent_module, "AIAgent", FakeAgent)

    detail, message = _run_chat_nonstream(
        SimpleNamespace(),
        SimpleNamespace(id="user-1", username="tester"),
    )

    assert detail["status"] == "completed"
    assert detail["response_preview"] == "功能测试通过"
    assert "聊天响应正常" in message


def test_chat_scenario_rejects_error_text_as_success(monkeypatch) -> None:
    """错误终态即使带有文本，也不得被 run-all 统计为通过。"""

    class FakeAgent:
        async def process(self, user_input, context):
            return {
                "status": "error",
                "response": "Error: 未配置模型 API Key",
                "error": "未配置模型 API Key",
            }

    monkeypatch.setattr(agent_module, "AIAgent", FakeAgent)

    result = _timed_run(
        "chat-nonstream",
        "非流式聊天",
        "AI聊天",
        _run_chat_nonstream,
        SimpleNamespace(),
        SimpleNamespace(id="user-1", username="tester"),
    )

    assert result.status == "fail"
    assert "未配置模型 API Key" in result.message

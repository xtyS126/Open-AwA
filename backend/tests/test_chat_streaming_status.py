import pytest

from api.services.chat_protocol import build_sse_response
from core.agent import AIAgent


@pytest.mark.asyncio
async def test_build_sse_response_passthrough_status_and_disable_buffering():
    """
    SSE 响应应透传阶段状态事件，并携带禁用代理缓冲所需的响应头。
    """

    async def fake_stream():
        yield {
            "type": "status",
            "phase": "planning",
            "message": "正在生成执行计划",
        }

    response = await build_sse_response(fake_stream())

    chunks: list[str] = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunks.append(chunk.decode("utf-8"))
        else:
            chunks.append(chunk)

    body = "".join(chunks)

    assert 'data: {"type": "status", "phase": "planning", "message": "正在生成执行计划"}\n\n' in body
    assert body.endswith('data: [DONE]\n\n')
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"


@pytest.mark.asyncio
async def test_ai_agent_process_stream_emits_status_before_plan(monkeypatch):
    """
    流式处理在生成计划前应先发出阶段状态，避免前端长时间收不到首包。
    """

    agent = AIAgent()

    async def fake_inject_runtime_capabilities(context):
        return None

    async def fake_build_conversation_history(session_id):
        return []

    async def fake_recognize_intent(user_input):
        return "chat"

    async def fake_extract_entities(user_input):
        return {}

    async def fake_retrieve_relevant_experiences(**kwargs):
        return []

    async def fake_retrieve_relevant_memories(**kwargs):
        return []

    async def fake_create_plan(intent, entities, context):
        return {
            "intent": "chat",
            "steps": [
                {
                    "step": 1,
                    "action": "llm_chat",
                    "message": context.get("message", ""),
                    "purpose": "对话交流",
                }
            ],
            "requires_confirmation": False,
        }

    async def fake_auto_execute_skills_and_plugins(intent, entities, context):
        return {"skills": [], "plugins": []}

    monkeypatch.setattr(agent, "_inject_runtime_capabilities", fake_inject_runtime_capabilities)
    monkeypatch.setattr(agent, "_build_conversation_history", fake_build_conversation_history)
    monkeypatch.setattr(agent, "_retrieve_relevant_experiences", fake_retrieve_relevant_experiences)
    monkeypatch.setattr(agent, "_retrieve_relevant_memories", fake_retrieve_relevant_memories)
    monkeypatch.setattr(agent, "_auto_execute_skills_and_plugins", fake_auto_execute_skills_and_plugins)
    monkeypatch.setattr(agent, "_schedule_record", lambda **kwargs: None)
    monkeypatch.setattr(agent.comprehension, "recognize_intent", fake_recognize_intent)
    monkeypatch.setattr(agent.comprehension, "extract_entities", fake_extract_entities)
    monkeypatch.setattr(agent.planner, "create_plan", fake_create_plan)

    stream = agent.process_stream("你好", {"session_id": "session-1"})
    events = []

    async for event in stream:
        events.append(event)
        if event.get("type") == "plan":
            break

    await stream.aclose()

    assert events[0]["type"] == "status"
    assert events[0]["phase"] == "starting"
    assert any(event.get("type") == "status" and event.get("phase") == "planning" for event in events[:-1])
    assert events[-1]["type"] == "plan"


@pytest.mark.asyncio
async def test_ai_agent_process_stream_replays_reasoning_content_after_tool_call(monkeypatch):
    """
    思考模式下，工具回环前应把上一轮 assistant 的 reasoning_content 回传给模型。
    """

    agent = AIAgent()
    captured_tool_messages = {"value": None}
    stream_call_count = {"value": 0}

    async def fake_inject_runtime_capabilities(context):
        return None

    async def fake_build_conversation_history(session_id):
        return []

    async def fake_recognize_intent(user_input):
        return "chat"

    async def fake_extract_entities(user_input):
        return {}

    async def fake_create_plan(intent, entities, context):
        return {
            "intent": "chat",
            "steps": [
                {
                    "step": 1,
                    "action": "llm_chat",
                    "message": context.get("message", ""),
                    "purpose": "对话交流",
                }
            ],
            "requires_confirmation": False,
        }

    async def fake_stream_call(prompt, context):
        stream_call_count["value"] += 1
        if stream_call_count["value"] == 1:
            yield {"content": "我先查一下。", "reasoning_content": "需要先调用工具。"}
            yield {
                "type": "tool_calls",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "plugin_demo__lookup",
                            "arguments": '{"query":"OpenAI"}',
                        },
                    }
                ],
            }
            return

        captured_tool_messages["value"] = context.get("_tool_messages")
        yield {"content": "查询完成。", "reasoning_content": ""}

    async def fake_execute_tool_call(tool_call, context):
        return {"ok": True, "result": {"answer": "done"}}

    monkeypatch.setattr(agent, "_inject_runtime_capabilities", fake_inject_runtime_capabilities)
    monkeypatch.setattr(agent, "_build_conversation_history", fake_build_conversation_history)
    monkeypatch.setattr(agent.comprehension, "recognize_intent", fake_recognize_intent)
    monkeypatch.setattr(agent.comprehension, "extract_entities", fake_extract_entities)
    monkeypatch.setattr(agent.planner, "create_plan", fake_create_plan)
    monkeypatch.setattr(agent.executor, "_call_llm_api_stream", fake_stream_call)
    monkeypatch.setattr(agent.executor, "_execute_tool_call", fake_execute_tool_call)

    events = []
    async for event in agent.process_stream(
        "帮我查 OpenAI 信息",
        {
            "session_id": "session-2",
            "thinking_enabled": True,
            "thinking_depth": 1,
        },
    ):
        events.append(event)

    assert stream_call_count["value"] == 2
    assert captured_tool_messages["value"] is not None
    assistant_message = captured_tool_messages["value"][0]
    tool_message = captured_tool_messages["value"][1]
    assert assistant_message["role"] == "assistant"
    assert assistant_message["content"] == "我先查一下。"
    assert assistant_message["reasoning_content"] == "需要先调用工具。"
    assert assistant_message["tool_calls"][0]["function"]["name"] == "plugin_demo__lookup"
    assert tool_message["role"] == "tool"
    assert any(event.get("content") == "查询完成。" for event in events)

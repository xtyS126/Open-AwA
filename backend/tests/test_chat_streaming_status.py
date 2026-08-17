import asyncio
from unittest.mock import AsyncMock

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

    monkeypatch.setattr(agent, "_inject_runtime_capabilities", fake_inject_runtime_capabilities)
    monkeypatch.setattr(agent, "_build_conversation_history", fake_build_conversation_history)
    monkeypatch.setattr(agent, "_retrieve_relevant_experiences", fake_retrieve_relevant_experiences)
    monkeypatch.setattr(agent, "_retrieve_relevant_memories", fake_retrieve_relevant_memories)
    monkeypatch.setattr(agent, "_schedule_record", lambda **kwargs: None)
    monkeypatch.setattr(agent.turn_coordinator, "recognize_intent", fake_recognize_intent)
    monkeypatch.setattr(agent.turn_coordinator, "extract_entities", fake_extract_entities)
    monkeypatch.setattr(agent.turn_coordinator, "create_plan", fake_create_plan)

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
async def test_ai_agent_process_stream_emits_starting_before_slow_magic_command(monkeypatch):
    """首个流式状态不得被耗时的魔法命令处理阻塞。"""

    agent = AIAgent()

    async def slow_magic_command(user_input, context):
        await asyncio.sleep(0.2)
        return {
            "command_name": "help",
            "success": True,
            "message": "帮助信息",
        }

    monkeypatch.setattr(agent, "_check_and_handle_magic_command", slow_magic_command)

    stream = agent.process_stream("/help", {"session_id": "session-ttft"})
    first_event = await asyncio.wait_for(anext(stream), timeout=0.05)
    await stream.aclose()

    assert first_event["type"] == "status"
    assert first_event["phase"] == "starting"


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
    monkeypatch.setattr(agent.turn_coordinator, "recognize_intent", fake_recognize_intent)
    monkeypatch.setattr(agent.turn_coordinator, "extract_entities", fake_extract_entities)
    monkeypatch.setattr(agent.turn_coordinator, "create_plan", fake_create_plan)
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


@pytest.mark.asyncio
async def test_ai_agent_process_stream_forwards_foreground_subagent_events_before_tool_completion(monkeypatch):
    """前台子代理事件应在工具完成前实时转发到主 SSE 流。"""

    agent = AIAgent()
    stream_call_count = {"value": 0}
    captured_tool_messages = {"value": None}

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
                    "purpose": "调度前台子代理",
                }
            ],
            "requires_confirmation": False,
        }

    async def fake_stream_call(prompt, context):
        stream_call_count["value"] += 1
        if stream_call_count["value"] == 1:
            yield {
                "type": "tool_calls",
                "tool_calls": [
                    {
                        "id": "call_subagent_1",
                        "type": "function",
                        "function": {
                            "name": "task_spawn_agent",
                            "arguments": '{"agent_type":"Explore","prompt":"执行子任务","description":"前台子代理","provider":"openai","model":"gpt-4o-mini"}',
                        },
                    }
                ],
            }
            return

        captured_tool_messages["value"] = context.get("_tool_messages")
        yield {"content": "主代理继续回复。", "reasoning_content": ""}

    async def fake_execute_tool_call(tool_call, context, on_subagent_event=None):
        assert callable(on_subagent_event)
        await on_subagent_event({
            "type": "subagent_start",
            "agent_id": "agt_fg_stream_1",
            "agent_type": "Explore",
            "description": "前台子代理",
        })
        await on_subagent_event({
            "type": "agent_message",
            "agent_id": "agt_fg_stream_1",
            "agent_type": "Explore",
            "message": "子代理实时输出",
        })
        await on_subagent_event({
            "type": "subagent_stop",
            "agent_id": "agt_fg_stream_1",
            "agent_type": "Explore",
            "state": "completed",
            "summary": "子代理摘要",
        })
        return {
            "ok": True,
            "result": {
                "agent_id": "agt_fg_stream_1",
                "run_mode": "foreground",
                "status": "completed",
                "summary": "子代理摘要",
                "message": "子代理摘要",
            },
            "tool_name": "task_spawn_agent",
        }

    monkeypatch.setattr(agent, "_inject_runtime_capabilities", fake_inject_runtime_capabilities)
    monkeypatch.setattr(agent, "_build_conversation_history", fake_build_conversation_history)
    monkeypatch.setattr(agent.turn_coordinator, "recognize_intent", fake_recognize_intent)
    monkeypatch.setattr(agent.turn_coordinator, "extract_entities", fake_extract_entities)
    monkeypatch.setattr(agent.turn_coordinator, "create_plan", fake_create_plan)
    monkeypatch.setattr(agent.executor, "_call_llm_api_stream", fake_stream_call)
    monkeypatch.setattr(agent.executor, "_execute_tool_call", fake_execute_tool_call)

    events = []
    async for event in agent.process_stream(
        "请派生前台子代理",
        {
            "session_id": "session-subagent-foreground",
            "provider": "openai",
            "model": "gpt-4o-mini",
        },
    ):
        events.append(event)

    event_types = [event.get("type") for event in events]
    assert event_types.count("subagent_start") == 1
    assert event_types.count("agent_message") == 1
    assert event_types.count("subagent_stop") == 1

    subagent_stop_index = next(index for index, event in enumerate(events) if event.get("type") == "subagent_stop")
    tool_completed_index = next(
        index for index, event in enumerate(events)
        if event.get("type") == "tool" and event.get("tool", {}).get("status") == "completed"
    )

    assert subagent_stop_index < tool_completed_index
    assert captured_tool_messages["value"] is not None
    assert any(
        message.get("role") == "tool" and "子代理摘要" in str(message.get("content") or "")
        for message in captured_tool_messages["value"]
    )
    assert any(event.get("content") == "主代理继续回复。" for event in events)


@pytest.mark.asyncio
async def test_ai_agent_process_stream_allows_more_than_five_tool_rounds(monkeypatch):
    """
    多轮工具调用超过 5 轮时不应被固定上限提前截断。
    """

    agent = AIAgent()
    stream_call_count = {"value": 0}
    tool_message_counts: list[int] = []

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
                    "purpose": "连续调用工具",
                }
            ],
            "requires_confirmation": False,
        }

    async def fake_stream_call(prompt, context):
        stream_call_count["value"] += 1
        tool_message_counts.append(len(context.get("_tool_messages", [])))
        if stream_call_count["value"] <= 6:
            yield {"content": f"第{stream_call_count['value']}轮。", "reasoning_content": ""}
            yield {
                "type": "tool_calls",
                "tool_calls": [
                    {
                        "id": f"call_{stream_call_count['value']}",
                        "type": "function",
                        "function": {
                            "name": "plugin_demo__loop",
                            "arguments": "{}",
                        },
                    }
                ],
            }
            return

        yield {"content": "第七轮完成。", "reasoning_content": ""}

    async def fake_execute_tool_call(tool_call, context):
        return {"ok": True, "result": {"tool_id": tool_call.get("id"), "status": "completed"}}

    monkeypatch.setattr(agent, "_inject_runtime_capabilities", fake_inject_runtime_capabilities)
    monkeypatch.setattr(agent, "_build_conversation_history", fake_build_conversation_history)
    monkeypatch.setattr(agent.turn_coordinator, "recognize_intent", fake_recognize_intent)
    monkeypatch.setattr(agent.turn_coordinator, "extract_entities", fake_extract_entities)
    monkeypatch.setattr(agent.turn_coordinator, "create_plan", fake_create_plan)
    monkeypatch.setattr(agent.executor, "_call_llm_api_stream", fake_stream_call)
    monkeypatch.setattr(agent.executor, "_execute_tool_call", fake_execute_tool_call)

    events = []
    async for event in agent.process_stream("连续调用 6 次工具", {"session_id": "session-3"}):
        events.append(event)

    assert stream_call_count["value"] == 7
    assert tool_message_counts[:3] == [0, 2, 4]
    assert any(event.get("content") == "第七轮完成。" for event in events)


@pytest.mark.asyncio
async def test_build_sse_response_forwards_structured_error_from_chunk():
    """
    生成器 yield 出结构化错误 chunk（含 error dict）时，
    SSE 应透传底层 error code 和 message，不统一显示「流式响应异常，请重试」。
    """

    async def fake_stream_with_structured_error():
        # 模拟 executor 返回的 {"ok": False, "error": {...}} 结构
        yield {
            "ok": False,
            "error": {
                "code": "llm_api_key_stale",
                "message": "API Key 已失效，请在设置页重新录入",
            },
        }

    response = await build_sse_response(fake_stream_with_structured_error())

    chunks: list[str] = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunks.append(chunk.decode("utf-8"))
        else:
            chunks.append(chunk)

    body = "".join(chunks)

    # 应包含与底层一致的 code 和 message
    assert "llm_api_key_stale" in body
    assert "API Key 已失效，请在设置页重新录入" in body
    # 不应回退为通用错误消息
    assert "流式响应异常，请重试" not in body

    # 验证 SSE event 格式：data: {"type": "error", "error": {"code": ..., "message": ...}}
    assert 'data: {"type": "error", "error": {"code": "llm_api_key_stale", "message": "API Key 已失效，请在设置页重新录入"}}' in body
    # 应以 [DONE] 结束
    assert body.endswith("data: [DONE]\n\n")


@pytest.mark.asyncio
async def test_build_sse_response_forwards_error_from_type_error_chunk():
    """
    生成器 yield 出 type=error + message 字符串的 chunk 时，
    SSE 应提取 message 透传，code 回退为 stream_internal_error。
    """
    async def fake_stream_with_type_error():
        yield {
            "type": "error",
            "message": "上游模型超时，请稍后重试",
        }

    response = await build_sse_response(fake_stream_with_type_error())

    chunks: list[str] = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunks.append(chunk.decode("utf-8"))
        else:
            chunks.append(chunk)

    body = "".join(chunks)

    # 应透传 message，code 回退为 stream_internal_error
    assert "stream_internal_error" in body
    assert "上游模型超时，请稍后重试" in body
    assert "流式响应异常，请重试" not in body


@pytest.mark.asyncio
async def test_build_sse_response_forwards_error_from_generator_exception():
    """
    生成器抛异常时（异常 args[0] 为 dict 形式的错误结构），
    SSE 应从异常中提取 error code 和 message 透传给客户端。
    """
    async def fake_stream_that_raises():
        yield {"type": "status", "phase": "starting"}
        # 模拟 agent 抛出携带结构化错误信息的异常
        raise Exception({
            "ok": False,
            "error": {
                "code": "llm_api_key_decrypt_failed",
                "message": "API Key 解密失败，请重新录入",
            },
        })

    response = await build_sse_response(fake_stream_that_raises())

    chunks: list[str] = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunks.append(chunk.decode("utf-8"))
        else:
            chunks.append(chunk)

    body = "".join(chunks)

    # 应从异常中提取 code 和 message 透传
    assert "llm_api_key_decrypt_failed" in body
    assert "API Key 解密失败，请重新录入" in body
    assert "流式响应异常，请重试" not in body
    # 应以 [DONE] 结束
    assert body.endswith("data: [DONE]\n\n")


@pytest.mark.asyncio
async def test_build_sse_response_falls_back_for_plain_exception():
    """
    生成器抛普通异常（无结构化错误信息）时，
    SSE 应回退为 stream_internal_error + str(exc)，而非统一显示「流式响应异常，请重试」。
    """
    async def fake_stream_with_plain_exception():
        yield {"type": "status", "phase": "starting"}
        raise RuntimeError("数据库连接失败")

    response = await build_sse_response(fake_stream_with_plain_exception())

    chunks: list[str] = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunks.append(chunk.decode("utf-8"))
        else:
            chunks.append(chunk)

    body = "".join(chunks)

    # 应回退为 stream_internal_error + 异常 message
    assert "stream_internal_error" in body
    assert "数据库连接失败" in body
    # str(exc) 非空时不应使用通用兜底消息
    assert "流式响应异常，请重试" not in body
    # 应以 [DONE] 结束
    assert body.endswith("data: [DONE]\n\n")


@pytest.mark.asyncio
async def test_ai_agent_process_stream_persists_pending_background_subagent_exchange(monkeypatch):
    """后台子代理让流提前结束前，必须持久化原问题、思考和工具事件。"""
    agent = AIAgent()

    async def fake_inject_runtime_capabilities(context):
        return None

    async def fake_build_conversation_history(session_id):
        return []

    async def fake_recognize_intent(user_input):
        return {"type": "chat", "action": "respond"}

    async def fake_extract_entities(user_input):
        return {}

    async def fake_create_plan(intent, entities, context):
        return {"intent": "chat", "steps": [], "requires_confirmation": False}

    async def fake_stream_call(prompt, context):
        yield {"content": "", "reasoning_content": "需要交给子代理处理。"}
        yield {
            "type": "tool_calls",
            "tool_calls": [{
                "id": "call-subagent-background",
                "type": "function",
                "function": {
                    "name": "task_spawn_agent",
                    "arguments": '{"agent_type":"Explore","prompt":"执行任务","description":"后台检索"}',
                },
            }],
        }

    async def fake_execute_tool_call(tool_call, context, on_subagent_event=None):
        return {
            "ok": True,
            "result": {
                "agent_id": "agt-background-1",
                "run_mode": "background",
                "status": "running",
            },
            "tool_name": "task_spawn_agent",
        }

    monkeypatch.setattr(agent, "_inject_runtime_capabilities", fake_inject_runtime_capabilities)
    monkeypatch.setattr(agent, "_build_conversation_history", fake_build_conversation_history)
    monkeypatch.setattr(agent, "_retrieve_relevant_experiences", AsyncMock(return_value=[]))
    monkeypatch.setattr(agent, "_retrieve_relevant_memories", AsyncMock(return_value=[]))
    monkeypatch.setattr(agent.turn_coordinator, "recognize_intent", fake_recognize_intent)
    monkeypatch.setattr(agent.turn_coordinator, "extract_entities", fake_extract_entities)
    monkeypatch.setattr(agent.turn_coordinator, "create_plan", fake_create_plan)
    monkeypatch.setattr(agent.executor, "_call_llm_api_stream", fake_stream_call)
    monkeypatch.setattr(agent.executor, "_execute_tool_call", fake_execute_tool_call)
    monkeypatch.setattr(agent.feedback, "update_memory", AsyncMock())

    events = [event async for event in agent.process_stream(
        "请查找完整视频列表",
        {"session_id": "session-background", "user_id": "user-1"},
    )]

    assert any(event.get("phase") == "waiting_subagents" for event in events)
    agent.feedback.update_memory.assert_awaited_once()
    persisted = agent.feedback.update_memory.await_args.kwargs
    assert persisted["user_input"] == "请查找完整视频列表"
    assert persisted["response"] == ""
    assert persisted["reasoning_content"] == "需要交给子代理处理。"
    assert persisted["tool_events"][0]["id"] == "call-subagent-background"

"""
微信自动回复后端测试。

这些用例重点覆盖：
1. 自动回复闭环是否能正常拉取、生成并发送。
2. 微信渠道是否会过滤思维链内容。
3. 游标与消息幂等状态是否能在重复轮询或服务重建后保持一致。
"""

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_current_user, get_db
from api.routes import weixin as weixin_routes
from api.services.weixin_auto_reply import (
    WeixinAutoReplyService,
    build_weixin_reply_text,
)
from config.security import encrypt_secret_value
from core.agent import AIAgent
from db.models import Base, WeixinBinding, WeixinAutoReplyRule
from main import app
from skills.weixin_skill_adapter import WeixinSkillAdapter


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)


def override_get_db():
    """提供测试隔离数据库会话。"""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def override_get_current_user():
    """提供固定测试用户。"""

    class DummyUser:
        id = "user-1"
        username = "testuser"

    return DummyUser()


def _reset_bindings_table() -> None:
    """每个测试前后清理微信绑定表。"""
    db = TestingSessionLocal()
    try:
        db.query(WeixinBinding).delete()
        db.query(WeixinAutoReplyRule).delete()
        db.commit()
    finally:
        db.close()


def _create_binding() -> None:
    """插入一条已绑定的微信账号记录。"""
    db = TestingSessionLocal()
    try:
        db.add(
            WeixinBinding(
                user_id="user-1",
                weixin_account_id="acc-1",
                token=encrypt_secret_value("plain-token"),
                base_url="https://wx.example.com",
                bot_type="3",
                channel_version="1.0.2",
                binding_status="bound",
                weixin_user_id="wx-owner-1",
            )
        )
        db.commit()
    finally:
        db.close()


def _build_service(tmp_path: Path, ai_reply_generator):
    """构造使用临时状态目录的自动回复服务。"""
    adapter = WeixinSkillAdapter(project_root=str(tmp_path))
    return WeixinAutoReplyService(
        adapter=adapter,
        session_factory=TestingSessionLocal,
        ai_reply_generator=ai_reply_generator,
        poll_interval_seconds=1,
    )


@contextmanager
def _test_client(service: WeixinAutoReplyService):
    """为 API 测试临时注入依赖与自动回复管理器。"""
    previous_overrides = dict(app.dependency_overrides)
    previous_manager = weixin_routes._AUTO_REPLY_MANAGER
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    weixin_routes._AUTO_REPLY_MANAGER = service
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides = previous_overrides
        weixin_routes._AUTO_REPLY_MANAGER = previous_manager


@pytest.fixture(autouse=True)
def reset_state():
    """保证每个测试从干净的数据库状态开始。"""
    _reset_bindings_table()
    yield
    _reset_bindings_table()


def test_build_weixin_reply_text_filters_reasoning_content():
    """验证微信渠道只保留最终答案，不暴露思维链。"""
    reply = build_weixin_reply_text(
        {
            "response": "<think>内部推理</think>\n最终答案：你好，这里是最终回复。",
            "reasoning_content": "不允许发送到微信",
        }
    )
    assert reply == "你好，这里是最终回复。"


@pytest.mark.asyncio
async def test_auto_reply_rule_engine(tmp_path, monkeypatch):
    """验证自动回复规则引擎优先于 AI。"""
    _create_binding()
    
    db = TestingSessionLocal()
    try:
        rule1 = WeixinAutoReplyRule(
            user_id="user-1",
            rule_name="Keyword Test",
            match_type="keyword",
            match_pattern="规则测试",
            reply_content="触发关键词规则",
            priority=10
        )
        rule2 = WeixinAutoReplyRule(
            user_id="user-1",
            rule_name="Regex Test",
            match_type="regex",
            match_pattern=r"正则.*测试",
            reply_content="触发正则规则",
            priority=5
        )
        db.add(rule1)
        db.add(rule2)
        db.commit()
    finally:
        db.close()

    class DummyAdapter(WeixinSkillAdapter):
        def __init__(self):
            super().__init__(project_root=str(tmp_path))
            self.get_updates_calls = 0
            self.send_calls = []

        async def get_updates(self, runtime, cursor, persist_cursor):
            self.get_updates_calls += 1
            if self.get_updates_calls == 1:
                return {
                    "cursor": "cursor-1",
                    "response": {
                        "msgs": [
                            {
                                "message_id": "msg-1",
                                "from_user_id": "user-A",
                                "context_token": "token-1",
                                "text": "这是一条规则测试消息",
                            },
                            {
                                "message_id": "msg-2",
                                "from_user_id": "user-B",
                                "context_token": "token-2",
                                "text": "这是一个正则表达式测试",
                            },
                            {
                                "message_id": "msg-3",
                                "from_user_id": "user-C",
                                "context_token": "token-3",
                                "text": "这是普通消息，不会触发规则",
                            }
                        ]
                    }
                }
            return {"cursor": cursor, "response": {"msgs": []}}

        async def send_text_message(self, runtime, payload):
            self.send_calls.append(payload)
            return {"request": payload}

    dummy_adapter = DummyAdapter()
    
    async def dummy_ai_generator(db_session, binding, inbound):
        return {"response": "AI生成的回复"}

    manager = WeixinAutoReplyService(
        adapter=dummy_adapter,
        session_factory=TestingSessionLocal,
    )
    
    # 将 AI 生成器替换，以便验证 fallback
    original_default_generator = manager._default_ai_reply_generator
    async def mock_generator(db_session, binding, inbound):
        # 让默认生成器中用 mock AI Agent 替代真实 Agent 的过程有点麻烦，直接使用 manager._default_ai_reply_generator 并且 mock AIAgent
        pass
    
    class MockAIAgent:
        def __init__(self, db_session=None):
            pass
        async def process(self, text, context):
            return {"response": "AI生成的回复"}

    monkeypatch.setattr("api.services.weixin_auto_reply.AIAgent", MockAIAgent)

    result = await manager.process_once("user-1")
    assert result["ok"] is True
    assert result["processed"] == 3
    
    assert len(dummy_adapter.send_calls) == 3
    assert dummy_adapter.send_calls[0]["text"] == "触发关键词规则"
    assert dummy_adapter.send_calls[1]["text"] == "触发正则规则"
    assert dummy_adapter.send_calls[2]["text"] == "AI生成的回复"


def test_build_weixin_reply_text_truncates_chinese_on_character_boundary():
    """验证中文回复按字符边界截断，不会产生半个字符的脏结果。"""
    reply = build_weixin_reply_text(
        {
            "response": "你好世界测试文本",
        },
        max_length=5,
    )
    assert reply == "你好世界测"
    assert reply.encode("utf-8").decode("utf-8") == "你好世界测"


@pytest.mark.asyncio
async def test_default_ai_reply_generator_strips_reasoning_content_and_sets_final_only(tmp_path, monkeypatch):
    """验证默认 AI 生成器会携带 final_only 上下文，并兜底移除返回结果中的思维链字段。"""
    _create_binding()
    service = _build_service(tmp_path, None)
    captured = {}

    async def fake_process(self, user_input, context):
        captured["user_input"] = user_input
        captured["context"] = dict(context)
        return {
            "status": "completed",
            "response": "最终答案：仅保留最终回复",
            "reasoning_content": "不应继续向下游暴露",
            "results": [
                {
                    "type": "execution",
                    "result": {
                        "response": "内部执行结果",
                        "reasoning_content": "嵌套思维链",
                    },
                }
            ],
        }

    monkeypatch.setattr(AIAgent, "process", fake_process)

    db = TestingSessionLocal()
    try:
        binding = db.query(WeixinBinding).filter(WeixinBinding.user_id == "user-1").first()
        result = await service._default_ai_reply_generator(
            db,
            binding,
            {
                "text": "帮我回复一下",
                "message_id": "msg-final-only",
                "context_token": "ctx-final-only",
                "from_user_id": "friend-final-only",
            },
        )
    finally:
        db.close()

    assert captured["user_input"] == "帮我回复一下"
    assert captured["context"]["output_mode"] == "final_only"
    assert captured["context"]["suppress_reasoning"] is True
    assert result["response"] == "最终答案：仅保留最终回复"
    assert "reasoning_content" not in result
    assert "reasoning_content" not in result["results"][0]["result"]


@pytest.mark.asyncio
async def test_auto_reply_processes_text_message_and_advances_cursor(tmp_path, monkeypatch):
    """验证文本消息能完成自动回复闭环，并在成功后推进游标。"""
    _create_binding()

    async def fake_ai_reply(db, binding, inbound):
        return {
            "response": "<think>不应下发</think>\n最终答案：已收到你的消息。",
            "reasoning_content": "隐藏思维链",
        }

    service = _build_service(tmp_path, fake_ai_reply)
    sent_messages = []

    async def fake_get_updates(config, cursor="", persist_cursor=True):
        return {
            "response": {
                "msgs": [
                    {
                        "message_id": "msg-1",
                        "from_user_id": "friend-1",
                        "context_token": "ctx-1",
                        "item_list": [{"text_item": {"text": "你好"}}],
                    }
                ]
            },
            "cursor": "cursor-1",
        }

    async def fake_send_text_message(config, payload):
        sent_messages.append(payload)
        return {"request": payload, "response": {"errcode": 0}}

    monkeypatch.setattr(service.adapter, "get_updates", fake_get_updates)
    monkeypatch.setattr(service.adapter, "send_text_message", fake_send_text_message)

    result = await service.process_once("user-1")

    assert result["ok"] is True
    assert result["processed"] == 1
    assert result["cursor_advanced"] is True
    assert service.adapter.load_cursor("acc-1") == "cursor-1"
    assert sent_messages == [
        {
            "to_user_id": "friend-1",
            "context_token": "ctx-1",
            "text": "已收到你的消息。",
        }
    ]

    status = service.get_status("user-1")
    assert status["binding_ready"] is True
    assert status["last_replied_user_id"] == "friend-1"
    assert status["processed_message_count"] == 1


@pytest.mark.asyncio
async def test_auto_reply_skips_invalid_messages_and_deduplicates_processed_message(tmp_path, monkeypatch):
    """验证缺字段消息会跳过，已发送成功的消息不会重复回发。"""
    _create_binding()

    async def fake_ai_reply(db, binding, inbound):
        return {"response": "最终答案：收到"}

    service = _build_service(tmp_path, fake_ai_reply)
    send_calls = []

    async def fake_get_updates(config, cursor="", persist_cursor=True):
        return {
            "response": {
                "msgs": [
                    {
                        "message_id": "skip-1",
                        "context_token": "ctx-missing-user",
                        "item_list": [{"text_item": {"text": "这条应被跳过"}}],
                    },
                    {
                        "message_id": "msg-dup",
                        "from_user_id": "friend-2",
                        "context_token": "ctx-dup",
                        "item_list": [{"text_item": {"text": "第一条可回复消息"}}],
                    },
                ]
            },
            "cursor": "cursor-dup",
        }

    async def fake_send_text_message(config, payload):
        send_calls.append(payload)
        return {"request": payload, "response": {"errcode": 0}}

    monkeypatch.setattr(service.adapter, "get_updates", fake_get_updates)
    monkeypatch.setattr(service.adapter, "send_text_message", fake_send_text_message)

    first_result = await service.process_once("user-1")
    second_result = await service.process_once("user-1")

    assert first_result["processed"] == 1
    assert first_result["skipped"] == 1
    assert second_result["duplicates"] == 1
    assert len(send_calls) == 1
    assert send_calls[0]["text"] == "收到"


@pytest.mark.asyncio
async def test_auto_reply_restores_cursor_after_service_recreation(tmp_path, monkeypatch):
    """验证服务重建后会从持久化游标继续轮询，而不是回到空游标。"""
    _create_binding()

    async def fake_ai_reply(db, binding, inbound):
        return {"response": "最终答案：恢复成功"}

    first_service = _build_service(tmp_path, fake_ai_reply)

    async def first_get_updates(config, cursor="", persist_cursor=True):
        return {
            "response": {
                "msgs": [
                    {
                        "message_id": "msg-recover-1",
                        "from_user_id": "friend-3",
                        "context_token": "ctx-recover-1",
                        "item_list": [{"text_item": {"text": "第一轮消息"}}],
                    }
                ]
            },
            "cursor": "cursor-saved",
        }

    async def fake_send_text_message(config, payload):
        return {"request": payload, "response": {"errcode": 0}}

    monkeypatch.setattr(first_service.adapter, "get_updates", first_get_updates)
    monkeypatch.setattr(first_service.adapter, "send_text_message", fake_send_text_message)

    first_result = await first_service.process_once("user-1")
    assert first_result["cursor"] == "cursor-saved"

    seen = {"cursor": None}
    second_service = _build_service(tmp_path, fake_ai_reply)

    async def second_get_updates(config, cursor="", persist_cursor=True):
        seen["cursor"] = cursor
        return {"response": {"msgs": []}, "cursor": "cursor-next"}

    monkeypatch.setattr(second_service.adapter, "get_updates", second_get_updates)
    monkeypatch.setattr(second_service.adapter, "send_text_message", fake_send_text_message)

    second_result = await second_service.process_once("user-1")

    assert seen["cursor"] == "cursor-saved"
    assert second_result["cursor"] == "cursor-next"
    assert second_service.adapter.load_cursor("acc-1") == "cursor-next"


@pytest.mark.asyncio
async def test_auto_reply_keeps_cursor_when_processing_fails(tmp_path, monkeypatch):
    """验证处理失败时不会推进游标，避免消息丢失。"""
    _create_binding()

    async def fake_ai_reply(db, binding, inbound):
        return {"response": "最终答案：这次发送会失败"}

    service = _build_service(tmp_path, fake_ai_reply)

    async def fake_get_updates(config, cursor="", persist_cursor=True):
        return {
            "response": {
                "msgs": [
                    {
                        "message_id": "msg-error",
                        "from_user_id": "friend-4",
                        "context_token": "ctx-error",
                        "item_list": [{"text_item": {"text": "需要重试的消息"}}],
                    }
                ]
            },
            "cursor": "cursor-error",
        }

    async def failing_send_text_message(config, payload):
        raise RuntimeError("upstream send failed")

    monkeypatch.setattr(service.adapter, "get_updates", fake_get_updates)
    monkeypatch.setattr(service.adapter, "send_text_message", failing_send_text_message)

    result = await service.process_once("user-1")

    assert result["ok"] is False
    assert result["errors"] == 1
    assert result["cursor_advanced"] is False
    assert service.adapter.load_cursor("acc-1") == ""


def test_auto_reply_status_and_process_once_routes(tmp_path, monkeypatch):
    """验证自动回复状态接口和单次处理接口可正常联通管理器。"""
    _create_binding()

    async def fake_ai_reply(db, binding, inbound):
        return {"response": "最终答案：测试"}

    service = _build_service(tmp_path, fake_ai_reply)

    async def fake_process_once(user_id):
        return {
            "ok": True,
            "status": "ok",
            "processed": 0,
            "skipped": 0,
            "duplicates": 0,
            "errors": 0,
            "cursor_advanced": True,
            "cursor": "cursor-route",
        }

    monkeypatch.setattr(service, "process_once", fake_process_once)

    with _test_client(service) as client:
        status_response = client.get("/api/weixin/auto-reply/status")
        assert status_response.status_code == 200
        status_data = status_response.json()
        assert status_data["binding_status"] == "bound"
        assert status_data["binding_ready"] is True
        assert status_data["auto_reply_running"] is False

        process_response = client.post("/api/weixin/auto-reply/process-once")
        assert process_response.status_code == 200
        assert process_response.json()["cursor"] == "cursor-route"

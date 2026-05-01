"""
为达到 90%+ 覆盖率补充的后端单元测试。
"""

import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.services.weixin_auto_reply import (
    _truncate_text,
    extract_weixin_text,
    build_weixin_message_id,
    sanitize_weixin_reply_text,
    build_weixin_reply_text,
    normalize_inbound_message,
    WeixinAutoReplyService,
    DEFAULT_AUTO_REPLY_FALLBACK_TEXT,
)
from db.models import Base, WeixinBinding, WeixinAutoReplyRule
from skills.weixin_skill_adapter import WeixinSkillAdapter, WeixinAdapterError, WeixinRuntimeConfig

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

@pytest.fixture(autouse=True)
def reset_db():
    db = TestingSessionLocal()
    db.query(WeixinBinding).delete()
    db.query(WeixinAutoReplyRule).delete()
    db.commit()
    db.close()
    yield

def test_truncate_text():
    assert _truncate_text("abcd", 3) == "..."

def test_extract_weixin_text_edge_cases():
    assert extract_weixin_text("not_a_dict") == ""
    assert extract_weixin_text({"msg": "not_a_dict"}) == ""
    assert extract_weixin_text({"msg": {"item_list": "not_a_list"}}) == ""
    assert extract_weixin_text({"item_list": ["not_a_dict", {"text_item": "not_a_dict"}, {"text": "hello"}]}) == "hello"

def test_build_weixin_message_id_fallback():
    assert build_weixin_message_id("not_a_dict") == ""
    # Test fallback hash creation
    msg = {
        "from_user_id": "u1",
        "context_token": "c1",
        "text": "hello",
        "create_time": 12345,
        "timestamp": 12345,
    }
    msg_id = build_weixin_message_id(msg)
    assert msg_id.startswith("wxmsg-")

def test_sanitize_weixin_reply_text_edge_cases():
    assert sanitize_weixin_reply_text("") == ""
    assert sanitize_weixin_reply_text("推理过程\n正文") == "正文"

def test_build_weixin_reply_text_fallback():
    assert build_weixin_reply_text({}) == DEFAULT_AUTO_REPLY_FALLBACK_TEXT

def test_normalize_inbound_message_edge_cases():
    msg1 = {"from_user_id": "u1"}
    res1 = normalize_inbound_message(msg1)
    assert res1["skip_reason"] == "missing_context_token"

    msg2 = {"from_user_id": "u1", "context_token": "c1"}
    res2 = normalize_inbound_message(msg2)
    assert res2["skip_reason"] == "missing_text"

@pytest.mark.asyncio
async def test_start_stop_restart(tmp_path):
    db = TestingSessionLocal()
    db.add(
        WeixinBinding(
            user_id="u1",
            weixin_account_id="acc1",
            token="token",
            binding_status="bound",
        )
    )
    db.commit()
    db.close()

    adapter = WeixinSkillAdapter(project_root=str(tmp_path))
    service = WeixinAutoReplyService(adapter=adapter, session_factory=TestingSessionLocal)
    
    # Mock loop to avoid infinite loop
    async def mock_run_loop(user_id):
        await asyncio.sleep(0.1)
    
    with patch.object(service, "_run_loop", new=mock_run_loop):
        res1 = await service.start("u1")
        assert res1["auto_reply_enabled"] is True
        
        # Start again should just return status
        res2 = await service.start("u1")
        assert res2["auto_reply_enabled"] is True

        res3 = await service.stop("u1")
        assert res3["auto_reply_enabled"] is False

        res4 = await service.restart("u1")
        assert res4["auto_reply_enabled"] is True
        
        await service.stop("u1")

def test_get_status_unbound(tmp_path):
    service = WeixinAutoReplyService(adapter=WeixinSkillAdapter(project_root=str(tmp_path)), session_factory=TestingSessionLocal)
    status = service.get_status("u_unbound")
    assert status["binding_status"] == "unbound"

@pytest.mark.asyncio
async def test_process_once_locked_exceptions(tmp_path):
    db = TestingSessionLocal()
    db.add(
        WeixinBinding(
            user_id="u1",
            weixin_account_id="acc1",
            token="token",
            binding_status="bound",
        )
    )
    db.commit()
    db.close()

    adapter = WeixinSkillAdapter(project_root=str(tmp_path))
    service = WeixinAutoReplyService(adapter=adapter, session_factory=TestingSessionLocal)

    # test WEIXIN_TIMEOUT
    adapter.get_updates = AsyncMock(side_effect=WeixinAdapterError("WEIXIN_TIMEOUT", "timeout"))
    res = await service._process_once_locked("u1")
    assert res["ok"] is True
    assert res["status"] == "timeout"

    # test adapter error
    adapter.get_updates = AsyncMock(side_effect=WeixinAdapterError("SOME_ERROR", "error"))
    res2 = await service._process_once_locked("u1")
    assert res2["ok"] is False
    assert res2["status"] == "error"

    # test no binding record found in DB during process (deleted)
    adapter.get_updates = AsyncMock(return_value={"response": {"msgs": [{"id": "1", "text": "a"}]}})
    
    with patch.object(service, "_load_runtime_or_raise") as mock_load:
        mock_load.return_value = WeixinRuntimeConfig(
            account_id="acc1",
            token="token",
            base_url="url",
            bot_type="3",
            channel_version="1",
            timeout_seconds=10,
            user_id="u1",
            binding_status="bound"
        )
        db = TestingSessionLocal()
        db.query(WeixinBinding).delete()
        db.commit()
        db.close()
        
        with pytest.raises(ValueError, match="未找到微信绑定记录"):
            await service._process_once_locked("u1")

@pytest.mark.asyncio
async def test_ai_generator_edge_cases(tmp_path):
    db = TestingSessionLocal()
    db.add(
        WeixinBinding(
            user_id="u1",
            weixin_account_id="acc1",
            token="token",
            binding_status="bound",
        )
    )
    db.add(WeixinAutoReplyRule(user_id="u1", rule_name="r1", match_type="regex", match_pattern="[invalid", reply_content=""))
    db.commit()
    binding = db.query(WeixinBinding).filter_by(user_id="u1").first()

    service = WeixinAutoReplyService(adapter=WeixinSkillAdapter(project_root=str(tmp_path)), session_factory=TestingSessionLocal)
    
    # Test regex error and non-dict agent result
    with patch("api.services.weixin_auto_reply.AIAgent") as MockAgent:
        mock_agent_inst = MockAgent.return_value
        mock_agent_inst.process = AsyncMock(return_value="plain_string")
        
        res = await service._default_ai_reply_generator(db, binding, {"text": "hello", "message_id": "1", "context_token": "c", "from_user_id": "f"})
        assert res["response"] == "plain_string"
    
    db.close()

def test_load_runtime_exceptions(tmp_path):
    service = WeixinAutoReplyService(adapter=WeixinSkillAdapter(project_root=str(tmp_path)), session_factory=TestingSessionLocal)
    
    with pytest.raises(ValueError, match="请先完成微信绑定"):
        service._load_runtime_or_raise("no_user")

    db = TestingSessionLocal()
    db.add(
        WeixinBinding(
            user_id="u_unbound",
            weixin_account_id="acc1",
            token="token",
            binding_status="unbound",
        )
    )
    db.commit()
    db.close()
    with pytest.raises(ValueError, match="尚未处于已绑定状态"):
        service._load_runtime_or_raise("u_unbound")

def test_state_edge_cases(tmp_path):
    adapter = WeixinSkillAdapter(project_root=str(tmp_path))
    service = WeixinAutoReplyService(adapter=adapter, session_factory=TestingSessionLocal, max_processed_messages=1)
    
    # _load_state not dict
    adapter.load_auto_reply_state = lambda x: None
    state = service._load_state("acc")
    assert state["enabled"] is False

    # _get_processed_messages not dict
    assert service._get_processed_messages({"processed_messages": []}) == {}

    # _save_state truncation
    adapter.save_auto_reply_state = lambda x, y: None
    service._save_state("acc", {"processed_messages": {
        "1": {"updated_at_ts": 1},
        "2": {"updated_at_ts": 2}
    }})

    # _record_processed_message empty id
    st = {}
    service._record_processed_message(st, {}, status="ok")
    assert st == {}

def test_clear_runtime_state(tmp_path):
    adapter = WeixinSkillAdapter(project_root=str(tmp_path))
    service = WeixinAutoReplyService(adapter=adapter, session_factory=TestingSessionLocal)
    with patch.object(adapter, "clear_account_state") as mock_clear:
        service.clear_runtime_state("acc")
        mock_clear.assert_called_once_with("acc")

@pytest.mark.asyncio
async def test_process_once_invalid_msg(tmp_path):
    db = TestingSessionLocal()
    db.add(
        WeixinBinding(
            user_id="u1",
            weixin_account_id="acc1",
            token="token",
            binding_status="bound",
        )
    )
    db.commit()
    db.close()

    adapter = WeixinSkillAdapter(project_root=str(tmp_path))
    service = WeixinAutoReplyService(adapter=adapter, session_factory=TestingSessionLocal)

    adapter.get_updates = AsyncMock(return_value={"response": {"msgs": ["not_a_dict"]}})
    res = await service._process_once_locked("u1")
    assert res["skipped"] == 1

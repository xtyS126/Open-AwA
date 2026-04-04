import uuid

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base, Skill
from skills.skill_engine import SkillEngine
from skills.weixin_skill_adapter import (
    WeixinSkillAdapter,
    WeixinRuntimeConfig,
    DEFAULT_QR_BASE_URL,
    SESSION_EXPIRED_ERRCODE,
)


def _build_weixin_skill_config(token: str = "test-token"):
    return {
        "name": "weixin_dispatch",
        "version": "1.0.0",
        "description": "weixin adapter dispatch for skill engine",
        "adapter": "weixin",
        "weixin": {
            "account_id": "test-account",
            "token": token,
            "base_url": "https://ilinkai.weixin.qq.com",
            "user_id": "wx-user-default",
            "binding_status": "bound"
        }
    }


def _create_db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)
    return session_local()


@pytest.mark.asyncio
async def test_weixin_adapter_fetch_login_qrcode_uses_fixed_qr_base_url(monkeypatch):
    adapter = WeixinSkillAdapter(project_root="d:/tmp/openawa")
    captured = {}

    async def fake_api_get(self, base_url, endpoint, params=None, timeout_seconds=15, extra_headers=None):
        captured["base_url"] = base_url
        captured["endpoint"] = endpoint
        captured["params"] = params
        captured["timeout_seconds"] = timeout_seconds
        return {"qrcode": "qr-fixed"}

    monkeypatch.setattr(WeixinSkillAdapter, "_api_get", fake_api_get)

    result = await adapter.fetch_login_qrcode(
        base_url="https://custom.weixin.qq.com",
        bot_type="9",
        timeout_seconds=12
    )

    assert result["qrcode"] == "qr-fixed"
    assert captured == {
        "base_url": DEFAULT_QR_BASE_URL,
        "endpoint": "ilink/bot/get_bot_qrcode",
        "params": {"bot_type": "9"},
        "timeout_seconds": 5,
    }


@pytest.mark.asyncio
async def test_weixin_adapter_fetch_qrcode_status_uses_provided_poll_base_url(monkeypatch):
    adapter = WeixinSkillAdapter(project_root="d:/tmp/openawa")
    captured = {}

    async def fake_api_get(self, base_url, endpoint, params=None, timeout_seconds=15, extra_headers=None):
        captured["base_url"] = base_url
        captured["endpoint"] = endpoint
        captured["params"] = params
        captured["timeout_seconds"] = timeout_seconds
        captured["extra_headers"] = extra_headers
        return {"status": "waiting"}

    monkeypatch.setattr(WeixinSkillAdapter, "_api_get", fake_api_get)

    result = await adapter.fetch_qrcode_status(
        base_url="https://redirect.weixin.qq.com",
        qrcode="qr-redirect",
        timeout_seconds=38
    )

    assert result["status"] == "waiting"
    assert captured == {
        "base_url": "https://redirect.weixin.qq.com",
        "endpoint": "ilink/bot/get_qrcode_status",
        "params": {"qrcode": "qr-redirect"},
        "timeout_seconds": 38,
        "extra_headers": {"iLink-App-ClientVersion": "1"},
    }


@pytest.mark.asyncio
async def test_weixin_adapter_returns_structured_error_when_missing_config_fields(monkeypatch):
    adapter = WeixinSkillAdapter(project_root="d:/tmp/openawa")

    monkeypatch.setattr(
        adapter,
        "check_health",
        lambda config: {"ok": True, "issues": [], "suggestions": [], "diagnostics": {}}
    )

    result = await adapter.execute(
        skill_name="wx_skill",
        skill_config=_build_weixin_skill_config(token=""),
        inputs={"action": "send_message", "payload": {}},
        context={}
    )

    assert result["success"] is False
    assert result["error"]["code"] == "WEIXIN_CONFIG_MISSING_FIELDS"
    assert "token" in result["error"]["details"]["missing_fields"]


@pytest.mark.asyncio
async def test_weixin_adapter_health_check_returns_diagnostics(monkeypatch):
    adapter = WeixinSkillAdapter(project_root="d:/tmp/openawa")

    monkeypatch.setattr(
        adapter,
        "check_health",
        lambda config: {
            "ok": True,
            "issues": [],
            "suggestions": [],
            "diagnostics": {"binding_ready": True}
        }
    )

    result = await adapter.execute(
        skill_name="wx_skill",
        skill_config=_build_weixin_skill_config(),
        inputs={"action": "health_check"},
        context={}
    )

    assert result["success"] is True
    assert result["outputs"]["data"]["health"]["ok"] is True
    assert "diagnostics" in result["outputs"]["data"]["health"]


@pytest.mark.asyncio
async def test_skill_engine_routes_weixin_skill_and_records_adapter_logs(monkeypatch):
    db_session = _create_db_session()
    try:
        config = _build_weixin_skill_config()
        skill = Skill(
            id=str(uuid.uuid4()),
            name=config["name"],
            version=config["version"],
            description=config["description"],
            config=yaml.dump(config),
            category="general",
            tags="[]",
            dependencies="[]",
            author="tester",
            enabled=True,
            usage_count=0
        )
        db_session.add(skill)
        db_session.commit()

        async def fake_api_post(self, config, endpoint, body, timeout_seconds=None):
            return {"ret": 0, "endpoint": endpoint, "echo": body}

        monkeypatch.setattr(
            "skills.weixin_skill_adapter.WeixinSkillAdapter.check_health",
            lambda self, runtime: {
                "ok": True,
                "issues": [],
                "suggestions": [],
                "diagnostics": {"plugin_root_exists": True}
            }
        )
        monkeypatch.setattr(
            "skills.weixin_skill_adapter.WeixinSkillAdapter._api_post",
            fake_api_post
        )

        engine = SkillEngine(db_session)
        result = await engine.execute_skill(
            skill_name=config["name"],
            inputs={
                "action": "send_message",
                "payload": {
                    "to_user_id": "user@im.wechat",
                    "text": "hello",
                    "context_token": "ctx-token"
                }
            },
            context={}
        )

        assert result["success"] is True
        assert result["steps"][0]["tool"] == "weixin_adapter"
        assert result["outputs"]["action"] == "send_text"
        logs = engine.get_execution_logs(skill_name=config["name"], limit=20)
        event_types = {item["event_type"] for item in logs}
        assert "ADAPTER_ROUTED" in event_types
        assert "ADAPTER_EXECUTION_SUCCESS" in event_types
    finally:
        db_session.close()


@pytest.mark.asyncio
async def test_skill_engine_returns_adapter_error_and_records_failure_logs(monkeypatch):
    db_session = _create_db_session()
    try:
        config = _build_weixin_skill_config(token="")
        skill = Skill(
            id=str(uuid.uuid4()),
            name=config["name"],
            version=config["version"],
            description=config["description"],
            config=yaml.dump(config),
            category="general",
            tags="[]",
            dependencies="[]",
            author="tester",
            enabled=True,
            usage_count=0
        )
        db_session.add(skill)
        db_session.commit()

        monkeypatch.setattr(
            "skills.weixin_skill_adapter.WeixinSkillAdapter.check_health",
            lambda self, runtime: {
                "ok": True,
                "issues": [],
                "suggestions": [],
                "diagnostics": {"plugin_root_exists": True}
            }
        )

        engine = SkillEngine(db_session)
        result = await engine.execute_skill(
            skill_name=config["name"],
            inputs={"action": "send_message", "payload": {"to_user_id": "user@im.wechat", "text": "hello", "context_token": "ctx-token"}},
            context={}
        )

        assert result["success"] is False
        assert "配置不完整" in result["error"]
        logs = engine.get_execution_logs(skill_name=config["name"], limit=20)
        event_types = {item["event_type"] for item in logs}
        assert "ADAPTER_EXECUTION_FAILED" in event_types
    finally:
        db_session.close()


@pytest.mark.asyncio
async def test_weixin_adapter_get_updates_persists_sync_buf_and_context_token(monkeypatch, tmp_path):
    adapter = WeixinSkillAdapter(project_root=str(tmp_path))

    async def fake_api_post(self, config, endpoint, body, timeout_seconds=None):
        assert endpoint == "ilink/bot/getupdates"
        assert body["get_updates_buf"] == ""
        return {
            "ret": 0,
            "errcode": 0,
            "get_updates_buf": "buf-next",
            "msgs": [
                {
                    "from_user_id": "user-a",
                    "context_token": "ctx-a",
                }
            ],
        }

    monkeypatch.setattr(WeixinSkillAdapter, "_api_post", fake_api_post)

    runtime = adapter.map_skill_config(_build_weixin_skill_config())
    result = await adapter._get_updates(runtime, {})

    assert result["state"]["saved_get_updates_buf"] == "buf-next"
    assert result["state"]["stored_context_token_count"] == 1
    assert adapter._load_get_updates_buf("test-account") == "buf-next"
    assert adapter._get_context_token("test-account", "user-a") == "ctx-a"


@pytest.mark.asyncio
async def test_weixin_adapter_send_message_uses_cached_context_token(monkeypatch, tmp_path):
    adapter = WeixinSkillAdapter(project_root=str(tmp_path))
    adapter._set_context_token("test-account", "user-a", "ctx-cached")
    captured = {}

    async def fake_api_post(self, config, endpoint, body, timeout_seconds=None):
        captured["endpoint"] = endpoint
        captured["body"] = body
        return {"ret": 0}

    monkeypatch.setattr(WeixinSkillAdapter, "_api_post", fake_api_post)

    runtime = adapter.map_skill_config(_build_weixin_skill_config())
    result = await adapter._send_message(runtime, {"to_user_id": "user-a", "text": "hello"})

    assert captured["endpoint"] == "ilink/bot/sendmessage"
    assert captured["body"]["msg"]["context_token"] == "ctx-cached"
    assert result["state"]["context_token_source"] == "cache"


@pytest.mark.asyncio
async def test_weixin_adapter_session_expired_pauses_followup_requests(monkeypatch, tmp_path):
    adapter = WeixinSkillAdapter(project_root=str(tmp_path))

    async def fake_api_post(self, config, endpoint, body, timeout_seconds=None):
        return {
            "ret": SESSION_EXPIRED_ERRCODE,
            "errcode": SESSION_EXPIRED_ERRCODE,
            "errmsg": "session expired",
            "msgs": [],
        }

    monkeypatch.setattr(WeixinSkillAdapter, "_api_post", fake_api_post)
    monkeypatch.setattr(
        adapter,
        "check_health",
        lambda config: {"ok": True, "issues": [], "suggestions": [], "diagnostics": {}},
    )

    runtime = adapter.map_skill_config(_build_weixin_skill_config())
    await adapter._get_updates(runtime, {})

    result = await adapter.execute(
        skill_name="wx_skill",
        skill_config=_build_weixin_skill_config(),
        inputs={"action": "send_message", "payload": {"to_user_id": "user-a", "text": "hello", "context_token": "ctx"}},
        context={},
    )

    assert result["success"] is False
    assert result["error"]["code"] == "WEIXIN_SESSION_PAUSED"



def test_weixin_adapter_map_skill_config_reads_binding_fields():
    adapter = WeixinSkillAdapter(project_root="d:/tmp/openawa")

    runtime = adapter.map_skill_config(_build_weixin_skill_config())

    assert runtime.user_id == "wx-user-default"
    assert runtime.binding_status == "bound"
    assert adapter._is_binding_ready(runtime) is True


@pytest.mark.asyncio
async def test_weixin_adapter_send_message_generates_ilink_client_id_format(monkeypatch, tmp_path):
    adapter = WeixinSkillAdapter(project_root=str(tmp_path))
    adapter._set_context_token("test-account", "user-a", "ctx-test")
    captured = {}

    async def fake_api_post(self, config, endpoint, body, timeout_seconds=None):
        captured["client_id"] = body["msg"]["client_id"]
        return {"ret": 0}

    monkeypatch.setattr(WeixinSkillAdapter, "_api_post", fake_api_post)

    runtime = adapter.map_skill_config(_build_weixin_skill_config())
    await adapter._send_message(runtime, {"to_user_id": "user-a", "text": "test message"})

    assert captured["client_id"].startswith("ilink-")
    uuid_part = captured["client_id"][len("ilink-"):]
    assert len(uuid_part) == 8
    assert all(c in "0123456789abcdef" for c in uuid_part)


def test_weixin_adapter_check_health_validates_static_config_fields():
    adapter = WeixinSkillAdapter(project_root="d:/tmp/openawa")

    result_valid = adapter.check_health(WeixinRuntimeConfig(
        account_id="test-account",
        token="test-token",
        base_url="https://ilinkai.weixin.qq.com",
        bot_type="3",
        channel_version="1.0.2",
        timeout_seconds=15,
        user_id="wx-user",
        binding_status="bound"
    ))
    assert result_valid["ok"] is True
    assert result_valid["issues"] == []
    assert "account_id" in result_valid["diagnostics"]
    assert "base_url" in result_valid["diagnostics"]
    assert result_valid["diagnostics"]["account_id"] == "test-account"

    result_missing_account = adapter.check_health(WeixinRuntimeConfig(
        account_id="",
        token="test-token",
        base_url="https://ilinkai.weixin.qq.com",
        bot_type="3",
        channel_version="1.0.2",
        timeout_seconds=15,
        user_id="",
        binding_status="unbound"
    ))
    assert result_missing_account["ok"] is False
    assert "account_id 为空" in result_missing_account["issues"]

    result_missing_token = adapter.check_health(WeixinRuntimeConfig(
        account_id="test-account",
        token="",
        base_url="https://ilinkai.weixin.qq.com",
        bot_type="3",
        channel_version="1.0.2",
        timeout_seconds=15,
        user_id="",
        binding_status="unbound"
    ))
    assert result_missing_token["ok"] is False
    assert "token 为空" in result_missing_token["issues"]

    result_invalid_base_url = adapter.check_health(WeixinRuntimeConfig(
        account_id="test-account",
        token="test-token",
        base_url="invalid-url",
        bot_type="3",
        channel_version="1.0.2",
        timeout_seconds=15,
        user_id="",
        binding_status="unbound"
    ))
    assert result_invalid_base_url["ok"] is False
    assert "base_url 格式无效" in result_invalid_base_url["issues"]

import uuid

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base, Skill
from skills.skill_engine import SkillEngine
from skills.weixin_skill_adapter import WeixinSkillAdapter


def _build_weixin_skill_config(token: str = "test-token"):
    return {
        "name": "weixin_dispatch",
        "version": "1.0.0",
        "description": "weixin adapter dispatch for skill engine",
        "adapter": "weixin",
        "weixin": {
            "account_id": "test-account",
            "token": token,
            "base_url": "https://ilinkai.weixin.qq.com"
        }
    }


def _create_db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)
    return session_local()


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
            "diagnostics": {"node_version": "22.3.0", "plugin_root_exists": True}
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
        assert result["outputs"]["action"] == "send_message"
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

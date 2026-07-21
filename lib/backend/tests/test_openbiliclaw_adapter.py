"""OpenBiliClaw 适配层与 10 个技能 handler 的单元测试。

覆盖三个核心场景：
1. build_openclaw_skills 返回 10 个 OpenClawSkillDescriptor，name 与 spec 列表一致
2. 每个技能 handler 正确调用底层 adapter 方法，并构造正确的 request 对象
3. handler 错误处理：AdapterValidationError/AdapterOperationError 返回结构化错误，
   RuntimeError 等未预期异常应传播（不静默吞错）

测试隔离：
- mock OpenClawAdapter（vendored 上游适配层）的 10 个异步方法
- 通过 OpenBiliClawAdapter._skill_to_tool_def 验证 descriptor 转换逻辑
- vendored 包通过 sys.path 注入加载，加载失败时整个文件用 pytest.skip 跳过
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

# 将 backend 目录加入 sys.path
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# 将 vendored 包源码目录加入 sys.path，便于导入 build_openclaw_skills
_VENDORED_SRC = _BACKEND_DIR / "plugins" / "openbiliclaw_builtin" / "src"
if str(_VENDORED_SRC) not in sys.path:
    sys.path.insert(0, str(_VENDORED_SRC))

# 尝试导入 vendored 模块；缺失时跳过整个测试文件
try:
    from openbiliclaw.integrations.openclaw.errors import (  # noqa: E402
        AdapterOperationError,
        AdapterValidationError,
    )
    from openbiliclaw.integrations.openclaw.schemas import (  # noqa: E402
        AvoidanceProbeFeedbackRequest,
        ChatRequest,
        FeedbackRequest,
    )
    from openbiliclaw.integrations.openclaw.skill import (  # noqa: E402
        OpenClawSkillDescriptor,
        build_openclaw_skills,
    )
    _VENDORED_AVAILABLE = True
    _VENDORED_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # noqa: BLE001 - 捕获所有导入异常以支持降级
    _VENDORED_AVAILABLE = False
    _VENDORED_IMPORT_ERROR = exc

# 始终可导入：被测的 OpenBiliClawAdapter（仅依赖 stdlib + loguru）
from plugins.openbiliclaw_builtin.adapter import OpenBiliClawAdapter  # noqa: E402


# 全部测试用例依赖 vendored 包，缺失时整文件跳过
pytestmark = pytest.mark.skipif(
    not _VENDORED_AVAILABLE,
    reason=f"vendored openbiliclaw 包不可用: {_VENDORED_IMPORT_ERROR}",
)


# 10 个技能的预期名称（与 skill.py 中 build_openclaw_skills 的返回顺序一致）
_EXPECTED_SKILL_NAMES: List[str] = [
    "openbiliclaw_sync_account",
    "openbiliclaw_get_profile",
    "openbiliclaw_recommend",
    "openbiliclaw_submit_feedback",
    "openbiliclaw_get_delight",
    "openbiliclaw_get_runtime_status",
    "openbiliclaw_chat",
    "openbiliclaw_next_probe",
    "openbiliclaw_next_avoidance_probe",
    "openbiliclaw_respond_avoidance_probe",
]


# ---------------------------------------------------------------------------
# fixture：mock OpenClawAdapter
# ---------------------------------------------------------------------------


def _build_mock_adapter() -> MagicMock:
    """构造一个 mock OpenClawAdapter，预设 10 个异步方法的返回值。

    返回值统一使用 dataclass 实例，便于 _run_handler 通过 asdict 转换为 dict。
    """
    adapter = MagicMock()

    # sync_account 返回 SyncAccountResponse
    from openbiliclaw.integrations.openclaw.schemas import (
        AvoidanceProbeResponse,
        ChatResponse,
        DelightResponse,
        FeedbackResponse,
        InterestProbeResponse,
        ProfileResponse,
        RecommendationResponse,
        RuntimeStatusResponse,
        SyncAccountResponse,
    )

    adapter.sync_account = AsyncMock(
        return_value=SyncAccountResponse(synced=True, new_event_count=3)
    )
    adapter.get_profile = AsyncMock(
        return_value=ProfileResponse(initialized=True, personality_portrait="demo")
    )
    adapter.recommend = AsyncMock(
        return_value=RecommendationResponse(items=[])
    )
    adapter.submit_feedback = AsyncMock(
        return_value=FeedbackResponse(ok=True, recommendation_id=1, feedback_type="like")
    )
    adapter.get_delight = AsyncMock(return_value=DelightResponse(item=None))
    adapter.get_runtime_status = AsyncMock(
        return_value=RuntimeStatusResponse(
            initialized=True,
            recommendation_count=0,
            pending_signal_events=0,
            unread_count=0,
        )
    )
    adapter.chat = AsyncMock(
        return_value=ChatResponse(reply="hello", session="openclaw")
    )
    adapter.get_next_probe = AsyncMock(
        return_value=InterestProbeResponse(probe=None)
    )
    adapter.get_next_avoidance_probe = AsyncMock(
        return_value=AvoidanceProbeResponse(probe=None)
    )
    adapter.respond_avoidance_probe = AsyncMock(
        return_value=__import__(
            "openbiliclaw.integrations.openclaw.schemas",
            fromlist=["AvoidanceProbeFeedbackResponse"],
        ).AvoidanceProbeFeedbackResponse(
            ok=True, action="confirm", domain="music", reply="ok"
        )
    )
    return adapter


@pytest.fixture
def mock_openclaw_adapter() -> MagicMock:
    """提供 mock OpenClawAdapter 实例。"""
    return _build_mock_adapter()


@pytest.fixture
def skills(mock_openclaw_adapter: MagicMock) -> List[OpenClawSkillDescriptor]:
    """提供 build_openclaw_skills 返回的 10 个技能描述符。"""
    return build_openclaw_skills(mock_openclaw_adapter)


def _find_skill(skills: List[OpenClawSkillDescriptor], name: str) -> OpenClawSkillDescriptor:
    """根据 name 查找技能描述符。"""
    for skill in skills:
        if skill.name == name:
            return skill
    raise AssertionError(f"未找到技能: {name}")


# ---------------------------------------------------------------------------
# 技能列表与转换测试
# ---------------------------------------------------------------------------


def test_build_tools_returns_exactly_ten_skills(skills):
    """build_openclaw_skills 应返回恰好 10 个技能描述符。"""
    assert len(skills) == 10


def test_skill_names_match_expected(skills):
    """10 个技能的 name 应与预期列表完全一致。"""
    actual_names = [skill.name for skill in skills]
    assert actual_names == _EXPECTED_SKILL_NAMES


def test_skill_descriptors_have_handlers(skills):
    """每个技能描述符应包含可调用的 handler。"""
    for skill in skills:
        assert callable(skill.handler), f"技能 {skill.name} 的 handler 不可调用"
        assert isinstance(skill.input_schema, dict), f"技能 {skill.name} 的 input_schema 非 dict"
        assert skill.input_schema.get("type") == "object", f"技能 {skill.name} 的 input_schema.type 不是 object"


def test_skill_to_tool_def_preserves_name_and_description(skills):
    """OpenBiliClawAdapter._skill_to_tool_def 应保留 name 与 description。"""
    adapter = OpenBiliClawAdapter()
    for descriptor in skills:
        tool_def = adapter._skill_to_tool_def(descriptor)
        assert tool_def["name"] == descriptor.name
        assert tool_def["description"] == descriptor.description


def test_skill_to_tool_def_includes_parameters_schema(skills):
    """转换后的工具定义应包含 parameters 字段，且为 dict 含 type/properties。"""
    adapter = OpenBiliClawAdapter()
    for descriptor in skills:
        tool_def = adapter._skill_to_tool_def(descriptor)
        params = tool_def["parameters"]
        assert isinstance(params, dict)
        assert params.get("type") == "object"
        assert "properties" in params and isinstance(params["properties"], dict)


def test_skill_to_tool_def_preserves_handler(skills):
    """转换后的工具定义应保留原 handler 引用，便于 PluginManager 直接调用。"""
    adapter = OpenBiliClawAdapter()
    for descriptor in skills:
        tool_def = adapter._skill_to_tool_def(descriptor)
        assert tool_def["handler"] is descriptor.handler


def test_skill_to_tool_def_raises_on_missing_name():
    """descriptor.name 缺失或非字符串时应抛 ValueError。"""
    adapter = OpenBiliClawAdapter()
    bad_descriptor = MagicMock()
    bad_descriptor.name = None
    bad_descriptor.description = ""
    bad_descriptor.input_schema = {}
    bad_descriptor.handler = None

    with pytest.raises(ValueError):
        adapter._skill_to_tool_def(bad_descriptor)


def test_skill_to_tool_def_raises_on_empty_name():
    """descriptor.name 为空字符串时应抛 ValueError。"""
    adapter = OpenBiliClawAdapter()
    bad_descriptor = MagicMock()
    bad_descriptor.name = "  "
    bad_descriptor.description = ""
    bad_descriptor.input_schema = {}
    bad_descriptor.handler = None

    with pytest.raises(ValueError):
        adapter._skill_to_tool_def(bad_descriptor)


def test_skill_to_tool_def_raises_on_non_callable_handler():
    """descriptor.handler 不可调用时应抛 ValueError。"""
    adapter = OpenBiliClawAdapter()
    bad_descriptor = MagicMock()
    bad_descriptor.name = "valid_name"
    bad_descriptor.description = ""
    bad_descriptor.input_schema = {}
    bad_descriptor.handler = "not callable"

    with pytest.raises(ValueError):
        adapter._skill_to_tool_def(bad_descriptor)


def test_skill_to_tool_def_fills_default_schema_when_invalid():
    """input_schema 非 dict 时应回退为默认空 schema。"""
    adapter = OpenBiliClawAdapter()
    descriptor = MagicMock()
    descriptor.name = "valid_name"
    descriptor.description = ""
    descriptor.input_schema = None  # 非 dict
    descriptor.handler = None

    tool_def = adapter._skill_to_tool_def(descriptor)
    assert tool_def["parameters"] == {"type": "object", "properties": {}}


# ---------------------------------------------------------------------------
# handler 调用测试
# ---------------------------------------------------------------------------


def _run_handler(handler, payload: Dict[str, Any]) -> Dict[str, Any]:
    """同步执行异步 handler 并返回结果。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(handler(payload))
    finally:
        loop.close()


def test_sync_account_handler_calls_adapter_sync_account(skills, mock_openclaw_adapter):
    """sync_account handler 应调用 adapter.sync_account 一次。"""
    skill = _find_skill(skills, "openbiliclaw_sync_account")
    result = _run_handler(skill.handler, {})

    mock_openclaw_adapter.sync_account.assert_awaited_once_with()
    assert result["ok"] is True
    assert "data" in result
    assert result["data"]["synced"] is True


def test_get_profile_handler_returns_dict_with_data(skills, mock_openclaw_adapter):
    """get_profile handler 应返回 {ok: True, data: {...}} 结构。"""
    skill = _find_skill(skills, "openbiliclaw_get_profile")
    result = _run_handler(skill.handler, {})

    assert result["ok"] is True
    assert isinstance(result["data"], dict)
    assert result["data"]["initialized"] is True
    assert result["data"]["personality_portrait"] == "demo"


def test_recommend_handler_passes_limit_and_refresh(skills, mock_openclaw_adapter):
    """recommend handler 应将 limit 与 refresh_if_needed 透传给 adapter.recommend。"""
    skill = _find_skill(skills, "openbiliclaw_recommend")
    _run_handler(skill.handler, {"limit": 10, "refresh_if_needed": True})

    mock_openclaw_adapter.recommend.assert_awaited_once_with(limit=10, refresh_if_needed=True)


def test_recommend_handler_uses_default_when_payload_missing(skills, mock_openclaw_adapter):
    """payload 缺失 limit/refresh_if_needed 时应使用默认值 5 与 False。"""
    skill = _find_skill(skills, "openbiliclaw_recommend")
    _run_handler(skill.handler, {})

    mock_openclaw_adapter.recommend.assert_awaited_once_with(limit=5, refresh_if_needed=False)


def test_submit_feedback_handler_constructs_feedback_request(skills, mock_openclaw_adapter):
    """submit_feedback handler 应构造 FeedbackRequest 并透传给 adapter.submit_feedback。"""
    skill = _find_skill(skills, "openbiliclaw_submit_feedback")
    _run_handler(
        skill.handler,
        {"recommendation_id": 1, "feedback_type": "like", "note": "good"},
    )

    mock_openclaw_adapter.submit_feedback.assert_awaited_once()
    call_args = mock_openclaw_adapter.submit_feedback.await_args
    request = call_args.args[0]
    assert isinstance(request, FeedbackRequest)
    assert request.recommendation_id == 1
    assert request.feedback_type == "like"
    assert request.note == "good"


def test_chat_handler_constructs_chat_request(skills, mock_openclaw_adapter):
    """chat handler 应构造 ChatRequest 并透传给 adapter.chat。"""
    skill = _find_skill(skills, "openbiliclaw_chat")
    _run_handler(skill.handler, {"message": "hello", "session": "test"})

    mock_openclaw_adapter.chat.assert_awaited_once()
    call_args = mock_openclaw_adapter.chat.await_args
    request = call_args.args[0]
    assert isinstance(request, ChatRequest)
    assert request.message == "hello"
    assert request.session == "test"


def test_chat_handler_uses_default_session_when_missing(skills, mock_openclaw_adapter):
    """payload 缺失 session 时应使用默认值 openclaw。"""
    skill = _find_skill(skills, "openbiliclaw_chat")
    _run_handler(skill.handler, {"message": "hello"})

    call_args = mock_openclaw_adapter.chat.await_args
    request = call_args.args[0]
    assert request.session == "openclaw"


def test_respond_avoidance_probe_handler_constructs_request(skills, mock_openclaw_adapter):
    """respond_avoidance_probe handler 应构造 AvoidanceProbeFeedbackRequest。"""
    skill = _find_skill(skills, "openbiliclaw_respond_avoidance_probe")
    _run_handler(
        skill.handler,
        {"domain": "music", "response": "confirm", "message": "ok"},
    )

    mock_openclaw_adapter.respond_avoidance_probe.assert_awaited_once()
    call_args = mock_openclaw_adapter.respond_avoidance_probe.await_args
    request = call_args.args[0]
    assert isinstance(request, AvoidanceProbeFeedbackRequest)
    assert request.domain == "music"
    assert request.response == "confirm"
    assert request.message == "ok"


def test_get_delight_handler_calls_adapter_get_delight(skills, mock_openclaw_adapter):
    """get_delight handler 应调用 adapter.get_delight 一次。"""
    skill = _find_skill(skills, "openbiliclaw_get_delight")
    result = _run_handler(skill.handler, {})

    mock_openclaw_adapter.get_delight.assert_awaited_once_with()
    assert result["ok"] is True


def test_get_runtime_status_handler_calls_adapter(skills, mock_openclaw_adapter):
    """get_runtime_status handler 应调用 adapter.get_runtime_status 一次。"""
    skill = _find_skill(skills, "openbiliclaw_get_runtime_status")
    result = _run_handler(skill.handler, {})

    mock_openclaw_adapter.get_runtime_status.assert_awaited_once_with()
    assert result["ok"] is True
    assert result["data"]["initialized"] is True


def test_get_next_probe_handler_calls_adapter(skills, mock_openclaw_adapter):
    """get_next_probe handler 应调用 adapter.get_next_probe 一次。"""
    skill = _find_skill(skills, "openbiliclaw_next_probe")
    _run_handler(skill.handler, {})

    mock_openclaw_adapter.get_next_probe.assert_awaited_once_with()


def test_get_next_avoidance_probe_handler_calls_adapter(skills, mock_openclaw_adapter):
    """get_next_avoidance_probe handler 应调用 adapter.get_next_avoidance_probe 一次。"""
    skill = _find_skill(skills, "openbiliclaw_next_avoidance_probe")
    _run_handler(skill.handler, {})

    mock_openclaw_adapter.get_next_avoidance_probe.assert_awaited_once_with()


# ---------------------------------------------------------------------------
# 错误处理测试
# ---------------------------------------------------------------------------


def test_handler_returns_error_on_validation_error(skills, mock_openclaw_adapter):
    """adapter 抛 AdapterValidationError 时，handler 应返回结构化错误。"""
    mock_openclaw_adapter.sync_account = AsyncMock(
        side_effect=AdapterValidationError("invalid input")
    )

    skill = _find_skill(skills, "openbiliclaw_sync_account")
    result = _run_handler(skill.handler, {})

    assert result["ok"] is False
    assert result["error_type"] == "validation_error"
    assert "invalid input" in result["error"]


def test_handler_returns_error_on_operation_error(skills, mock_openclaw_adapter):
    """adapter 抛 AdapterOperationError 时，handler 应返回结构化错误。"""
    mock_openclaw_adapter.get_profile = AsyncMock(
        side_effect=AdapterOperationError("operation failed")
    )

    skill = _find_skill(skills, "openbiliclaw_get_profile")
    result = _run_handler(skill.handler, {})

    assert result["ok"] is False
    assert result["error_type"] == "operation_error"
    assert "operation failed" in result["error"]


def test_handler_handles_unexpected_exception(skills, mock_openclaw_adapter):
    """adapter 抛 RuntimeError 等未预期异常时，handler 不应静默吞错，应向外传播。

    vendored skill._run_handler 仅捕获 AdapterValidationError 与 AdapterOperationError，
    其他异常应直接向外抛出，由调用方（PluginManager）处理。
    """
    mock_openclaw_adapter.recommend = AsyncMock(
        side_effect=RuntimeError("unexpected failure")
    )

    skill = _find_skill(skills, "openbiliclaw_recommend")
    # 未预期异常应向外传播，不被静默吞掉
    with pytest.raises(RuntimeError, match="unexpected failure"):
        _run_handler(skill.handler, {"limit": 5})


def test_submit_feedback_handler_returns_error_on_invalid_payload(skills, mock_openclaw_adapter):
    """submit_feedback 在构造 FeedbackRequest 时校验失败应返回 validation_error 响应。

    _run_handler 会捕获 AdapterValidationError 并转换为 {ok: False, error_type: "validation_error"}，
    不向外传播异常，确保调用方拿到结构化错误响应。
    """
    skill = _find_skill(skills, "openbiliclaw_submit_feedback")
    # recommendation_id=0 触发 FeedbackRequest.__post_init__ 抛 AdapterValidationError
    result = _run_handler(
        skill.handler,
        {"recommendation_id": 0, "feedback_type": "like", "note": ""},
    )

    assert result["ok"] is False
    assert result["error_type"] == "validation_error"
    # adapter.submit_feedback 不应被调用（校验在构造 request 时已失败）
    mock_openclaw_adapter.submit_feedback.assert_not_awaited()


def test_chat_handler_returns_error_on_empty_message(skills):
    """chat handler 在 message 为空时应返回 validation_error 响应。"""
    skill = _find_skill(skills, "openbiliclaw_chat")
    result = _run_handler(skill.handler, {"message": "", "session": "openclaw"})

    assert result["ok"] is False
    assert result["error_type"] == "validation_error"


def test_respond_avoidance_probe_handler_returns_error_on_invalid_response(skills):
    """respond_avoidance_probe 在 response 非法时应返回 validation_error 响应。"""
    skill = _find_skill(skills, "openbiliclaw_respond_avoidance_probe")
    result = _run_handler(
        skill.handler,
        {"domain": "music", "response": "invalid_response", "message": ""},
    )

    assert result["ok"] is False
    assert result["error_type"] == "validation_error"


# ---------------------------------------------------------------------------
# OpenBiliClawAdapter 适配层行为测试
# ---------------------------------------------------------------------------


def test_adapter_get_tools_returns_empty_before_initialize():
    """未调用 initialize 时，get_tools 应返回空列表。"""
    adapter = OpenBiliClawAdapter()
    assert adapter.get_tools() == []


def test_adapter_get_warnings_returns_empty_before_initialize():
    """未调用 initialize 时，get_warnings 应返回空列表。"""
    adapter = OpenBiliClawAdapter()
    assert adapter.get_warnings() == []


def test_adapter_get_warnings_returns_copy():
    """get_warnings 应返回列表副本，外部修改不影响内部状态。"""
    adapter = OpenBiliClawAdapter()
    adapter._warnings.append("warning1")
    warnings = adapter.get_warnings()
    warnings.append("external")

    assert "external" not in adapter._warnings


def test_adapter_cleanup_resets_state():
    """cleanup 应清空内部状态。"""
    adapter = OpenBiliClawAdapter()
    adapter._inner = MagicMock()
    adapter._skills = [{"name": "tool1"}]
    adapter._warnings = ["warning"]

    adapter.cleanup()

    assert adapter._inner is None
    assert adapter._skills == []
    assert adapter._warnings == []


# ---------------------------------------------------------------------------
# OpenBiliClawAdapter.initialize() 降级路径测试
# ---------------------------------------------------------------------------


def _make_fake_descriptor(name: str = "fake_skill") -> Any:
    """构造一个最小的 OpenClawSkillDescriptor 兼容对象。"""
    return OpenClawSkillDescriptor(
        name=name,
        description=f"description for {name}",
        input_schema={"type": "object", "properties": {}},
        handler=None,
    )


@pytest.mark.asyncio
async def test_initialize_loads_skills_when_vendored_available(monkeypatch):
    """vendored 模块加载成功且 build_openclaw_skills 返回 descriptors 时，应注册到 _skills。"""
    adapter = OpenBiliClawAdapter()

    # 构造 mock bootstrap 与 skill 模块
    fake_bootstrap = MagicMock()
    fake_bootstrap.build_openclaw_adapter = MagicMock(return_value="fake_inner_adapter")
    fake_skill = MagicMock()
    fake_skill.build_openclaw_skills = MagicMock(
        return_value=[_make_fake_descriptor("skill_a"), _make_fake_descriptor("skill_b")]
    )

    def fake_import(module_name: str):
        if module_name.endswith(".bootstrap"):
            return fake_bootstrap
        if module_name.endswith(".skill"):
            return fake_skill
        return MagicMock()

    monkeypatch.setattr("importlib.import_module", fake_import)

    await adapter.initialize()

    # 应成功加载 2 个技能
    tools = adapter.get_tools()
    assert len(tools) == 2
    assert tools[0]["name"] == "skill_a"
    assert tools[1]["name"] == "skill_b"
    # inner adapter 应被赋值
    assert adapter._inner == "fake_inner_adapter"
    # 不应有告警
    assert adapter.get_warnings() == []


@pytest.mark.asyncio
async def test_initialize_records_warning_when_bootstrap_module_missing(monkeypatch):
    """vendored bootstrap 模块导入失败时，应记录告警并保持空 skills 列表。"""
    adapter = OpenBiliClawAdapter()

    def fake_import(module_name: str):
        if module_name.endswith(".bootstrap"):
            raise ImportError("bootstrap not found")
        return MagicMock()

    monkeypatch.setattr("importlib.import_module", fake_import)

    await adapter.initialize()

    assert adapter.get_tools() == []
    assert adapter._inner is None
    warnings = adapter.get_warnings()
    assert any("bootstrap" in w for w in warnings)


@pytest.mark.asyncio
async def test_initialize_records_warning_when_build_adapter_missing(monkeypatch):
    """bootstrap 模块缺少 build_openclaw_adapter 函数时，应记录告警。"""
    adapter = OpenBiliClawAdapter()

    fake_bootstrap = MagicMock()
    # 删除 build_openclaw_adapter 属性
    del fake_bootstrap.build_openclaw_adapter

    def fake_import(module_name: str):
        if module_name.endswith(".bootstrap"):
            return fake_bootstrap
        return MagicMock()

    monkeypatch.setattr("importlib.import_module", fake_import)

    await adapter.initialize()

    assert adapter.get_tools() == []
    warnings = adapter.get_warnings()
    assert any("build_openclaw_adapter" in w for w in warnings)


@pytest.mark.asyncio
async def test_initialize_records_warning_when_build_adapter_raises(monkeypatch):
    """build_openclaw_adapter 抛异常时，应记录告警并降级为空 skills。"""
    adapter = OpenBiliClawAdapter()

    fake_bootstrap = MagicMock()
    fake_bootstrap.build_openclaw_adapter = MagicMock(
        side_effect=RuntimeError("config not found")
    )

    def fake_import(module_name: str):
        if module_name.endswith(".bootstrap"):
            return fake_bootstrap
        return MagicMock()

    monkeypatch.setattr("importlib.import_module", fake_import)

    await adapter.initialize()

    assert adapter.get_tools() == []
    assert adapter._inner is None
    warnings = adapter.get_warnings()
    assert any("OpenClawAdapter 构造失败" in w for w in warnings)


@pytest.mark.asyncio
async def test_initialize_records_warning_when_build_skills_missing(monkeypatch):
    """skill 模块缺少 build_openclaw_skills 函数时，应记录告警。"""
    adapter = OpenBiliClawAdapter()

    fake_bootstrap = MagicMock()
    fake_bootstrap.build_openclaw_adapter = MagicMock(return_value="fake_inner")
    fake_skill = MagicMock()
    # 删除 build_openclaw_skills 属性
    del fake_skill.build_openclaw_skills

    def fake_import(module_name: str):
        if module_name.endswith(".bootstrap"):
            return fake_bootstrap
        if module_name.endswith(".skill"):
            return fake_skill
        return MagicMock()

    monkeypatch.setattr("importlib.import_module", fake_import)

    await adapter.initialize()

    # inner adapter 应已赋值（build_openclaw_adapter 成功）
    assert adapter._inner == "fake_inner"
    assert adapter.get_tools() == []
    warnings = adapter.get_warnings()
    assert any("build_openclaw_skills" in w for w in warnings)


@pytest.mark.asyncio
async def test_initialize_records_warning_when_build_skills_raises(monkeypatch):
    """build_openclaw_skills 抛异常时，应记录告警并降级为空 skills。"""
    adapter = OpenBiliClawAdapter()

    fake_bootstrap = MagicMock()
    fake_bootstrap.build_openclaw_adapter = MagicMock(return_value="fake_inner")
    fake_skill = MagicMock()
    fake_skill.build_openclaw_skills = MagicMock(
        side_effect=RuntimeError("skill build failed")
    )

    def fake_import(module_name: str):
        if module_name.endswith(".bootstrap"):
            return fake_bootstrap
        if module_name.endswith(".skill"):
            return fake_skill
        return MagicMock()

    monkeypatch.setattr("importlib.import_module", fake_import)

    await adapter.initialize()

    assert adapter.get_tools() == []
    warnings = adapter.get_warnings()
    assert any("build_openclaw_skills 调用失败" in w for w in warnings)


@pytest.mark.asyncio
async def test_initialize_records_warning_when_skills_return_non_list(monkeypatch):
    """build_openclaw_skills 返回非 list 时，应记录告警并跳过技能注册。"""
    adapter = OpenBiliClawAdapter()

    fake_bootstrap = MagicMock()
    fake_bootstrap.build_openclaw_adapter = MagicMock(return_value="fake_inner")
    fake_skill = MagicMock()
    fake_skill.build_openclaw_skills = MagicMock(return_value="not a list")

    def fake_import(module_name: str):
        if module_name.endswith(".bootstrap"):
            return fake_bootstrap
        if module_name.endswith(".skill"):
            return fake_skill
        return MagicMock()

    monkeypatch.setattr("importlib.import_module", fake_import)

    await adapter.initialize()

    assert adapter.get_tools() == []
    warnings = adapter.get_warnings()
    assert any("非列表" in w for w in warnings)


@pytest.mark.asyncio
async def test_initialize_skips_invalid_descriptor(monkeypatch):
    """单个 descriptor 转换失败时应跳过，不影响其他 descriptor 注册。"""
    adapter = OpenBiliClawAdapter()

    # 第一个 descriptor 的 name 为 None（无效），第二个正常
    invalid_descriptor = MagicMock()
    invalid_descriptor.name = None
    invalid_descriptor.description = ""
    invalid_descriptor.input_schema = {}
    invalid_descriptor.handler = None

    valid_descriptor = _make_fake_descriptor("valid_skill")

    fake_bootstrap = MagicMock()
    fake_bootstrap.build_openclaw_adapter = MagicMock(return_value="fake_inner")
    fake_skill = MagicMock()
    fake_skill.build_openclaw_skills = MagicMock(
        return_value=[invalid_descriptor, valid_descriptor]
    )

    def fake_import(module_name: str):
        if module_name.endswith(".bootstrap"):
            return fake_bootstrap
        if module_name.endswith(".skill"):
            return fake_skill
        return MagicMock()

    monkeypatch.setattr("importlib.import_module", fake_import)

    await adapter.initialize()

    # 只应注册有效的 descriptor
    tools = adapter.get_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "valid_skill"

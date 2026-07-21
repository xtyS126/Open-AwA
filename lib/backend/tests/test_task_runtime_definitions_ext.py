"""
Task 11: AgentDefinition 字段扩展测试。

覆盖范围：
1. AgentDefinition 新增字段默认值与显式赋值
2. max_turns / effort / omit_project_context / memory_scope / hooks 字段验证
3. _get_effort_config 努力程度到 LLM 参数映射
4. MaxTurnsExceededError 异常语义
"""

from __future__ import annotations

from core.task_runtime.definitions import (
    AgentDefinition,
    AgentMemoryScope,
    HookConfig,
)
from core.task_runtime.runners import (
    MaxTurnsExceededError,
    _EFFORT_CONFIG_TABLE,
    _get_effort_config,
)


# ──────────────────────────────────────────────
#  AgentDefinition 新增字段默认值
# ──────────────────────────────────────────────

def test_agent_definition_new_fields_default():
    """验证 AgentDefinition 新增字段默认值符合向后兼容预期。"""
    agent_def = AgentDefinition(name="TestAgent")
    assert agent_def.max_turns is None
    assert agent_def.effort == "medium"
    assert agent_def.omit_project_context is False
    assert agent_def.hooks == []
    assert agent_def.memory_scope == AgentMemoryScope.LOCAL


def test_agent_definition_max_turns():
    """验证 max_turns 字段可被显式设置。"""
    agent_def = AgentDefinition(name="LimitedAgent", max_turns=10)
    assert agent_def.max_turns == 10

    # None 表示不限制
    unlimited = AgentDefinition(name="UnlimitedAgent", max_turns=None)
    assert unlimited.max_turns is None


def test_agent_definition_effort():
    """验证 effort 字段接受 low/medium/high 三个值。"""
    low_effort = AgentDefinition(name="LowEffort", effort="low")
    medium_effort = AgentDefinition(name="MediumEffort", effort="medium")
    high_effort = AgentDefinition(name="HighEffort", effort="high")

    assert low_effort.effort == "low"
    assert medium_effort.effort == "medium"
    assert high_effort.effort == "high"


def test_agent_definition_omit_project_context():
    """验证 omit_project_context 字段开关行为。"""
    default_def = AgentDefinition(name="DefaultAgent")
    skip_def = AgentDefinition(name="SkipContextAgent", omit_project_context=True)

    assert default_def.omit_project_context is False
    assert skip_def.omit_project_context is True


def test_agent_definition_memory_scope():
    """验证 memory_scope 字段接受三种记忆范围。"""
    user_scope = AgentDefinition(name="UserScope", memory_scope=AgentMemoryScope.USER)
    project_scope = AgentDefinition(name="ProjectScope", memory_scope=AgentMemoryScope.PROJECT)
    local_scope = AgentDefinition(name="LocalScope", memory_scope=AgentMemoryScope.LOCAL)

    assert user_scope.memory_scope == AgentMemoryScope.USER
    assert project_scope.memory_scope == AgentMemoryScope.PROJECT
    assert local_scope.memory_scope == AgentMemoryScope.LOCAL


def test_agent_definition_hooks_field():
    """验证 hooks 字段可接受 HookConfig 列表。"""
    hooks = [
        HookConfig(event="subagent_start", handler="log_start"),
        HookConfig(event="subagent_stop", handler="log_stop"),
    ]
    agent_def = AgentDefinition(name="HookedAgent", hooks=hooks)

    assert len(agent_def.hooks) == 2
    assert agent_def.hooks[0].event == "subagent_start"
    assert agent_def.hooks[0].handler == "log_start"
    assert agent_def.hooks[1].event == "subagent_stop"
    assert agent_def.hooks[1].handler == "log_stop"


def test_agent_definition_to_dict_includes_new_fields():
    """验证 to_dict 序列化包含所有新增字段。"""
    agent_def = AgentDefinition(
        name="SerializeAgent",
        max_turns=5,
        effort="high",
        omit_project_context=True,
        hooks=[HookConfig(event="subagent_start", handler="my_handler")],
        memory_scope=AgentMemoryScope.PROJECT,
    )
    d = agent_def.to_dict()

    assert d["max_turns"] == 5
    assert d["effort"] == "high"
    assert d["omit_project_context"] is True
    assert d["memory_scope"] == "project"
    assert len(d["hooks"]) == 1
    assert d["hooks"][0] == {"event": "subagent_start", "handler": "my_handler"}


# ──────────────────────────────────────────────
#  _get_effort_config 努力程度映射
# ──────────────────────────────────────────────

def test_get_effort_config_low():
    """验证 low effort 返回低温度与小思考预算。"""
    config = _get_effort_config("low")
    assert config["temperature"] == 0.2
    assert config["thinking_budget"] == 1024


def test_get_effort_config_medium():
    """验证 medium effort 返回中等温度与思考预算。"""
    config = _get_effort_config("medium")
    assert config["temperature"] == 0.5
    assert config["thinking_budget"] == 4096


def test_get_effort_config_high():
    """验证 high effort 返回高温度与大思考预算。"""
    config = _get_effort_config("high")
    assert config["temperature"] == 0.7
    assert config["thinking_budget"] == 16384


def test_get_effort_config_unknown_falls_back_to_medium():
    """验证未知 effort 值回退到 medium 配置。"""
    config = _get_effort_config("unknown")
    assert config["temperature"] == 0.5
    assert config["thinking_budget"] == 4096


def test_get_effort_config_returns_copy():
    """验证 _get_effort_config 返回字典副本，修改不影响全局表。"""
    config = _get_effort_config("low")
    config["temperature"] = 0.99
    # 全局表不应被修改
    assert _EFFORT_CONFIG_TABLE["low"]["temperature"] == 0.2


# ──────────────────────────────────────────────
#  MaxTurnsExceededError 异常语义
# ──────────────────────────────────────────────

def test_max_turns_exceeded_error_message():
    """验证 MaxTurnsExceededError 异常携带正确的 agent_id 与 max_turns。"""
    error = MaxTurnsExceededError(agent_id="agt_test_001", max_turns=5)
    assert error.agent_id == "agt_test_001"
    assert error.max_turns == 5
    assert "agt_test_001" in str(error)
    assert "5" in str(error)


def test_max_turns_exceeded_error_is_exception():
    """验证 MaxTurnsExceededError 是 Exception 子类，可被 except Exception 捕获。"""
    error = MaxTurnsExceededError(agent_id="agt_x", max_turns=1)
    assert isinstance(error, Exception)


# ──────────────────────────────────────────────
#  AgentMemoryScope 枚举值
# ──────────────────────────────────────────────

def test_agent_memory_scope_values():
    """验证 AgentMemoryScope 枚举包含 USER/PROJECT/LOCAL 三种范围。"""
    assert AgentMemoryScope.USER.value == "user"
    assert AgentMemoryScope.PROJECT.value == "project"
    assert AgentMemoryScope.LOCAL.value == "local"


def test_agent_memory_scope_is_str_enum():
    """验证 AgentMemoryScope 是 str 枚举，可直接作为字符串使用。"""
    assert AgentMemoryScope.USER == "user"
    assert AgentMemoryScope.PROJECT == "project"
    assert AgentMemoryScope.LOCAL == "local"


# ──────────────────────────────────────────────
#  HookConfig 数据类
# ──────────────────────────────────────────────

def test_hook_config_fields():
    """验证 HookConfig 包含 event 和 handler 两个字段。"""
    hook = HookConfig(event="subagent_start", handler="my_handler")
    assert hook.event == "subagent_start"
    assert hook.handler == "my_handler"


def test_hook_config_equality():
    """验证 HookConfig 同值实例相等。"""
    hook1 = HookConfig(event="subagent_start", handler="log")
    hook2 = HookConfig(event="subagent_start", handler="log")
    assert hook1 == hook2

"""
工作流引擎单元测试，验证定义解析、步骤执行、条件分支、并行执行、子工作流组合和边界情况。
"""

from __future__ import annotations

import asyncio

import pytest

from workflow.engine import WorkflowEngine
from workflow.parser import WorkflowParser


# ==================== 工作流定义解析测试 ====================

def test_parse_valid_yaml_definition():
    """正常 YAML 格式的工作流定义应被成功解析。"""
    yaml_def = """
name: 测试工作流
description: 用于单元测试
steps:
  - id: step_1
    type: tool
    tool: calculator
    action: add
    params:
      a: 1
      b: 2
  - id: step_2
    type: tool
    tool: reporter
    action: log
"""
    parser = WorkflowParser()
    result = parser.parse_definition(yaml_def)

    assert result["name"] == "测试工作流"
    assert result["description"] == "用于单元测试"
    assert len(result["steps"]) == 2
    assert result["steps"][0]["id"] == "step_1"
    assert result["steps"][0]["type"] == "tool"
    assert result["steps"][1]["id"] == "step_2"


def test_parse_valid_json_definition():
    """JSON 格式的工作流定义应被成功解析。"""
    json_def = """
{
    "name": "JSON工作流",
    "steps": [
        {"id": "s1", "type": "tool", "tool": "echo", "action": "say"}
    ]
}
"""
    parser = WorkflowParser()
    result = parser.parse_definition(json_def)

    assert result["name"] == "JSON工作流"
    assert len(result["steps"]) == 1
    assert result["steps"][0]["id"] == "s1"


def test_parse_dict_definition():
    """直接传入 dict 格式的定义也应被正确规范化。"""
    dict_def = {
        "name": "字典工作流",
        "steps": [
            {"id": "step_a", "type": "tool", "tool": "test", "action": "run"},
        ],
    }
    parser = WorkflowParser()
    result = parser.parse_definition(dict_def)

    assert result["name"] == "字典工作流"
    assert len(result["steps"]) == 1


def test_parse_empty_steps_raises_value_error():
    """空 steps 列表应抛出 ValueError。"""
    parser = WorkflowParser()
    with pytest.raises(ValueError, match="至少需要一个步骤"):
        parser.parse_definition({"name": "空工作流", "steps": []})


def test_parse_missing_steps_raises_value_error():
    """缺少 steps 字段应抛出 ValueError。"""
    parser = WorkflowParser()
    with pytest.raises(ValueError, match="至少需要一个步骤"):
        parser.parse_definition({"name": "无步骤工作流"})


def test_parse_empty_string_raises_value_error():
    """空字符串定义应抛出 ValueError。"""
    parser = WorkflowParser()
    with pytest.raises(ValueError, match="工作流定义不能为空"):
        parser.parse_definition("")


def test_parse_non_dict_raises_value_error():
    """非对象结构的定义应抛出 ValueError。"""
    parser = WorkflowParser()
    with pytest.raises(ValueError, match="必须是对象结构"):
        parser.parse_definition("[]")


def test_parse_nested_steps_raises_value_error():
    """嵌套步骤中非 dict 元素应抛出 ValueError。"""
    parser = WorkflowParser()
    with pytest.raises(ValueError, match="第 1 个步骤必须是对象"):
        parser.parse_definition({"steps": ["not_a_dict"]})


def test_parse_auto_generate_step_id():
    """未指定 id 的步骤应自动生成 step_N 格式的 id。"""
    parser = WorkflowParser()
    result = parser.parse_definition({
        "steps": [
            {"type": "tool", "tool": "a", "action": "x"},
            {"type": "tool", "tool": "b", "action": "y"},
        ],
    })
    assert result["steps"][0]["id"] == "step_1"
    assert result["steps"][1]["id"] == "step_2"


def test_parse_default_step_type():
    """未指定 type 的步骤应默认为 'tool'。"""
    parser = WorkflowParser()
    result = parser.parse_definition({
        "steps": [{"id": "s1", "tool": "echo", "action": "say"}],
    })
    assert result["steps"][0]["type"] == "tool"


def test_parse_default_workflow_name():
    """未指定 name 时应使用默认名称。"""
    parser = WorkflowParser()
    result = parser.parse_definition({
        "steps": [{"id": "s1", "type": "tool", "tool": "x", "action": "y"}],
    })
    assert result["name"] == "unnamed_workflow"


def test_parse_condition_step_with_branches():
    """条件步骤应正确解析 on_true 和 on_false 分支。"""
    parser = WorkflowParser()
    result = parser.parse_definition({
        "steps": [{
            "id": "cond_1",
            "type": "condition",
            "expression": "context.value > 10",
            "on_true": [
                {"id": "t1", "type": "tool", "tool": "log", "action": "info"}
            ],
            "on_false": [
                {"id": "f1", "type": "tool", "tool": "log", "action": "warn"}
            ],
        }],
    })
    step = result["steps"][0]
    assert step["type"] == "condition"
    assert step["expression"] == "context.value > 10"
    assert len(step["on_true"]) == 1
    assert len(step["on_false"]) == 1
    assert step["on_true"][0]["id"] == "t1"
    assert step["on_false"][0]["id"] == "f1"


# ==================== 工作流执行测试（需要 mock 外部依赖） ====================

@pytest.fixture
def engine_no_db():
    """
    创建不带数据库会话的引擎实例，适合纯逻辑测试。
    不会落库执行记录，只测试引擎核心逻辑。
    """
    return WorkflowEngine(db_session=None, skill_engine=None)


@pytest.fixture
def mock_tool_success():
    """
    返回一个成功的工具执行 mock 结果。
    用于 monkeypatch built_in_tool_registry.execute_tool。
    """
    async def _execute(tool_name, *, action, params, config):
        return {
            "success": True,
            "tool": tool_name,
            "action": action,
            "params": params,
            "result": f"executed {tool_name}.{action}",
        }
    return _execute


@pytest.fixture
def mock_tool_failure():
    """
    返回一个失败的工具执行 mock 结果。
    """
    async def _execute(tool_name, *, action, params, config):
        return {
            "success": False,
            "tool": tool_name,
            "action": action,
            "error": f"{tool_name}.{action} 执行失败",
        }
    return _execute


@pytest.mark.asyncio
async def test_execute_simple_tool_workflow(engine_no_db, mock_tool_success, monkeypatch):
    """
    单步骤工具工作流应正常执行并返回 completed 状态。
    """
    from tools.registry import built_in_tool_registry
    monkeypatch.setattr(built_in_tool_registry, "execute_tool", mock_tool_success)

    definition = {
        "name": "简单工具流程",
        "steps": [
            {"id": "step1", "type": "tool", "tool": "echo", "action": "say", "params": {"msg": "hello"}},
        ],
    }

    result = await engine_no_db.execute_definition(definition)

    assert result["status"] == "completed"
    assert result["workflow_name"] == "简单工具流程"
    assert len(result["steps"]) == 1
    assert result["steps"][0]["success"] is True
    assert result["steps"][0]["type"] == "tool"


@pytest.mark.asyncio
async def test_execute_multiple_steps_sequential(engine_no_db, mock_tool_success, monkeypatch):
    """
    多步骤工具工作流应按顺序执行全部步骤。
    """
    from tools.registry import built_in_tool_registry
    monkeypatch.setattr(built_in_tool_registry, "execute_tool", mock_tool_success)

    definition = {
        "steps": [
            {"id": "step1", "type": "tool", "tool": "a", "action": "x"},
            {"id": "step2", "type": "tool", "tool": "b", "action": "y"},
            {"id": "step3", "type": "tool", "tool": "c", "action": "z"},
        ],
    }

    result = await engine_no_db.execute_definition(definition)

    assert result["status"] == "completed"
    assert len(result["steps"]) == 3
    assert all(s["success"] for s in result["steps"])


@pytest.mark.asyncio
async def test_execute_with_input_context(engine_no_db, mock_tool_success, monkeypatch):
    """
    input_context 应正确传递并可在步骤参数中使用占位符渲染。
    """
    from tools.registry import built_in_tool_registry
    monkeypatch.setattr(built_in_tool_registry, "execute_tool", mock_tool_success)

    definition = {
        "steps": [
            {
                "id": "step1",
                "type": "tool",
                "tool": "echo",
                "action": "say",
                "params": {"message": "{{ context.user_name }}"},
            },
        ],
    }

    result = await engine_no_db.execute_definition(
        definition,
        input_context={"user_name": "张三"},
    )

    assert result["status"] == "completed"
    assert result["steps"][0]["result"]["params"]["message"] == "张三"


@pytest.mark.asyncio
async def test_execute_step_failure_stops_workflow(engine_no_db, mock_tool_failure, monkeypatch):
    """
    步骤执行失败时（默认 on_error=stop），工作流应停止并返回 failed 状态。
    """
    from tools.registry import built_in_tool_registry
    monkeypatch.setattr(built_in_tool_registry, "execute_tool", mock_tool_failure)

    definition = {
        "steps": [
            {"id": "step1", "type": "tool", "tool": "bad_tool", "action": "boom"},
            {"id": "step2", "type": "tool", "tool": "good_tool", "action": "run"},
        ],
    }

    result = await engine_no_db.execute_definition(definition)

    assert result["status"] == "failed"
    assert "error" in result
    # step2 不应该被执行，所以只有 step1 的结果
    assert len(result.get("steps", [])) <= 1


@pytest.mark.asyncio
async def test_execute_step_failure_continue_on_error(engine_no_db, mock_tool_failure, monkeypatch):
    """
    设置了 on_error: continue 的步骤即使失败，后续步骤仍应继续执行。
    """
    from tools.registry import built_in_tool_registry

    # 第一次调用失败，第二次调用成功
    call_count = [0]

    async def alternating_execute(tool_name, *, action, params, config):
        call_count[0] += 1
        if call_count[0] == 1:
            return {"success": False, "tool": tool_name, "action": action, "error": "first fails"}
        return {"success": True, "tool": tool_name, "action": action, "result": "second succeeds"}

    monkeypatch.setattr(built_in_tool_registry, "execute_tool", alternating_execute)

    definition = {
        "steps": [
            {
                "id": "step1",
                "type": "tool",
                "tool": "fallible",
                "action": "try",
                "on_error": "continue",
            },
            {"id": "step2", "type": "tool", "tool": "reliable", "action": "go"},
        ],
    }

    result = await engine_no_db.execute_definition(definition)

    assert result["status"] == "completed"
    assert len(result["steps"]) == 2
    assert result["steps"][0]["success"] is False  # 第一步失败
    assert result["steps"][1]["success"] is True   # 第二步成功


@pytest.mark.asyncio
async def test_execute_condition_step_true_branch(engine_no_db, mock_tool_success, monkeypatch):
    """
    条件为真时执行 on_true 分支。
    """
    from tools.registry import built_in_tool_registry
    monkeypatch.setattr(built_in_tool_registry, "execute_tool", mock_tool_success)

    definition = {
        "steps": [{
            "id": "cond1",
            "type": "condition",
            "expression": "context.score >= 60",
            "on_true": [
                {"id": "pass", "type": "tool", "tool": "log", "action": "info", "params": {"msg": "通过"}},
            ],
            "on_false": [
                {"id": "fail", "type": "tool", "tool": "log", "action": "error", "params": {"msg": "不通过"}},
            ],
        }],
    }

    result = await engine_no_db.execute_definition(
        definition,
        input_context={"score": 85},
    )

    assert result["status"] == "completed"
    cond_result = result["steps"][0]["result"]
    assert cond_result["matched"] is True
    assert len(cond_result["branch_results"]) == 1
    # on_true 分支执行了 pass 步骤
    assert cond_result["branch_results"][0]["step_id"] == "pass"


@pytest.mark.asyncio
async def test_execute_condition_step_false_branch(engine_no_db, mock_tool_success, monkeypatch):
    """
    条件为假时执行 on_false 分支。
    """
    from tools.registry import built_in_tool_registry
    monkeypatch.setattr(built_in_tool_registry, "execute_tool", mock_tool_success)

    definition = {
        "steps": [{
            "id": "cond1",
            "type": "condition",
            "expression": "context.score >= 60",
            "on_true": [
                {"id": "pass", "type": "tool", "tool": "log", "action": "info", "params": {"msg": "通过"}},
            ],
            "on_false": [
                {"id": "fail", "type": "tool", "tool": "log", "action": "error", "params": {"msg": "不通过"}},
            ],
        }],
    }

    result = await engine_no_db.execute_definition(
        definition,
        input_context={"score": 30},
    )

    assert result["status"] == "completed"
    cond_result = result["steps"][0]["result"]
    assert cond_result["matched"] is False
    assert cond_result["branch_results"][0]["step_id"] == "fail"


@pytest.mark.asyncio
async def test_execute_condition_step_missing_expression(engine_no_db):
    """
    条件步骤缺少 expression 时应抛出 ValueError。
    """
    definition = {
        "steps": [{
            "id": "cond1",
            "type": "condition",
            "on_true": [],
            "on_false": [],
        }],
    }

    result = await engine_no_db.execute_definition(definition)

    assert result["status"] == "failed"
    assert "缺少 expression" in result.get("error", "")


@pytest.mark.asyncio
async def test_execute_unsupported_step_type(engine_no_db):
    """
    不支持的步骤类型应导致工作流失败。
    """
    definition = {
        "steps": [{"id": "bad", "type": "unknown_type"}],
    }

    result = await engine_no_db.execute_definition(definition)

    assert result["status"] == "failed"
    assert "不支持的工作流步骤类型" in result.get("error", "")


# ==================== 占位符渲染测试 ====================

async def _render_helper(engine, template, context):
    """辅助函数：调用引擎的内部渲染逻辑。"""
    runtime = {"context": dict(context), "steps": {}, "last_result": {}}
    return engine._render_data(template, runtime)


def test_render_simple_context_placeholder():
    """简单的 context.xxx 占位符应被正确替换。"""
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    result = engine._render_data("{{ context.name }}", {
        "context": {"name": "张三"},
        "steps": {},
        "last_result": {},
    })
    assert result == "张三"


def test_render_nested_context_placeholder():
    """嵌套的 context.a.b 占位符应被正确替换。"""
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    result = engine._render_data("{{ context.user.profile.city }}", {
        "context": {"user": {"profile": {"city": "北京"}}},
        "steps": {},
        "last_result": {},
    })
    assert result == "北京"


def test_render_multiple_placeholders_in_string():
    """字符串中的多个占位符应全部替换。"""
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    result = engine._render_data("Hello {{ context.first }} {{ context.last }}!", {
        "context": {"first": "John", "last": "Doe"},
        "steps": {},
        "last_result": {},
    })
    assert result == "Hello John Doe!"


def test_render_non_string_value():
    """非字符串值（int、dict、list）应原样返回。"""
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    runtime = {"context": {}, "steps": {}, "last_result": {}}

    assert engine._render_data(42, runtime) == 42
    assert engine._render_data(3.14, runtime) == 3.14
    assert engine._render_data(True, runtime) is True
    assert engine._render_data([1, 2, 3], runtime) == [1, 2, 3]
    assert engine._render_data({"key": "value"}, runtime) == {"key": "value"}


def test_render_dict_with_placeholder_values():
    """字典中的值如果包含占位符应递归渲染。"""
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    result = engine._render_data(
        {"greeting": "{{ context.msg }}", "count": 5},
        {"context": {"msg": "你好"}, "steps": {}, "last_result": {}},
    )
    assert result == {"greeting": "你好", "count": 5}


def test_render_list_with_placeholder_values():
    """列表中的元素如果包含占位符应递归渲染。"""
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    result = engine._render_data(
        ["{{ context.a }}", "{{ context.b }}"],
        {"context": {"a": "x", "b": "y"}, "steps": {}, "last_result": {}},
    )
    assert result == ["x", "y"]


def test_render_last_result_placeholder():
    """last_result 占位符应正确解析。"""
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    result = engine._render_data("{{ last_result.data }}", {
        "context": {},
        "steps": {},
        "last_result": {"data": "previous_output"},
    })
    assert result == "previous_output"


def test_render_steps_placeholder():
    """steps 占位符应正确引用前序步骤的输出。"""
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    result = engine._render_data("{{ steps.step1.output }}", {
        "context": {},
        "steps": {"step1": {"output": "step1_result"}},
        "last_result": {},
    })
    assert result == "step1_result"


def test_render_nonexistent_placeholder_raises():
    """不存在的占位符路径必须显式抛错（定义错误在执行前暴露）。"""
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    with pytest.raises(ValueError, match="解析失败"):
        engine._render_data("{{ context.nonexistent.key }}", {
            "context": {},
            "steps": {},
            "last_result": {},
        })


# ==================== 条件表达式求值测试 ====================

def _eval_condition(engine, expression, context=None):
    """辅助函数：调用引擎的条件求值逻辑。"""
    runtime = {
        "context": dict(context or {}),
        "steps": {},
        "last_result": {},
    }
    return engine._evaluate_condition(expression, runtime)


def test_evaluate_simple_comparison_true():
    """简单比较表达式为真时返回 True。"""
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    assert _eval_condition(engine, "context.x > 5", {"x": 10}) is True


def test_evaluate_simple_comparison_false():
    """简单比较表达式为假时返回 False。"""
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    assert _eval_condition(engine, "context.x > 5", {"x": 3}) is False


def test_evaluate_equality():
    """等值比较表达式应正确求值。"""
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    assert _eval_condition(engine, "context.name == 'alice'", {"name": "alice"}) is True
    assert _eval_condition(engine, "context.name == 'bob'", {"name": "alice"}) is False


def test_evaluate_bool_op_and():
    """逻辑与运算应正确求值。"""
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    assert _eval_condition(engine, "context.a > 0 and context.b > 0", {"a": 1, "b": 1}) is True
    assert _eval_condition(engine, "context.a > 0 and context.b > 0", {"a": 1, "b": -1}) is False


def test_evaluate_bool_op_or():
    """逻辑或运算应正确求值。"""
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    assert _eval_condition(engine, "context.a > 0 or context.b > 0", {"a": -1, "b": 5}) is True
    assert _eval_condition(engine, "context.a > 0 or context.b > 0", {"a": -1, "b": -1}) is False


def test_evaluate_in_operator():
    """in 运算符应正确求值。"""
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    assert _eval_condition(engine, "'admin' in context.roles", {"roles": ["admin", "user"]}) is True
    assert _eval_condition(engine, "'super' in context.roles", {"roles": ["admin", "user"]}) is False


def test_evaluate_invalid_syntax_raises_value_error():
    """无效的表达式语法应抛出 ValueError。"""
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    with pytest.raises(ValueError):
        _eval_condition(engine, "context.x ==", {"x": 1})


def test_evaluate_function_call_raises_value_error():
    """条件表达式中包含函数调用应被拒绝。"""
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    with pytest.raises(ValueError, match="条件表达式不支持的结构"):
        _eval_condition(engine, "eval('1+1') == 2", {})


def test_evaluate_empty_condition_returns_false():
    """空字符串表达式应返回 False（通过 SyntaxError 转 ValueError）。"""
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    # 空表达式会在 ast.parse 时抛出 SyntaxError，被包装为 ValueError
    with pytest.raises(ValueError):
        _eval_condition(engine, "", {})


def test_evaluate_runtime_failure_raises():
    """求值期异常（如访问不存在的属性）必须显式抛错，禁止静默返回 False。"""
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    with pytest.raises(ValueError, match="求值失败"):
        _eval_condition(engine, "context.missing > 5", {"x": 10})


# ==================== 工具步骤参数校验测试 ====================

@pytest.mark.asyncio
async def test_execute_tool_step_missing_tool_name(engine_no_db):
    """
    工具步骤缺少 tool 名称时应导致工作流失败。
    """
    definition = {
        "steps": [{"id": "bad_tool", "type": "tool", "action": "do_something"}],
    }

    result = await engine_no_db.execute_definition(definition)

    assert result["status"] == "failed"
    assert "缺少 tool" in result.get("error", "")


@pytest.mark.asyncio
async def test_execute_tool_step_missing_action(engine_no_db):
    """
    工具步骤缺少 action 时应导致工作流失败。
    """
    definition = {
        "steps": [{"id": "bad_action", "type": "tool", "tool": "some_tool"}],
    }

    result = await engine_no_db.execute_definition(definition)

    assert result["status"] == "failed"
    assert "缺少 tool" in result.get("error", "")


# ==================== YAML 字符串定义测试 ====================

@pytest.mark.asyncio
async def test_execute_yaml_string_definition(engine_no_db, mock_tool_success, monkeypatch):
    """
    传入 YAML 字符串格式的定义应被正确解析和执行。
    """
    from tools.registry import built_in_tool_registry
    monkeypatch.setattr(built_in_tool_registry, "execute_tool", mock_tool_success)

    yaml_def = """
name: YAML测试
steps:
  - id: step_1
    type: tool
    tool: echo
    action: say
"""

    result = await engine_no_db.execute_definition(yaml_def)

    assert result["status"] == "completed"
    assert result["workflow_name"] == "YAML测试"
    assert len(result["steps"]) == 1


# ==================== 数据渲染边界测试 ====================

def test_resolve_placeholder_empty_expression_raises():
    """空占位符表达式必须显式抛错。"""
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    with pytest.raises(ValueError, match="为空"):
        engine._resolve_placeholder("  ", {
            "context": {},
            "steps": {},
            "last_result": {},
        })


def test_resolve_placeholder_default_to_context():
    """不以 context/steps/last_result 开头的裸名称占位符默认从 context 中查找。

    修复历史双重遍历 bug：`{{key}}` 应直接解析 context 中的 key 值。
    """
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    result = engine._resolve_placeholder("key", {
        "context": {"key": "direct_value"},
        "steps": {},
        "last_result": {},
    })
    assert result == "direct_value"


def test_resolve_placeholder_broken_path_raises():
    """裸名称占位符路径断裂（值不存在）时必须显式抛错。"""
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    with pytest.raises(ValueError, match="解析失败"):
        engine._resolve_placeholder("missing_key", {
            "context": {},
            "steps": {},
            "last_result": {},
        })


def test_resolve_placeholder_list_index():
    """通过 context 访问 list 类型值时，数字索引可正确访问元素。"""
    engine = WorkflowEngine(db_session=None, skill_engine=None)
    runtime = {
        "context": {"items": ["a", "b", "c"]},
        "steps": {},
        "last_result": {},
    }
    result = engine._render_data("{{ context.items.0 }}", runtime)
    assert result == "a"  # list 通过 .isdigit() 检测后使用 int 索引


# ==================== 并行步骤（parallel）解析测试 ====================

def test_parse_parallel_step_with_branches():
    """parallel 步骤应正确解析 branches 字段，每个 branch 是一组串行步骤。"""
    parser = WorkflowParser()
    result = parser.parse_definition({
        "steps": [{
            "id": "par1",
            "type": "parallel",
            "branches": [
                [{"id": "a1", "type": "tool", "tool": "x", "action": "y"}],
                [{"id": "b1", "type": "tool", "tool": "x", "action": "y"}],
            ],
        }],
    })
    step = result["steps"][0]
    assert step["type"] == "parallel"
    assert len(step["branches"]) == 2
    assert step["branches"][0][0]["id"] == "a1"
    assert step["branches"][1][0]["id"] == "b1"


def test_parse_parallel_step_single_step_branch():
    """parallel 步骤的 branch 支持单个步骤（非列表），自动包装为单元素列表。"""
    parser = WorkflowParser()
    result = parser.parse_definition({
        "steps": [{
            "id": "par1",
            "type": "parallel",
            "branches": [
                {"id": "a1", "type": "tool", "tool": "x", "action": "y"},
                {"id": "b1", "type": "tool", "tool": "x", "action": "y"},
            ],
        }],
    })
    step = result["steps"][0]
    assert len(step["branches"]) == 2
    # 单个步骤被自动包装为列表
    assert isinstance(step["branches"][0], list)
    assert step["branches"][0][0]["id"] == "a1"


def test_parse_parallel_step_missing_branches_raises():
    """parallel 步骤缺少 branches 应抛出 ValueError。"""
    parser = WorkflowParser()
    with pytest.raises(ValueError, match="缺少 branches"):
        parser.parse_definition({
            "steps": [{"id": "par1", "type": "parallel"}],
        })


def test_parse_parallel_step_empty_branches_raises():
    """parallel 步骤 branches 为空列表应抛出 ValueError。"""
    parser = WorkflowParser()
    with pytest.raises(ValueError, match="branches 为空"):
        parser.parse_definition({
            "steps": [{"id": "par1", "type": "parallel", "branches": []}],
        })


# ==================== 子工作流步骤（sub_workflow）解析测试 ====================

def test_parse_sub_workflow_step_with_id():
    """sub_workflow 步骤通过 workflow_id 引用子工作流。"""
    parser = WorkflowParser()
    result = parser.parse_definition({
        "steps": [{
            "id": "sub1",
            "type": "sub_workflow",
            "workflow_id": 42,
            "inputs": {"key": "value"},
        }],
    })
    step = result["steps"][0]
    assert step["type"] == "sub_workflow"
    assert step["workflow_id"] == 42
    assert step["inputs"] == {"key": "value"}
    assert step["max_depth"] == 5  # 默认值


def test_parse_sub_workflow_step_with_name():
    """sub_workflow 步骤通过 workflow_name 引用子工作流。"""
    parser = WorkflowParser()
    result = parser.parse_definition({
        "steps": [{
            "id": "sub1",
            "type": "sub_workflow",
            "workflow_name": "子工作流",
            "max_depth": 3,
        }],
    })
    step = result["steps"][0]
    assert step["workflow_name"] == "子工作流"
    assert step["workflow_id"] is None
    assert step["max_depth"] == 3


def test_parse_sub_workflow_step_missing_reference_raises():
    """sub_workflow 步骤未指定 workflow_id 和 workflow_name 应抛出 ValueError。"""
    parser = WorkflowParser()
    with pytest.raises(ValueError, match="必须指定 workflow_id 或 workflow_name"):
        parser.parse_definition({
            "steps": [{"id": "sub1", "type": "sub_workflow"}],
        })


# ==================== 并行步骤执行测试 ====================

@pytest.mark.asyncio
async def test_execute_parallel_step_all_branches_success(engine_no_db, mock_tool_success, monkeypatch):
    """所有分支都成功时，并行步骤应返回 success=True。"""
    from tools.registry import built_in_tool_registry
    monkeypatch.setattr(built_in_tool_registry, "execute_tool", mock_tool_success)

    definition = {
        "steps": [{
            "id": "par1",
            "type": "parallel",
            "branches": [
                [{"id": "a1", "type": "tool", "tool": "echo", "action": "say"}],
                [{"id": "b1", "type": "tool", "tool": "echo", "action": "say"}],
                [{"id": "c1", "type": "tool", "tool": "echo", "action": "say"}],
            ],
        }],
    }

    result = await engine_no_db.execute_definition(definition)

    assert result["status"] == "completed"
    par_step = result["steps"][0]
    assert par_step["type"] == "parallel"
    assert par_step["success"] is True
    assert par_step["result"]["branch_count"] == 3
    # 所有分支都成功
    for br in par_step["result"]["branch_results"]:
        assert br["success"] is True


@pytest.mark.asyncio
async def test_execute_parallel_step_branches_run_concurrently(engine_no_db, monkeypatch):
    """并行步骤的分支应同时执行，总耗时接近最慢分支而非所有分支之和。"""
    import time
    from tools.registry import built_in_tool_registry

    execution_log: list = []

    async def _slow_execute(tool_name, *, action, params, config):
        execution_log.append(f"{tool_name}_start")
        await asyncio.sleep(0.1)  # 模拟耗时操作
        execution_log.append(f"{tool_name}_end")
        return {"success": True, "tool": tool_name, "action": action, "result": "done"}

    monkeypatch.setattr(built_in_tool_registry, "execute_tool", _slow_execute)

    definition = {
        "steps": [{
            "id": "par1",
            "type": "parallel",
            "branches": [
                [{"id": "a1", "type": "tool", "tool": "branch_a", "action": "run"}],
                [{"id": "b1", "type": "tool", "tool": "branch_b", "action": "run"}],
            ],
        }],
    }

    start_time = time.monotonic()
    result = await engine_no_db.execute_definition(definition)
    elapsed = time.monotonic() - start_time

    assert result["status"] == "completed"
    # 并行执行总耗时应接近单分支耗时（0.1s），而非两倍（0.2s）
    assert elapsed < 0.2, f"并行执行耗时 {elapsed:.3f}s 超过预期，可能未真正并行"


@pytest.mark.asyncio
async def test_execute_parallel_step_one_branch_fails(engine_no_db, mock_tool_success, mock_tool_failure, monkeypatch):
    """一个分支失败时（默认 on_error=stop），并行步骤应标记为失败并抛出异常。"""
    from tools.registry import built_in_tool_registry

    call_count = [0]

    async def _mixed_execute(tool_name, *, action, params, config):
        call_count[0] += 1
        if call_count[0] == 2:  # 第二个调用失败
            return {"success": False, "tool": tool_name, "action": action, "error": "branch_b 失败"}
        return {"success": True, "tool": tool_name, "action": action, "result": "ok"}

    monkeypatch.setattr(built_in_tool_registry, "execute_tool", _mixed_execute)

    definition = {
        "steps": [{
            "id": "par1",
            "type": "parallel",
            "branches": [
                [{"id": "a1", "type": "tool", "tool": "branch_a", "action": "run"}],
                [{"id": "b1", "type": "tool", "tool": "branch_b", "action": "run"}],
            ],
        }],
    }

    result = await engine_no_db.execute_definition(definition)

    # 默认 on_error=stop，并行步骤失败导致整个工作流失败
    assert result["status"] == "failed"
    assert "分支" in result.get("error", "")


@pytest.mark.asyncio
async def test_execute_parallel_step_continue_on_error(engine_no_db, monkeypatch):
    """设置 on_error=continue 时，即使部分分支失败，并行步骤也继续。"""
    from tools.registry import built_in_tool_registry

    call_count = [0]

    async def _mixed_execute(tool_name, *, action, params, config):
        call_count[0] += 1
        if "fail" in tool_name:
            return {"success": False, "tool": tool_name, "action": action, "error": "预期失败"}
        return {"success": True, "tool": tool_name, "action": action, "result": "ok"}

    monkeypatch.setattr(built_in_tool_registry, "execute_tool", _mixed_execute)

    definition = {
        "steps": [
            {
                "id": "par1",
                "type": "parallel",
                "on_error": "continue",
                "branches": [
                    [{"id": "a1", "type": "tool", "tool": "ok_branch", "action": "run"}],
                    [{"id": "b1", "type": "tool", "tool": "fail_branch", "action": "run"}],
                ],
            },
            {"id": "after", "type": "tool", "tool": "after_tool", "action": "run"},
        ],
    }

    result = await engine_no_db.execute_definition(definition)

    assert result["status"] == "completed"
    par_step = result["steps"][0]
    assert par_step["success"] is False  # 并行步骤本身标记为失败
    # 但后续步骤继续执行
    assert result["steps"][1]["step_id"] == "after"


@pytest.mark.asyncio
async def test_execute_parallel_step_multi_step_branch(engine_no_db, mock_tool_success, monkeypatch):
    """每个分支可以包含多个串行步骤。"""
    from tools.registry import built_in_tool_registry
    monkeypatch.setattr(built_in_tool_registry, "execute_tool", mock_tool_success)

    definition = {
        "steps": [{
            "id": "par1",
            "type": "parallel",
            "branches": [
                [
                    {"id": "a1", "type": "tool", "tool": "a", "action": "x"},
                    {"id": "a2", "type": "tool", "tool": "a", "action": "y"},
                ],
                [{"id": "b1", "type": "tool", "tool": "b", "action": "x"}],
            ],
        }],
    }

    result = await engine_no_db.execute_definition(definition)

    assert result["status"] == "completed"
    par_step = result["steps"][0]
    # 分支 0 有 2 个步骤，分支 1 有 1 个步骤
    assert len(par_step["result"]["branch_results"][0]["results"]) == 2
    assert len(par_step["result"]["branch_results"][1]["results"]) == 1


# ==================== 子工作流执行测试 ====================

@pytest.mark.asyncio
async def test_execute_sub_workflow_without_db_raises(engine_no_db):
    """没有数据库会话时，子工作流步骤应失败。"""
    definition = {
        "steps": [{
            "id": "sub1",
            "type": "sub_workflow",
            "workflow_id": 1,
        }],
    }

    result = await engine_no_db.execute_definition(definition)

    assert result["status"] == "failed"
    assert "数据库会话" in result.get("error", "")


@pytest.mark.asyncio
async def test_execute_sub_workflow_with_mock_db(engine_no_db, mock_tool_success, monkeypatch):
    """使用 mock 数据库测试子工作流执行。"""
    from tools.registry import built_in_tool_registry
    monkeypatch.setattr(built_in_tool_registry, "execute_tool", mock_tool_success)

    # 创建 mock 数据库会话和 Workflow 模型
    class MockWorkflow:
        def __init__(self):
            self.id = 42
            self.name = "子工作流"
            self.definition = {
                "name": "子工作流",
                "steps": [
                    {"id": "sub_step1", "type": "tool", "tool": "sub_tool", "action": "run"},
                ],
            }

    class MockExecutionRecord:
        """模拟 WorkflowExecution 记录，支持属性赋值。"""
        def __init__(self):
            self.id = 1
            self.status = None
            self.output_payload = None
            self.error_message = None
            self.completed_at = None
        def __setattr__(self, key, value):
            object.__setattr__(self, key, value)

    class MockQuery:
        def __init__(self, workflow):
            self.workflow = workflow
        def filter(self, *args, **kwargs):
            return self
        def first(self):
            return self.workflow

    class MockDbSession:
        def __init__(self):
            self._workflow = MockWorkflow()
            self._record = MockExecutionRecord()
        def query(self, model):
            return MockQuery(self._workflow)
        def add(self, record):
            # 模拟 WorkflowExecution 记录添加
            pass
        def commit(self):
            pass
        def refresh(self, record):
            pass
        def rollback(self):
            pass

    engine = WorkflowEngine(db_session=MockDbSession(), skill_engine=None)

    definition = {
        "steps": [{
            "id": "sub1",
            "type": "sub_workflow",
            "workflow_id": 42,
            "inputs": {"extra_key": "extra_value"},
        }],
    }

    result = await engine.execute_definition(definition)

    assert result["status"] == "completed"
    sub_step = result["steps"][0]
    assert sub_step["type"] == "sub_workflow"
    assert sub_step["success"] is True
    # 子工作流的结果应包含其执行状态
    assert sub_step["result"]["status"] == "completed"


@pytest.mark.asyncio
async def test_execute_sub_workflow_not_found(engine_no_db, mock_tool_success, monkeypatch):
    """子工作流不存在时应失败。"""
    from tools.registry import built_in_tool_registry
    monkeypatch.setattr(built_in_tool_registry, "execute_tool", mock_tool_success)

    class MockExecutionRecord:
        def __init__(self):
            self.id = 1
            self.status = None
            self.output_payload = None
            self.error_message = None
            self.completed_at = None

    class MockQuery:
        def filter(self, *args, **kwargs):
            return self
        def first(self):
            return None  # 工作流不存在

    class MockDbSession:
        def query(self, model):
            return MockQuery()
        def add(self, record):
            pass
        def commit(self):
            pass
        def refresh(self, record):
            pass
        def rollback(self):
            pass

    engine = WorkflowEngine(db_session=MockDbSession(), skill_engine=None)

    definition = {
        "steps": [{
            "id": "sub1",
            "type": "sub_workflow",
            "workflow_id": 999,
        }],
    }

    result = await engine.execute_definition(definition)

    assert result["status"] == "failed"
    assert "不存在" in result.get("error", "")


@pytest.mark.asyncio
async def test_execute_sub_workflow_depth_limit(engine_no_db, mock_tool_success, monkeypatch):
    """子工作流递归深度超过限制时应失败。"""
    from tools.registry import built_in_tool_registry
    monkeypatch.setattr(built_in_tool_registry, "execute_tool", mock_tool_success)

    # 创建自引用的 mock 工作流（无限递归）
    class MockWorkflow:
        def __init__(self):
            self.id = 1
            self.name = "recursive"
            self.definition = {
                "name": "recursive",
                "steps": [
                    {
                        "id": "sub1",
                        "type": "sub_workflow",
                        "workflow_id": 1,
                        "max_depth": 2,  # 限制深度为 2
                    },
                ],
            }

    class MockExecutionRecord:
        def __init__(self):
            self.id = 1
            self.status = None
            self.output_payload = None
            self.error_message = None
            self.completed_at = None

    class MockQuery:
        def filter(self, *args, **kwargs):
            return self
        def first(self):
            return MockWorkflow()

    class MockDbSession:
        def query(self, model):
            return MockQuery()
        def add(self, record):
            pass
        def commit(self):
            pass
        def refresh(self, record):
            pass
        def rollback(self):
            pass

    engine = WorkflowEngine(db_session=MockDbSession(), skill_engine=None)

    definition = {
        "steps": [{
            "id": "sub1",
            "type": "sub_workflow",
            "workflow_id": 1,
            "max_depth": 2,
        }],
    }

    result = await engine.execute_definition(definition)

    # 递归到第 2 层时应被拦截
    assert result["status"] == "failed"
    assert "最大递归深度" in result.get("error", "")


# ==================== 并行+串行混合工作流测试 ====================

@pytest.mark.asyncio
async def test_execute_mixed_parallel_sequential_workflow(engine_no_db, mock_tool_success, monkeypatch):
    """并行步骤与串行步骤混合的工作流应正确执行。"""
    from tools.registry import built_in_tool_registry
    monkeypatch.setattr(built_in_tool_registry, "execute_tool", mock_tool_success)

    definition = {
        "steps": [
            {"id": "start", "type": "tool", "tool": "init", "action": "setup"},
            {
                "id": "par1",
                "type": "parallel",
                "branches": [
                    [{"id": "a1", "type": "tool", "tool": "task_a", "action": "run"}],
                    [{"id": "b1", "type": "tool", "tool": "task_b", "action": "run"}],
                ],
            },
            {"id": "end", "type": "tool", "tool": "finalize", "action": "cleanup"},
        ],
    }

    result = await engine_no_db.execute_definition(definition)

    assert result["status"] == "completed"
    assert len(result["steps"]) == 3
    assert result["steps"][0]["step_id"] == "start"
    assert result["steps"][1]["type"] == "parallel"
    assert result["steps"][2]["step_id"] == "end"

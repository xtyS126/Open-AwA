"""
Task 12: 内置 Verification 与 Guide Agent 定义测试。

覆盖范围：
1. Verification Agent 在 BUILTIN_AGENT_DEFINITIONS 中存在且配置正确
2. Guide Agent 在 BUILTIN_AGENT_DEFINITIONS 中存在且配置正确
3. SubagentOrchestrator 的 auto_verify 自动验证行为
"""

from __future__ import annotations

import asyncio

import pytest

from core.subagent import (
    SubagentOrchestrator,
    SubagentResult,
    SubagentTask,
)
from core.task_runtime.definitions import (
    BUILTIN_AGENT_DEFINITIONS,
    AgentMemoryScope,
)


# ──────────────────────────────────────────────
#  Verification Agent 定义测试
# ──────────────────────────────────────────────

def test_verification_agent_exists():
    """验证 Verification Agent 在 BUILTIN_AGENT_DEFINITIONS 中。"""
    assert "verification" in BUILTIN_AGENT_DEFINITIONS
    agent = BUILTIN_AGENT_DEFINITIONS["verification"]
    assert agent.name == "验证 Agent"


def test_verification_agent_has_readonly_tools():
    """验证 Verification Agent 工具集为只读，不含任何写操作工具。"""
    agent = BUILTIN_AGENT_DEFINITIONS["verification"]
    readonly_tools = {"read_file", "list_files", "file_exists", "web_search", "web_fetch"}
    # 工具集应为只读工具的子集
    assert set(agent.tools).issubset(readonly_tools)
    # 必须包含核心只读工具
    assert "read_file" in agent.tools
    assert "list_files" in agent.tools


def test_verification_agent_system_prompt():
    """验证 Verification Agent 的 system_prompt 包含独立验证关键短语。"""
    agent = BUILTIN_AGENT_DEFINITIONS["verification"]
    prompt = agent.system_prompt
    # 强调独立验证、不信任前序结果
    assert "独立验证" in prompt
    assert "不信任" in prompt
    # 强调必须实际运行测试 / 读取文件
    assert "测试" in prompt
    assert "读取" in prompt or "文件" in prompt
    # 强调给出明确验证结论
    assert "通过" in prompt
    assert "失败" in prompt


def test_verification_agent_max_turns():
    """验证 Verification Agent 的 max_turns=10。"""
    agent = BUILTIN_AGENT_DEFINITIONS["verification"]
    assert agent.max_turns == 10


def test_verification_agent_effort():
    """验证 Verification Agent 的 effort="high"。"""
    agent = BUILTIN_AGENT_DEFINITIONS["verification"]
    assert agent.effort == "high"


def test_verification_agent_omit_project_context():
    """验证 Verification Agent 需要项目上下文（omit_project_context=False）。"""
    agent = BUILTIN_AGENT_DEFINITIONS["verification"]
    assert agent.omit_project_context is False


def test_verification_agent_memory_scope():
    """验证 Verification Agent 的 memory_scope 为 LOCAL。"""
    agent = BUILTIN_AGENT_DEFINITIONS["verification"]
    assert agent.memory_scope == AgentMemoryScope.LOCAL


# ──────────────────────────────────────────────
#  Guide Agent 定义测试
# ──────────────────────────────────────────────

def test_guide_agent_exists():
    """验证 Guide Agent 在 BUILTIN_AGENT_DEFINITIONS 中。"""
    assert "guide" in BUILTIN_AGENT_DEFINITIONS
    agent = BUILTIN_AGENT_DEFINITIONS["guide"]
    assert agent.name == "引导 Agent"


def test_guide_agent_has_readonly_tools():
    """验证 Guide Agent 工具集为只读，不含任何写操作工具。"""
    agent = BUILTIN_AGENT_DEFINITIONS["guide"]
    readonly_tools = {"read_file", "list_files", "web_search"}
    assert set(agent.tools).issubset(readonly_tools)
    assert "read_file" in agent.tools


def test_guide_agent_system_prompt():
    """验证 Guide Agent 的 system_prompt 包含暂停询问与不可逆操作关键短语。"""
    agent = BUILTIN_AGENT_DEFINITIONS["guide"]
    prompt = agent.system_prompt
    # 强调在关键决策点暂停询问用户
    assert "暂停" in prompt
    assert "询问" in prompt
    # 强调提供选项分析
    assert "选项" in prompt or "分析" in prompt
    # 强调不自行做出不可逆操作
    assert "不可逆" in prompt
    # 强调遇到歧义时主动澄清
    assert "澄清" in prompt or "歧义" in prompt


def test_guide_agent_max_turns():
    """验证 Guide Agent 的 max_turns=5。"""
    agent = BUILTIN_AGENT_DEFINITIONS["guide"]
    assert agent.max_turns == 5


def test_guide_agent_effort():
    """验证 Guide Agent 的 effort="medium"。"""
    agent = BUILTIN_AGENT_DEFINITIONS["guide"]
    assert agent.effort == "medium"


def test_guide_agent_omit_project_context():
    """验证 Guide Agent 的 omit_project_context=True。"""
    agent = BUILTIN_AGENT_DEFINITIONS["guide"]
    assert agent.omit_project_context is True


def test_guide_agent_memory_scope():
    """验证 Guide Agent 的 memory_scope 为 USER。"""
    agent = BUILTIN_AGENT_DEFINITIONS["guide"]
    assert agent.memory_scope == AgentMemoryScope.USER


# ──────────────────────────────────────────────
#  SubagentOrchestrator auto_verify 测试
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delegate_one_auto_verify_appends_verification_result():
    """auto_verify=True 时应在任务完成后追加验证结果到原结果。"""
    orchestrator = SubagentOrchestrator(max_parallel=1)

    call_count = {"main": 0, "verify": 0}

    async def executor(task: SubagentTask) -> SubagentResult:
        # 区分主任务与验证任务
        if task.task_id.endswith("_verify"):
            call_count["verify"] += 1
            return SubagentResult(
                task_id=task.task_id,
                success=True,
                output="验证结论: 通过",
            )
        call_count["main"] += 1
        return SubagentResult(
            task_id=task.task_id,
            success=True,
            output="主任务完成结果",
        )

    task = SubagentTask(task_id="t1", instruction="实现功能X")
    result = await orchestrator.delegate_one(task, executor, auto_verify=True)

    # 主任务与验证任务各执行一次
    assert call_count["main"] == 1
    assert call_count["verify"] == 1
    # 验证结果附加到原结果
    assert result.success is True
    assert "verification" in result.metadata
    verification = result.metadata["verification"]
    assert verification["success"] is True
    assert "验证结论" in verification["output"]


@pytest.mark.asyncio
async def test_delegate_one_auto_verify_false_does_not_verify():
    """auto_verify=False（默认）时不应触发验证。"""
    orchestrator = SubagentOrchestrator(max_parallel=1)

    verify_called = {"count": 0}

    async def executor(task: SubagentTask) -> SubagentResult:
        if task.task_id.endswith("_verify"):
            verify_called["count"] += 1
        return SubagentResult(
            task_id=task.task_id,
            success=True,
            output="结果",
        )

    task = SubagentTask(task_id="t1", instruction="测试任务")
    result = await orchestrator.delegate_one(task, executor)

    # 默认不触发验证
    assert verify_called["count"] == 0
    assert "verification" not in result.metadata


@pytest.mark.asyncio
async def test_delegate_one_auto_verify_skipped_on_failure():
    """主任务失败时不应触发验证。"""
    orchestrator = SubagentOrchestrator(max_parallel=1)

    verify_called = {"count": 0}

    async def executor(task: SubagentTask):
        if task.task_id.endswith("_verify"):
            verify_called["count"] += 1
            return SubagentResult(task_id=task.task_id, success=True, output="验证")
        return SubagentResult(
            task_id=task.task_id,
            success=False,
            output="",
            error="主任务失败",
        )

    task = SubagentTask(task_id="t1", instruction="测试任务")
    result = await orchestrator.delegate_one(task, executor, auto_verify=True)

    # 主任务失败，不触发验证
    assert verify_called["count"] == 0
    assert result.success is False
    assert "verification" not in result.metadata


@pytest.mark.asyncio
async def test_delegate_all_auto_verify_verifies_each_task():
    """delegate_all 的 auto_verify=True 应对每个成功任务执行验证。"""
    orchestrator = SubagentOrchestrator(max_parallel=2)

    verify_count = {"count": 0}

    async def executor(task: SubagentTask) -> SubagentResult:
        if task.task_id.endswith("_verify"):
            verify_count["count"] += 1
            return SubagentResult(
                task_id=task.task_id,
                success=True,
                output="验证通过",
            )
        return SubagentResult(
            task_id=task.task_id,
            success=True,
            output=f"结果-{task.task_id}",
        )

    tasks = [
        SubagentTask(task_id="t1", instruction="任务1"),
        SubagentTask(task_id="t2", instruction="任务2"),
    ]
    results, _ = await orchestrator.delegate_all(tasks, executor, auto_verify=True)

    # 每个任务都触发验证
    assert verify_count["count"] == 2
    for r in results:
        assert "verification" in r.metadata


@pytest.mark.asyncio
async def test_delegate_one_auto_verify_verification_task_uses_readonly_tools():
    """验证任务应使用 Verification Agent 的只读工具集。"""
    orchestrator = SubagentOrchestrator(max_parallel=1)

    captured_tools: list = []

    async def executor(task: SubagentTask) -> SubagentResult:
        if task.task_id.endswith("_verify"):
            captured_tools.extend(task.allowed_tools)
            return SubagentResult(task_id=task.task_id, success=True, output="验证完成")
        return SubagentResult(task_id=task.task_id, success=True, output="主任务完成")

    task = SubagentTask(task_id="t1", instruction="实现功能")
    await orchestrator.delegate_one(task, executor, auto_verify=True)

    # 验证任务工具集应为只读
    readonly_tools = {"read_file", "list_files", "file_exists", "web_search", "web_fetch"}
    assert set(captured_tools).issubset(readonly_tools)

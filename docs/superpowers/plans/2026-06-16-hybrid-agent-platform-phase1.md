# Phase 1 实施计划：Agent 核心强化 + 角色定制 + 数据收集

> 创建时间：2026-06-16
> 关联设计文档：[2026-06-16-hybrid-agent-platform-design.md](../specs/2026-06-16-hybrid-agent-platform-design.md)
> 状态：待执行

---

## 总览

Phase 1 包含三大子系统，按依赖关系分为 7 个任务组（TG），共 21 个任务。

**执行顺序**：TG1 → TG2 → TG3 → TG4 → TG5 → TG6 → TG7

TG1-TG3 是 Agent 引擎增强（后端），TG4 是角色系统（后端+前端），TG5 是数据收集（后端+前端），TG6 是前端集成，TG7 是端到端验证。

```
TG1: 基础设施（配置 + 数据模型 + 迁移）
  ↓
TG2: 指数退避重试模块
  ↓
TG3: 步骤级回滚模块
  ↓
TG4: AI 角色定制系统
  ↓
TG5: 交互数据收集管道
  ↓
TG6: 前端页面与组件
  ↓
TG7: 端到端集成验证
```

---

## TG1：基础设施（配置 + 数据模型 + 迁移）

### Task 1.1：Settings 新增配置项

**目标**：在 `config/settings.py` 的 `Settings` 类中添加 Agent 引擎增强所需的配置项。

**修改文件**：`backend/config/settings.py`

**新增配置项**：

```python
# --- Agent 引擎增强配置 ---

# 自主纠错最大轮数（超出则请求人工介入）
AGENT_SELF_CORRECTION_MAX_ROUNDS: int = 3

# 单步骤超时（秒）
AGENT_STEP_TIMEOUT_SECONDS: int = 30

# 单任务全局超时（秒）
AGENT_TASK_TIMEOUT_SECONDS: int = 300

# 指数退避重试基础间隔（秒）
AGENT_RETRY_BASE_INTERVAL: float = 2.0

# 指数退避重试最大间隔（秒）
AGENT_RETRY_MAX_INTERVAL: float = 60.0

# 指数退避随机抖动系数（0.0-1.0）
AGENT_RETRY_JITTER: float = 0.1

# 步骤快照最大保留数量（防止内存泄漏）
AGENT_SNAPSHOT_MAX_COUNT: int = 50

# 模型降级策略：主模型失败时是否自动切换备用模型
AGENT_MODEL_FALLBACK_ENABLED: bool = True
```

**验证**：`python -c "from config.settings import settings; print(settings.AGENT_SELF_CORRECTION_MAX_ROUNDS)"`

**提交点**：`[Configuration] 新增 Agent 引擎增强配置项`

---

### Task 1.2：新增 AgentRole 数据模型

**目标**：在 `db/models.py` 中新增 `AgentRole` ORM 模型，并在 `init_db` 中添加迁移逻辑。

**修改文件**：`backend/db/models.py`

**新增模型**：

```python
class AgentRole(Base):
    """AI 角色定义模型，存储角色的性格、专长、工具权限和模型配置。"""
    __tablename__ = "agent_roles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    avatar_url: Mapped[str] = mapped_column(String(500), default="")

    # 角色核心定义
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    personality: Mapped[dict] = mapped_column(JSON, default=dict)
    # personality: {"tone": "professional|casual|friendly|strict",
    #               "verbosity": "concise|normal|detailed",
    #               "creativity": 0.0-1.0, "formality": 0.0-1.0}
    expertise: Mapped[dict] = mapped_column(JSON, default=dict)
    # expertise: {"domains": [], "languages": [], "specialties": []}

    # 知识绑定
    knowledge_base_ids: Mapped[dict] = mapped_column(JSON, default=list)

    # 工具权限
    allowed_tools: Mapped[dict] = mapped_column(JSON, default=list)
    allowed_skills: Mapped[dict] = mapped_column(JSON, default=list)

    # 模型配置
    model_config: Mapped[dict] = mapped_column(JSON, default=dict)
    # model_config: {"preferred_model": "", "fallback_model": "",
    #                 "temperature": 0.7, "max_tokens": 4096}

    # 元数据
    creator_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    is_preset: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )
```

**迁移逻辑**：在 `init_db()` 函数中添加 `_migrate_agent_roles(inspector, conn)` 调用，使用 `CREATE TABLE IF NOT EXISTS` 模式。

**验证**：`pytest tests/ -k "test_init_db" -x`

**提交点**：`[New] 新增 AgentRole 数据模型和迁移逻辑`

---

### Task 1.3：新增数据收集相关数据模型

**目标**：在 `db/models.py` 中新增数据收集管道所需的 ORM 模型。

**修改文件**：`backend/db/models.py`

**新增模型**：

```python
class ConversationData(Base):
    """对话数据收集模型，记录完整对话上下文和角色信息。"""
    __tablename__ = "conversation_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    role_id: Mapped[str] = mapped_column(String(64), default="")
    user_message: Mapped[str] = mapped_column(Text)
    assistant_message: Mapped[str] = mapped_column(Text)
    tools_used: Mapped[dict] = mapped_column(JSON, default=list)
    model_used: Mapped[str] = mapped_column(String(100), default="")
    token_count: Mapped[dict] = mapped_column(JSON, default=dict)
    response_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )


class ToolCallData(Base):
    """工具调用数据收集模型，记录工具名、参数、结果和耗时。"""
    __tablename__ = "tool_call_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    role_id: Mapped[str] = mapped_column(String(64), default="")
    tool_name: Mapped[str] = mapped_column(String(100))
    tool_params: Mapped[dict] = mapped_column(JSON)
    result_summary: Mapped[str] = mapped_column(Text, default="")
    success: Mapped[bool] = mapped_column(Boolean)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )


class ExecutionTrace(Base):
    """执行轨迹模型，记录规划-执行-反馈完整链路。"""
    __tablename__ = "execution_trace"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    role_id: Mapped[str] = mapped_column(String(64), default="")
    plan_steps: Mapped[dict] = mapped_column(JSON)
    executed_steps: Mapped[dict] = mapped_column(JSON)
    error_steps: Mapped[dict] = mapped_column(JSON, default=list)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    rollback_count: Mapped[int] = mapped_column(Integer, default=0)
    total_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )


class RoleSwitchEvent(Base):
    """角色切换事件模型，记录角色切换时间和原因。"""
    __tablename__ = "role_switch_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_role_id: Mapped[str] = mapped_column(String(64), default="")
    to_role_id: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
```

**注意**：`UserFeedback` 模型已存在（session_id/message_id/user_id/rating/comment），设计文档中新增的字段（conversation_id/role_id/feedback_type）通过迁移添加列，不破坏现有结构。

**迁移逻辑**：在 `init_db()` 中添加：
- `_migrate_conversation_data(inspector, conn)`
- `_migrate_tool_call_data(inspector, conn)`
- `_migrate_execution_trace(inspector, conn)`
- `_migrate_role_switch_event(inspector, conn)`
- `_migrate_user_feedback_add_columns(inspector, conn)` — 为现有 `user_feedback` 表添加 `conversation_id`、`role_id`、`feedback_type` 列

**验证**：`pytest tests/ -k "test_init_db" -x`

**提交点**：`[New] 新增数据收集相关数据模型和迁移逻辑`

---

## TG2：指数退避重试模块

### Task 2.1：实现 RetryPolicy 模块

**目标**：新增 `core/retry.py`，实现指数退避 + 随机抖动重试策略。

**新增文件**：`backend/core/retry.py`

**核心代码**：

```python
"""
指数退避重试策略模块，为 Agent 执行步骤提供可配置的重试机制。
"""

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Optional, TypeVar
from loguru import logger
from config.settings import settings


@dataclass
class RetryResult:
    """重试执行结果。"""
    success: bool
    attempts: int
    last_error: Optional[Exception] = None
    total_delay_seconds: float = 0.0
    result: Any = None


@dataclass
class RetryPolicy:
    """
    指数退避重试策略。

    参数:
        max_attempts: 最大重试次数（含首次执行）
        base_interval: 基础等待间隔（秒）
        max_interval: 最大等待间隔（秒）
        jitter: 随机抖动系数（0.0-1.0）
        exponential_base: 指数底数
    """
    max_attempts: int = 3
    base_interval: float = field(
        default_factory=lambda: settings.AGENT_RETRY_BASE_INTERVAL
    )
    max_interval: float = field(
        default_factory=lambda: settings.AGENT_RETRY_MAX_INTERVAL
    )
    jitter: float = field(
        default_factory=lambda: settings.AGENT_RETRY_JITTER
    )
    exponential_base: float = 2.0

    def compute_delay(self, attempt: int) -> float:
        """计算第 attempt 次重试的等待时间（秒）。"""
        delay = self.base_interval * (self.exponential_base ** (attempt - 1))
        delay = min(delay, self.max_interval)
        jitter_amount = delay * self.jitter * random.random()
        return delay + jitter_amount


async def execute_with_retry(
    func: Callable[..., Awaitable[Any]],
    *args: Any,
    policy: Optional[RetryPolicy] = None,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> RetryResult:
    """
    使用指数退避策略执行异步函数。

    参数:
        func: 要执行的异步函数
        policy: 重试策略，为 None 时使用默认策略
        retryable_exceptions: 可重试的异常类型元组
    """
    if policy is None:
        policy = RetryPolicy()

    result = RetryResult(success=False, attempts=0)
    last_error: Optional[Exception] = None

    for attempt in range(1, policy.max_attempts + 1):
        result.attempts = attempt
        try:
            ret = await func(*args, **kwargs)
            result.success = True
            result.result = ret
            return result
        except retryable_exceptions as e:
            last_error = e
            logger.bind(
                event="retry_attempt",
                module="retry",
                attempt=attempt,
                max_attempts=policy.max_attempts,
                error=str(e),
            ).warning(f"第 {attempt} 次执行失败: {e}")

            if attempt < policy.max_attempts:
                delay = policy.compute_delay(attempt)
                result.total_delay_seconds += delay
                logger.bind(
                    event="retry_delay",
                    module="retry",
                    attempt=attempt,
                    delay_seconds=round(delay, 2),
                ).info(f"等待 {delay:.2f}s 后重试")
                await asyncio.sleep(delay)

    result.last_error = last_error
    return result
```

**测试文件**：`backend/tests/test_retry.py`

**测试用例**：
- `test_compute_delay_increases_exponentially` — 验证延迟随重试次数指数增长
- `test_compute_delay_capped_at_max_interval` — 验证延迟不超过最大值
- `test_compute_delay_with_jitter` — 验证抖动在合理范围内
- `test_execute_with_retry_succeeds_first_attempt` — 首次成功不重试
- `test_execute_with_retry_retries_on_failure` — 失败后重试
- `test_execute_with_retry_stops_after_max_attempts` — 超过最大次数停止
- `test_execute_with_retry_non_retryable_exception` — 不可重试异常立即失败

**验证**：`pytest tests/test_retry.py -v`

**提交点**：`[New] 新增指数退避重试策略模块 core/retry.py`

---

### Task 2.2：集成 RetryPolicy 到 ExecutionLayer

**目标**：修改 `core/executor.py`，将 `retry_step` 方法从简单委派改为使用 `RetryPolicy`。

**修改文件**：`backend/core/executor.py`

**改动点**：

1. 导入 `RetryPolicy` 和 `execute_with_retry`
2. 修改 `retry_step` 方法：

```python
async def retry_step(self, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """使用指数退避策略重试失败的执行步骤。"""
    from core.retry import RetryPolicy, execute_with_retry

    policy = RetryPolicy(max_attempts=3)
    result = await execute_with_retry(
        self.execute_step,
        step,
        context,
        policy=policy,
        retryable_exceptions=(ToolExecutionError, LLMCallError),
    )

    if result.success:
        return result.result

    return {
        "status": "failed",
        "response": f"重试 {result.attempts} 次后仍然失败: {result.last_error}",
        "error": str(result.last_error),
    }
```

3. 在 `_call_llm_api_stream` 和 `_call_llm_api` 中添加全局超时控制：

```python
# 在 _call_llm_api 中添加超时包装
timeout = context.get("step_timeout", settings.AGENT_STEP_TIMEOUT_SECONDS)
result = await asyncio.wait_for(
    self._call_llm_api_internal(prompt, context),
    timeout=timeout,
)
```

**验证**：`pytest tests/ -k "executor" -x`

**提交点**：`[Optimization] ExecutionLayer 集成指数退避重试和步骤超时控制`

---

## TG3：步骤级回滚模块

### Task 3.1：实现 RollbackManager 模块

**目标**：新增 `core/rollback.py`，实现步骤快照和回滚管理。

**新增文件**：`backend/core/rollback.py`

**核心代码**：

```python
"""
步骤级回滚管理模块，为 Agent 执行步骤提供快照和回滚能力。
每个步骤执行前保存快照，失败时自动回滚到上一个稳定状态。
"""

import copy
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from loguru import logger
from config.settings import settings


@dataclass
class StepSnapshot:
    """步骤执行快照。"""
    step_index: int
    step_action: str
    context_state: Dict[str, Any]  # 执行上下文的深拷贝
    timestamp: float = field(default_factory=time.time)
    description: str = ""


class RollbackManager:
    """
    步骤级回滚管理器。

    在每个步骤执行前保存上下文快照，步骤失败时可以回滚到上一个稳定状态。
    快照数量受 AGENT_SNAPSHOT_MAX_COUNT 限制，超出时自动淘汰最旧的快照。
    """

    def __init__(self, max_snapshots: Optional[int] = None):
        self._snapshots: List[StepSnapshot] = []
        self._max_snapshots = max_snapshots or settings.AGENT_SNAPSHOT_MAX_COUNT

    def save_snapshot(
        self,
        step_index: int,
        step_action: str,
        context: Dict[str, Any],
        description: str = "",
    ) -> StepSnapshot:
        """保存步骤执行前的上下文快照。"""
        # 深拷贝上下文，防止后续修改影响快照
        context_copy = copy.deepcopy(context)

        snapshot = StepSnapshot(
            step_index=step_index,
            step_action=step_action,
            context_state=context_copy,
            description=description,
        )

        self._snapshots.append(snapshot)

        # 超出上限时淘汰最旧的快照
        while len(self._snapshots) > self._max_snapshots:
            removed = self._snapshots.pop(0)
            logger.bind(
                event="snapshot_evicted",
                module="rollback",
                step_index=removed.step_index,
            ).debug(f"淘汰旧快照: 步骤 {removed.step_index}")

        logger.bind(
            event="snapshot_saved",
            module="rollback",
            step_index=step_index,
            total_snapshots=len(self._snapshots),
        ).debug(f"保存快照: 步骤 {step_index} ({step_action})")

        return snapshot

    def rollback_to_last_stable(self) -> Optional[StepSnapshot]:
        """回滚到最后一个快照（即上一个稳定状态）。"""
        if not self._snapshots:
            logger.bind(event="rollback_no_snapshot", module="rollback").warning(
                "没有可用的快照，无法回滚"
            )
            return None

        snapshot = self._snapshots.pop()
        logger.bind(
            event="rollback_executed",
            module="rollback",
            step_index=snapshot.step_index,
            step_action=snapshot.step_action,
        ).info(f"回滚到步骤 {snapshot.step_index} ({snapshot.step_action})")

        return snapshot

    def get_context_after_rollback(self) -> Optional[Dict[str, Any]]:
        """执行回滚并返回恢复的上下文。"""
        snapshot = self.rollback_to_last_stable()
        if snapshot is None:
            return None
        return copy.deepcopy(snapshot.context_state)

    def clear(self) -> None:
        """清空所有快照。"""
        self._snapshots.clear()

    @property
    def snapshot_count(self) -> int:
        """当前快照数量。"""
        return len(self._snapshots)
```

**测试文件**：`backend/tests/test_rollback.py`

**测试用例**：
- `test_save_snapshot_stores_deep_copy` — 验证快照是深拷贝
- `test_rollback_to_last_stable_returns_latest_snapshot` — 回滚返回最新快照
- `test_rollback_removes_snapshot_from_stack` — 回滚后快照从栈中移除
- `test_rollback_empty_stack_returns_none` — 空栈回滚返回 None
- `test_max_snapshots_eviction` — 超出上限自动淘汰
- `test_get_context_after_rollback_returns_deep_copy` — 返回的上下文是深拷贝
- `test_clear_removes_all_snapshots` — 清空所有快照

**验证**：`pytest tests/test_rollback.py -v`

**提交点**：`[New] 新增步骤级回滚管理模块 core/rollback.py`

---

### Task 3.2：集成 RollbackManager 到 Agent 主流程

**目标**：修改 `core/agent.py` 和 `core/executor.py`，在步骤执行前保存快照，失败时触发回滚。

**修改文件**：
- `backend/core/agent.py`
- `backend/core/executor.py`

**改动点（agent.py）**：

1. 导入 `RollbackManager`
2. 在 `AIAgent.__init__` 中初始化 `self._rollback_manager: Optional[RollbackManager] = None`
3. 在 `process_stream` 方法中，当启用自主纠错模式时：
   - 创建 `RollbackManager` 实例
   - 在每个步骤执行前调用 `save_snapshot`
   - 步骤失败时调用 `rollback_to_last_stable` 恢复上下文
   - 进入自主纠错循环（最多 3 轮）

**自主纠错循环伪代码**：

```python
async def _self_correction_loop(self, step, context, error):
    """自主纠错循环：诊断错误 -> 生成修复计划 -> 回滚 -> 重新执行。"""
    from core.rollback import RollbackManager
    from config.settings import settings

    max_rounds = settings.AGENT_SELF_CORRECTION_MAX_ROUNDS
    rollback_manager = context.get("_rollback_manager")

    for correction_round in range(1, max_rounds + 1):
        # 1. 诊断错误
        diagnosis = await self.feedback.diagnose_error(error, context)

        # 2. 生成修复计划
        fix_plan = await self.planner.generate_fix_plan(diagnosis, context)

        # 3. 回滚到上一个稳定状态
        if rollback_manager:
            restored_context = rollback_manager.get_context_after_rollback()
            if restored_context:
                context.update(restored_context)

        # 4. 执行修复计划
        try:
            result = await self.executor.execute_step(fix_plan, context)
            if result.get("status") != "failed":
                return result
            error = Exception(result.get("response", "修复计划执行失败"))
        except Exception as e:
            error = e

    # 超出最大纠错轮数，请求人工介入
    return {
        "status": "needs_human_intervention",
        "response": f"自主纠错 {max_rounds} 轮后仍失败，需要人工介入",
        "error": str(error),
    }
```

**改动点（executor.py）**：

1. 在 `_call_llm_api_stream` 的 tool_calls 循环中，当 `consecutive_errors >= max_consecutive_errors` 时，不再直接终止，而是返回 `status: "failed"` 并携带错误信息，由 agent 层决定是否进入纠错循环

**验证**：`pytest tests/ -k "agent" -x`

**提交点**：`[New] Agent 主流程集成自主纠错循环和步骤级回滚`

---

### Task 3.3：FeedbackLayer 增加错误诊断能力

**目标**：修改 `core/feedback.py`，增加 `diagnose_error` 方法。

**修改文件**：`backend/core/feedback.py`

**新增方法**：

```python
async def diagnose_error(
    self,
    error: Exception,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    诊断执行错误的原因，生成结构化的诊断报告。

    返回:
        {
            "error_type": "tool_execution | llm_call | timeout | unknown",
            "error_message": "...",
            "likely_cause": "...",
            "suggested_fix": "..."
        }
    """
```

**实现逻辑**：
- 根据异常类型分类（ToolExecutionError / LLMCallError / TimeoutError / 其他）
- 调用 LLM 分析错误上下文，生成诊断报告
- 返回结构化诊断结果供 planner 使用

**验证**：`pytest tests/ -k "feedback" -x`

**提交点**：`[New] FeedbackLayer 增加自动错误诊断能力`

---

### Task 3.4：PlanningLayer 增加修复计划生成

**目标**：修改 `core/planner.py`，增加 `generate_fix_plan` 方法。

**修改文件**：`backend/core/planner.py`

**新增方法**：

```python
async def generate_fix_plan(
    self,
    diagnosis: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    基于错误诊断结果生成修复计划。

    返回:
        {
            "action": "tool_call | llm_call | retry",
            "tool": "...",
            "parameters": {...},
            "prompt": "...",
            "description": "修复说明"
        }
    """
```

**实现逻辑**：
- 将诊断结果和原始上下文组装成 prompt
- 调用 LLM 生成修复方案
- 解析 LLM 输出为结构化修复计划

**验证**：`pytest tests/ -k "planner" -x`

**提交点**：`[New] PlanningLayer 增加修复计划生成能力`

---

## TG4：AI 角色定制系统

### Task 4.1：实现 RoleEngine

**目标**：新增 `core/role_engine.py`，实现角色引擎核心逻辑。

**新增文件**：`backend/core/role_engine.py`

**核心代码**：

```python
"""
AI 角色引擎模块，负责角色配置的加载、注入、权限约束和知识库绑定。
"""

import uuid
from typing import Any, Dict, List, Optional
from loguru import logger
from sqlalchemy.orm import Session
from db.models import AgentRole


# 预设角色模板
PRESET_ROLES: List[Dict[str, Any]] = [
    {
        "id": "preset-code-reviewer",
        "name": "代码审查专家",
        "description": "严格审查代码质量、安全性和性能",
        "system_prompt": "你是一位严格的代码审查专家。审查代码时关注：1) 安全漏洞 2) 性能问题 3) 代码规范 4) 可维护性。给出具体的改进建议。",
        "personality": {"tone": "strict", "verbosity": "concise", "creativity": 0.2, "formality": 0.9},
        "expertise": {"domains": ["coding"], "languages": ["python", "typescript", "go"], "specialties": ["code-review"]},
        "allowed_tools": ["file_read", "file_write", "terminal", "search"],
        "allowed_skills": [],
        "model_config": {"preferred_model": "", "fallback_model": "", "temperature": 0.3, "max_tokens": 4096},
        "is_preset": True,
    },
    {
        "id": "preset-office-assistant",
        "name": "办公助手",
        "description": "高效处理文档、邮件、日程等日常办公事务",
        "system_prompt": "你是一位高效的办公助手。帮助用户处理文档撰写、邮件回复、日程安排等日常办公事务。回复简洁高效，重点突出。",
        "personality": {"tone": "casual", "verbosity": "concise", "creativity": 0.3, "formality": 0.5},
        "expertise": {"domains": ["writing", "scheduling"], "languages": [], "specialties": ["email", "document"]},
        "allowed_tools": ["file_read", "file_write", "search", "web_search"],
        "allowed_skills": [],
        "model_config": {"preferred_model": "", "fallback_model": "", "temperature": 0.5, "max_tokens": 4096},
        "is_preset": True,
    },
    {
        "id": "preset-tech-advisor",
        "name": "技术顾问",
        "description": "深度分析架构设计和技术选型",
        "system_prompt": "你是一位资深技术顾问。帮助用户进行架构设计分析、技术选型评估、系统方案对比。分析全面深入，给出有理有据的建议。",
        "personality": {"tone": "professional", "verbosity": "detailed", "creativity": 0.5, "formality": 0.8},
        "expertise": {"domains": ["architecture", "analysis"], "languages": ["python", "typescript", "go", "rust"], "specialties": ["system-design", "tech-selection"]},
        "allowed_tools": ["file_read", "search", "web_search", "terminal"],
        "allowed_skills": [],
        "model_config": {"preferred_model": "", "fallback_model": "", "temperature": 0.6, "max_tokens": 8192},
        "is_preset": True,
    },
    {
        "id": "preset-data-analyst",
        "name": "数据分析师",
        "description": "专注数据处理、可视化和统计分析",
        "system_prompt": "你是一位专业的数据分析师。帮助用户进行数据清洗、统计分析、可视化图表制作。注重数据准确性和分析逻辑的严谨性。",
        "personality": {"tone": "professional", "verbosity": "normal", "creativity": 0.4, "formality": 0.7},
        "expertise": {"domains": ["data-analysis", "visualization"], "languages": ["python", "sql"], "specialties": ["statistics", "chart"]},
        "allowed_tools": ["file_read", "file_write", "terminal", "search"],
        "allowed_skills": [],
        "model_config": {"preferred_model": "", "fallback_model": "", "temperature": 0.4, "max_tokens": 4096},
        "is_preset": True,
    },
    {
        "id": "preset-creative-writer",
        "name": "创意写作",
        "description": "富有创意的文案和内容创作",
        "system_prompt": "你是一位富有创意的写作助手。帮助用户进行文案创作、内容策划、故事构思。风格灵活多变，善于捕捉用户需求并给出新颖的表达。",
        "personality": {"tone": "friendly", "verbosity": "detailed", "creativity": 0.9, "formality": 0.3},
        "expertise": {"domains": ["writing", "creative"], "languages": [], "specialties": ["copywriting", "storytelling"]},
        "allowed_tools": ["file_read", "file_write", "search", "web_search"],
        "allowed_skills": [],
        "model_config": {"preferred_model": "", "fallback_model": "", "temperature": 0.8, "max_tokens": 4096},
        "is_preset": True,
    },
]


class RoleEngine:
    """
    AI 角色引擎，负责角色的加载、注入和约束。

    工作流：
    1. 加载角色配置（从数据库或预设模板）
    2. 注入 system_prompt 到 Agent 上下文
    3. 约束工具权限（只允许 allowed_tools + allowed_skills）
    4. 应用模型配置（preferred_model, temperature, max_tokens）
    5. 绑定知识库（从 knowledge_base_ids 加载上下文）
    """

    def __init__(self, db: Session):
        self._db = db

    def load_role(self, role_id: str) -> Optional[AgentRole]:
        """从数据库加载角色配置。"""
        return self._db.query(AgentRole).filter(AgentRole.id == role_id).first()

    def apply_role_to_context(
        self, role: AgentRole, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """将角色配置应用到 Agent 执行上下文。"""
        # 1. 注入 system_prompt
        context["system_prompt_override"] = role.system_prompt

        # 2. 应用 personality 参数
        personality = role.personality or {}
        if personality:
            context["personality"] = personality

        # 3. 约束工具权限
        allowed_tools = role.allowed_tools or []
        allowed_skills = role.allowed_skills or []
        if allowed_tools:
            context["allowed_tools_override"] = allowed_tools
        if allowed_skills:
            context["allowed_skills_override"] = allowed_skills

        # 4. 应用模型配置
        model_config = role.model_config or {}
        if model_config:
            context["model_config_override"] = model_config

        # 5. 绑定知识库
        knowledge_base_ids = role.knowledge_base_ids or []
        if knowledge_base_ids:
            context["knowledge_base_ids"] = knowledge_base_ids

        # 6. 记录角色信息
        context["role_id"] = role.id
        context["role_name"] = role.name

        return context

    def filter_tools_by_role(
        self, role: AgentRole, all_tools: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """根据角色权限过滤可用工具列表。"""
        allowed_tools = role.allowed_tools or []
        if not allowed_tools:
            return all_tools  # 未配置权限时允许所有工具

        filtered = []
        for tool in all_tools:
            tool_name = tool.get("function", {}).get("name", "")
            if tool_name in allowed_tools:
                filtered.append(tool)
        return filtered

    @staticmethod
    def get_preset_roles() -> List[Dict[str, Any]]:
        """获取预设角色模板列表。"""
        return PRESET_ROLES.copy()

    @staticmethod
    def ensure_presets_in_db(db: Session) -> int:
        """确保预设角色已写入数据库，返回新增数量。"""
        added = 0
        for preset in PRESET_ROLES:
            existing = db.query(AgentRole).filter(AgentRole.id == preset["id"]).first()
            if not existing:
                role = AgentRole(**preset)
                db.add(role)
                added += 1
        if added > 0:
            db.commit()
        return added
```

**测试文件**：`backend/tests/test_role_engine.py`

**测试用例**：
- `test_load_role_returns_role_from_db` — 从数据库加载角色
- `test_load_role_returns_none_for_nonexistent` — 不存在的角色返回 None
- `test_apply_role_to_context_injects_system_prompt` — 注入 system_prompt
- `test_apply_role_to_context_constrains_tools` — 约束工具权限
- `test_apply_role_to_context_applies_model_config` — 应用模型配置
- `test_filter_tools_by_role_filters_correctly` — 工具过滤正确
- `test_filter_tools_by_role_allows_all_when_no_constraint` — 未配置时允许所有
- `test_get_preset_roles_returns_list` — 获取预设列表
- `test_ensure_presets_in_db_creates_new_roles` — 写入预设到数据库
- `test_ensure_presets_in_db_skips_existing` — 跳过已存在的预设

**验证**：`pytest tests/test_role_engine.py -v`

**提交点**：`[New] 新增 AI 角色引擎模块 core/role_engine.py`

---

### Task 4.2：角色 API 路由

**目标**：新增 `api/routes/roles.py`，实现角色 CRUD + 切换 + 预设模板 API。

**新增文件**：`backend/api/routes/roles.py`

**API 端点**：

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/roles` | GET | 获取所有角色列表 |
| `/api/roles/{role_id}` | GET | 获取角色详情 |
| `/api/roles` | POST | 创建新角色 |
| `/api/roles/{role_id}` | PUT | 更新角色配置 |
| `/api/roles/{role_id}` | DELETE | 删除角色 |
| `/api/roles/presets` | GET | 获取预设角色模板列表 |
| `/api/roles/{role_id}/activate` | POST | 激活角色（绑定到当前会话） |

**Pydantic Schema**（在 `api/schemas.py` 中新增）：

```python
class RoleCreate(BaseModel):
    name: str = Field(..., max_length=100, description="角色名称")
    description: str = Field(default="", max_length=2000, description="角色描述")
    avatar_url: str = Field(default="", max_length=500, description="头像URL")
    system_prompt: str = Field(..., max_length=10000, description="系统提示词")
    personality: Dict[str, Any] = Field(default=dict, description="性格参数")
    expertise: Dict[str, Any] = Field(default=dict, description="专长领域")
    knowledge_base_ids: List[str] = Field(default=list, description="知识库ID列表")
    allowed_tools: List[str] = Field(default=list, description="允许的工具列表")
    allowed_skills: List[str] = Field(default=list, description="允许的技能列表")
    model_config: Dict[str, Any] = Field(default=dict, description="模型配置")
    is_public: bool = Field(default=False, description="是否公开")


class RoleResponse(BaseModel):
    id: str
    name: str
    description: str
    avatar_url: str
    system_prompt: str
    personality: Dict[str, Any]
    expertise: Dict[str, Any]
    knowledge_base_ids: List[str]
    allowed_tools: List[str]
    allowed_skills: List[str]
    model_config: Dict[str, Any]
    creator_id: Optional[int]
    is_public: bool
    usage_count: int
    is_preset: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = Field(default=None, max_length=2000)
    avatar_url: Optional[str] = Field(default=None, max_length=500)
    system_prompt: Optional[str] = Field(default=None, max_length=10000)
    personality: Optional[Dict[str, Any]] = None
    expertise: Optional[Dict[str, Any]] = None
    knowledge_base_ids: Optional[List[str]] = None
    allowed_tools: Optional[List[str]] = None
    allowed_skills: Optional[List[str]] = None
    model_config: Optional[Dict[str, Any]] = None
    is_public: Optional[bool] = None


class RoleActivateRequest(BaseModel):
    session_id: str = Field(..., description="要绑定角色的会话ID")
```

**activate 端点逻辑**：
- 加载角色配置
- 将角色信息写入会话上下文（存储到 ShortTermMemory 或 context）
- 返回激活结果

**验证**：`pytest tests/ -k "roles" -x`

**提交点**：`[New] 新增角色 CRUD + 切换 + 预设模板 API`

---

### Task 4.3：注册角色路由到 main.py

**目标**：在 `main.py` 中注册角色路由，并在启动时初始化预设角色。

**修改文件**：`backend/main.py`

**改动点**：

1. 导入：`from api.routes.roles import router as roles_router`
2. 注册路由：`app.include_router(roles_router, prefix=settings.API_V1_STR)`
3. 在 lifespan startup 中调用 `RoleEngine.ensure_presets_in_db(db)` 初始化预设角色

**验证**：启动服务后 `curl http://localhost:8000/api/roles/presets` 返回预设列表

**提交点**：`[Configuration] 注册角色路由并初始化预设角色`

---

### Task 4.4：Agent 集成角色引擎

**目标**：修改 `core/agent.py`，在 Agent 处理流程中集成角色引擎。

**修改文件**：`backend/core/agent.py`

**改动点**：

1. 导入 `RoleEngine`
2. 在 `process_stream` 方法中，检查 context 是否有 `role_id`
3. 如果有 `role_id`，通过 `RoleEngine` 加载角色配置并应用到上下文
4. 在工具注入阶段，使用 `RoleEngine.filter_tools_by_role` 过滤工具列表
5. 角色切换时记录 `RoleSwitchEvent`

**关键代码**：

```python
# 在 process_stream 中，工具注入前
role_id = context.get("role_id")
if role_id:
    from core.role_engine import RoleEngine
    role_engine = RoleEngine(db=None)  # 需要从依赖注入获取 db
    role = role_engine.load_role(role_id)
    if role:
        context = role_engine.apply_role_to_context(role, context)
        # 过滤工具
        all_tools = self._inject_runtime_capabilities(context)
        filtered_tools = role_engine.filter_tools_by_role(role, all_tools)
        context["tools"] = filtered_tools
```

**验证**：`pytest tests/ -k "agent" -x`

**提交点**：`[New] Agent 主流程集成角色引擎`

---

## TG5：交互数据收集管道

### Task 5.1：实现 DataCollector

**目标**：新增 `data/collector.py`，实现异步数据收集器。

**新增文件**：`backend/data/__init__.py`、`backend/data/collector.py`

**核心代码**：

```python
"""
异步数据收集器模块，不阻塞主流程地收集 Agent 交互数据。
使用 asyncio.Queue 实现生产者-消费者模式，批量写入数据库。
"""

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger
from db.models import SessionLocal, ConversationData, ToolCallData, ExecutionTrace, RoleSwitchEvent


class DataCollector:
    """异步数据收集器，不阻塞主流程。"""

    def __init__(self, batch_size: int = 50, flush_interval: float = 5.0):
        self._queue: asyncio.Queue[Tuple[str, Dict[str, Any]]] = asyncio.Queue()
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._running = False
        self._write_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """启动后台写入任务。"""
        if self._running:
            return
        self._running = True
        self._write_task = asyncio.create_task(self._write_loop())
        logger.bind(event="data_collector_started", module="data").info("数据收集器已启动")

    async def stop(self) -> None:
        """停止数据收集器，等待剩余数据写入完成。"""
        self._running = False
        if self._write_task:
            # 等待队列清空
            try:
                await asyncio.wait_for(self._write_task, timeout=10.0)
            except asyncio.TimeoutError:
                logger.bind(event="data_collector_stop_timeout", module="data").warning(
                    "数据收集器停止超时，可能有数据丢失"
                )
        logger.bind(event="data_collector_stopped", module="data").info("数据收集器已停止")

    async def collect_conversation(self, data: Dict[str, Any]) -> None:
        """收集对话数据（非阻塞）。"""
        await self._queue.put(("conversation", data))

    async def collect_tool_call(self, data: Dict[str, Any]) -> None:
        """收集工具调用数据（非阻塞）。"""
        await self._queue.put(("tool_call", data))

    async def collect_execution_trace(self, data: Dict[str, Any]) -> None:
        """收集执行轨迹数据（非阻塞）。"""
        await self._queue.put(("execution_trace", data))

    async def collect_role_switch(self, data: Dict[str, Any]) -> None:
        """收集角色切换事件（非阻塞）。"""
        await self._queue.put(("role_switch", data))

    async def _write_loop(self) -> None:
        """后台批量写入循环。"""
        while self._running or not self._queue.empty():
            batch: List[Tuple[str, Dict[str, Any]]] = []
            try:
                # 等待第一条数据
                item = await asyncio.wait_for(
                    self._queue.get(), timeout=self._flush_interval
                )
                batch.append(item)
                # 批量收集更多数据
                while not self._queue.empty() and len(batch) < self._batch_size:
                    batch.append(self._queue.get_nowait())
            except asyncio.TimeoutError:
                continue

            if batch:
                await self._write_batch(batch)

    async def _write_batch(self, batch: List[Tuple[str, Dict[str, Any]]]) -> None:
        """批量写入数据库。"""
        try:
            db = SessionLocal()
            try:
                for data_type, data in batch:
                    self._insert_record(db, data_type, data)
                db.commit()
            except Exception as e:
                db.rollback()
                logger.bind(
                    event="data_collector_write_error",
                    module="data",
                    batch_size=len(batch),
                    error=str(e),
                ).error(f"批量写入数据失败: {e}")
            finally:
                db.close()
        except Exception as e:
            logger.bind(
                event="data_collector_db_error",
                module="data",
                error=str(e),
            ).error(f"数据库连接失败: {e}")

    def _insert_record(
        self, db, data_type: str, data: Dict[str, Any]
    ) -> None:
        """根据数据类型创建对应的 ORM 对象并添加到 session。"""
        if data_type == "conversation":
            record = ConversationData(**data)
        elif data_type == "tool_call":
            record = ToolCallData(**data)
        elif data_type == "execution_trace":
            record = ExecutionTrace(**data)
        elif data_type == "role_switch":
            record = RoleSwitchEvent(**data)
        else:
            logger.bind(
                event="data_collector_unknown_type",
                module="data",
                data_type=data_type,
            ).warning(f"未知的数据类型: {data_type}")
            return
        db.add(record)


# 全局单例
data_collector = DataCollector()
```

**测试文件**：`backend/tests/test_data_collector.py`

**测试用例**：
- `test_collect_conversation_enqueues_item` — 对话数据入队
- `test_collect_tool_call_enqueues_item` — 工具调用数据入队
- `test_write_batch_inserts_records` — 批量写入数据库
- `test_write_batch_rollback_on_error` — 写入失败回滚
- `test_start_stop_lifecycle` — 启动停止生命周期

**验证**：`pytest tests/test_data_collector.py -v`

**提交点**：`[New] 新增异步数据收集器 data/collector.py`

---

### Task 5.2：集成 DataCollector 到 Agent 和 Executor

**目标**：在 Agent 和 Executor 的关键节点调用 DataCollector 收集数据。

**修改文件**：
- `backend/core/agent.py`
- `backend/core/executor.py`

**改动点（agent.py）**：

1. 导入 `data_collector`
2. 在 `process_stream` 完成后收集对话数据
3. 角色切换时收集 `RoleSwitchEvent`

```python
# 在 process_stream 的 finally 块中
from data.collector import data_collector

await data_collector.collect_conversation({
    "conversation_id": context.get("session_id", ""),
    "role_id": context.get("role_id", ""),
    "user_message": user_input,
    "assistant_message": full_response,
    "tools_used": tools_used_list,
    "model_used": context.get("model", ""),
    "token_count": token_count_dict,
    "response_time_ms": int((time.time() - start_time) * 1000),
})
```

**改动点（executor.py）**：

1. 在 `_execute_tool_call` 完成后收集工具调用数据

```python
from data.collector import data_collector

await data_collector.collect_tool_call({
    "conversation_id": context.get("session_id", ""),
    "role_id": context.get("role_id", ""),
    "tool_name": tool_name,
    "tool_params": parameters,
    "result_summary": str(result)[:500],
    "success": result.get("status") != "failed",
    "duration_ms": int((time.time() - tool_start_time) * 1000),
})
```

**验证**：`pytest tests/ -k "agent or executor" -x`

**提交点**：`[New] Agent 和 Executor 集成数据收集管道`

---

### Task 5.3：数据查询和导出 API

**目标**：新增 `api/routes/data.py`，实现数据查询和导出 API。

**新增文件**：`backend/api/routes/data.py`

**API 端点**：

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/data/stats` | GET | 数据统计概览 |
| `/api/data/conversations` | GET | 对话记录查询（支持按角色、时间范围筛选） |
| `/api/data/tool-calls` | GET | 工具调用日志查询 |
| `/api/data/execution-traces` | GET | 执行轨迹查询 |
| `/api/data/feedback` | GET | 用户反馈查询 |
| `/api/data/export` | POST | 数据导出（JSON/CSV 格式） |

**查询参数**：
- `role_id`: 按角色筛选
- `start_date` / `end_date`: 按时间范围筛选
- `page` / `page_size`: 分页
- `format`: 导出格式（json/csv）

**验证**：`pytest tests/ -k "data" -x`

**提交点**：`[New] 新增数据查询和导出 API`

---

### Task 5.4：注册数据路由和初始化 DataCollector

**目标**：在 `main.py` 中注册数据路由，并在 lifespan 中初始化和关闭 DataCollector。

**修改文件**：`backend/main.py`

**改动点**：

1. 导入：`from api.routes.data import router as data_router`
2. 注册路由：`app.include_router(data_router, prefix=settings.API_V1_STR)`
3. 在 lifespan startup 中：`await data_collector.start()`
4. 在 lifespan shutdown 中：`await data_collector.stop()`

**验证**：启动服务后 `curl http://localhost:8000/api/data/stats` 返回统计概览

**提交点**：`[Configuration] 注册数据路由并初始化数据收集器`

---

## TG6：前端页面与组件

### Task 6.1：角色类型定义和 API 封装

**目标**：新增前端角色类型定义和 API 调用封装。

**新增文件**：
- `frontend/src/shared/types/role.ts`
- `frontend/src/shared/api/rolesApi.ts`

**role.ts**：

```typescript
/** AI 角色性格参数 */
export interface RolePersonality {
  tone: "professional" | "casual" | "friendly" | "strict";
  verbosity: "concise" | "normal" | "detailed";
  creativity: number;  // 0.0-1.0
  formality: number;   // 0.0-1.0
}

/** AI 角色专长领域 */
export interface RoleExpertise {
  domains: string[];
  languages: string[];
  specialties: string[];
}

/** AI 角色模型配置 */
export interface RoleModelConfig {
  preferred_model: string;
  fallback_model: string;
  temperature: number;
  max_tokens: number;
}

/** AI 角色定义 */
export interface AgentRole {
  id: string;
  name: string;
  description: string;
  avatar_url: string;
  system_prompt: string;
  personality: RolePersonality;
  expertise: RoleExpertise;
  knowledge_base_ids: string[];
  allowed_tools: string[];
  allowed_skills: string[];
  model_config: RoleModelConfig;
  creator_id: number | null;
  is_public: boolean;
  usage_count: number;
  is_preset: boolean;
  created_at: string;
  updated_at: string;
}

/** 创建角色请求 */
export interface RoleCreateRequest {
  name: string;
  description?: string;
  avatar_url?: string;
  system_prompt: string;
  personality?: Partial<RolePersonality>;
  expertise?: Partial<RoleExpertise>;
  knowledge_base_ids?: string[];
  allowed_tools?: string[];
  allowed_skills?: string[];
  model_config?: Partial<RoleModelConfig>;
  is_public?: boolean;
}

/** 更新角色请求 */
export interface RoleUpdateRequest extends Partial<RoleCreateRequest> {}
```

**rolesApi.ts**：封装所有角色 API 调用（getRoles, getRole, createRole, updateRole, deleteRole, getPresets, activateRole）

**验证**：`cd frontend && npx tsc --noEmit`

**提交点**：`[New] 新增角色类型定义和 API 封装`

---

### Task 6.2：角色管理页面

**目标**：新增角色管理页面，包含角色列表、创建、编辑、删除功能。

**新增文件**：
- `frontend/src/features/roles/RolesPage.tsx` — 角色管理主页面
- `frontend/src/features/roles/RoleCard.tsx` — 角色卡片组件
- `frontend/src/features/roles/RoleEditor.tsx` — 角色编辑器（可视化配置性格、知识库、工具权限）

**RolesPage 功能**：
- 角色列表展示（卡片网格布局）
- 预设角色和自定义角色分区展示
- 创建新角色按钮
- 角色卡片点击进入编辑
- 删除角色确认对话框

**RoleEditor 功能**：
- 基本信息编辑（名称、描述、头像）
- System Prompt 编辑（代码编辑器风格）
- 性格参数滑块（creativity, formality）
- 语气和详细度下拉选择
- 专长领域多选
- 工具权限多选
- 模型配置（首选模型、温度、最大 token）

**验证**：`cd frontend && npm run build`

**提交点**：`[New] 新增角色管理页面和编辑器组件`

---

### Task 6.3：聊天界面角色选择器

**目标**：在聊天界面添加角色选择器，支持快速切换角色。

**新增文件**：`frontend/src/features/chat/components/RoleSelector.tsx`

**修改文件**：`frontend/src/features/chat/components/ChatInput.tsx`（或聊天界面主组件）

**RoleSelector 功能**：
- 下拉菜单展示可用角色列表
- 当前激活角色高亮显示
- 选择角色后调用 activateRole API
- 角色切换时显示切换动画

**验证**：`cd frontend && npm run build`

**提交点**：`[New] 新增聊天界面角色选择器组件`

---

### Task 6.4：数据看板和反馈按钮

**目标**：新增数据看板页面和对话消息反馈按钮。

**新增文件**：
- `frontend/src/features/data/DataDashboard.tsx` — 数据看板
- `frontend/src/features/chat/components/FeedbackButtons.tsx` — 点赞/点踩按钮
- `frontend/src/shared/api/dataApi.ts` — 数据 API 封装

**DataDashboard 功能**：
- 交互统计概览（总对话数、工具调用数、平均响应时间）
- 角色使用分布饼图
- 工具调用热力图
- 按时间范围筛选

**FeedbackButtons 功能**：
- 在每条助手消息下方显示点赞/点踩按钮
- 点击后调用反馈 API
- 已反馈的消息显示反馈状态

**验证**：`cd frontend && npm run build`

**提交点**：`[New] 新增数据看板和对话反馈按钮`

---

### Task 6.5：前端路由更新

**目标**：在 `App.tsx` 中新增 `/roles` 和 `/data` 路由。

**修改文件**：`frontend/src/App.tsx`

**新增路由**：
- `/roles` → `RolesPage`
- `/data` → `DataDashboard`

**侧边栏导航更新**：在导航菜单中添加"角色管理"和"数据看板"入口

**验证**：`cd frontend && npm run build`

**提交点**：`[Configuration] 前端新增角色和数据看板路由`

---

## TG7：端到端集成验证

### Task 7.1：后端集成测试

**目标**：编写后端集成测试，验证 Agent 引擎增强 + 角色系统 + 数据收集的端到端流程。

**新增文件**：`backend/tests/test_phase1_integration.py`

**测试用例**：
- `test_role_activation_affects_agent_behavior` — 激活角色后 Agent 行为受角色约束
- `test_self_correction_loop_retries_on_failure` — 自主纠错循环在失败时重试
- `test_rollback_restores_context_on_failure` — 回滚在失败时恢复上下文
- `test_data_collector_captures_conversation` — 数据收集器捕获对话数据
- `test_data_collector_captures_tool_call` — 数据收集器捕获工具调用数据
- `test_data_export_returns_correct_format` — 数据导出返回正确格式
- `test_preset_roles_initialized_on_startup` — 启动时预设角色已初始化

**验证**：`pytest tests/test_phase1_integration.py -v`

**提交点**：`[Test] 新增 Phase 1 后端集成测试`

---

### Task 7.2：前端构建验证和完整测试

**目标**：运行前端完整构建和测试，确保无 TypeScript 错误和 ESLint 错误。

**验证命令**：
```bash
cd frontend
npx tsc --noEmit
npm run lint
npm run build
npm run test
```

**后端验证命令**：
```bash
cd backend
pytest -v --cov
```

**提交点**：`[Test] Phase 1 完整构建和测试验证`

---

## 提交历史汇总

| 序号 | 提交信息 | 关联任务 |
|------|---------|---------|
| 1 | `[Configuration] 新增 Agent 引擎增强配置项` | Task 1.1 |
| 2 | `[New] 新增 AgentRole 数据模型和迁移逻辑` | Task 1.2 |
| 3 | `[New] 新增数据收集相关数据模型和迁移逻辑` | Task 1.3 |
| 4 | `[New] 新增指数退避重试策略模块 core/retry.py` | Task 2.1 |
| 5 | `[Optimization] ExecutionLayer 集成指数退避重试和步骤超时控制` | Task 2.2 |
| 6 | `[New] 新增步骤级回滚管理模块 core/rollback.py` | Task 3.1 |
| 7 | `[New] Agent 主流程集成自主纠错循环和步骤级回滚` | Task 3.2 |
| 8 | `[New] FeedbackLayer 增加自动错误诊断能力` | Task 3.3 |
| 9 | `[New] PlanningLayer 增加修复计划生成能力` | Task 3.4 |
| 10 | `[New] 新增 AI 角色引擎模块 core/role_engine.py` | Task 4.1 |
| 11 | `[New] 新增角色 CRUD + 切换 + 预设模板 API` | Task 4.2 |
| 12 | `[Configuration] 注册角色路由并初始化预设角色` | Task 4.3 |
| 13 | `[New] Agent 主流程集成角色引擎` | Task 4.4 |
| 14 | `[New] 新增异步数据收集器 data/collector.py` | Task 5.1 |
| 15 | `[New] Agent 和 Executor 集成数据收集管道` | Task 5.2 |
| 16 | `[New] 新增数据查询和导出 API` | Task 5.3 |
| 17 | `[Configuration] 注册数据路由并初始化数据收集器` | Task 5.4 |
| 18 | `[New] 新增角色类型定义和 API 封装` | Task 6.1 |
| 19 | `[New] 新增角色管理页面和编辑器组件` | Task 6.2 |
| 20 | `[New] 新增聊天界面角色选择器组件` | Task 6.3 |
| 21 | `[New] 新增数据看板和对话反馈按钮` | Task 6.4 |
| 22 | `[Configuration] 前端新增角色和数据看板路由` | Task 6.5 |
| 23 | `[Test] 新增 Phase 1 后端集成测试` | Task 7.1 |
| 24 | `[Test] Phase 1 完整构建和测试验证` | Task 7.2 |

---

## 风险与注意事项

1. **UserFeedback 模型冲突**：现有 `user_feedback` 表的字段（session_id/message_id/user_id/rating/comment）与设计文档中的字段（conversation_id/message_id/role_id/feedback_type/comment）不同。通过迁移添加新列，不删除旧列，保持向后兼容。

2. **RollbackManager 内存占用**：深拷贝上下文可能消耗大量内存。通过 `AGENT_SNAPSHOT_MAX_COUNT` 限制快照数量，并在任务完成后清空。

3. **DataCollector 写入失败**：批量写入失败时回滚当前批次，不影响后续批次。日志记录失败详情供排查。

4. **角色权限过滤**：当 `allowed_tools` 为空列表时，表示未配置权限约束，允许所有工具。只有明确配置了工具列表时才进行过滤。

5. **自主纠错循环**：纠错循环最多 3 轮，超出后返回 `needs_human_intervention` 状态。前端需要处理此状态，显示人工介入提示。

# Brooks-Lint Tech Debt Assessment — core/agent.py

> 评估时间：2026-07-26
> 评估工具：trae-remote-official:brooks-lint:brooks-debt
> 评估对象：[lib/backend/core/agent.py](file:///d:/代码/Open-AwA/lib/backend/core/agent.py)（2775 行，AIAgent 类 80+ 方法）
> 评估上下文：wave3 完成后（4 个父方法已拆分），对剩余技术债做完整扫描

---

## 报告头

**Mode:** Tech Debt Assessment
**Scope:** [lib/backend/core/agent.py](file:///d:/代码/Open-AwA/lib/backend/core/agent.py) (2775 行，AIAgent 类 80+ 方法)
**Health Score:** 20/100

AIAgent 类已积累系统性技术债：2 个 Critical 债务（长方法 + God Class）几乎阻塞任何非平凡改动，9 个 Warning 债务分布在 R2/R3/R4/R5/R6 五个维度，表明 decay 风险已系统性扩散而非局部问题。

---

## Findings

### Critical

**F1. R1 Cognitive Overload — 5 个方法超 80 行硬上限**
- **Symptom**: [lib/backend/core/agent.py](file:///d:/代码/Open-AwA/lib/backend/core/agent.py) 中 5 个方法超过项目硬上限（80 行）：
  - `_build_native_tools` ([L586-L703, 118 行](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L586-L703))
  - `__init__` ([L194-L306, 113 行](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L194-L306))
  - `_execute_single_plan_step` ([L2046-L2145, 100 行](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L2046-L2145))
  - `_handle_tool_calls_in_round` ([L1272-L1357, 86 行](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L1272-L1357))
  - `_emit_tool_post_events` ([L1576-L1659, 84 行](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L1576-L1659))
- **Source**: Fowler — Refactoring (Long Method)；项目 memory 中 "Long Method 拆分硬上限" 约束
- **Consequence**: wave3 仅拆分了 4 个父方法主体，拆出的子方法本身仍超阈值，长方法债务被"向下推"而非消除；100+ 行方法中任何改动都需在多分支间定位，回归风险高，开发者倾向于绕过而非修正。
- **Remedy**: 按 wave3 并行 subagent 模式启动 wave4：
  1. `_build_native_tools` 按 tool 来源四等分（plugin/MCP/builtin/task_runtime）
  2. `__init__` 按职责三等分（layers/memory/record_pipeline）
  3. `_execute_single_plan_step` 提取 `_execute_skill_branch` / `_execute_plugin_branch` / `_execute_regular_branch`
  4. `_handle_tool_calls_in_round` 提取 `_build_tool_messages` + `_handle_background_subagents_exit`
  5. `_emit_tool_post_events` 用 dict dispatch 替换 if 链
- **Pain × Spread**: 3 × 3 = 9（Critical debt，next sprint）

**F2. R2 Change Propagation — God Class: AIAgent 2775 行承载 80+ 方法**
- **Symptom**: [lib/backend/core/agent.py](file:///d:/代码/Open-AwA/lib/backend/core/agent.py) 单文件 2775 行，AIAgent 类包含 80+ 方法，覆盖意图识别、规划、工具分发、流式处理、状态机、记忆检索、经验提取、工作流执行、自主纠错、能力缓存、行为记录、预算追踪、灵魂注入等 13+ 个职责。Grep 显示 39 个 import 语句、17 处 lazy import。
- **Source**: Fowler — Refactoring (God Class, Divergent Change)；Brooks — The Mythical Man-Month (Ch. 2: Brooks's Law)
- **Consequence**: 任何新功能（新工具类型、新钩子、新事件类型）都需要修改 AIAgent，导致多开发者并行开发时合并冲突高发；测试套件必须通过 `AIAgent.__new__` 跳过 `__init__` 才能隔离测试，进一步加剧 T2 测试脆弱性；开发者"avoid touching it"是 Pain 3 的直接证据。
- **Remedy**: 按职责拆分为多个协作对象：
  1. `ToolDispatcher`（接管 `_dispatch_tool_call` / `_dispatch_ask_user_tool` / `_dispatch_regular_tool` / `_emit_tool_post_events`）
  2. `StreamOrchestrator`（接管 `_run_tool_calls_loop` / `_handle_tool_calls_in_round` / `_advance_state_machine_for_round` / `_finalize_stream`）
  3. `PlanExecutor`（接管 `_execute_plan_steps` / `_execute_single_plan_step` / `_handle_step_feedback` / `_auto_match_skills_plugins_for_process`）
  4. `CapabilityCache` 已存在（`CapabilityAggregator`），需进一步迁移 `_build_native_tools` / `_compute_tools_version`

  AIAgent 仅保留 process / process_stream 入口与极简协调逻辑。
- **Pain × Spread**: 3 × 3 = 9（Critical debt，next sprint）

### Warning

**F3. R1 Cognitive Overload — Long Parameter List**
- **Symptom**:
  - [lib/backend/core/agent.py:2256-2268](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L2256-L2268) `_collect_and_execute_in_parallel` 接收 10 个参数
  - [L1358-L1368](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L1358-L1368) `_advance_state_machine_for_round` 接收 8 个参数
  - [L1660-L1669](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L1660-L1669) `_finalize_stream` 接收 7 个参数
- **Source**: Fowler — Refactoring (Long Parameter List)
- **Consequence**: 调用方必须记住参数顺序，IDE 自动补全无法提示语义；参数间存在隐式约束（如 `intent`/`entities`/`intent_keywords`/`entities_list` 四个参数必须一致）却无法在签名中表达，容易传入不一致状态。
- **Remedy**: 提取 `PlanExecutionContext` dataclass 封装 `(intent, entities, intent_keywords, entities_list, user_input, context)`；提取 `RoundState` dataclass 封装 `(round_count, round_content, round_reasoning, state, effective_user_input)`。
- **Pain × Spread**: 2 × 2 = 4（Scheduled debt）

**F4. R2 Change Propagation — process vs process_stream 双路径 Divergent Change**
- **Symptom**: [lib/backend/core/agent.py:1852-1886](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L1852-L1886) `_prepare_process_context` 与 [L1116-L1164](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L1116-L1164) `_prepare_role_and_capabilities` 各自实现"魔法命令检查 + 上下文准备 + 能力注入 + 多模态/思考构建"，但行为略有差异（stream 路径有角色引擎加载与灵魂注入，process 路径没有）。
- **Source**: Fowler — Refactoring (Divergent Change)
- **Consequence**: 修改上下文准备逻辑（如新增"附件预处理"步骤）必须在两处同步修改，遗漏会导致 stream 与非 stream 行为不一致；当前已有差异（角色引擎只在 stream 路径触发）可能是 bug 也可能是设计，但代码未注释意图。
- **Remedy**: 提取统一的 `_prepare_execution_context(user_input, context, *, is_stream)` 模板方法，参数化差异点；或在 `ProcessContext` 对象中显式声明 `enable_role_engine` 等开关。
- **Pain × Spread**: 2 × 3 = 6（Scheduled debt）

**F5. R2 Change Propagation — tool_name 字符串硬编码多处（Shotgun Surgery）**
- **Symptom**: Grep 显示字符串 `"task_spawn_agent"` 在 [L1431](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L1431)、[L1546](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L1546)、[L1631](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L1631) 出现 3 次；`"builtin_ask_user"` 在 [L1447](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L1447) 出现；`"builtin_notify"` / `"builtin_todo_write"` / `"task_create_task"` / `"task_update_task"` / `"task_todo_write"` / `"task_create_team"` / `"task_delete_team"` / `"task_add_teammate"` / `"task_remove_teammate"` 等 9 个工具名在 `_emit_tool_post_events` 中硬编码。
- **Source**: Fowler — Refactoring (Shotgun Surgery)；Hunt & Thomas — The Pragmatic Programmer (Orthogonality)
- **Consequence**: 重命名任一工具名需在 3-5 处同步修改；新增工具类型（如 `task_create_label`）必须修改 `_emit_tool_post_events` 添加新分支，违反 OCP。
- **Remedy**: 提取 `ToolNames` 常量类（或 enum），所有引用改为 `ToolNames.TASK_SPAWN_AGENT`；事件派发改为 dict dispatch + 工具注册表模式。
- **Pain × Spread**: 2 × 3 = 6（Scheduled debt）

**F6. R3 Knowledge Duplication — `_execute_single_plan_step` 三分支重复**
- **Symptom**: [lib/backend/core/agent.py:2061-2144](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L2061-L2144) skill / plugin / execution 三个分支各自重复同一模式：`await execute_X(...) → results.append({type, step, result}) → self._schedule_record(node_type="tool_execution", ...) → record_tool_execution_metric(...)`，三段代码结构对称仅参数不同。
- **Source**: Hunt & Thomas — The Pragmatic Programmer (DRY)；Fowler — Refactoring (Duplicate Code)
- **Consequence**: 新增第 4 种执行类型（如 future "agent_tool"）时必须在 3 处对称位置添加分支；`_schedule_record` 调用契约变更需同步修改 3 处。
- **Remedy**: 提取 `_record_step_execution(step, result, execution_type, user_input, context)` 模板方法，三分支只传入差异化参数；或用 dict dispatch `{type: execute_fn}` 消除分支。
- **Pain × Spread**: 2 × 2 = 4（Scheduled debt）

**F7. R3 Knowledge Duplication — process vs process_stream 准备流程重复**
- **Symptom**: [lib/backend/core/agent.py:1804-1807](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L1804-L1807) `process` 调用 `_prepare_process_context`（魔法命令 + 上下文 + 能力注入 + 多模态 + 思考），[lib/backend/core/agent.py:1756-1760](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L1756-L1760) `process_stream` 调用 `_handle_magic_command_or_yield` + `_prepare_role_and_capabilities`（角色引擎 + 能力注入 + 多模态 + 思考），两条路径的"能力注入 + 多模态 + 思考"部分完全相同。
- **Source**: Fowler — Refactoring (Duplicate Code)
- **Consequence**: 修改能力注入或多模态构建逻辑需同步修改两处；wave1 提取的 `agent_context_builder` 已部分缓解，但调用点仍重复。
- **Remedy**: 统一为单一 `_prepare_context_pipeline(user_input, context, *, is_stream)` 入口，参数化差异点（角色引擎只在 stream 触发）。
- **Pain × Spread**: 2 × 2 = 4（Scheduled debt）

**F8. R4 Accidental Complexity — 14 个 deprecated 兼容别名（Speculative Generality 反向）**
- **Symptom**: [lib/backend/core/agent.py:183-516](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L183-L516) 保留 14 个 `# Deprecated: 仅为兼容测试` 的 staticmethod 别名：
  - `_is_final_only_mode` / `_build_status_event` / `_map_finish_reason_to_state`
  - `_get_stream_tool_kind` / `_summarize_stream_tool_result` / `_extract_spawned_subagent_result`
  - `_build_effective_user_input` / `_build_configured_model_hint`
  - `_strip_reasoning_content` / `_apply_scheduled_execution_defaults`
  - `_build_multimodal_context` / `_build_thinking_context`
  - `_summarize_skill_capabilities` / `_summarize_plugin_capabilities`
  - `_collect_mcp_capabilities` / `_collect_configured_model_capabilities`

  真实实现在 [agent_helpers.py](file:///d:/代码/Open-AwA/lib/backend/core/agent_helpers.py) / [agent_context_builder.py](file:///d:/代码/Open-AwA/lib/backend/core/agent_context_builder.py) / [agent_capability_builder.py](file:///d:/代码/Open-AwA/lib/backend/core/agent_capability_builder.py)。
- **Source**: Fowler — Refactoring (Speculative Generality, Lazy Class)；Winters et al. — Software Engineering at Google (Ch. 1: Hyrum's Law)
- **Consequence**: 真实抽象边界模糊，新开发者难以判断该调用 `agent._build_status_event` 还是 `agent_helpers.build_status_event`；别名成为事实 API（Hyrum's Law），移除时破坏 8 个测试文件，导致债务被"锁定"。
- **Remedy**: 落地 fix-test-implementation-coupling spec：
  1. 重写 8 个测试文件改用公开 API
  2. 一次性移除 14 个别名
  3. 在 CLAUDE.md Known Pitfalls 记录"禁止恢复 staticmethod 别名"约束
- **Pain × Spread**: 2 × 2 = 4（Scheduled debt，intentional）

**F9. R4 Accidental Complexity — `_emit_tool_post_events` Switch Statements**
- **Symptom**: [lib/backend/core/agent.py:1611-1658](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L1611-L1658) `_emit_tool_post_events` 用 7 个 `if tc_state.tool_name == "..."` 链式分发不同事件类型（builtin_notify / builtin_todo_write / task_spawn_agent / task_create_task / task_update_task / task_todo_write / task_create_team 等）。
- **Source**: Fowler — Refactoring (Switch Statements)
- **Consequence**: 新增工具类型必须修改 `_emit_tool_post_events` 添加新 if 分支，违反 OCP；7 个分支挤在 84 行方法中，是该方法是 Long Method Critical 的主要贡献者。
- **Remedy**: 改用 dict dispatch：`_TOOL_EVENT_DISPATCHERS: Dict[str, Callable[[tc_state, context], EventDict]] = {"builtin_notify": _emit_notification_event, "builtin_todo_write": _emit_todo_event, ...}`，新增工具类型只需注册新 dispatcher；或提取 `ToolEventDispatcher` 类。
- **Pain × Spread**: 2 × 2 = 4（Scheduled debt）

**F10. R5 Dependency Disorder — core/agent.py 反向依赖 db.models**
- **Symptom**:
  - [lib/backend/core/agent.py:249](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L249) `from db.models import SessionLocal`
  - [lib/backend/core/agent.py:2555](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L2555) `from db.models import Workflow`

  domain 层（core/）直接 import persistence 层（db/models.py 中的 SQLAlchemy ORM 类）。wave1 已通过 AskUserPort 解决了 `from api.routes.* import` 的反向依赖，但 persistence 反向依赖未处理。
- **Source**: Martin — Clean Architecture (Dependency Inversion Principle)
- **Consequence**: db/models.py schema 变更（如 Workflow 表字段重命名）直接传导到 core/agent.py；测试 core/agent.py 必须拖动完整 SQLAlchemy ORM 与数据库 fixture，是测试必须 `AIAgent.__new__` 跳过 `__init__` 的根因之一。
- **Remedy**: 仿 wave1 AskUserPort 模式：在 `core/ports/` 下定义 `WorkflowRepositoryPort` Protocol（含 `find_by_id(workflow_id) -> Optional[WorkflowDefinition]`），由 `api/adapters/workflow_repository_adapter.py` 实现，main.py lifespan 注入；`_execute_workflow_from_context` 改为 `self._workflow_repo.find_by_id()`。
- **Pain × Spread**: 2 × 2 = 4（Scheduled debt）

**F11. R6 Domain Model Distortion — Tool 分发逻辑在 service 层而非 domain**
- **Symptom**:
  - [lib/backend/core/agent.py:1406-1574](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L1406-L1574) `_dispatch_tool_call` / `_dispatch_ask_user_tool` / `_dispatch_regular_tool` 在 AIAgent service 层实现工具分发领域逻辑（解析参数、发射 running 事件、按工具名委派、处理取消/超时/参数校验）
  - [L1576-L1659](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L1576-L1659) `_emit_tool_post_events` 在 service 层实现工具事件派发领域逻辑
  - `_ToolCallState` ([L158-L172](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L158-L172)) 是纯数据袋，无任何行为
- **Source**: Evans — Domain-Driven Design (Anemic Domain Model, Domain Model pattern)；Fowler — Refactoring (Data Class)
- **Consequence**: 工具分发的领域规则散落在 service 层方法中，无法在 domain 层单元测试；新增工具类型需修改 service 层而非扩展 domain 模型；`_ToolCallState` 作为纯数据袋被 4 个 service 方法读写，状态一致性靠开发者记忆维护。
- **Remedy**: 提取 `ToolDispatcher` 领域对象，封装工具分发规则与 `_ToolCallState` 状态机；`_emit_tool_post_events` 提取为 `ToolEventEmitter` 对象，按工具类型注册 dispatcher 策略。
- **Pain × Spread**: 2 × 2 = 4（Scheduled debt）

### Suggestion

**F12. R1 Cognitive Overload — Magic numbers 跨方法耦合**
- **Symptom**:
  - [lib/backend/core/agent.py:1183](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L1183) `if len(conversation_history) > 40:`
  - [lib/backend/core/agent.py:1056](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L1056) `if not budget.should_compress() and len(messages) <= 40:`

  在两处独立硬编码同一阈值 40；[L969](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L969) `MAX_MSG_CHARS = 5_000` 在方法内局部定义。
- **Source**: McConnell — Code Complete (Ch. 12: Fundamental Data Types)
- **Consequence**: 压缩阈值调整时需同步修改两处，遗漏会导致状态事件与实际压缩行为不一致。
- **Remedy**: 提取为 `agent_helpers.COMPACTION_MESSAGE_THRESHOLD = 40` 常量，两处引用同一常量；`MAX_MSG_CHARS` 提升为模块级常量。
- **Pain × Spread**: 1 × 2 = 2（Monitored debt）

**F13. R3 Knowledge Duplication — 14 个 deprecated 别名构成双调用入口**
- **Symptom**: 同 F8。14 个别名使同一函数有两个调用入口（`AIAgent._method` 与 `agent_helpers.function`），新开发者调用方不一致。
- **Source**: Hunt & Thomas — The Pragmatic Programmer (DRY: Don't Repeat Yourself)
- **Consequence**: 知识重复——同一决策（如"如何判断 final_only_mode"）在两个位置表达，未来修改时可能只改一处。
- **Remedy**: 同 F8，落地 fix-test-implementation-coupling spec 后整体移除。
- **Pain × Spread**: 1 × 2 = 2（Monitored debt）

**F14. R4 Accidental Complexity — Lazy imports 散落 17 处**
- **Symptom**: Grep 显示 [lib/backend/core/agent.py](file:///d:/代码/Open-AwA/lib/backend/core/agent.py) 中有 17 处方法内 lazy import：
  - `from config.settings import settings`
  - `from memory.manager import MemoryManager`
  - `from core.role_engine import RoleEngine`
  - `from core.builtin_tools.manager import builtin_tool_manager`
  - 等

  部分是为避免循环依赖（合理），部分是为减少启动开销（可商榷）。
- **Source**: McConnell — Code Complete (Ch. 5: Design in Construction)
- **Consequence**: 模块依赖图不透明，IDE 跳转需进入方法内才能看到 import；部分 lazy import（如 `from db.models import Workflow`）掩盖了真实依赖方向。
- **Remedy**: 区分两类：
  1. 避免循环依赖的 lazy import（如 `from config.settings`）保留，但提取到模块顶部用 `TYPE_CHECKING` 注解
  2. 仅减少启动开销的 lazy import（如 `from core.role_engine`）合并到模块顶部
- **Pain × Spread**: 1 × 2 = 2（Monitored debt）

**F15. R5 Dependency Disorder — 模块扇出 > 30**
- **Symptom**: [lib/backend/core/agent.py](file:///d:/代码/Open-AwA/lib/backend/core/agent.py) 顶部 import 39 个符号，跨 6 个子包（core/、memory/、skills/、plugins/、workflow/、billing/），加上 17 处 lazy import，总扇出 > 50。
- **Source**: Martin — Clean Architecture (Stable Dependencies Principle)
- **Consequence**: 任何子包变更都可能影响 AIAgent；测试隔离困难，是 `AIAgent.__new__` 模式的根因之一。
- **Remedy**: 通过 God Class 拆分（F2）与 RepositoryPort 抽象（F10）自然降低扇出；目标将 AIAgent 扇出降至 < 15。
- **Pain × Spread**: 1 × 3 = 3（Monitored debt）

**F16. R6 Domain Model Distortion — `_ToolCallState` anemic data class**
- **Symptom**: [lib/backend/core/agent.py:157-172](file:///d:/代码/Open-AwA/lib/backend/core/agent.py#L157-L172) `_ToolCallState` 是 `@dataclass`，仅包含 8 个字段无任何方法；4 个 service 方法（`_dispatch_tool_call` / `_dispatch_ask_user_tool` / `_dispatch_regular_tool` / `_emit_tool_post_events`）读写其字段。
- **Source**: Fowler — Refactoring (Data Class)；Evans — Domain-Driven Design (Anemic Domain Model)
- **Consequence**: 状态一致性规则（如"result 必须在 tool_name 之后设置"）散落在 4 个方法中，无法在 dataclass 内聚。
- **Remedy**: 与 F11 合并：将 `_ToolCallState` 升级为 `ToolCallContext` 领域对象，封装状态转换规则（如 `mark_running(tool_name, tool_id)` / `set_result(result)` / `mark_background_subagent()`）。
- **Pain × Spread**: 1 × 2 = 2（Monitored debt）

---

## Debt Summary

| Risk | Findings | Avg Priority | Classification | Intent |
|------|----------|-------------|----------------|--------|
| Cognitive Overload (R1)      | 3 (F1, F3, F12) | 4.7 | Critical + Scheduled + Monitored | accidental |
| Change Propagation (R2)      | 3 (F2, F4, F5) | 5.7 | Critical + Scheduled | accidental |
| Knowledge Duplication (R3)   | 3 (F6, F7, F13) | 3.7 | Scheduled + Monitored | accidental |
| Accidental Complexity (R4)   | 3 (F8, F9, F14) | 3.3 | Scheduled + Monitored | mixed (F8 intentional) |
| Dependency Disorder (R5)     | 2 (F10, F15) | 4.0 | Scheduled + Monitored | accidental |
| Domain Model Distortion (R6) | 2 (F11, F16) | 2.5 | Scheduled + Monitored | mixed (F16 intentional) |

### 优先级矩阵

| Priority | Finding | Risk | Action |
|----------|---------|------|--------|
| 9 (Critical) | F1 Long Method × 5 | R1 | next sprint |
| 9 (Critical) | F2 God Class | R2 | next sprint |
| 6 (Scheduled) | F4 process 双路径 | R2 | within quarter |
| 6 (Scheduled) | F5 tool_name shotgun | R2 | within quarter |
| 4 (Scheduled) | F3 Long Parameter List | R1 | within quarter |
| 4 (Scheduled) | F6 三分支重复 | R3 | within quarter |
| 4 (Scheduled) | F7 准备流程重复 | R3 | within quarter |
| 4 (Scheduled) | F8 14 别名 | R4 | within quarter (intentional) |
| 4 (Scheduled) | F9 Switch Statements | R4 | within quarter |
| 4 (Scheduled) | F10 DIP 违反 | R5 | within quarter |
| 4 (Scheduled) | F11 domain logic 位置 | R6 | within quarter |
| 3 (Monitored) | F15 扇出 > 30 | R5 | watch |
| 2 (Monitored) | F12 magic numbers | R1 | watch |
| 2 (Monitored) | F13 双调用入口 | R3 | watch |
| 2 (Monitored) | F14 lazy imports | R4 | watch |
| 2 (Monitored) | F16 anemic data class | R6 | watch (intentional) |

---

## Recommendation

**Recommended focus:** R2 Change Propagation (Avg 5.7) 与 R1 Cognitive Overload (Avg 4.7) 是最紧迫的修复方向——两者共同指向 God Class 拆分（F2）作为最高 ROI 的单一动作：拆出 `ToolDispatcher` / `StreamOrchestrator` / `PlanExecutor` 后，F1（长方法）、F3（长参数列表）、F5（shotgun surgery）、F11（domain logic 位置）会同时缓解。R3 与 R4 的修复依赖 F2 完成（提取出的子对象天然消除重复与 switch statements）。R5 DIP 违反（F10）建议单独启动 `decouple-agent-from-persistence` spec，避免与 God Class 拆分冲突。

### 推荐执行路径

```
wave4 (next sprint, 并行 subagent)
  ├─ Task 1: 拆分 _build_native_tools (118→4×30)
  ├─ Task 2: 拆分 __init__ (113→3×38)
  ├─ Task 3: 拆分 _execute_single_plan_step (100→3 分支提取)
  ├─ Task 4: 拆分 _handle_tool_calls_in_round (86→2 子方法)
  └─ Task 5: _emit_tool_post_events 改 dict dispatch (84→<40)
      ↓
wave5 (within quarter, 串行)
  ├─ F2 God Class 拆分: ToolDispatcher / StreamOrchestrator / PlanExecutor
  ├─ F8 fix-test-implementation-coupling spec: 移除 14 别名 + 重写 8 测试
  └─ F10 decouple-agent-from-persistence spec: WorkflowRepositoryPort
      ↓
wave6 (within quarter, 收尾)
  ├─ F3 Long Parameter List: PlanExecutionContext / RoundState dataclass
  ├─ F5 ToolNames 常量类
  └─ F12 magic numbers 提常量
```

### 预期收益

- wave4 完成后：Health Score 从 20 → ~55（消除 2 个 Critical，5 个 Warning 降级）
- wave5 完成后：Health Score 从 55 → ~75（God Class 拆分消除 5 个 Warning，DIP 修复消除 1 个 Warning）
- wave6 完成后：Health Score 从 75 → ~85（剩余 Suggestion 级别债务清理）

---

## 修复验收证据

验收时间：2026-07-26。以下结果以本轮修复后的 `lib/backend/core/agent.py` 和生产构造路径为准。

| Finding | 状态 | 修复证据 |
|---|---|---|
| F1 | 已修复 | `AIAgent` 最长方法为 `process_stream` 79 行，架构契约强制所有方法不超过 80 行。 |
| F2 | 已修复 | `agent.py` 从 2775 行降至 1457 行，`AIAgent` 为 48 个方法；职责拆入 `AgentRuntime`、`AgentTaskRegistry`、`PlanExecutor`、`StreamOrchestrator`、`ToolDispatcher` 和 `ToolEventEmitter`。 |
| F3 | 已修复 | 方法最大参数数为 7；执行阶段参数收敛到 execution-context dataclass。 |
| F4 | 已修复 | 非流式与流式入口复用 `AgentRuntime` 和统一执行上下文，差异由编排器承载。 |
| F5 | 已修复 | 工具名称分类与事件规则集中到 `ToolDispatcher`、`ToolEventEmitter`，不再散落在 `AIAgent` 多个分支中。 |
| F6 | 已修复 | 计划步骤执行收敛到 `PlanExecutor`，统一执行、结果追加、记录和指标流程。 |
| F7 | 已修复 | 两条聊天路径共享运行时准备与 collaborator 组装，不再维护两套准备知识。 |
| F8 | 已修复 | 删除 14 个静态兼容别名；仓库不存在指向已移除 `AIAgent` 私有 helper 的测试引用。 |
| F9 | 已修复 | 工具后置事件由 `ToolEventEmitter` 按规则分发，`AIAgent` 不再维护长 if 链。 |
| F10 | 已修复 | 新增 `WorkflowRepositoryPort` 与 API adapter；`agent.py` 不导入 `db.models` 或 `api.routes`，生产路径注入 memory session factory。 |
| F11 | 已修复 | 工具调用状态转换和分发规则迁入 `ToolDispatcher` 与 `ToolCallContext`，可独立单测。 |
| F12 | 已修复 | 工具分类、事件类型和运行时阈值集中到职责对象，不再跨多个 `AIAgent` 方法复制魔法值。 |
| F13 | 已修复 | 与 F8 同步完成，单一公共调用入口由架构测试持续约束。 |
| F14 | 已修复 | AST 检查确认 `AIAgent` 方法内 import 数为 0。 |
| F15 | 已修复 | `agent.py` 直接项目模块扇出为 8，低于目标 15。 |
| F16 | 已修复 | `_ToolCallState` 已由具备状态转换行为的 `ToolCallContext` 替代。 |

### 自动化验证

- Brooks 定向回归：147 passed。
- 最终架构专项：10 passed，覆盖方法长度、参数数、嵌套 import、扇出、依赖方向、生产 collaborator 注入、计划执行、流编排、Workflow Repository Port 和 chat 场景终态。
- 后端完整分组回归：4554 passed，7 skipped。
- 前端：`npm run test -- --run`、`npm run lint`、`npm run typecheck`、`npm run build` 全部通过；lint 为 0 error、54 个既有 warning。
- 静态检查：任务 Python 文件 Ruff 通过，`git diff --check` 通过；结构指标为 1457 行、48 方法、最长方法 79 行、最大参数数 7、嵌套 import 0、直接项目模块扇出 8。

### 隔离运行时验证

- 使用独立 SQLite、Qdrant、workspace、日志目录和初始化标记启动 `127.0.0.1:18000`，未停止或修改现有用户服务。
- `/api/system/init-csrf-token`、`/api/system/init`、JWT 登录、`/api/auth/me` 与 `/api/system/ping` 均返回成功。
- 使用仅监听 `127.0.0.1:18001` 的 OpenAI 兼容测试桩和隔离数据库虚拟凭据完成模型调用，不读取用户密钥、不访问外网。
- `/api/test-scenarios/run-all`：10 passed，0 failed；显式 `chat-nonstream`：1 passed，0 failed，终态 `completed`。
- SSE：HTTP 200，`text/event-stream`，包含 `status`、`plan`、`chunk` 结构化帧和有效内容，严格以 `data: [DONE]` 结束。
- WebSocket：合法 Origin 与 `bearer.<JWT>` 子协议协商成功，依次收到 `response_chunk` 和最终 `response`；请求 ID、64 位校验和一致，终态 `completed`。
- 真实 Chromium：聊天输入框、用户消息和助手回复均可见，page error 为 0；仅记录一个与本次修复无关的既有 React `fetchPriority` 开发警告。

## 附录：评估方法说明

### 评估工具

- **Skill**: `trae-remote-official:brooks-lint:brooks-debt`
- **评估依据**: 12 本经典工程书籍（见 source-coverage.md）
- **评分公式**: Pain × Spread（max 9）
  - Pain 1-3: 当前开发痛感
  - Spread 1-3: 影响文件/模块/开发者数

### 评估范围

- 文件：`lib/backend/core/agent.py`
- 行数：2775 行
- 类：AIAgent（80+ 方法）
- 评估时点：wave3 完成后（2026-07-26）

### 历史趋势

| Wave | 日期 | Score | 关键变化 |
|------|------|-------|---------|
| wave1 | 2026-07-20 | 53 | 提取 agent_helpers + AskUserPort |
| wave2 | 2026-07-25 | 89 | 拆分 process_stream / process 主体 |
| wave3 | 2026-07-26 | 92 | 拆分 4 个父方法 + 9 个单测 |
| wave4 (本次评估) | 2026-07-26 | 20 (debt) | 完整 decay 风险扫描，识别 16 个 findings |

> 注：Health Dashboard 评分（80）与本次 Tech Debt Assessment 评分（20）差异源于评分维度不同——Health Dashboard 含 Architecture/Debt/Test 三维加权，Tech Debt 仅评估债务绝对值。

---

## 附录：参考来源

| Book | Author | 引用条目 |
|------|--------|---------|
| Refactoring | Martin Fowler | Long Method, Long Parameter List, God Class, Divergent Change, Shotgun Surgery, Duplicate Code, Speculative Generality, Lazy Class, Middle Man, Switch Statements, Data Class, Feature Envy |
| Clean Architecture | Robert C. Martin | DIP, ADP, SDP, SAP, ISP, LSP, SRP, OCP |
| The Pragmatic Programmer | Hunt & Thomas | Orthogonality, DRY, Law of Demeter |
| Domain-Driven Design | Eric Evans | Ubiquitous Language, Bounded Context, Anemic Domain Model, Domain Model pattern |
| The Mythical Man-Month | Frederick Brooks | Brooks's Law, Conceptual Integrity, Second-System Effect |
| Code Complete | Steve McConnell | Routine length, Naming, Magic numbers, Design in Construction |
| A Philosophy of Software Design | John Ousterhout | Deep vs shallow modules, Strategic vs tactical programming, Information Leakage |
| Software Engineering at Google | Winters et al. | Hyrum's Law, Dependency management |
| xUnit Test Patterns | Meszaros | Assertion Roulette, Mystery Guest, General Fixture, Eager Test, Erratic Test |
| The Art of Unit Testing | Osherove | Test naming, Test isolation, Mock usage |
| Working Effectively with Legacy Code | Feathers | Legacy code, Seams, Characterization Tests |
| How Google Tests Software | Google | Change coverage, Pyramid shape |

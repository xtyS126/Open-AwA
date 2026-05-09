# Subagent 模型选择修复与等待控制 Spec

## Why

当前 Subagent 系统存在两个核心问题：
1. **模型未选择 Bug**：Subagent 被调用时，LLM 可能不传 `provider`/`model` 参数，导致子代理无法正确解析所使用的模型，可能回退到无模型状态或使用错误的默认模型。
2. **前台模式不工作**：当前 `task_spawn_agent` 的前台模式（`background=false`）返回的是 `AsyncGenerator`，但 `executor._execute_tool_call()` 并未消费该生成器，直接返回占位消息 `"前台子代理已启动，通过 SSE 流获取结果"`，导致子代理实际从未运行，主 Agent 也无法获取子代理的真实输出。

## What Changes

- **修复前台子代理执行链路**：让 `_execute_tool_call` 或上层工具执行循环消费前台模式的 `AsyncGenerator`，将子代理的流式输出通过 SSE 事件实时转发给前端，并将最终摘要作为工具调用结果返回给主 Agent。
- **修复模型参数传递与选择**：确保 Subagent 被调用时，能从主 Agent 的上下文中继承或明确指定模型，避免子代理无模型运行。
- **明确两种等待模式的行为**：
  - **不等待模式** (`background=true`)：主 Agent 调用 Subagent 后立即继续下一步（思考+调用+回复），UI 中仅显示调用了 `task_spawn_agent` 工具，子代理结果通过独立事件异步推送，不阻塞主流程。
  - **等待模式** (`background=false`)：主 Agent 调用 Subagent 后阻塞等待子代理运行结束，获取子代理的最终输出摘要作为工具调用回复内容，UI 中展示完整的"思考+调用 Subagent+等待 Subagent 运行完成+回复"流程。

## Impact

- Affected specs: `diagnose-and-fix-task-toolchain`, `enhance-continuous-tool-calling-display`
- Affected code:
  - `backend/core/executor.py` -- `_execute_tool_call` 中 `task_spawn_agent` 分支
  - `backend/core/agent.py` -- 工具调用循环、子代理事件发射
  - `backend/core/task_runtime/runners.py` -- `run_foreground` 流式输出
  - `backend/core/task_runtime/facade.py` -- `spawn_agent` 入口
  - `frontend/src/features/chat/ChatPage.tsx` -- 子代理 SSE 事件处理
  - `frontend/src/features/chat/components/AssistantThoughtSegment.tsx` -- 子代理 UI 渲染

## ADDED Requirements

### Requirement: 前台子代理同步等待执行

系统 SHALL 在前台模式 (`background=false`) 下，主 Agent 调用 `task_spawn_agent` 后阻塞等待子代理运行完成，并将子代理的最终输出摘要作为工具调用结果返回给主 Agent。

#### Scenario: 主 Agent 等待子代理完成

- **GIVEN** 主 Agent 调用 `task_spawn_agent` 且 `background=false`（或不传，默认为 false）
- **WHEN** 工具执行时接收到 `run_foreground` 返回的 `AsyncGenerator`
- **THEN** 系统 SHALL 消费该生成器的所有 chunk，通过 SSE 事件实时转发 `subagent_start`、`agent_message`、`subagent_stop` 给前端
- **AND** 系统 SHALL 将子代理的最终摘要作为工具调用结果返回给主 Agent
- **AND** 主 Agent SHALL 在获得子代理结果后继续生成回复

#### Scenario: 主 Agent 不等待子代理（后台模式）

- **GIVEN** 主 Agent 调用 `task_spawn_agent` 且 `background=true`
- **WHEN** 工具执行返回后台结果 `{"agent_id": "...", "status": "queued"}`
- **THEN** 系统 SHALL 立即将该结果返回给主 Agent
- **AND** 主 Agent SHALL 在收到结果后立即继续下一步（思考或回复）
- **AND** 子代理的运行时更新通过独立 SSE 事件异步推送

#### Scenario: 前台子代理执行失败

- **GIVEN** 前台子代理运行过程中抛出异常
- **WHEN** `run_foreground` 生成器产生错误
- **THEN** 系统 SHALL 将错误信息包含在工具调用结果中返回主 Agent
- **AND** 系统 SHALL 通过 `subagent_stop` 事件通知前端子代理执行失败

### Requirement: 子代理模型选择

系统 SHALL 确保子代理在启动时能正确解析并选择所使用的模型，包括从主 Agent 上下文继承模型和从工具调用参数指定模型。

#### Scenario: LLM 在工具调用中明确指定模型

- **GIVEN** LLM 调用 `task_spawn_agent` 时传入了 `provider` 和 `model` 参数或 `provider:model` 格式的 `model` 参数
- **WHEN** 系统执行 `_normalize_subagent_model_selection` 解析参数
- **THEN** 系统 SHALL 将解析后的 `provider` 和 `model` 传入子代理上下文
- **AND** 子代理 SHALL 使用指定的模型运行

#### Scenario: LLM 未指定模型时回退到主 Agent 的模型

- **GIVEN** LLM 调用 `task_spawn_agent` 时未传入 `model` 参数
- **WHEN** 系统执行模型选择逻辑
- **THEN** 系统 SHALL 从主 Agent 上下文（`context.get("provider")`、`context.get("model")`、`context.get("configured_model_catalog")`）中继承模型配置
- **AND** 子代理 SHALL 使用主 Agent 当前正在使用的模型运行

#### Scenario: 无法解析任何有效模型

- **GIVEN** LLM 未指定模型且主 Agent 上下文中也没有有效模型配置
- **WHEN** 系统尝试启动子代理
- **THEN** 系统 SHALL 返回明确错误信息 `"未能解析子代理模型，请指定 provider/model 参数或确保主会话已配置模型"`
- **AND** 子代理 SHALL NOT 被启动

## MODIFIED Requirements

### Requirement: task_spawn_agent 工具定义

**变更**：`task_spawn_agent` 工具的描述中应更明确地说明 `background` 参数的两种行为差异。

- `background=false`（默认）：主 Agent 等待子代理完成后获取摘要结果
- `background=true`：主 Agent 不等待，子代理异步执行，结果通过独立通道推送

### Requirement: 子代理 SSE 事件流（前台模式）

**变更**：前台模式下子代理的 SSE 事件流从原来的"不工作"变为"完整流式转发"。

事件顺序：
1. `subagent_start` -- 子代理启动
2. `agent_message`（可选，多次）-- 子代理的流式输出日志
3. `subagent_stop` -- 子代理完成（含摘要）

## REMOVED Requirements

无。

# Tasks

## Task 1: 修复 executor 中前台子代理的执行链路

**描述**: `backend/core/executor.py` 的 `_execute_tool_call` 中，当前台模式 `spawn_agent` 返回 `AsyncGenerator` 时，需要将其改为阻塞消费生成器，获取子代理最终结果。

- [x] SubTask 1.1: 修改 `_execute_tool_call` 中 `task_spawn_agent` 分支的 foreground 路径
  - 当前 `isinstance(result, dict)` 为 false 时直接返回占位消息，需改为 `async for` 消费生成器
  - 收集所有 chunk，提取最终响应作为工具调用结果
  - 将 subagent 的 `agent_id`、`run_mode`、`summary` 等信息包含在返回结果的 result 中
  - 如果生成过程中出现异常，返回 error 状态的结果

- [x] SubTask 1.2: 在 `_execute_tool_call` 方法签名中添加可选的 `on_subagent_event` 回调参数
  - 回调签名为 `Callable[[Dict[str, Any]], Awaitable[None]]`
  - 用于将子代理 SSE chunk 转发到主 Agent 的 SSE 流中

**验证**: 前台模式下调用 `task_spawn_agent` 能获取子代理真实执行结果而不是占位消息。

---

## Task 2: 修复 agent.py 中的子代理事件发射逻辑

**描述**: `backend/core/agent.py` 中工具调用循环需要适配新的前台子代理执行链路。

- [x] SubTask 2.1: 修改第 1508 行附近的工具执行调用处
  - 在调用 `self.executor._execute_tool_call(tc, context)` 时，传入 `on_subagent_event` 回调
  - 回调中 `yield` 子代理的 `subagent_start`、`agent_message`、`subagent_stop` 事件到主 SSE 流

- [x] SubTask 2.2: 更新第 1532-1555 行的子代理事件发射逻辑
  - 统一后台和前台模式的 `subagent_start`/`subagent_stop` 事件格式
  - 前台模式下方在 `on_subagent_event` 回调中已经 yield 过事件，工具的 completed 事件仅包含摘要信息
  - 移除现有"未返回可追踪 agent_id"的 warning，因为前台模式修复后将始终有 agent_id

**验证**: 前端能收到前台子代理的完整事件流（subagent_start -> agent_message -> subagent_stop）。

---

## Task 3: 强化子代理模型选择与回退机制

**描述**: 确保子代理在任何情况下都能正确获得模型配置。

- [x] SubTask 3.1: 在 `executor._execute_tool_call` 的 `task_spawn_agent` 分支中增强模型回退
  - 当 LLM 未传 `model` 参数时，尝试从 `context` 中提取当前正在使用的模型（`context.get("model")`）
  - 当 LLM 未传 `provider` 参数时，尝试从 `context.get("provider")` 继承
  - 如果仍然无法确定模型，调用 `_resolve_llm_configuration` 查找该 provider 的默认配置（已有能力）
  - 如果最终仍无法确定模型，返回明确错误而非静默失败

- [x] SubTask 3.2: 更新 `_normalize_subagent_model_selection` 使其在无 provider 但有 model 时也能更智能地匹配
  - 如果 model 是完整名称（如 `gpt-4o`），在 `configured_model_catalog` 中查找匹配的 provider
  - 如果找不到匹配，保留 model 并尝试在子代理内部通过 litellm 自动路由

- [x] SubTask 3.3: 在 `runners.py` 的 `run_foreground`/`run_background` 中，确保 `sub_context["model"]` 和 `sub_context["provider"]` 在为空时能正确回退
  - 当 `provider` 为空时，检查 context 中的 `configured_model_catalog` 中有无默认配置
  - 当 `model` 为空时，使用 provider 的默认模型

**验证**: 子代理在 LLM 不传模型参数时也能正确选择模型运行。

---

## Task 4: 优化 task_spawn_agent 工具定义描述

**描述**: 让 LLM 更清楚地理解 `background` 参数的两种行为差异。

- [x] SubTask 4.1: 更新 `agent.py` 中 `task_spawn_agent` 工具定义的 description
  - 明确说明 `background` 参数的含义和行为差异
  - 在 model_hint 中包含当前正在使用的模型信息，引导 LLM 正确传递

**验证**: LLM 在调用 `task_spawn_agent` 时能根据场景正确选择 `background` 参数值。

---

## Task 5: 前端适配前台子代理事件流

**描述**: 确保前端能正确处理前台模式下子代理的完整事件流。

- [x] SubTask 5.1: 检查 `ChatPage.tsx` 中 SSE 事件处理是否兼容前台模式
  - 前台模式下事件顺序：`subagent_start` -> `agent_message`(s) -> `subagent_stop`
  - 确保 `subagent_stop` 在主 Agent 的工具调用完成事件之前到达
  - 前台模式下子代理的 `subagent_stop` 不应触发超时清理逻辑

- [x] SubTask 5.2: 更新 `AssistantThoughtSegment.tsx` 中子代理渲染逻辑
  - 前台模式下子代理的次级思维链作为工具调用的一部分在时间轴中展示
  - 子代理完成后的摘要应显示为工具结果的一部分

- [x] SubTask 5.3: 更新 `executionMeta.ts` 中 `applySubagentStop` 逻辑
  - 前台模式子代理完成时，将 summary 内容关联到对应的 toolEvent

**验证**: 前端能正确渲染前台子代理的执行过程和结果。

---

# Task Dependencies

- Task 2 依赖 Task 1（修改 agent.py 需要 executor 先提供正确的接口）
- Task 3 可与 Task 1-2 并行
- Task 4 可与 Task 1-3 并行
- Task 5 依赖 Task 1-2（前端适配需要后端事件流先正常工作）

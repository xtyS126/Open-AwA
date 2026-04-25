# 修复工具调用流式链路断裂 Spec

## Why

用户在浏览器中观察到，工具调用（即执行详情中的 `div` 面板）在流式模式下根本不可用——一旦 LLM 返回 `tool_calls`，整个执行链条直接断裂。具体表现为：
1. 后端 `process_stream()` 仅在流模式直接绕过工具调用处理逻辑
2. LLM 流式响应中返回的 `tool_calls` 被完全忽略，未被解析执行
3. 前端 SSE 事件流中从未收到 `task`/`tool` 事件，导致执行详情面板中的步骤永远停留在"等待中"状态
4. 没有任何错误状态或降级通知给用户

## What Changes

- **核心修复**：在 `agent.py` 的 `process_stream()` 中增加 `tool_calls` 循环处理逻辑——当 LLM 流响应结束后检测 `tool_calls`，执行对应工具，将结果回填到 `messages`，然后继续 LLM 调用
- **SSE 事件补齐**：在流模式中正确发射 `task`（步骤状态）和 `tool`（工具调用状态）SSE 事件，确保前端执行详情面板能实时更新
- **错误容错**：工具调用失败时不直接断链，而是将错误信息作为 `tool` 结果返回给 LLM，由 LLM 决定降级或重试
- **超时保护**：为流模式下的工具调用增加超时控制，避免某个工具卡死整个流
- **前端兼容**：前端 SSE 解析层确保即使 `task`/`tool` 事件迟到或乱序也能正确合并状态

## Impact

- Affected specs: AI 对话流式链路、工具调用协议、执行详情面板
- Affected code:
  - `backend/core/agent.py` — `process_stream()` 增加 tool_calls 循环
  - `backend/core/executor.py` — 增加流模式下工具执行的辅助方法
  - `backend/api/services/chat_protocol.py` — 确保 `task`/`tool` 事件在流模式中可用
  - `frontend/src/features/chat/utils/executionMeta.ts` — 兼容乱序/迟到事件
  - `frontend/src/features/chat/ChatPage.tsx` — SSE 事件分发路径验证
  - 相关测试文件

## ADDED Requirements

### Requirement: 流式工具调用循环

系统 SHALL 在流式模式下支持完整的 LLM `tool_calls` 调用循环。

#### Scenario: LLM 流式响应返回 tool_calls
- **WHEN** 流式模式下 LLM 完成流式输出且返回 `tool_calls`
- **THEN** 系统解析 `tool_calls`，执行对应 MCP/Plugin/Skill 工具，将执行结果回填到 `messages` 作为 `role: "tool"`，然后继续调用 LLM 生成最终回复
- **AND** `tool` 事件在工具执行前（status=running）、执行中（status=running）、执行完成后（status=completed/error）分别发射

#### Scenario: 流式模式多轮工具循环
- **WHEN** LLM 在一次回复中返回多个 `tool_calls`，或基于工具结果再次调用工具
- **THEN** 系统支持多轮工具调用循环，直到 LLM 不再返回 `tool_calls`

#### Scenario: 流式模式纯对话（无工具调用）
- **WHEN** LLM 流式响应中不含 `tool_calls`
- **THEN** 行为保持不变，直接透传 `chunk` 事件

### Requirement: 流式工具调用容错

系统 SHALL 在工具调用失败时保持流式链路不断裂。

#### Scenario: 工具调用异常
- **WHEN** 工具调用抛出异常或超时
- **THEN** 系统将错误信息作为 `role: "tool"` 结果返回给 LLM，并发射 `tool` 事件标记为 status=error 并包含 detail
- **AND** 不中断流式链路，由 LLM 决定降级回复或重试

#### Scenario: 工具调用超时
- **WHEN** 单个工具调用超过配置的超时阈值（默认 30s）
- **THEN** 系统中断该工具调用，返回超时错误给 LLM

### Requirement: SSE 事件时序正确

系统 SHALL 在流模式中按正确时序发射 `task` 和 `tool` 事件。

#### Scenario: 执行步骤更新
- **WHEN** 工具调用循环开始/完成
- **THEN** 系统发射 `task` 事件，status 从 `running` 更新为 `completed`/`error`

#### Scenario: 工具调用状态更新
- **WHEN** 单个工具开始执行/执行完成/执行失败
- **THEN** 系统发射 `tool` 事件，status 反映对应状态，detail 包含结果摘要或错误信息

### Requirement: 前端迟序事件兼容

前端 SHALL 兼容 `task`/`tool` 事件迟到或乱序到达。

#### Scenario: 乱序事件处理
- **WHEN** 前端收到 `tool` 事件的时间顺序与发射顺序不一致
- **THEN** 前端按 `tool.id` 合并状态，不因乱序覆盖正确状态

#### Scenario: 迟到事件处理
- **WHEN** 前端在 `chunk` 完成后才收到 `tool` 事件
- **THEN** 前端仍然正确合并到执行详情面板中

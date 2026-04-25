# 修复审计发现的 P0/P1 安全与性能风险

## Why

综合审计报告（audit-ai-tool-calling-pipeline）识别出 31 项风险，其中 P0 级 5 项、P1 级 10 项、P2 级 12 项、P3 级 7 项。现有的 `fix-p0-security-vulnerabilities`、`engineering-refactor-p0-p1`、`fix-code-review-issues-p1-p3` 等规格已覆盖部分问题（如沙箱命令注入、SQL 注入、全局单例、日志持久化等），但仍有大量审计识别的 P0/P1 风险未被修复。

## What Changes

### 后端安全加固
- 匿名 AI 调用限制：`get_optional_current_user` 改为 `get_current_user`，要求登录才能调用 AI
- JWT 黑名单机制：在 redis/内存中维护已吊销 token 列表
- 日志脱敏保护：移除通过配置关闭脱敏的能力，强制脱敏
- CSRF Cookie 加固：添加 HttpOnly、SameSite=Lax 标志

### 后端可靠性增强
- 全链路超时控制：在每个阶段添加 `asyncio.wait_for` 超时
- LLM 调用重试/退避/熔断：在 litellm_adapter 中添加指数退避重试
- 异步日志写入：行为日志和会话记录改为异步批量写入
- Rate Limit：添加 `slowapi` 全局限流器

### 前端修复
- localStorage 高频写入优化：流式更新使用 debounce/throttle
- HTTP 错误双重通知修复：统一错误处理通道
- ChatPage.tsx 拆分：提取子组件

## Impact
- Affected code: backend/api/routes/chat.py, backend/core/agent.py, backend/core/litellm_adapter.py, backend/api/dependencies.py, backend/config/security.py, backend/core/behavior_logger.py, backend/core/conversation_recorder.py, frontend/src/features/chat/ChatPage.tsx, frontend/src/shared/api/api.ts
- Affected specs: auth, chat, security

## ADDED Requirements

### Requirement: Anonymous AI Call Restriction

The system SHALL require authenticated users to call AI endpoints.

**Scenario: Unauthenticated user calls chat endpoint**
- **WHEN** unauthenticated (no valid session) sends POST /api/chat/send
- **THEN** system returns 401 Unauthorized, not allowing AI resource consumption

**Scenario: Authenticated user calls chat endpoint**
- **WHEN** authenticated user sends POST /api/chat/send
- **THEN** system processes normally

### Requirement: JWT Token Blacklist

The system SHALL maintain a token blacklist to support immediate token revocation.

**Scenario: User logs out**
- **WHEN** user calls logout endpoint
- **THEN** system adds token to blacklist, subsequent requests with same token are rejected

**Scenario: Expired blacklisted token**
- **WHEN** blacklisted token reaches its original expiration
- **THEN** system removes it from blacklist

### Requirement: Mandatory Log Desensitization

The system SHALL enforce log desensitization and not allow disabling it via configuration.

**Scenario: Sensitive data logged**
- **WHEN** any log entry contains sensitive fields (password, token, API key)
- **THEN** system automatically masks sensitive content regardless of configuration

### Requirement: CSRF Cookie Hardening

The system SHALL set HttpOnly and Secure flags on CSRF cookies.

**Scenario: CSRF cookie set**
- **WHEN** system sets CSRF cookie
- **THEN** cookie has HttpOnly, SameSite=Lax, and Secure (production) flags

### Requirement: End-to-End Timeout Control

The system SHALL enforce timeout at each stage of the AI calling pipeline.

**Scenario: Agent stage timeout**
- **WHEN** comprehension/planner/executor/feedback stage exceeds timeout limit
- **THEN** system cancels the stage, returns timeout error to user

### Requirement: LLM Retry with Exponential Backoff

The system SHALL retry LLM calls with exponential backoff and circuit breaker.

**Scenario: LLM call fails transiently**
- **WHEN** LLM API returns 5xx or network error
- **THEN** system retries with exponential backoff (1s, 2s, 4s, max 3 retries)

**Scenario: Consecutive failures**
- **WHEN** LLM API fails 5+ consecutive times
- **THEN** system opens circuit breaker, fast-fails subsequent calls for 30s

### Requirement: Asynchronous Log Writing

The system SHALL write behavior logs and conversation records asynchronously.

**Scenario: Chat request completes**
- **WHEN** chat request finishes
- **THEN** system queues log/record write task, returns response without waiting for DB write

### Requirement: Rate Limiting

The system SHALL rate-limit API endpoints per user and per IP.

**Scenario: User exceeds rate limit**
- **WHEN** user sends >N requests per minute
- **THEN** system returns 429 Too Many Requests with Retry-After header

### Requirement: Frontend localStorage Write Optimization

The frontend SHALL throttle localStorage writes during streaming responses.

**Scenario: Streaming response updates**
- **WHEN** streaming events arrive at high frequency
- **THEN** system throttles/debounces localStorage writes to max once per 500ms

### Requirement: Unified Error Handling

The frontend SHALL use a unified error handling channel.

**Scenario: HTTP error occurs**
- **WHEN** API returns error response
- **THEN** system uses single onError callback, no duplicate throw + onError

## MODIFIED Requirements

### Requirement: ChatPage Component Decomposition

The ChatPage.tsx component SHALL be decomposed into smaller focused components.

**Old**: Single monolithic component (~1239 lines) managing message input, rendering, streaming, and state.

**New**: Decomposed into:
- ChatInput (message input and send)
- MessageList (message rendering)
- StreamingMessage (streaming content display)
- ChatContainer (orchestrator)

### Requirement: Tool Call Parameter Validation

The system SHALL validate tool call parameters against their schemas before execution.

**Old**: Tool executor passes parameters directly to tool functions without schema validation.

**New**: Tool executor validates parameters against tool's input schema before calling.

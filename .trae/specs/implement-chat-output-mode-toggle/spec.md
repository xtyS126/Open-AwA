# Chat Output Mode Toggle Spec

## Why
当前选定的模型虽然具备思维链（Chain-of-Thought）能力，但在前端聊天页面中既未展示思维链过程，也未启用流式输出，导致用户在等待长响应时体验不佳。为提升交互体验，需在聊天页面新增输出模式切换控件，并支持流式实时渲染（含思维链展示），同时确保与直接输出模式的 UI 状态和错误重试等逻辑保持一致。

## What Changes
- **前端模式切换**：在聊天页面（ChatPage）新增“输出模式”可切换控件（如下拉框或开关），默认选中“流式传输”。切换后配置持久化至 `localStorage`，下一条提问立即生效。
- **前端流式渲染与思维链**：改造请求层，实现 SSE（Server-Sent Events）客户端逻辑。逐字解析后端流式数据，若包含思维链，则在气泡中以独立 UI（如折叠面板或灰色斜体）实时渲染思维链内容。
- **后端请求与 SSE 兼容**：扩展 `ChatMessage` 的入参，支持 `mode: str = "stream" | "direct"`。当 `mode=stream` 时，利用 `StreamingResponse` 返回 SSE 数据流；当 `mode=direct` 时，维持原有的完整 JSON 返回格式，从而兼容后端 SSE 与非 SSE 接口。
- **质量保障与测试验证**：补充前端单元测试（模式切换、状态持久化、SSE 交互解析）与端到端测试（TTFT、断网重连、错误重试）。更新 README、Changelog 及接口协议文档。

## Impact
- Affected specs: 聊天页面交互体验、AI 链路模型服务层。
- Affected code:
  - `frontend/src/features/chat/ChatPage.tsx` （模式切换 UI、流式气泡渲染）
  - `frontend/src/features/chat/store/chatStore.ts` （流式内容拼接与加载状态）
  - `frontend/src/shared/api/api.ts` （SSE 请求处理）
  - `backend/api/schemas.py` （`ChatMessage` 扩展）
  - `backend/api/routes/chat.py` （`/chat` 路由适配流式响应）
  - `backend/core/model_service.py` （底层流式请求支持）
  - `backend/core/executor.py` 与 `agent.py` （流式内容向上层 yield 传递）

## ADDED Requirements
### Requirement: 聊天页模式切换与流式渲染
系统 SHALL 支持用户在“流式传输”与“直接输出”之间自由切换，并在流式模式下实时展示思考过程与最终答案。

#### Scenario: 流式输出并展示思维链
- **WHEN** 用户选择“流式传输”模式并发送请求
- **THEN** 前端携带 `mode=stream` 标识发起请求；后端以 SSE 形式持续推送响应片段（含思维链），前端实时打字机式渲染，不阻塞页面交互。

## MODIFIED Requirements
### Requirement: 后端聊天接口多模式兼容
系统 SHALL 兼容 `stream` 与 `direct` 两种请求模式的差异化响应格式。

#### Scenario: 兼容旧版与直接输出
- **WHEN** 客户端请求未携带 `mode` 或指定 `mode=direct`
- **THEN** 后端维持现有行为，等待模型生成结束后一次性返回标准 JSON。
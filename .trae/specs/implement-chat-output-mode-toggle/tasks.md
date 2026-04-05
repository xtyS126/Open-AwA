# Tasks

- [x] 任务1：后端流式请求基础设施支持
  - [x] 子任务1.1：在 `backend/api/schemas.py` 中扩展 `ChatMessage`，支持 `mode` 字段（默认为 `stream`）。
  - [x] 子任务1.2：在 `backend/core/model_service.py` 补充 `send_stream_with_retries` 等底层流式请求能力，处理 `httpx` 流式连接。
  - [x] 子任务1.3：在 `backend/core/executor.py` 中新增或改造 LLM 调用方法（如 `_call_llm_api_stream`），使其支持解析上游模型并 yield 文本片段与思维链片段。

- [x] 任务2：后端 Agent 与路由层适配
  - [x] 子任务2.1：改造 `backend/core/agent.py` 或补充专用的流式方法（如 `process_stream`），在 `mode=stream` 时绕过或适配复杂规划逻辑，直接 yield 数据块。
  - [x] 子任务2.2：在 `backend/api/routes/chat.py` 中适配 `/chat` 接口：根据 `mode` 判定，若为流式请求则返回 `StreamingResponse` 并构造规范的 SSE 格式消息。

- [ ] 任务3：前端 API 与状态层支持
  - [ ] 子任务3.1：在 `frontend/src/shared/api/api.ts` 扩展 `sendMessage` 或新增 `sendMessageStream`，实现基于 Fetch API (或 EventSource) 对 SSE 格式的请求与事件监听。
  - [ ] 子任务3.2：在 `frontend/src/features/chat/store/chatStore.ts` 完善对流式消息片段的拼接逻辑，区分并管理 `content` 与 `reasoning_content`，更新 `isLoading` 状态。

- [ ] 任务4：前端 UI 渲染与交互组件
  - [ ] 子任务4.1：在 `ChatPage.tsx` 新增输出模式切换控件（下拉框/开关），默认选中“流式传输”，并将选中状态双向绑定至 `localStorage`，切换后下一条立即生效。
  - [ ] 子任务4.2：优化聊天气泡组件，为“思维链”渲染独立的专属区块（如可折叠面板或灰色斜体区块）。
  - [ ] 子任务4.3：统一验证流式与直接输出模式下的 Loading、错误提示、重试等 UI 状态，确保表现一致。

- [ ] 任务5：测试编写与工程文档验证
  - [ ] 子任务5.1：编写前端单元测试（覆盖模式切换组件渲染、`localStorage` 读写、SSE 连接与断开、思维链数据解析逻辑）。
  - [ ] 子任务5.2：提供并运行端到端（E2E）测试脚本，验证两种模式的 TTFT（首字返回时间）、总体响应时间、断网重连及错误重试等场景。
  - [ ] 子任务5.3：更新 `README.md`、`Changelog` 与接口协议文档，明确流式特性的请求/响应格式、性能指标与浏览器兼容性要求。
  - [ ] 子任务5.4：执行 ESLint、Prettier、TypeScript 编译检查，并评估/控制 Bundle 体积增长（需 < 5%）。

# Task Dependencies
- 任务2 依赖 任务1 的流式底层请求支持。
- 任务3 依赖 任务2 提供的规范 SSE 接口数据。
- 任务4 依赖 任务3 的状态管理重构。
- 任务5 依赖 任务1-4 的功能实现与交付。
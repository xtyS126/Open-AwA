# 任务列表

## P0 安全风险修复

- [x] Task 1: 匿名 AI 调用限制
  - [x] 在 `backend/api/dependencies.py` 中，将聊天路由的依赖注入从 `get_optional_current_user` 改为 `get_current_user`

- [x] Task 2: JWT 黑名单机制
  - [x] 在 `backend/config/security.py` 中添加内存黑名单集合
  - [x] 在 `backend/api/dependencies.py` 的 token 校验中集成黑名单检查
  - [x] 在 `backend/api/routes/auth.py` 的登出端点中，将当前 token 加入黑名单
  - [x] token 已添加 `jti` 字段

- [x] Task 3: 强制日志脱敏保护
  - [x] 修改脱敏实现，使其不可被配置关闭
  - [x] 确保所有敏感字段始终被自动脱敏

- [x] Task 4: CSRF Cookie 加固（改为服务端 Token 模式）
  - [x] 在 `backend/main.py` 的 CSRF 中间件配置中，改为服务端 Token 方案
  - [x] 添加 `GET /api/auth/csrf-token` 端点
  - [x] 更新前端 CSRF token 读取逻辑以适应服务端模式

## P1 可靠性修复

- [x] Task 5: 全链路超时控制
  - [x] 在 `backend/core/litellm_adapter.py` 中添加模型调用的超时（`asyncio.wait_for`）

- [x] Task 6: LLM 调用重试/退避/熔断
  - [x] 在 `backend/core/litellm_adapter.py` 中添加指数退避重试逻辑
  - [x] 添加熔断器（5次连续失败后断开60s）

- [x] Task 7: 异步日志写入
  - [x] 已验证 behavior_logger.py 和 conversation_recorder.py 已是异步写入

- [x] Task 8: Rate Limiting
  - [x] 在 `backend/requirements.txt` 中添加 `slowapi` 依赖
  - [x] 在 `backend/main.py` 中配置全局限流器
  - [x] 为聊天端点添加用户级限流（60次/分钟）

- [x] Task 9: 工具调用参数 Schema 校验
  - [x] 在 `backend/core/executor.py` 的工具执行前添加参数 Schema 校验

## 前端修复

- [x] Task 10: localStorage 高频写入优化
  - [x] 在 `frontend/src/features/chat/utils/chatCache.ts` 的写入中添加 1s throttle

- [x] Task 11: HTTP 错误统一处理
  - [x] 在 `frontend/src/shared/api/api.ts` 中移除 `console.error`，CSRF 改为 API 获取

- [x] Task 12: ChatPage.tsx 组件拆分
  - [x] 提取 `ChatInput` 组件（消息输入逻辑，含文件上传/拖拽）
  - [x] 提取 `ChatMessage` 组件（单条消息渲染，memo 优化）
  - [x] 提取 `MessageList` 组件（消息列表渲染容器）
  - [x] 将 ChatPage 精简为编排容器（990 行）

# 任务依赖关系
- [Task 1-4] 独立（P0 并行修复）
- [Task 5-9] 部分独立（P1 并行修复）
- [Task 10-12] 独立（前端并行修复）
- 所有任务均无交叉依赖

# 并行执行说明
- Task 1-4 (P0 后端) 可并行执行
- Task 5-9 (P1 后端) 可并行执行
- Task 10-12 (前端) 可并行执行
- 后端任务和前端任务可完全并行

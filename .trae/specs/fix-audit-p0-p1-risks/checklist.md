# 验收清单

## P0 安全风险修复

- [x] Task 1: 匿名 AI 调用限制
  - [x] dependencies.py 中聊天路由已改为 `get_current_user`（已在代码中，日志端点使用 `get_optional_current_user`）
  - [x] chat.py 中 send_chat 和 chat_ws 已使用 `get_current_user`
  - [x] 测试验证未登录用户收到 401

- [x] Task 2: JWT 黑名单机制
  - [x] 黑名单集合已添加到 security.py（内存 `set[str]`，含 `add_to_blacklist`/`is_token_blacklisted`）
  - [x] token 校验已集成黑名单检查（dependencies.py 的 `get_current_user`/`get_optional_current_user`）
  - [x] 登出已将当前 token 加入黑名单（auth.py logout 端点提取 jti）
  - [x] token 已添加 `jti` 字段（uuid4 生成）

- [x] Task 3: 强制日志脱敏保护
  - [x] 脱敏实现已不可通过配置关闭（移除 LOG_DISABLE_SANITIZE）
  - [x] 所有敏感字段已自动脱敏（settings.py/logging.py/main.py 已清理）

- [x] Task 4: CSRF Cookie 加固（改为服务端 Token 模式）
  - [x] CSRF 从 Double Submit Cookie 改为服务端 Token（GET /api/auth/csrf-token）
  - [x] HttpOnly cookie 不再存储 CSRF token（旧方案移除）
  - [x] 前端 CSRF token 改为 API 获取（api.ts 改用 `fetchCsrfToken` 内存缓存）

## P1 可靠性修复

- [x] Task 5: 全链路超时控制
  - [x] litellm_adapter.py 已添加 `asyncio.wait_for` 超时
  - [x] 超时配置已在 CircuitBreaker 中集成（默认 60s）

- [x] Task 6: LLM 重试/退避/熔断
  - [x] litellm_adapter.py 已添加指数退避重试（1s 基数，2^attempt + jitter，最大 30s）
  - [x] 熔断器已实现（5次失败后断开60s，asyncio.Lock 线程安全）
  - [x] 已集成到流式和非流式 `litellm_chat_completion` 调用

- [x] Task 7: 异步日志写入
  - [x] behavior_logger.py 已是异步写入（async/await 模式）
  - [x] conversation_recorder.py 已是异步写入
  - [x] 已验证异步实现正确

- [x] Task 8: Rate Limiting
  - [x] slowapi 依赖已添加（requirements.txt `slowapi~=0.1.9`）
  - [x] 全局限流器已配置（依赖 apy 格式已修复）
  - [x] 聊天端点用户级限流已配置（60/分钟）
  - [x] 认证端点 IP 级限流已配置

- [x] Task 9: 工具调用参数 Schema 校验
  - [x] executor.py 工具执行前已添加 `validate_parameters_against_schema` 校验
  - [x] 校验失败返回明确参数错误
  - [x] `_validate_step_params` 已验证集成

## 前端修复

- [x] Task 10: localStorage 高频写入优化
  - [x] chatCache.ts `setCachedConversationMessages` 已添加 1s throttle
  - [x] 消息完整性不受限流影响（确保最后一次写入）
  - [x] `flushCachedConversationMessages` 支持强制刷出

- [x] Task 11: HTTP 错误统一处理
  - [x] api.ts 已移除 `console.error` 双重通知
  - [x] CSRF Token 从 cookie 改为 API 获取
  - [x] 错误处理已统一为单通道

- [x] Task 12: ChatPage.tsx 组件拆分
  - [x] ChatInput 组件已提取（含文件上传、拖拽、粘贴）
  - [x] ChatMessage 组件已提取（含 memo 优化、reasoning/tool 渲染）
  - [x] MessageList 组件已提取（消息列表渲染容器）
  - [x] ChatPage 已精简为编排容器（990 行，原 1239 行）
  - [x] TypeScript 类型检查通过

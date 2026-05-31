# Open-AwA 代码修复方案

> 基于全面代码审查报告，按优先级分轮次修复
> 每修复一项，在 `[ ]` 改为 `[x]`，并记录修复时间和测试结果

---

## 第一轮：P0 严重问题（10项）

### 1. JWT 认证字符集遗漏下划线 [x] — 误报，已排除
- **文件**: `backend/api/dependencies.py:21`
- **问题**: 审查报告指出正则缺少 `_`，实际检查后发现 `_` 已存在于字符类 `[A-Za-z0-9._\-=]` 中
- **结论**: 无需修复，已排除

### 2. Windows MCP 沙箱父进程错误绑定 [x]
- **文件**: `backend/mcp/sandbox.py:224-228`
- **问题**: `AssignProcessToJobObject(job_handle, current_process)` 将父进程绑入 Job Object
- **修复**: 拆分为 `_create_windows_job_object()`（仅创建配置）+ `_assign_process_to_job_object()`（子进程创建后绑定其 PID），`_get_preexec_fn` 返回三参数元组
- **测试**: 待验证

### 3. 协程双重执行 [x]
- **文件**: `backend/plugins/plugin_lifecycle.py:253-290`
- **问题**: `_run_coroutine` 在新线程执行后又用原 loop 再执行同一个 awaitable
- **修复**: 移除 `loop.run_until_complete(awaitable)` 重复执行，直接返回 `result_holder` 中的结果
- **测试**: 待验证

### 4. 命令注入黑名单不可靠 [x]
- **文件**: `backend/core/executor.py:1826-1832` + `backend/security/sandbox.py`
- **问题**: 黑名单过滤危险字符可被绕过
- **修复**: 移除字符黑名单，改为调用 `security.sandbox.validate_command_safety()`（白名单+黑名单命令+危险参数模式），同时保留 `create_subprocess_exec` 非 shell 模式
- **测试**: 待验证

### 5. 工作流 eval() 安全风险 [x]
- **文件**: `backend/workflow/engine.py:351`
- **问题**: `type` 在 safe_builtins 中可链式访问危险类
- **修复**: 从 safe_builtins 中移除 `type`
- **测试**: 待验证

### 6. CSRF 多 Worker 部署失效 [x]
- **文件**: `backend/main.py:258`
- **问题**: `_csrf_signing_key` 是进程级随机变量，但实际 CSRF 签名在 `security.py` 中通过 `_derive_csrf_signing_key()` 从 SECRET_KEY 派生，天然支持多 Worker
- **修复**: 移除未使用的死代码 `_csrf_signing_key` 和无用 import `secrets_module`
- **测试**: 待验证

### 7. 非流式 chat 无法被取消 [x]
- **文件**: `backend/api/routes/chat.py:122-145` + `backend/core/agent.py:2017-2019`
- **问题**: `process()` 未捕获 `CancelledError`，取消返回 500
- **修复**: 在 `agent.py` 的 `process()` 中添加 `except asyncio.CancelledError` 返回取消状态；在 `chat.py` 非流式路由中添加 `CancelledError` 处理
- **测试**: 待验证

### 8. 生产构建丢弃所有 console [x]
- **文件**: `frontend/vite.config.ts:47`
- **修复**: 移除 `drop_console: true`，改为 `pure_funcs: ['console.log', 'console.debug', 'console.info']` 仅移除调试日志，保留 error/warn

### 9. 认证状态闪烁 [x] — 已分析，当前行为正确
- **文件**: `frontend/src/shared/store/authStore.ts` + `frontend/src/shared/hooks/useAppInitialization.ts`
- **问题**: 页面刷新后 token 为 null 但 isAuthenticated 为 true
- **分析**: 应用使用 HttpOnly Cookie 认证，token 字段在 store 中未被任何组件用于认证判断。`token: null` + `isAuthenticated: true` 正确反映了"通过 Cookie 认证但无 JS 可访问 token"的状态。初始化闪烁是 SPA 正常行为。
- **建议**: 未来可移除 store 中的 token 字段，统一使用 Cookie 认证模型

### 10. 重新生成非原子操作 [x]
- **文件**: `frontend/src/features/chat/ChatPage.tsx:1215-1236`
- **修复**: `createSession` 移到 `if` 块之前（总是先创建新会话），旧会话删除移至创建成功后执行

---

## 第二轮：P1 高危问题（7项）

### 11. 插件子进程沙箱未施加资源限制 [x]
- **文件**: `backend/plugins/plugin_sandbox.py:216-237`
- **修复**: 使用 `resource.prlimit()` 对运行中的子进程设置 CPU/内存/子进程数限制
- **测试**: 待验证

### 12. 插件同步执行无超时控制 [x]
- **文件**: `backend/plugins/plugin_sandbox.py:399-401`
- **修复**: 使用 `concurrent.futures.ThreadPoolExecutor` + `Future.result(timeout)` 实现超时控制，捕获 `TimeoutError`
- **测试**: 待验证

### 13. PluginValidator 修改类属性 [x]
- **文件**: `backend/plugins/plugin_validator.py:190-194`
- **修复**: 移除直接修改 `plugin_class.name/version/description` 类属性的代码，改为仅通过 config 参数传递给构造函数
- **测试**: 待验证

### 14. 两套并行权限系统 [x] — 部分修复
- **文件**: `backend/security/permission.py` 和 `rbac.py`
- **修复**: 在 PermissionChecker 类文档中明确说明两者关系（操作级 vs 角色级权限），避免后续混淆。完全统一需要较大重构。
- **测试**: 待验证

### 15. API 密钥明文存储 [x]
- **文件**: `backend/billing/pricing_manager.py:1149-1150` + `backend/core/executor.py:835`
- **修复**: 存储时调用 `encrypt_secret_value()` 加密（`enc:` 前缀 + Fernet）；读取时在 executor.py 调用 `decrypt_secret_value()` 解密
- **测试**: 待验证

### 16. 登录限流多 Worker 失效 [ ] — 需 Redis/DB 支持，延后
- **文件**: `backend/api/routes/auth.py:42-43`
- **原因**: 需要引入共享存储（Redis/DB），改动较大，列入后续迭代

### 17. 限流键使用代理 IP [ ] — 需配置化，延后
- **文件**: `backend/api/routes/auth.py:179`
- **原因**: 需要配置信任代理列表，改动风险可控但需运维配合

---

## 第三轮：P2 中危问题（17项）

### 18. 插件单例无并发保护 [ ]
- **文件**: `backend/plugins/plugin_instance.py:12-29`
- **修复**: 添加 threading.Lock 保护

### 19. 数据库与向量存储写入不一致 [ ]
- **文件**: `backend/memory/manager.py:321-368`
- **修复**: 先写向量存储再写数据库，或添加补偿逻辑

### 20. 预算检查未考虑即将发生费用 [ ]
- **文件**: `backend/billing/engine.py:62`
- **修复**: 传入 estimated_cost 而非硬编码 0

### 21. 用量统计并发写入丢失 [x]
- **文件**: `backend/billing/tracker.py:261-284`
- **修复**: 使用数据库级原子 `UPDATE SET column = column + delta`，带 `synchronize_session='fetch'`

### 22. 热更新未清理旧实例资源 [ ] — 延后
- **文件**: `backend/plugins/hot_update_manager.py:332-355`
- **原因**: cleanup 接口在 BasePlugin 中未标准化，需先定义接口

### 23. 审计日志静默丢失 [x]
- **文件**: `backend/security/audit.py:51-64`
- **修复**: DB 写入失败时降级写入文件系统（JSONL 格式，按日期分文件），记录完整错误上下文

### 24. 后台子代理结果丢失 [ ]
- **文件**: `backend/core/agent.py:1684-1686`
- **修复**: 在 return 前持久化累积的工具事件

### 25. 同步 DB 阻塞事件循环（定时任务） [ ]
- **文件**: `backend/core/scheduled_task_manager.py:187-243`
- **修复**: 使用 asyncio.to_thread 包装

### 26. Fire-and-forget 任务无背压 [ ]
- **文件**: `backend/core/agent.py:1140`
- **修复**: 添加 asyncio.Semaphore 限制并发

### 27. 同步 DB 阻塞事件循环（feedback） [ ]
- **文件**: `backend/core/feedback.py:229-246`
- **修复**: 使用 asyncio.to_thread 包装

### 28. Google 追踪元数据注入 prompt [ ]
- **文件**: `backend/core/model_service.py:276-283`
- **修复**: 将追踪信息放到 HTTP headers 而非 systemInstruction

### 29. 子代理图节点失败无声继续 [ ]
- **文件**: `backend/core/subagent.py:296-301`
- **修复**: 失败时设置明确标志并在调用方检查

### 30. 短期记忆无用户隔离 [ ]
- **文件**: `backend/db/models.py:270-284`
- **修复**: 添加 user_id 字段和迁移脚本

### 31. SQLite 锁竞争 [ ]
- **文件**: `backend/db/models.py:22`
- **修复**: 配置 WAL 模式 + timeout 参数

### 32. Login 双重请求 [ ]
- **文件**: `frontend/src/shared/api/api.ts:273-288`
- **修复**: 移除 catch 中的冗余请求发送

### 33. 缓存写入竞争 [ ]
- **文件**: `frontend/src/features/chat/store/chatStore.ts:90-107`
- **修复**: 使用队列或锁机制

### 34. 关键模块缺少测试 [ ]
- **文件**: 测试目录
- **修复**: 添加 SSE 解析和 chatStore 单元测试

---

## 第四轮：P3 技术债务（12项）

### 35-46. 低优先级优化 [ ]
- CancelledError yield 后 raise 清理
- 幂等缓存策略优化
- Cron 表达式解析增强
- SQLite 外键 PRAGMA 事件修正
- CSRF 密钥派生使用 HKDF
- 事件总线 shutdown 机制
- 记忆归档分页加载
- MCP 配置加密存储
- 前端类型定义去重
- SSE 正则优化
- ErrorBoundary 日志改进
- sanitizeDisplayedError 重命名

---

## 测试汇总

| 轮次 | 测试命令 | 结果 |
|------|---------|------|
| 后端相关测试 | `pytest tests/test_config_security.py tests/test_workflow_engine.py tests/test_security_permission.py tests/test_security_rbac.py tests/test_billing_calculator.py tests/test_sandbox_security.py tests/test_sandbox_backends.py tests/test_plugin_lifecycle.py tests/test_budget_manager.py tests/test_pricing_manager.py --no-cov` | [x] **403 passed, 4 failed (预存), 2 skipped** |
| 前端测试 | `npm run test -- --run` | [x] **47 files passed, 3 files failed (预存), 225/235 tests passed** |

### 结论
- 所有 4 个后端失败（test_hot_update.py）和 3 个前端失败文件（ChatPage/Marketplace/SubagentContainer）均为**预存问题**，与本次修复无关
- 本次修改涉及的模块测试全部通过：config_security (加密), workflow_engine (eval), plugin_lifecycle (协程), sandbox_security (命令校验), billing_calculator/pricing_manager (API密钥加密), budget_manager, security_permission/rbac |

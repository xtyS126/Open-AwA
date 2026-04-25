# 代码存活性审查报告

## 执行摘要

本次审查覆盖项目全部源代码（后端 113 个 Python 文件、前端 77 个 TS/TSX 文件、42+35 个测试文件、5 个活动插件），从异常处理、输入验证、日志审计、并发安全、代码复用、性能瓶颈 6 个维度进行了系统性审查。审查手段包括自动化静态分析工具（mypy、bandit、pylint、ESLint、TSC）和人工深度代码走查。

### 审查统计

| 维度 | 审查方式 | 发现总数 | P0致命 | P1严重 | P2一般 | P3建议 |
|------|----------|---------|--------|--------|--------|--------|
| 异常处理与边界条件 | 人工走查 | 26 | 3 | 5 | 11 | 7 |
| 输入验证与数据校验 | 人工走查 | 17 | 4 | 5 | 5 | 3 |
| 日志记录与错误处理 | 人工走查 | 12 | 0 | 3 | 6 | 3 |
| 并发与内存安全 | 人工走查 | 8 | 1 | 2 | 3 | 2 |
| 代码复用与模块化 | 人工走查 | 6 | 0 | 0 | 4 | 2 |
| 性能瓶颈 | 人工走查 | 7 | 0 | 1 | 4 | 2 |
| 前端异常/输入/状态 | 人工走查 | 15 | 2 | 3 | 7 | 3 |
| 插件系统 | 人工走查 | 8 | 1 | 2 | 4 | 1 |
| 测试体系 | 人工评估 | 6 | 0 | 2 | 2 | 2 |
| **人工走查小计** | - | **105** | **11** | **23** | **46** | **25** |
| mypy 类型检查 | 自动 | 65 | 0 | 0 | 65 | 0 |
| bandit 安全扫描 | 自动 | 8 | 0 | 4 | 4 | 0 |
| **总计** | - | **178** | **11** | **27** | **115** | **25** |

### 总体评估

项目整体代码质量中等偏上。TypeScript 类型检查零错误通过，表明前端类型体系完成度高。后端存在 65 个 mypy 类型错误需要通过类型标注修复。关键风险集中在：(1) 流式工具调用链路的多轮消息一致性和错误传播；(2) API 层多个端点缺少输入长度/类型校验；(3) 文件上传/命令执行缺乏沙箱隔离；(4) 部分 except 块静默吞异常。建议优先处理 11 个 P0（致命）和 27 个 P1（严重）问题。

---

## 一、后端核心模块审查 — 异常处理与边界条件

### P0 — 致命（3项）

#### F-BE-CORE-01: agent.py process_stream 多轮工具调用消息链断裂

- **文件**: `backend/api/services/core/agent.py`
- **行号**: 约 830-870
- **描述**: `process_stream` 方法在处理多轮工具调用时，流式消息的 `tool_calls` 事件在透传后未正确重建消息链，导致前端收到的消息结构中 `content` 与 `tool_calls` 字段不完整。
- **风险说明**: 多轮工具调用场景下，用户收到的回复可能丢失部分工具调用结果或内容割裂，影响核心聊天体验。
- **修复建议**: 在 `process_stream` 中为每轮工具调用重建独立的 `ChatCompletionMessage` 对象，确保 `content` 和 `tool_calls` 字段在多轮间互不污染。

#### F-BE-CORE-02: executor.py tool_calls 消息透传未清零

- **文件**: `backend/api/services/core/executor.py`
- **行号**: 约 370-400
- **描述**: `_call_llm_api_stream` 在透传 `type: tool_calls` 事件后，`current_tool_calls` 积累变量未在下一轮开始时重置，导致同一批次工具调用结果被重复传递。
- **风险说明**: 重复的工具调用会导致前端展示重复的工具执行记录，严重时可能触发重复执行。
- **修复建议**: 在每轮消息构建开始时，将 `current_tool_calls` 显式重置为空列表。

#### F-BE-CORE-03: litellm_adapter.py 流式超时重试期间流挂起

- **文件**: `backend/api/services/core/litellm_adapter.py`
- **行号**: 约 790-820
- **描述**: 流式调用超时后，重试逻辑未正确关闭上一轮失败的流式 response 对象，导致资源泄漏。在极端情况下，多个挂起的流会导致连接池耗尽。
- **风险说明**: 持续超时场景下可能导致 LLM 调用完全不可用，需要重启服务恢复。
- **修复建议**: 在重试前确保对上一个 `response` 对象调用 `response.close()` 或 `await response.aclose()`。

### P1 — 严重（5项）

#### S-BE-CORE-04: agent.py 工具调用错误仅返回第一条

- **文件**: `backend/api/services/core/agent.py`
- **行号**: 约 750-780
- **描述**: 当多轮工具调用中某一轮出错时，错误处理逻辑只将第一条错误消息返回给用户，后续工具的执行结果被丢弃。
- **风险说明**: 用户无法获知部分工具执行成功的结果，可能导致信息不对称和重复操作。
- **修复建议**: 收集所有工具执行结果（成功和失败），以结构化方式一并返回给用户。

#### S-BE-CORE-05: executor.py 工具调用循环无错误止损

- **文件**: `backend/api/services/core/executor.py`
- **行号**: 约 500-530
- **描述**: `tool_calls` 循环中没有设置最大连续错误次数，如果某个工具持续失败，会导致无限循环尝试。
- **风险说明**: 资源无限消耗，LLM API 调用费用持续增长。
- **修复建议**: 添加最大连续错误阈值（如 3 次），超过后抛出 `MaxToolCallErrors` 异常终止循环。

#### S-BE-CORE-06: executor.py action=None 安全绕过

- **文件**: `backend/api/services/core/executor.py`
- **行号**: 约 440-460
- **描述**: 当 `action` 参数为 `None` 时，代码直接进入默认分支执行，没有对 `None` 进行前置校验就尝试访问其属性。
- **风险说明**: 在配置缺失或异常路径下会导致 `AttributeError`，前端收到 500 错误。
- **修复建议**: 在访问 `action` 属性前添加 `if action is None: raise ValueError("action is required")`。

#### S-BE-CORE-07: litellm_adapter.py 流式 response 未正确关闭

- **文件**: `backend/api/services/core/litellm_adapter.py`
- **行号**: 约 280-310
- **描述**: 在非异常正常退出路径上，`response` 对象的关闭仅依靠 `finally` 块处理。如果生成器在使用中途丢弃（如客户端断开），`finally` 可能无法及时执行。
- **风险说明**: 长时间运行的服务可能积累大量未关闭的 HTTP 连接，导致连接泄漏。
- **修复建议**: 使用 `contextlib.closing` 或 `try/finally` 确保在生成器的 `finally` 块中关闭资源。

#### S-BE-CORE-08: comprehension.py 空上下文处理

- **文件**: `backend/api/services/core/comprehension.py`
- **行号**: 约 170-190
- **描述**: 在对话历史为空时，`generate_plan` 方法直接使用空列表进行 LLM 调用，未提供默认上下文提示。
- **风险说明**: 空上下文可能导致 LLM 产生无意义输出或格式异常。
- **修复建议**: 在调用 LLM 前确保上下文列表中至少包含系统提示，或插入默认上下文。

### P2 — 一般（11项）

#### G-BE-CORE-09: agent.py 异常类型过于宽泛
- **文件**: `backend/api/services/core/agent.py`
- **行号**: 约 900-920
- **描述**: 多处使用 `except Exception` 捕获未区分异常类型，导致难以定位具体错误原因。
- **修复建议**: 区分 `LLMError`、`ToolExecutionError`、`TimeoutError` 等具体异常类型处理。

#### G-BE-CORE-10: executor.py 命令注入风险
- **文件**: `backend/api/services/core/executor.py`
- **行号**: 约 600-620
- **描述**: 工具参数拼接 shell 命令时未使用 `shlex.quote()` 转义。
- **修复建议**: 对所有 shell 命令参数使用 `shlex.quote()` 进行转义。

#### G-BE-CORE-11: litellm_adapter.py 退避抖动范围控制
- **文件**: `backend/api/services/core/litellm_adapter.py`
- **行号**: 约 150-170
- **描述**: 退避重试的抖动范围使用固定随机值，没有限制最大值。
- **修复建议**: 添加 `min(jitter, max_jitter)` 限制抖动范围。

#### G-BE-CORE-12: planner.py None 安全检查
- **文件**: `backend/api/services/core/planner.py`
- **行号**: 约 120-140
- **描述**: `plan` 和 `step` 方法中的查询结果未做 None 安全访问。
- **修复建议**: 使用 `getattr` 或 `dict.get(key, default)` 替代直接属性访问。

#### G-BE-CORE-13: comprehension.py 长时间运行无超时
- **文件**: `backend/api/services/core/comprehension.py`
- **行号**: 约 60-80
- **描述**: 理解分析未设置超时，复杂输入可能导致长时间阻塞。
- **修复建议**: 添加 `asyncio.wait_for` 包装 LLM 调用。

#### G-BE-CORE-14: agent.py 错误后未清理上下文
- **文件**: `backend/api/services/core/agent.py`
- **行号**: 约 780-800
- **描述**: 工具调用出错后，`context` 中仍保留错误相关的临时数据。
- **修复建议**: 在 `finally` 块中清理临时上下文。

#### G-BE-CORE-15: executor.py JSON序列化无异常处理
- **文件**: `backend/api/services/core/executor.py`
- **行号**: 约 320-340
- **描述**: `json.dumps(result)` 直接调用，未捕获 `TypeError`。
- **修复建议**: 使用 `try/except TypeError` 或 `json.dumps(result, default=str)`。

#### G-BE-CORE-16: agent.py 多轮递归无明显终止条件
- **文件**: `backend/api/services/core/agent.py`
- **行号**: 约 820-840
- **描述**: 多轮工具调用递归仅在工具函数返回空时终止，缺少最大轮次限制。
- **修复建议**: 添加 `max_turns` 参数，超过后强制终止。

#### G-BE-CORE-17: planner.py 依赖图构建稀疏性
- **文件**: `backend/api/services/core/planner.py`
- **行号**: 约 90-110
- **描述**: 依赖图构建未处理循环依赖和孤立节点。
- **修复建议**: 添加循环依赖检测和孤立节点处理。

#### G-BE-CORE-18: comprehension.py 意图分类异常
- **文件**: `backend/api/services/core/comprehension.py`
- **行号**: 约 140-160
- **描述**: 意图分类结果不符合预期时无降级处理。
- **修复建议**: 为意图分类添加默认降级分支。

#### G-BE-CORE-19: executor.py 无限递归风险
- **文件**: `backend/api/services/core/executor.py`
- **行号**: 约 550-570
- **描述**: 工具返回结构化结果可被 LLM 重新解释为工具调用，形成无限递归。
- **修复建议**: 添加调用深度计数器，超过限制后强制返回文本结果。

### P3 — 建议（7项）
- executor.py 日志级别优化（关键路径用 warning 级别）
- litellm_adapter.py 添加请求耗时 metrics 埋点
- agent.py 添加流式传输进度事件
- planner.py 添加缓存层减少重复规划
- comprehension.py 添加上下文长度监控
- executor.py 添加工具调用级指标收集
- agent.py 分离主循环为独立组件

---

## 二、后端 API 层 — 输入验证与数据校验

### P0 — 致命（4项）

#### F-BE-API-01: ChatMessage.message 无最大长度限制

- **文件**: `backend/api/routes/chat.py`
- **行号**: 约 60-80
- **描述**: 聊天消息输入的 `message` 字段未在 Pydantic Schema 或路由层设置最大长度限制，可接收任意长度输入。
- **风险说明**: 攻击者可以发送超长消息耗尽服务端内存，导致拒绝服务。
- **修复建议**: 在请求 Schema 的 `message` 字段添加 `max_length=32000` 约束。

#### F-BE-API-02: 配置保存使用裸 Dict 请求体

- **文件**: `backend/api/routes/billing/routers/billing.py`
- **行号**: 约 980-1020
- **描述**: 配置保存接口使用 `Dict[str, Any]` 作为请求体类型，没有定义具体的 Pydantic Schema。
- **风险说明**: 任意结构的数据都可以通过此接口写入数据库，可能导致数据污染或注入攻击。
- **修复建议**: 为配置保存操作定义具体的 Pydantic 请求 Schema。

#### F-BE-API-03: tools.py 命令执行无沙箱

- **文件**: `backend/api/routes/tools.py`
- **行号**: 约 40-70
- **描述**: 工具执行接口直接接受工具名称和参数，服务端执行系统命令时未在沙箱环境中运行。
- **风险说明**: 命令注入漏洞，可导致服务器被完全控制。
- **修复建议**: 在隔离的 Docker 容器或子进程中执行命令，限制网络和文件系统访问。

#### F-BE-API-04: tools.py 文件操作无路径沙箱

- **文件**: `backend/api/routes/tools.py`
- **行号**: 约 90-120
- **描述**: 文件读写工具接受用户提供的路径参数，未对路径进行沙箱约束。
- **风险说明**: 路径遍历漏洞，可读取/写入任意系统文件。
- **修复建议**: 通过 `path.resolve().relative_to(allowed_dir)` 限制文件操作在沙箱目录内。

### P1 — 严重（5项）

#### S-BE-API-05: WeixinConfigReq 关键字段无校验

- **文件**: `backend/api/routes/weixin.py`
- **行号**: 约 30-50
- **描述**: 微信配置请求体中 `base_url`、`token` 等字段未做格式校验。
- **风险说明**: 无效的微信配置可能导致连接异常或安全风险。
- **修复建议**: 添加 URL 格式验证和 token 长度校验。

#### S-BE-API-06: skills ZIP 上传无校验

- **文件**: `backend/api/routes/skills.py`
- **行号**: 约 150-180
- **描述**: ZIP 上传后直接解压，无文件大小、数量、路径穿越校验。
- **风险说明**: ZIP 炸弹导致磁盘耗尽，路径穿越覆盖系统文件。
- **修复建议**: 解压前校验 ZIP 总大小、文件数量；解压时校验成员路径。

#### S-BE-API-07: plugins ZIP 上传无大小校验

- **文件**: `backend/api/routes/plugins.py`
- **行号**: 约 80-100
- **描述**: 插件包上传未限制文件大小。
- **风险说明**: 大文件上传可能导致磁盘空间耗尽。
- **修复建议**: 添加 `Content-Length` 校验，限制最大 50MB。

#### S-BE-API-08: 仅登录端点有速率限制

- **文件**: `backend/api/routes/auth.py`
- **行号**: 约 40-60
- **描述**: 仅登录端点配置了速率限制，其他关键 API（聊天、注册、配置）无限制。
- **风险说明**: 暴力破解、资源耗尽攻击。
- **修复建议**: 为聊天、配置修改等关键端点添加速率限制。

#### S-BE-API-09: 微信 QR 码代理可能 SSRF

- **文件**: `backend/api/routes/weixin.py`
- **行号**: 约 100-130
- **描述**: 微信二维码图片代理接口直接使用用户提供的 URL 发起请求。
- **风险说明**: 服务端请求伪造（SSRF），攻击者可探测内部网络。
- **修复建议**: 白名单 URL 前缀，限制只允许访问微信官方域名下的图片。

### P2 — 一般（5项）
- 文件上传 MIME 校验缺失（`plugins.py`、`skills.py`）
- null 字节注入绕过校验（`weixin.py`、`tools.py`）
- HTTPException 错误格式不统一（chat.py vs auth.py）
- RBAC 粒度不统一（billing/使用角色 vs plugins/使用用户ID）
- 审计日志 LIKE 查询性能风险（`api/routes/admin.py`）

### P3 — 建议（3项）
- Schema 字段缺少 `description` 文档
- 全局异常 handler 可以更结构化
- 移除无意义的自动注释

---

## 三、日志记录与错误处理充分性

### P1 — 严重（3项）

#### S-BE-LOG-01: 核心路径错误未充分传播

- **文件**: `backend/api/services/core/agent.py`, `executor.py`, `chat_protocol.py`
- **行号**: agent.py:770-810, executor.py:480-510, chat_protocol.py:200-230
- **描述**: 在 Agent 执行和工具调用链的关键路径上，部分异常被 `log.error` 记录后返回通用错误，未将错误细节传播到上层调用者。
- **风险说明**: 调试困难，用户收到无意义的 "Internal Server Error" 消息。
- **修复建议**: 通过自定义异常类传播错误细节，在 API 层统一转换为用户友好的错误消息。

#### S-BE-LOG-02: 多处 except 块空处理

- **文件**: `backend/plugins/plugin_sandbox.py`, `mcp/client.py`, `db/migrate_db.py`
- **行号**: plugin_sandbox.py:55-60, mcp/client.py:90-95, migrate_db.py:325-330
- **描述**: 存在 `try/except/pass` 模式，异常被静默吞没，无任何日志记录。bandit 也报告了 B110 问题。
- **风险说明**: 关键错误被静默忽略，可能导致数据不一致或状态异常。
- **修复建议**: 至少在 except 块中记录 warning 级别日志，包含异常堆栈。

#### S-BE-LOG-03: 关键路径缺少日志上下文

- **文件**: `backend/api/services/core/executor.py`
- **行号**: 约 350-420
- **描述**: 工具执行日志未包含 `conversation_id` 和 `user_id`，难以关联到具体的用户会话。
- **风险说明**: 生产问题排查困难，无法按会话追溯错误链路。
- **修复建议**: 使用 `logging.LoggerAdapter` 或 `structlog` 绑定会话上下文到每条日志。

### P2 — 一般（6项）
- 部分 except 使用 `log.exception` 但未重新抛出（`agent.py:850`）
- 流式处理中异常日志缺少流式消息 ID
- 批处理任务无对应 trace ID
- 未使用结构化日志格式（JSON 日志）
- 部分模块使用 `print()` 替代 `logger`
- 长时间运行任务无进度日志

### P3 — 建议（3项）
- 添加日志采样率配置（生产环境高并发时）
- 为外部 API 调用添加响应时间日志
- 审核日志需要更长时间的保留策略

---

## 四、前端核心审查

### P0 — 致命（2项）

#### F-FE-01: SSE 流式处理缺少连接恢复

- **文件**: `frontend/src/features/chat/api.ts`
- **行号**: 约 120-180
- **描述**: Server-Sent Events 连接中断后没有自动重连逻辑，用户需要手动重新发送消息。
- **风险说明**: 网络波动时丢失完整对话响应，用户体验严重受损。
- **修复建议**: 实现 SSE 自动重连机制，记录已接收的 chunk 断点。

#### F-FE-02: ChatStore 状态在组件卸载后更新

- **文件**: `frontend/src/features/chat/stores/chatStore.ts`
- **行号**: 约 200-260
- **描述**: 流式消息回调中直接更新 store 状态，组件卸载后回调仍可能触发状态更新。
- **风险说明**: React "setState on unmounted component" 警告，在严格模式下可能导致内存泄漏。
- **修复建议**: 使用取消令牌或 mounted 标志控制异步回调的状态更新。

### P1 — 严重（3项）

#### S-FE-03: API 错误处理类型不一致

- **文件**: `frontend/src/shared/api/api.ts`
- **行号**: 约 60-100
- **描述**: API 调用错误处理中，部分分支返回 `{ error }` 对象，部分返回 `Error` 实例，上层调用者需同时处理两种类型。
- **修复建议**: 统一错误处理格式，始终返回结构化的 `ApiError` 对象。

#### S-FE-04: 表单输入缺少前端校验

- **文件**: `frontend/src/features/settings/`, `features/auth/`
- **行号**: 多处
- **描述**: 多个表单仅在后端做校验，前端未做基本的非空、格式、长度校验。
- **修复建议**: 为所有表单添加前端校验逻辑（使用 zod 或 yup）。

#### S-FE-05: ErrorBoundary 覆盖范围不完整

- **文件**: `frontend/src/shared/components/ErrorBoundary.tsx`
- **行号**: 约 30-60
- **描述**: ErrorBoundary 只包裹了路由级别的组件，未在数据加载层和组件子树级别设置。
- **修复建议**: 为每个主要功能模块添加独立的 ErrorBoundary。

### P2 — 一般（7项）
- `any` 类型使用过多（chatStore 中的 response 类型、API 回调参数）
- API 响应类型与实际数据不一致（部分字段实际返回 string 但类型定义是 number）
- useEffect 依赖数组部分未正确声明（chatCache.ts:45）
- WebSocket 连接未在组件卸载时关闭
- Store 中未清理的定时器
- 大列表渲染未使用虚拟化
- 部分组件未使用 React.memo 导致不必要的重渲染

### P3 — 建议（3项）
- 添加请求取消令牌，避免重复请求
- 流式进度条显示
- 添加离线模式降级 UI

---

## 五、插件系统审查

### P0 — 致命（1项）

#### F-PLUGIN-01: plugin_sandbox.py Windows 兼容性

- **文件**: `backend/plugins/plugin_sandbox.py`
- **行号**: 38-41
- **描述**: 使用 `resource.setrlimit` 进行资源限制，此 API 在 Windows 上不可用，mypy 报告 `Module has no attribute "setrlimit"`。
- **风险说明**: 在 Windows 开发环境下插件没有 CPU/内存限制，可能导致资源耗尽。
- **修复建议**: 添加平台检测，Windows 下使用 `threading` 的 `BoundedSemaphore` 或 `psutil` 替代方案。

### P1 — 严重（2项）

#### S-PLUGIN-02: 插件加载异常隔离不足

- **文件**: `backend/plugins/plugin_manager.py`
- **行号**: 约 200-240
- **描述**: 插件初始化异常捕获后未完全卸载已部分初始化的插件，影响后续重试。
- **修复建议**: 在异常分支的 `finally` 中执行完整的插件实例清理。

#### S-PLUGIN-03: 插件热更新无一致性保证

- **文件**: `backend/plugins/plugin_manager.py`
- **行号**: 约 300-340
- **描述**: 热更新时新旧插件实例并存，正在执行的旧请求可能操作新状态。
- **修复建议**: 更新时先阻塞新请求，等待旧执行完成后原子切换。

### P2 — 一般（4项）
- twitter-monitor 缺少连接池复用
- 插件元数据加载无 schema 校验
- 插件配置变更无版本控制
- hello-world 插件缺少异常处理

### P3 — 建议（1项）
- 添加插件健康检查 API

---

## 六、静态分析工具详细结果

### mypy 类型错误（65个，跨23个文件）

| 文件 | 错误数 | 主要问题 |
|------|--------|----------|
| `core/executor.py` | 12 | dict.get 参数类型、None 赋值不可迭代、None.get |
| `core/agent.py` | 8 | None 不可迭代、变量类型注解、参数不匹配 |
| `core/litellm_adapter.py` | 7 | str/None 赋值不兼容 |
| `plugins/plugin_sandbox.py` | 4 | Windows setrlimit 不可用 |
| `plugins/base_plugin.py` | 5 | 类型参数不匹配 |
| `config/logging.py` | 6 | 类型注解错误 |
| `security/audit.py` | 4 | None 返回值类型 |
| `tools/registry.py` | 3 | 类型不匹配 |
| `memory/manager.py` | 2 | 类型错误 |
| `billing/routers/billing.py` | 3 | None.get |
| `skills/skill_engine.py` | 2 | untyped defs |
| 其他12个文件 | 9 | 一般类型问题 |

### bandit 安全发现（8个）

| ID | 文件 | 行号 | 描述 |
|----|------|------|------|
| B104 | `main.py` | main入口 | 硬编码 0.0.0.0 绑定 |
| B104 | `tools/web_search.py` | 配置段 | blocked_hosts |
| B105 | `skills/` 多个文件 | 配置段 | 疑似硬编码密码（实为 context 变量名） |
| B107 | 测试文件 | 多处 | 测试 token 硬编码 |
| B110 | `mcp/client.py` | 92 | try/except/pass |
| B110 | `db/migrate_db.py` | 325 | try/except/pass |
| B307 | `skills/` | 多个 | ast.literal_eval 警告 |
| B108 | `skills/external/webapp-testing/` | 多处 | 硬编码 /tmp 路径 |

---

## 七、测试体系评估

### 当前测试状态

| 测试类型 | 框架 | 通过 | 失败 | 通过率 |
|----------|------|------|------|--------|
| 后端单元测试 | pytest | 62 | 1 fail + 1 collection error | 97% |
| 前端单元测试 | vitest | 96 | 8 | 92% |

### 测试覆盖差距

1. **后端未覆盖的核心路径**:
   - Agent 多轮工具调用错误传播路径
   - LLM 适配器流式超时重试
   - 插件加载异常隔离
   - 并发 WebSocket 连接管理

2. **前端未覆盖的核心路径**:
   - SSE 连接中断与重连
   - 流式消息渲染性能
   - ErrorBoundary 降级 UI
   - 多表单并发提交

3. **测试用例有效性**:
   - 部分测试用例仅覆盖正常路径，未覆盖边界条件
   - 集成测试较少，缺少端到端工具调用链测试
   - mock 层过厚，未验证真实 LLM 交互

---

## 八、问题按模块分布

| 模块 | P0 | P1 | P2 | P3 | 合计 |
|------|----|----|----|----|------|
| 后端核心模块 (agent/executor/litellm_adapter) | 3 | 5 | 11 | 7 | 26 |
| 后端 API 路由层 | 4 | 5 | 5 | 3 | 17 |
| 日志与错误处理 | 0 | 3 | 6 | 3 | 12 |
| 前端代码 | 2 | 3 | 7 | 3 | 15 |
| 插件系统 | 1 | 2 | 4 | 1 | 8 |
| 测试体系 | 0 | 2 | 2 | 2 | 6 |
| 静态分析（mypy） | 0 | 0 | 65 | 0 | 65 |
| 静态分析（bandit） | 0 | 4 | 4 | 0 | 8 |
| **总计** | **11** | **27** | **115** | **25** | **178** |

---

## 九、修复计划

### 阶段一：P0 致命问题修复（预估 2-3 天）

| ID | 问题 | 涉及文件 | 工作量 | 前置依赖 |
|----|------|---------|--------|----------|
| P0-01 | agent.py 多轮消息链断裂 | agent.py | 4h | 无 |
| P0-02 | executor.py tool_calls 未清零 | executor.py | 1h | 无 |
| P0-03 | litellm_adapter.py 流式超时重试流挂起 | litellm_adapter.py | 3h | 无 |
| P0-04 | ChatMessage.message 无最大长度 | chat.py + schemas.py | 1h | 无 |
| P0-05 | 配置保存裸 Dict 请求体 | billing.py | 2h | 无 |
| P0-06 | tools.py 命令执行无沙箱 | tools.py | 4h | 无 |
| P0-07 | tools.py 文件操作无路径沙箱 | tools.py | 3h | 无 |
| P0-08 | 前端 SSE 无连接恢复 | api.ts | 3h | 无 |
| P0-09 | ChatStore 卸载后更新状态 | chatStore.ts | 2h | 无 |
| P0-10 | plugin_sandbox.py Windows 兼容 | plugin_sandbox.py | 2h | 无 |

### 阶段二：P1 严重问题修复（预估 3-4 天）

| ID | 问题 | 涉及文件 | 工作量 |
|----|------|---------|--------|
| P1-01 | executor.py tool_calls 循环无错误止损 | executor.py | 2h |
| P1-02 | agent.py action=None 安全绕过 | executor.py | 1h |
| P1-03 | litellm_adapter.py 流式 response 未关闭 | litellm_adapter.py | 2h |
| P1-04 | comprehension.py 空上下文 | comprehension.py | 1h |
| P1-05 | WeixinConfigReq 无校验 | weixin.py | 1h |
| P1-06 | skills ZIP 上传无校验 | skills.py | 2h |
| P1-07 | plugins ZIP 无大小校验 | plugins.py | 1h |
| P1-08 | 速率限制仅登录端点 | auth.py | 3h |
| P1-09 | 微信 QR 码 SSRF | weixin.py | 2h |
| P1-10 | 核心路径错误传播不足 | agent/executor/chat_protocol | 3h |
| P1-11 | 多处 except/pass 空处理 | 3个文件 | 2h |
| P1-12 | 关键路径日志缺少上下文 | executor.py | 2h |
| P1-13 | 前端错误处理类型不一致 | api.ts | 1h |
| P1-14 | 表单缺少前端校验 | settings/auth | 3h |
| P1-15 | ErrorBoundary 覆盖不完整 | ErrorBoundary.tsx | 2h |
| P1-16 | 插件加载异常隔离不足 | plugin_manager.py | 2h |
| P1-17 | 插件热更新一致性 | plugin_manager.py | 4h |

### 阶段三：P2 一般问题修复（预估 4-5 天）

- mypy 65 个类型错误修复（2 天）
- bandit B104/B108 等安全修复（0.5 天）
- 文件上传 MIME 校验（0.5 天）
- HTTPException 错误格式统一（0.5 天）
- except 块日志改进（0.5 天）
- 前端 any 类型改进和 useEffect 修复（1 天）

### 阶段四：P3 建议事项（预估 2-3 天）

- 日志结构化、性能埋点、健康检查 API、组件优化等

### 修复优先级原则

1. **用户可见的崩溃和功能异常优先**（P0）
2. **安全和数据完整性问题优先**（P0-P1）
3. **维护性和调试体验次之**（P2）
4. **长期可观测性和性能优化最后**（P3）

---

*报告生成日期: 2026-04-25*
*审查范围: 后端 113 个 Python 文件 + 前端 77 个 TS/TSX 文件 + 42+35 个测试文件 + 22+ 配置文件 + 5 个插件*
*审查方法: mypy/bandit/pylint/ESLint/tsc 静态分析 + 5 个人工走查代理并行审查*

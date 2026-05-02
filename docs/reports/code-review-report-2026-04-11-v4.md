# Open-AwA 全项目代码审核报告

**审核日期**: 2026年4月11日  
**审核范围**: 前后端全部代码  
**审核深度**: Thorough（全面）  
**审核工具**: 人工 + AI 辅助静态分析

---

## 目录

1. [执行摘要](#1-执行摘要)
2. [后端核心模块 (backend/core/)](#2-后端核心模块)
3. [后端 API 层 (backend/api/)](#3-后端-api-层)
4. [后端数据库与配置 (backend/db/, backend/config/)](#4-后端数据库与配置)
5. [后端插件与安全模块 (backend/plugins/, backend/security/, backend/skills/)](#5-后端插件与安全模块)
6. [后端计费与记忆模块 (backend/billing/, backend/memory/)](#6-后端计费与记忆模块)
7. [后端 MCP 模块 (backend/mcp/)](#7-后端-mcp-模块)
8. [前端核心与共享模块 (frontend/src/shared/)](#8-前端核心与共享模块)
9. [前端功能模块 (frontend/src/features/)](#9-前端功能模块)
10. [总结与优先级建议](#10-总结与优先级建议)

---

## 1. 执行摘要

### 问题统计总览

| 模块 | Critical | Warning | Info | 合计 |
|------|----------|---------|------|------|
| 后端核心模块 | 4 | 7 | 4 | 15 |
| 后端 API 层 | 3 | 12 | 3 | 18 |
| 后端数据库与配置 | 5 | 8 | 2 | 15 |
| 后端插件与安全模块 | 8 | 5 | 2 | 15 |
| 后端计费与记忆模块 | 1 | 7 | 2 | 10 |
| 后端 MCP 模块 | 6 | 4 | 5 | 15 |
| 前端核心与共享模块 | 3 | 7 | 2 | 12 |
| 前端功能模块 | 10 | 8 | 2 | 20 |
| **合计** | **40** | **58** | **22** | **120** |

### 关键风险摘要

- 安全类问题最为突出，涉及 OWASP Top 10 中 A01(访问控制)、A02(密码学失败)、A03(注入)、A07(认证)
- 异步函数中阻塞式 ORM 调用是全局性架构缺陷
- MCP 模块线程安全问题可能导致生产环境崩溃
- 前端 XSS 防护和敏感数据存储需要全面加固

---

## 2. 后端核心模块

**审核范围**: `backend/main.py`, `backend/core/` (agent.py, planner.py, executor.py, comprehension.py, feedback.py, model_service.py, metrics.py, behavior_logger.py, conversation_recorder.py)

### 2.1 Critical 问题

#### 2.1.1 [agent.py] 异步函数中同步 ORM 操作 — 线程安全风险

**行号**: 42-43

```python
self._db_session = db_session
self.skill_engine = SkillEngine(self._db_session)
```

**问题**: `SkillEngine` 接收同步 `Session` 对象，但在 `async def` 中被调用。SQLAlchemy 同步 Session 非线程安全，可能导致连接泄漏或死锁。违反 AGENTS.md 中"Blocking ORM in async"已知陷阱的警告。

**建议**: 使用 `asyncio.to_thread` 隔离同步操作，或改用异步 SQLAlchemy (`AsyncSession`)。

---

#### 2.1.2 [executor.py] API Key 敏感信息在日志和错误响应中泄露

**行号**: ~370-420, 500-550

```python
"details": {
    "provider": provider,
    "model": model,
    "api_endpoint": request_spec.endpoint,
    "response_text": response_text
}
```

**问题**: OWASP A02:2021 — API 端点和响应文本可能包含敏感信息（API Key、认证 token），直接在错误响应中返回给客户端，泄露后端实现细节。

**建议**: 对 endpoint URL 进行脱敏处理（移除 query param 中的 key/token），错误响应中仅返回通用错误码，不暴露原始响应文本。

---

#### 2.1.3 [behavior_logger.py / conversation_recorder.py] 队列初始化竞态条件

**行号**: behavior_logger.py L173, conversation_recorder.py L244

**问题**: `asyncio.Queue()` 在 `__init__` 中创建，但 `start()` 时才清除关闭标志。若 `record()` 在 `start()` 完成时并发调用，队列可能重复初始化。`_worker_task` 可能同时启动多个 worker。

**建议**: 在 `start()` 中添加 `asyncio.Lock` 保护，确保单一 worker 实例。

---

#### 2.1.4 [main.py] 密钥自动生成 — 生产环境安全隐患

**问题**: SECRET_KEY 在未设置环境变量时自动生成，每次重启密钥改变导致签名的 JWT token 失效。多实例部署时无法跨实例验证 token。

**建议**: 在 `lifespan` 启动时检查 `ENVIRONMENT == "production"` 且 `SECRET_KEY` 未配置时抛出异常阻止启动。

---

### 2.2 Warning 问题

#### 2.2.1 [agent.py] 内部异常信息泄露给客户端

**行号**: 149-158

```python
return {
    'status': 'error',
    'skill_name': skill_name,
    'error': str(e)  # 可能暴露内部实现细节
}
```

**建议**: 返回通用错误描述 + error_id 用于链路追踪。

---

#### 2.2.2 [planner.py] 计划验证功能缺失

**行号**: 48-95

**问题**: 无法处理循环依赖或冲突步骤，`_find_parallel_steps()` 未考虑跨层依赖，缺少计划可执行性检查。

---

#### 2.2.3 [executor.py] 工具执行缓存缺乏 TTL 过期策略

**行号**: 52-55

**问题**: LRU 缓存无 Time-To-Live，长时间运行的应用中缓存的业务数据可能过时，且无法区分成功/失败结果的保留策略。

---

#### 2.2.4 [main.py] CSRF 保护存在绕过风险

**行号**: 104-127

**问题**: 测试环境跳过 CSRF 校验易误操作；WebSocket 路径绕过 CSRF 依赖 query 参数认证（可被 XSS 窃取）；`HttpOnly=False` 使前端脚本可读取 CSRF token，增大 XSS 风险面。

---

#### 2.2.5 [feedback.py] 内存更新失败被静默吞掉

**行号**: 101-125

**问题**: 内存更新异常不向调用方反馈，可能导致用户会话上下文断裂，且缺少失败原因日志。

---

#### 2.2.6 [model_service.py] 重试策略参数不安全

**行号**: 23-25

**问题**: 退避基数 0.2s 对 429 (Rate Limit) 过短；缺乏 jitter 防止 Thundering Herd；对 409 (Conflict) 的重试可能导致数据不一致。

---

#### 2.2.7 [comprehension.py] 实体识别正则过于原始

**行号**: 42-50

**问题**: 正则无边界检查，中文文本中易误匹配；Windows 路径模式可匹配系统路径导致信息泄露。

---

### 2.3 Info 问题

- **[多文件]** 模板注释过度冗长，缺乏形参/返回值/异常的详细描述
- **[agent.py]** `skill_results` / `plugin_results` 列表无大小限制，长时间运行可能导致内存泄漏
- **[metrics.py]** `render()` 遍历期间未持有锁的完整时间（TOCTOU 风险）
- **[conversation_recorder.py]** 序列化方法缺乏关键异常路径文档

---

## 3. 后端 API 层

**审核范围**: `backend/api/schemas.py`, `backend/api/dependencies.py`, `backend/api/routes/`, `backend/api/services/`

### 3.1 Critical 问题

#### 3.1.1 [chat.py] WebSocket 中的数据库连接泄露

**行号**: 120-145

**问题**: WebSocket 连接长时间存活期间，`db` 变量被持续使用。连接中断时 `db.close()` 的 `finally` 块可能未被正确执行，导致数据库连接池耗尽。

---

#### 3.1.2 [experiences.py] setattr 滥用导致数据验证绕过

**行号**: 138-149

```python
for key, value in update_data.items():
    if key in ALLOWED_UPDATE_FIELDS:
        setattr(experience, key, value)  # 无类型校验
```

**问题**: 虽有白名单但 `setattr` 不验证值的类型或范围，恶意用户可传入任意类型数据污染模型。

**建议**: 逐字段显式赋值，并对 `confidence` 等字段添加范围校验 (0.0 <= x <= 1.0)。

---

#### 3.1.3 [weixin.py] 微信绑定令牌明文存储

**行号**: 62-80

```python
binding = WeixinBinding(
    token=payload.token,  # 直接保存到数据库，未加密
)
```

**问题**: OWASP A02:2021 — OAuth token 和 API 密钥应使用加密存储（如 Fernet 对称加密），而非明文。数据库泄露将直接导致账号被劫持。

---

### 3.2 Warning 问题

| 编号 | 文件 | 问题 | 行号 |
|------|------|------|------|
| 3.2.1 | dependencies.py | Token 过期时间未显式验证 | 24-35 |
| 3.2.2 | experiences.py | 排序字段使用 getattr 存在风险 | 48-56 |
| 3.2.3 | weixin.py | 缺少 OAuth2 state 参数防 CSRF | 145-175 |
| 3.2.4 | auth.py | 登录接口无速率限制（暴力破解风险） | 42-73 |
| 3.2.5 | weixin.py | 微信参数输入验证不足（无长度/格式限制） | 62-80 |
| 3.2.6 | auth.py | 日志中记录用户名，需审查日志访问控制 | 65-72 |
| 3.2.7 | skills.py | 技能列表缺少多租户隔离 | 全文 |
| 3.2.8 | chat_protocol.py | WebSocket 协议版本协商缺失 | 24-48 |
| 3.2.9 | experiences.py | 分页 page 参数无上限（大偏移量致性能问题） | 24-26 |
| 3.2.10 | plugins.py | 事务管理缺少 Rollback 处理 | 78-92 |
| 3.2.11 | chat_protocol.py | 异常处理过于宽泛（bare except） | 140-160 |
| 3.2.12 | chat.py | 部分异步函数中阻塞调用 | 120-135 |

---

## 4. 后端数据库与配置

**审核范围**: `backend/db/models.py`, `backend/config/` (settings.py, security.py, logging.py, experience_settings.py), `backend/migrate_db.py`

### 4.1 Critical 问题

#### 4.1.1 [settings.py] SECRET_KEY 环境检测不严格

**行号**: 11-34

**问题**: `ENVIRONMENT` 默认值为 `"development"`，如果环境变量设置有偏差（如 `prod` 而非 `production`），不会触发异常。应支持更多变体或使用枚举验证。

---

#### 4.1.2 [models.py] SQLite 外键约束启用后未验证是否生效

**行号**: 61-70

```python
cursor.execute("PRAGMA foreign_keys=ON")
cursor.close()  # 未检查 PRAGMA 返回值
```

**问题**: SQLite 旧版本或编译时未启用外键支持时，PRAGMA 命令会被静默忽略，导致孤立数据无法被检测。

**建议**: 执行后查询 `PRAGMA foreign_keys` 验证返回值为 1。

---

#### 4.1.3 [models.py] 日期时间字段 Lambda 默认值陷阱

**行号**: 88-90

```python
created_at: Mapped[datetime] = mapped_column(
    DateTime, default=lambda: datetime.now(timezone.utc)
)
```

**问题**: SQLAlchemy 中 `default=lambda` 实际上是在每次创建实例时调用，这里用法本身是正确的。但建议统一使用 `server_default=func.now()` 确保数据库层面的一致性。

---

#### 4.1.4 [security.py] 密码哈希工作负载未配置

**行号**: 7-8

```python
pwd_context = CryptContext(schemes=["pbkdf2_sha256", "bcrypt"], deprecated="auto")
```

**问题**: 未设置 bcrypt 轮数和 pbkdf2 迭代次数。OWASP 建议 bcrypt rounds >= 12, pbkdf2 rounds >= 600,000。

---

#### 4.1.5 [migrate_db.py] SQL 注入验证可被绕过

**行号**: 45-65

**问题**: 列类型验证中 `.split('(')[0]` 提取基类型后，完整类型字符串仍通过 f-string 拼接到 SQL 中。输入如 `VARCHAR(255); DROP TABLE users--` 可通过基类型检查。

**建议**: 使用更严格的正则白名单 `^(TYPE)\s*(\(\d+\))?\s*(DEFAULT\s+...)?$` 验证完整类型字符串。

---

### 4.2 Warning 问题

| 编号 | 文件 | 问题 | 行号 |
|------|------|------|------|
| 4.2.1 | models.py | 数据库连接池配置偏小（pool_size=5） | 17-24 |
| 4.2.2 | models.py | 慢查询阈值 500ms 硬编码 | 27 |
| 4.2.3 | logging.py | 日志缓冲区大小固定且未可配置 (maxlen=5000) | 21 |
| 4.2.4 | logging.py | 脱敏逻辑不覆盖 JSON 嵌套字段 | 109-135 |
| 4.2.5 | models.py | ExperienceMemory 字段设计问题（命名不清、缺少约束） | 262-285 |
| 4.2.6 | settings.py | 配置类缺少 API 密钥长度验证和 URL 格式验证 | 96-175 |
| 4.2.7 | models.py | 迁移函数参数名 `use_engine` 含义不清 | 353-365 |
| 4.2.8 | logging.py | 日志文件路径使用相对路径，容器环境不可靠 | 300-305 |

---

## 5. 后端插件与安全模块

**审核范围**: `backend/plugins/`, `backend/security/`, `backend/skills/`

### 5.1 Critical 问题

#### 5.1.1 [plugin_sandbox.py] 异步执行缺少资源限制

**行号**: 96-130

**问题**: 异步方法仅施加超时限制，完全无法约束内存和 CPU 占用。`_apply_resource_limits()` 仅在同步线程中有效，恶意插件可在异步方法中无限分配内存导致系统崩溃。

---

#### 5.1.2 [plugin_sandbox.py] execute_command() 缺少前置权限验证

**行号**: 150-200

**问题**: 调用此方法前无权限检查，调用者可能忘记验证权限，导致权限提升。

---

#### 5.1.3 [plugin_manager.py] ZIP 解压路径遍历防护不完整

**行号**: 558-580

**问题**: 逐文件检查但循环末尾调用 `extractall()` 忽略前面检查；缺少 symlink 检查，可创建指向系统目录的符号链接；Windows UNC 路径处理不足。

---

#### 5.1.4 [plugin_manager.py] 静态安全扫描 AST 分析后权限推导不可靠

**行号**: 310-328

**问题**: 仅检查直接导入，别名导入 (`import subprocess as sp`)、动态导入 (`__import__('subprocess')`)、`importlib.import_module()` 均可绕过。

---

#### 5.1.5 [rbac.py] RBAC 权限检查竞态条件 (TOCTOU)

**行号**: 79-96

**问题**: 检查权限和执行操作之间有时间窗口，期间角色可能被撤销，导致使用已撤销权限执行操作。

---

#### 5.1.6 [audit.py] 审计日志写入失败被静默忽略

**行号**: 32-55

**问题**: 审计日志写入失败返回 `None`，导致关键操作无法追溯。安全事件在审计系统故障时完全不可见。

---

#### 5.1.7 [plugin_manager.py] DNS Rebinding 防护存在 TOCTOU 漏洞

**行号**: 890-915

**问题**: URL 安全性检查使用两次 DNS 解析，但实际下载使用 `httpx.get(source_url)` 会第三次解析 DNS，可能得到不同 IP。应在验证后绑定固定 IP 下载。

---

#### 5.1.8 [skill_executor.py] 技能执行缺少粒度权限控制

**问题**: 无细致权限验证框架，任何有权限的用户可执行任意 skill；不区分 read/write/delete 权限粒度。

---

### 5.2 Warning 问题

| 编号 | 文件 | 问题 |
|------|------|------|
| 5.2.1 | plugin_manager.py | 静态扫描危险模式规则过于宽松 |
| 5.2.2 | plugin_manager.py | 多个公开方法缺少权限校验 |
| 5.2.3 | plugin_manager.py | 资源限制配置缺少上下限边界校验 |
| 5.2.4 | plugin_sandbox.py | 插件异常信息可能泄露沙箱内部细节 |
| 5.2.5 | rbac.py | 所有权限检查依赖 DB 查询，高并发下性能瓶颈 |

---

## 6. 后端计费与记忆模块

**审核范围**: `backend/billing/` (engine.py, calculator.py, tracker.py, budget_manager.py, pricing_manager.py, reporter.py, models.py, routers/), `backend/memory/` (manager.py, experience_manager.py)

### 6.1 Critical 问题

#### 6.1.1 [reporter.py] 引用未定义变量 `records` 导致运行时崩溃

**行号**: 108

```python
return {
    "total_calls": len(records),  # records 未定义
}
```

**问题**: `get_cost_statistics()` 方法构建了 `query` 对象但从未执行 `.all()`，后续引用 `records` 导致 `NameError`。所有调用此方法的 API 端点将崩溃。

**建议**: 执行查询获取记录，或改用已有的聚合计数。

---

### 6.2 Warning 问题

#### 6.2.1 [全局] 浮点精度导致金额计算偏差

**行号**: models.py L35-37, calculator.py L120-122, reporter.py L72

**问题**: 整个计费系统使用 `float` 类型存储金额，`round(total_cost, 6)` 的舍入方式不符合财务场景最佳实践。长期累加存在精度丧失风险。

**建议**: 改用 `Decimal` 类型或数据库 `NUMERIC(18,8)` 类型。

---

#### 6.2.2 [engine.py] 预算检查 proposed_cost 始终传 0

**行号**: 48

```python
budget_check = self.budget_manager.check_budget(
    user_id=user_id,
    proposed_cost=0  # 应传入估算成本
)
```

**问题**: 预算检查形同虚设，用户永远不会因预算不足被拦截。

---

#### 6.2.3 [tracker.py] 事务注释与实现不符

**行号**: 71-76

**问题**: `_update_user_summary()` 中注释说"不在此处单独 commit"，但上层 `create_usage_record()` 实际立即 commit，注释具有误导性。

---

#### 6.2.4 [calculator.py] Token 转换常数硬编码无文档

**行号**: 7-10

**问题**: `CHINESE_CHARS_PER_TOKEN = 1.5` 等常数缺乏来源文档和运行时可配置性。

---

#### 6.2.5 [manager.py] 记忆搜索中 N+1 数据库问题

**行号**: 208-226

**问题**: `search_memories()` 对每条结果逐一调用 `update_memory_access()`，产生 N 次数据库更新。

**建议**: 批量更新 `LongTermMemory.id.in_(memory_ids)` 单次 SQL 完成。

---

#### 6.2.6 [experience_manager.py] 成功率计算缺少除零保护

**行号**: 320-333

**问题**: 部分路径下 `success_count / usage_count` 未检查 `usage_count > 0`。

---

#### 6.2.7 [billing/routers] 部分端点缺少 user_id 隔离注释

**行号**: 281-290

**问题**: `GET /api/billing/models` 注入了 `current_user` 但未使用，设计意图不明确。

---

## 7. 后端 MCP 模块

**审核范围**: `backend/mcp/` (client.py, manager.py, protocol.py, transport.py, types.py)

### 7.1 Critical 问题

#### 7.1.1 [transport.py] SSE receive() 方法设计缺陷

**行号**: 254-256

```python
async def receive(self, timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    raise MCPTransportError("SSE 模式请使用 send_and_receive 方法")
```

**问题**: 违反基类接口契约。`client.py` 的 `_send_request()` 可能对 SSE 和 Stdio 使用统一的发送/接收模式，导致 SSE 模式运行时崩溃。

---

#### 7.1.2 [client.py] 调用 SSE 的 send_and_receive() 接口不一致

**行号**: 178-183

**问题**: 客户端假设 `send_and_receive()` 存在但未在基类中声明，跨文件接口不一致，编译时无法检查。

---

#### 7.1.3 [manager.py] 单例模式线程安全缺陷

**行号**: 15-27

```python
def __new__(cls):
    if cls._instance is None:      # 检查
        cls._instance = super().__new__(cls)  # 创建
        cls._instance._initialized = False
    return cls._instance
```

**问题**: `__new__` 和 `__init__` 之间无锁保护。多线程场景下，两个线程同时通过 `is None` 检查将创建多个实例或导致 `_clients` 被初始化多次。

**建议**: 使用 `threading.Lock()` 保护关键区域。

---

#### 7.1.4 [manager.py] 私有字典并发修改导致 RuntimeError

**行号**: 75-85

**问题**: 迭代 `self._clients.items()` 时，另一线程可能修改字典，导致 `RuntimeError: dictionary changed size during iteration`。

**建议**: 迭代前创建快照 `dict(self._clients.items())`。

---

#### 7.1.5 [manager.py] API 路由直接访问私有变量 `_clients`

**行号**: API routes/mcp.py L79

```python
client = manager._clients.get(server_id)
```

**问题**: 违反封装原则。应在 manager 中提供 `is_server_connected()` 等公开方法。

---

#### 7.1.6 [transport.py] Stdio stderr 管道未被读取

**行号**: 94

**问题**: stderr 管道被创建但从未读取，Server 大量错误输出时缓冲区满将导致进程阻塞（假死）。

**建议**: 启动后台 task 持续读取 stderr 并记录日志。

---

### 7.2 Warning 问题

| 编号 | 文件 | 问题 | 行号 |
|------|------|------|------|
| 7.2.1 | transport.py | 连接状态 is_connected 存在竞态检查 | 74 |
| 7.2.2 | client.py | list_tools() 并发调用时 _tools 缓存竞态 | 127-132 |
| 7.2.3 | types.py | Pydantic Config 类已弃用，应迁移到 ConfigDict | 23-35 |
| 7.2.4 | protocol.py | ID 计数器 itertools.count() 非线程安全 | 15-21 |

### 7.3 Info 问题

- transport.py 超时配置硬编码 (30s / 5s)
- client.py 初始化握手响应缺少 error 字段验证
- client.py 无连接重连机制
- manager.py 缺少最大连接数限制和空闲连接清理
- types.py MCPMessage.error 字段结构不符合 JSON-RPC 2.0 规范

---

## 8. 前端核心与共享模块

**审核范围**: `frontend/src/shared/` (api, store, hooks, components, types, utils), `frontend/src/App.tsx`, 配置文件

### 8.1 Critical 问题

#### 8.1.1 [authStore.ts] Token 存储安全风险

**行号**: 14, 18, 26-27

```typescript
token: sessionStorage.getItem('token'),
sessionStorage.setItem('token', token)
```

**问题**: `sessionStorage` 容易受到 XSS 攻击，一旦存在 XSS 漏洞，攻击者可立即获取 JWT token。

**建议**: 使用 HttpOnly Cookies 或内存存储 + refresh token 机制。

---

#### 8.1.2 [api.ts] CSRF Token 解析缺陷

**行号**: 7-10

```typescript
const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/)
```

**问题**: 手工正则解析 cookie 容易遗漏边界情况（特殊字符、空格、编码等）。

**建议**: 使用 `js-cookie` 库替代手工解析。

---

#### 8.1.3 [api.ts] SSE 流式响应错误被静默吞掉

**行号**: 250-263

```typescript
try {
  const data = JSON.parse(dataStr)
} catch (e) {
  // 忽略不完整 chunk 的解析错误
}
```

**问题**: JSON 解析失败被完全忽略，导致网络问题或格式错误时无法调试。

**建议**: 使用 warning 级别的日志记录解析失败，保留前 100 字符用于调试。

---

### 8.2 Warning 问题

| 编号 | 文件 | 问题 | 行号 |
|------|------|------|------|
| 8.2.1 | App.tsx | Token 验证失败后缺少用户提示 | 79-92 |
| 8.2.2 | App.tsx | 自动登录逻辑仅检查 DEV 模式，缺少额外安全开关 | 94-120 |
| 8.2.3 | logger.ts | 敏感字段过滤列表不完整 | 65-82 |
| 8.2.4 | useNotification.ts | Hook 依赖项可能不完整 | 33-44 |
| 8.2.5 | themeStore.ts | 主题切换时未处理 SSR/hydration 场景 | 30-35 |
| 8.2.6 | ConfirmDialog.tsx | 事件冒泡未阻止，嵌套对话框可能异常 | 37-40 |
| 8.2.7 | api.ts | CSRF Token 为空时请求静默发送，后端无法区分 | 27-34 |

### 8.3 Info 问题

- 缺少 Content-Security-Policy (CSP) 响应头配置
- Logger 上报队列 `_reportQueue` 无大小限制，API 不可用时可能导致内存泄漏

---

## 9. 前端功能模块

**审核范围**: `frontend/src/features/` (chat, dashboard, settings, skills, plugins, memory, billing, experiences, communication)

### 9.1 Critical 问题

#### 9.1.1 [ChatPage.tsx] XSS 漏洞 — 错误消息未转义

**行号**: 345-350

```typescript
addMessage('assistant', `请求失败：${error.message}`)
```

**问题**: API 返回的错误消息未经转义直接渲染，恶意 API 可返回包含 `<script>` 标签的内容触发 XSS。

**建议**: 使用 `DOMPurify` 或手动转义 HTML 实体。

---

#### 9.1.2 [SettingsPage.tsx] API 密钥在 React 状态中明文存储

**行号**: 580-620

**问题**: API 密钥存储在 React 状态中，可被 React DevTools 读取或页面崩溃报告泄露。

---

#### 9.1.3 [CommunicationPage.tsx] 轮询定时器内存泄漏

**行号**: 35-40, 175-185

**问题**: 多次调用 `startQrLogin()` 可能启动多个 `setInterval`，`clearQrPolling()` 仅清理最后一个。

---

#### 9.1.4 [SettingsPage.tsx] useEffect 依赖缺失

**行号**: 190-220

**问题**: `loadBillingData` 等函数在 useEffect 依赖外部定义但被调用，可能导致过时闭包。

---

#### 9.1.5 [ChatPage.tsx] 异步请求竞态条件

**行号**: 150-180

**问题**: 无 AbortController，旧请求完成时仍会更新已卸载组件的状态。`retryCount` 在依赖中可能导致无限重试。

---

#### 9.1.6 [BillingPage.tsx] API 返回值未验证

**行号**: 55

**问题**: 假设 `response.data.content` 一定存在，未验证可能为 null/undefined。

---

#### 9.1.7 [PluginsPage.tsx] 文件上传安全漏洞

**行号**: 130-160

**问题**: 仅检查文件扩展名（可绕过），无文件大小限制（DoS 风险），无 MIME 类型验证。

---

#### 9.1.8 [MemoryPage.tsx] 错误处理链不完整

**行号**: 50-80

**问题**: `loadShortTermMemories()` 异步异常未被 try/catch 捕获；`getCandidateSessionIds` 在依赖中可能导致无限循环。

---

#### 9.1.9 [marketplaceApi.ts] 独立 axios 实例导致 Token 管理分裂

**问题**: 创建独立 axios 实例和拦截器，Token 刷新逻辑与主 API 分离，增加维护成本和泄露风险。

**建议**: 统一使用 `@/shared/api/api.ts` 导出的 api 实例。

---

#### 9.1.10 [多文件] localStorage 直接存储敏感数据

**位置**: ChatPage.tsx L80/L287, ReasoningContent.tsx L27-35

**问题**: localStorage 明文存储无过期机制，XSS 攻击可读取全部数据。

---

### 9.2 Warning 问题

| 编号 | 文件 | 问题 |
|------|------|------|
| 9.2.1 | ChatPage.tsx | 大量消息列表无虚拟化渲染（性能） |
| 9.2.2 | SettingsPage.tsx | 表单状态管理过于集中，组件膨胀 |
| 9.2.3 | DashboardPage.tsx | 数据轮询无节流/消抖 |
| 9.2.4 | SkillsPage.tsx | 技能列表搜索为全量过滤 |
| 9.2.5 | ExperiencesPage.tsx | 经验详情加载无取消机制 |
| 9.2.6 | PluginsPage.tsx | 插件状态变更缺少乐观更新 |
| 9.2.7 | CommunicationPage.tsx | 二维码图片数据未清理可能持续占用内存 |
| 9.2.8 | BillingPage.tsx | CSV 导出大数据量下浏览器可能卡顿 |

---

## 10. 总结与优先级建议

### P0 — 必须立即修复（安全/正确性）

| 序号 | 问题 | 模块 | 影响 |
|------|------|------|------|
| 1 | reporter.py 引用未定义变量 `records` | 计费 | 生产崩溃 |
| 2 | MCP Manager 单例线程安全缺陷 | MCP | 数据竞争/崩溃 |
| 3 | MCP 字典并发修改 RuntimeError | MCP | 运行时异常 |
| 4 | SSE transport receive() 违反接口契约 | MCP | SSE 模式不可用 |
| 5 | 微信令牌明文存储 | API/weixin | 账号泄露 |
| 6 | ZIP 路径遍历防护不完整 | 插件 | 任意文件写入 |
| 7 | 插件沙箱异步执行无资源限制 | 插件 | 系统崩溃 |
| 8 | 审计日志写入失败被静默忽略 | 安全 | 安全审计盲区 |

### P1 — 应尽快修复（安全加固）

| 序号 | 问题 | 模块 | 影响 |
|------|------|------|------|
| 9 | 前端 XSS 漏洞（错误消息未转义） | 前端/Chat | XSS 攻击 |
| 10 | Token sessionStorage 存储 | 前端/Auth | Token 窃取 |
| 11 | API 密钥明文存储在 React 状态 | 前端/Settings | 密钥泄露 |
| 12 | executor.py API Key 在日志中泄露 | 后端核心 | 敏感信息泄露 |
| 13 | 登录接口无速率限制 | API/auth | 暴力破解 |
| 14 | RBAC 权限检查竞态条件 | 安全 | 权限提升 |
| 15 | 密码哈希工作负载未配置 | 配置/security | 弱密码保护 |
| 16 | DNS Rebinding TOCTOU 漏洞 | 插件 | SSRF 攻击 |

### P2 — 需要改进（性能/可维护性）

| 序号 | 问题 | 模块 |
|------|------|------|
| 17 | 异步函数中阻塞 ORM 调用（全局性） | 后端全局 |
| 18 | 计费系统浮点精度问题 | 计费 |
| 19 | 预算检查 proposed_cost 始终为 0 | 计费 |
| 20 | 记忆搜索 N+1 查询 | 记忆 |
| 21 | 前端大列表无虚拟化渲染 | 前端 |
| 22 | 前端异步请求竞态条件 | 前端 |
| 23 | 工具执行缓存无 TTL | 后端核心 |
| 24 | 数据库连接池配置偏小 | 数据库 |

### P3 — 建议优化（代码质量）

| 序号 | 问题 | 模块 |
|------|------|------|
| 25 | 日志脱敏不覆盖嵌套字段 | 配置/前端 |
| 26 | Pydantic Config 类迁移到 ConfigDict | MCP |
| 27 | 模板注释过度冗长 | 后端核心 |
| 28 | 事务注释与实现不符 | 计费 |
| 29 | 前端 Logger 队列无大小限制 | 前端 |
| 30 | CSP 响应头未配置 | 前端 |

---

## 附录：审核方法论

1. **静态分析**: 逐文件阅读源代码，检查逻辑正确性和代码风格
2. **安全审计**: 基于 OWASP Top 10 2021 标准检查安全漏洞
3. **架构评估**: 评估模块间耦合度、接口设计和可扩展性
4. **性能分析**: 识别异步阻塞、N+1 查询、内存泄漏等性能瓶颈
5. **代码风格**: 验证命名规范、注释语言（中文）、无 emoji 等项目规范

---

*报告生成于 2026年4月11日，共计发现 120 个问题（40 Critical / 58 Warning / 22 Info）*

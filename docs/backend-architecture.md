# 后端架构说明

本文档基于当前 `backend/` 目录下的代码，对 Open-AwA 后端的结构、主要模块与数据流做说明。

## 1. 总体结构

后端采用 FastAPI 组织 API 层，通过 SQLAlchemy 管理数据模型，并在 `core/`、`skills/`、`plugins/`、`billing/`、`memory/` 等目录中拆分业务模块。

关键入口：

- [main.py](file:///d:/代码/Open-AwA/backend/main.py#L1-L95)

## 2. 启动入口

`main.py` 负责：

- 创建 FastAPI 应用
- 配置 CORS
- 在 `lifespan` 中初始化数据库和计费模块
- 初始化 RBAC 内置角色
- 同步本地用户配置
- 初始化插件市场内置插件
- 初始化插件管理器全局单例，发现并加载数据库中已启用的插件
- 注册认证、聊天、技能、插件、记忆、提示词、行为、经验、会话记录、计费等路由
- 提供根路由与健康检查路由

参考：

- [main.py](file:///d:/代码/Open-AwA/backend/main.py#L26-L95)

## 3. 目录分层

```text
backend/
├─ api/                # FastAPI 路由、依赖与接口 schema
├─ billing/            # 用量计费、预算、报表、模型定价
├─ config/             # 应用配置与安全配置
├─ core/               # Agent 主流程实现
├─ db/                 # SQLAlchemy 模型与数据库初始化
├─ memory/             # 记忆与经验相关逻辑
├─ plugins/            # 插件系统核心实现
├─ security/           # 权限、审计与隔离
├─ skills/             # Skill 引擎与验证器
└─ tests/              # 后端测试
```

## 4. API 层

API 路由集中在 `backend/api/routes/`。

当前已注册的主要路由模块包括：

- [auth.py](file:///d:/代码/Open-AwA/backend/api/routes/auth.py#L14-L62)
- [chat.py](file:///d:/代码/Open-AwA/backend/api/routes/chat.py#L14-L190)
- [skills.py](file:///d:/代码/Open-AwA/backend/api/routes/skills.py#L17-L368)
- [plugins.py](file:///d:/代码/Open-AwA/backend/api/routes/plugins.py#L15-L519)
- [memory.py](file:///d:/代码/Open-AwA/backend/api/routes/memory.py#L12-L121)
- [prompts.py](file:///d:/代码/Open-AwA/backend/api/routes/prompts.py#L10-L109)
- [behavior.py](file:///d:/代码/Open-AwA/backend/api/routes/behavior.py#L11-L119)
- [experiences.py](file:///d:/代码/Open-AwA/backend/api/routes/experiences.py#L14-L260)
- [conversation.py](file:///d:/代码/Open-AwA/backend/api/routes/conversation.py#L14-L139)
- [billing.py](file:///d:/代码/Open-AwA/backend/billing/routers/billing.py#L14-L260)

### 4.1 API 依赖与鉴权

鉴权依赖位于：

- [dependencies.py](file:///d:/代码/Open-AwA/backend/api/dependencies.py)

认证流程通过 JWT 实现，登录接口在校验用户名密码后生成 token。

## 5. 数据层

数据库模型位于：

- [models.py](file:///d:/代码/Open-AwA/backend/db/models.py#L20-L235)

### 5.1 主要实体

当前可确认的主要数据实体有：

- `User`
- `Skill`
- `Plugin`
- `SkillExecutionLog`
- `PluginExecutionLog`
- `ShortTermMemory`
- `LongTermMemory`
- `BehaviorLog`
- `ExperienceMemory`
- `ExperienceExtractionLog`
- `PromptConfig`
- `ConversationRecord`

### 5.2 数据库初始化

数据库初始化入口：

- [init_db](file:///d:/代码/Open-AwA/backend/db/models.py#L225-L227)

此外还包含一个会话记录表字段迁移逻辑：

- [conversation record metadata migration](file:///d:/代码/Open-AwA/backend/db/models.py#L204-L223)

## 6. 聊天与 Agent 主流程

聊天接口位于：

- [chat.py](file:///d:/代码/Open-AwA/backend/api/routes/chat.py#L21-L190)

接口会构造上下文后调用 `AIAgent.process()`。Agent 核心位于：

- [agent.py](file:///d:/代码/Open-AwA/backend/core/agent.py)
- [comprehension.py](file:///d:/代码/Open-AwA/backend/core/comprehension.py)
- [planner.py](file:///d:/代码/Open-AwA/backend/core/planner.py)
- [executor.py](file:///d:/代码/Open-AwA/backend/core/executor.py)
- [feedback.py](file:///d:/代码/Open-AwA/backend/core/feedback.py)

从目录组织可以看出，后端将 Agent 流程拆分为理解、规划、执行、反馈等阶段。

### 6.1 多轮对话上下文机制

Agent 初始化时会创建 `MemoryManager` 并注入到 `FeedbackLayer`。每次处理请求时：

1. `AIAgent._build_conversation_history()` 从 `ShortTermMemory` 中按 `session_id` 检索最近的对话记录
2. 对话历史注入到 `context["conversation_history"]`
3. `ExecutionLayer._build_messages_with_history()` 将历史消息拼接为 LLM messages 数组
4. `FeedbackLayer.update_memory()` 在请求完成后将当前轮次的 user/assistant 消息存入 `ShortTermMemory`

这套机制同时适用于前端聊天和微信聊天，不同渠道通过不同的 `session_id` 隔离上下文：
- 前端聊天：`session_id` 由前端传入（默认 `"default"`）
- 微信聊天：`session_id` 格式为 `"weixin:auto:{account_id}:{from_user_id}"`

### 6.1 模型服务协议与链路治理

模型服务协议适配集中在：

- [model_service.py](file:///d:/代码/Open-AwA/backend/core/model_service.py)
- [executor.py](file:///d:/代码/Open-AwA/backend/core/executor.py)
- [billing.py](file:///d:/代码/Open-AwA/backend/billing/routers/billing.py#L778-L891)

当前实现补充了以下约束：

- 按 `provider` 生成不同的端点、请求头与请求载荷，避免把所有模型服务都按 OpenAI 协议调用
- 在上游模型请求中透传 `X-Request-Id` 与 `X-Client-Ver`
- 对客户端请求返回 `X-Server-Ver` 与 `X-Version-Status`，提供简单版本协商结果
- 为模型服务请求补充标准错误码与有限次重试
- 通过 [metrics.py](file:///d:/代码/Open-AwA/backend/core/metrics.py) 输出简易 Prometheus 文本指标

### 6.2 WebSocket 协议增强

聊天 WebSocket 位于：

- [chat.py](file:///d:/代码/Open-AwA/backend/api/routes/chat.py#L1-L291)

当前在保留最终完整消息的同时，新增了分段消息：

- 每个分段包含 `seq`、`total` 与 `checksum`
- 最终完整消息继续返回 `response` 或 `confirmation_result`
- 工具执行会结合 `idempotency_key` 复用已完成结果，减少重复副作用

## 7. Skill 系统

技能系统入口路由：

- [skills.py](file:///d:/代码/Open-AwA/backend/api/routes/skills.py#L17-L368)

相关核心实现位于：

- [skill_engine.py](file:///d:/代码/Open-AwA/backend/skills/skill_engine.py)
- [skill_validator.py](file:///d:/代码/Open-AwA/backend/skills/skill_validator.py)
- [skill_loader.py](file:///d:/代码/Open-AwA/backend/skills/skill_loader.py)
- [skill_registry.py](file:///d:/代码/Open-AwA/backend/skills/skill_registry.py)

当前已实现的技能侧能力包括：

- 技能信息增删改查
- 技能执行
- YAML 配置校验
- 上传文件解析
- 经验提取接口

## 8. 插件系统

插件系统核心目录：

- `backend/plugins/`

关键模块包括：

- [base_plugin.py](file:///d:/代码/Open-AwA/backend/plugins/base_plugin.py#L5-L58)
- [extension_protocol.py](file:///d:/代码/Open-AwA/backend/plugins/extension_protocol.py#L8-L156)
- [plugin_loader.py](file:///d:/代码/Open-AwA/backend/plugins/plugin_loader.py#L11-L93)
- [plugin_validator.py](file:///d:/代码/Open-AwA/backend/plugins/plugin_validator.py#L24-L160)
- [plugin_sandbox.py](file:///d:/代码/Open-AwA/backend/plugins/plugin_sandbox.py#L8-L121)
- [plugin_lifecycle.py](file:///d:/代码/Open-AwA/backend/plugins/plugin_lifecycle.py#L13-L220)
- [plugin_manager.py](file:///d:/代码/Open-AwA/backend/plugins/plugin_manager.py)
- [plugin_instance.py](file:///d:/代码/Open-AwA/backend/plugins/plugin_instance.py) -- 全局单例管理
- [hot_update_manager.py](file:///d:/代码/Open-AwA/backend/plugins/hot_update_manager.py)

### 8.1 插件管理器单例

插件管理器通过 `plugins.plugin_instance` 模块实现全局单例模式：

- `main.py lifespan` 中调用 `plugin_instance.init(PluginManager())` 初始化
- 启动时自动发现插件并加载数据库中已启用的插件
- 所有路由和 Agent 通过 `plugin_instance.get()` 获取同一实例
- 避免了之前每个模块各自创建 `PluginManager()` 导致状态不一致的问题

### 8.2 插件生命周期管理

插件安装、卸载、启用、禁用操作现在同步更新数据库记录和运行时状态：

- 安装（POST /plugins）：创建 DB 记录后自动 discover + load
- 卸载（DELETE /plugins/{id}）：先 unload 运行时实例再删除 DB 记录
- 启用/禁用（PUT /plugins/{id}/toggle）：切换 DB 状态后同步 load/unload
- 列表（GET /plugins）：返回 DB 记录并附带运行时加载状态和生命周期状态

### 8.3 当前插件接口能力

从插件路由可以确认，后端已支持：

- 插件列表与详情（含运行时状态）
- 插件发现（GET /plugins/discover）
- 数据库层安装记录
- 启用/禁用切换（同步运行时加载/卸载）
- 执行插件方法
- 获取工具描述
- 权限查询、授权、撤销
- 日志读取
- 发现、上传、热更新、回滚
- 配置 schema 查询、保存、重置、导出

## 9. 记忆与经验系统

相关模块：

- [memory.py](file:///d:/代码/Open-AwA/backend/api/routes/memory.py#L12-L121)
- [experiences.py](file:///d:/代码/Open-AwA/backend/api/routes/experiences.py#L14-L260)
- [experience_manager.py](file:///d:/代码/Open-AwA/backend/memory/experience_manager.py)

当前后端已经把记忆分成：

- 短期记忆
- 长期记忆
- 经验记忆

经验记忆还支持：

- 手动创建、更新、删除
- 搜索
- 手动触发提取
- 统计汇总

## 10. 行为分析与会话记录

### 10.1 行为分析

行为分析路由：

- [behavior.py](file:///d:/代码/Open-AwA/backend/api/routes/behavior.py#L11-L119)

当前提供：

- 统计接口
- 日志列表接口
- 手工记录行为接口

### 10.2 会话记录

会话记录路由：

- [conversation.py](file:///d:/代码/Open-AwA/backend/api/routes/conversation.py#L14-L139)

当前提供：

- 最近记录预览
- JSONL 导出
- 历史清理
- 采集开关查询与更新

## 11. 计费系统

计费相关目录：

- `backend/billing/`

核心模块包括：

- [tracker.py](file:///d:/代码/Open-AwA/backend/billing/tracker.py)
- [pricing_manager.py](file:///d:/代码/Open-AwA/backend/billing/pricing_manager.py)
- [budget_manager.py](file:///d:/代码/Open-AwA/backend/billing/budget_manager.py)
- [reporter.py](file:///d:/代码/Open-AwA/backend/billing/reporter.py)
- [billing.py](file:///d:/代码/Open-AwA/backend/billing/routers/billing.py#L14-L260)

当前接口已经覆盖：

- 用量查询
- 成本统计
- 模型价格查询与更新
- 预算配置
- 报表获取
- 保留期相关接口
- 模型配置相关接口

## 12. 后端请求大致流向

以典型 HTTP 请求为例：

```text
客户端请求
  -> FastAPI 路由
  -> Depends 注入数据库 / 当前用户
  -> 业务模块（Agent / Skill / Plugin / Billing / Memory）
  -> SQLAlchemy 持久化或查询
  -> Pydantic / JSON 响应
```

以聊天请求为例，可关注：

- [chat.py](file:///d:/代码/Open-AwA/backend/api/routes/chat.py#L21-L43)

## 13. 当前架构特点

从代码现状来看，后端架构具有以下特点：

- 入口清晰，路由集中注册
- 功能模块按领域拆分较明确
- SQLite 默认可快速启动，适合本地开发
- 插件、技能、记忆、计费是相对独立的功能域
- 仍处于持续演进状态，部分功能已具备接口，但实现成熟度不完全一致

## 14. 阅读建议

如果你需要继续维护后端，建议按以下顺序阅读：

1. [main.py](file:///d:/代码/Open-AwA/backend/main.py#L1-L95)
2. [models.py](file:///d:/代码/Open-AwA/backend/db/models.py#L20-L235)
3. 重点业务路由文件
4. 对应业务目录中的 manager / engine / core 实现
5. `backend/tests/` 中的测试文件

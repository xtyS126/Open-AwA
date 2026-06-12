# Open-AwA Code Wiki

> **项目定位**: AI Agent 实验性平台 / 执行层网关，连接大模型与实际系统操作。
> **技术栈**: FastAPI (Python) + React 18 (TypeScript) + SQLite
> **许可协议**: MIT

---

## 目录

- [一、项目概览](#一项目概览)
- [二、整体架构](#二整体架构)
- [三、后端模块详解](#三后端模块详解)
  - [3.1 入口与启动 (main.py)](#31-入口与启动-mainpy)
  - [3.2 API 层 (api/)](#32-api-层-api)
  - [3.3 核心引擎 (core/)](#33-核心引擎-core)
  - [3.4 技能系统 (skills/)](#34-技能系统-skills)
  - [3.5 插件系统 (plugins/)](#35-插件系统-plugins)
  - [3.6 计费系统 (billing/)](#36-计费系统-billing)
  - [3.7 记忆系统 (memory/)](#37-记忆系统-memory)
  - [3.8 安全模块 (security/)](#38-安全模块-security)
  - [3.9 MCP 协议 (mcp/)](#39-mcp-协议-mcp)
  - [3.10 数据库 (db/)](#310-数据库-db)
  - [3.11 配置模块 (config/)](#311-配置模块-config)
  - [3.12 频道模块 (channels/)](#312-频道模块-channels)
  - [3.13 工作流模块 (workflow/)](#313-工作流模块-workflow)
  - [3.14 数据模型一览](#314-数据模型一览)
- [四、前端模块详解](#四前端模块详解)
  - [4.1 应用入口与路由](#41-应用入口与路由)
  - [4.2 功能模块 (features/)](#42-功能模块-features)
  - [4.3 共享模块 (shared/)](#43-共享模块-shared)
  - [4.4 状态管理](#44-状态管理)
  - [4.5 国际化 (i18n/)](#45-国际化-i18n)
- [五、API 接口参考](#五api-接口参考)
- [六、关键类与函数速查](#六关键类与函数速查)
- [七、依赖关系](#七依赖关系)
- [八、项目运行方式](#八项目运行方式)
- [九、测试体系](#九测试体系)

---

## 一、项目概览

Open-AwA 是一个以 **FastAPI 后端 + React 前端** 构建的 AI Agent 实验性平台，定位为 **AI智能体执行层网关**。

### 核心价值

| 维度 | 说明 |
|------|------|
| 本地运行 | 数据完全私有、安全可靠 |
| 自主执行 | 不仅能回答问题，还能执行实际操作 |
| 可扩展性 | 通过 Skill、MCP、插件灵活扩展 |
| 多层安全 | 沙箱隔离、RBAC、审计日志、CSRF 防护 |

### 当前已实现能力

- 聊天接口（HTTP + WebSocket，支持流式 SSE + 多轮对话上下文）
- 用户注册、登录、JWT 鉴权
- 技能的增删改查、执行、经验提取
- 插件热插拔（发现、加载、启用/禁用、执行、权限管理、热更新）
- 三层记忆系统（短期/长期/经验记忆）
- 工作流定义与执行
- MCP 协议客户端（Stdio + SSE 传输，工具发现与调用）
- 计费系统（模型定价、预算、报表）
- 微信互联（二维码登录、自动回复、技能适配）
- 多频道接入（微信、钉钉、飞书、Telegram、Discord 等）
- 行为分析与会话记录采集
- 定时任务（AI 提示词 + 插件命令调度）
- 子代理派生（多 Agent 协作，支持团队管理和消息传递）
- 用户画像自动提取与管理
- 编码辅助（代码编辑器、文件树、Git 面板、Diff 视图）

---

## 二、整体架构

### 2.1 六层架构设计

```
┌──────────────────────────────────────────────────┐
│ 第1层：用户交互层 (Web UI / CLI / API / IDE)      │
├──────────────────────────────────────────────────┤
│ 第2层：API 网关层 (认证/限流/协议适配/负载均衡)    │
├──────────────────────────────────────────────────┤
│ 第3层：核心引擎层 (NLU/规划/工具调用/记忆管理)     │
├──────────────────────────────────────────────────┤
│ 第4层：技能执行层 (Skill 生命周期/沙箱隔离/权限)   │
├──────────────────────────────────────────────────┤
│ 第5层：资源抽象层 (文件系统/网络/进程/LLM抽象)    │
├──────────────────────────────────────────────────┤
│ 第6层：系统资源层 (本地文件/系统命令/网络/API)     │
└──────────────────────────────────────────────────┘
```

### 2.2 仓库目录总览

```
Open-AwA/
├── backend/               # FastAPI 后端
│   ├── main.py            # FastAPI 入口
│   ├── api/               # 路由、依赖注入、Schema
│   │   ├── routes/        # 业务路由（30+ 模块）
│   │   ├── services/      # 服务层（聊天协议、WebSocket管理）
│   │   ├── dependencies.py # 认证与DB依赖注入
│   │   └── schemas.py     # Pydantic 请求/响应模型
│   ├── core/              # 核心引擎
│   │   ├── agent.py       # AI Agent 主控制器
│   │   ├── executor.py    # 执行层（工具调用、LLM调用）
│   │   ├── planner.py     # 规划层（任务分解）
│   │   ├── comprehension.py # 理解层（意图识别）
│   │   ├── feedback.py    # 反馈层（结果评估）
│   │   ├── autonomous/    # 自主运行模式
│   │   ├── builtin_tools/ # 内置工具（文件/终端/搜索/待办）
│   │   ├── coding/        # 编码辅助（AST搜索/LSP/Git/Diff）
│   │   ├── context/       # 上下文压缩与Token预算
│   │   ├── heartbeat/     # 心跳引擎
│   │   ├── startup/       # 启动流程（引导/性能分析）
│   │   ├── task_runtime/  # 任务运行时（子代理/团队/消息）
│   │   └── workspace/     # 工作区管理
│   ├── billing/           # 计费模块
│   ├── channels/          # 多频道接入
│   ├── config/            # 配置管理
│   ├── db/                # 数据库模型与初始化
│   ├── mcp/               # MCP 协议客户端
│   ├── memory/            # 记忆系统
│   ├── plugins/           # 插件系统
│   ├── security/          # 安全模块
│   ├── skills/            # 技能系统
│   ├── tools/             # 工具注册
│   └── workflow/          # 工作流引擎
├── frontend/              # React 前端
│   ├── src/
│   │   ├── features/      # 功能模块（按领域拆分）
│   │   ├── shared/        # 共享资源（API/组件/Store/Hooks）
│   │   ├── styles/        # 全局样式
│   │   ├── assets/        # 静态资源
│   │   └── i18n/          # 国际化
│   └── tests/e2e/         # Playwright E2E 测试
├── plugins/               # 示例插件
├── docs/                  # 项目文档
├── scripts/               # 脚本工具
└── reports/               # 审计/代码审查报告
```

### 2.3 Agent 核心流程（理解 -> 规划 -> 执行 -> 反馈）

```
用户输入
  │
  ├── 魔法命令检测 (magic_commands.py)
  │    └── 匹配成功 → 直接执行命令 → 返回结果
  │
  ├── 意图识别 (comprehension.py: recognize_intent)
  ├── 实体提取 (comprehension.py: extract_entities)
  │
  ├── 经验检索 (experience检索)
  ├── 长期记忆检索 (向量搜索)
  │
  ├── 任务规划 (planner.py: create_plan)
  │    ├── execute → [read_files, execute_command, llm_generate]
  │    ├── query   → [llm_query]
  │    ├── explain → [llm_explain]
  │    └── chat    → [llm_chat]
  │
  ├── 自动执行技能/插件 (匹配的Skill和Plugin)
  │
  ├── 步骤执行循环 (executor.py: execute_step)
  │    ├── 幂等缓存检查
  │    ├── 参数Schema校验
  │    ├── 自主模式安全检查（四层洋葱）
  │    ├── 分发执行（LLM调用 / 工具调用 / 技能 / 插件）
  │    └── 结果缓存
  │
  ├── 反馈评估 (feedback.py: evaluate_result)
  │    ├── needs_confirmation? → 等待用户确认
  │    └── needs_retry?       → 重试执行
  │
  └── 更新记忆 (短期记忆持久化)
```

### 2.4 流式处理流程 (process_stream)

```
用户输入
  │
  ├── yield "status: starting"
  ├── 上下文准备（对话历史、多模态、思考参数）
  │
  ├── yield "status: planning"
  ├── yield "type: plan" (规划结果)
  │
  ├── Tool Call 循环 (最多 N 轮):
  │    ├── 流式 LLM 调用 → yield chunk...
  │    ├── 检测到 tool_calls:
  │    │    ├── yield "task" 事件
  │    │    ├── 逐个执行工具:
  │    │    │    ├── yield "tool" running
  │    │    │    ├── 执行工具
  │    │    │    ├── yield "tool" completed/error
  │    │    │    └── 特殊处理 (notification/todo_update/subagent等)
  │    │    └── 注入工具结果到上下文
  │    └── 无 tool_calls → 退出循环
  │
  └── 更新记忆
```

---

## 三、后端模块详解

### 3.1 入口与启动 (main.py)

**文件**: [main.py](file:///d:/代码/Open-AwA/backend/main.py)

#### 启动流程

启动过程按职责拆分为 6 个独立步骤，每步失败有独立日志和错误上下文：

| 步骤 | 函数 | 职责 |
|------|------|------|
| 1. 基础设施 | `_startup_infrastructure()` | LiteLLM 依赖检测、模型供应商可用性检查、API Key 初始化 |
| 2. 数据初始化 | `_startup_data_init()` | DB 建表、计费配置、默认定价、RBAC 角色、Owner 用户创建 |
| 3. 插件系统 | `_startup_plugin_system()` | 市场种子、插件发现、已启用插件加载 |
| 4. 后台任务 | `_startup_background_tasks()` | 定时任务管理器启动、微信自动回复自动启动 |
| 5. 自主模式 | `_startup_autonomous_mode()` | 自主运行模式初始化（可选，通过.env配置） |
| 6. 关闭流程 | `lifespan() -> yield` | 自主模式关闭 → 定时任务停止 → HTTP客户端关闭 |

#### 中间件注册顺序

| 中间件 | 职责 |
|--------|------|
| CORS | 跨域资源共享 |
| CSP | Content-Security-Policy 安全头 |
| CSRF Protection | Per-session 签名 Token 模式 |
| Request Context | 生成/继承请求ID、日志上下文、版本协商 |
| Cache Headers | 静态资源长期缓存策略 |

#### 路由注册（按注册顺序）

| 路由前缀 | 模块 | 说明 |
|----------|------|------|
| `/api/auth` | auth | 认证路由 |
| `/api/chat` | chat | 聊天路由 |
| `/api/skills` | skills | 技能路由 |
| `/api/plugins` | plugins | 插件路由 |
| `/api/memory` | memory | 记忆路由 |
| `/api/workflows` | workflows | 工作流路由 |
| `/api/scheduled-tasks` | scheduled_tasks | 定时任务路由 |
| `/api/diary` | diary | 日记路由 |
| `/api/prompts` | prompts | 提示词路由 |
| `/api/behaviors` | behavior | 行为分析路由 |
| `/api/experiences` | experiences | 经验路由 |
| `/api/conversations` | conversation | 会话记录路由 |
| `/api/logs` | logs | 日志路由 |
| `/api/mcp` | mcp | MCP协议路由 |
| `/api/models` | models | 模型配置路由 |
| `/api/billing` | billing | 计费路由 |
| `/api/marketplace` | marketplace | 市场路由 |
| `/api/security` | security | 安全路由 |
| `/api/weixin` | weixin | 微信路由 |
| `/api/tools` | tools | 工具路由 |
| `/api/subagents` | subagents | 子代理路由 |
| `/api/task-runtime` | task_runtime | 任务运行时路由 |
| `/api/user` | user | 用户路由 |
| `/api/user-profile` | user_profile | 用户画像路由 |
| `/api/system` | system | 系统路由 |
| `/api/test-runner` | test_runner | 测试运行路由 |
| `/api/workspace` | workspace | 工作区路由 |
| `/api/heartbeat` | heartbeat | 心跳路由 |
| `/api/coding` | coding | 编码路由 |
| `/api/inbox` | inbox | 收件箱路由 |
| `/api/magic-commands` | magic_commands | 魔法命令路由 |
| `/api/tts` | tts | 语音合成路由 |
| `/api/tasks` | tasks | 任务路由 |

#### 关键函数

| 函数 | 说明 |
|------|------|
| `lifespan(app)` | FastAPI 生命周期管理，组织启动与关闭 |
| `get_csrf_token()` | 返回 per-session 签名 CSRF Token |
| `root()` | `/` 根路径健康探活 |
| `health_check()` | `/health` 轻量级健康检查（无需认证） |
| `metrics()` | `/metrics` Prometheus 文本指标导出（需认证） |
| `run_server()` | 启动 uvicorn 服务，处理端口占用等异常 |
| `_get_client_ip()` | 从请求中提取真实客户端 IP（代理感知） |

---

### 3.2 API 层 (api/)

#### 3.2.1 依赖注入 (dependencies.py)

**文件**: [dependencies.py](file:///d:/代码/Open-AwA/backend/api/dependencies.py)

| 依赖函数 | 说明 |
|----------|------|
| `get_current_user()` | 统一认证：API Key 优先 → JWT Bearer → Cookie |
| `get_optional_current_user()` | 可选认证，未认证返回 None 而非异常 |
| `get_current_admin_user()` | 管理员权限检查 |
| `_normalize_request_token()` | Token 规范化（长度、字符集、空白字符校验） |

**认证优先级**: `API Key (compare_digest)` > `JWT Bearer` > `HttpOnly Cookie`

#### 3.2.2 服务层 (api/services/)

| 文件 | 说明 |
|------|------|
| `chat_protocol.py` | 聊天协议：SSE事件构建（task/tool/subagent/notification/todo） |
| `diary_writer.py` | 日记写入器 |
| `weixin_auto_reply.py` | 微信自动回复管理器 |
| `ws_manager.py` | WebSocket 连接管理与广播 |

#### 3.2.3 核心路由说明

| 路由文件 | 核心功能 |
|----------|----------|
| [auth.py](file:///d:/代码/Open-AwA/backend/api/routes/auth.py) | 登录、注册、登出、CSRF Token获取、当前用户信息 |
| [chat.py](file:///d:/代码/Open-AwA/backend/api/routes/chat.py) | 聊天发送（HTTP+SSE）、WebSocket 聊天、会话取消、历史消息 |
| [skills.py](file:///d:/代码/Open-AwA/backend/api/routes/skills.py) | 技能CRUD、执行、微信技能适配 |
| [plugins.py](file:///d:/代码/Open-AwA/backend/api/routes/plugins.py) | 插件CRUD、导入/导出、启用/禁用、权限管理、热更新 |
| [memory.py](file:///d:/代码/Open-AwA/backend/api/routes/memory.py) | 短期/长期记忆管理、向量搜索、归档、质量报告 |
| [models.py](file:///d:/代码/Open-AwA/backend/api/routes/models.py) | 模型配置管理、供应商管理 |
| [scheduled_tasks.py](file:///d:/代码/Open-AwA/backend/api/routes/scheduled_tasks.py) | 定时任务CRUD、Cron表达式、每日重复任务 |
| [task_runtime.py](file:///d:/代码/Open-AwA/backend/api/routes/task_runtime.py) | 子代理管理、团队管理、任务清单 |
| [tts.py](file:///d:/代码/Open-AwA/backend/api/routes/tts.py) | 语音合成、声音克隆、语音库管理 |
| [weixin.py](file:///d:/代码/Open-AwA/backend/api/routes/weixin.py) | 微信二维码登录、绑定状态、自动回复规则 |
| [tasks.py](file:///d:/代码/Open-AwA/backend/api/routes/tasks.py) | 非交互式任务执行（v1.5）：后台任务提交、超时控制、Webhook回调、SSRF防护 |
| [weixin_skill.py](file:///d:/代码/Open-AwA/backend/api/routes/weixin_skill.py) | 微信技能适配路由 |
| [user_profile.py](file:///d:/代码/Open-AwA/backend/api/routes/user_profile.py) | 用户画像管理 |
| [workspace.py](file:///d:/代码/Open-AwA/backend/api/routes/workspace.py) | 工作区管理 |
| [heartbeat.py](file:///d:/代码/Open-AwA/backend/api/routes/heartbeat.py) | 心跳路由 |
| [inbox.py](file:///d:/代码/Open-AwA/backend/api/routes/inbox.py) | 收件箱管理 |
| [magic_commands.py](file:///d:/代码/Open-AwA/backend/api/routes/magic_commands.py) | 魔法命令路由 |
| [marketplace.py](file:///d:/代码/Open-AwA/backend/api/routes/marketplace.py) | 插件/技能市场路由 |
| [user.py](file:///d:/代码/Open-AwA/backend/api/routes/user.py) | 用户管理路由 |
| [diary.py](file:///d:/代码/Open-AwA/backend/api/routes/diary.py) | 日记路由 |
| [tools.py](file:///d:/代码/Open-AwA/backend/api/routes/tools.py) | 工具路由 |
| [subagents.py](file:///d:/代码/Open-AwA/backend/api/routes/subagents.py) | 子代理路由 |
| [system.py](file:///d:/代码/Open-AwA/backend/api/routes/system.py) | 系统信息路由 |
| [security.py](file:///d:/代码/Open-AwA/backend/api/routes/security.py) | 安全配置路由 |
| [coding.py](file:///d:/代码/Open-AwA/backend/api/routes/coding.py) | 编码辅助路由 |

---

### 3.3 核心引擎 (core/)

#### 3.3.1 AIAgent — 主控制器

**文件**: [agent.py](file:///d:/代码/Open-AwA/backend/core/agent.py)

**类**: `AIAgent`

**核心属性**:
- `comprehension: ComprehensionLayer` — 理解层
- `planner: PlanningLayer` — 规划层
- `executor: ExecutionLayer` — 执行层
- `feedback: FeedbackLayer` — 反馈层
- `skill_engine: SkillEngine` — 技能引擎
- `plugin_manager: PluginManager` — 插件管理器
- `memory_manager: MemoryManager` — 记忆管理器
- `workflow_engine: WorkflowEngine` — 工作流引擎

**核心方法**:

| 方法 | 说明 |
|------|------|
| `process(user_input, context)` | **非流式主流程**：意图识别→规划→执行(Skill/Plugin/Tool)→反馈→记忆更新 |
| `process_stream(user_input, context)` | **流式主流程**：同process但实时yield数据块（支持Tool Call循环） |
| `handle_confirmation(confirmed, step, context)` | 处理用户确认/取消操作 |
| `execute_skill(skill_name, inputs, context)` | 通过SkillEngine执行技能 |
| `execute_plugin(plugin_name, method, **kwargs)` | 执行插件方法 |
| `_inject_runtime_capabilities(context)` | 注入运行态能力到上下文（技能/插件/MCP/模型目录） |
| `_build_native_tools(capabilities)` | 构建OpenAI兼容的tools参数（原生function calling） |
| `_auto_execute_skills_and_plugins()` | 基于意图自动匹配并执行技能/插件 |
| `_auto_compress_context()` | 自动检测Token使用量并压缩对话上下文 |

**活跃任务管理**:
- `register_agent_task(session_id, task)` — 注册活跃Agent任务
- `unregister_agent_task(session_id)` — 移除已完成任务
- `get_agent_task(session_id)` — 获取指定会话任务（供取消端点使用）
- `_cleanup_completed_tasks()` — 清理已完成/已取消任务（防止内存泄漏）

#### 3.3.2 ExecutionLayer — 执行层

**文件**: [executor.py](file:///d:/代码/Open-AwA/backend/core/executor.py)

**类**: `ExecutionLayer`

**核心方法**:

| 方法 | 说明 |
|------|------|
| `execute_step(step, context)` | 执行单个规划步骤，根据 action 分发给对应处理函数 |
| `retry_step(step, context)` | 重试失败步骤（绕过缓存） |
| `_call_llm_api(prompt, context)` | 非流式LLM调用（LiteLLM），支持 tool_calls 循环 |
| `_call_llm_api_stream(prompt, context)` | 流式LLM调用，yield {content, reasoning_content} |
| `_execute_tool_call(tool_call, context)` | 执行单个工具调用，按前缀分发 |
| `_resolve_llm_configuration(context)` | 解析LLM配置（provider/model/api_key/api_endpoint），四级优先级 |

**工具调用分发逻辑**:
- `plugin_*` → 插件系统执行（自动加载/自动发现）
- `mcp_*` → MCP 客户端执行
- `builtin_*` → 内置工具（通过ToolRegistry或builtin_tool_manager）
- `task_*` → 任务运行时（子代理/团队/消息/任务清单/Todo）

**关键辅助方法**:
- `resolve_max_tool_call_rounds()` — 解析工具调用回环上限（默认settings配置，上限100轮）
- `validate_parameters_against_schema()` — JSON Schema 校验工具参数
- `_build_tool_idempotency_key()` — 构建幂等键，防止重复副作用
- `_build_agent_capability_system_prompt()` — 构建Agent能力说明系统提示词

#### 3.3.3 PlanningLayer — 规划层

**文件**: [planner.py](file:///d:/代码/Open-AwA/backend/core/planner.py)

**类**: `PlanningLayer`

**方法**:

| 方法 | 说明 |
|------|------|
| `create_plan(intent, entities, context)` | 根据意图类型创建执行计划 |
| `_create_execution_plan()` | 执行意图：read_files + execute_command + llm_generate |
| `_create_query_plan()` | 查询意图：llm_query |
| `_create_explain_plan()` | 解释意图：llm_explain |
| `_create_chat_plan()` | 对话意图：llm_chat |
| `analyze_dependencies(steps)` | 分析步骤依赖关系，识别可并行执行的步骤 |
| `generate_experience_prompt(experiences)` | 生成经验提示词 |

#### 3.3.4 其他核心模块

| 文件 | 核心类/函数 | 说明 |
|------|-------------|------|
| `comprehension.py` | `ComprehensionLayer` | 意图识别、实体提取 |
| `feedback.py` | `FeedbackLayer` | 结果评估、确认需求判断、记忆更新 |
| `model_service.py` | `build_thinking_params()`, `build_multimodal_message()` | 模型服务协议适配 |
| `litellm_adapter.py` | `litellm_chat_completion()`, `litellm_chat_completion_stream()` | LiteLLM 统一调用层 |
| `magic_commands.py` | `get_magic_command_registry()` | 魔法命令注册与解析 |
| `metrics.py` | `prometheus_registry` | Prometheus 指标导出 |
| `behavior_logger.py` | `behavior_logger` | 行为埋点日志 |
| `conversation_recorder.py` | `conversation_recorder` | 会话记录 |
| `scheduled_task_manager.py` | `scheduled_task_manager` | 定时任务调度 |
| `subagent.py` | | 子代理派生与服务 |
| `context/compressor.py` | `ContextCompressor` | 对话上下文压缩 |
| `context/token_budget.py` | `TokenBudget` | Token 预算控制 |
| `autonomous/manager.py` | `get_autonomous_manager()` | 自主运行模式管理 |
| `builtin_tools/manager.py` | `builtin_tool_manager` | 内置工具管理 |

##### 3.3.4.1 Owner 用户模块

**文件**: [core/owner.py](file:///d:/代码/Open-AwA/backend/core/owner.py)

v1.5 引入的单用户模式 Owner 管理模块，提供统一的所有者查询和创建逻辑：

| 函数 | 类型 | 说明 |
|------|------|------|
| `ensure_owner_user(db)` | 同步 | 确保唯一 owner 用户在 DB 中存在（启动时调用） |
| `get_owner_user(db)` | 异步 | 异步获取 owner（带 Dual-Check Locking 缓存） |
| `get_owner_id_sync(db)` | 同步 | 同步获取 owner ID（用于非 async 上下文） |
| `invalidate_owner_cache()` | 同步 | 清除 owner 缓存（测试/更新后使用） |

**环境变量配置**:
- `OPENAWA_OWNER_USERNAME` — owner 用户名（默认 admin）
- `OPENAWA_OWNER_PASSWORD` — owner 密码（未设置时自动生成）
- `OPENAWA_OWNER_NICKNAME` — 昵称（可选）
- `OPENAWA_OWNER_EMAIL` — 邮箱（可选）

##### 3.3.4.2 自主运行模式安全增强 (autonomous/)

**目录**: [core/autonomous/](file:///d:/代码/Open-AwA/backend/core/autonomous/)

v1.5 对自主模式进行了全面安全加固，实现了**四层安全洋葱模型**：

| 文件 | 类 | 安全层级 | 说明 |
|------|-----|----------|------|
| `hard_deny.py` | `HardDenyChecker` | 第1层：硬底线 | 永久禁止系统破坏命令、敏感路径访问、自身配置修改 |
| `workspace_boundary.py` | `WorkspaceBoundary` | 第2层：工作区边界 | 限制文件操作在工作区根目录内，防止路径穿越 |
| `network_policy.py` | `NetworkPolicyChecker` | 第3层：网络策略 | 出站网络控制（AllowAll/BlockLocal/AllowList） |
| `resource_limits.py` | `ResourceLimiter` | 第4层：资源限制 | CPU/内存/时间硬限制 |
| `checkpoint.py` | `CheckpointManager` | 辅助 | 文件写入/删除前自动创建回滚检查点 |
| `audit.py` | `AutonomousAuditor` | 辅助 | 自主操作审计日志（定期刷新） |
| `config.py` | `AutonomousConfig` | 配置 | 完整自主模式配置（仅通过 .env 环境变量读取） |
| `manager.py` | `AutonomousModeManager` | 编排 | 全局单例，统一管理四层安全组件 |

**硬底线检查列表** (hard_deny.py):
- 系统破坏命令: `rm -rf /`, `dd of=/dev/`, `sudo`, `shutdown`, `reboot`, fork炸弹等
- 敏感系统路径: `/etc/shadow`, `/etc/passwd`, `/proc`, `/sys`, `/boot`, `/root/.ssh`
- 自身配置保护: `.env`, `.env.local`, `config/settings.py`, `config/security.py`

**自主模式配置环境变量**:

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OPENAWA_AUTONOMOUS_MODE` | 主开关 (true/false) | false |
| `OPENAWA_AUTONOMOUS_CONFIRM_KEY` | 确认密钥（可选二次验证） | - |
| `OPENAWA_AUTONOMOUS_SCOPE` | 生效范围 (scheduled/chat/ci) | - |
| `OPENAWA_AUTONOMOUS_WORKSPACE` | 工作区根目录（必填） | - |
| `OPENAWA_AUTONOMOUS_NETWORK_POLICY` | 网络策略 (allow_all/block_local/allowlist) | allow_all |
| `OPENAWA_AUTONOMOUS_CMD_TIMEOUT` | 单命令超时（秒） | 120 |
| `OPENAWA_AUTONOMOUS_TASK_TIMEOUT` | 总任务超时（秒） | 1800 |
| `OPENAWA_AUTONOMOUS_MEMORY_LIMIT` | 内存限制（MB） | 1024 |
| `OPENAWA_AUTONOMOUS_CHECKPOINT_ENABLED` | 自动回滚 | true |
| `OPENAWA_AUTONOMOUS_AUDIT_LEVEL` | 审计级别 (minimal/full) | full |
| `OPENAWA_AUTONOMOUS_ALERT_WEBHOOK` | 告警 Webhook | - |



---

### 3.4 技能系统 (skills/)

**目录**: [backend/skills/](file:///d:/代码/Open-AwA/backend/skills/)

#### 核心模块

| 文件 | 类 | 说明 |
|------|-----|------|
| `skill_engine.py` | `SkillEngine` | 技能引擎：技能加载、执行、统计 |
| `skill_registry.py` | | 技能注册表：技能元数据管理 |
| `skill_loader.py` | | 技能加载器：从DB/YAML加载技能定义 |
| `skill_executor.py` | | 技能执行器：单个技能的步骤执行 |
| `skill_validator.py` | | 技能验证器：校验技能YAML配置格式 |
| `skill_matcher.py` | | 技能匹配器：基于意图/实体匹配技能 |
| `skill_orchestrator.py` | | 技能编排器：多技能协同调度 |
| `skill_security.py` | | 技能安全：沙箱执行与权限检查 |
| `experience_extractor.py` | `ExperienceExtractor` | 经验提取器：从执行会话提取经验 |
| `pool_manager.py` | | 技能池管理 |
| `version_manager.py` | | 技能版本管理 |
| `weixin_skill_adapter.py` | | 微信技能适配器 |

#### 内置技能 (builtin/)

| 文件 | 技能名称 | 说明 |
|------|----------|------|
| `file_reader.py` | file_reader | 文件读取技能 |
| `browser_cdp.py` | browser_cdp | 浏览器CDP控制 |
| `browser_visible.py` | browser_visible | 浏览器可视化操作 |
| `channel_message.py` | channel_message | 频道消息发送 |
| `cron.py` | cron | 定时任务技能 |
| `dingtalk_channel.py` | dingtalk_channel | 钉钉频道技能 |
| `docx.py` | docx | Word文档读写 |
| `guidance.py` | guidance | 引导技能（系统内置） |
| `himalaya.py` | himalaya | Himalaya服务技能 |
| `multi_agent_collaboration.py` | | 多Agent协作技能 |
| `news.py` | news | 新闻获取技能 |
| `pdf.py` | pdf | PDF文件处理 |
| `pptx.py` | pptx | PPT文件处理 |
| `qa_source_index.py` | | QA源索引技能 |
| `xlsx.py` | xlsx | Excel文件处理 |

---

### 3.5 插件系统 (plugins/)

**目录**: [backend/plugins/](file:///d:/代码/Open-AwA/backend/plugins/)

#### 核心模块

| 文件 | 关键类/函数 | 说明 |
|------|-------------|------|
| `plugin_manager.py` | `PluginManager` | 插件管理器：加载/卸载/执行/发现 |
| `base_plugin.py` | `BasePlugin` | 插件基类 |
| `plugin_loader.py` | | 插件加载器 |
| `plugin_validator.py` | | 插件验证器（ZIP/MIME/大小校验） |
| `plugin_sandbox.py` | | 插件沙箱隔离 |
| `plugin_lifecycle.py` | | 插件生命周期（发现→加载→验证→启用→禁用） |
| `plugin_instance.py` | `plugin_instance` | 全局单例（通过 `get()` 获取） |
| `hot_update_manager.py` | | 热更新管理（更新/回滚） |
| `plugin_context.py` | `PluginContext` | 插件上下文 |
| `plugin_logger.py` | | 插件日志 |
| `extension_protocol.py` | | 扩展协议 |
| `event_bus.py` | | 插件事件总线 |
| `dependency_resolver.py` | | 插件依赖解析 |
| `schema_validator.py` | | 插件Schema校验 |
| `command_plugin.py` | `CommandPlugin` | 命令型插件 |
| `cli/plugin_cli.py` | | 插件CLI工具 |
| `marketplace/registry.py` | `marketplace_registry` | 插件市场注册表 |

#### 插件生命周期

```
发现 (discover) → 加载 (load) → 验证 (validate)
    → 安装 (install) → 启用 (enable) → 执行 (execute)
    → 禁用 (disable) → 卸载 (unload)
    → 热更新 (hot_update) ←→ 回滚 (rollback)
```

**使用单例获取**: `from plugins import plugin_instance; pm = plugin_instance.get()`

---

### 3.6 计费系统 (billing/)

**目录**: [backend/billing/](file:///d:/代码/Open-AwA/backend/billing/)

| 文件 | 类/函数 | 说明 |
|------|---------|------|
| `tracker.py` | `UsageTracker` | 用量追踪 |
| `calculator.py` | `CostCalculator` | 成本计算 |
| `engine.py` | `BillingEngine` | 计费引擎 |
| `pricing_manager.py` | `PricingManager` | 价格配置管理（DB读写、模型配置解析） |
| `budget_manager.py` | `BudgetManager` | 预算管理 |
| `reporter.py` | `UsageReporter` | 报表生成 |
| `models.py` | | 计费数据模型 |
| `deepseek_tokenizer_utils.py` | | DeepSeek Tokenizer 辅助 |
| `routers/billing.py` | | 计费API路由 |

---

### 3.7 记忆系统 (memory/)

**目录**: [backend/memory/](file:///d:/代码/Open-AwA/backend/memory/)

#### 三层记忆架构

| 层 | 表 | 类/文件 | 说明 |
|-----|-----|---------|------|
| 短期记忆 | `short_term_memory` | `manager.py` | 当前会话上下文记忆（按session_id隔离） |
| 长期记忆 | `long_term_memory` | `manager.py` | 持久化重要知识，支持向量检索 |
| 经验记忆 | `experience_memory` | `experience_manager.py` | 结构化经验，含置信度和使用统计 |

| 文件 | 说明 |
|------|------|
| `manager.py` | `MemoryManager`: 统一记忆管理入口 |
| `experience_manager.py` | `ExperienceManager`: 经验记忆管理 |
| `working_memory.py` | 工作内存管理 |
| `vector_store_manager.py` | ChromaDB 向量存储管理 |
| `hybrid_search.py` | BM25 + 向量混合检索 |
| `bm25_retriever.py` | BM25 关键词检索 |
| `auto_dream.py` | 自动"梦境"生成（定时摘要） |
| `daily_log.py` | 日记日志管理 |
| `chroma_telemetry.py` | ChromaDB 遥测 |

---

### 3.8 安全模块 (security/)

**目录**: [backend/security/](file:///d:/代码/Open-AwA/backend/security/)

| 文件 | 类/函数 | 说明 |
|------|---------|------|
| `rbac.py` | `RBACManager` | 基于角色的访问控制（admin/developer/viewer） |
| `permission.py` | | 权限控制 |
| `audit.py` | `AuditLogger` | 审计日志（异步写入+失败告警） |
| `sandbox.py` | `validate_command_safety()` | 命令执行安全白名单 |
| `unified_access.py` | | 统一访问控制 |
| `pii.py` | | 敏感信息脱敏 |
| `rate_limit_store.py` | `init_rate_limit_store()` | 分布式限流存储 |
| `backends.py` | | 安全后端 |
| `backup_trust.py` | | 备份信任 |

**安全体系**:
- **认证**: JWT + API Key (compare_digest) + HttpOnly Cookie（v1.5 新增 API Key 单用户模式认证）
- **CSRF**: Per-session签名Token + Double Submit Cookie + 所有 Bearer 请求跳过 CSRF
- **RBAC**: admin / developer / viewer 三级角色
- **加密**: Fernet对称加密存储敏感字段
- **沙箱**: 命令白名单、路径穿越防护、超时控制
- **审计**: 异步审计日志、写入失败告警
- **SSRF防护** (v1.5): Webhook URL 仅允许HTTPS、拒绝内网/本地/链路本地IP、`follow_redirects=False`、云元数据端点黑名单
- **CSP**: Content-Security-Policy 安全头（script-src 禁止 unsafe-inline）

---

### 3.9 MCP 协议 (mcp/)

**目录**: [backend/mcp/](file:///d:/代码/Open-AwA/backend/mcp/)

| 文件 | 类/函数 | 说明 |
|------|---------|------|
| `manager.py` | `MCPManager` | 线程安全单例，管理多Server连接 |
| `client.py` | | MCP 客户端实现 |
| `protocol.py` | `MCPProtocol` | 标准JSON-RPC 2.0请求构建 |
| `transport.py` | | Stdio + SSE 双传输模式实现 |
| `types.py` | | MCP 协议类型定义 |
| `config_store.py` | | MCP Server 配置存储 |
| `sandbox.py` | | MCP 执行沙箱 |

**传输模式**:
- **Stdio**: 子进程 stdin/stdout 通信，自动读取stderr防止缓存满导致假死
- **SSE**: HTTP POST 传输

---

### 3.10 数据库 (db/)

**文件**: [models.py](file:///d:/代码/Open-AwA/backend/db/models.py)

#### 关键函数

| 函数 | 说明 |
|------|------|
| `init_db(bind_engine=None)` | 数据库初始化：建表 + 迁移（支持自定义engine） |
| `get_db()` | FastAPI 依赖注入：获取数据库会话 |
| `Base` | SQLAlchemy 声明式基类 |

#### SQLite 特殊配置
- WAL 模式: `PRAGMA journal_mode=WAL`
- 外键强制: `PRAGMA foreign_keys=ON`
- 繁忙超时: `PRAGMA busy_timeout=30000`
- 慢查询监控: SQL事件监听（阈值可配置）
- 错误监听: `handle_error` 事件

#### ORM 模型层级

```
Base
├── User              # 用户模型
├── Workspace         # 工作区模型
├── LoginDevice       # 登录设备
├── Skill             # 技能模型
├── Plugin            # 插件模型
├── SkillExecutionLog # 技能执行日志
├── PluginExecutionLog# 插件执行日志
├── Conversation      # 会话聚合
├── ShortTermMemory   # 短期记忆
├── LongTermMemory    # 长期记忆
├── Workflow          # 工作流定义
├── WorkflowStep      # 工作流步骤
├── WorkflowExecution # 工作流执行记录
├── ScheduledTask     # 定时任务
├── ScheduledTaskExecution # 定时任务执行记录
├── BehaviorLog       # 行为埋点日志
├── ExperienceMemory  # 经验记忆
├── Role              # 角色
├── UserRole          # 用户角色关联
├── AuditLog          # 审计日志
├── LoginRateLimit    # 登录限流
├── UserFeedback      # 用户反馈
├── ExperienceExtractionLog # 经验提取日志
├── PromptConfig      # 提示词配置
├── ConversationRecord# 会话记录
├── TokenBlacklist    # JWT黑名单
├── WeixinBinding     # 微信绑定
├── WeixinAutoReplyRule # 微信自动回复规则
├── TaskAgentDefinition    # 代理类型定义
├── TaskAgentSession       # 代理运行实例
├── TaskItem          # 共享任务清单项
├── TaskEvent         # 任务事件审计
├── TaskTeam          # 代理团队
├── TaskTeamMember    # 团队成员
├── TaskMailboxMessage# 代理间消息
├── ProfileFact       # 用户画像事实
├── ProfileExtractionLog # 画像提取日志
```

#### 数据库迁移函数
`init_db()` 在表创建后自动执行以下迁移（向后兼容旧数据库）：

| 迁移函数 | 说明 |
|----------|------|
| `_migrate_conversation_record_metadata_column()` | metadata列迁移到record_metadata |
| `_migrate_plugin_columns()` | 补齐category/author/source/dependencies/installed_at |
| `_migrate_long_term_memory_user_id()` | 补齐user_id实现多租户隔离 |
| `_migrate_long_term_memory_enhancements()` | 补齐confidence/quality_score/archive_status |
| `_migrate_audit_log_columns()` | 补齐details/ip_address/created_at |
| `_migrate_skill_json_columns()` | YAML/文本配置迁移为合法JSON |
| `_migrate_conversation_columns()` | 补齐会话聚合字段并从历史回填 |
| `_migrate_user_profile_columns()` | 补齐头像/昵称/邮箱/画像数据 |
| `_migrate_task_runtime_columns()` | 补齐started_at/completed_at |
| `_migrate_scheduled_task_daily_columns()` | 补齐is_daily/cron_expression/weekdays/daily_time |
| `_migrate_short_term_memory_rich_fields()` | 补齐reasoning_content/tool_events |
| `_migrate_workspace_columns()` | 补齐workspace_id |
| `_migrate_profile_facts_table()` | 创建画像事实和提取日志表 |
| `_migrate_user_role_fk()` | 清理孤立user_roles记录 |
| `_migrate_model_configuration_new_params()` | 补齐frequency_penalty等模型参数 |
| `_migrate_permission_saved()` | 创建权限决策持久化表 |

---

### 3.11 配置模块 (config/)

| 文件 | 类/变量 | 说明 |
|------|---------|------|
| `settings.py` | `Settings` (BaseSettings) | 应用配置（环境变量/默认值），含API_KEY、DB_URL等 |
| `security.py` | `generate_csrf_token()`, `decode_access_token()` | 安全配置，CSRF Token、JWT编解码、Fernet加密 |
| `logging.py` | `init_logging()`, `generate_request_id()` | Loguru 日志初始化、request_id管理 |
| `config_loader.py` | | 配置加载器 |
| `config_manager.py` | | 配置管理器 |
| `experience_settings.py` | | 经验提取配置 |

#### 3.11.1 CLI 工具 (v1.5)

**文件**: [generate_api_key.py](file:///d:/代码/Open-AwA/backend/generate_api_key.py)

独立的访问密钥生成工具，用于在生产环境部署前手动配置 API Key：

| 命令 | 说明 |
|------|------|
| `python generate_api_key.py` | 生成新密钥并写入 .env.local，已有密钥时拒绝覆盖 |
| `python generate_api_key.py --show` | 仅生成并打印，不写入文件 |
| `python generate_api_key.py --force` | 强制替换已有密钥 |

**功能特性**:
- 自动检测误写为 `SECRET_KEY` 的密钥并修正
- 写入 `.env.local` 后自动设置文件权限为仅 owner 可读写 (`chmod 600`)
- 密钥格式: `sk-` 前缀 + 43 字符随机字符串

**关键配置项** (settings.py):

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `PROJECT_NAME` | Open-AwA AI Agent | 项目名称 |
| `VERSION` | 1.5.0 | 版本号 |
| `API_V1_STR` | /api | API前缀 |
| `DATABASE_URL` | sqlite:///./backend/openawa.db | 数据库连接 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 1440 | Token过期时间（分钟） |
| `SANDBOX_TIMEOUT` | 30 | 沙箱超时（秒） |
| `SANDBOX_MEMORY_LIMIT` | 512m | 沙箱内存限制 |
| `SANDBOX_BACKEND` | restricted_python | 沙箱后端 |
| `LOG_LEVEL` | INFO | 日志级别 |
| `LOG_SERIALIZE` | True | 结构化日志序列化 |
| `LOG_SERVICE_NAME` | openawa-backend | 日志服务名 |
| `LOG_DIR` | ./logs | 日志文件目录 |
| `LOG_FILE_ROTATION` | 10 MB | 日志轮转大小 |
| `LOG_FILE_RETENTION` | 30 days | 日志保留天数 |
| `VECTOR_DB_PATH` | backend/data/vector_db | ChromaDB持久化路径 |
| `TOOL_EXECUTION_CACHE_SIZE` | 256 | 工具执行缓存上限 |
| `MAX_TOOL_CALL_ROUNDS` | 12 | 工具调用最大轮次 |
| `MAX_ACTIVE_AGENT_TASKS` | 1000 | 活跃Agent任务容量上限 |
| `RECORD_SEMAPHORE_SIZE` | 20 | 并发记录信号量 |
| `SLOW_QUERY_THRESHOLD_MS` | 500 | 慢查询阈值（毫秒） |
| `OPENAWA_API_KEY` | auto | 全局API Key（v1.5新增，启动时自动生成并持久化） |
| `OPENAWA_OWNER_USERNAME` | admin | Owner用户名（v1.5新增） |
| `RATE_LIMIT_BACKEND` | memory | 限流后端（memory/db） |
| `TRUSTED_PROXIES` | 127.0.0.1,::1,10.0... | 受信代理IP/CIDR |
| `SSL_CERTFILE` | - | HTTPS证书路径（可选） |
| `SSL_KEYFILE` | - | HTTPS私钥路径（可选） |
| `USAGE_RETENTION_DAYS` | 365 | 用量保留天数 |
| `MAX_UPLOAD_SIZE` | 10MB | 文件上传大小上限 |

---

### 3.12 频道模块 (channels/)

**目录**: [backend/channels/](file:///d:/代码/Open-AwA/backend/channels/)

支持多渠道接入：

| 文件 | 平台 |
|------|------|
| `wecom.py` | 企业微信 |
| `dingtalk.py` | 钉钉 |
| `feishu.py` | 飞书 |
| `telegram.py` | Telegram |
| `discord.py` | Discord |
| `slack.py` | Slack |
| `matrix.py` | Matrix |
| `qq.py` | QQ |
| `imessage.py` | iMessage |
| `base.py` | 频道基类 |
| `manager.py` | 频道管理器 |

---

### 3.13 工作流模块 (workflow/)

**目录**: [backend/workflow/](file:///d:/代码/Open-AwA/backend/workflow/)

| 文件 | 类/函数 | 说明 |
|------|---------|------|
| `engine.py` | `WorkflowEngine` | 工作流执行引擎 |
| `parser.py` | | 工作流定义解析（YAML格式） |

**工作流支持**: 顺序执行、条件分支（if/else）、工具/技能/插件步骤编排

---

### 3.14 数据模型一览

#### 用户与认证

| 表 | 关键字段 | 说明 |
|-----|----------|------|
| `users` | id, username, password_hash, role, profile_data | 用户模型 |
| `login_devices` | user_id, device_type, ip_address, jti | 登录设备 |
| `token_blacklist` | jti, expires_at | JWT黑名单 |
| `login_rate_limits` | rate_limit_key, attempt_count, blocked_until | 登录限流 |

#### 技能与插件

| 表 | 关键字段 | 说明 |
|-----|----------|------|
| `skills` | id, name, version, config, enabled, usage_count | 技能模型 |
| `plugins` | id, name, version, enabled, config, category | 插件模型 |
| `skill_execution_logs` | skill_id, inputs, outputs, status, execution_time | 技能执行日志 |
| `plugin_execution_logs` | plugin_id, method, inputs, outputs, status | 插件执行日志 |
| `model_configurations` | provider, model, api_key, api_endpoint, selected_models | 模型配置（billing） |

#### 记忆与知识

| 表 | 关键字段 | 说明 |
|-----|----------|------|
| `short_term_memory` | session_id, workspace_id, role, content, reasoning_content, tool_events | 短期记忆（当前会话） |
| `long_term_memory` | user_id, workspace_id, content, embedding, confidence, quality_score | 长期记忆（向量检索） |
| `experience_memory` | user_id, experience_type, title, content, confidence | 经验记忆 |

#### 会话与记录

| 表 | 关键字段 | 说明 |
|-----|----------|------|
| `conversations` | session_id, user_id, title, message_count, deleted_at | 会话聚合 |
| `conversation_records` | session_id, user_id, node_type, llm_input, llm_output | 会话详细记录 |
| `behavior_logs` | user_id, action_type, details | 行为埋点日志 |
| `user_feedback` | session_id, message_id, rating, comment | 用户反馈 |

#### 任务与调度

| 表 | 关键字段 | 说明 |
|-----|----------|------|
| `scheduled_tasks` | user_id, title, prompt, cron_expression, task_type | 定时任务 |
| `scheduled_task_executions` | task_id, user_id, status, response | 定时任务执行记录 |
| `workflows` | user_id, name, definition, format | 工作流定义 |
| `workflow_executions` | workflow_id, user_id, status, input_payload, output_payload | 工作流执行记录 |
| `task_items` | task_id, list_id, subject, status, owner_agent_id | 共享任务清单项 |
| `task_agent_definitions` | name, scope, system_prompt, tools_json, permission_mode | 代理类型定义 |
| `task_agent_sessions` | agent_id, parent_session_id, agent_type, state, summary | 代理运行实例 |
| `task_teams` | team_id, name, lead_agent_id, state | 代理团队 |
| `task_team_members` | team_id, agent_id, name, role, state | 团队成员 |
| `task_mailbox_messages` | message_id, from_agent_id, to_agent_id, delivered | 代理间消息 |

#### 安全与权限

| 表 | 关键字段 | 说明 |
|-----|----------|------|
| `roles` | name, display_name, permissions | 角色定义 |
| `user_roles` | user_id, role_name | 用户角色关联 |
| `audit_logs` | user_id, action, resource, result, ip_address | 审计日志 |

#### 画像

| 表 | 关键字段 | 说明 |
|-----|----------|------|
| `profile_facts` | id, user_id, category, fact_key, fact_value, confidence | 用户画像事实 |
| `profile_extraction_logs` | user_id, trigger_type, facts_added, facts_updated | 画像提取日志 |

#### 微信

| 表 | 关键字段 | 说明 |
|-----|----------|------|
| `weixin_bindings` | user_id, weixin_account_id, token, binding_status | 微信绑定（token加密存储） |
| `weixin_auto_reply_rules` | user_id, match_type, match_pattern, reply_content | 自动回复规则 |

#### 其他

| 表 | 说明 |
|-----|------|
| `workspaces` | 智能体工作区 |
| `prompt_configs` | 提示词配置 |
| `experience_extraction_log` | 经验提取日志 |
| `event_log` | 事件日志（core/event_log.py定义） |
| `permission_saved` | 权限决策持久化（db/permission_models.py定义） |

---

## 四、前端模块详解

### 4.1 应用入口与路由

**入口文件**: [frontend/src/main.tsx](file:///d:/代码/Open-AwA/frontend/src/main.tsx)

**路由配置**: [App.tsx](file:///d:/代码/Open-AwA/frontend/src/App.tsx) 基于 React Router DOM 6

| 路由 | 组件 | 说明 |
|------|------|------|
| `/login` | `LoginPage` | 登录页面 |
| `/chat` | `ChatPage` | AI聊天主页 |
| `/communication` | `CommunicationPage` | 微信独立通讯页面 |
| `/dashboard` | `DashboardPage` | 仪表盘（行为统计+计费趋势） |
| `/settings` | `SettingsPage` | 系统设置 |
| `/skills` | `SkillsPage` | 技能管理 |
| `/skills/market` | `SkillMarketPage` | 技能市场 |
| `/plugins` | (重定向到 /plugins/manage) | 插件入口 |
| `/plugins/manage` | `PluginsPage` | 插件管理 |
| `/plugins/config/:pluginId` | `PluginConfigPage` | 插件配置 |
| `/plugins/marketplace` | `MarketplacePage` | 插件市场 |
| `/memory` | `MemoryPage` | 记忆管理 |
| `/billing` | `BillingPage` | 计费页面 |
| `/experiences` | `ExperiencePage` | 经验管理 |
| `/agents` | `AgentListPage` | 代理列表 |
| `/coding` | `CodingPage` | 编码辅助 |
| `/workspace` | `WorkspacePage` | 工作区管理 |
| `/scheduled-tasks` | `ScheduledTasksPage` | 定时任务 |
| `/search` | `LocalSearchPage` | 本地搜索 |
| `/test` | `TestPage` | 测试工具页 |
| `/tts` | `TtsPage` | 语音合成 |
| `/theme` | `ThemePage` | 主题设置 |
| `/inbox` | `InboxPage` | 收件箱 |
| `/user` | `UserCenterPage` | 用户中心 |
| `/user/profile` | `ProfileEditorPage` | 用户画像编辑 |

### 4.2 功能模块 (features/)

#### 聊天模块 (chat/)

| 文件 | 说明 |
|------|------|
| `ChatPage.tsx` | 聊天主页面：消息展示、输入、模型选择 |
| `CommunicationPage.tsx` | 微信通讯页面 |
| `types.ts` | 聊天模块类型定义 |
| `store/chatStore.ts` | 聊天状态管理（Zustand） |
| `hooks/useChatAutoScroll.ts` | 聊天自动滚动 |
| `hooks/useStreamBuffer.ts` | SSE流缓冲处理 |
| `hooks/useStreamExecutionState.ts` | 流式执行状态管理 |
| `hooks/useTaskPanelState.ts` | 任务面板状态 |
| `hooks/conversationHistory.ts` | 会话历史加载 |
| `utils/streamParser.ts` | SSE流解析器 |
| `utils/chatCache.ts` | 聊天缓存 |
| `utils/logParser.ts` | 日志解析 |
| `components/ChatInput.tsx` | 聊天输入框 |
| `components/ChatMessage.tsx` | 聊天消息渲染 |
| `components/MessageList.tsx` | 虚化消息列表 |
| `components/AssistantMarkdownContent.tsx` | Markdown内容渲染 |
| `components/ReasoningContent.tsx` | 思维链折叠展示 |
| `components/SubagentExecutionContainer.tsx` | 子代理执行容器 |
| `components/TaskPanel.tsx` | 任务面板 |
| `components/TaskTracker.tsx` | 任务追踪器 |
| `components/TodoPanel.tsx` | Todo面板 |
| `components/AgentSwitcher.tsx` | 代理切换器 |
| `components/CommandPalette.tsx` | 命令面板 |
| `components/ConversationSidebar.tsx` | 会话侧边栏 |

#### 设置模块 (settings/)

| 文件 | 说明 |
|------|------|
| `SettingsPage.tsx` | 设置主页（Tab切换，v1.5 重构为组件化架构） |
| `SettingsPage.utils.tsx` | 设置页共享工具函数（normalizeProviderBaseUrl等） |
| `modelsApi.ts` | 模型配置API |
| `envVarApi.ts` | 环境变量API |
| `MCPSettings.tsx` | MCP服务器管理 |
| `SecuritySettings.tsx` | 安全设置 |
| `PermissionSettings.tsx` | 权限设置 |
| `EnvVarSettings.tsx` | 环境变量设置 |
| components/ApiSettings/ | API密钥配置面板 |
| components/ModelsTab/ | 模型管理Tab（添加/表格/管理） |
| components/BillingTab/ | 计费Tab（价格编辑器/定价表格组） |
| components/PromptsTab/ | 提示词配置Tab |
| components/DataCollectionTab/ | 数据采集Tab（统计/导出/清理/预览） |
| components/DataRetentionTab/ | 数据保留策略Tab |
| components/GeneralSettings/ | 通用设置Tab |
| modals/CreateProviderModal/ | 创建供应商模态框 |
| modals/DeleteConfirmModal/ | 删除确认模态框 |
| modals/DeleteModelsModal/ | 批量删除模型模态框 |
| modals/ImportModelsModal/ | 导入模型配置模态框 |

#### 其他功能模块

| 模块 | 关键文件 | 说明 |
|------|----------|------|
| billing/ | `BillingPage.tsx`, `billingApi.ts`, `billing.ts` | 计费页面（成本统计卡片+趋势图+明细表） |
| dashboard/ | `DashboardPage.tsx`, `dashboard.ts` | 仪表盘 |
| skills/ | `SkillsPage.tsx`, `SkillModal.tsx`, `skillsApi.ts` | 技能管理 |
| plugins/ | `PluginsPage.tsx`, `PluginConfigPage.tsx`, `PluginDebugPanel.tsx` | 插件管理 |
| memory/ | `MemoryPage.tsx` | 记忆管理 |
| experiences/ | `ExperiencePage.tsx`, `experiencesApi.ts`, `fileExperiencesApi.ts` | 经验管理 |
| coding/ | `CodingPage.tsx`, `codingApi.ts`, `codingStore.ts` | 编码辅助（编辑器/文件树/Git/Diff） |
| agents/ | `AgentListPage.tsx`, `AgentCreateModal.tsx` | 代理管理 |
| scheduledTasks/ | `ScheduledTasksPage.tsx`, `CronExpressionBuilder.tsx` | 定时任务 |
| tts/ | `TtsPage.tsx`, `ttsApi.ts`, `ttsStore.ts` | 语音合成与声音克隆 |
| user/ | `UserCenterPage.tsx`, `ProfileEditorPage.tsx`, `ProfileRadarChart.tsx` | 用户中心与画像 |
| inbox/ | `InboxPage.tsx`, `inboxApi.ts`, `inboxStore.ts` | 收件箱 |
| workspace/ | `WorkspacePage.tsx`, `workspaceApi.ts`, `workspaceStore.ts` | 工作区管理 |

### 4.3 共享模块 (shared/)

| 目录 | 关键文件 | 说明 |
|------|----------|------|
| `api/` | `api.ts`, `client.ts` | 统一Axios封装（withCredentials, CSRF, interceptor） |
| `api/` | `mcpApi.ts`, `toolsApi.ts`, `securityApi.ts`, `profileApi.ts`, `subagentsApi.ts`, `taskRuntimeApi.ts` | 各类API封装 |
| `store/` | `authStore.ts`, `themeStore.ts`, `profileStore.ts` | 全局状态（认证/主题/用户画像） |
| `components/Sidebar/` | `Sidebar.tsx` | 全局侧边栏导航 |
| `components/ErrorBoundary/` | `ErrorBoundary.tsx` | 错误边界（降级UI+重试按钮） |
| `components/Toast/` | `Toast.tsx` | 全局Toast通知 |
| `components/ConfirmDialog/` | `ConfirmDialog.tsx` | 确认对话框 |
| `components/PageLayout/` | `PageLayout.tsx` | 页面布局容器 |
| `components/LoadingState/` | `LoadingState.tsx` | 加载状态 |
| `components/ui/` | Button, Card, Modal, Input, Textarea, Tabs, Skeleton, EmptyState | 基础UI组件库 |
| `components/ToolCallCard/` | `ToolCallCard.tsx` | 工具调用卡片 |
| `hooks/` | `useAppInitialization.ts`, `useFlexSearch.ts`, `useNotification.ts` | 全局Hooks |
| `types/` | `api.ts` | API类型定义 |
| `utils/` | `logger.ts`, `dateFormat.ts`, `preferenceSync.ts`, `safeStorage.ts` | 工具函数（v1.5: logger 增加 localStorage 环形缓冲区持久化） |
| `events/` | `billingEvents.ts` | 计费事件 |
| `perf/` | `metrics.ts` | 性能指标收集 |

### 4.4 状态管理

基于 **Zustand** 的状态管理方案：

| Store | 文件 | 管理状态 |
|-------|------|----------|
| `useAuthStore` | `shared/store/authStore.ts` | 用户认证（token仅存内存，不写入storage） |
| `useThemeStore` | `shared/store/themeStore.ts` | 白天/黑夜模式切换 |
| `useChatStore` | `features/chat/store/chatStore.ts` | 聊天消息列表、加载状态、会话ID |
| `useProfileStore` | `shared/store/profileStore.ts` | 用户画像 |
| `useCodingStore` | `features/coding/store/codingStore.ts` | 编码辅助状态 |
| `useInboxStore` | `features/inbox/store/inboxStore.ts` | 收件箱状态 |
| `useTtsStore` | `features/tts/store/ttsStore.ts` | 语音合成状态 |
| `useWorkspaceStore` | `features/workspace/store/workspaceStore.ts` | 工作区状态 |

**Store 选择器优化**: 使用 `shallow` 进行对象级别比较，避免不必要的重渲染。

### 4.5 国际化 (i18n/)

**目录**: [frontend/src/i18n/](file:///d:/代码/Open-AwA/frontend/src/i18n/)

支持语言：简体中文 (`zh-CN`)、英语 (`en-US`)、日语 (`ja-JP`)、俄语 (`ru-RU`)

---

## 五、API 接口参考

### 认证接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 用户登录（返回JWT+HttpOnly Cookie） |
| POST | `/api/auth/register` | 用户注册 |
| POST | `/api/auth/logout` | 用户登出（清除 Cookie） |
| GET | `/api/auth/me` | 获取当前用户信息 |
| GET | `/api/auth/csrf-token` | 获取 per-session CSRF Token |

### 聊天接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | 发送聊天消息 |
| POST | `/api/chat/stream` | SSE 流式聊天 |
| WS | `/api/chat/ws` | WebSocket 聊天 |
| POST | `/api/chat/cancel/{session_id}` | 取消指定会话的Agent任务 |
| GET | `/api/chat/history/{session_id}` | 获取会话历史消息 |

### 技能接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/skills` | 获取技能列表 |
| POST | `/api/skills` | 创建技能 |
| PUT | `/api/skills/{id}` | 更新技能 |
| DELETE | `/api/skills/{id}` | 删除技能 |
| POST | `/api/skills/{id}/execute` | 执行技能 |

### 插件接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/plugins` | 获取插件列表（含运行时状态） |
| POST | `/api/plugins` | 安装插件 |
| PUT | `/api/plugins/{id}` | 更新插件 |
| DELETE | `/api/plugins/{id}` | 卸载插件 |
| POST | `/api/plugins/{id}/enable` | 启用插件 |
| POST | `/api/plugins/{id}/disable` | 禁用插件 |
| POST | `/api/plugins/{id}/authorize` | 授权插件 |
| GET | `/api/plugins/discover` | 发现可用插件 |
| POST | `/api/plugins/import-url` | 从URL导入插件 |
| POST | `/api/plugins/{id}/hot-update` | 热更新插件 |
| POST | `/api/plugins/{id}/rollback` | 回滚插件 |

### 记忆接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/memory` | 获取记忆 |
| POST | `/api/memory` | 保存记忆 |
| DELETE | `/api/memory/{id}` | 删除记忆 |
| GET | `/api/memory/vector-search` | 向量语义搜索 |
| POST | `/api/memory/archive` | 归档长期记忆 |
| GET | `/api/memory/quality` | 查看记忆质量报告 |
| GET | `/api/memory/stats` | 查看记忆统计 |

### 计费接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/billing/usage` | 获取用量记录 |
| GET | `/api/billing/cost` | 获取成本统计 |
| GET | `/api/billing/models` | 获取模型价格列表 |
| PUT | `/api/billing/models/{id}` | 更新模型价格 |
| GET | `/api/billing/budget` | 获取预算配置 |
| PUT | `/api/billing/budget` | 设置预算 |

### MCP 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/mcp/servers` | 获取MCP Server列表 |
| POST | `/api/mcp/servers` | 添加MCP Server |
| POST | `/api/mcp/servers/{id}/connect` | 连接MCP Server |
| GET | `/api/mcp/tools` | 获取所有MCP工具 |
| POST | `/api/mcp/tools/call` | 调用MCP工具 |

### 工作流接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/workflows` | 获取工作流列表 |
| POST | `/api/workflows` | 创建工作流 |
| PUT | `/api/workflows/{id}` | 更新工作流 |
| DELETE | `/api/workflows/{id}` | 删除工作流 |
| POST | `/api/workflows/execute` | 执行工作流 |
| GET | `/api/workflows/executions/{execution_id}` | 查询工作流执行状态 |

### 定时任务接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/scheduled-tasks` | 获取定时任务列表 |
| POST | `/api/scheduled-tasks` | 创建定时任务 |
| PUT | `/api/scheduled-tasks/{id}` | 更新定时任务 |
| DELETE | `/api/scheduled-tasks/{id}` | 删除定时任务 |
| POST | `/api/scheduled-tasks/{id}/execute` | 手动执行定时任务 |

### 任务执行接口 (v1.5)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/tasks/execute` | 非交互式任务提交：一次性执行AI任务并返回完整结果，支持超时控制和Webhook回调 |

### 其他接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查（无需认证） |
| GET | `/metrics` | Prometheus指标（需认证） |
| GET | `/api/tools` | 获取可用工具列表 |
| GET | `/api/system/info` | 系统信息 |
| POST | `/api/coding/format` | 代码格式化 |
| POST | `/api/coding/lint` | 代码检查 |
| POST | `/api/tts/synthesize` | 语音合成 |
| POST | `/api/tts/clone-voice` | 声音克隆 |
| GET | `/api/inbox` | 获取收件箱消息 |

---

## 六、关键类与函数速查

### 后端核心类

| 类 | 文件 | 职责 |
|----|------|------|
| `AIAgent` | [core/agent.py](file:///d:/代码/Open-AwA/backend/core/agent.py) | Agent主控制器，管理理解→规划→执行→反馈全流程 |
| `ExecutionLayer` | [core/executor.py](file:///d:/代码/Open-AwA/backend/core/executor.py) | 执行层：LLM调用、工具分派、幂等缓存 |
| `PlanningLayer` | [core/planner.py](file:///d:/代码/Open-AwA/backend/core/planner.py) | 规划层：根据意图生成执行计划 |
| `ComprehensionLayer` | [core/comprehension.py](file:///d:/代码/Open-AwA/backend/core/comprehension.py) | 理解层：意图识别与实体提取 |
| `FeedbackLayer` | [core/feedback.py](file:///d:/代码/Open-AwA/backend/core/feedback.py) | 反馈层：结果评估与记忆更新 |
| `PluginManager` | [plugins/plugin_manager.py](file:///d:/代码/Open-AwA/backend/plugins/plugin_manager.py) | 插件管理器：加载/卸载/执行/发现 |
| `SkillEngine` | [skills/skill_engine.py](file:///d:/代码/Open-AwA/backend/skills/skill_engine.py) | 技能引擎：技能加载/执行/统计 |
| `PricingManager` | [billing/pricing_manager.py](file:///d:/代码/Open-AwA/backend/billing/pricing_manager.py) | 价格管理：模型配置CRUD、API端点解析 |
| `MemoryManager` | [memory/manager.py](file:///d:/代码/Open-AwA/backend/memory/manager.py) | 记忆管理：三层记忆统一入口 |
| `MCPManager` | [mcp/manager.py](file:///d:/代码/Open-AwA/backend/mcp/manager.py) | MCP管理器：线程安全单例、多Server连接 |
| `AutonomousModeManager` | [core/autonomous/manager.py](file:///d:/代码/Open-AwA/backend/core/autonomous/manager.py) | 自主模式管理器（v1.5增强）：四层安全洋葱（硬底线/工作区边界/网络策略/资源限制） |
| `HardDenyChecker` | [core/autonomous/hard_deny.py](file:///d:/代码/Open-AwA/backend/core/autonomous/hard_deny.py) | 硬底线检查器（v1.5新增）：禁止系统破坏命令和敏感路径访问 |
| `ResourceLimiter` | [core/autonomous/resource_limits.py](file:///d:/代码/Open-AwA/backend/core/autonomous/resource_limits.py) | 资源限制器（v1.5新增）：CPU/内存/时间硬限制 |
| `RBACManager` | [security/rbac.py](file:///d:/代码/Open-AwA/backend/security/rbac.py) | RBAC权限管理 |
| `WorkflowEngine` | [workflow/engine.py](file:///d:/代码/Open-AwA/backend/workflow/engine.py) | 工作流执行引擎 |
| `ContextCompressor` | [core/context/compressor.py](file:///d:/代码/Open-AwA/backend/core/context/compressor.py) | 上下文压缩器 |
| `TokenBudget` | [core/context/token_budget.py](file:///d:/代码/Open-AwA/backend/core/context/token_budget.py) | Token预算控制 |

### 前端核心组件

| 组件 | 文件 | 职责 |
|------|------|------|
| `ChatPage` | [features/chat/ChatPage.tsx](file:///d:/代码/Open-AwA/frontend/src/features/chat/ChatPage.tsx) | 聊天主页面 |
| `SettingsPage` | [features/settings/SettingsPage.tsx](file:///d:/代码/Open-AwA/frontend/src/features/settings/SettingsPage.tsx) | 设置页面 |
| `PluginsPage` | [features/plugins/PluginsPage.tsx](file:///d:/代码/Open-AwA/frontend/src/features/plugins/PluginsPage.tsx) | 插件管理页面 |
| `BillingPage` | [features/billing/BillingPage.tsx](file:///d:/代码/Open-AwA/frontend/src/features/billing/BillingPage.tsx) | 计费页面 |
| `ReasoningContent` | [features/chat/components/ReasoningContent.tsx](file:///d:/代码/Open-AwA/frontend/src/features/chat/components/ReasoningContent.tsx) | 思维链折叠展示 |
| `Sidebar` | [shared/components/Sidebar/Sidebar.tsx](file:///d:/代码/Open-AwA/frontend/src/shared/components/Sidebar/Sidebar.tsx) | 全局侧边栏导航 |
| `ErrorBoundary` | [shared/components/ErrorBoundary/ErrorBoundary.tsx](file:///d:/代码/Open-AwA/frontend/src/shared/components/ErrorBoundary/ErrorBoundary.tsx) | 错误边界组件 |

---

## 七、依赖关系

### 后端依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| fastapi | ~0.109.1 | Web框架 |
| uvicorn | ==0.27.0 | ASGI服务器 |
| sqlalchemy | ==2.0.25 | ORM |
| pydantic | >=2.6.0 | 数据验证 |
| pydantic-settings | >=2.1.0 | 配置管理 |
| python-jose | ~3.4.0 | JWT处理 |
| passlib | ==1.7.4 | 密码哈希（bcrypt） |
| websockets | ==12.0 | WebSocket支持 |
| loguru | ==0.7.2 | 结构化日志 |
| pyyaml | ==6.0.1 | YAML解析 |
| chromadb | ==0.4.22 | 向量数据库 |
| httpx | >=0.26.0 | HTTP客户端 |
| litellm | >=1.80.0 | 统一LLM调用（支持多供应商） |
| aiofiles | ==23.2.1 | 异步文件操作 |
| python-dotenv | ==1.0.0 | 环境变量加载 |
| click | ~8.1.0 | CLI工具 |
| slowapi | ~0.1.9 | 速率限制 |
| RestrictedPython | >=5.0 | 安全代码执行 |
| python-multipart | ~0.0.22 | 文件上传 |
| cryptography | (间接) | Fernet对称加密 |

### 前端依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| react | ^18.2.0 | UI框架 |
| react-dom | ^18.2.0 | React DOM渲染 |
| react-router-dom | ^6.22.0 | 路由管理 |
| react-markdown | ^10.1.0 | Markdown渲染 |
| react-virtuoso | ^4.18.7 | 虚拟列表 |
| recharts | ^2.12.0 | 图表库 |
| axios | ^1.6.7 | HTTP客户端 |
| zustand | ^4.5.0 | 状态管理 |
| @monaco-editor/react | ^4.6.0 | 代码编辑器 |
| katex | ^0.16.45 | 数学公式渲染 |
| rehype-katex | ^7.0.1 | remark KaTeX插件 |
| remark-math | ^6.0.0 | Markdown数学支持 |
| remark-gfm | ^4.0.1 | GitHub Flavored Markdown |
| highlight.js | ^11.11.1 | 代码高亮 |
| js-cookie | ^3.0.5 | Cookie操作 |
| lucide-react | ^1.8.0 | 图标库 |
| qrcode | ^1.5.4 | 二维码生成 |
| idb | ^8.0.3 | IndexedDB封装 |

### 开发依赖（前端）

| 依赖 | 用途 |
|------|------|
| vite | 构建工具 |
| typescript | 类型检查 |
| vitest | 单元测试 |
| @playwright/test | E2E测试 |
| @testing-library/react | React组件测试 |
| eslint | 代码检查 |
| jsdom | DOM模拟（测试） |
| rollup-plugin-visualizer | 构建包分析 |

### 模块间依赖关系图

```
main.py ──┬── api/routes/*      (路由层)
          ├── api/dependencies  (认证+DB注入)
          ├── api/schemas       (Pydantic模型)
          ├── billing/          (计费→db, config)
          ├── config/           (配置→settings)
          ├── security/         (安全→db, config)
          ├── core/agent.py     (核心引擎)
          │    ├── core/executor.py ──┬── core/litellm_adapter (LLM调用)
          │    │                      ├── mcp/manager          (MCP工具)
          │    │                      ├── plugins/             (插件执行)
          │    │                      ├── core/tool_registry   (工具注册)
          │    │                      └── core/builtin_tools/  (内置工具)
          │    ├── core/planner.py
          │    ├── core/comprehension.py
          │    ├── core/feedback.py
          │    ├── skills/           (技能引擎)
          │    ├── memory/           (记忆系统)
          │    └── workflow/         (工作流)
          ├── db/models.py          (数据模型)
          └── config/logging.py     (日志)
```

**关键依赖路径**:
- API Route → `get_current_user()` (dependencies) → JWT/Cookie/API Key 认证
- API Route → `get_db()` → `SessionLocal` → SQLAlchemy Engine
- Chat Route → `AIAgent.process()/process_stream()` → 四层核心流程
- Agent → `ExecutionLayer._call_llm_api()` → `litellm_adapter` → 外部LLM API
- Agent → `ExecutionLayer._execute_tool_call()` → 按前缀分派（plugin_/mcp_/builtin_/task_）
- Agent → `FeedbackLayer.update_memory()` → `MemoryManager` → `ShortTermMemory`

---

## 八、项目运行方式

### 8.1 环境要求

| 组件 | 版本要求 |
|------|----------|
| Python | >= 3.11 |
| Node.js | >= 18 |
| npm | >= 9+ |

### 8.2 后端启动

```powershell
# Windows PowerShell
cd d:\代码\Open-AwA\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dev.txt   # 开发依赖（含pytest）
python main.py
```

启动后可访问:
- API: `http://127.0.0.1:8000/`
- 健康检查: `http://127.0.0.1:8000/health`
- Prometheus指标: `http://127.0.0.1:8000/metrics` (需认证)

### 8.3 前端启动

```powershell
cd d:\代码\Open-AwA\frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

前端地址: `http://127.0.0.1:5173`

### 8.4 Docker 部署

项目根目录提供 `docker-compose.yml` 和 `Dockerfile`：

```bash
docker-compose up -d
```

### 8.5 生产环境配置

生产环境必须显式设置以下环境变量 (.env 或 .env.local)：

| 变量 | 说明 |
|------|------|
| `SECRET_KEY` | JWT签名密钥 + Fernet加密密钥派生源（**必须显式设置**） |
| `DATABASE_URL` | 数据库连接URL（生产建议PostgreSQL） |
| `ALLOWED_ORIGINS` | CORS白名单（逗号分隔） |
| `OPENAI_API_KEY` | OpenAI API密钥 |
| `ANTHROPIC_API_KEY` | Anthropic API密钥 |
| `DEEPSEEK_API_KEY` | DeepSeek API密钥 |
| `ENVIRONMENT` | 部署环境（development / production） |
| `DEBUG_MODE` | 调试模式开关（true/false，开发环境可开启） |

### 8.6 前端环境变量

| 变量 | 说明 |
|------|------|
| `VITE_ENABLE_DEV_AUTO_LOGIN` | 开发态自动登录（true/false） |
| `VITE_TEST_USERNAME` | 开发态自动登录用户名 |
| `VITE_TEST_PASSWORD` | 开发态自动登录密码 |

---

## 九、测试体系

### 9.1 后端测试

```powershell
cd backend

# 运行全部测试
python -m pytest

# 详细输出 + 覆盖率
pytest -v --cov

# 运行特定测试文件
pytest tests/test_agent_core.py -v
```

**测试目录**: [backend/tests/](file:///d:/代码/Open-AwA/backend/tests/)

**测试覆盖**（主要测试文件）:

| 测试文件 | 覆盖范围 |
|----------|----------|
| `test_agent_core.py` | Agent 核心流程(process/process_stream/魔法命令) |
| `test_executor_tool_calling.py` | 工具调用（plugin/mcp/builtin/task分发） |
| `test_planner.py` | 规划层（四种意图的plan生成） |
| `test_comprehension.py` | 理解层（意图识别/实体提取） |
| `test_billing_calculator.py` | 计费计算 |
| `test_pricing_manager.py` | 价格配置 |
| `test_budget_manager.py` | 预算管理 |
| `test_security_rbac.py` | RBAC权限 |
| `test_db_models.py` | 数据模型 |
| `test_litellm_adapter.py` | LiteLLM适配器 |
| `test_plugin_lifecycle.py` | 插件生命周期 |
| `test_skill_guidance.py` | 技能引导 |
| `test_memory_tools.py` | 记忆工具 |
| `test_task_runtime_*.py` | 任务运行时（Phase1-4） |
| `test_weixin_auto_reply.py` | 微信自动回复 |

### 9.2 前端测试

```powershell
cd frontend

# 单元测试
npm run test

# 覆盖率报告（阈值90%）
npm run test:coverage

# TypeScript 类型检查
npm run typecheck

# ESLint 代码检查
npm run lint

# 生产构建
npm run build

# Playwright E2E 测试
npm run e2e
```

**测试目录**: [frontend/src/__tests__/](file:///d:/代码/Open-AwA/frontend/src/__tests__/)

**E2E测试目录**: [frontend/tests/e2e/](file:///d:/代码/Open-AwA/frontend/tests/e2e/)

### 9.3 代码质量检查清单

| 检查项 | 命令 | 说明 |
|--------|------|------|
| 后端类型检查 | `mypy backend/ --ignore-missing-imports` | Python静态类型分析 |
| 后端安全扫描 | `bandit -r backend/` | 安全漏洞扫描 |
| 前端类型检查 | `tsc --noEmit` | TypeScript编译检查 |
| 前端代码检查 | `eslint "src/**/*.{ts,tsx}" --max-warnings=0` | ESLint零警告 |
| 构建验证 | `npm run build` | 生产构建验证 |
| 测试通过率 | `pytest -x --tb=short` / `vitest run` | 全部测试通过 |

### 9.4 预制CI检查项

项目配置了预制CI流水线（`.github/workflows/ci.yml`），包含：
1. 后端测试（pytest）
2. 前端测试（vitest）
3. 前端类型检查（tsc --noEmit）
4. 前端构建（npm run build）
5. 安全扫描（bandit + npm audit）

---

## 附录

### A. 项目版本历史

| 版本 | 日期 | 主要更新 |
|------|------|---------|
| 1.0 | 2026-03 | 项目初始化，核心聊天、Skill、插件系统 |
| 1.1 | 2026-03 | 记忆系统、行为分析、计费模块 |
| 1.2 | 2026-04 | 前端重构、微信集成、完整日志系统 |
| 1.3 | 2026-04 | 安全加固：HttpOnly Cookie、Fernet加密、MCP协议、CSRF防护、RBAC |
| 1.4 | 2026-04 | 插件全局单例、多轮对话上下文、插件运行时状态 |
| 1.5 | 2026-06 | 单用户API Key认证、Owner自动化、自主模式四层安全洋葱、任务执行API、SettingsPage重构、SSRF全面加固、前端日志持久化 |

### B. 文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 项目说明 | [README.md](file:///d:/代码/Open-AwA/README.md) | 项目总体介绍与快速开始 |
| 详细技术文档 | [PROJECT_DOCUMENTATION.md](file:///d:/代码/Open-AwA/PROJECT_DOCUMENTATION.md) | 完整技术文档 |
| 开发规范 | [AGENTS.md](file:///d:/代码/Open-AwA/AGENTS.md) | 项目开发规范与Git提交规则 |
| 后端架构 | [docs/架构/后端架构说明.md](file:///d:/代码/Open-AwA/docs/架构/后端架构说明.md) | 后端结构、核心模块详解 |
| 前端架构 | [docs/架构/前端架构说明.md](file:///d:/代码/Open-AwA/docs/架构/前端架构说明.md) | 前端页面、服务层、状态管理 |
| 部署指南 | [docs/指南/部署与运行说明.md](file:///d:/代码/Open-AwA/docs/指南/部署与运行说明.md) | 部署与运行 |
| 测试指南 | [docs/指南/测试说明.md](file:///d:/代码/Open-AwA/docs/指南/测试说明.md) | 测试策略 |
| 插件开发 | [docs/插件开发手册/](file:///d:/代码/Open-AwA/docs/插件开发手册/) | 插件开发手册（入门/API/最佳实践/FAQ） |
| 文档导航 | [docs/文档导航.md](file:///d:/代码/Open-AwA/docs/文档导航.md) | 全部文档入口索引 |

### C. 关键文件速查

| 用途 | 文件路径 |
|------|----------|
| 后端入口 | [backend/main.py](file:///d:/代码/Open-AwA/backend/main.py) |
| Agent主控制器 | [backend/core/agent.py](file:///d:/代码/Open-AwA/backend/core/agent.py) |
| 执行层 | [backend/core/executor.py](file:///d:/代码/Open-AwA/backend/core/executor.py) |
| 规划层 | [backend/core/planner.py](file:///d:/代码/Open-AwA/backend/core/planner.py) |
| 数据模型 | [backend/db/models.py](file:///d:/代码/Open-AwA/backend/db/models.py) |
| 认证依赖 | [backend/api/dependencies.py](file:///d:/代码/Open-AwA/backend/api/dependencies.py) |
| 安全配置 | [backend/config/security.py](file:///d:/代码/Open-AwA/backend/config/security.py) |
| 应用配置 | [backend/config/settings.py](file:///d:/代码/Open-AwA/backend/config/settings.py) |
| API Key生成工具 | [backend/generate_api_key.py](file:///d:/代码/Open-AwA/backend/generate_api_key.py) |
| Owner用户模块 | [backend/core/owner.py](file:///d:/代码/Open-AwA/backend/core/owner.py) |
| 自主模式配置 | [backend/core/autonomous/config.py](file:///d:/代码/Open-AwA/backend/core/autonomous/config.py) |
| 自主模式管理器 | [backend/core/autonomous/manager.py](file:///d:/代码/Open-AwA/backend/core/autonomous/manager.py) |
| 聊天路由 | [backend/api/routes/chat.py](file:///d:/代码/Open-AwA/backend/api/routes/chat.py) |
| 插件路由 | [backend/api/routes/plugins.py](file:///d:/代码/Open-AwA/backend/api/routes/plugins.py) |
| 插件管理器 | [backend/plugins/plugin_manager.py](file:///d:/代码/Open-AwA/backend/plugins/plugin_manager.py) |
| 任务执行API | [backend/api/routes/tasks.py](file:///d:/代码/Open-AwA/backend/api/routes/tasks.py) |
| LiteLLM适配 | [backend/core/litellm_adapter.py](file:///d:/代码/Open-AwA/backend/core/litellm_adapter.py) |
| 前端入口 | [frontend/src/main.tsx](file:///d:/代码/Open-AwA/frontend/src/main.tsx) |
| 前端路由 | [frontend/src/App.tsx](file:///d:/代码/Open-AwA/frontend/src/App.tsx) |
| 聊天页面 | [frontend/src/features/chat/ChatPage.tsx](file:///d:/代码/Open-AwA/frontend/src/features/chat/ChatPage.tsx) |
| 聊天状态 | [frontend/src/features/chat/store/chatStore.ts](file:///d:/代码/Open-AwA/frontend/src/features/chat/store/chatStore.ts) |
| 认证状态 | [frontend/src/shared/store/authStore.ts](file:///d:/代码/Open-AwA/frontend/src/shared/store/authStore.ts) |
| CSS Token | [frontend/src/styles/tokens.css](file:///d:/代码/Open-AwA/frontend/src/styles/tokens.css) |

---

> 本文档基于 Open-AwA v1.5 代码库生成，最后更新：2026-06-12

# Open-AwA 项目详细技术文档

## 项目概述

Open-AwA 是一个以 FastAPI 后端和 React 前端构建的 AI Agent 实验性平台。该项目定位为**AI智能体执行层网关**，旨在构建一个连接大模型与实际系统操作的执行层框架。项目当前已实现聊天调用、技能管理、插件管理、记忆管理、经验提取、提示词配置、行为统计、会话记录采集与计费模块等功能，并提供了一套可独立演进的插件生命周期与调试能力。

本项目采用**微内核+插件**的分层架构设计，遵循"从对话到执行"的范式转移趋势。系统的核心价值体现在四个维度：本地运行确保数据完全私有、安全可靠；自主执行能力使系统不仅能回答问题，还能执行实际操作；可扩展性通过 Skill、MCP、插件的灵活扩展实现；多层次安全防护机制保障系统安全可控。

---

## 一、系统架构

### 1.1 整体架构分层

系统采用六层架构设计，自上而下依次为：用户交互层负责 Web UI、CLI、API、IDE 插件等交互方式；API 网关层处理认证、限流、协议适配、负载均衡；核心引擎层实现 NLU、任务规划、工具调用、结果生成与记忆管理；技能执行层管理 Skill 生命周期、沙箱隔离、权限控制；资源抽象层提供文件系统、网络、进程、大模型抽象；系统资源层对接本地文件、系统命令、网络、API 服务。

### 1.2 后端架构详解

后端采用 FastAPI 组织 API 层，通过 SQLAlchemy 管理数据模型，核心模块分布于 core/、skills/、plugins/、billing/、memory/ 等目录。入口文件 main.py 负责创建 FastAPI 应用、配置 CORS、在 lifespan 中初始化数据库和计费模块、注册各类业务路由。

```
backend/
├── api/                        # FastAPI 路由、依赖与接口 schema
│   ├── routes/                 # 业务路由模块
│   │   ├── auth.py            # 认证路由
│   │   ├── chat.py           # 聊天路由
│   │   ├── skills.py         # 技能路由
│   │   ├── plugins.py        # 插件路由
│   │   ├── memory.py         # 记忆路由
│   │   ├── prompts.py        # 提示词路由
│   │   ├── behavior.py       # 行为分析路由
│   │   ├── experiences.py    # 经验路由
│   │   ├── conversation.py   # 会话记录路由
│   │   └── logs.py          # 日志查询路由
│   ├── services/             # 服务层
│   │   ├── chat_protocol.py  # 聊天协议
│   │   └── ws_manager.py     # WebSocket 管理
│   ├── dependencies.py      # 依赖注入
│   └── schemas.py           # Pydantic 数据模型
├── billing/                   # 计费模块
│   ├── routers/              # 计费路由
│   ├── tracker.py           # 用量追踪
│   ├── calculator.py         # 成本计算
│   ├── engine.py            # 计费引擎
│   ├── models.py            # 计费数据模型
│   ├── pricing_manager.py    # 价格配置管理
│   ├── budget_manager.py     # 预算管理
│   └── reporter.py          # 报表生成
├── config/                    # 配置模块
│   ├── settings.py          # 应用配置
│   ├── security.py          # 安全配置
│   ├── logging.py           # 日志配置
│   └── experience_settings.py # 经验配置
├── core/                      # 核心引擎
│   ├── agent.py             # AI 智能体主控制器
│   ├── comprehension.py     # 理解层：意图识别、实体提取
│   ├── planner.py           # 规划层：任务分解、策略制定
│   ├── executor.py          # 执行层：工具调用、结果处理
│   ├── feedback.py          # 反馈层：结果验证、状态更新
│   ├── model_service.py     # 模型服务协议适配
│   ├── metrics.py           # Prometheus 指标
│   ├── behavior_logger.py   # 行为日志
│   └── conversation_recorder.py # 会话记录
├── db/                        # 数据库
│   ├── models.py            # SQLAlchemy 模型
│   └── __init__.py           # 数据库初始化
├── memory/                     # 记忆系统
│   ├── manager.py           # 记忆管理器
│   └── experience_manager.py # 经验管理器
├── plugins/                    # 插件系统
│   ├── base_plugin.py       # 插件基类
│   ├── plugin_manager.py     # 插件管理器
│   ├── plugin_loader.py     # 插件加载器
│   ├── plugin_validator.py   # 插件验证器
│   ├── plugin_sandbox.py     # 插件沙箱
│   ├── plugin_lifecycle.py   # 插件生命周期
│   ├── hot_update_manager.py # 热更新管理
│   ├── extension_protocol.py # 扩展协议
│   ├── plugin_logger.py      # 插件日志
│   ├── registry/            # 插件注册表
│   ├── cli/                 # 插件 CLI
│   └── examples/            # 示例插件
├── security/                  # 安全模块
│   ├── permission.py        # 权限控制
│   ├── audit.py            # 审计日志
│   └── sandbox.py          # 沙箱隔离
├── skills/                     # 技能系统
│   ├── skill_engine.py     # Skill 引擎
│   ├── skill_registry.py   # Skill 注册表
│   ├── skill_loader.py     # Skill 加载器
│   ├── skill_validator.py  # Skill 验证器
│   ├── skill_executor.py   # Skill 执行器
│   ├── weixin_skill_adapter.py # 微信技能适配器
│   ├── built_in/           # 内置 Skill
│   │   └── file_manager.py # 文件管理器
│   └── configs/            # Skill 配置
└── tests/                     # 测试模块
```

### 1.3 前端架构详解

前端使用 React 18 + TypeScript + Vite 构建，采用功能模块分离的目录结构，通过 Zustand 管理状态，Axios 处理 API 请求，Recharts 展示图表数据。

```
frontend/
├── src/
│   ├── features/             # 功能模块（按领域拆分）
│   │   ├── chat/            # 聊天功能
│   │   │   ├── ChatPage.tsx
│   │   │   ├── CommunicationPage.tsx # 微信通讯页面
│   │   │   ├── components/
│   │   │   │   └── ReasoningContent.tsx # 思维链展示
│   │   │   └── store/
│   │   │       └── chatStore.ts
│   │   ├── dashboard/       # 仪表盘
│   │   ├── settings/       # 设置页面
│   │   │   └── modelsApi.ts # 模型配置 API
│   │   ├── skills/          # 技能管理
│   │   │   ├── SkillsPage.tsx
│   │   │   └── SkillModal.tsx
│   │   ├── plugins/         # 插件管理
│   │   │   ├── PluginsPage.tsx
│   │   │   ├── PluginDebugPanel.tsx
│   │   │   └── plugin-sdk.d.ts
│   │   ├── memory/          # 记忆管理
│   │   ├── experiences/     # 经验管理
│   │   │   ├── ExperiencePage.tsx
│   │   │   ├── experiencesApi.ts
│   │   │   └── fileExperiencesApi.ts
│   │   └── billing/         # 计费页面
│   │       ├── BillingPage.tsx
│   │       ├── billing.ts
│   │       └── billingApi.ts
│   ├── shared/              # 共享资源
│   │   ├── api/
│   │   │   └── api.ts      # 统一 API 封装
│   │   ├── components/
│   │   │   └── Sidebar/    # 侧边栏组件
│   │   ├── store/
│   │   │   ├── authStore.ts # 认证状态管理
│   │   │   └── themeStore.ts # 主题状态管理
│   │   ├── hooks/           # 自定义 Hooks
│   │   ├── types/
│   │   │   └── api.ts      # API 类型定义
│   │   └── utils/
│   │       └── logger.ts   # 统一日志工具
│   ├── __tests__/          # 单元测试
│   └── styles/
│       └── global.css      # 全局样式
└── tests/
    └── e2e/                # Playwright E2E 测试
```

---

## 二、核心功能模块

### 2.1 聊天与 Agent 主流程

聊天接口是系统的核心交互入口，支持 HTTP 和 WebSocket 两种通信方式。接口会构造上下文后调用 AIAgent.process()，Agent 主流程分为四个阶段：理解层(comprehension.py)负责意图识别和实体提取；规划层(planner.py)负责任务分解和策略制定；执行层(executor.py)负责工具调用和结果处理；反馈层(feedback.py)负责结果验证和状态更新。

当前实现的模型服务协议与链路治理具有以下特点：按 provider 生成不同的端点、请求头与请求载荷，避免把所有模型服务都按 OpenAI 协议调用；在上游模型请求中透传 X-Request-Id 与 X-Client-Ver；对客户端请求返回 X-Server-Ver 与 X-Version-Status，提供简单版本协商结果；为模型服务请求补充标准错误码与有限次重试；通过 metrics.py 输出简易 Prometheus 文本指标。

WebSocket 协议增强在保留最终完整消息的同时，新增了分段消息机制：每个分段包含 seq、total 与 checksum；最终完整消息继续返回 response 或 confirmation_result；工具执行会结合 idempotency_key 复用已完成结果，减少重复副作用。

### 2.2 Skill 系统

技能系统提供了 Skill 的标准化定义格式，支持 YAML 配置。Skill 路由支持技能的增删改查、执行、配置读取、上传解析与经验提取。核心实现位于 skill_engine.py、skill_validator.py、skill_loader.py、skill_registry.py。

当前已实现的技能侧能力包括：技能信息增删改查；技能执行；YAML 配置校验；上传文件解析；经验提取接口。系统还内置了文件管理器技能(file_manager.yaml)，并提供了微信技能适配器(weixin_skill_adapter.py)用于接入微信 Clawbot。

### 2.3 插件系统

插件系统采用热插拔架构，支持插件的发现、加载、验证、授权、热更新与回滚。核心模块包括 base_plugin.py 定义插件基类、extension_protocol.py 实现扩展协议、plugin_loader.py 负责插件加载、plugin_validator.py 验证插件合法性、plugin_sandbox.py 提供沙箱隔离、plugin_lifecycle.py 管理生命周期。

当前插件接口能力包括：插件列表与详情；数据库层安装记录；启用/禁用切换；执行插件方法；获取工具描述；权限查询、授权、撤销；日志读取；发现、上传、热更新、回滚。系统还提供了 CLI 工具(plugin_cli.py)和调试面板(PluginDebugPanel.tsx)用于插件开发调试。

### 2.4 记忆系统

后端把记忆分成三层：短期记忆(ShortTermMemory)管理当前会话上下文；长期记忆(LongTermMemory)持久化重要知识；经验记忆(ExperienceMemory)存储结构化经验。经验记忆还支持手动创建、更新、删除、搜索、手动触发提取和统计汇总。

相关模块包括 memory.py 路由层、experience_manager.py 经验管理器、experiences.py 经验路由。系统还支持基于文件的经验存储(fileExperiencesApi.ts)，经验内容可导出为 Markdown 文件。

### 2.5 计费系统

计费系统提供完整的用量计费能力，包括多模态计费、模型价格配置、预算控制、报表生成。核心模块包括 tracker.py 用量追踪器、pricing_manager.py 价格配置管理、budget_manager.py 预算管理、reporter.py 报表生成、engine.py 计费引擎、calculator.py 成本计算。

当前接口已经覆盖：用量查询；成本统计；模型价格查询与更新；预算配置；报表获取；保留期相关接口；模型配置相关接口。前端计费页面支持成本统计卡片、趋势图与饼图、用量明细表、CSV 导出按钮。

### 2.6 提示词配置

提示词接口已调整为兼容模式：/api/prompts/active 在无激活提示词时不再返回404，而是优先激活最近更新的提示词；若库中为空则自动创建默认 System Prompt 并返回。

### 2.7 行为分析与会话记录

行为分析模块提供统计接口、日志列表接口、手工记录行为接口。会话记录模块支持最近记录预览、JSONL 导出、历史清理、采集开关查询与更新。Agent/Executor/Feedback 链路均接入非阻塞记录埋点；设置页新增数据采集入口并可预览/导出/清理。

### 2.8 日志系统

项目已落地完整日志能力：后端统一 loguru 初始化与脱敏、HTTP 中间件注入并回传 X-Request-Id、关键链路结构化日志；前端新增统一 logger 与全局错误采集、axios 透传/记录 request_id；后端新增 /api/logs 查询与 /api/logs/export(JSONL) 导出接口。

### 2.9 微信集成

微信集成已通过 weixin_skill_adapter.py 接入 Skill 引擎，支持二维码登录（weixin-ilink）、通讯页面独立入口。系统支持二维码开始与状态轮询（wait/scaned/expired/confirmed/timeout）、登录成功自动回填 account_id/token/base_url，并提供取消扫码与退出登录接口联动。

---

## 三、数据模型

### 3.1 数据库实体

当前可确认的主要数据实体有：User 用户表；Skill 技能表；Plugin 插件表；SkillExecutionLog 技能执行日志；PluginExecutionLog 插件执行日志；ShortTermMemory 短期记忆；LongTermMemory 长期记忆；BehaviorLog 行为日志；ExperienceMemory 经验记忆；ExperienceExtractionLog 经验提取日志；PromptConfig 提示词配置；ConversationRecord 会话记录。

数据库初始化入口为 init_db 函数，位于 models.py 第 225-227 行。此外还包含一个会话记录表字段迁移逻辑用于兼容旧库。

### 3.2 数据库迁移

当本地 SQLite 旧库缺少 plugins 表新增字段（如 category/author/source/dependencies/installed_at）时，/api/plugins 会报 sqlite3.OperationalError: no such column。可在 init_db 中增加按列存在性执行 ALTER TABLE 的轻量迁移以兼容旧库。

---

## 四、技术实现细节

### 4.1 后端技术栈

后端采用 Python 3.11+ 构建，主要依赖包括：FastAPI 作为 Web 框架；SQLAlchemy 2.x 作为 ORM；pydantic-settings 管理配置；Loguru 输出日志；Uvicorn 运行服务；SQLite 作为默认存储（生产环境可切换为 PostgreSQL）。

### 4.2 前端技术栈

前端采用 React 18 + TypeScript 5，主要依赖包括：Vite 5 作为构建工具；React Router DOM 6 管理路由；Axios 处理 HTTP 请求；Zustand 管理状态；Recharts 绘制图表；Vitest 执行单元测试；Playwright 执行 E2E 测试。

### 4.3 前端测试配置

单元测试位于 src/__tests__/ 目录，使用 Vitest 运行。E2E 测试位于 tests/e2e/ 目录，使用 Playwright 运行。配置文件 playwright.config.ts 会在测试时自动启动后端 uvicorn main:app 和前端 npm run dev。

### 4.4 CI/CD 配置

项目配置了 GitHub Actions CI/CD 流水线，配置文件位于 .github/workflows/ci.yml。流水线包含测试与构建任务，确保代码质量。

---

## 五、前端页面与路由

### 5.1 页面清单

前端目前包含以下页面路由：/chat 聊天页面；/dashboard 仪表盘页面；/settings 设置页面；/skills 技能管理页面；/plugins 插件管理页面；/memory 记忆管理页面；/billing 计费页面；/communication 微信 Clawbot 独立通讯页面。

### 5.2 聊天页面

聊天页面(ChatPage.tsx)主要功能包括聊天输入、消息展示、模型选择、保存默认模型。依赖 chatStore 管理消息列表、加载状态、会话 ID、清空会话等操作。页面支持 Chain-of-Thought 折叠展示(ReasoningContent.tsx)。

### 5.3 仪表盘页面

仪表盘页面(DashboardPage.tsx)主要功能为行为统计与计费趋势展示。依赖 behaviorAPI 获取行为数据、billingAPI 获取计费数据。使用 Recharts 绘制趋势图表。

### 5.4 插件页面

插件页面(PluginsPage.tsx)主要功能包括展示插件列表、导入 zip 插件、启用/禁用、查看权限状态、授权与撤销权限、打开调试面板。调试面板(PluginDebugPanel.tsx)是插件开发的重要入口。

### 5.5 计费页面

计费页面(BillingPage.tsx)主要功能包括成本统计卡片、趋势图与饼图、用量明细表、CSV 导出按钮。页面调用 billingApi 获取计费数据并渲染图表。

### 5.6 主题切换

系统支持白天黑夜模式全局切换。themeStore.ts 实现了 html 级别的 .dark 类切换逻辑，支持 localStorage 持久化及系统偏好识别。Sidebar 底部包含主题切换按钮。

---

## 六、API 接口设计

### 6.1 主要 REST API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/auth/login | 用户登录 |
| GET | /api/auth/me | 获取当前用户信息 |
| POST | /api/chat | 发送消息 |
| WS | /api/chat/ws | WebSocket 聊天 |
| GET | /api/skills | 获取技能列表 |
| POST | /api/skills | 创建技能 |
| PUT | /api/skills/{id} | 更新技能 |
| DELETE | /api/skills/{id} | 删除技能 |
| POST | /api/skills/{id}/execute | 执行技能 |
| GET | /api/plugins | 获取插件列表 |
| POST | /api/plugins | 安装插件 |
| PUT | /api/plugins/{id} | 更新插件 |
| DELETE | /api/plugins/{id} | 卸载插件 |
| POST | /api/plugins/{id}/enable | 启用插件 |
| POST | /api/plugins/{id}/disable | 禁用插件 |
| POST | /api/plugins/{id}/authorize | 授权插件 |
| GET | /api/memory | 获取记忆 |
| POST | /api/memory | 保存记忆 |
| DELETE | /api/memory/{id} | 删除记忆 |
| GET | /api/prompts | 获取提示词配置 |
| PUT | /api/prompts | 更新提示词配置 |
| GET | /api/billing/usage | 获取用量记录 |
| GET | /api/billing/cost | 获取成本统计 |
| GET | /api/billing/models | 获取模型价格列表 |
| PUT | /api/billing/models/{id} | 更新模型价格 |
| GET | /api/billing/budget | 获取预算配置 |
| PUT | /api/billing/budget | 设置预算 |
| GET | /api/conversations | 获取会话记录 |
| GET | /api/conversations/export | 导出会话记录 |
| DELETE | /api/conversations | 清理会话记录 |
| GET | /api/logs | 查询日志 |
| GET | /api/logs/export | 导出日志 |
| GET | /api/behaviors | 获取行为统计 |

### 6.2 认证流程

认证依赖位于 dependencies.py。认证登录接口 /api/auth/login 使用 OAuth2PasswordRequestForm，前端必须以 application/x-www-form-urlencoded 发送 username/password；若用 JSON 会触发 422 并导致后续聊天请求因缺 token 出现 401。登录接口在校验用户名密码后生成 JWT token。

---

## 七、插件开发指南

### 7.1 插件结构

插件目录结构如下：manifest.json 定义插件元数据；src/index.py 插件入口文件；README.md 插件文档。插件必须继承 BasePlugin 类并实现必要方法。

### 7.2 插件生命周期

插件生命周期包括发现、加载、验证、安装、启用、执行、禁用、卸载等阶段。hot_update_manager.py 支持插件热更新与回滚。

### 7.3 示例插件

仓库包含三个示例插件：hello-world 演示基础插件开发；theme-switcher 演示主题切换功能；data-chart 演示数据图表功能。

---

## 八、部署与运维

### 8.1 环境要求

建议环境为 Python 3.11 或更高版本、Node.js 18 或更高版本、npm 9+。

### 8.2 后端启动

Windows PowerShell 环境启动后端：
```powershell
cd d:\代码\Open-AwA\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

启动后可访问 http://127.0.0.1:8000/ 和 http://127.0.0.1:8000/health。

### 8.3 前端启动

```powershell
cd d:\代码\Open-AwA\frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

默认前端地址为 http://127.0.0.1:5173。

### 8.4 生产环境配置

生产环境中应显式设置以下环境变量：SECRET_KEY；DATABASE_URL；ALLOWED_ORIGINS；各模型提供方 API Key。

---

## 九、未来规划

### 9.1 微信集成完善

扫码后微信绑定失败需独立处理，需要在 weixin wait 接口 confirmed 分支返回并保存 user_id、binding_status，并在前端展示绑定结果。

### 9.2 MCP 协议支持

系统尚未支持 Model Context Protocol 标准，未来计划实现 MCP 协议解析、MCP 客户端/服务端、工具发现、结构化工具调用、stdio/SSE 协议连接。

### 9.3 插件市场

当前插件市场按钮尚未实现功能，未来计划实现浏览/搜索/下载插件功能。

### 9.4 前端 UI 改进

未来计划实现完整的扁平化 UI 重构，包括去除边框/强阴影、完善白天/黑夜模式切换、统一极简风格。

### 9.5 Chain-of-Thought 改进

计划实现思维链折叠展示功能，支持展开/收起 Chain-of-Thought 内容。

### 9.6 多语言模型支持

未来计划扩展支持 DeepSeek、通义千问、Kimi、智谱AI 等多语言模型。

### 9.7 安全增强

计划实现多级沙箱隔离、RBAC 权限模型、完整审计日志、数据加密存储。

---

## 十、文档索引

### 10.1 项目入口文档

- 根 README：项目总体介绍

### 10.2 架构与运行文档

- deployment.md：本地开发与部署说明
- backend-architecture.md：后端结构、核心模块与数据层说明
- frontend-architecture.md：前端页面、服务层与状态管理说明
- testing.md：后端、前端、E2E 测试与建议检查项

### 10.3 插件开发文档

- plugin-developer-handbook/README.md：插件开发手册入口
- 1-getting-started.md：入门指南
- 2-api-reference.md：API 参考
- 3-best-practices.md：最佳实践
- 4-faq.md：常见问题

### 10.4 推荐阅读顺序

初次接手项目建议按以下顺序阅读文档：根 README；deployment.md；backend-architecture.md；frontend-architecture.md；testing.md；如果需要开发插件，再阅读插件开发手册。

---

## 十一、版本与更新

| 版本 | 日期 | 主要更新 |
|------|------|---------|
| 1.0 | 2026-03 | 项目初始化，实现核心聊天、Skill、插件系统 |
| 1.1 | 2026-03 | 新增记忆系统、行为分析、计费模块 |
| 1.2 | 2026-04 | 前端系统重构、微信集成、完整日志系统 |

---

## 十二、许可与贡献

项目采用 MIT 许可证开源。欢迎提交 Issue 和 Pull Request。

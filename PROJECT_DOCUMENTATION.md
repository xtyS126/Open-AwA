# Open-AwA 项目详细技术文档

## 项目概述

Open-AwA 是一个以 FastAPI 后端和 React 前端构建的 AI Agent 实验性平台。该项目定位为**AI智能体执行层网关**，旨在构建一个连接大模型与实际系统操作的执行层框架。项目当前已实现聊天调用、技能管理、插件管理、记忆管理、经验提取、提示词配置、行为统计、会话记录采集与计费模块等功能，并提供了一套可独立演进的插件生命周期与调试能力。v1.6 进一步扩展了子代理编排、IM 渠道适配、任务运行时、定时任务、角色系统、用户画像、工作区、编码助手、TTS、终端、自主运行模式、数据仪表盘、收件箱、插件市场等模块，前端页面路由扩展至 30+，后端路由模块扩展至 39 个。

本项目采用**微内核+插件**的分层架构设计，遵循"从对话到执行"的范式转移趋势。系统的核心价值体现在四个维度：本地运行确保数据完全私有、安全可靠；自主执行能力使系统不仅能回答问题，还能执行实际操作；可扩展性通过 Skill、MCP、插件、子代理的灵活扩展实现；多层次安全防护机制保障系统安全可控。

项目在 v1.3 版本中依据全面代码审核报告（code-review-report-2026-04-11-v4）完成了 40 项 Critical 和 58 项 Warning 级别问题的系统性修复，涵盖认证加固、敏感数据加密、插件沙箱安全、MCP 线程安全、前端 XSS 防护等关键领域。v1.5 引入 OPENAWA_API_KEY 强制校验机制与 SSRF 加固，并完成 P0+P1+P2 共 20+ 项性能优化。v1.6 完成子代理编排系统与插件市场落地。

---

## 一、系统架构

### 1.1 整体架构分层

系统采用六层架构设计，自上而下依次为：用户交互层负责 Web UI、CLI、API、IDE 插件等交互方式；API 网关层处理认证、限流、协议适配、负载均衡；核心引擎层实现 NLU、任务规划、工具调用、结果生成与记忆管理；技能执行层管理 Skill 生命周期、沙箱隔离、权限控制；资源抽象层提供文件系统、网络、进程、大模型抽象；系统资源层对接本地文件、系统命令、网络、API 服务。

### 1.2 后端架构详解

后端采用 FastAPI 组织 API 层，通过 SQLAlchemy 管理数据模型，核心模块分布于 core/、skills/、plugins/、billing/、memory/、mcp/、channels/、im/、workflow/ 等目录。入口文件 main.py 负责创建 FastAPI 应用、配置 CORS/CSRF/CSP/速率限制中间件、在 lifespan 中按职责拆分为四个独立启动步骤（基础设施、数据初始化、插件系统、后台任务）、注册 39 个业务路由模块。

```
backend/
├── api/                        # FastAPI 路由、依赖与接口 schema
│   ├── routes/                 # 业务路由模块（39 个）
│   │   ├── auth.py            # 认证路由
│   │   ├── chat.py           # 聊天路由
│   │   ├── skills.py         # 技能路由（含微信技能）
│   │   ├── plugins.py        # 插件路由
│   │   ├── memory.py         # 记忆路由
│   │   ├── workflows.py      # 工作流路由
│   │   ├── scheduled_tasks.py # 定时任务路由
│   │   ├── subagents.py      # 子代理路由
│   │   ├── coding.py         # 编码助手路由
│   │   ├── mcp.py            # MCP 协议路由
│   │   ├── models.py         # 模型配置路由
│   │   ├── tts.py            # TTS 路由
│   │   ├── roles.py          # 角色路由
│   │   ├── role_market.py    # 角色市场路由
│   │   ├── user.py           # 用户路由
│   │   ├── user_profile.py   # 用户画像路由
│   │   ├── workspace.py      # 工作区路由
│   │   ├── inbox.py          # 收件箱路由
│   │   ├── im.py             # IM 渠道路由
│   │   ├── terminal.py       # 终端路由
│   │   ├── data.py           # 数据仪表盘路由
│   │   ├── heartbeat.py      # 心跳路由
│   │   ├── tasks.py          # 任务路由
│   │   ├── task_runtime.py   # 任务运行时路由
│   │   ├── test_runner.py    # 测试运行器路由
│   │   ├── system.py         # 系统监控路由
│   │   ├── security.py       # 安全路由
│   │   ├── marketplace.py    # 插件市场路由
│   │   ├── weixin.py         # 微信路由
│   │   ├── tools.py          # 内置工具路由
│   │   ├── magic_commands.py # 魔法命令路由
│   │   ├── diary.py          # 日记路由
│   │   ├── prompts.py        # 提示词路由
│   │   ├── behavior.py       # 行为分析路由
│   │   ├── experiences.py    # 经验路由
│   │   ├── experience_files.py # 经验文件路由
│   │   ├── conversation.py   # 会话记录路由
│   │   └── logs.py          # 日志查询路由
│   ├── services/             # 服务层
│   │   ├── chat_protocol.py  # 聊天协议
│   │   ├── ws_manager.py     # WebSocket 管理
│   │   ├── weixin_auto_reply.py # 微信自动回复
│   │   └── diary_writer.py   # 日记写入
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
├── channels/                  # IM 渠道适配
│   ├── base.py              # 渠道基类
│   ├── manager.py           # 渠道管理器
│   ├── feishu.py            # 飞书
│   ├── telegram.py          # Telegram
│   ├── dingtalk.py          # 钉钉
│   ├── discord.py           # Discord
│   ├── slack.py             # Slack
│   ├── qq.py                # QQ
│   ├── matrix.py            # Matrix
│   ├── imessage.py          # iMessage
│   └── wecom.py             # 企业微信
├── config/                    # 配置模块
│   ├── settings.py          # 应用配置
│   ├── security.py          # 安全配置
│   ├── logging.py           # 日志配置
│   ├── config_loader.py     # 配置加载器
│   ├── config_manager.py    # 配置管理器
│   └── experience_settings.py # 经验配置
├── core/                      # 核心引擎
│   ├── agent.py             # AI 智能体主控制器
│   ├── agent_api.py         # Agent API
│   ├── comprehension.py     # 理解层：意图识别、实体提取
│   ├── planner.py           # 规划层：任务分解、策略制定
│   ├── executor.py          # 执行层：工具调用、结果处理
│   ├── feedback.py          # 反馈层：结果验证、状态更新
│   ├── model_service.py     # 模型服务协议适配
│   ├── litellm_adapter.py   # LiteLLM 统一网关适配
│   ├── metrics.py           # Prometheus 指标
│   ├── behavior_logger.py   # 行为日志
│   ├── conversation_recorder.py # 会话记录
│   ├── conversation_sessions.py # 会话会话管理
│   ├── compaction_manager.py # 上下文压缩
│   ├── command_executor.py  # 命令执行器
│   ├── checkpoint_store.py  # 检查点存储
│   ├── event_log.py         # 事件日志
│   ├── hook_manager.py      # Hook 管理器
│   ├── magic_commands.py    # 魔法命令
│   ├── owner.py             # Owner 用户管理
│   ├── permission_manager.py # 权限管理
│   ├── retry.py             # 重试机制
│   ├── role_engine.py       # 角色引擎
│   ├── rollback.py          # 回滚
│   ├── scheduled_task_manager.py # 定时任务管理器
│   ├── skill_guidance.py    # 技能引导
│   ├── subagent.py          # 子代理编排
│   ├── tool_approval.py     # 工具审批
│   ├── tool_entries.py      # 工具条目
│   ├── tool_registry.py     # 工具注册器
│   ├── weixin_utils.py      # 微信工具
│   ├── autonomous/          # 自主运行模式
│   │   ├── manager.py       # 自主管理器
│   │   ├── audit.py         # 审计
│   │   ├── checkpoint.py    # 检查点
│   │   ├── config.py        # 配置
│   │   └── hard_deny.py     # 硬拒绝规则
│   ├── builtin_tools/       # 内置工具
│   │   ├── manager.py       # 管理器
│   │   ├── notify.py        # 通知
│   │   └── todo.py          # 待办
│   ├── coding/              # 编码助手
│   │   ├── ast_search.py    # AST 搜索
│   │   ├── claude_code.py   # Claude Code 集成
│   │   ├── diff_engine.py   # Diff 引擎
│   │   ├── file_tree.py     # 文件树
│   │   ├── git_integration.py # Git 集成
│   │   ├── lsp_proxy.py     # LSP 代理
│   │   └── prompts.py       # 提示词
│   ├── context/             # 上下文管理
│   │   ├── compressor.py    # 压缩器
│   │   └── token_budget.py  # token 预算
│   ├── heartbeat/           # 心跳
│   │   └── engine.py        # 心跳引擎
│   ├── startup/             # 启动
│   │   ├── bootstrap.py     # 引导
│   │   ├── profiler.py      # 启动 profiler
│   │   └── tasks.py         # 启动任务
│   ├── task_runtime/        # 任务运行时
│   │   ├── facade.py        # 外观
│   │   ├── registry.py      # 注册器
│   │   ├── runners.py       # 运行器
│   │   ├── sessions.py      # 会话
│   │   └── task_store.py    # 任务存储
│   └── workspace/           # 工作区
│       └── manager.py       # 工作区管理器
├── data/                      # 数据收集
│   └── collector.py         # 数据收集器
├── db/                        # 数据库
│   ├── models.py            # SQLAlchemy 模型
│   ├── permission_models.py # 权限模型
│   └── __init__.py           # 数据库初始化
├── im/                        # IM 适配器
│   ├── adapter_base.py      # 适配器基类
│   ├── feishu_adapter.py    # 飞书适配器
│   ├── telegram_adapter.py  # Telegram 适配器
│   └── router.py            # IM 路由
├── mcp/                       # MCP 协议模块
│   ├── client.py            # MCP 客户端
│   ├── manager.py           # MCP 管理器（线程安全单例）
│   ├── protocol.py          # JSON-RPC 2.0 协议构建
│   ├── transport.py         # Stdio/SSE 传输层
│   ├── sandbox.py           # MCP 沙箱
│   ├── config_store.py      # 配置存储
│   └── types.py             # 类型定义
├── memory/                     # 记忆系统
│   ├── manager.py           # 记忆管理器
│   ├── experience_manager.py # 经验管理器
│   ├── vector_store_manager.py # 向量存储管理器
│   ├── working_memory.py    # 工作内存
│   ├── hybrid_search.py     # 混合检索
│   ├── bm25_retriever.py    # BM25 检索器
│   ├── auto_dream.py        # 自动梦境
│   ├── daily_log.py         # 每日日志
│   └── chroma_telemetry.py  # Chroma 遥测
├── plugins/                    # 插件系统
│   ├── base_plugin.py       # 插件基类
│   ├── plugin_instance.py   # 插件管理器全局单例
│   ├── plugin_manager.py     # 插件管理器
│   ├── plugin_loader.py     # 插件加载器
│   ├── plugin_validator.py   # 插件验证器
│   ├── plugin_sandbox.py     # 插件沙箱
│   ├── plugin_lifecycle.py   # 插件生命周期
│   ├── plugin_context.py    # 插件上下文
│   ├── plugin_logger.py      # 插件日志
│   ├── hot_update_manager.py # 热更新管理
│   ├── extension_protocol.py # 扩展协议
│   ├── event_bus.py         # 事件总线
│   ├── dependency_resolver.py # 依赖解析
│   ├── command_plugin.py    # 命令插件
│   ├── schema_validator.py  # Schema 验证器
│   ├── registry/            # 插件注册表
│   ├── marketplace/         # 插件市场
│   ├── cli/                 # 插件 CLI
│   └── examples/            # 示例插件
├── security/                  # 安全模块
│   ├── rbac.py              # 基于角色的访问控制
│   ├── permission.py        # 权限控制
│   ├── audit.py            # 审计日志（异步写入+失败告警）
│   ├── sandbox.py          # 沙箱隔离
│   ├── pii.py              # PII 脱敏
│   ├── backends.py         # 沙箱后端
│   ├── backup_trust.py     # 备份信任
│   ├── unified_access.py   # 统一访问控制
│   └── rate_limit_store.py # 速率限制存储
├── skills/                     # 技能系统
│   ├── skill_engine.py     # Skill 引擎
│   ├── skill_registry.py   # Skill 注册表
│   ├── skill_loader.py     # Skill 加载器
│   ├── skill_validator.py  # Skill 验证器
│   ├── skill_executor.py   # Skill 执行器
│   ├── skill_orchestrator.py # Skill 编排器
│   ├── skill_matcher.py    # Skill 匹配器
│   ├── skill_security.py   # Skill 安全
│   ├── skill_md_loader.py  # Skill MD 加载器
│   ├── pool_manager.py     # 池管理器
│   ├── version_manager.py  # 版本管理器
│   ├── experience_extractor.py # 经验提取器
│   ├── weixin_skill_adapter.py # 微信技能适配器
│   ├── builtin/            # 内置 Skill
│   │   ├── browser_cdp.py  # 浏览器 CDP
│   │   ├── cron.py         # 定时
│   │   ├── docx.py         # DOCX
│   │   ├── file_reader.py  # 文件读取
│   │   ├── guidance.py     # 引导
│   │   ├── himalaya.py     # 邮件
│   │   ├── news.py         # 新闻
│   │   ├── pdf.py          # PDF
│   │   ├── pptx.py         # PPTX
│   │   └── xlsx.py         # XLSX
│   └── configs/            # Skill 配置
├── tools/                     # 内置工具注册器
│   └── registry.py
├── workflow/                  # 工作流引擎
│   ├── engine.py            # 工作流引擎
│   └── parser.py            # 工作流解析器
└── tests/                     # 测试模块
```

### 1.3 前端架构详解

前端使用 React 18 + TypeScript + Vite 构建，采用功能模块分离的目录结构（`features/` 按领域拆分，`shared/` 放共享资源），通过 Zustand 管理状态，Axios 处理 API 请求，Recharts 展示图表数据。

```
frontend/
├── src/
│   ├── features/             # 功能模块（按领域拆分）
│   │   ├── auth/            # 认证（LoginPage）
│   │   ├── chat/            # 聊天功能
│   │   │   ├── ChatPage.tsx
│   │   │   ├── CommunicationPage.tsx # 微信通讯页面
│   │   │   ├── components/   # 聊天组件（ChatInput、ChatMessage、MessageList、ReasoningContent、TaskPanel、PermissionDialog、SubagentExecutionContainer 等）
│   │   │   ├── hooks/       # 自定义 Hooks（useChatStream、useChatAutoScroll、useConversationHistory 等）
│   │   │   ├── store/
│   │   │   │   └── chatStore.ts
│   │   │   ├── utils/       # 工具（streamParser、logParser、executionMeta 等）
│   │   │   └── wechat-module/ # 微信配置模块
│   │   ├── dashboard/       # 仪表盘
│   │   ├── settings/       # 设置页面（多 Tab）
│   │   │   ├── components/  # 按 Tab 拆分（ApiSettings、BillingTab、DataCollectionTab、ModelsTab、PromptsTab 等）
│   │   │   ├── containers/  # Tab 容器
│   │   │   ├── modals/      # 模态框（CreateProviderModal、DeleteModelsModal、ImportModelsModal 等）
│   │   │   ├── hooks/       # 设置相关 hooks
│   │   │   └── modelsApi.ts # 模型配置 API
│   │   ├── skills/          # 技能管理（SkillsPage、SkillModal、SkillMarketPage）
│   │   ├── plugins/         # 插件管理（PluginsPage、PluginConfigPage、MarketplacePage、PluginDebugPanel）
│   │   ├── memory/          # 记忆管理
│   │   ├── experiences/     # 经验管理（ExperiencePage、experiencesApi、fileExperiencesApi）
│   │   ├── billing/         # 计费页面（BillingPage、billingApi）
│   │   ├── coding/          # 编码助手（CodingPage、文件树、编辑器、Diff、Git、终端）
│   │   ├── scheduledTasks/  # 定时任务（日历视图、cron 构建器、任务模板）
│   │   ├── tts/             # TTS 语音合成（语音库、语音克隆、音频播放）
│   │   ├── user/            # 用户中心（画像仪表盘、置信度、时间线、雷达图）
│   │   ├── workspace/       # 工作区
│   │   ├── inbox/           # 收件箱
│   │   ├── agents/          # 子代理列表
│   │   ├── roles/           # 角色管理
│   │   ├── marketplace/     # 角色市场
│   │   ├── data/            # 数据仪表盘
│   │   ├── im/              # IM 渠道管理
│   │   ├── test/            # 测试页
│   │   ├── theme/           # 主题页
│   │   └── search/          # 本地搜索
│   ├── shared/              # 共享资源
│   │   ├── api/             # API 封装（api、client、dataApi、imApi、mcpApi、profileApi、rolesApi、securityApi、subagentsApi、terminalApi、toolsApi 等）
│   │   ├── components/      # 共享组件（Sidebar、ErrorBoundary、Toast、ConfirmDialog、PageLayout、ToolCallCard 等）
│   │   │   └── ui/          # UI 基础组件库（Avatar、Badge、Button、Card、Input、Modal、Skeleton、Tabs、Tooltip 等）
│   │   ├── store/           # 全局 store（authStore、themeStore、profileStore）
│   │   ├── hooks/           # 自定义 Hooks（useAppInitialization、useFlexSearch、useNotification）
│   │   ├── types/           # 类型定义（api、role）
│   │   ├── utils/           # 工具（logger、dateFormat、errorMessages、safeStorage、preferenceSync）
│   │   ├── events/          # 事件（billingEvents）
│   │   └── perf/            # 性能埋点（metrics）
│   ├── __tests__/          # 应用级单测（App.test、main.test）
│   └── styles/
│       ├── global.css      # 全局样式
│       └── tokens.css      # 设计令牌
└── tests/
    └── e2e/                # Playwright E2E 测试（auth、chat、settings）
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

插件系统采用热插拔架构，通过全局单例模式管理插件管理器（`plugins.plugin_instance`），支持插件的发现、加载、验证、授权、热更新与回滚。核心模块包括 base_plugin.py 定义插件基类、extension_protocol.py 实现扩展协议、plugin_loader.py 负责插件加载、plugin_validator.py 验证插件合法性、plugin_sandbox.py 提供沙箱隔离、plugin_lifecycle.py 管理生命周期、plugin_instance.py 管理全局单例。

应用启动时，lifespan 初始化 PluginManager 全局单例，自动发现插件并加载数据库中已启用的插件。所有路由和 Agent 通过 `plugin_instance.get()` 获取同一实例，保证运行时状态一致。

插件安装、卸载、启用、禁用操作同步更新数据库记录和运行时状态：安装后自动 discover + load；卸载前先 unload 运行时实例；启用/禁用同步 load/unload。插件列表接口返回数据库记录并附带运行时加载状态。

当前插件接口能力包括：插件列表与详情（含运行时状态）；插件发现（GET /plugins/discover）；数据库层安装记录；启用/禁用切换（同步运行时加载/卸载）；执行插件方法；获取工具描述；权限查询、授权、撤销；日志读取；发现、上传、热更新、回滚；配置 schema 查询、保存、重置、导出。系统还提供了 CLI 工具(plugin_cli.py)和调试面板(PluginDebugPanel.tsx)用于插件开发调试。

### 2.4 记忆与上下文系统

后端把记忆分成三层：短期记忆(ShortTermMemory)管理当前会话上下文；长期记忆(LongTermMemory)持久化重要知识；经验记忆(ExperienceMemory)存储结构化经验。经验记忆还支持手动创建、更新、删除、搜索、手动触发提取和统计汇总。

**多轮对话上下文机制**：Agent 初始化时创建 MemoryManager 并注入到 FeedbackLayer。每次处理用户请求时，自动从 ShortTermMemory 中按 session_id 检索最近对话记录，作为 `conversation_history` 注入到 LLM 调用的 messages 数组中。请求完成后，FeedbackLayer 自动将当前轮次的 user/assistant 消息存入 ShortTermMemory。此机制同时适用于前端聊天和微信聊天，不同渠道通过不同的 session_id 隔离上下文（前端使用前端传入的 sessionId，微信使用 `weixin:auto:{account_id}:{from_user_id}` 格式）。

前端 ChatPage 页面挂载或会话切换时自动从后端加载历史消息，支持页面刷新后恢复对话上下文。

相关模块包括 memory.py 路由层、experience_manager.py 经验管理器、experiences.py 经验路由、memory/manager.py 记忆管理器。系统还支持基于文件的经验存储(fileExperiencesApi.ts)，经验内容可导出为 Markdown 文件。

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

微信集成已通过 weixin_skill_adapter.py 接入 Skill 引擎，支持二维码登录（weixin-ilink）、通讯页面独立入口。系统支持二维码开始与状态轮询（wait/scaned/expired/confirmed/timeout）、登录成功自动回填 account_id/token/base_url，并提供取消扫码与退出登录接口联动。微信绑定令牌已改为 Fernet 对称加密存储，数据库中仅保存 `enc:` 前缀的密文。

### 2.10 MCP 协议支持

MCP（Model Context Protocol）模块已实现完整的客户端协议栈，位于 backend/mcp/ 目录。支持 Stdio（子进程 stdin/stdout）和 SSE（HTTP POST）两种传输方式，提供工具发现（tools/list）、工具调用（tools/call）和资源访问（resources/list、resources/read）能力。MCPManager 采用线程安全单例模式管理多 Server 连接，MCPProtocol 生成标准 JSON-RPC 2.0 请求。传输层基类声明了统一的 `send_and_receive()` 接口，SSE 和 Stdio 各自实现，避免跨模式调用不兼容。Stdio transport 会自动启动后台任务读取子进程 stderr，防止缓冲区满导致进程假死。

### 2.11 安全体系

项目已落地多层安全防护：

- **认证与鉴权**：JWT 令牌通过 HttpOnly Cookie 传递，前端不再在 sessionStorage/localStorage 中存储令牌；登录接口内置速率限制（5分钟内最多5次失败尝试，超限封锁15分钟）；密码哈希使用 bcrypt rounds=12 / pbkdf2 rounds=600,000。
- **CSRF 防护**：后端中间件对变更类请求强制验证 Double Submit Cookie；前端 axios 拦截器自动从 Cookie 读取 csrf_token 并注入 X-CSRF-Token 请求头。
- **RBAC 权限模型**：内置 admin/developer/viewer 三种角色，权限检查通过 RBACManager 集中管理，所有管理接口要求 admin 角色。
- **审计日志**：AuditLogger 异步写入审计记录，写入失败时记录 Loguru 告警而非静默丢弃。
- **敏感数据加密**：微信令牌、API 密钥等敏感字段使用独立的 `ENCRYPTION_KEY` 进行 Fernet 对称加密；JWT 与 CSRF 分别使用 `JWT_SECRET_KEY` 和 `CSRF_SECRET_KEY`。
- **插件安全**：ZIP 解压逐文件校验路径并阻止 symlink；远程下载使用 IP Pinning 防止 DNS Rebinding；AST 静态扫描检测危险导入。
- **OPENAWA_API_KEY 强制校验**：v1.5 引入，未配置时拒绝启动，CLI 工具 generate_api_key.py 写入 .env.local 后立即 chmod 600 消除 TOCTOU 窗口。
- **SSRF 加固**：BASE_URL 校验阻断内网/本地/链路本地 IP 地址。
- **日志脱敏**：敏感字段在日志输出前自动替换为脱敏占位符。

### 2.12 子代理编排系统

v1.6 引入的子代理（Subagent）编排系统位于 backend/core/subagent.py 与 backend/api/routes/subagents.py，提供三级隔离（进程级/协程级/会话级）、生命周期状态机（created/running/paused/completed/failed/cancelled）、资源限制（最大并发数、超时、内存上限）与编排器（Orchestrator）能力。支持子代理并行执行、消息合并、错误事件回调，前端 SubagentContainer 组件已对接 /api/subagents 系列接口。

### 2.13 IM 渠道适配

v1.6 引入的 IM 渠道适配层位于 backend/channels/ 与 backend/im/ 目录，支持飞书、Telegram、钉钉、企业微信、Slack、Discord、QQ、微信、邮件等 9 个渠道的统一接入。每个渠道实现独立的适配器（Adapter）与 Webhook 处理器，通过 /api/im 统一路由对外暴露。渠道配置支持在线管理，消息双向同步。

### 2.14 任务运行时与定时任务

任务运行时（Task Runtime）位于 backend/core/task_runtime/ 与 backend/api/routes/task_runtime.py，提供长时任务的创建、调度、状态追踪、结果回收能力。定时任务（Scheduled Tasks）位于 backend/api/routes/scheduled_tasks.py，基于 cron 表达式调度，支持任务暂停/恢复/删除/手动触发。前端 ScheduledTasksPage 与 TaskRuntimePage 已对接相应接口。

### 2.15 角色系统与用户画像

角色系统（Roles）位于 backend/api/routes/roles.py 与 role_market.py，支持角色的增删改查、市场共享、应用与卸载。用户画像（User Profile）位于 backend/api/routes/user_profile.py，记录用户偏好、技能标签、历史行为特征，用于个性化推荐与上下文注入。

### 2.16 工作区与编码助手

工作区（Workspace）位于 backend/api/routes/workspace.py 与 backend/core/workspace/，提供项目级文件管理、多项目切换、工作区隔离能力。编码助手（Coding Assistant）位于 backend/api/routes/coding.py 与 backend/core/coding/，集成代码补全、重构建议、错误诊断、测试生成等能力，前端 CodingPage 已对接。

### 2.17 TTS、终端与自主运行模式

TTS 模块位于 backend/api/routes/tts.py，支持文本转语音输出。终端（Terminal）位于 backend/api/routes/terminal.py，提供 Web 终端能力（受限沙箱内执行）。自主运行模式（Autonomous）位于 backend/core/autonomous/，支持 Agent 在无用户输入的情况下自主规划并执行任务链。

### 2.18 数据仪表盘、收件箱与插件市场

数据仪表盘（Data Dashboard）位于 backend/api/routes/data.py，聚合展示用量、计费、行为、性能等多维指标。收件箱（Inbox）位于 backend/api/routes/inbox.py，统一收集系统通知、任务结果、子代理消息。插件市场（Marketplace）位于 backend/plugins/marketplace/ 与 backend/api/routes/marketplace.py，提供插件浏览、搜索、详情、安装能力（详见 9.3 节）。

---

## 三、数据模型

### 3.1 数据库实体

当前可确认的主要数据实体有：User 用户表；Skill 技能表；Plugin 插件表；SkillExecutionLog 技能执行日志；PluginExecutionLog 插件执行日志；ShortTermMemory 短期记忆；LongTermMemory 长期记忆；BehaviorLog 行为日志；ExperienceMemory 经验记忆；ExperienceExtractionLog 经验提取日志；PromptConfig 提示词配置；ConversationRecord 会话记录；WeixinBinding 微信绑定表（令牌加密存储）；AuditLog 审计日志表；Role 角色表；UserRole 用户角色关联表。

数据库初始化入口为 init_db 函数，位于 models.py 第 225-227 行。此外还包含一个会话记录表字段迁移逻辑用于兼容旧库。

### 3.2 数据库迁移

当本地 SQLite 旧库缺少 plugins 表新增字段（如 category/author/source/dependencies/installed_at）时，/api/plugins 会报 sqlite3.OperationalError: no such column。可在 init_db 中增加按列存在性执行 ALTER TABLE 的轻量迁移以兼容旧库。

---

## 四、技术实现细节

### 4.1 后端技术栈

后端采用 Python 3.11+ 构建，主要依赖包括：FastAPI 作为 Web 框架；SQLAlchemy 2.x 作为 ORM；pydantic-settings 管理配置；Loguru 输出日志；Uvicorn 运行服务；SQLite 作为默认存储（生产环境可切换为 PostgreSQL）；cryptography（Fernet）用于敏感数据对称加密；passlib 提供 bcrypt/pbkdf2 密码哈希。

### 4.2 前端技术栈

前端采用 React 18 + TypeScript 5，主要依赖包括：Vite 5 作为构建工具；React Router DOM 6 管理路由；Axios 处理 HTTP 请求（withCredentials 启用 Cookie 自动携带）；Zustand 管理状态（认证信息仅存内存，不再写入 sessionStorage）；js-cookie 读取 CSRF 令牌；Recharts 绘制图表；Vitest 执行单元测试；Playwright 执行 E2E 测试。

### 4.3 前端测试配置

单元测试位于 src/__tests__/ 目录，使用 Vitest 运行。E2E 测试位于 tests/e2e/ 目录，使用 Playwright 运行。配置文件 playwright.config.ts 会在测试时自动启动后端 uvicorn main:app 和前端 npm run dev。

### 4.4 CI/CD 配置

项目配置了 GitHub Actions CI/CD 流水线，配置文件位于 .github/workflows/ci.yml。流水线包含测试与构建任务，确保代码质量。

---

## 五、前端页面与路由

### 5.1 页面清单

前端目前包含以下页面路由（共 30+ 个）：/login 登录页；/chat 聊天页面（支持 /chat/:conversationId 会话切换）；/dashboard 仪表盘页面；/settings 设置页面（含模型/计费/数据采集/数据保留/外观/通用/MCP/权限/安全/环境变量/提示词等 Tab）；/skills 技能管理页面；/skills/market 技能市场；/scheduled-tasks 定时任务；/plugins/manage 插件管理页面；/plugins/config/:pluginId 插件配置；/plugins/marketplace 插件市场；/memory 记忆管理页面；/experience 经验记忆；/billing 计费页面；/communication 微信 Clawbot 独立通讯页面；/user 用户中心；/profile/edit 用户画像编辑；/test 测试页；/workspace 工作区；/coding 编码助手；/inbox 收件箱；/agents 子代理列表；/roles 角色管理；/role-market 角色市场；/data 数据仪表盘；/tts TTS 语音合成；/im IM 渠道管理。

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
| POST | /api/auth/register | 用户注册 |
| POST | /api/auth/logout | 用户登出（清除 Cookie） |
| GET | /api/auth/me | 获取当前用户信息 |
| GET | /api/auth/csrf-token | 获取 CSRF token |
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
| POST | /api/memory/vector-search | 长期记忆向量检索 |
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
| GET | /api/mcp/servers | 获取 MCP Server 列表 |
| POST | /api/mcp/servers | 添加 MCP Server |
| POST | /api/mcp/servers/{id}/connect | 连接 MCP Server |
| GET | /api/mcp/tools | 获取所有 MCP 工具 |
| POST | /api/mcp/tools/call | 调用 MCP 工具 |
| GET | /api/subagents | 获取子代理列表 |
| POST | /api/subagents | 创建子代理 |
| POST | /api/subagents/{id}/execute | 执行子代理 |
| GET | /api/scheduled_tasks | 获取定时任务列表 |
| POST | /api/scheduled_tasks | 创建定时任务 |
| GET | /api/roles | 获取角色列表 |
| GET | /api/role_market | 获取角色市场 |
| GET | /api/user_profile | 获取用户画像 |
| PUT | /api/user_profile | 更新用户画像 |
| GET | /api/workspace | 获取工作区列表 |
| GET | /api/coding/* | 编码助手接口 |
| GET | /api/tts/* | TTS 接口 |
| GET | /api/im/* | IM 渠道接口 |
| GET | /api/data/* | 数据仪表盘接口 |
| GET | /api/terminal/* | 终端接口 |
| GET | /api/system/* | 系统监控接口 |
| GET | /api/heartbeat/* | 心跳接口 |
| GET | /api/inbox/* | 收件箱接口 |
| GET | /api/marketplace/* | 插件市场接口 |
| GET | /api/security/* | 安全接口 |
| GET | /api/weixin/* | 微信接口 |
| GET | /api/tools/* | 内置工具接口 |
| GET | /api/task_runtime/* | 任务运行时接口 |
| GET | /api/test_runner/* | 测试运行器接口 |
| GET | /api/magic_commands/* | 魔法命令接口 |
| GET | /api/diary/* | 日记接口 |
| GET | /api/tasks/* | 任务接口 |
| GET | /api/models/* | 模型配置接口 |
| GET | /api/experiences | 获取经验列表 |
| GET | /api/experience_files | 获取经验文件 |
| GET | /api/workflows | 获取工作流列表 |
| POST | /api/workflows/execute | 执行工作流 |

### 6.2 认证流程

认证依赖位于 dependencies.py。登录接口 /api/auth/login 使用 OAuth2PasswordRequestForm（application/x-www-form-urlencoded），校验通过后生成 JWT 并通过 HttpOnly Cookie 和响应体双重下发。dependencies.py 优先读取 Bearer Token，缺失时回退到 Cookie，实现前端无感鉴权。登录接口内置速率限制，同一来源 IP+用户名 组合在 5 分钟窗口内最多允许 5 次失败尝试，超限后封锁 15 分钟。登出接口 /api/auth/logout 清除 Cookie。

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

生产环境中应显式设置以下环境变量：`JWT_SECRET_KEY`、`CSRF_SECRET_KEY`、`ENCRYPTION_KEY`、`OPENAWA_API_KEY`、`OPENAWA_OWNER_PASSWORD`、`DATABASE_URL` 与 `ALLOWED_ORIGINS`。三类密钥必须跨重启保持稳定，否则已签发令牌或已加密数据会失效。

---

## 九、未来规划

### 9.1 微信集成完善

扫码后微信绑定失败需独立处理，需要在 weixin wait 接口 confirmed 分支返回并保存 user_id、binding_status，并在前端展示绑定结果。

### 9.2 MCP 协议支持 [已实现]

MCP 客户端协议栈已在 v1.3 完整落地，包括 Stdio/SSE 双传输、工具发现与调用、资源访问、线程安全 Manager 单例。详见 2.10 节。后续可扩展 MCP Server 端实现，允许外部工具发现并调用 Open-AwA 内部能力。

### 9.3 插件市场 [已实现]

插件市场已在 v1.6 落地，位于 backend/plugins/marketplace/ 与 backend/api/routes/marketplace.py。提供插件浏览（分页 + 分类筛选）、关键词搜索、详情查看、一键安装能力，前端 MarketplacePage 已对接 /api/marketplace/plugins 系列接口。后续可扩展插件上传审核、版本回滚、付费分发等运营能力。

### 9.4 前端 UI 改进 [部分已实现]

v1.6 已完成扁平化 UI 重构：去除冗余边框/强阴影、引入 tokens.css 设计令牌体系、统一白天/黑夜模式切换、CSS Module 按功能域拆分。剩余：继续完善极简风格细节、动画过渡与无障碍访问。

### 9.5 Chain-of-Thought 改进

计划实现思维链折叠展示功能，支持展开/收起 Chain-of-Thought 内容。

### 9.6 多语言模型支持 [已实现]

v1.5 起 LiteLLM 统一网关已接入 DeepSeek、通义千问（QWEN_API_KEY）、Kimi（MOONSHOT_API_KEY）、智谱AI（ZHIPU_API_KEY）、Ollama 本地模型（OLLAMA_BASE_URL）等多家模型服务，前端供应商配置页支持在线管理。详见 2.1 节模型服务链路治理部分。

### 9.7 安全增强 [大部分已实现]

v1.3 已落地：RBAC 三级权限模型、AuditLogger 异步审计日志、Fernet 敏感数据加密、HttpOnly Cookie 令牌传输、CSRF Double Submit Cookie、登录速率限制、ZIP symlink 阻断与 DNS Rebinding IP Pinning。剩余：多级沙箱隔离（async 资源限制待操作系统层面落地）。详见 2.11 节。

---

## 十、文档索引

### 10.1 项目入口文档

- 根 README：项目总体介绍

### 10.2 架构与运行文档

- docs/指南/部署与运行说明.md：本地开发与部署说明
- docs/架构/后端架构说明.md：后端结构、核心模块与数据层说明
- docs/架构/前端架构说明.md：前端页面、服务层与状态管理说明
- docs/指南/测试说明.md：后端、前端、E2E 测试与建议检查项

### 10.3 插件开发文档

- plugin-developer-handbook/README.md：插件开发手册入口
- 1-getting-started.md：入门指南
- 2-api-reference.md：API 参考
- 3-best-practices.md：最佳实践
- 4-faq.md：常见问题

### 10.4 推荐阅读顺序

初次接手项目建议按以下顺序阅读文档：根 README；docs/指南/部署与运行说明.md；docs/架构/后端架构说明.md；docs/架构/前端架构说明.md；docs/指南/测试说明.md；如果需要开发插件，再阅读插件开发手册。

---

## 十一、版本与更新

| 版本 | 日期 | 主要更新 |
|------|------|---------|
| 1.0 | 2026-03 | 项目初始化，实现核心聊天、Skill、插件系统 |
| 1.1 | 2026-03 | 新增记忆系统、行为分析、计费模块 |
| 1.2 | 2026-04 | 前端系统重构、微信集成、完整日志系统 |
| 1.3 | 2026-04 | 安全加固：认证模型重构（HttpOnly Cookie + 速率限制）、敏感数据 Fernet 加密、MCP 协议模块实现、插件安全增强（ZIP symlink/DNS Rebinding）、前端 XSS 防护、CSRF Double Submit Cookie、RBAC 权限模型 |
| 1.4 | 2026-04 | 插件系统修复：全局单例模式、lifespan 初始化、安装/卸载/启用/禁用生命周期同步；多轮对话上下文机制：前端聊天和微信聊天共用 ShortTermMemory 上下文注入；插件发现接口与运行时状态查询 |
| 1.5 | 2026-05 | 多模型统一网关：LiteLLM 接入 DeepSeek/通义千问/Kimi/智谱AI/Ollama；OPENAWA_API_KEY 强制校验机制（未配置拒绝启动）；SSRF 加固（BASE_URL 内网/本地 IP 阻断）；性能优化 P0+P1+P2 共 20+ 项（异步文件 I/O、技能插件并行、PRAGMA 缓存、列表分页、虚拟滚动、Tab API 去重、ChromaDB 批量、DB 连接池可配等） |
| 1.6 | 2026-06 | 子代理编排系统（三级隔离、生命周期状态机、资源限制与编排器）；插件市场落地（浏览/搜索/详情/安装）；前端设置页重构（外观定制 Tab、供应商表单优化、SSE 代理修复、主题背景系统）；IM 渠道适配（飞书/Telegram/钉钉等 9 个渠道）；任务运行时、定时任务、角色系统、用户画像、工作区、编码助手、TTS、终端、自主运行模式、数据仪表盘、收件箱等新模块上线；前端 30+ 页面路由、后端 39 个路由模块 |

---

## 十二、许可与贡献

项目采用 MIT 许可证开源。欢迎提交 Issue 和 Pull Request。

# Open-AwA

Open-AwA 是一个以 FastAPI 后端和 React 前端构建的 AI Agent 平台，定位为 **OpenClaw 级别的 AI Agent 能力 + 二次元 AI 陪伴的情感体验**。当前仓库已经实现了聊天调用、技能管理、插件管理、记忆管理、经验提取、提示词配置、行为统计、会话记录采集与计费模块等功能，并提供了一套可独立演进的插件生命周期与调试能力。项目同时具备角色系统、桌面宠物、TTS 语音合成、日记生成、Soul 引擎等陪伴方向的基础设施，正在向二次元 AI 陪伴产品方向演进。

本文档基于当前仓库代码整理，尽量只描述已经存在的实现与可直接验证的能力。

## 目录

- [项目概览](#项目概览)
- [当前能力](#当前能力)
- [技术栈](#技术栈)
- [仓库结构](#仓库结构)
- [快速开始](#快速开始)
- [运行方式](#运行方式)
- [主要接口与页面](#主要接口与页面)
- [插件开发文档](#插件开发文档)
- [测试与质量检查](#测试与质量检查)
- [更多文档](#更多文档)
- [已知情况说明](#已知情况说明)

## 项目概览

当前仓库由两个主要应用组成：

- 后端：`backend/`，使用 FastAPI、SQLAlchemy、JWT 鉴权、SQLite 默认存储
- 前端：`frontend/`，使用 React 18、TypeScript、Vite、React Router、Zustand、Recharts

后端入口会在启动时初始化数据库、创建计费表并补齐默认模型定价；前端提供聊天、仪表盘、设置、技能、插件、记忆、计费等页面。

相关代码可参考：

- [main.py](backend/main.py#L1-L95)
- [settings.py](backend/config/settings.py#L24-L59)
- [App.tsx](frontend/src/App.tsx#L1-L91)

## 当前能力

基于现有代码，可以确认的模块包括：

- 聊天接口与 WebSocket 会话通信（支持多轮对话上下文，自动注入历史消息、流式分段、思维链展示、子代理编排）
- 用户注册、登录与 `/auth/me` 鉴权信息获取（JWT HttpOnly Cookie + CSRF Double Submit + 登录速率限制）
- 技能的增删改查、执行、配置读取、上传解析与经验提取，以及技能市场
- 内置文件管理、终端执行、网页搜索、编码工具（LSP/Git/Diff）、TTS 等统一注册，并可作为内置技能复用
- 插件的增删改查、启用/禁用（同步运行时加载/卸载）、执行、工具描述读取、上传解包、权限授权、日志查看、热更新与回滚、插件市场
- 短期记忆、工作内存、长期记忆与经验记忆管理，支持长期记忆向量检索、混合检索、质量评估、归档与统计
- 工作流定义解析、顺序执行、条件分支，以及工具、技能、插件步骤编排
- 提示词配置管理
- 行为日志与统计
- 会话记录预览、导出、清理与采集开关
- 模型定价、预算、报表、配置管理等计费能力
- 子代理（Subagent）编排：三级隔离、生命周期状态机、资源限制与编排器
- 任务运行时（task_runtime）：任务注册、会话、运行器与存储
- 定时任务管理（scheduled_tasks）：cron 调度、模板、日历视图
- MCP 协议客户端：Stdio/SSE 双传输、工具发现与调用、资源访问
- IM 渠道集成：飞书、Telegram、钉钉、Discord、Slack、QQ、Matrix、iMessage、企业微信等多渠道适配
- 微信集成：扫码登录、自动回复、技能适配
- 角色系统（roles）：预设角色、角色市场、角色引擎，支持二次元陪伴角色卡导入
- 桌面宠物（pets）：内置宠物 + 自定义导入 + 精灵动画 10 状态，支持二次元风格宠物
- 日记功能（diary）：LLM 生成第一人称陪伴日记，PII 脱敏
- Soul 引擎（soul）：五层洋葱人格模型，AI 陪伴者人格定义
- 用户画像（user_profile）：自动提取、置信度、时间线、雷达图
- 编码助手（coding）：AST 搜索、文件树、Diff、Git 集成、LSP 代理、Claude Code 集成
- 工作区（workspace）：多项目工作区管理
- 收件箱（inbox）：消息聚合
- 数据仪表盘（data）：数据收集器与可视化
- TTS 语音合成：豆包 TTS、语音克隆、语音库
- 终端（terminal）：远程终端执行
- 系统监控（system）：系统状态、健康检查
- 自主运行模式（autonomous）：审计、检查点、硬拒绝规则
- 心跳（heartbeat）：存活探测
- 魔法命令（magic_commands）：快捷指令
- 测试运行器（test_runner）：测试用例执行
- 日志查询与导出（logs）：结构化日志、JSONL 导出
- 安全模块：RBAC、审计日志、PII 脱敏、沙箱、统一访问控制

后端路由注册见：

- [main.py](backend/main.py#L860-L899)

数据库模型见：

- [models.py](backend/db/models.py#L20-L235)

## 技术栈

### 后端

- Python 3.11+
- FastAPI
- SQLAlchemy 2.x
- pydantic-settings
- Loguru
- Uvicorn
- SQLite（默认）

依赖文件：

- [requirements.txt](backend/requirements.txt)

### 前端

- React 18
- TypeScript 5
- Vite 5
- React Router DOM 6
- Axios
- Zustand
- Recharts
- Vitest
- Playwright

依赖与脚本：

- [package.json](frontend/package.json#L1-L38)

## 仓库结构

```text
Open-AwA/
├─ backend/                      # FastAPI 后端工作区
│  ├─ api/routes/                # 业务路由
│  ├─ core/                      # Agent 核心流程与运行时
│  ├─ billing/ memory/ plugins/ # 计费、记忆、插件领域模块
│  ├─ security/ skills/ tools/  # 安全、技能、工具模块
│  ├─ tests/                     # 后端测试
│  └─ main.py                    # FastAPI 入口
├─ frontend/                     # React Web 客户端工作区
│  ├─ src/features/              # 按领域拆分的功能模块
│  ├─ src/shared/                # 共享 API、组件、状态与工具
│  ├─ src/__tests__/             # 前端单测
│  ├─ tests/e2e/                 # Playwright E2E
│  └─ package.json
├─ desktop/                      # Electron 桌面客户端
├─ android/                      # Android 原生客户端
├─ var/                          # 运行时数据（gitignore，自动创建）
│  ├─ data/                     # 数据库、向量库、上传文件
│  ├─ logs/                     # 日志
│  ├─ workspace/                # 工作区
│  ├─ plugins/                  # 用户插件数据
│  └─ pets/                     # 宠物数据
├─ bin/                         # 可执行脚本
│  ├─ dev.bat                   # 开发启动
│  ├─ deploy.ps1                # Docker 一键部署
│  ├─ install.ps1               # 一键安装
│  ├─ generate_api_key.py       # API Key 生成
│  ├─ migrate_layout.py         # 目录重组迁移脚本
│  └─ migrate_runtime_data.py   # 遗留运行时数据收拢脚本
├─ assets/                      # 静态资源
│  └─ design/                   # 设计稿（原 open-awa-canvas）
├─ deploy/                      # 部署配置
│  ├─ Dockerfile
│  ├─ docker-compose*.yml
│  ├─ nginx.conf
│  ├─ entrypoint.sh
│  └─ nginx/                    # nginx 子配置
├─ plugins/                     # 示例插件目录（用户可见入口）
├─ scripts/                     # 辅助脚本（性能测试、同步等）
├─ docs/                        # 项目文档
│  ├─ reports/                  # 历史/回归报告
│  ├─ audit/                    # 审计报告
│  ├─ 架构/                     # 架构说明
│  ├─ 指南/                     # 部署/测试指南
│  └─ 插件开发手册/             # 插件开发文档
├─ pyproject.toml
├─ .env.example
└─ .gitignore
```

## 快速开始

### 1. 环境要求

建议环境：

- Python 3.11 或更高版本
- Node.js 18 或更高版本
- npm 9+

### 2. 启动后端

Windows PowerShell：

```powershell
cd d:\代码\Open-AwA\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

启动后可访问：

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/health`

### 3. 启动前端

```powershell
cd d:\代码\Open-AwA\frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

默认前端地址：

- `http://127.0.0.1:5173`

## 运行方式

### 后端启动行为

后端启动流程已拆分为独立步骤，便于排障与单元测试：

1. 基础设施初始化：LiteLLM 依赖检测、模型供应商可用性检查、`OPENAWA_API_KEY` 校验（未配置或长度不足 32 字符将拒绝启动）
2. 数据层初始化：DB 建表、计费表、预设角色（RoleEngine）、RBAC 内置角色、Owner 用户创建、默认模型定价与配置
3. 插件系统初始化：市场种子、插件发现、已启用插件加载、`system-tools` 内置插件注册
4. 后台任务初始化：定时任务管理器、微信自动回复（按 `auto_start_reply` 配置）
5. 自主运行模式初始化（仅通过 `.env` 配置启用）
6. 数据收集器初始化
7. 挂载各业务路由（39 个路由模块）
8. 配置 CORS、CSRF、CSP、速率限制等中间件

代码位置：

- [main.py](backend/main.py#L181-L460)

### 默认配置

默认配置来自 [settings.py](backend/config/settings.py#L76-L241)，其中较重要的项包括：

- `API_V1_STR=/api`
- `DATABASE_URL=sqlite:///<项目根>/var/data/openawa.db`（默认使用绝对路径，不受启动目录影响）
- `ACCESS_TOKEN_EXPIRE_MINUTES=1440`
- `SANDBOX_TIMEOUT=30`
- `SANDBOX_MEMORY_LIMIT=512m`
- `SANDBOX_BACKEND=restricted_python`
- `LOG_LEVEL=INFO`
- `VECTOR_DB_PATH=<项目根>/var/data/qdrant`
- `OPENAWA_API_KEY=`（必填，未配置时拒绝启动，可运行 `python bin/bin/generate_api_key.py` 生成）
- `OPENAWA_OWNER_USERNAME=admin`
- `RATE_LIMIT_BACKEND=memory`（多 worker 部署时建议 `database`）
- `TRUSTED_PROXIES=127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16`
- `MAX_TOOL_CALL_ROUNDS=12`
- `AGENT_TASK_TIMEOUT_SECONDS=300`

长期记忆向量检索默认会读取以下配置或环境变量：

- `VECTOR_DB_PATH`：Qdrant 持久化目录
- `MEMORY_EMBEDDING_PROVIDER`：嵌入提供方，可选 `hash`、`openai`、`sentence-transformers`
- `OPENAI_API_KEY`：当嵌入提供方为 `openai` 时使用

生产环境中应显式设置：

- `JWT_SECRET_KEY`（JWT 签名密钥，至少 32 字符）
- `CSRF_SECRET_KEY`（CSRF 签名密钥，至少 32 字符）
- `ENCRYPTION_KEY`（Fernet 密钥，用于敏感配置加密）
- `OPENAWA_API_KEY`（必填，至少 32 字符）
- `OPENAWA_OWNER_PASSWORD`（Owner 初始密码）
- `DATABASE_URL`
- `ALLOWED_ORIGINS`（生产环境未配置时拒绝启动）
- `ENVIRONMENT=production`
- 各模型提供方 API Key（`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `DEEPSEEK_API_KEY` / `QWEN_API_KEY` / `ZHIPU_API_KEY` / `MOONSHOT_API_KEY`）
- 可选：`SSL_CERTFILE` / `SSL_KEYFILE` 启用 HTTPS

前端开发阶段常用环境变量（`frontend/.env.development`）：

- `VITE_ENABLE_DEV_AUTO_LOGIN`：是否启用开发态自动登录（`true/false`）
- `VITE_TEST_USERNAME`：开发态自动登录用户名（仅当启用自动登录时生效）
- `VITE_TEST_PASSWORD`：开发态自动登录密码（仅当启用自动登录时生效）

## 主要接口与页面

### 后端主要路由

已在入口文件注册的主路由包括（共 39 个模块）：

- `/api/auth` - 认证（登录/注册/登出/csrf-token）
- `/api/chat` - 聊天（HTTP + WebSocket）
- `/api/skills` - 技能管理（含微信技能 `/skills/weixin/*`）
- `/api/plugins` - 插件管理
- `/api/memory` - 记忆管理（含向量检索/归档/质量/统计）
- `/api/workflows` - 工作流
- `/api/scheduled_tasks` - 定时任务
- `/api/diary` - 日记
- `/api/prompts` - 提示词配置
- `/api/behaviors` - 行为分析
- `/api/experiences` - 经验记忆
- `/api/experience_files` - 经验文件
- `/api/conversations` - 会话记录
- `/api/logs` - 日志查询与导出
- `/api/mcp/*` - MCP 协议
- `/api/models/*` - 模型配置
- `/api/billing/*` - 计费
- `/api/marketplace/*` - 插件市场
- `/api/security/*` - 安全
- `/api/weixin/*` - 微信
- `/api/tools/*` - 内置工具
- `/api/subagents/*` - 子代理
- `/api/task_runtime/*` - 任务运行时
- `/api/user/*` - 用户管理（含头像静态文件）
- `/api/user_profile/*` - 用户画像
- `/api/system/*` - 系统监控
- `/api/test_runner/*` - 测试运行器
- `/api/workspace/*` - 工作区
- `/api/heartbeat/*` - 心跳
- `/api/coding/*` - 编码助手
- `/api/inbox/*` - 收件箱
- `/api/magic_commands/*` - 魔法命令
- `/api/tts/*` - TTS 语音合成
- `/api/tasks/*` - 任务
- `/api/roles/*` - 角色管理
- `/api/role_market/*` - 角色市场
- `/api/data/*` - 数据仪表盘
- `/api/terminal/*` - 终端
- `/api/im/*` - IM 渠道

可参考以下代码：

- [auth.py](backend/api/routes/auth.py#L14-L62)
- [chat.py](backend/api/routes/chat.py#L14-L190)
- [skills.py](backend/api/routes/skills.py#L17-L368)
- [plugins.py](backend/api/routes/plugins.py#L15-L519)
- [memory.py](backend/api/routes/memory.py#L12-L121)
- [subagents.py](backend/api/routes/subagents.py)
- [coding.py](backend/api/routes/coding.py)
- [mcp.py](backend/api/routes/mcp.py)

### 记忆与工作流扩展接口

后端记忆与工作流相关接口包括：

- `/api/memory/vector-search`：长期记忆混合检索与语义检索入口
- `/api/memory/archive`：执行长期记忆归档
- `/api/memory/quality`：查看长期记忆质量报告
- `/api/memory/stats`：查看长期记忆统计与向量库状态
- `/api/workflows`：工作流定义的创建、查询、更新、删除
- `/api/workflows/execute`：显式执行工作流
- `/api/workflows/executions/{execution_id}`：查询工作流执行状态
- [experiences.py](backend/api/routes/experiences.py#L14-L260)
- [conversation.py](backend/api/routes/conversation.py#L14-L139)
- [billing.py](backend/billing/routers/billing.py#L14-L260)

### 前端页面

前端目前包含以下页面路由（共 30+ 个）：

- `/login` - 登录页
- `/chat` - 聊天页（支持 `/chat/:conversationId` 会话切换）
- `/dashboard` - 仪表盘
- `/settings` - 设置页（含模型/计费/数据采集/数据保留/外观/通用/MCP/权限/安全/环境变量等 Tab）
- `/skills` - 技能管理
- `/skills/market` - 技能市场
- `/scheduled-tasks` - 定时任务
- `/plugins` - 插件管理（自动重定向到 `/plugins/manage`）
- `/plugins/manage` - 插件列表
- `/plugins/config/:pluginId` - 插件配置
- `/plugins/marketplace` - 插件市场
- `/memory` - 记忆管理
- `/experience` - 经验记忆
- `/billing` - 计费
- `/communication` - 微信通讯
- `/user` - 用户中心
- `/profile/edit` - 用户画像编辑
- `/test` - 测试页
- `/workspace` - 工作区
- `/coding` - 编码助手
- `/inbox` - 收件箱
- `/agents` - 子代理列表
- `/roles` - 角色管理
- `/role-market` - 角色市场
- `/data` - 数据仪表盘
- `/tts` - TTS 语音合成
- `/im` - IM 渠道

代码位置：

- [App.tsx](frontend/src/App.tsx#L64-L128)

其中几个核心页面对应实现：

- [ChatPage.tsx](frontend/src/features/chat/ChatPage.tsx)
- [DashboardPage.tsx](frontend/src/features/dashboard/DashboardPage.tsx)
- [PluginsPage.tsx](frontend/src/features/plugins/PluginsPage.tsx)
- [MemoryPage.tsx](frontend/src/features/memory/MemoryPage.tsx)
- [BillingPage.tsx](frontend/src/features/billing/BillingPage.tsx)
- [SettingsPage.tsx](frontend/src/features/settings/SettingsPage.tsx)
- [CodingPage.tsx](frontend/src/features/coding/CodingPage.tsx)
- [ScheduledTasksPage.tsx](frontend/src/features/scheduledTasks/ScheduledTasksPage.tsx)

## 插件开发文档

仓库已经包含插件开发手册，现已按当前代码重新整理。入口文档：

- [插件开发手册.md](docs/插件开发手册/插件开发手册.md)

建议阅读顺序：

1. [一-快速开始.md](docs/插件开发手册/一-快速开始.md)
2. [二-API参考.md](docs/插件开发手册/二-API参考.md)
3. [三-最佳实践.md](docs/插件开发手册/三-最佳实践.md)
4. [四-常见问题.md](docs/插件开发手册/四-常见问题.md)

示例插件目录：

- [plugins/hello-world](plugins/hello-world)
- [plugins/theme-switcher](plugins/theme-switcher)
- [plugins/data-chart](plugins/data-chart)

### 插件包格式规范（ZIP）

插件 ZIP 包建议以插件根目录打包，且至少包含以下文件：

- `index.js`：插件入口文件，导出插件主逻辑
- `schema.json`：配置结构定义，用于动态表单渲染与校验
- `README.md`：插件说明文档（功能、参数、权限、使用方式）

建议同时包含：

- `package.json`：版本与元信息
- `assets/`：静态资源目录（如图标、示例配置）

### 本地调试步骤（插件管理与配置）

1. 启动后端与前端服务（见“快速开始”）
2. 访问 `http://127.0.0.1:5173/plugins/manage`
3. 通过“导入插件”上传本地 ZIP 或通过“URL 导入”拉取远程包
4. 在插件卡片点击“配置”进入 `/plugins/config/:pluginId`
5. 修改配置并保存，确认页面提示“写入 config.json”
6. 可通过“重置默认 / 导出配置 / 导入配置 / 回滚到导入前”验证辅助工具链

### 常见排错

- 导入失败：确认 ZIP 后缀、MIME 与文件大小不超过 50MB
- URL 导入失败：确认 URL 可访问且后端白名单策略允许
- 表单保存失败：优先检查必填项、枚举值、正则与数值范围校验提示
- 配置未生效：确认当前插件 ID 正确，且保存接口返回成功

## 测试与质量检查

### 后端

```powershell
cd d:\代码\Open-AwA\backend
python -m pytest
```

### 前端单元测试

```powershell
cd d:\代码\Open-AwA\frontend
npm run test
```

### 前端覆盖率

```powershell
cd d:\代码\Open-AwA\frontend
npm run test:coverage
```

### 前端类型检查

```powershell
cd d:\代码\Open-AwA\frontend
npm run typecheck
```

### 前端构建

```powershell
cd d:\代码\Open-AwA\frontend
npm run build
```

### E2E 测试

```powershell
cd d:\代码\Open-AwA\frontend
npm run e2e
```

E2E 配置见：

- [playwright.config.ts](frontend/playwright.config.ts#L1-L54)

## 更多文档

完整文档导航见 [docs/文档导航.md](docs/文档导航.md)。常用入口如下：

- [二次元陪伴发展方向路线图](docs/二次元陪伴发展方向路线图.md)
- [未来技术路线图](docs/架构/未来路线图.md)
- [部署与开发](docs/指南/部署与运行说明.md)
- [后端架构](docs/架构/后端架构说明.md)
- [前端架构](docs/架构/前端架构说明.md)
- [测试策略](docs/指南/测试说明.md)
- [部署迁移指南](docs/指南/上线迁移指南.md)
- [回归测试报告](docs/reports/回归测试报告.md)
- [插件开发手册](docs/插件开发手册/插件开发手册.md)

## 愿景规划

### 核心方向：二次元 AI 陪伴

Open-AwA 的发展方向是成为 **OpenClaw 级别的 AI Agent 能力 + 二次元陪伴的情感体验** 的融合产品。详细路线图见 [二次元陪伴发展方向路线图](docs/二次元陪伴发展方向路线图.md)。

### 目标形态：贾维斯式多终端 AI 助手

将 Open-AwA 从"AI Agent 平台"演进为类似贾维斯的跨终端智能助手：

- **云端服务器**：FastAPI 后端即服务，支持多用户、多设备接入
- **手机端 App**：多端登录、会话漫游、消息实时同步
- **电脑端**：浏览器访问 + 原生桌面封装（托盘常驻、全局快捷键唤起、语音唤醒）
- **语音交互**：语音输入 + AI 语音回复，支持打断与多音色
- **主动感知**：AI 主动推送提醒（日程摘要、消息提醒、异常告警）
- **跨端任务接力**：手机发起的复杂任务自动路由到电脑端执行

### 阶段性路线图

#### 阶段 1：多端会话同步基础（MVP）
- 后端：设备注册 API、会话同步协议（基于现有 WebSocket 扩展）、消息序列号与冲突解决
- 前端：抽离会话状态到 Zustand + 持久化、多设备管理页
- 移动端：PWA 起步（manifest + service worker + 响应式适配），零原生开发成本验证多端体验

#### 阶段 2：语音交互
- ASR：浏览器 Web Speech API 起步 -> 后期接 Whisper API
- TTS：Edge TTS / Azure TTS，支持中文多音色
- 唤醒词：桌面端用 Tauri/Electron 封装获得麦克风常驻权限
- 前端：语音按钮 + 波形动画 + 中断控制

#### 阶段 3：桌面端原生封装
- Tauri 封装现有 Web 端（包体小 ~10MB、Rust 安全）
- 系统托盘常驻 + 全局快捷键（如 Alt+Space 唤起）+ 开机自启
- 麦克风后台权限

#### 阶段 4：主动感知与跨端接力
- 事件总线：日历/邮件/文件变更等事件源接入
- 推送系统：手机端 Web Push + 桌面端系统通知
- 任务路由：手机发起的复杂任务自动转到电脑端执行

#### 阶段 5：移动端原生升级
- 当 PWA 验证体验不足时，升级到 React Native + Expo
- 复用后端 API，重写原生 UI，获得推送/生物识别/后台能力

## 已知情况说明

以下内容是根据当前代码观察得到，建议在后续开发中继续收敛：

- 前端 `App.tsx` 中保留了开发态自动登录逻辑（通过 `useAppInitialization` Hook），属于开发便利逻辑，不适合作为正式产品流程说明，见 [App.tsx](frontend/src/App.tsx#L131-L173)
- 后端启动强制要求 `OPENAWA_API_KEY`（至少 32 字符），未配置时拒绝启动，可通过 `python bin/bin/generate_api_key.py` 生成
- 生产环境（`ENVIRONMENT=production`）启动时会强制校验 `JWT_SECRET_KEY`、`CSRF_SECRET_KEY`、`ENCRYPTION_KEY` 与 `ALLOWED_ORIGINS`，未配置将拒绝启动
- README 只描述已存在的接口与页面，不对未完成功能做保证

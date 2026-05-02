# Open-AwA

Open-AwA 是一个以 FastAPI 后端和 React 前端构建的 AI Agent 实验性平台，当前仓库已经实现了聊天调用、技能管理、插件管理、记忆管理、经验提取、提示词配置、行为统计、会话记录采集与计费模块等功能，并提供了一套可独立演进的插件生命周期与调试能力。

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

- 聊天接口与 WebSocket 会话通信（支持多轮对话上下文，自动注入历史消息）
- 用户注册、登录与 `/auth/me` 鉴权信息获取
- 技能的增删改查、执行、配置读取、上传解析与经验提取
- 内置文件管理、终端执行、网页搜索工具统一注册，并可作为内置技能复用
- 插件的增删改查、启用/禁用（同步运行时加载/卸载）、执行、工具描述读取、上传解包、权限授权、日志查看、热更新与回滚、插件发现
- 短期记忆、工作内存、长期记忆与经验记忆管理，支持长期记忆向量检索、质量评估、归档与统计
- 工作流定义解析、顺序执行、条件分支，以及工具、技能、插件步骤编排
- 提示词配置管理
- 行为日志与统计
- 会话记录预览、导出、清理与采集开关
- 模型定价、预算、报表、配置管理等计费能力

后端路由注册见：

- [main.py](backend/main.py#L52-L76)

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
├─ backend/                     # FastAPI 后端
│  ├─ api/routes/               # 业务路由
│  ├─ billing/                  # 计费相关模块
│  ├─ config/                   # 配置与安全
│  ├─ core/                     # Agent 核心流程
│  ├─ db/                       # SQLAlchemy 模型与数据库初始化
│  ├─ memory/                   # 记忆与经验管理
│  ├─ plugins/                  # 插件系统核心
│  ├─ skills/                   # Skill 系统
│  ├─ tests/                    # 后端测试
│  └─ main.py                   # FastAPI 入口
├─ frontend/                    # React 前端
│  ├─ src/features/             # 功能模块（页面、组件、状态）
│  ├─ src/shared/               # 共享资源（组件、API、状态、类型、工具）
│  ├─ src/__tests__/            # 前端单测
│  ├─ tests/e2e/                # Playwright E2E
│  └─ package.json
├─ plugins/                     # 示例插件目录
└─ docs/                        # 项目文档
   └─ archive/                  # 历史报告归档
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

后端在启动时会：

1. 初始化主数据库表
2. 创建计费模块表结构
3. 初始化默认模型定价配置
4. 初始化 RBAC 角色权限与本地用户
5. 初始化插件管理器全局单例，自动发现并加载已启用插件
6. 挂载各业务路由
7. 配置允许的 CORS 来源

代码位置：

- [main.py](backend/main.py#L22-L76)

### 默认配置

默认配置来自 [settings.py](backend/config/settings.py#L24-L59)，其中较重要的项包括：

- `API_V1_STR=/api`
- `DATABASE_URL=sqlite:///./backend/openawa.db`
- `ACCESS_TOKEN_EXPIRE_MINUTES=1440`
- `SANDBOX_TIMEOUT=30`
- `SANDBOX_MEMORY_LIMIT=512m`
- `LOG_LEVEL=INFO`
- `VECTOR_DB_PATH=backend/data/vector_db`

长期记忆向量检索默认会读取以下配置或环境变量：

- `VECTOR_DB_PATH`：ChromaDB 持久化目录
- `MEMORY_EMBEDDING_PROVIDER`：嵌入提供方，可选 `hash`、`openai`、`sentence-transformers`
- `OPENAI_API_KEY`：当嵌入提供方为 `openai` 时使用

生产环境中应显式设置：

- `SECRET_KEY`
- `DATABASE_URL`
- `ALLOWED_ORIGINS`
- 各模型提供方 API Key

前端开发阶段常用环境变量（`frontend/.env.development`）：

- `VITE_ENABLE_DEV_AUTO_LOGIN`：是否启用开发态自动登录（`true/false`）
- `VITE_TEST_USERNAME`：开发态自动登录用户名（仅当启用自动登录时生效）
- `VITE_TEST_PASSWORD`：开发态自动登录密码（仅当启用自动登录时生效）

## 主要接口与页面

### 后端主要路由

已在入口文件注册的主路由包括：

- `/api/auth`
- `/api/chat`
- `/api/skills`
- `/api/plugins`
- `/api/memory`
- `/api/workflows`
- `/api/prompts`
- `/api/behaviors`
- `/api/experiences`
- `/api/conversations`
- `/api/billing`

可参考以下代码：

- [auth.py](backend/api/routes/auth.py#L14-L62)
- [chat.py](backend/api/routes/chat.py#L14-L190)
- [skills.py](backend/api/routes/skills.py#L17-L368)
- [plugins.py](backend/api/routes/plugins.py#L15-L519)
- [memory.py](backend/api/routes/memory.py#L12-L121)

### 记忆与工作流扩展接口

本轮新增或增强的后端接口包括：

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

前端目前包含以下页面路由：

- `/chat`
- `/dashboard`
- `/settings`
- `/skills`
- `/plugins`（自动重定向到 `/plugins/manage`）
- `/plugins/manage`
- `/plugins/config/:pluginId`
- `/memory`
- `/billing`

代码位置：

- [App.tsx](frontend/src/App.tsx#L70-L88)

其中几个核心页面对应实现：

- [ChatPage.tsx](frontend/src/features/chat/ChatPage.tsx#L1-L259)
- [DashboardPage.tsx](frontend/src/features/dashboard/DashboardPage.tsx#L1-L128)
- [PluginsPage.tsx](frontend/src/features/plugins/PluginsPage.tsx#L1-L260)
- [MemoryPage.tsx](frontend/src/features/memory/MemoryPage.tsx#L1-L154)
- [BillingPage.tsx](frontend/src/features/billing/BillingPage.tsx#L1-L249)

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

- [部署与开发](docs/指南/部署与运行说明.md)
- [后端架构](docs/架构/后端架构说明.md)
- [前端架构](docs/架构/前端架构说明.md)
- [测试策略](docs/指南/测试说明.md)
- [部署迁移指南](docs/指南/上线迁移指南.md)
- [回归测试报告](docs/报告/回归测试报告.md)
- [插件开发手册](docs/插件开发手册/插件开发手册.md)

## 已知情况说明

以下内容是根据当前代码观察得到，建议在后续开发中继续收敛：

- 前端初始化流程会自动注册并登录测试用户，属于开发便利逻辑，不适合作为正式产品流程说明，见 [App.tsx](frontend/src/App.tsx#L20-L53)
- `PluginsPage` 中存在“浏览插件市场”按钮，但当前仓库未看到对应市场实现
- README 只描述已存在的接口与页面，不对未完成功能做保证

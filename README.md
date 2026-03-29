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

- [main.py](file:///d:/代码/Open-AwA/backend/main.py#L1-L95)
- [settings.py](file:///d:/代码/Open-AwA/backend/config/settings.py#L24-L59)
- [App.tsx](file:///d:/代码/Open-AwA/frontend/src/App.tsx#L1-L91)

## 当前能力

基于现有代码，可以确认的模块包括：

- 聊天接口与 WebSocket 会话通信
- 用户注册、登录与 `/auth/me` 鉴权信息获取
- 技能的增删改查、执行、配置读取、上传解析与经验提取
- 插件的增删改查、启用/禁用、执行、工具描述读取、上传解包、权限授权、日志查看、热更新与回滚
- 短期记忆、长期记忆与经验记忆管理
- 提示词配置管理
- 行为日志与统计
- 会话记录预览、导出、清理与采集开关
- 模型定价、预算、报表、配置管理等计费能力

后端路由注册见：

- [main.py](file:///d:/代码/Open-AwA/backend/main.py#L52-L76)

数据库模型见：

- [models.py](file:///d:/代码/Open-AwA/backend/db/models.py#L20-L235)

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

- [requirements.txt](file:///d:/代码/Open-AwA/backend/requirements.txt)

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

- [package.json](file:///d:/代码/Open-AwA/frontend/package.json#L1-L38)

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
│  ├─ src/components/           # 通用组件
│  ├─ src/pages/                # 页面
│  ├─ src/services/             # API 封装
│  ├─ src/stores/               # Zustand 状态管理
│  ├─ src/__tests__/            # 前端单测
│  ├─ tests/e2e/                # Playwright E2E
│  └─ package.json
├─ plugins/                     # 示例插件目录
└─ docs/                        # 项目文档
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
4. 挂载各业务路由
5. 配置允许的 CORS 来源

代码位置：

- [main.py](file:///d:/代码/Open-AwA/backend/main.py#L22-L76)

### 默认配置

默认配置来自 [settings.py](file:///d:/代码/Open-AwA/backend/config/settings.py#L24-L59)，其中较重要的项包括：

- `API_V1_STR=/api`
- `DATABASE_URL=sqlite:///./openawa.db`
- `ACCESS_TOKEN_EXPIRE_MINUTES=1440`
- `SANDBOX_TIMEOUT=30`
- `SANDBOX_MEMORY_LIMIT=512m`
- `LOG_LEVEL=INFO`

生产环境中应显式设置：

- `SECRET_KEY`
- `DATABASE_URL`
- `ALLOWED_ORIGINS`
- 各模型提供方 API Key

## 主要接口与页面

### 后端主要路由

已在入口文件注册的主路由包括：

- `/api/auth`
- `/api/chat`
- `/api/skills`
- `/api/plugins`
- `/api/memory`
- `/api/prompts`
- `/api/behaviors`
- `/api/experiences`
- `/api/conversations`
- `/api/billing`

可参考以下代码：

- [auth.py](file:///d:/代码/Open-AwA/backend/api/routes/auth.py#L14-L62)
- [chat.py](file:///d:/代码/Open-AwA/backend/api/routes/chat.py#L14-L190)
- [skills.py](file:///d:/代码/Open-AwA/backend/api/routes/skills.py#L17-L368)
- [plugins.py](file:///d:/代码/Open-AwA/backend/api/routes/plugins.py#L15-L519)
- [memory.py](file:///d:/代码/Open-AwA/backend/api/routes/memory.py#L12-L121)
- [experiences.py](file:///d:/代码/Open-AwA/backend/api/routes/experiences.py#L14-L260)
- [conversation.py](file:///d:/代码/Open-AwA/backend/api/routes/conversation.py#L14-L139)
- [billing.py](file:///d:/代码/Open-AwA/backend/billing/routers/billing.py#L14-L260)

### 前端页面

前端目前包含以下页面路由：

- `/chat`
- `/dashboard`
- `/settings`
- `/skills`
- `/plugins`
- `/memory`
- `/billing`

代码位置：

- [App.tsx](file:///d:/代码/Open-AwA/frontend/src/App.tsx#L70-L88)

其中几个核心页面对应实现：

- [ChatPage.tsx](file:///d:/代码/Open-AwA/frontend/src/pages/ChatPage.tsx#L1-L259)
- [DashboardPage.tsx](file:///d:/代码/Open-AwA/frontend/src/pages/DashboardPage.tsx#L1-L128)
- [PluginsPage.tsx](file:///d:/代码/Open-AwA/frontend/src/pages/PluginsPage.tsx#L1-L260)
- [MemoryPage.tsx](file:///d:/代码/Open-AwA/frontend/src/pages/MemoryPage.tsx#L1-L154)
- [BillingPage.tsx](file:///d:/代码/Open-AwA/frontend/src/pages/BillingPage.tsx#L1-L249)

## 插件开发文档

仓库已经包含插件开发手册，现已按当前代码重新整理。入口文档：

- [README.md](file:///d:/代码/Open-AwA/docs/plugin-developer-handbook/README.md)

建议阅读顺序：

1. [1-getting-started.md](file:///d:/代码/Open-AwA/docs/plugin-developer-handbook/1-getting-started.md)
2. [2-api-reference.md](file:///d:/代码/Open-AwA/docs/plugin-developer-handbook/2-api-reference.md)
3. [3-best-practices.md](file:///d:/代码/Open-AwA/docs/plugin-developer-handbook/3-best-practices.md)
4. [4-faq.md](file:///d:/代码/Open-AwA/docs/plugin-developer-handbook/4-faq.md)

示例插件目录：

- `d:\代码\Open-AwA\plugins\hello-world`
- `d:\代码\Open-AwA\plugins\theme-switcher`
- `d:\代码\Open-AwA\plugins\data-chart`

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

- [playwright.config.ts](file:///d:/代码/Open-AwA/frontend/playwright.config.ts#L1-L54)

## 更多文档

新增与更新后的中文文档位于 `docs/`：

- [README.md](file:///d:/代码/Open-AwA/docs/README.md)
- [deployment.md](file:///d:/代码/Open-AwA/docs/deployment.md)
- [backend-architecture.md](file:///d:/代码/Open-AwA/docs/backend-architecture.md)
- [frontend-architecture.md](file:///d:/代码/Open-AwA/docs/frontend-architecture.md)
- [testing.md](file:///d:/代码/Open-AwA/docs/testing.md)

## 已知情况说明

以下内容是根据当前代码观察得到，建议在后续开发中继续收敛：

- 前端初始化流程会自动注册并登录测试用户，属于开发便利逻辑，不适合作为正式产品流程说明，见 [App.tsx](file:///d:/代码/Open-AwA/frontend/src/App.tsx#L20-L53)
- `PluginsPage` 中存在“浏览插件市场”按钮，但当前仓库未看到对应市场实现
- README 只描述已存在的接口与页面，不对未完成功能做保证

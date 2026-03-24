# Open-AwA AI Agent Framework

基于 OpenClaw 架构的 AI 智能体框架，支持 Skill、MCP、工具调用、提示词配置、用户行为分析、记忆系统、插件热更新、计费系统等核心功能。

## 特性

- **AI 智能体核心**：理解 → 规划 → 执行 → 反馈的完整闭环
- **Skill 系统**：可扩展的技能插件体系，支持 YAML 配置、依赖管理、注册/执行生命周期
- **MCP 支持**：Model Context Protocol 原生集成
- **工具调用**：统一的工具注册和执行机制
- **记忆系统**：短期 + 长期三层记忆架构，经验记忆自动提取与复用
- **插件系统**：完整的企业级热插拔架构，支持生命周期管理（registered/loaded/enabled/disabled/unloaded/error/updating）、8 种扩展点类型、热更新与灰度发布、安全沙箱隔离、依赖解析
- **安全隔离**：多级沙箱和权限控制，静态代码扫描 + 运行时权限授权
- **行为分析**：完整的用户行为追踪和统计
- **提示词管理**：动态提示词模板配置
- **计费系统**：Token 级计费、预算控制、模型配置管理、多维度成本报告
- **可观测性**：独立日志通道、实时 Debug 面板、热更新状态追踪

## 技术栈

**后端**
- Python 3.11+
- FastAPI
- SQLAlchemy 2.0（Mapped 类型）
- JWT 认证
- Loguru 日志

**前端**
- React 18
- TypeScript（严格模式）
- Vite
- Zustand
- Recharts
- Playwright（E2E 测试）

## 快速开始

### 后端启动

```bash
cd backend

# 创建虚拟环境
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动服务
python main.py
# 或
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

后端将在 http://localhost:8000 启动

### 前端启动

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端将在 http://localhost:5173 启动

### 插件开发

```bash
cd backend

# 初始化插件模板
python -m plugins.cli.plugin_cli init my-plugin

# 构建插件包
python -m plugins.cli.plugin_cli build ./plugins/my-plugin

# 验证插件配置
python -m plugins.cli.plugin_cli validate ./plugins/my-plugin
```

## 项目结构

```
backend/
├── core/               # 核心引擎
│   ├── agent.py        # AI 智能体主控制器
│   ├── comprehension.py # 理解层
│   ├── planner.py      # 规划层
│   ├── executor.py     # 执行层
│   └── feedback.py     # 反馈层
├── api/
│   ├── routes/         # API 路由模块
│   │   ├── auth.py     # 认证
│   │   ├── chat.py     # 聊天
│   │   ├── skills.py   # 技能管理
│   │   ├── plugins.py  # 插件管理
│   │   ├── behaviors.py # 行为分析
│   │   ├── experiences.py # 经验记忆
│   │   └── memory.py   # 记忆系统
│   └── dependencies.py  # 依赖注入
├── plugins/            # 插件系统核心
│   ├── plugin_manager.py        # 插件管理器
│   ├── plugin_lifecycle.py     # 生命周期状态机
│   ├── extension_protocol.py  # 扩展点协议
│   ├── schema_validator.py     # 配置校验
│   ├── hot_update_manager.py   # 热更新管理
│   ├── plugin_logger.py        # 独立日志通道
│   ├── security/
│   │   ├── static_scanner.py  # 静态安全扫描
│   │   ├── permission_controller.py # 权限控制
│   │   └── sandbox.py         # 运行时沙箱
│   ├── cli/
│   │   └── plugin_cli.py      # CLI 工具
│   └── examples/               # 示例插件
├── skills/             # Skill 系统
├── memory/             # 记忆系统
├── billing/            # 计费系统
│   ├── pricing_manager.py   # 定价管理
│   ├── tracker.py          # 用量追踪
│   ├── engine.py           # 计费引擎
│   ├── calculator.py        # 费用计算
│   ├── budget_manager.py   # 预算控制
│   └── reporter.py         # 成本报告
├── security/           # 安全模块
└── main.py            # 应用入口

frontend/
├── src/
│   ├── components/
│   │   ├── PluginDebugPanel.tsx  # 实时 Debug 面板
│   │   └── ...
│   ├── pages/
│   │   ├── ChatPage.tsx
│   │   ├── PluginsPage.tsx
│   │   └── ...
│   ├── services/
│   │   ├── chatService.ts
│   │   ├── pluginService.ts
│   │   └── ...
│   ├── types/
│   │   └── plugin-sdk.d.ts  # TypeScript SDK 类型定义
│   └── stores/
└── playwright.config.ts     # E2E 测试配置
```

## API 接口

### 认证
- `POST /api/auth/register` - 用户注册
- `POST /api/auth/login` - 用户登录

### 聊天
- `POST /api/chat` - 发送消息
- `GET /api/chat/history/{session_id}` - 获取聊天历史
- `WS /api/chat/ws/{session_id}` - WebSocket 连接

### 技能
- `GET /api/skills` - 获取技能列表
- `POST /api/skills` - 安装技能
- `POST /api/skills/upload` - 上传技能包
- `DELETE /api/skills/{id}` - 卸载技能
- `GET /api/skills/stats` - 技能统计

### 插件
- `GET /api/plugins` - 获取插件列表
- `POST /api/plugins` - 安装插件
- `POST /api/plugins/upload` - 上传插件包
- `DELETE /api/plugins/{id}` - 卸载插件
- `PUT /api/plugins/{id}/enable` - 启用插件
- `PUT /api/plugins/{id}/disable` - 禁用插件
- `POST /api/plugins/{id}/update` - 热更新
- `POST /api/plugins/{id}/rollback` - 回滚
- `GET /api/plugins/{id}/permissions` - 权限状态
- `POST /api/plugins/{id}/permissions/authorize` - 授权
- `GET /api/plugins/logs` - 获取插件日志

### 经验
- `GET /api/experiences` - 获取经验列表
- `POST /api/experiences` - 创建经验
- `GET /api/experiences/search` - 搜索经验
- `GET /api/experiences/stats` - 经验统计

### 记忆
- `GET /api/memory/short-term/{session_id}` - 短期记忆
- `GET /api/memory/long-term` - 长期记忆
- `POST /api/memory/long-term` - 添加长期记忆

### 提示词
- `GET /api/prompts` - 获取提示词列表
- `POST /api/prompts` - 创建提示词
- `PUT /api/prompts/{id}` - 更新提示词

### 行为分析
- `GET /api/behaviors/stats` - 获取行为统计
- `GET /api/behaviors/intents` - 意图分布

### 计费
- `GET /api/billing/usage` - 获取用量
- `GET /api/billing/cost` - 获取成本
- `GET /api/billing/budget` - 获取预算状态

## 插件扩展点

插件支持以下 8 种扩展点类型：

| 扩展点类型 | 用途 |
|-----------|------|
| `tool` | 注册工具供 Agent 调用 |
| `hook` | 拦截处理链中的事件 |
| `command` | 注册命令到 CLI |
| `route` | 注册 API 路由 |
| `event_handler` | 订阅系统事件 |
| `scheduler` | 定时任务 |
| `middleware` | 请求/响应中间件 |
| `data_provider` | 提供结构化数据 |

## 测试

```bash
# 后端测试
cd backend
python -m pytest

# 前端单元测试
cd frontend
npm run test

# 前端类型检查
npm run typecheck

# E2E 测试（需先启动后端）
cd frontend
npm run e2e
```

## 代码质量

```bash
# 后端 ruff 检查
cd backend
ruff check .

# 后端 mypy 类型检查
mypy . --ignore-missing-imports

# 前端 ESLint
cd frontend
npx eslint src/ --ext .ts,.tsx
```

## 文档

详细文档请参考：
- [插件开发手册](docs/plugin-developer-handbook/)
- [OpenClaw 研究报告](docs/openclaw-research.md)
- [项目规范](.trae/specs/)

## 许可证

MIT License

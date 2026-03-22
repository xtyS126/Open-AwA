# Open-AwA AI Agent Framework

基于 OpenClaw 架构的 AI 智能体框架，支持 Skill、MCP、工具调用、提示词配置、用户行为分析、记忆系统等核心功能。

## 特性

- **AI 智能体核心**：理解 → 规划 → 执行 → 反馈的完整闭环
- **Skill 系统**：可扩展的技能插件体系
- **MCP 支持**：Model Context Protocol 原生集成
- **工具调用**：统一的工具注册和执行机制
- **记忆系统**：短期 + 长期三层记忆架构
- **安全隔离**：多级沙箱和权限控制
- **行为分析**：完整的用户行为追踪和统计
- **提示词管理**：动态提示词模板配置
- **插件系统**：热插拔的插件架构

## 技术栈

**后端**
- Python 3.11+
- FastAPI
- SQLAlchemy
- JWT 认证
- Loguru 日志

**前端**
- React 18
- TypeScript
- Vite
- Zustand
- Recharts

## 快速开始

### 后端启动

```bash
cd backend

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

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

前端将在 http://localhost:3000 启动

## 项目结构

```
backend/
├── core/               # 核心引擎
│   ├── agent.py       # AI 智能体主控制器
│   ├── comprehension.py  # 理解层
│   ├── planner.py      # 规划层
│   ├── executor.py     # 执行层
│   └── feedback.py     # 反馈层
├── api/               # API 路由
│   └── routes/        # 路由模块
├── memory/            # 记忆系统
├── security/          # 安全模块
└── main.py           # 应用入口

frontend/
├── src/
│   ├── components/   # React 组件
│   ├── pages/         # 页面
│   ├── services/      # API 服务
│   ├── stores/        # 状态管理
│   └── styles/        # 样式
└── package.json
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
- `DELETE /api/skills/{id}` - 卸载技能

### 插件
- `GET /api/plugins` - 获取插件列表
- `POST /api/plugins` - 安装插件
- `DELETE /api/plugins/{id}` - 卸载插件

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

## UI 设计

采用扁平化设计风格：
- 主色调：浅灰 (#F5F5F5) + 深灰 (#333333)
- 强调色：低饱和度蓝 (#5B8DEF)
- 圆角：8-12px
- 无阴影或轻微阴影

## 核心模块

### 理解层 (Comprehension Layer)
- 意图识别
- 实体提取
- 参数解析

### 规划层 (Planning Layer)
- 任务分解
- 工具选择
- 依赖分析

### 执行层 (Execution Layer)
- 工具调用
- 结果处理
- 错误恢复

### 反馈层 (Feedback Layer)
- 结果评估
- 响应生成
- 记忆更新

## 安全特性

- JWT 认证
- RBAC 权限控制
- 操作审计日志
- 敏感操作确认
- 危险命令检测

## 扩展性

- 支持多语言模型（OpenAI, Claude, DeepSeek 等）
- 预留多渠道接入接口
- 自定义工具注册
- 插件热加载

## 文档

详细文档请参考：
- [OpenClaw 研究报告](docs/openclaw-research.md)
- [项目规范](.trae/specs/ai-agent-framework/spec.md)

## 许可证

MIT License

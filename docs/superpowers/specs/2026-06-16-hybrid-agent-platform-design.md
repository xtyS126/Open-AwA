# Open-AwA 混合 AI Agent 平台演进设计

> 创建时间：2026-06-16
> 状态：已批准

---

## 一、项目定位

Open-AwA 定位为**本地优先的 AI Agent 混合平台**，融合 IDE 编程能力与 IM 网关能力，核心差异化是 **AI 角色定制 + 交互数据收集**。

### 目标用户场景

1. **开发者编程助手** — AI Agent 自主完成编码、调试、重构
2. **个人办公自动化** — AI Agent 自动执行邮件、日程、文档处理
3. **跨平台消息管理** — AI Agent 统一管理多个 IM 平台的消息和自动回复
4. **业务工作流自动化** — AI Agent 编排和执行复杂业务工作流
5. **AI 角色扮演与数据收集** — 定制 AI 角色，收集交互数据用于优化和分析

### 核心差异化

相比 OpenClaw（IM 网关为主）和 Trae Work（AI IDE 为主），Open-AwA 的差异化在于：

- **AI 角色定制系统** — 用户可创建具有不同角色、性格、知识库的 AI Agent，远超简单的 system prompt 定制
- **交互数据收集管道** — 系统化收集 Agent 交互数据，用于角色优化、行为分析和训练数据生成
- **混合能力** — 一个平台同时提供 IDE 编程和 IM 网关能力，而非割裂的两个产品

### 部署模式

本地优先（Local-First），所有数据存储在用户本地设备，核心能力离线可用。

---

## 二、演进策略

采用**方案 A：渐进增强**，在现有 FastAPI + React 架构上逐步演进，不重写核心。

### 四阶段路线

| 阶段 | 主题 | 核心交付物 |
|------|------|-----------|
| **阶段 1** | Agent 核心强化 + 角色定制 | 强自主 Agent 引擎、AI 角色模板系统、交互数据收集管道 |
| **阶段 2** | IDE 能力补齐 | Monaco Editor 集成、文件树、终端面板、SOLO/Builder 模式 |
| **阶段 3** | IM 网关扩展 | 多渠道适配器框架、Telegram/飞书/钉钉接入、统一消息路由 |
| **阶段 4** | 生态与可视化 | 技能市场、角色市场、工作流可视化编排 |

每个阶段独立可交付，前一阶段的产出是后一阶段的基础。

---

## 三、架构总览

```
+-----------------------------------------------------+
|                   前端 (React)                        |
|  +----------+ +----------+ +--------------------+    |
|  | 聊天界面  | | IDE 面板  | | IM 渠道管理面板    |    |
|  | (已有)    | | (阶段2)   | | (阶段3)            |    |
|  +----------+ +----------+ +--------------------+    |
|  +----------+ +----------+ +--------------------+    |
|  | 角色管理  | | 工作流   | | 数据看板           |    |
|  | (阶段1)   | | (阶段4)  | | (阶段1)            |    |
|  +----------+ +----------+ +--------------------+    |
+-----------------------------------------------------+
|                   后端 (FastAPI)                      |
|  +-----------------------------------------------+   |
|  |           Agent 核心引擎 (阶段1 增强)            |   |
|  |  理解层 -> 规划层 -> 执行层 -> 反馈层            |   |
|  |  + 自主纠错 + 回滚补偿 + 指数退避重试            |   |
|  +-----------------------------------------------+   |
|  +----------+ +----------+ +--------------------+    |
|  | 角色引擎  | | IM 网关  | | 数据收集管道       |    |
|  | (阶段1)   | | (阶段3)  | | (阶段1)            |    |
|  +----------+ +----------+ +--------------------+    |
|  +----------+ +----------+ +--------------------+    |
|  | 技能系统  | | 插件系统 | | 记忆系统 (增强)     |    |
|  | (阶段4)   | | (已有)   | |                    |    |
|  +----------+ +----------+ +--------------------+    |
+-----------------------------------------------------+
```

---

## 四、阶段 1：Agent 核心强化 + 角色定制

### 4.1 强自主 Agent 引擎

#### 现状问题

当前 Agent 执行层缺少自主纠错、回滚补偿、指数退避重试等能力，长任务容易中断需要频繁人工干预。

#### 增强内容

| 能力 | 设计 | 涉及文件 |
|------|------|---------|
| **自主纠错循环** | 执行步骤失败后，Agent 自动诊断错误原因，生成修复计划，重新执行。最多 3 轮纠错，超出则请求人工介入 | `core/executor.py`, `core/feedback.py`, `core/planner.py` |
| **步骤级回滚** | 每个步骤执行前保存快照（文件变更、状态变更），失败时自动回滚到上一个稳定状态 | 新增 `core/rollback.py` |
| **指数退避重试** | 替换当前的单次重试，改为指数退避 + 随机抖动（base=2s, max=60s, jitter=0.1） | 新增 `core/retry.py` |
| **全局超时控制** | 单步骤超时 30s，单任务超时 300s，可配置 | `core/executor.py`, `config/settings.py` |
| **降级策略** | 主模型失败时自动切换到备用模型（从 model_service 配置读取 fallback 列表） | `core/agent.py`, `core/model_service.py` |
| **计划确认 UI** | 后端 `requires_confirmation` 字段已存在，前端实现确认对话框，用户可批准/修改/拒绝执行计划 | 前端新增确认对话框组件 |

#### 自主纠错流程

```
步骤执行 -> 成功? -> 继续
    |
    v 失败
错误诊断 (feedback.py diagnose_error)
    |
    v
生成修复计划 (planner.py generate_fix_plan)
    |
    v
回滚到快照 (rollback.py restore_snapshot)
    |
    v
重新执行修复计划
    |
    v
纠错次数 < 3? -> 是 -> 回到"步骤执行"
    |
    v 否
请求人工介入
```

#### 后端改动清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `core/executor.py` | 修改 | 增加纠错循环、全局超时、降级策略调用 |
| `core/feedback.py` | 修改 | 增加自动诊断和修复建议生成 |
| `core/planner.py` | 修改 | 增加"修复计划"生成能力 |
| `core/agent.py` | 修改 | 集成降级策略、角色引擎 |
| `core/rollback.py` | 新增 | 步骤快照和回滚管理 |
| `core/retry.py` | 新增 | 退避重试策略 |
| `config/settings.py` | 修改 | 新增超时和重试相关配置项 |

#### 前端改动清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `features/chat/components/PlanConfirmDialog.tsx` | 新增 | 计划确认对话框 |
| `features/chat/components/TaskTracker.tsx` | 修改 | 增加纠错/回滚状态展示 |

### 4.2 AI 角色定制系统

#### 数据模型

```python
class AgentRole(Base):
    __tablename__ = "agent_roles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    avatar_url: Mapped[str] = mapped_column(String(500), default="")

    # 角色核心定义
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    personality: Mapped[dict] = mapped_column(JSON, default=dict)
    # personality 结构: {
    #   "tone": "professional|casual|friendly|strict",
    #   "verbosity": "concise|normal|detailed",
    #   "creativity": 0.0-1.0,
    #   "formality": 0.0-1.0
    # }
    expertise: Mapped[dict] = mapped_column(JSON, default=dict)
    # expertise 结构: {
    #   "domains": ["coding", "writing", "analysis"],
    #   "languages": ["python", "typescript"],
    #   "specialties": ["code-review", "architecture"]
    # }

    # 知识绑定
    knowledge_base_ids: Mapped[dict] = mapped_column(JSON, default=list)

    # 工具权限
    allowed_tools: Mapped[dict] = mapped_column(JSON, default=list)
    allowed_skills: Mapped[dict] = mapped_column(JSON, default=list)

    # 模型配置
    model_config: Mapped[dict] = mapped_column(JSON, default=dict)
    # model_config 结构: {
    #   "preferred_model": "gpt-4",
    #   "fallback_model": "gpt-3.5-turbo",
    #   "temperature": 0.7,
    #   "max_tokens": 4096
    # }

    # 元数据
    creator_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
```

#### 角色模板预设

| 模板名 | system_prompt 要点 | personality | expertise | 典型场景 |
|--------|-------------------|-------------|-----------|---------|
| 代码审查专家 | 严格审查代码质量、安全性、性能 | strict, concise, creativity=0.2 | coding, code-review | 代码审查 |
| 办公助手 | 高效处理文档、邮件、日程 | casual, concise, creativity=0.3 | writing, scheduling | 日常办公 |
| 技术顾问 | 深度分析架构设计和技术选型 | professional, detailed, creativity=0.5 | architecture, analysis | 架构设计 |
| 数据分析师 | 专注数据处理、可视化、统计 | professional, normal, creativity=0.4 | data-analysis, visualization | 数据分析 |
| 创意写作 | 富有创意的文案和内容创作 | friendly, detailed, creativity=0.9 | writing, creative | 内容创作 |

#### 角色引擎工作流

```
用户选择角色
    |
    v
角色引擎加载角色配置 (role_engine.py)
    |
    v
注入 system_prompt 到 Agent
    |
    v
约束工具权限 (只允许 allowed_tools + allowed_skills)
    |
    v
应用模型配置 (preferred_model, temperature, max_tokens)
    |
    v
绑定知识库 (从 knowledge_base_ids 加载上下文)
    |
    v
Agent 开始工作
```

#### 后端改动清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `api/routes/roles.py` | 新增 | 角色 CRUD + 切换 + 预设模板 API |
| `core/role_engine.py` | 新增 | 角色引擎（加载配置、注入 prompt、约束权限、绑定知识库） |
| `db/models.py` | 修改 | 新增 AgentRole 模型 |
| `api/schemas.py` | 修改 | 新增 RoleCreate/RoleResponse/RoleUpdate Schema |
| `core/agent.py` | 修改 | 集成角色引擎，支持角色切换 |
| `main.py` | 修改 | 注册角色路由 |

#### API 设计

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/roles` | GET | 获取所有角色列表 |
| `/api/roles/{role_id}` | GET | 获取角色详情 |
| `/api/roles` | POST | 创建新角色 |
| `/api/roles/{role_id}` | PUT | 更新角色配置 |
| `/api/roles/{role_id}` | DELETE | 删除角色 |
| `/api/roles/presets` | GET | 获取预设角色模板列表 |
| `/api/roles/{role_id}/activate` | POST | 激活角色（绑定到当前会话） |

#### 前端改动清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `features/roles/RolesPage.tsx` | 新增 | 角色管理页面（列表、创建、编辑、删除） |
| `features/roles/RoleEditor.tsx` | 新增 | 角色编辑器（可视化配置性格、知识库、工具权限） |
| `features/roles/RoleCard.tsx` | 新增 | 角色卡片组件 |
| `features/chat/components/RoleSelector.tsx` | 新增 | 聊天界面角色选择器 |
| `shared/api/rolesApi.ts` | 新增 | 角色 API 调用封装 |
| `shared/types/role.ts` | 新增 | 角色类型定义 |
| `App.tsx` | 修改 | 新增 `/roles` 路由 |

### 4.3 交互数据收集管道

#### 收集的数据类型

| 数据类型 | 内容 | 存储表 | 用途 |
|----------|------|--------|------|
| 对话记录 | 完整对话上下文 + 角色信息 | conversation_data | 角色行为分析 |
| 工具调用日志 | 工具名、参数、结果、耗时 | tool_call_data | 工具使用模式分析 |
| 执行轨迹 | 规划->执行->反馈完整链路 | execution_trace | Agent 能力评估 |
| 用户反馈 | 点赞/点踩、修正建议 | user_feedback | 角色质量优化 |
| 角色切换事件 | 切换时间、源角色、目标角色 | role_switch_event | 使用习惯分析 |

#### 数据模型

```python
class ConversationData(Base):
    __tablename__ = "conversation_data"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(64))
    role_id: Mapped[str] = mapped_column(String(64))
    user_message: Mapped[str] = mapped_column(Text)
    assistant_message: Mapped[str] = mapped_column(Text)
    tools_used: Mapped[dict] = mapped_column(JSON, default=list)
    model_used: Mapped[str] = mapped_column(String(100))
    token_count: Mapped[dict] = mapped_column(JSON, default=dict)
    response_time_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

class ToolCallData(Base):
    __tablename__ = "tool_call_data"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(64))
    role_id: Mapped[str] = mapped_column(String(64))
    tool_name: Mapped[str] = mapped_column(String(100))
    tool_params: Mapped[dict] = mapped_column(JSON)
    result_summary: Mapped[str] = mapped_column(Text)
    success: Mapped[bool] = mapped_column(Boolean)
    duration_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

class ExecutionTrace(Base):
    __tablename__ = "execution_trace"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(64))
    role_id: Mapped[str] = mapped_column(String(64))
    plan_steps: Mapped[dict] = mapped_column(JSON)
    executed_steps: Mapped[dict] = mapped_column(JSON)
    error_steps: Mapped[dict] = mapped_column(JSON, default=list)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    rollback_count: Mapped[int] = mapped_column(Integer, default=0)
    total_duration_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

class UserFeedback(Base):
    __tablename__ = "user_feedback"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(64))
    message_id: Mapped[str] = mapped_column(String(64))
    role_id: Mapped[str] = mapped_column(String(64))
    feedback_type: Mapped[str] = mapped_column(String(20))  # "positive" | "negative"
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

class RoleSwitchEvent(Base):
    __tablename__ = "role_switch_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    from_role_id: Mapped[str] = mapped_column(String(64))
    to_role_id: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
```

#### 数据收集器设计

```python
class DataCollector:
    """异步数据收集器，不阻塞主流程"""

    def __init__(self, db_session_factory):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._session_factory = db_session_factory
        self._running = False

    async def start(self) -> None:
        """启动后台写入任务"""
        self._running = True
        asyncio.create_task(self._write_loop())

    async def collect_conversation(self, data: ConversationData) -> None:
        """收集对话数据（非阻塞）"""
        await self._queue.put(("conversation", data))

    async def collect_tool_call(self, data: ToolCallData) -> None:
        """收集工具调用数据（非阻塞）"""
        await self._queue.put(("tool_call", data))

    async def _write_loop(self) -> None:
        """后台批量写入循环"""
        while self._running:
            batch = []
            try:
                # 等待第一条数据
                item = await asyncio.wait_for(self._queue.get(), timeout=5.0)
                batch.append(item)
                # 批量收集更多数据
                while not self._queue.empty() and len(batch) < 50:
                    batch.append(self._queue.get_nowait())
            except asyncio.TimeoutError:
                continue

            if batch:
                await self._write_batch(batch)
```

#### 后端改动清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `data/collector.py` | 新增 | 异步数据收集器 |
| `data/schemas.py` | 新增 | 数据收集 Schema 定义 |
| `data/models.py` | 新增 | 数据收集相关 ORM 模型 |
| `api/routes/data.py` | 新增 | 数据查询和导出 API |
| `core/agent.py` | 修改 | 在关键节点调用数据收集器 |
| `core/executor.py` | 修改 | 在工具调用和执行轨迹处调用数据收集器 |
| `main.py` | 修改 | 注册数据路由，初始化数据收集器 |

#### 数据查询 API

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/data/stats` | GET | 数据统计概览 |
| `/api/data/conversations` | GET | 对话记录查询（支持按角色、时间范围筛选） |
| `/api/data/tool-calls` | GET | 工具调用日志查询 |
| `/api/data/execution-traces` | GET | 执行轨迹查询 |
| `/api/data/feedback` | GET | 用户反馈查询 |
| `/api/data/export` | POST | 数据导出（JSON/CSV 格式） |

#### 前端改动清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `features/data/DataDashboard.tsx` | 新增 | 数据看板（交互统计、角色使用分布、工具调用热力图） |
| `features/chat/components/FeedbackButtons.tsx` | 新增 | 对话消息的点赞/点踩按钮 |
| `shared/api/dataApi.ts` | 新增 | 数据 API 调用封装 |
| `App.tsx` | 修改 | 新增 `/data` 路由 |

---

## 五、阶段 2：IDE 能力补齐

### 5.1 IDE 布局

采用可分栏的面板布局，类似 VS Code 的经典三栏结构：

```
+--------------------------------------------------+
|  顶部导航栏（角色选择 | 模式切换 | 渠道状态）      |
+--------+-------------------------+---------------+
|        |                         |               |
| 文件树  |     编辑器 / 聊天面板    |   AI 助手面板  |
|        |     (Monaco Editor)     |  (角色对话)    |
|        |     (聊天界面)           |               |
|        |                         |               |
+--------+-------------------------+---------------+
|  终端面板 (xterm.js)                              |
+--------------------------------------------------+
```

### 5.2 核心组件

| 组件 | 技术选型 | 说明 |
|------|---------|------|
| 代码编辑器 | Monaco Editor (@monaco-editor/react) | VS Code 同款编辑器，支持语法高亮、智能补全、多标签 |
| 文件树 | 自研组件 + 后端文件管理 API | 复用现有 `file_manager.py`，前端新增树形展示 |
| 终端面板 | xterm.js + 后端 PTY | 复用现有 `terminal_executor.py`，通过 WebSocket 传输 |
| AI 助手面板 | 现有聊天组件重构 | 支持代码上下文注入（选中代码/当前文件自动附加） |

### 5.3 SOLO / Builder 双模式

| 模式 | 行为 | 类比 |
|------|------|------|
| SOLO 模式 | Agent 自主完成整个任务，用户只给目标，Agent 自行规划、编码、测试、修复 | 类似 Trae SOLO |
| Builder 模式 | Agent 逐步执行，每步展示计划并等待用户确认/修改后执行 | 类似 Trae Builder |

实现方式：
- SOLO 模式：`requires_confirmation=False`，Agent 连续执行直到完成或遇到不可恢复错误
- Builder 模式：`requires_confirmation=True`，每个步骤/阶段暂停等待用户确认
- 前端通过模式切换按钮控制，后端通过参数控制确认行为

### 5.4 后端改动清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `api/routes/files.py` | 新增 | 文件树浏览 API（列出目录、读取文件、写入文件） |
| `api/routes/terminal.py` | 新增 | WebSocket 终端会话 API |
| `core/builtin_tools/file_manager.py` | 修改 | 增强（支持目录遍历、批量操作） |
| `core/builtin_tools/terminal_executor.py` | 修改 | 增强（PTY 模式、WebSocket 桥接） |

### 5.5 前端改动清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `features/ide/IdeLayout.tsx` | 新增 | IDE 整体布局 |
| `features/ide/FileTree.tsx` | 新增 | 文件树组件 |
| `features/ide/CodeEditor.tsx` | 新增 | Monaco Editor 封装 |
| `features/ide/TerminalPanel.tsx` | 新增 | xterm.js 终端 |
| `features/ide/ModeSwitcher.tsx` | 新增 | SOLO/Builder 模式切换 |
| `App.tsx` | 修改 | 新增 `/ide` 路由 |

---

## 六、阶段 3：IM 网关扩展

### 6.1 适配器架构

```
+-------------------------------------------+
|            IM 网关层                       |
|  +----------+ +----------+ +---------+    |
|  |Telegram  | |  飞书     | |  钉钉   |    |
|  |Adapter   | |  Adapter | | Adapter |    |
|  +----+-----+ +----+-----+ +----+----+    |
|       |            |            |          |
|  +----+------------+------------+--------+ |
|  |       统一消息路由器                  | |
|  |  (消息标准化 + 会话映射 + 角色分发)   | |
|  +------------------+---------------------+ |
+---------------------+-----------------------+
                      |
              +-------+-------+
              |  Agent 引擎    |
              |  (角色系统)    |
              +---------------+
```

### 6.2 适配器接口

```python
class IMAdapter(ABC):
    """IM 渠道适配器基类"""

    @abstractmethod
    async def start(self) -> None:
        """启动适配器，建立与 IM 平台的连接"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """停止适配器，断开连接"""
        ...

    @abstractmethod
    async def send_message(self, chat_id: str, text: str) -> None:
        """发送消息到 IM 平台"""
        ...

    @abstractmethod
    async def receive_message(self) -> AsyncGenerator[IMMessage, None]:
        """接收来自 IM 平台的消息流"""
        ...

class IMMessage:
    """统一的 IM 消息格式"""
    message_id: str
    chat_id: str
    sender_id: str
    sender_name: str
    content: str
    channel: str  # "telegram" | "feishu" | "dingtalk"
    timestamp: datetime
    metadata: dict  # 渠道特有的元数据
```

### 6.3 优先接入渠道

| 渠道 | 优先级 | 理由 |
|------|--------|------|
| Telegram | P0 | Bot API 最成熟，开发成本最低 |
| 飞书 | P0 | 国内企业用户多，开放 API 完善 |
| 钉钉 | P1 | 国内企业用户多，与飞书互补 |

### 6.4 后端改动清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `im/adapter_base.py` | 新增 | 适配器基类和统一消息格式 |
| `im/router.py` | 新增 | 统一消息路由器 |
| `im/telegram_adapter.py` | 新增 | Telegram 适配器 |
| `im/feishu_adapter.py` | 新增 | 飞书适配器 |
| `im/dingtalk_adapter.py` | 新增 | 钉钉适配器 |
| `im/session_mapper.py` | 新增 | IM 会话与 Agent 会话映射 |
| `api/routes/im.py` | 新增 | IM 渠道管理 API |
| `main.py` | 修改 | 注册 IM 路由，启动适配器 |

### 6.5 前端改动清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `features/im/ImChannelsPage.tsx` | 新增 | 渠道配置和管理页面 |
| `features/chat/components/ChannelBadge.tsx` | 新增 | 消息来源渠道标识 |
| `shared/api/imApi.ts` | 新增 | IM API 调用封装 |
| `App.tsx` | 修改 | 新增 `/im` 路由 |

---

## 七、阶段 4：生态与可视化

### 7.1 技能市场

- 用户可发布/安装/评分技能
- 后端新增 `api/routes/marketplace.py`
- 前端新增 `features/marketplace/MarketplacePage.tsx`

### 7.2 角色市场

- 用户可发布/安装/评分 AI 角色
- 复用技能市场的架构模式
- 前端新增 `features/marketplace/RoleMarketPage.tsx`

### 7.3 工作流可视化编排

- 拖拽式 DAG 编辑器（基于 React Flow）
- 节点类型：工具调用、条件分支、并行网关、子工作流
- 前端新增 `features/workflow/WorkflowEditor.tsx`

---

## 八、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 阶段 1 改动范围大，可能引入回归 | 高 | 每个子能力独立开发，完成后运行完整测试套件 |
| Monaco Editor 集成可能影响前端性能 | 中 | 懒加载 IDE 组件，仅在 `/ide` 路由加载 |
| IM 适配器依赖第三方 SDK 稳定性 | 中 | 适配器隔离运行，单个渠道故障不影响其他渠道 |
| 数据收集可能影响主流程性能 | 低 | 异步写入 + 批量提交，不阻塞主流程 |
| 角色系统复杂度可能超预期 | 中 | 先实现核心能力（prompt + 工具权限），知识库绑定后续迭代 |

---

## 九、成功指标

| 指标 | 阶段 1 目标 | 最终目标 |
|------|-----------|---------|
| Agent 自主完成率（无需人工干预） | >= 60% | >= 80% |
| 角色切换响应时间 | < 2s | < 1s |
| 数据收集延迟（不影响主流程） | < 100ms | < 50ms |
| 支持 IM 渠道数 | 0 | >= 3 |
| IDE 模式可用性 | 不适用 | 支持 SOLO + Builder |
| 技能/角色市场内容数 | 0 | >= 20 预设 |

# Open-AwA Project Guidelines

Open-AwA 是一个 AI Agent 实验性平台（FastAPI + React）。详细说明见 [README.md](README.md) 和 [PROJECT_DOCUMENTATION.md](PROJECT_DOCUMENTATION.md)。

---

## Build and Test

### Backend (Python 3.11+, FastAPI)

```bash
cd backend
pip install -r requirements.txt          # 生产依赖
pip install -r requirements-dev.txt      # 开发依赖（含 pytest）
python main.py                           # 启动服务 (uvicorn, 端口 8000)
pytest                                   # 运行测试
pytest -v --cov                          # 详细输出 + 覆盖率
```

### Frontend (Node.js, React 18 + Vite)

```bash
cd frontend
npm install
npm run dev                              # 开发服务器 (端口 5173)
npm run build                            # TypeScript 检查 + Vite 构建
npm run test                             # Vitest 单元测试
npm run test:coverage                    # 覆盖率报告 (阈值 90%)
npm run lint                             # ESLint
npm run e2e                              # Playwright E2E 测试
```

---

## Architecture

```
backend/
  main.py          # 入口：中间件、路由注册、数据库初始化
  api/routes/      # 业务路由（/api/auth, /chat, /skills, /plugins, /memory, /billing 等）
  api/schemas.py   # Pydantic 请求/响应模型
  api/dependencies.py  # OAuth2 + DB session 注入
  core/            # Agent 核心（agent, planner, executor, comprehension, feedback）
  db/models.py     # SQLAlchemy ORM 模型
  billing/         # 计费模块（定价、预算、用量）
  memory/          # 记忆与经验管理
  plugins/         # 插件系统（生命周期、沙箱、热更新、CLI）
  security/        # 审计日志、权限控制、沙箱隔离
  skills/          # 技能引擎与经验提取
  config/          # 配置（settings, security, logging）

frontend/src/
  features/        # 按功能模块组织（chat, dashboard, settings, skills, plugins, memory, billing, experiences）
  shared/          # 公共模块（api, store, hooks, components, types, utils）
  __tests__/       # 单元测试
```

详细架构说明见 [docs/架构/后端架构说明.md](docs/架构/后端架构说明.md) 和 [docs/架构/前端架构说明.md](docs/架构/前端架构说明.md)。
部署指南见 [docs/指南/部署与运行说明.md](docs/指南/部署与运行说明.md)，测试策略见 [docs/指南/测试说明.md](docs/指南/测试说明.md)。
插件开发见 [docs/插件开发手册/](docs/插件开发手册/)。

### ACP Vibe Coding 集成

ACP（Agent Client Protocol）是一套用于调用本地 vibe coding 应用的开放协议。Open-AwA 作为 ACP Host，通过子进程方式拉起 Claude Code、Codex、OpenClaw、OpenCode 等 CLI Agent，并以 SSE 流式方式把 Agent 事件回传给前端，实现统一的 vibe coding 体验。

关键文件：

- `backend/acp_host/` - ACP 核心模块
  - `core.py` - 共享数据结构与异常层级（`ACPAgentConfig`/`ACPConfig`/`SuspendedPermission`/`ACPErrors` 异常族）
  - `client.py` - 托管客户端 `ACPHostedClient`，处理 ACP 协议事件分发与 permission 挂起-恢复
  - `service.py` - `ACPService` 服务层，管理子进程生命周期、prompt 轮次与模块级单例注册表
  - `permissions.py` - 权限审批适配器与硬阻断安全策略
  - `tool_adapter.py` - 工具调用事件渲染适配
  - `agents/` - 内置 Agent 配置目录（`claude_code.py`/`codex.py`/`openclaw.py`/`opencode.py`）
- `backend/api/routes/acp.py` - ACP REST API 路由（`/api/acp/agents`、`/sessions`、SSE prompt 等）
- `backend/core/terminal/` - VT100 仿真器与 PTY 持久会话
  - `vt_screen.py` - ANSI/SGR 转义序列解析与字符网格维护
  - `pty_session.py` - PTY 进程封装与屏幕快照
- `backend/api/routes/preview_proxy.py` - 反向代理（用于本地开发服务器预览，SSRF 防护）
- `backend/api/routes/notifications.py` - 通知 HTTP API（用于 Claude Code hooks 集成）
- `backend/static/claude-code-hooks.json` - Claude Code hooks 配置模板
- `frontend/src/features/vibe-coding/` - 前端三栏布局页面（Agent 选择 / 会话面板 / 终端 / 文件预览）

---

## Code Style

### Absolute Rules

1. **All code comments MUST be in Chinese** -- 文件头注释、函数注释、关键逻辑行内注释均用中文
2. **Emoji is strictly prohibited everywhere** -- 源码、注释、文档、commit message、配置、日志中一律不得使用 emoji
   - 用 `[DONE]` 代替完成标记，用 `[Fix]` 代替 bug 标记，用 `[NEW]` 代替新功能标记

### Backend Conventions

- Classes: `PascalCase`，Functions/variables: `snake_case`
- Routes are `async def`，DB models extend `Base`，schemas extend `BaseModel`
- Pydantic schemas use `Create`/`Response` suffix variants（如 `SkillCreate`, `SkillResponse`）
- Config class sets `from_attributes = True` for ORM-to-schema conversion
- Dependencies via `Depends(get_db)` and `Depends(get_current_user)`
- Logging via Loguru with `request_id` context from middleware

### Frontend Conventions

- Components: `PascalCase` with `Page` suffix for route pages（如 `ChatPage`, `SettingsPage`）
- Stores: `use` prefix（如 `useAuthStore`, `useChatStore`），使用 Zustand
- API modules: feature-specific files（如 `modelsApi.ts`, `billingApi.ts`）
- CSS Modules: `[FeatureName].module.css`
- Path alias: `@/` maps to `src/`
- Test files in `__tests__/` mirror the src structure

---

## Known Pitfalls

- **Blocking ORM in async**: `ExperienceManager` 中 `async def` 调用同步 SQLAlchemy 查询，可能阻塞事件循环
- **SQLite FK not enforced by default**: 外键约束需要在连接参数中显式启用
- **Vector DB path is relative**: `VECTOR_DB_PATH = "./data/vector_db"`，工作目录不同会导致路径问题
- **Billing tables init required**: `PricingManager.ensure_configuration_schema()` 必须在 lifespan startup 中执行
- **SECRET_KEY auto-generated**: 不设置环境变量时自动生成，生产环境必须显式配置
- **Chat supports both SSE and WebSocket**: 修改聊天功能时需同时测试两条路径
- **Plugin Manager is a singleton**: 通过 `plugins.plugin_instance.get()` 获取，不要直接 `PluginManager()` 创建新实例
- **Conversation history auto-injected**: Agent 自动从 ShortTermMemory 加载对话历史，无需手动传递
- **Backend root directory file scatter**: backend 根目录散落了 14+ 个独立脚本（`replace_file.py`、`elevate_script.ps1`、`grant_perm.ps1` 等），这些是一次性迁移辅助脚本，不属于应用代码。后续路线图将统一迁移到 `scripts/` 目录。新增脚本不应放在根目录。
- **ACP SDK 是可选依赖**: `acp` Python SDK 缺失时 `ACPService` 优雅降级，状态管理方法（`get_session`/`close_chat_session`/`cancel_turn`）仍可用，但 `run_turn`/`resume_permission` 抛 `ACPConfigurationError`
- **pywinpty 仅 Windows 需要**: POSIX 系统使用标准库 `pty`，Windows 使用 `pywinpty` 提供 PTY 能力
- **ACP 会话隔离**: 按 `chat_id = f"{user_id}:{session_id}"` 隔离，每个 `(chat_id, agent)` 组合对应一个 `_Conversation` 实例
- **ACP Permission 挂起-恢复**: 使用 `asyncio.Future` + `SuspendedPermission` 载体实现，用户审批后通过 `resolve_permission` 恢复执行
- **ACP 硬阻断安全策略**: `rm -rf /`、`sudo rm -rf`、`mkfs`、`dd if=` 命令子串直接拒绝执行，不进入用户审批流程
- **ACP 进程树清理**: 使用 `psutil.Process.children(recursive=True)` 递归 kill 子进程，psutil 不可用时回退到 POSIX `os.kill` 或 Windows `taskkill /T`

---

## Git Commit Rules

### Pre-commit Checklist（强制执行，不可跳过）

Before `git add` and `git commit`, complete in order:

1. **OCR AI 审查（必须第 1 步）** -- 运行 `.\scripts\code-audit.ps1 -SkipTests` 对未提交变更进行 AI 审查
   - 如果审查发现问题，修复后重新运行审计，直到通过
   - 如果审查通过，继续下一步
2. **Style check** -- 命名规范、注释完整（中文）、无 Emoji
3. **Run tests** -- 全部测试通过，新功能有对应测试，覆盖率不降低
4. **Dependency check** -- 新增依赖版本兼容，`requirements.txt` / `package.json` 已同步更新
5. **Document update** -- 功能变更更新 README.md，接口变更更新 API 文档
6. **git commit** -- 在完成一个模块的迭代并检查后提交到 main 分支

### OCR Viewer 自动化代码审计

在完成每个重构阶段后，运行 OCR Viewer 代码审计脚本对未提交变更进行自动审查：

```powershell
# 完整审计（前端 + 后端）
.\scripts\code-audit.ps1

# 仅前端审计
.\scripts\code-audit.ps1 -FrontendOnly

# 仅后端审计
.\scripts\code-audit.ps1 -BackendOnly

# 跳过测试（快速检查）
.\scripts\code-audit.ps1 -SkipTests

# 详细模式（显示完整 diff）
.\scripts\code-audit.ps1 -Verbose
```

审计脚本自动执行以下检查：
1. Git 状态 — 变更文件列表与分类统计
2. Emoji 违规 — Unicode 表情符号检测
3. 调试代码残留 — `console.log/debug/info`、`debugger` 语句
4. 前端检查 — TypeScript 类型检查 + ESLint
5. 前端测试 — Vitest 单元测试
6. 后端测试 — pytest
7. 注释规范 — 新增注释使用中文

审计通过（exit 0）→ 执行 `git commit`；审计失败（exit 1）→ 根据报告修复问题后重新审计。

### 阶段化重构工作流

对于多阶段任务（如前端重构方案），每完成一个阶段按以下流程推进：

```
阶段N 代码完成
  → 运行 .\scripts\code-audit.ps1
  → 审计通过? 
      [否] → 根据 reports/audit-result.txt 修复问题 → 重新审计
      [是] → git add -A && git commit -m "[Refactoring] 阶段N: xxx"
          → 进入阶段 N+1
```

所有阶段完成后运行一次完整测试：
```bash
cd frontend && npm run test:coverage && cd ..
cd backend && pytest -v --cov && cd ..
```

### Commit Message Format

```
[Type] Concise description of the change
```

| Type | Description |
|------|-------------|
| `[New]` | New Feature |
| `[Fix]` | Fix Bug |
| `[Optimization]` | Code optimization, performance improvement |
| `[Refactoring]` | Code refactoring, without affecting functionality |
| `[Documentation]` | Documentation Updates |
| `[Test]` | Test-related changes |
| `[Configuration]` | Configuration file change |
| `[Remove]` | Remove a function or file |
| `[Dependency]` | Dependency Updates |

```bash
# Correct
git commit -m "[New] User login interface add captcha verification"
git commit -m "[Fix] Fix duplicate data in paginated order list query"

# Wrong (prohibited)
git commit -m "update"          # too vague
git commit -m "fix bug"         # not specific
```
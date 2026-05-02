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

---

## Git Commit Rules

### Pre-commit Checklist

Before `git add` and `git commit`, complete in order:
1. **Code review** -- 逐文件检查：无语法错误、无调试代码残留、无硬编码敏感信息
2. **Style check** -- 命名规范、注释完整（中文）、无 Emoji
3. **Run tests** -- 全部测试通过，新功能有对应测试，覆盖率不降低
4. **Dependency check** -- 新增依赖版本兼容，`requirements.txt` / `package.json` 已同步更新
5. **Document update** -- 功能变更更新 README.md，接口变更更新 API 文档
6. **git commit** -- 在完成一个模块的迭代并检查后提交本地的debug分支

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
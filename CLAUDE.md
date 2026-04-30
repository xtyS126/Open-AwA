# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build and Development Commands

### Backend (Python 3.11+, FastAPI)

```bash
cd backend
pip install -r requirements.txt          # 生产依赖
pip install -r requirements-dev.txt      # 开发依赖（含 pytest）
python main.py                           # 启动服务 (uvicorn, 端口 8000)
pytest                                   # 运行测试
pytest -v --cov                          # 详细输出 + 覆盖率
```

### Frontend (Node.js 18+, React 18 + Vite)

```bash
cd frontend
npm install
npm run dev                              # 开发服务器 (端口 5173)
npm run build                            # TypeScript 检查 + Vite 构建
npm run test                             # Vitest 单元测试
npm run test:coverage                    # 覆盖率报告 (阈值 90%)
npm run lint                             # ESLint
npm run typecheck                        # TypeScript 类型检查 (tsc --noEmit)
npm run e2e                              # Playwright E2E 测试
```

## Architecture Overview

Open-AwA is an AI Agent experimental platform with a **FastAPI backend** and **React frontend**, following a microkernel + plugin architecture.

### Backend Layers (in main.py startup order)

1. **Logging init** — Loguru, request ID injection, sanitization
2. **DB init** — SQLAlchemy tables, billing schema, default pricing, RBAC roles, local user sync, built-in skills seed
3. **Plugin system init** — PluginManager singleton lifecycle (discover → load enabled plugins)
4. **Route registration** — 20+ route modules mounted (auth, chat, skills, plugins, memory, workflows, prompts, behavior, billing, market, security, weixin, MCP, subagents, etc.)
5. **Scheduled task manager** — started during lifespan, stopped on shutdown
6. **Shared HTTP client** — closed on shutdown

### Agent Core Flow (AIAgent.process)

```
comprehension.py → planner.py → executor.py → feedback.py
```
- Conversation history auto-injected from ShortTermMemory (no manual passing needed)
- Supports both SSE (HTTP) and WebSocket paths
- Tools executed with idempotency_key for deduplication

### Key Subsystems

| System | Directory | Key Files |
|--------|-----------|-----------|
| Agent Core | `backend/core/` | `agent.py`, `comprehension.py`, `planner.py`, `executor.py`, `feedback.py` |
| Plugin System | `backend/plugins/` | `plugin_manager.py`, `plugin_instance.py` (singleton), `base_plugin.py`, `plugin_sandbox.py` |
| Skill System | `backend/skills/` | `skill_engine.py`, `skill_executor.py`, `skill_registry.py` |
| Memory | `backend/memory/` | `manager.py`, `experience_manager.py`, `vector_store_manager.py` |
| Billing | `backend/billing/` | `tracker.py`, `pricing_manager.py`, `engine.py`, `calculator.py` |
| MCP Protocol | `backend/mcp/` | `client.py`, `manager.py` (thread-safe singleton), `transport.py`, `protocol.py` |
| Security | `backend/security/` | `rbac.py`, `audit.py`, `permission.py`, `sandbox.py` |
| Workflow | `backend/workflow/` | `engine.py`, `parser.py` |

### Frontend Structure

- `src/features/` — Feature modules (chat, dashboard, skills, plugins, memory, billing, experiences, settings, scheduledTasks, auth, user)
- `src/shared/` — Shared: `api/`, `components/`, `store/`, `hooks/`, `types/`, `utils/`
- `src/__tests__/` — Unit tests mirroring the feature structure
- State: Zustand stores (`useAuthStore`, `useChatStore`, `useThemeStore`)
- API: Axios with `withCredentials` for Cookie-based auth; path alias `@/` → `src/`

## Code Conventions

### Mandatory

1. **All code comments MUST be in Chinese** — file headers, function comments, inline comments
2. **Emoji is strictly prohibited everywhere** — source, comments, docs, commits, config, logs. Use `[DONE]`, `[Fix]`, `[NEW]` instead.

### Backend

- Classes: `PascalCase`, functions/variables: `snake_case`
- Routes: `async def`; DB models extend `Base`; schemas extend `BaseModel`
- Pydantic schemas: `Create`/`Response` suffix variants (e.g., `SkillCreate`, `SkillResponse`)
- Config class: `from_attributes = True` for ORM-to-schema conversion
- Dependencies: `Depends(get_db)` and `Depends(get_current_user)`
- Logging: Loguru with `request_id` context from middleware

### Frontend

- Components: `PascalCase` with `Page` suffix for routes (e.g., `ChatPage`, `SettingsPage`)
- Stores: `use` prefix (e.g., `useAuthStore`, `useChatStore`), using Zustand
- API modules: feature-specific files (e.g., `modelsApi.ts`, `billingApi.ts`)
- CSS Modules: `[FeatureName].module.css`
- Test files in `__tests__/` mirror the src structure

### Commit Message Format

```
[Type] Concise description of the change
```
Types: `[New]`, `[Fix]`, `[Optimization]`, `[Refactoring]`, `[Documentation]`, `[Test]`, `[Configuration]`, `[Remove]`, `[Dependency]`

## Known Pitfalls

- **Blocking ORM in async**: `ExperienceManager` uses sync SQLAlchemy queries in `async def`, may block the event loop
- **SQLite FK not enforced by default**: Foreign key constraints need explicit connection parameter
- **Vector DB path is relative**: `VECTOR_DB_PATH` resolves relative to `backend/`, can break if working directory changes
- **Plugin Manager is a singleton**: Use `plugins.plugin_instance.get()`, never create `PluginManager()` directly
- **SECRET_KEY auto-generated in dev**: Must be explicitly set as env var in production; auto-generation persists to `.env.local`
- **Billing tables require init**: `PricingManager.ensure_configuration_schema()` must run in lifespan startup
- **Chat supports both SSE and WebSocket**: Changes to chat must test both paths
- **Conversation history auto-injected**: Agent pulls from ShortTermMemory by `session_id`, don't manually pass

## API Path Prefix

All API routes use prefix `settings.API_V1_STR` (`/api`) except MCP, billing, marketplace, security, weixin, tools, and subagents which use their own prefixes. See `main.py` lines 386-407 for the full registration list.

## Key Documentation

- [AGENTS.md](AGENTS.md) — Extended build/test commands, architecture details, code style, and more pitfalls
- [README.md](README.md) — Project overview, capabilities, quick start
- [PROJECT_DOCUMENTATION.md](PROJECT_DOCUMENTATION.md) — Detailed technical documentation
- [docs/backend-architecture.md](docs/backend-architecture.md) — Backend architecture details
- [docs/frontend-architecture.md](docs/frontend-architecture.md) — Frontend architecture details
- [docs/deployment.md](docs/deployment.md) — Deployment guide
- [docs/testing.md](docs/testing.md) — Testing strategy
- [docs/plugin-developer-handbook/](docs/plugin-developer-handbook/) — Plugin development guide

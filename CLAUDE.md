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
pytest path/to/test.py -k "test_name"    # 运行单个测试
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
4. **Route registration** — 20+ route modules mounted (auth, chat, skills, plugins, memory, workflows, prompts, behavior, billing, market, security, weixin, MCP, subagents, system diagnostics, test runner)
5. **Scheduled task manager** — started during lifespan, stopped on shutdown
6. **Shared HTTP client** — closed on shutdown

### Agent Core Flow (AIAgent.process)

```
comprehension.py → planner.py → executor.py → feedback.py
```
- Conversation history auto-injected from ShortTermMemory (`session_id` key, no manual passing needed)
- Supports both SSE (HTTP) and WebSocket paths
- Tools executed with `idempotency_key` for deduplication
- LLM calls loop up to 5 tool-calling rounds (call → tool_calls → execute → append results → re-call)
- `context["_tools"]` carries native OpenAI function-calling tool definitions; `context["agent_capabilities"]` carries the text summary

### Key Subsystems

| System | Directory | Key Files |
|--------|-----------|-----------|
| Agent Core | `backend/core/` | `agent.py`, `comprehension.py`, `planner.py`, `executor.py`, `feedback.py` |
| Plugin System | `backend/plugins/` | `plugin_manager.py`, `plugin_instance.py` (singleton), `base_plugin.py`, `plugin_sandbox.py`, `plugin_lifecycle.py` (state machine), `hot_update_manager.py` (blue-green) |
| Skill System | `backend/skills/` | `skill_engine.py`, `skill_executor.py`, `skill_registry.py`, `skill_loader.py` |
| Memory | `backend/memory/` | `manager.py`, `experience_manager.py`, `vector_store_manager.py` |
| Billing | `backend/billing/` | `tracker.py`, `pricing_manager.py`, `engine.py`, `calculator.py` |
| MCP Protocol | `backend/mcp/` | `client.py`, `manager.py` (thread-safe singleton), `transport.py`, `protocol.py` |
| Security | `backend/security/` | `rbac.py`, `audit.py`, `permission.py`, `sandbox.py` |
| Scheduled Tasks | `backend/core/` | `scheduled_task_manager.py` (polling loop + transactional claims) |
| Model Service | `backend/core/` | `model_service.py` (litellm adapter + shared httpx client) |
| Subagents | `backend/core/` | `subagent.py` (StateGraph executor) |
| Workflow | `backend/workflow/` | `engine.py`, `parser.py` |
| System Diagnostics | `backend/api/routes/` | `system.py` (health checks), `test_runner.py` (10 scenario E2E tests) |

### Frontend Structure

- `src/features/` — Feature modules (chat, dashboard, skills, plugins, memory, billing, experiences, settings, scheduledTasks, auth, user, test)
- `src/shared/` — Shared: `api/`, `components/`, `store/`, `hooks/`, `types/`, `utils/`
- `src/__tests__/` — Unit tests mirroring the feature structure
- State: Zustand stores (`useAuthStore`, `useChatStore`, `useThemeStore`)
- API: Axios with `withCredentials` for Cookie-based auth; path alias `@/` → `src/`

## Adding a New API Route (Backend)

1. Create `backend/api/routes/my_feature.py` with an `APIRouter`
2. Import in `main.py`: `from api.routes.my_feature import router as my_router`
3. Register in `main.py`: `app.include_router(my_router)` (or `app.include_router(my_router, prefix=settings.API_V1_STR)` for `/api` prefix)
4. Use `Depends(get_current_user)` for auth-protected endpoints, `Depends(get_db)` for DB access
5. If no auth needed (like `/health`), skip dependency injection

## System Diagnostics and Test Runner

Two diagnostic layers are available, both designed for automated validation:

- **`GET /api/system/ping`** — No-auth lightweight connectivity probe
- **`GET /api/system/diagnostics`** — Auth-required checks DB/plugins/skills/MCP status, returns `healthy` or `degraded`
- **`GET /api/test-scenarios`** — Lists 10 real E2E test scenarios
- **`POST /api/test-scenarios/run`** — Runs one named scenario (body: `{"name": "chat-nonstream"}`)
- **`POST /api/test-scenarios/run-all`** — Runs all 10 scenarios, returns pass/fail report

Test scenarios exercise real production code paths (AIAgent, conversation CRUD, plugin discovery, etc.), not mocked. Use these for Claude Code-triggered validation.

## Plugin System Architecture

### Lifecycle State Machine

Eight states with explicit valid transitions in `plugin_lifecycle.py`: `REGISTERED → LOADED → ENABLED ↔ DISABLED → UNLOADED`, plus `UPDATING` and `ERROR`. Each state transition calls the corresponding hook on the plugin instance (`on_registered`, `on_loaded`, etc.). Failed transitions trigger automatic rollback.

### Blue-Green Hot Update

`hot_update_manager.py` implements zero-downtime updates via active/standby slots. `prepare_update()` loads the new version into standby; `commit_update()` atomically swaps. Supports gated rollout (percentage/user-list/region-based) and snapshot-based rollback (last 10 versions, in-memory only).

### Singleton Access

Always use `plugins.plugin_instance.get()` to access the PluginManager. Never create `PluginManager()` directly. `get()` auto-creates an uninitialized instance if `init()` was never called, so startup order matters.

### Sandbox

`plugin_sandbox.py` wraps plugin execution with `asyncio.wait_for` timeout control. Resource limits (memory/CPU) are applied via `resource.setrlimit` on Unix or `psutil` on Windows. The default timeout is 60 seconds.

## MCP vs Plugin Manager

They serve different purposes:
- **PluginManager** — Manages local Python plugin modules (discovery, lifecycle, sandboxed execution, hooks). Plugins are Python classes.
- **MCPManager** — Manages external MCP server processes (stdio/SSE transport). Has no sandbox, no lifecycle state machine, no skill integration. Stores server configs on disk with hot-reload. Uses double-checked locking singleton.

MCP tool names follow the pattern `mcp_{server_id}/{tool_name}` for dispatch in `executor._execute_tool_call()`.

## Chat Protocol Details

- **SSE** — Uses two event types: default `data:` for content tokens, `event: reasoning` with `data:` for thinking tokens. The frontend tracks the `event:` field between `data:` lines.
- **WebSocket** — Splits large messages (>1024 bytes) into chunked JSON frames with checksums. Supports `"message"` and `"confirm"` message types. Both paths call the same `AIAgent.process()`.
- **Streaming retry** — Frontend retries on network errors up to 1 time, but only if zero data was received (partial data = throw immediately, no retry).

## Security Architecture

- **JWT blacklist** — Tokens carry a `jti` (UUID4). On logout, the jti is blacklisted in the DB and auto-expires after `ACCESS_TOKEN_EXPIRE_MINUTES`.
- **Fernet encryption** — `SECRET_KEY` is SHA256-hashed to derive a Fernet key for encrypting sensitive values (API keys). Values with prefix `enc:` are idempotently re-encrypted (won't double-encrypt).
- **Password hashing** — pbkdf2_sha256 (600K rounds) for new, bcrypt (12 rounds) for legacy. Both verified.
- **Cookie + CSRF** — Access token in HttpOnly cookie (`SameSite=lax`). Frontend fetches `/api/auth/csrf-token` and attaches `X-CSRF-Token` on state-changing requests. `/auth/login` and `/auth/register` are exempt.

## Scheduled Task Isolation

Scheduled tasks run in an isolated agent context (`scheduled_execution_isolated: True`, dedicated `session_id`). They do NOT write to conversation history or memory. The manager uses 2-second polling with transactional claim (`UPDATE ... WHERE status='pending'` as row-level lock) to prevent duplicate execution. Daily tasks auto-reschedule to the next cron match; on crash recovery, orphaned "running" tasks reset to "pending."

## Model Service Patterns

- **Per-provider request building** — `build_provider_request()` constructs completely different payloads for OpenAI-compatible, Anthropic, Google Gemini, and Ollama.
- **Thinking depth mapping** — 0-5 depth converts to provider-specific params: `reasoning_effort` (OpenAI o-series), `budget_tokens` (Anthropic), boolean flag (DeepSeek R1).
- **Shared HTTP client** — `get_shared_client()` returns a singleton `httpx.AsyncClient` (100 max connections, 20 keepalive). All LLM API calls go through it. Closed on shutdown.
- **Retry** — 3 attempts with exponential backoff (`0.2s * 2^attempt`) on retryable status codes (408/409/425/429/5xx) and network errors.

## Frontend SSE Parsing

`chatAPI.sendMessageStream` manually parses SSE via `fetch` + `ReadableStream` (not Axios). It has its own buffer-based line parser that handles partial reads and tracks `event:` type to split reasoning vs content tokens. Streaming events include `chunk`, `status`, `plan`, `result`, `task`, `tool`, and `usage`.

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
- **Plugin hot update state is ephemeral**: Snapshots and active/standby slots are in-memory only, lost on restart
- **Windows ACL restrictions**: Some directories have restrictive permissions; use elevated PowerShell to replace existing files when tools fail with EPERM

## API Path Prefix

All API routes use prefix `settings.API_V1_STR` (`/api`) except MCP, billing, marketplace, security, weixin, tools, subagents, system (diagnostics), and test-scenarios which use their own prefixes. See `main.py` lines 390-417 for the full registration list.

## Key Documentation

- [AGENTS.md](AGENTS.md) — Extended guidelines, pre-commit checklist, git rules
- [README.md](README.md) — Project overview, capabilities, quick start
- [PROJECT_DOCUMENTATION.md](PROJECT_DOCUMENTATION.md) — Detailed technical documentation
- [docs/backend-architecture.md](docs/backend-architecture.md) — Backend architecture details
- [docs/frontend-architecture.md](docs/frontend-architecture.md) — Frontend architecture details
- [docs/deployment.md](docs/deployment.md) — Deployment guide
- [docs/testing.md](docs/testing.md) — Testing strategy
- [docs/plugin-developer-handbook/](docs/plugin-developer-handbook/) — Plugin development guide

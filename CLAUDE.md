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

## Automated Verification & Self-Healing Workflow

Claude Code 在完成代码修改后，必须通过真实操作验证代码可行性，并在测试失败时自主诊断、修复并重新测试，形成"修改 → 验证 → 修复 → 重测"的闭环。本节定义该闭环的标准流程。

### Service Lifecycle Management（服务生命周期管理）

验证前必须确保后端服务运行。服务管理命令：

```bash
# 启动后端（端口 8000，后台运行，日志输出到 backend/logs/）
cd backend
python main.py

# 启动前端开发服务器（端口 5173，仅前端验证时需要）
cd frontend
npm run dev
```

服务健康检查（无需认证，用于快速探测服务是否存活）：

```bash
# 轻量连通性探测 — 返回 {"pong": true, "timestamp": ...}
curl http://localhost:8000/api/system/ping

# 完整系统诊断（需认证）— 检查 DB/插件/技能/MCP 子系统
curl -H "Authorization: Bearer <TOKEN>" http://localhost:8000/api/system/diagnostics
```

启动判定规则：
- `GET /api/system/ping` 在 30 秒内返回 200 且 `pong=true` → 服务就绪
- 超时或连接拒绝 → 检查 `backend/logs/` 下的启动日志，定位启动失败原因（端口占用、DB 初始化失败、插件加载异常等）

### Authentication & API Access（认证与 API 访问）

OpenAwA 后端采用 **API Key 优先** 认证策略（见 `backend/api/dependencies.py` `get_current_user`）：

1. **路径 1（主认证，推荐）**：`Authorization: Bearer <OPENAWA_API_KEY>` — API Key 匹配后直接返回 owner 用户，跳过 JWT 解析和黑名单检查
2. **路径 2（兼容降级）**：JWT Bearer token（来自 `/api/auth/login`）— 仅用于前端浏览器会话兼容
3. **路径 3（兼容降级）**：HttpOnly Cookie — 仅用于前端浏览器会话兼容

> **API Key 是首选认证方式**，自动化测试、CLI 工具、浏览器扩展均应使用 API Key，无需用户名密码登录。
> 用户名密码登录仅用于前端 Web UI 会话（HttpOnly Cookie + CSRF），后端服务进程不应使用。

#### API Key 获取

```bash
# 方式 1：生成新 API Key（写入 backend/.env.local）
cd backend && python generate_api_key.py

# 方式 2：从现有配置读取
grep OPENAWA_API_KEY backend/.env.local
```

API Key 必须至少 32 字符，未配置时后端拒绝启动。

#### 使用 API Key 调用 API

```bash
# 所有受保护接口只需携带 Authorization 头
curl -H "Authorization: Bearer <OPENAWA_API_KEY>" http://localhost:8000/api/system/diagnostics

# 状态变更接口（POST/PUT/PATCH/DELETE）同样只需 Authorization，无需 CSRF token
curl -X PUT -H "Authorization: Bearer <OPENAWA_API_KEY>" \
     -H "Content-Type: application/json" \
     -d '{"key":"value"}' \
     http://localhost:8000/api/plugins/<id>/config
```

#### JWT 登录（仅前端 Web UI 使用）

前端浏览器会话仍使用 JWT + Cookie + CSRF，登录流程：

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=<USER>&password=<PWD>"
```

返回 `access_token` + `csrf_token`，前端通过 HttpOnly Cookie 自动管理会话。**此路径不适用于自动化测试和 CLI 工具。**

### Real Operation Verification Procedure（真实操作验证流程）

完成代码修改后，按以下顺序执行真实操作验证。每一步通过后才进入下一步；任一步骤失败则进入下文的 Self-Healing Bug Fix Loop（自主修 Bug 循环）。

#### 步骤 1：静态检查（快速失败，无需启动服务）

```powershell
# OCR AI 审查 + lint + typecheck，跳过测试以加速反馈
.\scripts\code-audit.ps1 -SkipTests
```

- 通过 → 进入步骤 2
- 失败 → 进入自愈循环

#### 步骤 2：单元测试（验证代码逻辑正确性）

```bash
# 后端单元测试
cd backend && pytest -x --tb=short

# 前端单元测试
cd frontend && npm run test
```

- 全部通过 → 进入步骤 3
- 失败 → 进入自愈循环，针对失败的测试用例定位修复

#### 步骤 3：服务启动验证（验证服务能正常拉起）

```bash
# 启动后端服务（后台运行）
cd backend && python main.py &

# 等待服务就绪（最多 30 秒轮询）
curl --retry 5 --retry-delay 2 --retry-connrefused http://localhost:8000/api/system/ping
```

- `pong=true` → 进入步骤 4
- 启动失败 → 检查 `backend/logs/` 日志，进入自愈循环

#### 步骤 4：E2E 场景验证（通过 test-scenarios 运行真实业务路径）

系统内置 10 个真实 E2E 测试场景（定义在 `backend/api/routes/test_runner.py`），覆盖：服务健康、系统诊断、对话生命周期、非流式聊天、插件发现、技能列表、文件工具、定时任务、用户会话、MCP 状态。

```bash
# 使用 API Key 认证（从 backend/.env.local 读取）
API_KEY=$(grep OPENAWA_API_KEY backend/.env.local | cut -d'=' -f2- | tr -d '"')

# 列出所有可用场景（无需认证）
curl -s http://localhost:8000/api/test-scenarios

# 运行全部 10 个场景（API Key 认证，返回 passed/failed/total 汇总）
curl -s -X POST http://localhost:8000/api/test-scenarios/run-all \
  -H "Authorization: Bearer $API_KEY"

# 运行单个场景（如非流式聊天）
curl -s -X POST http://localhost:8000/api/test-scenarios/run \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "chat-nonstream"}'
```

场景列表：
| 场景名 | 类别 | 验证内容 |
|--------|------|----------|
| `health-basic` | 基础设施 | `/health` 端点可达 |
| `diagnostics-full` | 基础设施 | DB/插件/技能/MCP 全量诊断 |
| `conversation-lifecycle` | 对话管理 | 创建→重命名→软删除→恢复 |
| `chat-nonstream` | AI 聊天 | AIAgent.process 返回有效响应 |
| `plugin-discovery` | 插件系统 | 插件发现与已加载列表 |
| `skills-list` | 技能系统 | 技能列表与启用状态 |
| `tool-file-operation` | 工具调用 | 文件列表与读取工具 |
| `scheduled-task-lifecycle` | 定时任务 | 创建→查询→取消 |
| `auth-session-valid` | 身份认证 | 当前用户会话有效 |
| `mcp-status` | MCP 服务 | MCP 服务器连接状态 |

- `failed=0` → 进入步骤 5
- `failed>0` → 进入自愈循环，针对失败场景定位修复

#### 步骤 5：API 集成测试（使用 api-testing skill 覆盖全部路由模块）

项目内置 `api-testing` skill（位于 `backend/skills/external/api-testing/`），通过 YAML 定义测试用例，覆盖全部 24+ API 路由模块。

```bash
# 运行全部 API 集成测试（生成 Markdown + JSON 报告）
cd backend/skills/external/api-testing
python -m core

# 报告输出到 reports/ 目录
# - reports/api-test-report-<timestamp>.md（人类可读）
# - reports/api-test-report-<timestamp>.json（机器可读）
```

- 全部通过 → 进入步骤 6
- 失败 → 进入自愈循环

#### 步骤 6：前端构建验证

```bash
cd frontend && npm run build
```

- 构建成功且无警告 → 验证完成，可提交
- 构建失败 → 进入自愈循环

### Self-Healing Bug Fix Loop（自主修 Bug 循环）

当任一验证步骤失败时，Claude Code 必须自主执行以下闭环，最多迭代 3 次：

```
[失败] → 诊断根因 → 应用最小修复 → 重跑失败用例 → [通过?]
                                                      [是] → 重跑完整验证流程
                                                      [否] → 迭代次数 +1
                                                            [迭代<3] → 继续诊断
                                                            [迭代=3] → 停止，向用户报告
```

#### 诊断阶段

1. **捕获完整失败信息**：读取测试输出的完整错误堆栈、失败用例名、断言期望值与实际值
2. **定位根因**：
   - 单元测试失败 → 用 `Read` 打开失败测试文件，理解断言逻辑 → 用 `Grep` 找到被测函数实现 → 对比期望与实际
   - E2E 场景失败 → 读取场景返回的 `detail` 字段 → 定位 `backend/api/routes/test_runner.py` 中对应场景函数 → 追踪到实际业务代码
   - 服务启动失败 → 读取 `backend/logs/` 下的启动日志 → 定位异常堆栈
   - 静态检查失败 → 读取 `reports/audit-result.txt` 和 `reports/ocr-review.txt`
3. **区分失败类型**：
   - 代码缺陷 → 修复实现
   - 测试本身错误（断言过时、mock 不匹配）→ 修复测试
   - 环境问题（依赖缺失、端口占用）→ 修复环境

#### 修复阶段

1. **最小修复原则**：只修改导致失败的代码，不重构、不优化、不扩大改动范围
2. **保持类型安全**：Python 函数完整类型标注，TypeScript 禁用 `any`
3. **保持中文注释**：新增注释必须中文，无 emoji
4. **不引入新依赖**：除非失败原因明确是缺少依赖

#### 重测阶段

1. **先重跑失败的单个用例**（快速验证修复有效）：
   ```bash
   # 后端单个测试
   cd backend && pytest tests/test_xxx.py::test_function_name -x --tb=short

   # 前端单个测试
   cd frontend && npm run test -- --run src/__tests__/xxx.test.ts

   # 单个 E2E 场景（使用 API Key）
   API_KEY=$(grep OPENAWA_API_KEY backend/.env.local | cut -d'=' -f2- | tr -d '"')
   curl -s -X POST http://localhost:8000/api/test-scenarios/run \
     -H "Authorization: Bearer $API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"name": "<失败的场景名>"}'
   ```
2. **单用例通过后，重跑完整验证流程**（步骤 1-6）确保修复未引入回归
3. **记录修复过程**：在最终报告中说明根因和修复方案

#### 终止条件与用户报告

达到以下任一条件时停止自愈循环：
- 所有验证步骤通过 → 验证成功，可提交代码
- 迭代 3 次仍未通过 → 停止，向用户报告

用户报告必须包含：
- 失败的验证步骤和具体用例名
- 根因分析（定位到文件和行号）
- 已尝试的修复方案及每次修复后的测试结果
- 失败的完整错误输出（截取关键部分）
- 建议的下一步操作（如需用户介入的环境问题、需讨论的设计决策等）

### Verification Checklist（提交前验证清单）

在执行 `git commit` 前，必须确认以下全部通过：

- [ ] 步骤 1：`.\scripts\code-audit.ps1 -SkipTests` 静态检查通过
- [ ] 步骤 2：后端 `pytest` + 前端 `npm run test` 全部通过
- [ ] 步骤 3：后端服务启动且 `GET /api/system/ping` 返回 `pong=true`
- [ ] 步骤 4：`POST /api/test-scenarios/run-all` 返回 `failed=0`
- [ ] 步骤 5：`api-testing` skill 全部 API 集成测试通过
- [ ] 步骤 6：前端 `npm run build` 构建成功无警告
- [ ] 自愈循环（如有失败）未超过 3 次迭代
- [ ] OCR 完整审计 `.\scripts\code-audit.ps1` 通过（含测试）

### Common Failure Patterns（常见失败模式与快速定位）

| 失败现象 | 快速定位 | 修复方向 |
|----------|----------|----------|
| 服务启动后立即退出 | `backend/logs/` 启动日志 | 检查 DB 连接、端口占用、插件加载 |
| `chat-nonstream` 场景失败 | 场景返回的 `detail.response_preview` | 检查 LLM API Key 配置、`model_service.py` |
| `conversation-lifecycle` 失败 | `core/conversation_sessions.py` | 检查 DB session 提交、外键约束 |
| `plugin-discovery` 失败 | `plugins/plugin_instance.get()` | 检查插件目录扫描、插件加载异常 |
| 认证 401 | `api/dependencies.py` `get_current_user` | 检查 token 过期、JWT 黑名单、Cookie 传递 |
| CSRF 403 | 请求头 `X-CSRF-Token` | 确认 state-changing 请求携带 CSRF token |
| 速率限制 429 | `RateLimitStore` | 测试中避免高频请求，或等待窗口重置 |
| 前端构建类型错误 | `tsc --noEmit` 输出 | 修复 TypeScript 类型，禁用 `any` |
| pytest 测试污染 | `conftest.py` fixture 隔离 | 确保测试间 DB 状态隔离，使用事务回滚 |

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
| Channels | `backend/channels/` | `manager.py` (connection pool), `base.py` (abstract adapter), 11 adapters: weixin, dingtalk, feishu, discord, telegram, slack, qq, matrix, imessage, wecom |
| Coding | `backend/core/coding/` | AST search, LSP integration, Git panel, Diff viewer |
| Scheduled Tasks | `backend/core/` | `scheduled_task_manager.py` (polling loop + transactional claims) |
| Model Service | `backend/core/` | `model_service.py` (litellm adapter + shared httpx client) |
| Subagents | `backend/core/` | `subagent.py` (StateGraph executor), task_runtime (multi-agent teams) |
| Workflow | `backend/workflow/` | `engine.py`, `parser.py` |
| Tools | `backend/tools/` | Tool registry, built-in tools (file, terminal, search, todo) |
| System Diagnostics | `backend/api/routes/` | `system.py` (health checks), `test_runner.py` (10 scenario E2E tests) |
| ACP Vibe Coding | `backend/acp_host/` | `core.py` (dataclasses + exceptions), `client.py` (ACPHostedClient), `service.py` (ACPService singleton), `permissions.py` (hard-block policy), `tool_adapter.py`, `agents/` (4 built-in agents) |

### Frontend Structure

- `src/features/` — Feature modules (chat, dashboard, skills, plugins, memory, billing, experiences, settings, scheduledTasks, auth, user, agents, coding, workspace, inbox, tts, search, test)
- `src/shared/` — Shared: `api/`, `components/`, `store/`, `hooks/`, `types/`, `utils/`
- `src/__tests__/` — Unit tests mirroring the feature structure
- `src/i18n/` — Internationalization (dynamic locale loading per language)
- State: Zustand stores (`useAuthStore`, `useChatStore`, `useThemeStore`)
- API: Axios with `withCredentials` for Cookie-based auth; path alias `@/` → `src/`

### Frontend Component Architecture Pattern

Feature modules follow a layered pattern to avoid circular dependencies and enable lazy loading:

```
features/settings/
  SettingsPage.tsx          # Route page (lazy-loaded by App.tsx)
  containers/               # Tab/modal containers (lazy-loaded, one per tab)
    ModelsTabContainer.tsx
    ApiTabContainer.tsx
    ...
  hooks/                    # Shared data hooks (cross-tab cache)
    useSharedSettingsData.ts
  modelsApi.ts              # API calls for this feature
```

- **Containers** wrap tab/modal content, loaded via `React.lazy()` + `Suspense` to avoid blocking the route page
- **Hooks** manage cross-tab shared state (e.g., `useSharedSettingsData` caches provider/config data once across all Settings tabs)
- **Zustand selectors** are atomized to single-field granularity (e.g., `useChatStore(s => s.streamingContent)` not object selectors) to minimize re-renders during streaming
- Components that receive stable props should be wrapped in `React.memo`

## Adding a New API Route (Backend)

1. Create `backend/api/routes/my_feature.py` with an `APIRouter`
2. Import in `main.py`: `from api.routes.my_feature import router as my_router`
3. Register in `main.py`: `app.include_router(my_router)` (or `app.include_router(my_router, prefix=settings.API_V1_STR)` for `/api` prefix)
4. Use `Depends(get_current_user)` for auth-protected endpoints, `Depends(get_db)` for DB access
5. If no auth needed (like `/health`), skip dependency injection

## System Diagnostics and Test Runner

> 完整的自动化验证流程见 [Automated Verification & Self-Healing Workflow](#automated-verification--self-healing-workflow)。本节为端点速查参考。

Two diagnostic layers are available, both designed for automated validation:

- **`GET /api/system/ping`** — No-auth lightweight connectivity probe
- **`GET /api/system/diagnostics`** — Auth-required checks DB/plugins/skills/MCP status, returns `healthy` or `degraded`
- **`GET /api/test-scenarios`** — Lists 10 real E2E test scenarios
- **`POST /api/test-scenarios/run`** — Runs one named scenario (body: `{"name": "chat-nonstream"}`)
- **`POST /api/test-scenarios/run-all`** — Runs all 10 scenarios, returns pass/fail report

Test scenarios exercise real production code paths (AIAgent, conversation CRUD, plugin discovery, etc.), not mocked. Use these for Claude Code-triggered validation.

## ACP Vibe Coding API

ACP（Agent Client Protocol）用于调用本地 vibe coding 应用（Claude Code / Codex / OpenClaw / OpenCode）。所有端点强制鉴权，会话按 `(user_id, session_id)` 隔离。

### ACP Agent 与会话端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/acp/agents` | 列出所有 agent + `available` 状态（同步探测包到线程池） |
| POST | `/api/acp/sessions` | 创建会话，body `{agent, cwd}`，返回 `session_id` |
| GET | `/api/acp/sessions` | 列出当前用户活动会话 |
| POST | `/api/acp/sessions/{id}/prompt` | 发起一轮 prompt，body `{prompt, restart?}`，SSE 流式响应 |
| POST | `/api/acp/sessions/{id}/permission` | 恢复 permission，body `{option_id}` |
| POST | `/api/acp/sessions/{id}/cancel` | 取消当前轮 |
| DELETE | `/api/acp/sessions/{id}` | 关闭并移除会话 |

SSE 事件类型：`text` | `tool` | `status` | `permission` | `usage` | `result` | `error`。客户端断开时后端自动调用 `ACPService.cancel_turn` 取消未完成的 prompt。

### 通知 API（Claude Code Hooks 集成）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/notifications` | 发送通知，body `{title, body, pane_id?, notification_type}` |
| GET | `/api/notifications?limit=N` | 列出最近 N 条通知（默认 50，最大 100） |
| GET | `/api/notifications/stream` | SSE 长连接，30s 心跳，实时推送 |

Hooks 模板见 `backend/static/claude-code-hooks.json`。

### 文件预览与反向代理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/coding/preview/file?path=<path>` | 按扩展名分发渲染（Markdown/图片/音视频/Office） |
| GET | `/api/preview/{port}/{path:path}` | 反向代理到 `127.0.0.1:{port}` |

SSRF 防护：`/api/preview/{port}/...` 拒绝 `port < 1024` 或 `> 65535`，强制目标主机为 `127.0.0.1`。

### 终端 PTY API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/terminal/sessions/{id}/snapshot` | 返回屏幕网格快照（cols/rows/grid） |
| WebSocket | `/terminal/ws/pty/{session_id}?token=...` | PTY 双向通信（input/output/resize/shell_info） |

注意：terminal 路由前缀为 `/terminal`（无 `/api` 前缀）。

## Plugin System Architecture

### Lifecycle State Machine

Eight states with explicit valid transitions in `plugin_lifecycle.py`: `REGISTERED → LOADED → ENABLED ↔ DISABLED → UNLOADED`, plus `UPDATING` and `ERROR`. Each state transition calls the corresponding hook on the plugin instance (`on_registered`, `on_loaded`, etc.). Failed transitions trigger automatic rollback.

### Blue-Green Hot Update

`hot_update_manager.py` implements zero-downtime updates via active/standby slots. `prepare_update()` loads the new version into standby; `commit_update()` atomically swaps. Supports gated rollout (percentage/user-list/region-based) and snapshot-based rollback (last 10 versions, in-memory only).

### Singleton Access

Always use `plugins.plugin_instance.get()` to access the PluginManager. Never create `PluginManager()` directly. `get()` auto-creates an uninitialized instance if `init()` was never called, so startup order matters.

### Sandbox

`plugin_sandbox.py` wraps plugin execution with `asyncio.wait_for` timeout control. Resource limits (memory/CPU) are applied via `resource.setrlimit` on Unix or `psutil` on Windows. The default timeout is 60 seconds.

## Channels System (Multi-IM Integration)

The channels system (`backend/channels/`) provides a unified abstraction for 11 IM platforms. Each platform implements the `ChannelAdapter` abstract base class:

- **Adapter pattern** — `base.py` defines `ChannelAdapter` (ABC), `ChannelMessage`, `ChannelConfig`. Each platform (weixin, dingtalk, feishu, discord, telegram, slack, qq, matrix, imessage, wecom) extends it.
- **Connection pool** — `ChannelManager` in `manager.py` manages lifecycle (connect/disconnect/health check) and message queuing for all registered adapters.
- **ChannelType enum** — Standardized platform identifiers used for routing and message dispatch.
- Route: `backend/api/routes/weixin.py` handles WeChat-specific webhooks; other channels route through their respective adapters.

Channels are distinct from MCP and Plugins — they are inbound message sources, not tool providers.

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

### Git Workflow

**所有提交直接推到 main 分支，不使用 debug 分支作为中间步骤。**
完成修改后直接 `git add` + `git commit` 到 main：
```bash
git add -A
git commit -m "[Type] 变更描述"
```
不使用 `debug` 分支，不创建中间分支。如果需要回滚，使用 `git revert`。

### OCR Viewer 自动化审计（每次提交前强制执行）

**每完成一个阶段或准备 git commit 前，必须先运行 OCR 审计，审查通过后才能提交。不可跳过此步骤。**

> OCR 审计是 [Automated Verification & Self-Healing Workflow](#automated-verification--self-healing-workflow) 步骤 1 的组成部分。完整提交前验证清单见 [Verification Checklist](#verification-checklist提交前验证清单)。

```powershell
# 完整审计（含 ocr AI 审查 + 测试）
.\scripts\code-audit.ps1

# 快速审计（仅 ocr + lint + typecheck，跳过测试）
.\scripts\code-audit.ps1 -SkipTests

# 仅前端/后端
.\scripts\code-audit.ps1 -FrontendOnly
.\scripts\code-audit.ps1 -BackendOnly
```

工作流：
```
代码完成 → .\scripts\code-audit.ps1 → 
  [FAIL] → 根据 reports/audit-result.txt 修复 → 重新审计
  [PASS] → git add -A && git commit -m "[Type] 描述"
```

审计报告输出到 `reports/audit-result.txt`，ocr 输出到 `reports/ocr-review.txt`。详细说明见 AGENTS.md。

## Known Pitfalls

- **Blocking ORM in async**: `ExperienceManager` uses sync SQLAlchemy queries in `async def`, may block the event loop
- **SQLite FK not enforced by default**: Foreign key constraints need explicit connection parameter
- **Vector DB path is relative**: `VECTOR_DB_PATH` resolves relative to `backend/`, can break if working directory changes
- **Plugin Manager is a singleton**: Use `plugins.plugin_instance.get()`, never create `PluginManager()` directly. Use `pm.has_plugin(name)` / `pm.is_plugin_loaded(name)` instead of `getattr(pm, "plugin_metadata", {})`.
- **SECRET_KEY auto-generated in dev**: Must be explicitly set as env var in production; auto-generation persists to `.env.local`
- **Billing tables require init**: `PricingManager.ensure_configuration_schema()` must run in lifespan startup
- **Chat supports both SSE and WebSocket**: Changes to chat must test both paths
- **Conversation history auto-injected**: Agent pulls from ShortTermMemory by `session_id`, don't manually pass
- **Plugin hot update state is ephemeral**: Snapshots and active/standby slots are in-memory only, lost on restart
- **Windows ACL restrictions**: Some directories have restrictive permissions; use elevated PowerShell to replace existing files when tools fail with EPERM
- **resolve_max_tool_call_rounds**: 定义在 `executor.py`，`agent.py` 通过 import 引用同一函数，不可重复定义
- **RBAC 通配符**: `check_permission` 支持 `skill:*` 匹配 `skill:read`，`*` 仅在同段数下生效
- **登录限流**: 通过 `RateLimitStore` 抽象层管理，`DatabaseRateLimitStore` 使用 `time.time()`（跨 worker 一致），`MemoryRateLimitStore` 使用 `time.monotonic()`（单进程不受时钟跳变影响）
- **模型参数 or 陷阱**: `getattr(config, "retry_count", 3) or 3` 会将 `0` 误判为未设置，必须使用 `is not None` 检查
- **SSRF 防护**: `BASE_URL` 校验拒绝内网/本地/链路本地 IP 地址，修改模型服务 URL 验证逻辑时需保持此检查
- **Tool calls 结果截断**: 过长的工具调用结果会被截断后再传给 LLM，修改截断阈值时注意上下文窗口限制
- **ACP SDK 缺失优雅降级**: `acp` Python SDK 是可选依赖，缺失时 `ACPService.run_turn`/`resume_permission` 抛 `ACPConfigurationError`，但状态管理方法（`get_session`/`close_chat_session`/`cancel_turn`）仍可正常工作
- **pywinpty 仅 Windows**: POSIX 系统用标准库 `pty`，Windows 用 `pywinpty` 提供 PTY 能力
- **ACP 会话隔离机制**: 按 `chat_id = f"{user_id}:{session_id}"` 隔离，每个 `(chat_id, agent)` 对应一个 `_Conversation` 实例，模块级 `_acp_services` 字典按 agent 标识索引 service 实例
- **ACP 硬阻断策略**: `rm -rf /`、`sudo rm -rf`、`mkfs`、`dd if=` 命令子串直接拒绝，不进入用户审批流程

## API Path Prefix

All API routes use prefix `settings.API_V1_STR` (`/api`) except MCP, billing, marketplace, security, weixin, tools, subagents, system (diagnostics), and test-scenarios which use their own prefixes. See `main.py` lines 390-417 for the full registration list.

## Key Documentation

- [AGENTS.md](AGENTS.md) — Extended guidelines, pre-commit checklist, git rules
- [README.md](README.md) — Project overview, capabilities, quick start
- [CODE_WIKI.md](CODE_WIKI.md) — Comprehensive code wiki (1500+ lines): six-layer architecture, full module deep-dives, class/function quick reference, dependency graph
- [PROJECT_DOCUMENTATION.md](PROJECT_DOCUMENTATION.md) — Detailed technical documentation
- [docs/架构/后端架构说明.md](docs/架构/后端架构说明.md) — Backend architecture details
- [docs/架构/前端架构说明.md](docs/架构/前端架构说明.md) — Frontend architecture details
- [docs/指南/部署与运行说明.md](docs/指南/部署与运行说明.md) — Deployment guide
- [docs/指南/测试说明.md](docs/指南/测试说明.md) — Testing strategy
- [docs/插件开发手册/](docs/插件开发手册/) — Plugin development guide

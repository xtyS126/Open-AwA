# CLAUDE.md

> 本文件是 Claude Code 在 Open-AwA 项目中长期自主迭代的**操作契约**。
> Claude Code 在每次进入项目前必须完整阅读本文件，并严格遵守其中的自主权边界、迭代节奏、验证闭环与记忆机制。
> 通用 AI Agent 规则（适用于 Cursor / Codex / 其他 IDE Agent）见 [AGENTS.md](AGENTS.md)。

---

## 0. Role & Mindset（角色与心智模型）

你不是"一次性任务执行者"，而是 Open-AwA 项目的**长期自主迭代者**。

- **目标视角**：每一次操作都要服务于"持续推动项目向前"的长期目标，而非仅完成眼前指令
- **风险视角**：每一次修改都要自问三件事——是否破坏现有功能？是否可回滚？是否沉淀了经验？
- **演进视角**：技术债务要主动识别并记录，但不擅自大规模重构；新功能要兼顾与现有架构的协调
- **协作视角**：把用户视为"产品 owner + 评审者"，把项目记忆视为"前一位迭代者留下的交接文档"

长期迭代的核心心态：**小步快走、闭环验证、沉淀经验、尊重历史**。

---

## 1. Autonomy Boundary（自主权边界）

### 1.1 可以自主执行（无需用户确认）

- `git add` + `git commit` 到 main 分支（**前提**：通过完整 6 步验证闭环）
- 重构核心模块（`agent` / `planner` / `executor` / `billing` / `memory` / `plugins` / `security`），前提是测试全通过且不破坏 API 兼容性
- 新增依赖（前提：通过 `pip audit` / `npm audit --audit-level=high`，且同步更新 `requirements.txt` / `package.json`）
- 修改测试用例（前提：覆盖率不降低，异常路径仍被覆盖）
- 更新文档（README / AGENTS.md / 架构文档 / API 文档）
- 修复 Known Pitfalls 中已记录的问题
- 沉淀新的硬约束、坑点到 `project_memory.md` 与本文件 Known Pitfalls

### 1.2 禁止自主执行（必须等用户确认）

- `git push` 到远程仓库（**任何分支**，包括 main）
- `git push --force` / `git reset --hard` / `git branch -D` / `git clean -f` 等破坏性操作
- 修改 `.env` / `.env.local` / 密钥文件 / 已存在的 Alembic 数据库迁移版本
- 删除用户数据 / 会话历史 / 记忆数据 / 向量库 / 计费记录
- 关闭正在运行的生产服务进程
- 跨越 1.3 节"谨慎执行"边界的大改动（见 1.3）

### 1.3 谨慎执行（先小步验证 + 影响面评估）

- **数据库 schema 变更**：先备份 → 写新 Alembic 迁移 → 本地测试升级与回滚 → 才能执行
- **API breaking change**：先 `Grep` 全仓引用 → 评估前端/测试/文档影响面 → 提供兼容层或同步更新所有调用方
- **安全相关代码**（`rbac.py` / `permission.py` / `sandbox.py` / `audit.py`）：改动必须新增对应测试用例
- **核心 Agent 流程**（`comprehension → planner → executor → feedback`）：改动必须跑通 `chat-nonstream` E2E 场景
- **SSE / WebSocket 聊天路径**：改动必须同时测试两条路径
- **Plugin 生命周期**：改动必须验证 `REGISTERED → LOADED → ENABLED ↔ DISABLED → UNLOADED` 状态机

---

## 2. Long-term Memory Protocol（长期记忆协议）

> 记忆机制是长期自主迭代的**强制流程**，不是可选项。AI 必须在迭代前读取、迭代后沉淀。

### 2.1 迭代前必读（每次新会话 / 新任务开始时）

按顺序读取以下记忆文件，提取与本任务相关的硬约束、坑点、用户偏好：

1. `c:\Users\23941\.trae-cn\memory\user_profile.md` — 用户偏好与技术栈
2. `c:\Users\23941\.trae-cn\memory\projects\-d----Open-AwA\project_memory.md` — 项目级硬约束
3. `c:\Users\23941\.trae-cn\memory\projects\-d----Open-AwA\<当日日期>\topics.md` — 近期任务上下文
4. 必要时用 `Grep` 在 `projects\-d----Open-AwA\` 下搜索关键词，追溯历史 session_memory

读取后必须在脑中明确：本任务相关的硬约束有哪些？哪些坑必须避开？用户偏好是什么？

### 2.2 迭代后必写（每次完成一个迭代单元后）

| 触发条件 | 写入位置 |
|---------|---------|
| 发现新的硬约束、不可绕过的规则 | `project_memory.md` 的 Hard Constraints |
| 发现新的坑点 / 陷阱 | `project_memory.md` + 本文件 Known Pitfalls |
| 完成一个有意义的任务（修复 / 重构 / 新功能） | 当日 `topics.md` 追加 `[session_id: xxx \| topic_summary_time: YYYY-MM-DD HH:MM:SS]` |
| 用户偏好或工作方式发生变化 | `user_profile.md` |
| 新增 / 修改了 API 接口 | 本文件 Architecture Overview + AGENTS.md |

写入格式必须遵循 `memory_item` 结构，时间戳用本地时间（北京时间）。

### 2.3 重复错误沉淀（强制）

若同一个错误在 3 次迭代中出现 ≥2 次，必须立即：

1. 在 `project_memory.md` 的 Hard Constraints 中新增条目
2. 在本文件 Known Pitfalls 中新增条目（含定位方法与修复方向）
3. 在下次迭代前的读取阶段主动 `Grep` 检查相关关键词
4. 在 commit message 中标注 `[Lesson]` 前缀

### 2.4 记忆冲突处理

当 `project_memory.md` 与本文件 / AGENTS.md 内容冲突时：

- **以本文件 / AGENTS.md 为准**（代码契约优先于历史记忆）
- 在 `project_memory.md` 中标注 `OUTDATED:` 前缀
- 在下次 commit 中同步更新本文件 / AGENTS.md

---

## 3. Task-Driven Iteration Loop（任务驱动迭代闭环）

### 3.1 单任务 6 步闭环

每个任务必须按以下 6 步顺序执行，**不可跳过任何一步**：

```
[1] 读记忆     → 读取 user_profile / project_memory / topics.md
[2] 规划       → TodoWrite 拆解子任务，标注优先级
[3] 实现       → 编辑代码，遵循 Code Conventions
[4] 测试验证   → 后端 pytest + 前端 npm run test
[5] 服务+E2E   → 启动后端 → /api/system/ping → run-all E2E → 前端 npm run build
[6] 沉淀记忆   → 更新 project_memory.md / topics.md / 本文件 pitfalls
```

任一步骤失败 → 进入第 5 节的 Self-Healing Bug Fix Loop。

### 3.2 Self-Healing 上限（硬性终止条件）

- 单个验证步骤失败时**最多自愈 3 次**
- 3 次仍失败 → **立即停止**，向用户报告，**不强行 commit**
- 报告必须包含：失败步骤、根因分析（定位到文件:行号）、已尝试方案、失败完整错误输出、建议下一步

### 3.3 任务切换规则

- 当前任务未通过验证闭环前，**不开启新任务**
- 例外：发现阻塞 bug 且不影响当前任务时，可记录到 TodoWrite 后继续当前任务
- 例外：用户明确要求切换时，先沉淀当前进度到 `topics.md`，再切换

### 3.4 TodoWrite 使用规范

- 每个任务必须用 TodoWrite 拆解为 ≥3 个子任务（除非任务本身极简）
- 子任务状态实时更新：开始时 `in_progress`，完成时 `completed`
- 同时只允许 1 个子任务处于 `in_progress`
- 完成的子任务必须写 `summary` 字段，记录实际产出

---

## 4. Build and Development Commands

### 4.1 Backend (Python 3.11+, FastAPI)

```bash
cd backend
pip install -r requirements.txt          # 生产依赖
pip install -r requirements-dev.txt      # 开发依赖（含 pytest）
python main.py                           # 启动服务 (uvicorn, 端口 8000)
pytest                                   # 运行测试
pytest -v --cov                          # 详细输出 + 覆盖率
pytest path/to/test.py -k "test_name"    # 运行单个测试
```

### 4.2 Frontend (Node.js 18+, React 18 + Vite)

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

---

## 5. Automated Verification & Self-Healing Workflow

Claude Code 在完成代码修改后，必须通过真实操作验证代码可行性，并在测试失败时自主诊断、修复并重新测试，形成"修改 → 验证 → 修复 → 重测"的闭环。本节定义该闭环的标准流程。

### 5.1 Service Lifecycle Management（服务生命周期管理）

验证前必须确保后端服务运行。服务管理命令：

```bash
# 启动后端（端口 8000，后台运行，日志输出到 var/logs/）
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
- 超时或连接拒绝 → 检查 `var/logs/` 下的启动日志，定位启动失败原因（端口占用、DB 初始化失败、插件加载异常等）

### 5.2 Authentication & API Access（认证与 API 访问）

OpenAwA 后端采用 **API Key 优先** 认证策略（见 `backend/api/dependencies.py` `get_current_user`）：

1. **路径 1（主认证，推荐）**：`Authorization: Bearer <OPENAWA_API_KEY>` — API Key 匹配后直接返回 owner 用户，跳过 JWT 解析和黑名单检查
2. **路径 2（兼容降级）**：JWT Bearer token（来自 `/api/auth/login`）— 仅用于前端浏览器会话兼容
3. **路径 3（兼容降级）**：HttpOnly Cookie — 仅用于前端浏览器会话兼容

> **API Key 是首选认证方式**，自动化测试、CLI 工具、浏览器扩展均应使用 API Key，无需用户名密码登录。
> 用户名密码登录仅用于前端 Web UI 会话（HttpOnly Cookie + CSRF），后端服务进程不应使用。

#### API Key 获取

```bash
# 方式 1：生成新 API Key（写入 backend/.env.local）
cd backend && python bin/bin/generate_api_key.py

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

### 5.3 Real Operation Verification Procedure（真实操作验证流程）

完成代码修改后，按以下顺序执行真实操作验证。每一步通过后才进入下一步；任一步骤失败则进入下文的 Self-Healing Bug Fix Loop（自主修 Bug 循环）。

#### 步骤 1：静态检查（快速失败，无需启动服务）

```powershell
# 代码审计 + lint + typecheck，跳过测试以加速反馈
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
- 启动失败 → 检查 `var/logs/` 日志，进入自愈循环

#### 步骤 4：E2E 场景验证（通过 test-scenarios 运行真实业务路径）

系统内置 10 个真实 E2E 测试场景（定义在 `backend/api/routes/test_runner.py`），覆盖：服务健康、系统诊断、对话生命周期、非流式聊天、插件发现、技能列表、文件工具、定时任务、用户会话、MCP 状态。

```bash
# 使用 API Key 认证（从 backend/.env.local 读取）
API_KEY=$(grep OPENAWA_API_KEY backend/.env.local | cut -d'=' -f2- | tr -d '"')

# 列出所有可用场景（需要 API Key 认证）
curl -s http://localhost:8000/api/test-scenarios \
  -H "Authorization: Bearer $API_KEY"

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

### 5.4 Self-Healing Bug Fix Loop（自主修 Bug 循环）

当任一验证步骤失败时，Claude Code 必须自主执行以下闭环，**最多迭代 3 次**（硬性上限，不可放宽）：

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
   - 服务启动失败 → 读取 `var/logs/` 下的启动日志 → 定位异常堆栈
   - 静态检查失败 → 读取 `reports/audit-result.txt`
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
- 迭代 3 次仍未通过 → **立即停止**，向用户报告（不强行 commit）

用户报告必须包含：
- 失败的验证步骤和具体用例名
- 根因分析（定位到文件和行号）
- 已尝试的修复方案及每次修复后的测试结果
- 失败的完整错误输出（截取关键部分）
- 建议的下一步操作（如需用户介入的环境问题、需讨论的设计决策等）

### 5.5 Verification Checklist（提交前验证清单）

在执行 `git commit` 前，必须确认以下全部通过：

- [ ] 步骤 1：`.\scripts\code-audit.ps1 -SkipTests` 静态检查通过
- [ ] 步骤 2：后端 `pytest` + 前端 `npm run test` 全部通过
- [ ] 步骤 3：后端服务启动且 `GET /api/system/ping` 返回 `pong=true`
- [ ] 步骤 4：`POST /api/test-scenarios/run-all` 返回 `failed=0`
- [ ] 步骤 5：`api-testing` skill 全部 API 集成测试通过
- [ ] 步骤 6：前端 `npm run build` 构建成功无警告
- [ ] 自愈循环（如有失败）未超过 3 次迭代
- [ ] **记忆沉淀已完成**（project_memory.md / topics.md 已更新）

### 5.6 Common Failure Patterns（常见失败模式与快速定位）

| 失败现象 | 快速定位 | 修复方向 |
|----------|----------|----------|
| 服务启动后立即退出 | `var/logs/` 启动日志 | 检查 DB 连接、端口占用、插件加载 |
| `chat-nonstream` 场景失败 | 场景返回的 `detail.response_preview` | 检查 LLM API Key 配置、`model_service.py` |
| `conversation-lifecycle` 失败 | `core/conversation_sessions.py` | 检查 DB session 提交、外键约束 |
| `plugin-discovery` 失败 | `plugins/plugin_instance.get()` | 检查插件目录扫描、插件加载异常 |
| 认证 401 | `api/dependencies.py` `get_current_user` | 检查 token 过期、JWT 黑名单、Cookie 传递 |
| CSRF 403 | 请求头 `X-CSRF-Token` | 确认 state-changing 请求携带 CSRF token |
| 速率限制 429 | `RateLimitStore` | 测试中避免高频请求，或等待窗口重置 |
| 前端构建类型错误 | `tsc --noEmit` 输出 | 修复 TypeScript 类型，禁用 `any` |
| pytest 测试污染 | `conftest.py` fixture 隔离 | 确保测试间 DB 状态隔离，使用事务回滚 |

---

## 6. Architecture Overview

Open-AwA is an AI Agent experimental platform with a **FastAPI backend** and **React frontend**, following a microkernel + plugin architecture.

### 6.1 Backend Layers (in main.py startup order)

1. **Logging init** — Loguru, request ID injection, sanitization
2. **DB init** — SQLAlchemy tables, billing schema, default pricing, RBAC roles, local user sync, built-in skills seed
3. **Plugin system init** — PluginManager singleton lifecycle (discover → load enabled plugins)
4. **Route registration** — 20+ route modules mounted (auth, chat, skills, plugins, memory, workflows, prompts, behavior, billing, market, security, weixin, MCP, subagents, system diagnostics, test runner)
5. **Scheduled task manager** — started during lifespan, stopped on shutdown
6. **Shared HTTP client** — closed on shutdown

### 6.2 Agent Core Flow (AIAgent.process)

```
agent.py → agent_turn_coordinator.py → executor.py → feedback.py
```
- `AgentTurnCoordinator` 保留完整用户消息并生成唯一模型执行步骤；不再通过本地关键词分类选择执行分支
- Conversation history auto-injected from ShortTermMemory (`session_id` key, no manual passing needed)
- Supports both SSE (HTTP) and WebSocket paths
- Tools executed with `idempotency_key` for deduplication
- LLM calls loop up to 5 tool-calling rounds (call → tool_calls → execute → append results → re-call)
- `context["_tools"]` carries native OpenAI function-calling tool definitions; `context["agent_capabilities"]` carries the text summary

### 6.3 Key Subsystems

| System | Directory | Key Files |
|--------|-----------|-----------|
| Agent Core | `backend/core/` | `agent.py`, `agent_turn_coordinator.py`, `executor.py`（兼容门面）, `execution_configuration.py`, `execution_model_runtime.py`, `execution_tool_runtime.py`, `execution_step_runtime.py`, `execution_prompt_builder.py`, `feedback.py` |
| Plugin System | `backend/plugins/` | `plugin_manager.py`, `plugin_instance.py` (singleton), `base_plugin.py`, `plugin_sandbox.py`, `plugin_lifecycle.py` (state machine), `hot_update_manager.py` (blue-green) |
| Skill System | `backend/skills/` | `skill_engine.py`, `skill_executor.py`, `skill_registry.py`, `skill_loader.py` |
| Memory | `backend/memory/` | `manager.py`, `consolidation_runner.py`, `extractor.py`, `experience_manager.py`, `vector_store_manager.py`, `decay.py`, `auto_dream.py` |
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

### 6.4 Memory API（记忆系统端点速查，Spec memory-experience-redesign）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/memory/long-term` | 长期记忆列表（含 `source_type`/`memory_layer`/`state` 元数据） |
| POST | `/api/memory/long-term` | 手动新增长期记忆 |
| DELETE | `/api/memory/long-term/{id}` | 删除长期记忆 |
| POST | `/api/memory/long-term/{id}/validate` | 用户"准确"验证：state→validated，confidence 提升至 0.9 |
| POST | `/api/memory/long-term/{id}/deprecate` | 用户"不准确"主动遗忘：state→deprecated（软删除） |
| GET | `/api/memory/short-term` | 按 session 分组的短期记忆（对话原文） |
| GET | `/api/memory/short-term/{session_id}` | 指定会话短期记忆 |
| GET | `/api/memory/short-term/recent` | 最近 N 条短期记忆（新对话上下文恢复） |
| GET | `/api/memory/search` | 关键词+向量混合搜索（`?query=`，`layer` 可过滤） |
| POST | `/api/memory/vector-search` | 混合检索，可传 `keyword_weight`/`vector_weight` |
| GET | `/api/memory/quality` | 记忆质量批量报告（低置信度/待验证） |
| GET | `/api/memory/stats` | 记忆统计（total/active/archived/平均置信度/向量数/分层） |
| POST | `/api/memory/consolidation/run` | 手动触发巩固（短期→长期 LLM 提炼，force 模式） |
| GET | `/api/memory/decay-config` | 查询记忆衰减配置（按层级） |
| PUT | `/api/memory/decay-config` | 更新记忆衰减配置（半衰期/阈值/开关） |
| POST | `/api/memory/archive` | 按时间/重要度/低质量批量归档 |

> 记忆写入契约：**长期记忆只存 LLM 提炼后的高价值信息（≤200 字事实/偏好/决策）**。`core/feedback.py` 关键词路径与 `consolidation_runner.py` 均经 `extractor.py` 的 LLM 提炼后入库，禁止把对话原文直接写入长期记忆。短期记忆（对话原文）仅用于会话上下文注入与巩固提炼的原料。

### 6.5 向量模型配置（Spec memory-model-config-chain）

嵌入/重排模型支持本地与云端双模式，模型注册表定义于 `memory/model_registry.py`：

| 类型 | 本地模型（ModelScope 默认下载） | 云端模型（OpenAI 兼容 API） |
|------|------|------|
| 嵌入 | `all-MiniLM-L6-v2`（384 维）、`bge-small-zh-v1.5`（512 维，中文推荐）、`bge-m3`（1024 维）、`Qwen3-VL-Embedding-2B`（多模态本地嵌入） | `text-embedding-3-small`（通用 OpenAI 兼容） |
| 重排 | `ms-marco-MiniLM-L6-v2`（CrossEncoder）、`bge-reranker-v2-m3`、`Qwen3-VL-Reranker-2B`（多模态本地重排） | 通用 OpenAI 兼容重排器（请求结构 `{model, query, documents}`） |

- **加载链**（本地模型）：单一下载源，无自动降级链。默认 ModelScope（国内网络友好），`MODEL_DOWNLOAD_SOURCE=huggingface` 显式切换；下载失败必须显式报错，禁止静默切换下载源
- **配置项**（settings 或 DB `vector_model_config` 表，DB 优先）：`MEMORY_EMBEDDING_PROVIDER`（local/cloud/hash）、`MEMORY_EMBEDDING_MODEL`、`MEMORY_EMBEDDING_API_KEY/ENDPOINT`、`MEMORY_RERANK_PROVIDER`（local/cloud/off）、`MEMORY_RERANK_MODEL`、`MEMORY_RERANK_API_KEY/ENDPOINT`
- **模型端点**：`GET /api/models/vector/registry`（注册表+下载状态）、`POST /api/models/vector/download`（后台下载）、`GET /api/models/vector/download/status`、`GET/PUT /api/models/vector/config`
- **检索接入**：`MemoryManager.search_memories` 混合检索（BM25+向量融合）后，配置了重排器时对 3 倍候选做二次相关性重排再截断；未配置或重排失败时静默退回融合排序
- **多模态**：`CloudEmbeddingProvider.embed_inputs` 支持文本+图像输入（DashScope/vLLM 兼容格式）；`CloudReranker` 请求结构 `{model, query, documents}`，响应兼容 `{results: [{index, relevance_score}]}`
- **前端**：MemoryPage 侧栏"向量模型配置"卡片（模型选择/下载按钮/云端 API 配置/下载源/保存）

### 6.6 Frontend Structure

- `src/features/` — Feature modules (chat, dashboard, skills, plugins, memory, billing, experiences, settings, scheduledTasks, auth, user, agents, coding, workspace, inbox, tts, search, test)
- `src/shared/` — Shared: `api/`, `components/`, `store/`, `hooks/`, `types/`, `utils/`
- `src/__tests__/` — Unit tests mirroring the feature structure
- `src/i18n/` — Internationalization (dynamic locale loading per language)
- State: Zustand stores (`useAuthStore`, `useChatStore`, `useThemeStore`)
- API: Axios with `withCredentials` for Cookie-based auth; path alias `@/` → `src/`

### 6.7 Frontend Component Architecture Pattern

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

---

## 7. Adding a New API Route (Backend)

1. Create `backend/api/routes/my_feature.py` with an `APIRouter`
2. Import in `main.py`: `from api.routes.my_feature import router as my_router`
3. Register in `main.py`: `app.include_router(my_router)` (or `app.include_router(my_router, prefix=settings.API_V1_STR)` for `/api` prefix)
4. Use `Depends(get_current_user)` for auth-protected endpoints, `Depends(get_db)` for DB access
5. If no auth needed (like `/health`), skip dependency injection

---

## 8. System Diagnostics and Test Runner

> 完整的自动化验证流程见 [Automated Verification & Self-Healing Workflow](#5-automated-verification--self-healing-workflow)。本节为端点速查参考。

Two diagnostic layers are available, both designed for automated validation:

- **`GET /api/system/ping`** — No-auth lightweight connectivity probe
- **`GET /api/system/diagnostics`** — Auth-required checks DB/plugins/skills/MCP status, returns `healthy` or `degraded`
- **`GET /api/test-scenarios`** — Lists 10 real E2E test scenarios
- **`POST /api/test-scenarios/run`** — Runs one named scenario (body: `{"name": "chat-nonstream"}`)
- **`POST /api/test-scenarios/run-all`** — Runs all 10 scenarios, returns pass/fail report

Test scenarios exercise real production code paths (AIAgent, conversation CRUD, plugin discovery, etc.), not mocked. Use these for Claude Code-triggered validation.

---

## 9. ACP Vibe Coding API

ACP（Agent Client Protocol）用于调用本地 vibe coding 应用（Claude Code / Codex / OpenClaw / OpenCode）。所有端点强制鉴权，会话按 `(user_id, session_id)` 隔离。

### 9.1 ACP Agent 与会话端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/acp/agents` | 列出所有 agent + `available` 状态（同步探测包到线程池） |
| POST | `/api/acp/sessions` | 创建会话，body `{agent, cwd}`，返回 `session_id` |
| GET | `/api/acp/sessions` | 列出当前用户活动会话 |
| POST | `/api/acp/sessions/{id}/prompt` | 发起一轮 prompt，body `{prompt, restart?}`，SSE 流式响应 |
| POST | `/api/acp/sessions/{id}/permission` | 恢复 permission，body `{option_id}` |
| POST | `/api/acp/sessions/{id}/cancel` | 取消当前轮 |
| DELETE | `/api/acp/sessions/{id}` | 关闭并移除会话 |
| GET | `/api/acp/opencode/status` | 查询白名单项目中的 OpenCode 安装与可用状态 |
| POST | `/api/acp/opencode/install` | 经用户明确确认后，在白名单 Node.js 项目中安装固定的 `opencode-ai@latest` 并执行依赖审计 |

SSE 事件类型：`text` | `tool` | `status` | `permission` | `usage` | `result` | `error`。客户端断开时后端自动调用 `ACPService.cancel_turn` 取消未完成的 prompt。

### 9.2 通知 API（Claude Code Hooks 集成）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/notifications` | 发送通知，body `{title, body, pane_id?, notification_type}` |
| GET | `/api/notifications?limit=N` | 列出最近 N 条通知（默认 50，最大 100） |
| GET | `/api/notifications/stream` | SSE 长连接，30s 心跳，实时推送 |

Hooks 模板见 `backend/static/claude-code-hooks.json`。

### 9.3 文件预览与反向代理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/coding/preview/file?path=<path>` | 按扩展名分发渲染（Markdown/图片/音视频/Office） |
| GET | `/api/preview/{port}/{path:path}` | 反向代理到 `127.0.0.1:{port}` |

SSRF 防护：`/api/preview/{port}/...` 拒绝 `port < 1024` 或 `> 65535`，强制目标主机为 `127.0.0.1`。

### 9.4 终端 PTY API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/terminal/sessions/{id}/snapshot` | 返回屏幕网格快照（cols/rows/grid） |
| WebSocket | `/terminal/ws/pty/{session_id}?token=...` | PTY 双向通信（input/output/resize/shell_info） |

注意：terminal 路由前缀为 `/terminal`（无 `/api` 前缀）。

---

## 10. Plugin System Architecture

### 10.1 Lifecycle State Machine

Eight states with explicit valid transitions in `plugin_lifecycle.py`: `REGISTERED → LOADED → ENABLED ↔ DISABLED → UNLOADED`, plus `UPDATING` and `ERROR`. Each state transition calls the corresponding hook on the plugin instance (`on_registered`, `on_loaded`, etc.). Failed transitions trigger automatic rollback.

### 10.2 Blue-Green Hot Update

`hot_update_manager.py` implements zero-downtime updates via active/standby slots. `prepare_update()` loads the new version into standby; `commit_update()` atomically swaps. Supports gated rollout (percentage/user-list/region-based) and snapshot-based rollback (last 10 versions, in-memory only).

### 10.3 Singleton Access

Always use `plugins.plugin_instance.get()` to access the PluginManager. Never create `PluginManager()` directly. `get()` auto-creates an uninitialized instance if `init()` was never called, so startup order matters.

### 10.4 Sandbox

`plugin_sandbox.py` wraps plugin execution with `asyncio.wait_for` timeout control. Resource limits (memory/CPU) are applied via `resource.setrlimit` on Unix or `psutil` on Windows. The default timeout is 60 seconds.

---

## 11. Channels System (Multi-IM Integration)

The channels system (`backend/channels/`) provides a unified abstraction for 11 IM platforms. Each platform implements the `ChannelAdapter` abstract base class:

- **Adapter pattern** — `base.py` defines `ChannelAdapter` (ABC), `ChannelMessage`, `ChannelConfig`. Each platform (weixin, dingtalk, feishu, discord, telegram, slack, qq, matrix, imessage, wecom) extends it.
- **Connection pool** — `ChannelManager` in `manager.py` manages lifecycle (connect/disconnect/health check) and message queuing for all registered adapters.
- **ChannelType enum** — Standardized platform identifiers used for routing and message dispatch.
- Route: `backend/api/routes/weixin.py` handles WeChat-specific webhooks; other channels route through their respective adapters.

Channels are distinct from MCP and Plugins — they are inbound message sources, not tool providers.

---

## 12. MCP vs Plugin Manager

They serve different purposes:
- **PluginManager** — Manages local Python plugin modules (discovery, lifecycle, sandboxed execution, hooks). Plugins are Python classes.
- **MCPManager** — Manages external MCP server processes (stdio/SSE transport). Has no sandbox, no lifecycle state machine, no skill integration. Stores server configs on disk with hot-reload. Uses double-checked locking singleton.

MCP tool names follow the pattern `mcp_{server_id}/{tool_name}` for dispatch in `executor._execute_tool_call()`.

---

## 13. Chat Protocol Details

- **SSE** — Uses two event types: default `data:` for content tokens, `event: reasoning` with `data:` for thinking tokens. The frontend tracks the `event:` field between `data:` lines.
- **WebSocket** — Splits large messages (>1024 bytes) into chunked JSON frames with checksums. Supports `"message"` and `"confirm"` message types. Both paths call the same `AIAgent.process()`.
- **Streaming retry** — Frontend retries on network errors up to 1 time, but only if zero data was received (partial data = throw immediately, no retry).

---

## 14. Security Architecture

- **JWT blacklist** — Tokens carry a `jti` (UUID4). On logout, the jti is blacklisted in the DB and auto-expires after `ACCESS_TOKEN_EXPIRE_MINUTES`.
- **Fernet encryption** — `SECRET_KEY` is SHA256-hashed to derive a Fernet key for encrypting sensitive values (API keys). Values with prefix `enc:` are idempotently re-encrypted (won't double-encrypt).
- **Password hashing** — pbkdf2_sha256 (600K rounds) for new, bcrypt (12 rounds) for legacy. Both verified.
- **Cookie + CSRF** — Access token in HttpOnly cookie (`SameSite=lax`). Frontend fetches `/api/auth/csrf-token` and attaches `X-CSRF-Token` on state-changing requests. `/auth/login` and `/auth/register` are exempt.

---

## 15. Scheduled Task Isolation

Scheduled tasks run in an isolated agent context (`scheduled_execution_isolated: True`, dedicated `session_id`). They do NOT write to conversation history or memory. The manager uses 2-second polling with transactional claim (`UPDATE ... WHERE status='pending'` as row-level lock) to prevent duplicate execution. Daily tasks auto-reschedule to the next cron match; on crash recovery, orphaned "running" tasks reset to "pending."

---

## 16. Model Service Patterns

- **Per-provider request building** — `build_provider_request()` constructs completely different payloads for OpenAI-compatible, Anthropic, Google Gemini, and Ollama.
- **Thinking depth mapping** — 0-5 depth converts to provider-specific params: `reasoning_effort` (OpenAI o-series), `budget_tokens` (Anthropic), boolean flag (DeepSeek R1).
- **Shared HTTP client** — `get_shared_client()` returns a singleton `httpx.AsyncClient` (100 max connections, 20 keepalive). All LLM API calls go through it. Closed on shutdown.
- **Retry** — 3 attempts with exponential backoff (`0.2s * 2^attempt`) on retryable status codes (408/409/425/429/5xx) and network errors.

---

## 17. Frontend SSE Parsing

`chatAPI.sendMessageStream` manually parses SSE via `fetch` + `ReadableStream` (not Axios). It has its own buffer-based line parser that handles partial reads and tracks `event:` type to split reasoning vs content tokens. Streaming events include `chunk`, `status`, `plan`, `result`, `task`, `tool`, and `usage`.

---

## 18. Code Conventions

### 18.1 Mandatory

1. **All code comments MUST be in Chinese** — file headers, function comments, inline comments
2. **Emoji is strictly prohibited everywhere** — source, comments, docs, commits, config, logs. Use `[DONE]`, `[Fix]`, `[NEW]` instead.

### 18.2 Backend

- Classes: `PascalCase`, functions/variables: `snake_case`
- Routes: `async def`; DB models extend `Base`; schemas extend `BaseModel`
- Pydantic schemas: `Create`/`Response` suffix variants (e.g., `SkillCreate`, `SkillResponse`)
- Config class: `from_attributes = True` for ORM-to-schema conversion
- Dependencies: `Depends(get_db)` and `Depends(get_current_user)`
- Logging: Loguru with `request_id` context from middleware

### 18.3 Frontend

- Components: `PascalCase` with `Page` suffix for routes (e.g., `ChatPage`, `SettingsPage`)
- Stores: `use` prefix (e.g., `useAuthStore`, `useChatStore`), using Zustand
- API modules: feature-specific files (e.g., `modelsApi.ts`, `billingApi.ts`)
- CSS Modules: `[FeatureName].module.css`
- Test files in `__tests__/` mirror the src structure

### 18.4 Commit Message Format

```
[Type] Concise description of the change
```
Types: `[New]`, `[Fix]`, `[Optimization]`, `[Refactoring]`, `[Documentation]`, `[Test]`, `[Configuration]`, `[Remove]`, `[Dependency]`, `[Lesson]`（用于沉淀重复错误修复）

### 18.5 Git Workflow

**所有提交直接推到 main 分支，不使用 debug 分支作为中间步骤。**
完成修改后直接 `git add` + `git commit` 到 main：
```bash
git add <具体文件>
git commit -m "[Type] 变更描述"
```
不使用 `debug` 分支，不创建中间分支。如果需要回滚，使用 `git revert`。

**禁止自主 `git push`**——push 必须由用户确认后执行。

---

## 19. Known Pitfalls

> 本节是长期迭代沉淀的"已知陷阱库"。每次遇到新坑点必须追加到此；每次开始任务前必须扫描相关条目。

- **OUTDATED: Blocking ORM in async**: `ExperienceManager` uses sync SQLAlchemy queries in `async def`, may block the event loop（已修复：实际为同步实现，描述失真，2026-07-04 审计确认）
- **SQLite FK not enforced by default**: Foreign key constraints need explicit connection parameter
- **Vector DB path is absolute**: `config/runtime_paths.py` anchors the default to `<project-root>/var/data/qdrant`; do not reintroduce CWD-relative storage paths
- **Plugin Manager is a singleton**: Use `plugins.plugin_instance.get()`, never create `PluginManager()` directly. Use `pm.has_plugin(name)` / `pm.is_plugin_loaded(name)` instead of `getattr(pm, "plugin_metadata", {})`.
- **SECRET_KEY auto-generated in dev**: Must be explicitly set as env var in production; auto-generation persists to `.env.local`
- **Billing tables require init**: `PricingManager.ensure_configuration_schema()` must run in lifespan startup
- **Chat supports both SSE and WebSocket**: Changes to chat must test both paths
- **Conversation history auto-injected**: Agent pulls from ShortTermMemory by `session_id`, don't manually pass
- **Plugin hot update state is ephemeral**: Snapshots and active/standby slots are in-memory only, lost on restart
- **Windows ACL restrictions**: Some directories have restrictive permissions; use elevated PowerShell to replace existing files when tools fail with EPERM
- **测试缓存路径不得越出仓库或跨任务共享**：`backend/pytest.ini` 使用工作区内已忽略的 `.pytest_cache`，`frontend/vite.config.ts` 使用 `frontend/.vite-cache`；从子工作区写 `../../var/cache` 会落到 `D:\代码\var`，共享 `var/cache` 还会在 Windows 触发 ACL 拒绝或文件锁冲突。
- **PowerShell rg 引号解析**: 复杂正则中混用单双引号会在执行前被 PowerShell 误解析；拆分为固定关键词检查，或先在脚本文件中定义模式再执行。
- **共享向量运行时必须在 lifespan 预热**：仅在 `api/routes/chat.py` 的聊天入口调用 `prewarm_agent_memory()` 不足以保护先访问记忆页的场景；`main.py` 必须在 `yield` 前通过可降级启动步骤预热 `MemoryManager` 共享向量存储。定位方法：日志中首个 `/api/memory/long-term` 在 `VectorStoreManager initialized` 前等待 15 秒以上；修复方向：复用 `core/agent_runtime_warmup.py`，禁止用调大 Axios timeout 掩盖冷启动。
- **Vite API 代理目标不得重复携带 `/api`**：浏览器请求已使用 `/api/*`，若 `OPENAWA_API_PROXY_TARGET` 配成 `http://host:port/api`，Vite 会向后端发送 `/api/api/*` 并产生伪 404；`frontend/vite.config.ts` 必须规范化目标为后端 origin，修改代理配置后运行 `viteConfigRetirement.test.ts`。
- **sharedApi 业务路径不得重复携带 `/api`**：`sharedApi` 的 `baseURL` 已包含 `/api`，业务模块常量必须从领域路径开始（如 `/soul`），禁止写成 `/api/soul`；定位方法：浏览器网络记录出现同源 `/api/api/*`，而前端错误日志只展示调用参数 `/api/*`。修复后必须同时校验真实请求 URL、后端统一响应的 `data` 解包以及写接口路径和载荷。
- **离线启动默认使用 LiteLLM 本地价格表**：`core/litellm_adapter.py` 必须在导入 `litellm` 前默认设置 `LITELLM_LOCAL_MODEL_COST_MAP=True`，避免无法访问 GitHub 时 DNS 失败与 5 秒远程价格表回退；显式部署环境变量仍可覆盖默认值。
- **resolve_max_tool_call_rounds**: 定义在 `executor.py`，`agent.py` 通过 import 引用同一函数，不可重复定义
- **ExecutionLayer 必须保持薄兼容门面**：`core/executor.py` 不得超过 420 行，直接方法不得超过 40 行；配置、模型调用、工具执行和步骤执行分别由 `execution_configuration.py`、`execution_model_runtime.py`、`execution_tool_runtime.py`、`execution_step_runtime.py` 承担，协作者禁止反向 import `core.executor`。修改执行链后必须运行 `tests/test_executor_facade_architecture.py`
- **TanStack Router 根路径只能有一个重定向权威**：`RootGuard` 负责认证状态与默认落点；`/` 索引路由只能建立有效匹配并返回 `null`，禁止再声明 `/ -> /chat` 重定向。否则未登录路径会在 `/login` 与 `/chat` 之间竞争，触发 `Router.Transitioner` 无限更新并使 Vitest worker OOM。修改根路由后必须运行 `src/__tests__/router/RouteGuards.test.tsx`、`src/__tests__/App.test.tsx` 与入口测试。
- **RBAC 通配符**: `check_permission` 支持 `skill:*` 匹配 `skill:read`，`*` 仅在同段数下生效
- **登录限流**: 通过 `RateLimitStore` 抽象层管理，`DatabaseRateLimitStore` 使用 `time.time()`（跨 worker 一致），`MemoryRateLimitStore` 使用 `time.monotonic()`（单进程不受时钟跳变影响）
- **模型参数 or 陷阱**: `getattr(config, "retry_count", 3) or 3` 会将 `0` 误判为未设置，必须使用 `is not None` 检查
- **SSRF 防护**: `BASE_URL` 校验拒绝内网/本地/链路本地 IP 地址，修改模型服务 URL 验证逻辑时需保持此检查
- **Tool calls 结果截断**: 过长的工具调用结果会被截断后再传给 LLM，修改截断阈值时注意上下文窗口限制
- **ACP SDK 缺失优雅降级**: `acp` Python SDK 是可选依赖，缺失时 `ACPService.run_turn`/`resume_permission` 抛 `ACPConfigurationError`，但状态管理方法（`get_session`/`close_chat_session`/`cancel_turn`）仍可正常工作
- **pywinpty 仅 Windows**: POSIX 系统用标准库 `pty`，Windows 用 `pywinpty` 提供 PTY 能力
- **ACP 会话隔离机制**: 按 `chat_id = f"{user_id}:{session_id}"` 隔离，每个 `(chat_id, agent)` 对应一个 `_Conversation` 实例，模块级 `_acp_services` 字典按 agent 标识索引 service 实例
- **ACP 硬阻断策略**: `rm -rf /`、`sudo rm -rf`、`mkfs`、`dd if=` 命令子串直接拒绝，不进入用户审批流程
- **Backend root directory file scatter**: backend 根目录散落了 14+ 个独立脚本（`replace_file.py`、`elevate_script.ps1`、`grant_perm.ps1` 等），这些是一次性迁移辅助脚本，不属于应用代码。后续路线图将统一迁移到 `scripts/` 目录。新增脚本不应放在根目录
- **SECRET_KEY 已完全废弃**: 使用 `JWT_SECRET_KEY`、`CSRF_SECRET_KEY`、`ENCRYPTION_KEY` 代替
- **API Key 存储位置**: 使用数据库 `provider_credentials` 表（`enc2:` 前缀），不再使用 `.env` 环境变量
- **API Key 解密**: 在 provider 连接检查中必须使用 `decrypt_secret_value()` 解密后使用
- **provider_credential 查询**: 使用 `pricing_manager.get_provider_credential(provider_id)` by name（与 billing routes 一致）
- **跳过 enc: 旧密文**: 查询 provider credentials 时跳过 `enc:` 前缀的旧密文条目
- **HTTP 请求头字符集**: 必须只包含 ISO-8859-1 字符（0-255 码点），避免 XMLHttpRequest 失败
- **WebSocket Origin 校验**: 必须包含 Origin header 校验以防止 CSWSH 攻击
- **WebSocket token 不走 URL**: token 不能通过 URL query 参数传递，避免在日志/历史/Referer 中泄露
- **CSRF 必须开启**: 防止跨站请求伪造
- **Terminal/PTY 会话鉴权**: 必须校验用户所有权，防止 IDOR
- **ACP 子进程环境变量**: 父进程环境只能按 `acp_host.service._SAFE_INHERITED_ENV_KEYS` 与 `LC_*` 显式白名单继承；Agent 专用变量必须通过 `ACPAgentConfig.env` 明确声明，禁止恢复“仅过滤敏感键、其余全部继承”的黑名单模式
- **Agent 重试抖动上限**: `RetryPolicy.compute_delay()` 必须对“基础退避 + jitter”最终结果应用 `max_interval` 上限；禁止只封顶基础延迟后再追加抖动，否则 30 秒上限可膨胀到 45 秒
- **OpenCode ACP 启动与安装**: OpenCode 必须以 `opencode acp` 启动；网页安装仅接受白名单工作目录、固定包名 `opencode-ai@latest` 和显式确认，启动时优先使用项目 `node_modules/.bin/opencode`
- **base_url 解析优先级**: 使用 `getattr(config, 'base_url', None)` 修复运算符优先级问题
- **新 provider 创建约束**: `provider` 字段必须非空，`config_id` 仅更新时需要
- **前端移动端适配 CSS @media 限制**: CSS @media 中不能使用 var() 引用 tokens.css 断点令牌（--breakpoint-xs/sm/md/lg/xl），必须使用数字字面量；但在 @media 块前必须注释对应 token 名，如 `/* 移动端（≤ 768px，对应 --breakpoint-md 令牌） */`，便于令牌变更时全局定位。定位方法：检查 CSS Module 文件头注释是否标注 token 名；修复方向：保留数字字面量但在 @media 块前追加 token 标注注释
- **Windows Alembic UTF-8 配置**: `alembic.ini` 含 UTF-8 内容时，`alembic/env.py` 的 `fileConfig` 必须显式传入 `encoding="utf-8"`；当前迁移图存在多个 head，验证或部署全部分支应使用 `alembic upgrade heads`，单分支迁移则指定具体 revision。

---

## 19.1 2026-07-10 回归新增陷阱

- **首次初始化与 E2E 隔离**：Playwright 的全新临时数据库必须配套独立 `INITIALIZED_MARKER_PATH`，或由全局 setup 先完成 `/api/system/init`；否则前端会跳到 `/setup`，依赖 `#apiKey` 的登录助手会让后续 E2E 全部级联失败。首次部署向导需单独覆盖。
- **Qdrant 缺失 point 必须显式可见**：数据库记忆行可能早于向量 point 写入；读路径在条目上暴露 `vector_sync_error` 字段（可见而非静默跳过），写路径（更新/删除元数据）遇缺失 point 必须 fail-closed 抛错，禁止吞掉后继续。
- **显式 provider 凭证错误**：模型列表接口收到请求体中的 api_key/api_endpoint 后，远端认证失败必须返回结构化错误；仅后台使用已保存配置时允许回退本地模型列表。
- **Windows shell 内建命令**：`command_executor.py` 保持 `shell=False`，对 echo/pwd 使用平台内建适配，不得改为 shell=True。
- **WebSocket/SSE E2E**：使用独立临时数据库、向量路径和端口，避免锁定生产数据库或 Qdrant；WebSocket 必须同时验证 Origin 与子协议 token，SSE 必须检查 text/event-stream 和 [DONE]。
- **Windows 多服务 E2E 生命周期**：外层服务器包装脚本可能只停止 PowerShell/CMD 包装进程，遗留 Uvicorn 或 Vite 孙进程并让后续验收误复用旧源码；多服务门禁优先使用 Playwright 原生 `webServer`，`reuseExistingServer=false`，结束后必须按端口核对监听 PID 与命令行，只能停止已确认属于本轮测试的进程。
- **Python 3.12 异步测试事件循环**：测试异步接口必须使用 `pytest.mark.asyncio` 与直接 `await`；禁止在同步测试中调用 `asyncio.get_event_loop().run_until_complete(...)`，因为前序测试关闭默认循环后会出现顺序相关的 `RuntimeError: There is no current event loop`。
- **CSRF 双提交 token 必须成对签发**：`X-CSRF-Token` 使用响应体中的原始 token，`csrf_access_token` Cookie 保存签名 token；登录和 `/api/auth/csrf-token` 必须通过 `generate_csrf_token_pair(response)` 同时写入两者，不能把签名 Cookie 当作 header token，也不能只轮换 Cookie。
- **认证状态不得早于 CSRF 初始化发布**：API Key 验证或缓存会话恢复后，必须先等待 `refreshCsrfToken()` 完成再设置 `isAuthenticated=true`；否则 Chat 等认证后立即挂载的组件会先发出状态变更请求，虽可由响应拦截器重试成功，浏览器仍会记录一次 403。
- **插件热更新不得 deepcopy 运行时实例**：active slot 含 `plugin_instance`、sandbox 和 module 引用，直接 `deepcopy(route["slots"]["active"])` 会触发 `cannot pickle 'module' object`；回滚快照只复制可序列化元数据，运行时对象按引用或显式字段保存。
- **插件回滚必须兼容异步生命周期**：恢复实例的 `initialize()` 可能返回 awaitable，必须复用 `TransitionExecutor._run_coroutine()` 等现有适配器等待完成并校验返回值；直接调用会产生 `coroutine was never awaited`，且插件会在未初始化完成时被注册。
- **ACP 全局关闭必须在有效事件循环内创建协程聚合**：`_shutdown_acp_services()` 在没有运行中 loop 时必须通过 `asyncio.run()` 执行内部 async 函数，再在其中创建并等待 `asyncio.gather(...)`；禁止先在同步上下文创建 gather，否则 Python 3.12 会留下 `close_all_sessions` 未 await 协程，破坏 pytest 全局清理。
- **Loguru 全局控制台 sink 不得持有 pytest 捕获流**：`init_logging()` 使用 `sys.__stderr__` 而非按用例替换的 `sys.stderr`；否则日志测试重新初始化后，捕获流关闭会导致后续任意日志出现 `Logging error in Loguru Handler`。
- **Windows 命令模板输出必须显式 UTF-8 容错解码**：`command_executor.py` 的白名单 `subprocess.run(..., text=True)` 必须传 `encoding="utf-8", errors="replace"`；依赖系统 GBK 会在 Git 等 UTF-8 输出时使 reader thread 触发 `UnicodeDecodeError`。
- **后端全量 pytest 分组运行目录**：完整串行套件已多次超过 15 分钟；按 8 组覆盖时必须在 `backend` 工作目录执行、关闭共享 coverage 数据文件并每次最多并发两组。否则 ACP 路由测试会因 `os.getcwd()` 落在白名单外产生伪 400。

## 19.9 2026-08-08 无兜底专项（全仓兜底代码清理）新增陷阱

- **项目硬约束：禁止兜底/降级/静默容错代码**。任何"失败后悄悄继续、返回空值、切换备用路径"的行为都视为缺陷：主路径应被修好而非降级。修复三原则：(a) 异常自然传播；(b) 显式结构化错误结果（如 `{ok: False, error: {code, message}}`）；(c) 安全敏感路径（RBAC/审计/E2B/SSRF/WS 鉴权）fail-closed。豁免仅限：瞬时重试（`retry.py`/`circuit_breaker.py`）、显式配置开关、可选字段默认值、前端 i18n 回退与 ErrorBoundary/Suspense、API Key→JWT→Cookie 认证链、`LITELLM_LOCAL_MODEL_COST_MAP` 离线价格表。新增代码若出现"except 吞异常 + 返回默认值"必须自我审查。
- **failover 模块已删除**：`core/failover.py` 整文件删除（执行链与监控统计均移除）；`GET /api/models/failover/circuit-breakers`、`failover/chains`、`failover/events`、`latency/stats`、`latency/providers` 5 个监控端点已从 `api/routes/models.py` 移除。禁止重新引入 provider 故障转移与降级监控；新代码引用 `core.failover` 将直接 ImportError。
- **MCP_SSE_ALLOWED_ORIGINS 生产必须显式配置**：`main.py` 启动时 fail-closed——环境变量未配置或为空时拒绝启动（`RuntimeError: 未配置 MCP_SSE_ALLOWED_ORIGINS`）。生产部署与隔离 E2E 实例必须设置逗号分隔的允许 origin 列表；测试 conftest 在 `pytest_configure` 中设置 `https://localhost`。
- **E2E 场景同步执行必须线程池卸载**：`api/routes/test_runner.py` 的 `run_scenario`/`run_all_scenarios` 用 `await asyncio.to_thread(runner, ...)` 执行同步场景。禁止改回事件循环内直接调用——health-basic 场景会向自身端口发起真实 HTTP，同步阻塞事件循环会自请求死锁（10 秒超时）。chat-nonstream 场景构造 `AIAgent` 必须注入完整持久化边界（`db_session`/`workflow_repository`/`memory_session_factory`），与生产 chat 路由一致；缺注入时 fail-closed 抛错是预期行为。
- **隔离 E2E 实例需完整复制模型目录**：隔离数据库验证 `chat-nonstream` 时，除 `provider_credentials` 外还必须复制 `model_configurations`（默认模型目录）与 `model_pricing`（价格表），否则模型解析回退到默认 openai/gpt-5.5 并因无 Key 报 `llm_api_key_missing`（生产库因目录含 deepseek 默认模型而正常）。

## 19.2 2026-07-23 聊天刷新恢复新增陷阱

- **后台子代理返回前必须保存完整消息快照**：SSE 主流程在后台子代理启动后提前返回时，必须先保存用户问题、已产生的思考、工具事件、子代理元数据和助手占位消息；否则页面刷新后只能看到残缺的助手正文，用户问题、思考和子代理过程都会丢失。
- **隐藏续写必须按字段合并执行元数据**：后台续写完成后不能只覆盖助手正文，还要合并 `thinking`、`tool_calls`、子代理汇总与执行元数据；已有事件按稳定标识去重，避免刷新后重复或缺失。
- **子代理结构化日志必须先归一化再渲染**：`plan`、`task`、`tool`、`status`、`chunk` 等事件不得直接作为 JSON 文本交给 Markdown；终态 transcript 优先复用缓存，伪子代理标识必须保留完整 fallback logs，不能只保留 summary。
- **记忆查询不得直接使用超长工具输出**：SQLite 的模糊搜索输入必须先统一清洗、压缩和截断；整段工具结果或大型 JSON 直接进入 `LIKE`/`GLOB` 会触发 `LIKE or GLOB pattern too complex`，进而使聊天流式请求失败。
- **反馈层长期记忆调用保持显式契约**：`add_long_term_memory` 必须以 `memory_layer=` 显式传递记忆层，修改反馈链路时需用契约测试防止位置参数漂移导致 `MemoryPersistenceError`。
- **真实运行库 ACL 必须同时覆盖旁车文件**：Windows 上修复 `var/data/openawa.db` 写权限时，要在提升权限终端检查数据库目录以及 `openawa.db`、`openawa.db-wal`、`openawa.db-shm` 的所有者和写权限；禁止通过删除真实库或旁车文件绕过 `attempt to write a readonly database`。
- **chat-nonstream 场景必须校验成功终态**：`api/routes/test_runner.py` 不得仅凭 `response` 非空判定通过；`AIAgent.process()` 返回 `status=error` 时即使正文包含错误文本，也必须让 run-all 记录失败。
- **AIAgent 架构指标必须由 AST 契约持续约束**：`core/agent.py` 的方法不得超过 80 行、参数不得超过 8 个、方法内不得使用 lazy import、直接项目模块扇出必须小于 15，并禁止反向依赖 `db.models` 与 `api.routes`；修改 Agent 核心后必须运行 `tests/test_agent_architecture.py`。
- **AIAgent 测试不得恢复静态 helper 别名**：测试应直接覆盖 collaborator 或公共 helper，禁止为了兼容旧测试在 `AIAgent` 上重新挂载私有静态别名，也禁止通过 `AIAgent.__new__` 绕过生产构造契约。
- **生产 AIAgent 构造必须注入持久化边界**：路由、定时任务、微信自动回复和子代理运行器创建 `AIAgent` 时，必须提供 `WorkflowRepositoryPort` adapter 与 memory session factory；新增构造路径需同步加入架构测试。
- **pytest 文件日志必须隔离到临时目录**：测试收集前设置独立 `LOG_DIR`，避免测试写入真实 `var/logs`、持有用户日志句柄或因 Windows 文件锁导致回归不稳定。
- **Sandbox 必须先校验原始命令再解析平台可执行文件**：权限、白名单和危险模式检查必须发生在 Windows/POSIX executable resolution 之前，禁止让危险命令借“command not found”绕过安全拒绝。
- **旧 code-audit 脚本已移除**：`scripts/code-audit.ps1` 已由提交 `489446ee` 删除；当前 Agent 架构验证使用任务文件 Ruff、`git diff --check`、`tests/test_agent_architecture.py`、目标回归、完整分组 pytest 和隔离 E2E，不得把缺失旧脚本误判为产品失败。

## 19.4 2026-08-05 移动 APP（Capacitor）新增陷阱

- **AGP 拒绝中文路径构建**：项目根目录 `D:\代码\Open-AwA` 含非 ASCII 字符，AGP 报 "project path contains non-ASCII characters"（b.android.com/95744）。修复方向：`frontend/android/gradle.properties` 必须保留 `android.overridePathCheck=true`。
- **gradle 发行版下载必须走国内镜像**：`gradle-wrapper.properties` 的 distributionUrl 使用 `https://mirrors.cloud.tencent.com/gradle/`（services.gradle.org 国内不可达导致 wrapper 卡死）；`networkTimeout` 调至 120000。
- **工程内自定义 Capacitor 插件必须显式注册**：`@CapacitorPlugin` 注解扫描对未列入 `capacitor.plugins.json` 的工程内插件不保证生效（运行时报 "LanDiscovery plugin is not implemented"）；必须在 `MainActivity.onCreate` 里 `super.onCreate` 之前调用 `registerPlugin(LanDiscoveryPlugin.class)`。
- **API_BASE_URL 必须保持模块级可变绑定**：`client.ts` 的 `API_BASE_URL` 是 `export let` 并由 `setBackendUrl()` 重新赋值（ES Module live binding），禁止改回 `const`。绕过 axios 的原生通道（SSE 流式 `chatApi.ts`、WebSocket `inboxStream.ts`/`TerminalPane.tsx`/`useWeixinWebSocket.ts`、文件预览、权限流等 10+ 处直接拼接 `API_BASE_URL`）依赖此机制在切换后端后立即生效。定位方法：APP 内切换服务器后聊天报 "Failed to fetch" 且日志 URL 是旧地址；修复方向：检查是否有人把 `export let` 改成了 `const` 或把 setBackendUrl 里对 `API_BASE_URL` 的赋值移除。
- **原生容器内 localhost/127.0.0.1 后端视为未配置**：`isBackendConfigured()` 在 `isNativeApp()` 时拒绝 localhost/127.0.0.1（指向设备自身而非宿主机），避免残留配置把用户挡在服务器选择页之外。
- **APP 内 API Key 持久化到 localStorage**：`persistApiKey` 在原生平台同时写入 sessionStorage 与 localStorage（WebView 进程可被系统回收，sessionStorage 随进程消失导致冷启动要重输密钥）；Web 模式行为不变。
- **Android 模拟器网络拓扑**：MuMu/AOSP 模拟器内本机 IP 为 10.0.2.15（NAT 网段），宿主机后端经 10.0.2.2 映射可达（宿主 LAN IP 与模拟器不同网段，同网段扫描扫不到）；`lanDiscovery.ts` 的候选列表包含 `EMULATOR_HOST_ALIAS=10.0.2.2` 且置于首位优先探测。
- **切换服务器后必须重新初始化**：`useAppInitialization` 的短路条件含 `needsServerSelection`（`isNativeApp() && (needsServerSelection || !isBackendConfigured())`），effect 依赖数组含 `needsServerSelection`，否则选择后端后 `isSystemInitialized` 仍为 null 卡在"无法连接服务"。
- **Android 命令在 git-bash 下路径转换**：`adb shell screencap -p /sdcard/x.png` 的 `/sdcard` 会被 git-bash 转成 Windows 路径，必须写 `//sdcard/x.png`（双斜杠阻止 MSYS 转换）。
- **截图验证用 uiautomator/CDP 而非 Read 图片**：模拟器截图 PNG 在本环境 Read 工具不支持（Unsupported Image），改用 `uiautomator dump`（UI 层级 XML）或 CDP（`Runtime.evaluate` + `awaitPromise`）读取 WebView 内部状态。

## 19.3 2026-08-04 记忆体验重设计新增陷阱

- **长期记忆禁止直存对话原文**：`core/feedback.py` 关键词即时路径必须经 `ConsolidationRunner.extract_turn_async` 后台 LLM 提炼（≤200 字事实 + 模型评估 importance/source_type）后入库；原文只允许存在于短期记忆层。定位方法：长期记忆列表出现 `User asked: ...` 前缀或 importance 恒为 0.7 的内容；修复方向：检查 feedback `_should_persist` 分支是否又恢复了 `persist_content` 原文直存。
- **手动巩固 watermark 仅在成功时推进**：`POST /api/memory/consolidation/run`（以及自动巩固）的 fingerprint 持久化与 watermark 推进只发生在提炼成功后；未配置提炼模型时返回 `extracted=0` 且不消耗短期记忆提炼机会。定位方法：consolidation/run 返回 processed>0 且 extracted=0；修复方向：检查是否又恢复了"失败仍推进 watermark"的防死循环分支（已删除，异常自然传播）。
- **mock ConsolidationRunner 必须设置整数阈值**：测试注入 `FeedbackLayer.set_consolidation_runner` 的 mock 必须设置 `_conversation_threshold=10` 与 `increment_conversation_count` 返回值，否则 `_trigger_consolidation_check_async` 中 `count >= threshold` 对 MagicMock 比较抛 TypeError。
- **前端 React Hooks 不得在 early return 之后声明**：MemoryPage 等组件的 useMemo/useCallback 必须在 loading early return 之前声明，否则数据到达后首帧渲染 Hook 数量不一致，触发 "Rendered more hooks than during the previous render"。
- **真实库上验证状态变更 API 后必须恢复**：用 `validate`/`deprecate` 做连通性验证会真实修改用户记忆状态（validated/deprecated），验证后须将 `state`/`archive_status` 恢复为 `active` 并还原 confidence 原值（SQLite 直改可行；Qdrant 元数据被服务锁定，可用 `archive_long_term_memory(id, "active")` 或接受向量侧差异）。

## 19.5 移动 APP（Capacitor Android）架构

移动端通过 **Capacitor 8** 将现有 React 前端打包为 Android 原生应用，核心能力是**局域网后端自动发现与用户选择接入**。

### 工程结构

```
frontend/
  capacitor.config.ts        # appId=com.openawa.mobile, webDir=dist, allowMixedContent=true
  android/                   # Capacitor Android 原生工程（gradle 8.14.3 + AGP 8.13）
    app/src/main/java/com/openawa/mobile/
      MainActivity.java      # 显式 registerPlugin(LanDiscoveryPlugin.class)
      LanDiscoveryPlugin.java# 本机 IPv4 + 网段前缀获取（@CapacitorPlugin）
```

### 接入流程（APP 首启）

1. `useAppInitialization` 短路：原生容器且未配置后端 → `needsServerSelection=true` → RootGuard 跳 `/server-select`
2. `ServerSelectPage` 自动扫描：原生插件取本机 IP → 枚举同 /24 网段 + `10.0.2.2`（模拟器宿主映射）→ 并发 24 路 fetch 探测 `http://{ip}:8000/api/system/ping`（900ms 超时/个）→ `pong=true` 即命中
3. 用户点击实例 → `setBackendUrl(url)`（持久化 localStorage + 更新 axios baseURL + 重新赋值 `API_BASE_URL` live binding）→ `setNeedsServerSelection(false)` → 初始化重跑
4. 认证走 API Key（Bearer），`persistApiKey` 在原生平台持久化到 localStorage → 冷启动免登录

### 关键设计约束

- **WebView origin 为 `https://localhost`**，后端 CORS 正则 `ALLOW_LAN_ORIGIN_REGEX` 放行 `localhost` 与 `192.168.(0|1|2).x`，WebView 内 XHR/SSE/WS 直连 LAN 后端无需原生 HTTP 桥
- `android:usesCleartextTraffic="true"` + `allowMixedContent=true`：https 页面直连 http://LAN-IP 明文后端
- 原生容器内移除 Google Fonts 外部引用（`disableExternalFontsInNativeApp`），字体回退系统栈
- 扫描/选择页路径 `/server-select`，登录页提供"切换服务器"入口（APP 模式）

### 构建与安装（MuMu 模拟器）

```bash
cd frontend
npm run build && npx cap sync android
cd android && export JAVA_HOME="D:\Program Files\Java\jdk-21" && export ANDROID_HOME="D:\Android\Sdk"
./gradlew.bat assembleDebug --no-daemon   # 产物 app/build/outputs/apk/debug/app-debug.apk
adb -s 127.0.0.1:5555 install -r app/build/outputs/apk/debug/app-debug.apk
adb -s 127.0.0.1:5555 shell am start -n com.openawa.mobile/.MainActivity
```

### 局域网 APK 分发（手机免数据线安装）

后端提供无认证分发页（`backend/api/routes/apk_dist.py`）：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/apk` | 分发页：版本/大小/构建时间 + 下载按钮 + 安装引导 |
| GET | `/apk/dist.css` | 页面样式（同源外链，满足 CSP style-src 'self'） |
| GET | `/apk/download` | APK 下载（`application/vnd.android.package-archive`，文件名 Open-AwA.apk） |

手机浏览器访问 `http://<后端局域网IP>:8000/apk` 即可下载安装，无需数据线。
APK 路径默认锚定 `frontend/android/app/build/outputs/apk/debug/app-debug.apk`，可用 `APK_PATH` 环境变量覆盖；未打包时下载返回 404 引导文案。

后端侧：`ALLOW_LAN_ACCESS=true` 环境变量开启局域网 CORS 放行；`INSTANCE_NAME` 自定义实例名（ping 响应展示用）；`/api/system/ping` 无认证返回 `{pong, version, instance_name, api_prefix, capabilities}` 供 APP 发现。

真机调试：`adb forward tcp:9222 localabstract:webview_devtools_remote_<pid>` 后经 CDP 检查 WebView 状态。

## 19.6 2026-08-06 APP 界面重设计（信号中枢主题）新增陷阱

- **Android WebView 不支持 CSS color-mix()**：`CSS.supports('background', 'color-mix(in srgb, red 50%, blue)')` 在 MuMu WebView 返回 false；且 CSS 压缩器会把同一属性的多条声明合并为最后一条，导致"先写回退色、再写 color-mix 覆盖"的降级策略失效（背景解析为 transparent）。毛玻璃背景必须显式写深浅两套 rgba 常量（浅 `rgba(255,255,255,0.88)` / 深 `rgba(15,23,42,0.88)`），与 ChatInput 移动端模式一致。定位方法：computed style 的 backgroundColor 为 `rgba(0,0,0,0)` 且页面上有 backdrop-filter。
- **移动端底部导航必须用 flex column 布局而非 fixed 覆盖**：AppShell 移动端 `.app-container` 设 `flex-direction: column`，Tab Bar 作为 flex 子项天然避让内容区；`position: fixed; bottom: 0` 的底栏（如 ChatInput）必须 `bottom: calc(var(--tab-bar-height) + var(--safe-area-bottom))` 悬浮于 Tab Bar 之上，键盘弹起时由 inline style 覆盖 bottom。
- **git-bash 下 node 脚本参数以 `/` 开头会被 MSYS 路径转换**：`node cdp-helper.cjs nav "/memory"` 会把参数转成 `D:/Program Files/Git/memory`；必须 `MSYS_NO_PATHCONV=1` 前缀执行。
- **uiautomator dump 中 WebView 按钮的 aria-label 覆盖 text 字段**：带 aria-label 的按钮其可见文本不会出现在 text 属性中（显示为 aria-label 值）；验证可见文本时用 CDP 读取或先去掉 aria-label。
- **CDP 截图 PNG/JPEG 在 Read 工具均不支持**：视觉验证用 DOM computed style（getComputedStyle）+ 截图像素颜色统计（PIL）替代。
- **CDP 路由验证模式**：`frontend/scripts/cdp-helper.cjs`（eval/nav/shot）+ `verify-routes.cjs`（24 路由批量验收）可复用；TanStack Router 监听 popstate，导航用 `history.pushState` + 派发 `PopStateEvent` 即可，无需整页刷新。

---

## 20. API Path Prefix

All API routes use prefix `settings.API_V1_STR` (`/api`) except MCP, billing, marketplace, security, weixin, tools, subagents, system (diagnostics), and test-scenarios which use their own prefixes. See `main.py` lines 390-417 for the full registration list.

---

## 21. Key Documentation

- [AGENTS.md](AGENTS.md) — 通用 AI Agent 规则契约（自主权边界、记忆协议、迭代闭环、反模式）
- [README.md](README.md) — Project overview, capabilities, quick start
- [CODE_WIKI.md](docs/CODE_WIKI.md) — Comprehensive code wiki (1500+ lines): six-layer architecture, full module deep-dives, class/function quick reference, dependency graph
- [PROJECT_DOCUMENTATION.md](docs/PROJECT_DOCUMENTATION.md) — Detailed technical documentation
- [docs/架构/后端架构说明.md](docs/架构/后端架构说明.md) — Backend architecture details
- [docs/架构/前端架构说明.md](docs/架构/前端架构说明.md) — Frontend architecture details
- [docs/指南/部署与运行说明.md](docs/指南/部署与运行说明.md) — Deployment guide
- [docs/指南/测试说明.md](docs/指南/测试说明.md) — Testing strategy
- [docs/插件开发手册/](docs/插件开发手册/) — Plugin development guide

## 19.7 2026-08-06 APP 卡死修复（WebView 渲染满载）新增陷阱

- **Android WebView 中任何活跃 CSS 动画都会强制整页 60fps 重绘**：哪怕只是 6x6 元素的 opacity 动画（gfxinfo 对照实验：仅禁 6x6 呼吸灯动画，帧率 60fps→2fps，20s 1200帧→0帧）。APP 长时间运行会拖垮渲染线程卡死整个手机。**硬性规则：APP 页面空闲状态必须零 running 动画**；loading/spinner/流式指示动画只允许在对应状态存在且状态结束必须卸载/停用。验证方法：`node scripts/verify-animations.cjs`（逐路由检查 getAnimations）+ `dumpsys gfxinfo com.openawa.mobile`（空闲 20s 帧数应为 0）。修复方向：动画元素静态化或条件渲染（如 `stats.running > 0 ? styles['stat-spin'] : ''`）。
- **前端 WS/SSE URL 不得硬编码 /api 前缀**：`API_BASE_URL` 可能已含 `/api`（lanDiscovery 返回"接入用 API 基址" `http://ip:8000/api`），硬编码 `/api` 会形成 `/api/api` 双前缀 404/403。必须按 `API_BASE_URL.includes('/api')` 条件补全（参考 TerminalPane 的 apiPrefix 模式）。定位方法：浏览器/WebView 控制台出现 `ws://host/api/api/...` 或 `POST /api/api/... 404`。
- **后端 terminal 路由注册在 /api 前缀下**：main.py `include_router(terminal_router, prefix=API_V1_STR)`，实际路径为 `/api/terminal/...`（HTTP 与 WS 都是）；terminalApi 的 BASE 保持 `/terminal`（sharedApi baseURL 已含 /api），TerminalPane WS 拼接需条件补全 /api。
- **WebSocket 认证失败（4001/4002）必须停止重连**：token 不会自行变好，重连只会制造动画常驻 + 连接风暴。inbox 流与 TerminalPane 均应在 onclose 检查 close code 停止（AUTH_FAILED_CLOSE_CODES）。
- **EventSource 在 APP（WebView origin=https://localhost）内不得用相对路径**：相对路径请求 WebView 自身返回 text/html 404，必须用 API_BASE_URL 拼绝对地址（同样注意 /api 双前缀）。

## 19.8 2026-08-06 WebSocket 鉴权统一（api.security.ws_auth）

- **WS 鉴权必须支持 API Key 与 JWT 双路径**：`api/security/ws_auth.py` 的 `resolve_ws_user_from_token`（API Key compare_digest → owner；JWT decode → user）是 chat/terminal/weixin 共用的唯一实现源。terminal.py 曾只认 JWT（decode_access_token），APP（API Key 登录）下 WS 永远 4002 被拒 → 前端无限重连。**任何新增 WS 端点必须使用该函数**，禁止重复实现 decode_access_token 单路径。
- **terminal.py 是绑定导入**：测试 monkeypatch 必须 patch `terminal_route.resolve_ws_user_from_token`（模块内绑定名），patch `api.security.ws_auth.resolve_ws_user_from_token`（模块属性）对绑定导入不生效。

## 19.10 2026-08-08 APP OTA 更新与移动端布局新增陷阱

- **OTA versionCode 递增基准必须是 build.gradle 而非 manifest**：manifest.json 只是发布产物，可能滞后于设备已装版本（v0.03 时手动构建过 versionCode 5，manifest 却停留在 2/3）；从 manifest 递增会发布比设备更低的 versionCode，`update-check` 恒返回 `has_update=false`，APP 永不弹更新提示。定位方法：设备 `dumpsys package com.openawa.mobile | grep versionCode` 大于 manifest `version_code`，而后端日志只有部署验证时的 update-check 请求、没有设备的；修复方向：`release-apk.ps1` 从 build.gradle 当前 versionCode +1（显式参数可覆盖），发布后必须验证 `version_code > 设备已装`。
- **release-apk.ps1 读 manifest.json 必须显式 `-Encoding UTF8`**：manifest 是 UTF-8 无 BOM 且含中文 changelog，PowerShell 5.1 的 Get-Content 默认按 ANSI(GBK) 解码出乱码，`ConvertFrom-Json` 直接抛 "Invalid object passed in"；写回必须 `WriteAllText(…, New-Object System.Text.UTF8Encoding $false)` 保持无 BOM。
- **构建 APK 前必须先 `npx cap sync android`**：release-apk.ps1 直接 gradle assembleDebug，若 android 工程 assets 是旧 dist，产物是"旧前端 + 新版本号"；判别方法：新版本 APK 大小与旧版一字不差（如 6314014 bytes）。gradle 日志中 `:app:mergeDebugAssets` 显示 UP-TO-DATE 也说明 dist 未变。
- **loading-fallback 是全局工具类，必须有 CSS 定义**：`RouteGuards.tsx`/`AppShell.tsx` 多处使用 `loading-fallback`（加载占位与重连页），global.css 曾完全缺失该定义导致"暂时无法连接服务"页内容裸渲染卡左上角；重连页另用 `reconnect-page`（min-height:100vh + flex 居中）。定位方法：grep 全局 CSS 无 `.loading-fallback` 匹配；修复方向：任何新增的全局类必须在 `src/styles/global.css` 补定义并带主题 token。
- **uiautomator dump 看不到 WebView 内部 DOM**：弹窗、按钮、文本等 WebView 渲染内容在 uiautomator XML 中不可见（仅系统原生 UI 如安装对话框可见），APP 内 UI 验证必须用 CDP（`adb forward tcp:9222 localabstract:webview_devtools_remote_<pid>` + `frontend/scripts/cdp-helper.cjs eval`）；git-bash 下 adb pull/shell 访问 /sdcard 路径需 `MSYS_NO_PATHCONV=1` 或双斜杠，否则被 MSYS 转成 Windows 路径。
- **移动端抽屉打开入口统一走底部 Tab Bar "更多"**：Sidebar 左上角汉堡按钮已删除（原位置改为 MobileUserArea 头像+姓名，点击进 /user），移动端完整导航只能经 `useMobileNavStore.openDrawer`（MobileTabBar "更多"）打开；新增移动端导航入口时不得在左上角再造汉堡按钮，测试驱动抽屉也走 store 而非按钮。

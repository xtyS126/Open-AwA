# WorkbenchProject 与统一项目上下文实施计划

> **For agentic workers:** 按任务逐项执行；每个生产变更必须遵循 RED、确认预期失败、GREEN、定向回归。并行执行者只能修改明确分配的文件，不得回退共享工作树中的既有改动。

**Goal:** 用独立、用户隔离的 `WorkbenchProject + WorkbenchContext` 替换客户端绝对路径权威，让 `/workbench/projects`、`/workbench/editor`、`/workbench/agents` 共享持续 `project_id`，并让 Coding、ACP、Terminal、Preview 消费同一个服务端解析结果。

**Architecture:** 新建不依赖 FastAPI 的 `backend/workbench/` 领域包，负责项目所有权、允许根、规范路径与漂移校验；API 路由只映射领域异常。数据库同时维护 ORM、Alembic revision 与当前生产所需的启动期幂等迁移。前端建立真实嵌套 `WorkbenchShell`、服务端 context store 和项目切换事务，绝不把 `projectDir/projectCwd/cwd/resolved_root` 作为授权输入。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、SQLAlchemy、Alembic、SQLite、React 18、TypeScript、TanStack Router、Zustand、Vitest、Pytest、Playwright。

**执行边界:** 共享工作树已有大量用户与助手域改动；不得回退、覆盖或格式化无关文件，不得读写真实 `var/data/openawa.db` 及 WAL/SHM，不得删除真实项目目录，不得修改已有 Alembic revision，不得替换正式品牌资源。完整门禁通过前不提交；不执行 push。

**批准规范:** `docs/superpowers/specs/2026-08-12-workbench-project-context-design.md`

---

## 文件职责图

- `backend/db/models/workbench.py`：`WorkbenchProject` 与 `WorkbenchContext` ORM。
- `backend/workbench/`：领域异常、允许根策略、项目 resolver、CRUD/context service、运行时占用查询接口。
- `backend/api/routes/workbench.py`：项目 CRUD、context 与 PreviewLease API。
- `backend/alembic/versions/*_add_workbench_projects.py`：只接当前 `add_consolidation_tables` head 的 revision。
- `backend/db/models/migrations.py`：生产启动期幂等兜底；与 Alembic/ORM schema 等价。
- `frontend/src/features/workbench/`：真实 Shell、项目页、API、context store 与 runtime store。
- `frontend/src/router/index.tsx`：`/workbench` 真实父路由及三个相对子路由。
- `frontend/src/features/coding/`：只用 `project_id` 的编辑器状态与 API。
- `frontend/src/features/vibe-coding/`：只用 `project_id` 的 ACP、Terminal 与 Preview 运行时。

## Task 1：锁定 ORM 与迁移契约

**Files:**
- Create: `backend/db/models/workbench.py`
- Modify: `backend/db/models/__init__.py`
- Modify: `backend/db/models/base.py`
- Modify: `backend/db/models/migrations.py`
- Create: `backend/alembic/versions/20260812_1200_add_workbench_projects.py`
- Create: `backend/tests/test_workbench_models.py`
- Create: `backend/tests/test_workbench_migration.py`

- [ ] **Step 1: 写 ORM RED**

断言两张表字段、无长度字符串 `user_id`、`users.id` CASCADE、项目删除时 context SET NULL、`(user_id, canonical_root)` 唯一约束、`(user_id, is_enabled, last_opened_at)` 复合索引，以及 `registered_root/canonical_root` 不可空。

- [ ] **Step 2: 运行 RED 并确认模型或表不存在**

Run:

```powershell
& 'D:\代码\Open-AwA\.venv\Scripts\python.exe' -m pytest --no-cov backend/tests/test_workbench_models.py -q
```

Expected: 收集成功，因 `db.models.workbench` 或表定义不存在失败。

- [ ] **Step 3: 写 Alembic 升降级 RED**

使用 `tmp_path` 创建临时 SQLite URL，覆盖：当前静态单 head、前一 revision 到新 head、downgrade 一步、再次 upgrade、空库与带用户样本数据、索引/唯一约束/外键、临时磁盘目录不被删除。测试不得连接真实 `var/data/openawa.db`。

- [ ] **Step 4: 实现 ORM、revision 与模型注册**

项目 ID 使用服务端生成的字符串 UUID；时间字段统一 UTC。revision 的 `down_revision = "add_consolidation_tables"`，不改任何旧 revision。downgrade 先删 context，再逆序删项目索引和表。

- [ ] **Step 5: 实现幂等 runtime migration**

新增 `_migrate_workbench_tables(use_engine=None)`，仅创建缺失表/关键索引；接入 `init_db()`。禁止手写与 ORM 不同的列类型或默认值。

- [ ] **Step 6: 证明三条 schema 路径等价并覆盖真实桥接顺序**

把 Alembic head、`Base.metadata.create_all()`、runtime migration 的 inspector 输出规范化后比较表、列、nullable、PK、FK、唯一约束与索引。revision 遇到两张 runtime-created 表时仅在 schema 完全一致后采纳；部分存在或不一致 fail-fast。测试 `旧 DB -> runtime create -> Alembic upgrade` 和 `旧 DB -> Alembic upgrade -> 新代码 startup`。运行两份测试到 GREEN。

## Task 2：实现领域级路径策略与 resolver

**Files:**
- Create: `backend/workbench/__init__.py`
- Create: `backend/workbench/errors.py`
- Create: `backend/workbench/path_policy.py`
- Create: `backend/workbench/project_service.py`
- Create: `backend/workbench/runtime_registry.py`
- Modify: `backend/config/settings.py`
- Create: `backend/tests/test_workbench_path_policy.py`
- Create: `backend/tests/test_workbench_project_service.py`

- [ ] **Step 1: 写允许根与路径 RED**

覆盖空值、相对路径、NUL、文件、系统/驱动器/用户主目录根、允许根外、`..`、符号链接逃逸、Windows junction、大小写规范化、目录消失与登记后链接漂移。解析器不得自动创建客户端路径。

- [ ] **Step 2: 写所有权 RED**

`get_owned_project` 必须在同一次查询中包含项目 ID 与用户 ID；不存在和越权抛同一个 `ProjectNotFound`。禁用、根漂移和允许根变化分别抛领域异常，且领域包不导入 FastAPI。

- [ ] **Step 3: 运行 RED 并确认缺失实现**

Run:

```powershell
& 'D:\代码\Open-AwA\.venv\Scripts\python.exe' -m pytest --no-cov backend/tests/test_workbench_path_policy.py backend/tests/test_workbench_project_service.py -q
```

- [ ] **Step 4: 实现 `WORKBENCH_ALLOWED_ROOTS`**

`WORKBENCH_ALLOWED_ROOTS` 与 `WORKBENCH_ALLOWED_ROOTS_BY_USER` 均使用 JSON。管理员/单用户模式才使用全局根，普通多用户必须有 user ID 映射；非法元素使对应配置 fail-fast，空数组表示禁止。默认只使用稳定 `PROJECT_ROOT` 与 `WORKSPACE_DIR`，不使用 `os.getcwd()`。仅在新配置未显式设置时兼容读取一次 `ACP_ALLOWED_WORKDIRS` 并记录 2026.9 移除警告。

- [ ] **Step 5: 实现登记与每次使用重解析**

登记保存原始 `registered_root` 与平台规范化 `canonical_root`；每次消费重新 strict resolve、校验相等、校验允许根和目录存在。子路径解析使用路径分段关系并在 I/O 前复验，不能用字符串前缀。

- [ ] **Step 6: 运行 GREEN 与现有安全回归**

同时运行 Coding sandbox、ACP cwd、Terminal cwd 现有相关测试，确认新领域包没有提前改变旧入口行为。

- [ ] **Step 7: 实现运行时 registry RED/GREEN**

覆盖项目级锁、acquire 内重验项目、release/finally、list/close_all、disable/delete 与并发 acquire 串行化、单 worker 本地运行时门禁。资源类型使用规范固定集合，不接受自由字符串。

## Task 3：实现项目 CRUD 与用户 context API

**Files:**
- Modify: `backend/api/schemas.py`
- Create: `backend/api/routes/workbench.py`
- Modify: `backend/main.py`
- Create: `backend/tests/test_workbench_routes.py`

- [ ] **Step 1: 写 CRUD RED**

覆盖 201 创建、列表排序、单项读取、重命名、启用/禁用、204 删除、重复规范根 409、错误路径 422、允许根外 403、额外字段 422、跨用户与不存在统一 404、删除不触碰临时目录。

- [ ] **Step 2: 写 context RED**

覆盖无上下文、选择、刷新恢复、显式 null、跨用户项目 404、禁用项目 409、更新 `last_opened_at`、禁用当前项目清空 context，以及请求体出现 `resolved_root/project_dir/cwd` 时 422。

- [ ] **Step 3: 运行 RED**

Run:

```powershell
& 'D:\代码\Open-AwA\.venv\Scripts\python.exe' -m pytest --no-cov backend/tests/test_workbench_routes.py -q
```

- [ ] **Step 4: 实现严格 schema 与路由映射**

Create 只接受 `display_name/root`，Update 只接受 `display_name/is_enabled`，Context PATCH 只接受 `project_id`。路由将领域异常统一映射为规范 code，不把绝对路径拼进用户错误。

- [ ] **Step 5: 接入审计和运行时占用门禁**

注册、选择、禁用、删除记录结构化审计。活动 ACP/Terminal/Preview 存在时禁用或删除返回 `409 workbench_project_in_use`；测试使用可注入的占用查询假对象，不启动真实子进程。

- [ ] **Step 6: 运行 GREEN 与认证回归**

运行 workbench routes、auth/dependencies、workspace 相关测试；确认 Workspace API 未被修改。

## Task 4：把 Coding 全入口迁移到 `project_id`

**Files:**
- Modify: `backend/api/routes/coding.py`
- Create: `backend/tests/test_coding_workbench_project.py`
- Modify: `backend/tests/test_coding_api.py` 或当前实际 Coding 测试文件

- [ ] **Step 1: 写全入口 RED**

参数化覆盖 tree、list、read、write、search、Git、AST、LSP、文件预览/下载。每个入口都要求 `project_id`；缺失返回 `workbench_project_required`，越权/不存在统一 404，禁用/漂移 fail-closed，旧 `project_dir` 不得继续执行。

- [ ] **Step 2: 运行 RED 并确认旧接口仍接受绝对路径**

- [ ] **Step 3: 用 resolver 替换 `_get_project_dir`**

保留 `_validate_file_path` 的敏感文件与项目内二次策略，但其 root 必须来自 resolver。所有 body/query schema 统一改为 `project_id`，不能遗漏 Git/AST/LSP 或下载入口。

- [ ] **Step 4: 运行 GREEN 与 Coding 定向回归**

验证读写临时项目、symlink escape、敏感文件、Git 非仓库错误、LSP 可选依赖降级。

## Task 5：把 ACP 与 Terminal 迁移到 `project_id`

**Files:**
- Modify: `backend/api/routes/acp.py`
- Modify: `backend/api/routes/terminal.py`
- Modify: `backend/acp_host/service.py`（仅在项目重新校验需要服务层接口时）
- Modify: `backend/tests/test_acp_routes.py`
- Modify: `backend/tests/test_terminal_pty.py`
- Create: `backend/tests/test_terminal_workbench_project.py`

- [ ] **Step 1: 写 ACP RED**

create/status/install 只接受 `project_id`；session metadata 保存 project ID；列表按项目过滤；prompt、permission、cancel、close 前重验 owner/启用状态/根漂移；跨用户、禁用、删除后关闭并拒绝。

- [ ] **Step 2: 写 Terminal RED**

普通终端与 PTY 创建、WS 重连只接受 `project_id`；session metadata 保存 owner 与项目；跨项目/跨用户 session ID 拒绝；响应不把 cwd 当授权输入；现有 API Key/JWT 双鉴权和 4001/4002 不重连行为保持。

- [ ] **Step 3: 运行 RED**

- [ ] **Step 4: 删除公共 cwd 权威路径**

移除或封闭 ACP/Terminal 模块级 allowed roots 与 `_validate_cwd` 运行入口，统一调用 resolver。内部子进程仍接收 resolver 产出的 cwd，但 API 响应和请求不依赖客户端绝对路径。

- [ ] **Step 5: 接入项目占用查询**

ACP/Terminal 注册活动项目资源；关闭与空闲淘汰时注销。项目普通页面切换不杀进程，项目禁用/删除必须等待资源关闭。

- [ ] **Step 6: 运行 GREEN 与生命周期回归**

验证 permission 挂起恢复、cancel/close、进程树清理、PTY quota/淘汰、WS owner 校验与无残留子进程。

## Task 6：实现项目级 PreviewLease

**Files:**
- Create: `backend/workbench/preview_lease.py`
- Modify: `backend/api/routes/workbench.py`
- Modify: `backend/api/routes/preview_proxy.py`
- Modify: `backend/tests/test_preview_routes.py`
- Create: `backend/tests/test_workbench_preview_lease.py`

- [ ] **Step 1: 写 lease RED**

覆盖签发、过期、关闭、owner/project/port/session 绑定、跨用户、同用户跨项目、关联 session 结束、项目禁用/删除以及服务重启后内存 lease 失效。

- [ ] **Step 2: 写代理边界 RED**

合法白名单端口但无 lease 也必须拒绝；代理路径为 `/api/workbench/projects/{project_id}/previews/{preview_id}/{path:path}`；仍固定回环地址并保持现有 SSRF 与生产禁用门禁。

- [ ] **Step 3: 实现进程内 lease registry**

lease ID 不可预测，含绝对过期时间；签发前验证关联 ACP/Terminal session 与 project；查询时重验 resolver。注册表提供测试 reset，不跨测试泄漏。

- [ ] **Step 4: 运行 GREEN 与 preview 回归**

验证 Markdown/Text/Office 下载与代理错误转发均不丢认证、项目和 lease 门禁。

## Task 7：实现前端 workbench API、store 与项目页

**Files:**
- Create: `frontend/src/features/workbench/workbenchTypes.ts`
- Create: `frontend/src/features/workbench/workbenchApi.ts`
- Create: `frontend/src/features/workbench/store/workbenchProjectStore.ts`
- Create: `frontend/src/features/workbench/store/workbenchRuntimeStore.ts`
- Create: `frontend/src/features/workbench/WorkbenchContextProvider.tsx`
- Create: `frontend/src/features/workbench/WorkbenchProjectsPage.tsx`
- Create: `frontend/src/features/workbench/WorkbenchProjectsPage.module.css`
- Create: `frontend/src/__tests__/features/workbench/workbenchApi.test.ts`
- Create: `frontend/src/__tests__/features/workbench/store/workbenchContextStore.test.ts`
- Create: `frontend/src/__tests__/features/workbench/WorkbenchProjectsPage.test.tsx`

- [ ] **Step 1: 写 API 契约 RED**

递归检查所有请求只发送 `project_id`，不出现 `project_dir/projectCwd/cwd/resolved_root`。项目 ID 使用品牌类型，禁止 `Workspace.id` 直接充当工作台项目 ID。

- [ ] **Step 2: 写 store RED**

覆盖 projects/context 并行 hydration、StrictMode 在途复用、选择成功、失败不乐观保留、显式清空、登出/服务器切换 reset、旧请求完成不污染新用户。

- [ ] **Step 3: 写项目页 RED**

覆盖列表、空/加载/错误、登记、重命名、启用/禁用、删除确认文案、选择后跳转 Editor/Agents，以及 404/409/422 可操作错误。

- [ ] **Step 4: 实现 GREEN**

普通 Web 响应和 store 均不包含 `registered_root/canonical_root/resolved_root`。项目摘要只含 ID、显示名、启用状态和时间戳。

- [ ] **Step 5: 运行定向 GREEN**

同时运行既有 WorkspacePage 测试，证明智能体 Workspace 能力仍保留。

## Task 8：建立真实 WorkbenchShell 父路由

**Files:**
- Create: `frontend/src/features/workbench/WorkbenchShell.tsx`
- Create: `frontend/src/features/workbench/WorkbenchShell.module.css`
- Modify: `frontend/src/router/index.tsx`
- Modify: `frontend/src/layouts/AppShell.tsx`
- Create: `frontend/src/__tests__/router/workbenchRoutes.test.tsx`
- Create: `frontend/src/__tests__/layouts/AppShell.workbenchPersistence.test.tsx`

- [ ] **Step 1: 写嵌套路由 RED**

三个 L2 的 parent 必须是同一个 workbench route；跨 L2 导航时 Shell/Provider mount counter 保持 1；直接深链渲染共享项目栏和正确叶子。

- [ ] **Step 2: 写 transition key RED**

`/workbench/projects|editor|agents` 得到同一个领域 key，跨到 `/assistant` 才改变；工作台内部状态引用在 L2 导航后保持。

- [ ] **Step 3: 实现真实 route tree**

保留 `routeDefinitions` 的完整规范路径供清单与退役门禁读取，但 route 构造将三个工作台定义挂到相对 child path。三个页面不得分别包 Shell。

- [ ] **Step 4: 改 `AppShell` 为领域级 key**

GlobalTopBar 与 DomainLocalNav 位置保持，WorkbenchShell 在其下渲染项目栏与叶子 Outlet。跨领域动画存在，工作台 L2 不重挂父壳。

- [ ] **Step 5: 运行路由、Sidebar、MobileTabBar 回归**

## Task 9：迁移前端 Coding 状态与 API

**Files:**
- Modify: `frontend/src/features/coding/codingApi.ts`
- Modify: `frontend/src/features/coding/store/codingStore.ts`
- Modify: `frontend/src/features/coding/CodingPage.tsx`
- Modify: `frontend/src/features/coding/components/FileTree.tsx`
- Modify: `frontend/src/features/coding/components/EditorPane.tsx`
- Modify: `frontend/src/features/coding/components/GitPanel.tsx`
- Modify: 当前 Coding AST/LSP/Preview 调用组件
- Create: `frontend/src/__tests__/features/coding/codingWorkbenchProject.test.tsx`
- Create: `frontend/src/__tests__/features/coding/store/codingStore.workbench.test.ts`

- [ ] **Step 1: 写无项目阻断 RED**

无 context 时显示选择项目动作，tree/read/Git/AST/LSP 调用均为零；有项目时每个调用携带同一 `project_id`。

- [ ] **Step 2: 写切换事务 RED**

未保存文件、Git 写操作或进行中请求阻断切换；确认后取消旧请求、清空服务端派生状态并恢复目标项目内存快照；失败回滚；旧异步结果不得写入新项目。

- [ ] **Step 3: 移除 `projectDir` 权威状态**

API 与组件只消费 active project ID。全局编辑器偏好保留；文件树、Git、Diff、搜索和 LSP 不跨项目；dirty buffer 仅进入对应项目的内存快照，不写 localStorage。

- [ ] **Step 4: 运行 Coding 前端 GREEN**

## Task 10：迁移前端 ACP、Terminal 与 Preview runtime

**Files:**
- Create: `frontend/src/features/workbench/store/workbenchRuntimeStore.ts`
- Create: `frontend/src/features/workbench/components/WorkbenchRuntimeDock.tsx`
- Modify: `frontend/src/features/vibe-coding/VibeCodingPage.tsx`
- Modify: `frontend/src/features/vibe-coding/hooks/useVibeCodingLayout.ts`
- Modify: `frontend/src/shared/api/acpApi.ts`
- Modify: `frontend/src/shared/api/terminalApi.ts`
- Modify: `frontend/src/features/vibe-coding/components/TerminalPane.tsx`
- Modify: `frontend/src/features/vibe-coding/components/FilePreviewPane.tsx`
- Modify: `frontend/src/features/coding/CodingPage.tsx`
- Create: `frontend/src/__tests__/features/workbench/WorkbenchRuntimeDock.test.tsx`
- Create: `frontend/src/__tests__/features/workbench/workbenchRuntimeStore.test.ts`

- [ ] **Step 1: 写 runtime store RED**

ACP selected agent/session、dock、terminal binding 与 preview intent 按 `project_id` 分区；所有异步 action 显式接收项目 ID；换项目不泄漏旧 path/port/session。

- [ ] **Step 2: 写共享 dock RED**

Editor/Agents L2 切换不重新创建 PTY；换项目按切换事务 detach/关闭旧订阅；preview lease 只用于所属项目；项目切换撤销旧 Blob URL。

- [ ] **Step 3: 移除 `projectCwd/cwd` 前端输入**

ACP create/status/install、Terminal/PTY、Preview 全部发送 `project_id`。文件预览 path 必须是项目相对路径；网页预览必须先取得 PreviewLease。

- [ ] **Step 4: 收口双终端宿主**

WorkbenchShell 下只保留一套共享 PTY runtime。Coding 的旧 `TerminalPanel` 从运行路径退场，但仅在全仓确认无引用后删除文件；不能顺手删除其他 Coding 能力。

- [ ] **Step 5: 运行 ACP/Terminal/Preview 前端回归**

## Task 11：补齐导航 manifest 与四语言门禁

**Files:**
- Modify: `frontend/src/shared/navigation/navigationManifest.ts`
- Modify: `frontend/src/i18n/locales/zh-CN.ts`
- Modify: `frontend/src/i18n/locales/ja-JP.ts`
- Modify: 仅在缺键时修改 `en-US.ts`、`ru-RU.ts`
- Modify: `frontend/src/__tests__/shared/i18n/i18n.test.tsx`
- Modify: `frontend/src/__tests__/shared/navigation/navigationManifest.test.ts`

- [ ] **Step 1: 写 child label RED**

递归遍历五域全部 children，四语言每个 `labelKey` 都必须存在且非空；中文/日文 `nav.workbench.agents` 不得继续是临时英文 `Agents`。

- [ ] **Step 2: 写项目上下文门禁 RED**

projects 为 false；editor 与 agents 为 true。无项目时由 WorkbenchShell 呈现空状态，不由导航清单静默隐藏规范入口。

- [ ] **Step 3: 修复翻译与 manifest 到 GREEN**

全仓扫描内部生成的旧 `/workspace`、`/coding`、`/vibe-coding` URL，允许路由重定向声明和明确测试夹具，不允许新业务链接生成旧 URL。

## Task 12：迁移、全量、服务与浏览器验收

**Files:**
- Create: `frontend/tests/e2e/compatibility/workbench-shell-acceptance.spec.ts`
- Modify: `frontend/tests/e2e/auth.ts`（仅在隔离项目 fixture 需要时）
- Modify: `frontend/tests/e2e/support/start_backend.py`（仅在新增隔离目录环境变量需要时）
- Update: `docs/superpowers/plans/2026-08-12-workbench-project-context.md`
- Update: `docs/design/cross-platform-navigation-redesign-2026-08-09/implementation-and-acceptance.md`
- Update: `CLAUDE.md` / `AGENTS.md` 仅在出现新的可复用硬约束或坑点时

- [ ] **Step 1: 迁移验收**

在临时 SQLite 上执行前一 revision -> head、downgrade 一步、再 upgrade；核对 schema、外键与样本数据。不得对真实数据库运行 downgrade。

- [ ] **Step 2: 后端定向与分组全量**

先运行本计划新增的所有测试，再按项目既有分组策略运行 backend tests；收集失败时最多自愈三次。同一 collection/ACL 错误达到停手条件后转隔离环境，不在用户工作区反复重试。

- [ ] **Step 3: 前端全量门禁**

Run:

```powershell
Set-Location frontend
npm run test
npm run typecheck
npm run lint
npm run build
```

记录通过数量、构建模块数以及与本功能无关的既知门禁例外。

- [ ] **Step 4: 隔离服务与 API**

使用临时 `DATABASE_URL`、`LOG_DIR`、`INITIALIZED_MARKER_PATH`、工作区根和 Playwright `webServer`，验证 `/api/system/ping`、项目 CRUD/context、Coding、ACP、Terminal 与 PreviewLease。核对最终监听 PID，不只停止启动脚本初始 PID。

- [ ] **Step 5: 五档浏览器验收**

至少覆盖 375、480、768、1024、1440 宽度：登记两个临时项目；同项目 Editor/Agents/Projects 切换保留 Shell/context；项目切换不泄漏文件、Diff、Git、ACP、Terminal、Preview；reload/深链/后退/前进恢复；用户 B 不能访问用户 A 项目；删除登记后磁盘标记文件仍存在；无横向溢出、pageerror 或 error console。

- [ ] **Step 6: 端口与数据清理证据**

验收结束确认测试端口释放、Uvicorn/Vite/Playwright/终端子进程无残留、临时目录可删除、真实 `var/` 未改变。

## Task 13：文档、记忆与最终差异审查

**Files:**
- Update: `C:\Users\23941\.trae-cn\memory\projects\-d----Open-AwA\2026-08-12\topics.md`
- Update: `C:\Users\23941\.trae-cn\memory\projects\-d----Open-AwA\project_memory.md`（仅有新硬约束时）
- Update: 本计划 checkbox 与验收记录

- [ ] **Step 1: 更新 A3 验收台账**

明确 Workbench Task 2 页面合并的真实完成范围、剩余 Automation/Android/Electron/品牌授权缺口，不能把工作台切片冒充整体 A3 完成。

- [ ] **Step 2: 沉淀项目记忆**

topics 记录实际改动、测试数量、浏览器证据、迁移证据、端口清理和已知例外。只有发现新硬约束才更新 project_memory/CLAUDE/AGENTS，避免重复堆叠。

- [ ] **Step 3: 最终工作树审查**

运行 `git status --short`、任务文件 `git diff --check`、无 Emoji/英文代码注释门禁、旧绝对路径权威扫描、真实数据路径扫描。只审查本任务改动，不把既有未提交文件归功于本任务。

- [ ] **Step 4: 按完整六步门禁决定提交**

只有全部要求通过、文档和记忆完成、没有真实数据或无关改动混入时，才可按项目规则选择性 `git add` 并提交到 main；不执行 push。若任一必需门禁连续三次失败，停止并报告，不强行 commit。

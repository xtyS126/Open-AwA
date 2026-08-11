# WorkbenchProject 与统一项目上下文设计规范

> 日期：2026-08-12  
> 状态：架构选择与实施边界已批准  
> 适用范围：Open-AwA Web 工作台、Coding、ACP、终端与文件预览  
> 架构选择：独立服务端权威 `WorkbenchProject + WorkbenchContext`，不复用 `Workspace.id`

## 1. 背景与决策

A3 导航将工作台统一为“项目、编辑、Agents”三个二级视图，并要求三者共享持续的 `project_id` 上下文。当前实现不满足这一要求：项目页复用智能体配置领域的 `WorkspacePage`，Coding 由客户端传递 `project_dir`，Vibe Coding 由页面局部状态传递 `projectCwd`，终端和 ACP 还维护各自的绝对路径白名单。绝对路径既无法表达用户所有权，也无法在页面切换、刷新和深链恢复时提供稳定身份。

本规范采用独立的服务端权威模型：

- `WorkbenchProject` 表示某个用户登记的代码项目引用。
- `WorkbenchContext` 表示该用户当前选中的工作台项目。
- 浏览器只提交不透明的 `project_id`，不能提交权威路径。
- Coding、ACP、终端和文件预览统一调用同一个解析器，把 `project_id` 解析为本次请求可用的 `resolved_root`。
- 现有 `Workspace` 继续承载智能体配置、人设、技能、频道和心跳，不承担代码项目身份。

## 2. 目标

1. 为工作台建立用户隔离、可持久化、可审计的项目身份。
2. 让“项目、编辑、Agents”共享同一个服务端项目上下文，并在刷新、后退、前进和直接深链时恢复。
3. 让 Coding、ACP、终端和预览使用同一个路径解析与安全策略。
4. 阻止客户端绝对路径、路径遍历、符号链接或 Windows junction 绕过允许根与项目登记。
5. 切换二级页面时保留同项目状态；切换项目时清除或按项目隔离旧项目状态。
6. 为旧数据库同时提供 Alembic revision 与启动期幂等迁移，并证明两条建库路径 schema 等价。
7. 保持旧规范路由重定向可用，不恢复重复页面入口。

## 3. 非目标

- 不删除或重构现有智能体 `Workspace` 能力。
- 不删除磁盘上的项目目录、文件、Git 仓库或用户运行数据。
- 不设计远程容器、SSH 工作区或云端仓库同步。
- 不在本切片统一 Automation Run 模型。
- 不替换正式品牌资源、桌面图标、Android `mipmap` 或 PWA 图标。
- 不允许前端自行发现任意本机目录；项目根必须通过服务端登记接口创建。

## 4. 领域模型

### 4.1 `workbench_projects`

| 字段 | 类型 | 约束 | 语义 |
|---|---|---|---|
| `id` | `String` | 主键，非空 | 服务端生成的不透明项目 ID |
| `user_id` | `String` | `users.id` 外键，`ON DELETE CASCADE`，非空 | 项目所有者；与无长度 `String` 的 `User.id` 同型 |
| `display_name` | `String(200)` | 非空 | 用户可修改的显示名称 |
| `registered_root` | `Text` | 非空 | 登记时用户提交的路径文本，仅用于服务端受控审计和重新解析 |
| `canonical_root` | `Text` | 非空 | 登记时解析后的规范绝对路径，用于唯一性与漂移检测 |
| `is_enabled` | `Boolean` | 非空，默认 `true` | 是否允许被解析和使用 |
| `created_at` | `DateTime(timezone=True)` | 非空 | 创建时间 |
| `updated_at` | `DateTime(timezone=True)` | 非空 | 最后修改时间 |
| `last_opened_at` | `DateTime(timezone=True)` | 可空 | 最近被设为当前项目的时间 |

表级约束与索引：

- 唯一约束 `uq_workbench_projects_user_canonical_root(user_id, canonical_root)`。
- 普通索引 `ix_workbench_projects_user_enabled_opened(user_id, is_enabled, last_opened_at)`。
- `id` 与 `user_id` 的查询必须在同一个 SQL 条件中完成；不存在和越权都返回 404。
- `canonical_root` 创建后不可通过 PATCH 修改。变更根目录必须新建登记记录，避免项目身份静默指向另一目录。
- DELETE 物理删除登记记录，但绝不删除 `registered_root` 或 `canonical_root` 对应的磁盘目录。

### 4.2 `workbench_contexts`

| 字段 | 类型 | 约束 | 语义 |
|---|---|---|---|
| `user_id` | `String` | 主键；`users.id` 外键，`ON DELETE CASCADE` | 每个用户至多一个上下文 |
| `current_project_id` | `String` | 可空；`workbench_projects.id` 外键，`ON DELETE SET NULL` | 当前项目 |
| `updated_at` | `DateTime(timezone=True)` | 非空 | 上下文最后更新时间 |

应用层还必须验证 `current_project_id` 属于同一 `user_id` 且项目已启用。首版有意保留普通单列外键以维持 `ON DELETE SET NULL`；它不能在数据库层表达跨表所有权，因此所有 context 写入都通过领域服务完成，启动时扫描并清空跨用户或失效引用，禁止路由直接赋值。复合外键与 `SET NULL` 会同时尝试清空非空 `user_id`，本切片不采用该方案。

### 4.3 删除语义

- 删除用户：数据库级联删除其 `WorkbenchProject` 与 `WorkbenchContext` 记录。
- 删除当前项目：`WorkbenchContext.current_project_id` 由数据库置空；领域服务提交后返回空上下文。
- 删除非当前项目：只删除该登记记录。
- 项目仍有关联的 ACP、Terminal 或 Preview 运行时资源时，禁用与删除返回 `409 workbench_project_in_use`；用户先关闭运行时资源，再重试。路由不能在仍有持有目录权限的子进程时撤销登记却放任进程继续运行。
- 删除任何项目登记都不能调用文件删除、目录删除、Git 清理或递归移动。
- 审计日志记录“谁在何时删除了哪个登记”，但审计日志不改变物理删除语义。

## 5. API 契约

所有接口要求 `get_current_user`，统一位于 `/api/workbench`。

### 5.1 项目 CRUD

#### `GET /api/workbench/projects`

按 `is_enabled DESC, last_opened_at DESC NULLS LAST, updated_at DESC` 返回当前用户的项目。响应不得包含其他用户记录。

#### `POST /api/workbench/projects`

请求：

```json
{
  "display_name": "Open-AwA",
  "root": "D:\\代码\\Open-AwA"
}
```

行为：规范化显示名称，解析并验证根路径，保存 `registered_root` 与 `canonical_root`。同一用户重复登记同一规范根返回 `409 workbench_project_root_conflict`。数据库仍使用 `(user_id, canonical_root)` 唯一约束；物理根授权由按用户允许根策略控制。两个用户只有在部署管理员明确把同一规范根同时授予二者时才能登记同一目录，这被视为显式共享授权，不是默认行为。

`display_name` 先 trim，trim 后必须为 1 至 200 个 Unicode 字符，拒绝 C0/C1 控制字符。项目 ID 使用 UUID v4 小写字符串。所有时间戳由应用以 UTC 生成；ORM、Alembic 与 runtime migration 使用相同的 `is_enabled=true` 默认值。

#### `GET /api/workbench/projects/{project_id}`

只按 `(id, user_id)` 查询。不存在、属于其他用户或已物理删除统一返回 `404 workbench_project_not_found`。

#### `PATCH /api/workbench/projects/{project_id}`

只允许修改：

```json
{
  "display_name": "Open-AwA 主仓库",
  "is_enabled": true
}
```

禁止提交 `root`、`registered_root`、`canonical_root`、`resolved_root`、`user_id`。禁用当前项目时，服务端在同一事务中清空当前上下文。

#### `DELETE /api/workbench/projects/{project_id}`

无活动运行时资源时返回 `204`。只删除数据库登记；请求处理链不得出现任何磁盘删除函数。重复删除与越权统一返回 404；仍被 ACP、Terminal 或 Preview 使用时返回 `409 workbench_project_in_use`。

### 5.2 当前上下文

#### `GET /api/workbench/context`

无上下文时返回：

```json
{
  "project": null,
  "updated_at": null
}
```

有上下文时返回项目摘要。普通浏览器响应不返回 `registered_root`、`canonical_root` 或 `resolved_root`；服务端内部消费者在同一请求中调用 resolver 获得 `resolved_root`。如需路径诊断，必须使用管理员专用、单独鉴权并写审计的诊断端点，本切片不提供该端点。

#### `PATCH /api/workbench/context`

只接受：

```json
{
  "project_id": "project-id"
}
```

`project_id: null` 表示显式清空。服务端验证所有权、启用状态和路径可用性后，在同一事务中更新 context 以及项目 `last_opened_at`。请求体出现 `resolved_root`、`project_dir`、`cwd` 或其他额外字段时返回 422。

### 5.3 响应白名单

普通 Web API 只使用以下响应结构：

```text
WorkbenchProjectSummaryResponse
  id, display_name, is_enabled, created_at, updated_at, last_opened_at

WorkbenchProjectListResponse
  items: WorkbenchProjectSummaryResponse[]

WorkbenchContextResponse
  project: WorkbenchProjectSummaryResponse | null
  updated_at: datetime | null
```

不返回 `user_id`、`registered_root`、`canonical_root` 或 `resolved_root`。创建请求中的 `root` 只是一次性登记候选值，经服务端验证后不再成为客户端权威。

### 5.4 项目消费接口

Coding、ACP、终端和预览的新契约只接收 `project_id`：

- Coding 查询参数或请求体：`project_id`。
- ACP 会话创建、OpenCode 状态与安装：`project_id`。
- Terminal HTTP 创建与 WebSocket 握手：`project_id`。
- Preview session/proxy 建立：`project_id`，服务端把目标进程与项目绑定。

调用方未传 `project_id` 时不从 `os.getcwd()`、`CODING_PROJECT_DIR`、`project_dir`、`cwd` 或最近一次前端状态推导项目；返回 `409 workbench_project_required`。2026.8 后端 schema 仍识别旧 `project_dir/cwd` 字段，但只返回 `422 legacy_project_path_not_supported` 与 `Sunset: 2026-09-01`，绝不执行该路径；2026.9 删除旧字段。

## 6. 统一项目解析器

### 6.1 服务接口

后端新增不依赖 FastAPI 的独立领域包 `backend/workbench/`，由路由负责把领域异常映射为 HTTP 响应。核心服务提供：

- `get_owned_project(db, user_id, project_id)`。
- `resolve_project_root(db, user_id, project_id, require_enabled=True)`。
- `set_current_project(db, user_id, project_id | None)`。
- `register_project(db, user_id, display_name, registered_root)`。

Coding、ACP、Terminal 与 Preview 只依赖这些公开函数，不导入彼此的私有 `_validate_cwd` 或 `_get_project_dir`。领域包不得导入 `HTTPException`、路由模块或前端契约。

### 6.2 允许根设置

允许根配置使用 JSON，避免 Windows 驱动器冒号和路径分隔符歧义：

- `WORKBENCH_ALLOWED_ROOTS`：JSON 字符串数组，只对 `role=admin` 或明确的单用户部署生效；未设置时默认 `[PROJECT_ROOT, WORKSPACE_DIR]`。
- `WORKBENCH_ALLOWED_ROOTS_BY_USER`：JSON 对象，键为 user ID，值为该用户的绝对根数组；普通用户只能使用自己的映射。
- 设置为空数组表示显式禁止登记；不回退默认值。
- 任意数组元素非法会使整个对应变量加载失败并在启动时 fail-fast，不能静默忽略部分错误。
- 每个根 strict resolve 后按平台规范化去重；父子重叠时保留最窄的显式授权集合，不自动扩权。
- UNC/网络路径首版拒绝；根本身是 symlink/junction 时保存最终真实路径，并在每次使用时复验。

动态 `os.getcwd()` 永远不能成为允许根。普通多用户部署未配置 `WORKBENCH_ALLOWED_ROOTS_BY_USER` 时，普通用户的根集合为空。

兼容策略：

- `ACP_ALLOWED_WORKDIRS` 仅在 2026.8 兼容期作为管理员全局旧配置输入；启动时若 `WORKBENCH_ALLOWED_ROOTS` 未显式设置，则用其替代默认全局根并记录一次弃用警告。2026.9 删除兼容读取。
- `CODING_PROJECT_DIR` 不再作为请求级默认项目，只能用于首次初始化时由管理员显式登记，运行时不能绕过 `project_id`。
- Terminal 的模块级 `_ALLOWED_WORKSPACE_ROOTS = [os.getcwd()]` 被统一解析器替换。

### 6.3 登记时算法

1. 拒绝空字符串、NUL 字符和非绝对路径。
2. 拒绝包含 `~` 的路径，避免把服务进程账户 home 误当登录用户 home；随后执行 `os.path.abspath`、`os.path.realpath` 与 `Path.resolve(strict=True)`。
3. 要求目标存在且是目录。
4. 拒绝文件系统根、驱动器根和用户主目录根。项目必须等于某个显式允许根，或是该允许根的后代；因此默认 `PROJECT_ROOT` 可以登记 Open-AwA 仓库本身，`WORKSPACE_DIR` 可以登记自身或其子项目。配置加载时若允许根本身是系统根、驱动器根或用户主目录根，则整项配置无效并 fail-closed。
5. 使用“路径相等或 `relative_to` 成功”验证规范路径位于某个允许根内；字符串前缀比较不构成授权。
6. Windows 上解析 reparse point/junction 的最终目标，再执行允许根检查。
7. 保存原始输入为 `registered_root`，保存大小写规范化后的最终绝对路径为 `canonical_root`。Windows 唯一性比较使用 `os.path.normcase` 后的值。

### 6.4 每次使用算法

1. 以 `(project_id, user_id)` 查询项目；未命中返回统一 404。
2. `is_enabled=false` 返回 `409 workbench_project_disabled`。
3. 对 `registered_root` 再次执行真实路径解析。
4. 要求新解析值在平台规范化后等于保存的 `canonical_root`；不一致返回 `409 workbench_project_root_changed`，防止符号链接或 junction 登记后漂移。
5. 再次验证当前规范路径仍位于配置允许根内，且目录仍存在。
6. 返回仅在本次请求范围内有效的 `resolved_root`。
7. 文件相对路径再以 `resolved_root` 为边界解析；写操作继续调用现有文件策略，但 `working_dir` 必须是统一结果。

### 6.5 错误模型

错误响应使用结构化 `detail`：

| HTTP | code | 场景 |
|---|---|---|
| 404 | `workbench_project_not_found` | 不存在或越权 |
| 409 | `workbench_project_required` | 需要项目但未选择 |
| 409 | `workbench_project_disabled` | 项目已禁用 |
| 409 | `workbench_project_root_conflict` | 同用户重复登记规范根 |
| 409 | `workbench_project_root_changed` | 登记路径重新解析后发生漂移 |
| 409 | `workbench_project_in_use` | 项目仍有 ACP、Terminal 或 Preview 资源，不能禁用或删除 |
| 422 | `workbench_project_root_invalid` | 路径不存在、非目录、系统根或格式非法 |
| 403 | `workbench_project_root_forbidden` | 路径不在允许根内 |

错误日志只能记录脱敏后的项目 ID、用户 ID 和结构化 code；绝对路径只在受控审计字段中记录，不拼进面向浏览器的错误消息。

### 6.6 本地运行时注册表与并发

新增进程级 `WorkbenchRuntimeRegistry`，是 ACP、Terminal 与 Preview 的唯一活动资源索引：

```text
acquire(user_id, project_id, resource_type, resource_id)
release(user_id, project_id, resource_type, resource_id)
list_active(user_id, project_id)
assert_not_in_use(user_id, project_id)
close_all(user_id, project_id)
```

- `resource_type` 固定为 `acp_session`、`acp_turn`、`terminal_session`、`pty_session`、`opencode_install`、`preview_lease`；Coding 单次文件/Git 写操作使用同一项目锁但不登记长期资源，LSP 进程若跨请求存活则登记为 `lsp_session`。
- 每个 `(user_id, project_id)` 有一把异步锁。资源 acquire、项目 disable/delete 的 in-use 检查与数据库写入共享该锁：acquire 在锁内重新查询项目仍存在且启用后登记；disable/delete 在锁内确认无资源后提交，消除“检查为空后又创建 session”的竞争。
- close/取消/异常/空闲淘汰的 `finally` 必须 release；注册表提供测试 reset 和应用 shutdown 的 `close_all`。
- 普通页面切换不会 revoke 资源。用户可以通过 `GET /api/workbench/projects/{project_id}/runtime-resources` 查看 blocker，并用现有 ACP/Terminal close API 逐个关闭；项目 API 不代替用户强杀有状态任务。
- 当前本地 ACP/Terminal/Preview 本身是进程内 session registry，因此启用这些能力时要求单 Uvicorn worker。检测到多 worker 时本地运行时创建接口返回 `503 workbench_single_worker_runtime_required`；只读项目/Coding API 仍可用。
- 当前没有用户删除公开 API。未来新增用户删除流程时，必须先在用户级锁内 `close_all` 全部项目资源，再删除用户；直接数据库管理操作属于停服维护，不能在运行服务中只依赖 FK CASCADE。

## 7. Coding、ACP、终端与预览迁移

### 7.1 Coding

- `codingApi` 的所有 `projectDir?: string` 改为 `projectId: string`。
- 后端所有 `_get_project_dir(project_dir)` 调用改为依赖统一 resolver。
- 没有项目时 Coding 页面展示项目选择提示，不请求文件树、Git、AST 或 LSP。
- 读写、搜索、Git、AST、LSP 与下载接口全部覆盖相同所有权与路径漂移测试。

### 7.2 ACP

- 会话创建、OpenCode 状态和安装只接收 `project_id`。
- ACP session metadata 同时保存 `project_id` 与创建时的 `resolved_root` 快照；后续每轮执行先重新解析项目，再核对快照，失败时终止而不是继续使用缓存 cwd。
- `chat_id = f"{user_id}:{session_id}"` 的会话隔离保持不变。
- 项目切换不强制杀死其他项目的 ACP 会话，但 UI 只显示当前项目的会话；服务端列表按 `project_id` 过滤。
- prompt、permission、cancel 与 close 在读取 session metadata 后重新验证 owner、项目启用状态和规范根；验证失败即取消并关闭该会话，不能继续使用缓存 cwd。

### 7.3 Terminal

- HTTP 创建和 WebSocket 建立都使用 `project_id`；token 仍不得放入 URL。
- Terminal session metadata 增加 `project_id` 与 owner，重连时验证 owner 与当前项目解析结果。
- 用户切换项目时前端断开当前终端订阅并切换到目标项目的终端集合；旧项目进程不因页面切换立即终止，只能由显式 close、现有配额淘汰或应用 shutdown 结束。
- 项目禁用或删除属于权限撤销，不等同于普通页面切换；存在活动终端时服务端返回 `workbench_project_in_use`，直到终端被显式关闭或按现有空闲淘汰完成。
- HTTP 创建 session 时写入 owner 与 `project_id`；WebSocket 只携带不可预测 session ID，并通过现有 Cookie/API Key/JWT 解析与 Origin 校验取得用户。服务端从 session metadata 读取 project ID 并重验 resolver，WebSocket 不再接受第二份可冲突的客户端 `project_id`。

### 7.4 Preview

- 项目内文件预览与本地开发服务器端口代理是两种接口。文件预览使用 `GET /api/workbench/projects/{project_id}/files/preview?path=<relative>`，继续执行大小、MIME、敏感文件和下载策略；它不需要 PreviewLease。
- 仅有 `project_id + port` 不能证明端口属于该用户或项目。端口代理使用 `POST /api/workbench/projects/{project_id}/previews`，请求为 `{session_kind: "terminal" | "acp", session_id, port}`。服务端用 `psutil` 或等价平台 API 证明监听 `127.0.0.1:port` 的 PID 是关联 session 进程或其后代后才签发 lease；客户端声明本身不构成证明。
- `PreviewLease` 完整字段为 `preview_id`、`user_id`、`project_id`、`port`、`session_kind`、`session_id`、`created_at`、`expires_at`。ID 使用 256 bit CSPRNG；TTL 固定 15 分钟，同一 session 最多 3 个活动 lease；续租再次验证监听 PID 与项目后延长 15 分钟，不得超过关联 session 生命周期。
- `POST .../previews/{preview_id}/renew` 续租，`DELETE .../previews/{preview_id}` 撤销。Terminal/ACP session 关闭、项目禁用、用户登出和应用关闭时自动 revoke。
- 代理接口使用 `/api/workbench/projects/{project_id}/previews/{preview_id}/{path:path}`。每次代理同时验证 lease owner、项目 ID、端口、关联会话存活状态和统一 resolver 结果；缺失 lease、跨项目复用、过期或关联会话结束都拒绝。
- `PreviewLease` 首版是进程内运行时记录，不新增第三张持久化表；服务重启后全部失效。端口代理首版仅在单 Uvicorn worker 模式启用；检测到多 worker 时该能力 fail-closed 返回 `503 preview_single_worker_required`，Coding、ACP 与 Terminal 其他能力继续可用。
- HTTP 代理与 WebSocket 代理都使用同一 lease；WebSocket upgrade 前执行相同 owner、project、session、port 与过期校验。
- 预览文件路径只能是项目根相对路径；文件或启动命令的工作目录来自 resolver。
- 现有固定回环地址、允许端口和 SSRF 目标验证继续生效，统一项目解析不放宽主机、端口或私网策略。
- 切换项目时关闭前端预览连接、撤销 Blob URL，并清空目标项目以外的预览状态。

## 8. 前端架构

新增：

```text
frontend/src/features/workbench/
  WorkbenchShell.tsx
  WorkbenchContextProvider.tsx
  WorkbenchProjectBar.tsx
  WorkbenchProjectsPage.tsx
  workbenchTypes.ts
  workbenchApi.ts
  store/workbenchProjectStore.ts
  store/workbenchRuntimeStore.ts
  components/WorkbenchRuntimeDock.tsx
```

### 8.1 真实共享父路由

路由树必须形成同一个父布局：

```text
/workbench
  WorkbenchShell
    /projects
    /editor
    /agents
```

三个页面不能分别套一份 Shell。`WorkbenchContextProvider` 挂在 Shell 内，仅初始化一次，只负责加载服务端项目/context 与订阅同步；`WorkbenchProjectBar` 负责选择器；`WorkbenchRuntimeDock` 是唯一 Terminal/FilePreview 宿主并位于叶子 Outlet 外。

固定布局层级为：

```text
AppShell
  GlobalTopBar
  main
    DomainLocalNav
    WorkbenchShell
      WorkbenchProjectBar
      WorkbenchRuntimeDock
      Outlet
```

当前 `AppShell` 以完整 `location.pathname` 作为 Outlet transition key，会在三个 L2 之间重挂整个子树。实现时必须改为领域级 key；工作台三个 L2 共用 `workbench` key，跨领域导航仍可重建页面边界。L2 动画只能包叶子 Outlet，不能包共享的 Workbench Shell。

### 8.2 Store 状态

`workbenchProjectStore` 保存：

- `projects`。
- `currentProjectId`，项目摘要始终由 `projects` selector 派生，不保存第二份真相。
- `phase: idle | loading | no-projects | no-selection | ready | invalid | switching | error`。
- `pendingSwitch`、`switchGeneration` 与按 project ID 的 Coding 快照。
- `loadProjects`、`loadContext`、`selectProject`、`confirmSwitch`、`cancelSwitch`、`clearProject`、`resetForServerChange`。

`workbenchRuntimeStore` 按 `project_id` 保存 ACP selected agent/session、dock 状态、Terminal binding 与 Preview intent。所有异步 action 显式接收 `project_id + switchGeneration`，旧响应不得写入新项目。

不得把可提交给后端的 `resolvedRoot`、`projectDir` 或 `cwd` 作为授权状态。服务端切换、登出或用户变化时必须清空 store。

### 8.3 项目页

`WorkbenchProjectsPage` 替代 `/workbench/projects` 对 `WorkspacePage` 的复用，提供：

- 当前用户的项目列表、最近打开状态与启用状态。
- 登记项目、重命名、启用/禁用和删除登记。
- 选择项目后跳转编辑或 Agents。
- 删除确认明确写出“只移除 Open-AwA 登记，不删除磁盘目录”。

现有 `WorkspacePage` 保留在代码库中，其智能体配置能力后续迁移到助手配置或设置时另立任务；本切片不删除它。

### 8.4 项目状态隔离

- 同项目在 `/projects`、`/editor`、`/agents` 间切换：保留打开文件、活动文件、面板选择、终端、ACP 会话选择和预览 intent；file tree、Git、Diff、LSP 与搜索结果可以继续显示当前项目数据，但离开项目时不做持久快照。
- 切换到另一项目是确定的 saga：`ready(old) -> preflighting(target) -> blocked | staging -> PATCH server context -> committing local stores -> ready(target)`。先冻结新操作；存在 dirty 文件、Git 写、运行中命令或 Agent turn 时保持旧项目并显示阻断项。
- dirty 文件默认只保留在旧项目的内存快照，不自动写盘也不静默丢弃；用户可以保存、放弃或取消切换。确认后保存旧项目的 open dirty files、active file 和面板选择，取消旧项目请求，再 PATCH 服务端 context。PATCH 成功后原子切本地项目；本地 commit 异常时立即补偿 PATCH 回旧项目并重新 hydrate，补偿失败则以服务端 GET context 为权威进入 error 状态。
- 首版逐项策略固定为：open/dirty files、active file、面板与 ACP 选择按 project ID 保存在内存；file tree、Git、Diff、LSP、搜索结果切换时清空并重取；Terminal binding 若可 reattach 则按项目保存，否则显式关闭；Preview intent 按项目保存但 Blob/Markdown/Text/iframe 派生内容始终清空；编辑器字体等全局偏好保留。
- 无当前项目：Editor/Agents 显示明确空状态和“选择项目”动作，不发起 Coding、ACP、Terminal 或 Preview 请求。
- `navigationManifest` 中 `workbench.editor.requiresProjectContext` 与 `workbench.agents.requiresProjectContext` 必须为 `true`；projects 保持 `false`。

### 8.5 深链与浏览器历史

- 进入任意 workbench 深链时 Provider 先恢复服务端 context，再渲染消费页面。
- 浏览器后退或前进只改变 L2 路由，不改变当前项目。
- 项目选择成功以服务端 PATCH 结果为准；请求失败不得乐观保留客户端选择。
- 直接访问 Editor/Agents 且无项目时留在规范路由显示空状态，不循环重定向。
- `requiresProjectContext` 只是导航与 UI capability metadata，用来触发 project-required 空状态和阻断业务请求；RouteGuard 不据此重定向。
- 多标签页使用 `BroadcastChannel("openawa-workbench-context")` 广播成功的 context PATCH，并在窗口重新获得 focus 时 refetch。GET/PATCH 响应携带基于 `updated_at` 的 ETag；客户端可用 `If-Match` 防止覆盖较新的标签页选择，冲突返回 409 后重新 hydrate。

## 9. 数据库迁移策略

### 9.1 Alembic

- 新 revision 以当前唯一 head `add_consolidation_tables` 为 `down_revision`。
- upgrade 按父子顺序创建 `workbench_projects`、索引与唯一约束，再创建 `workbench_contexts`。
- downgrade 先删除 `workbench_contexts`，再删除独立索引并删除 `workbench_projects`；表内 unique/FK 随表删除，不在 SQLite 上单独 `drop_constraint`。
- 不修改任何已有 revision。

### 9.2 启动期幂等迁移

当前生产启动仍执行 `Base.metadata.create_all()` 与 `db/models/migrations.py`。因此：

- ORM 模型必须注册到 `Base.metadata`，空库 `create_all` 直接得到新表。
- `migrations.py` 新增 `_migrate_workbench_tables(use_engine=None)`，仅在表不存在时按 ORM metadata 创建，并显式验证关键索引。
- `init_db` 在已有迁移之后调用该函数。
- 幂等迁移不得修改现有项目目录，也不得读写真实 `var/data/openawa.db` 的测试副本。
- 新 Alembic revision 必须识别 runtime/create_all 已经创建的两张表：若两表均存在且完整 schema 与目标严格一致，则跳过建表 DDL，让 Alembic 正常记录新 revision；若只存在一张或任意列、约束、外键、索引不一致，则 fail-fast，不猜测修补。
- 支持两种真实顺序：`旧 DB -> 新代码 runtime create -> Alembic upgrade` 与 `旧 DB -> Alembic upgrade -> 新代码 startup`。downgrade 后必须同时回滚到不含新 ORM 的旧应用版本；不得用新代码再次 startup 后宣称 downgrade 保持。

### 9.3 升降级验证

使用临时 SQLite 数据库分别验证：

1. 前一 revision 升级到新 head。
2. 新表、列、唯一约束、复合索引与外键删除行为。
3. downgrade 一步后两张表消失且旧表与样本数据保留。
4. 再次 upgrade 成功。
5. 空数据库 Alembic 路径。
6. 带用户和旧业务样本数据的升级路径。
7. ORM `create_all`、runtime migration 与 Alembic head 的规范化 schema 等价。
8. SQLite `PRAGMA foreign_keys=ON` 在实际连接上生效。
9. 删除用户只级联登记与 context。
10. 删除项目登记不会删除临时磁盘目录及文件。
11. runtime 先建表再 Alembic upgrade 能正确采纳一致 schema；部分表或不一致 schema 拒绝升级。

## 10. 测试矩阵

### 10.1 后端 RED 测试

- ORM 字段、同型 user FK、唯一约束、CASCADE 与 SET NULL。
- register/list/get/patch/delete 的用户隔离与 404 不泄漏。
- display name 校验、重复规范根、禁用当前项目清空 context。
- 路径不存在、文件、系统根、允许根外、`..`、符号链接和 Windows junction。
- 登记后链接漂移、目录消失、允许根配置变化时 fail-closed。
- context GET/PATCH/null、额外字段 422、跨用户项目 404。
- Coding 全入口拒绝缺失项目、越权项目与旧 `project_dir`。
- ACP 创建/状态/安装、Terminal HTTP/WS、Preview 使用同一 resolver。
- ACP/Terminal session owner 与 `project_id` 隔离。
- Alembic upgrade/downgrade/re-upgrade 与 runtime schema 等价。

### 10.2 前端 RED 测试

- `workbenchApi` 只发送 `project_id`，不发送绝对路径。
- store 初始化、选择、失败回滚、清空与服务器切换重置。
- Provider 在 StrictMode 下复用在途 context 请求。
- Projects 页面 CRUD、删除说明与 404/409/422 错误呈现。
- 真实父路由在三个 L2 页面之间不重挂 Provider。
- 无项目时 Editor/Agents 不调用业务 API。
- 同项目 L2 切换保留状态；换项目清理 Coding/Vibe/Terminal/Preview 状态。
- reload、直接深链、后退、前进恢复同一项目。
- manifest 两个 `requiresProjectContext` 值以及全部 child `labelKey` 四语言非临时值。

### 10.3 回归门禁

- 后端定向 pytest 使用项目 `.venv` 和临时 `DATABASE_URL`/`LOG_DIR`。
- 前端定向 Vitest 后运行全量 `npm run test`、typecheck、任务 ESLint 与 `npm run build`。
- 聊天 SSE/WebSocket、助手域与旧路由重定向不得回归。
- API 未配置真实模型密钥时，`llm_api_key_missing` 只能记录为结构化例外，不能宣称真实模型调用成功。

## 11. 浏览器验收

在隔离数据库、隔离日志和 `reuseExistingServer=false` 下完成：

1. 以用户 A 登记两个临时项目，项目列表显示正确，磁盘内容不被修改。
2. 选择项目一，进入 Editor，打开文件并建立终端；切到 Agents 再返回，文件与同项目状态保留。
3. 切换项目二，确认项目一的打开文件、Diff、终端订阅、ACP 选择与预览不泄漏。
4. 刷新 `/workbench/editor`，服务端恢复项目二。
5. 新标签直接打开 `/workbench/agents`，恢复同一项目；另一个标签切换项目时通过 BroadcastChannel/focus refetch 收敛。
6. 用户 B 无法通过项目一 ID 获取、选择或消费项目；响应与不存在项目一致。
7. 禁用当前项目后 Editor/Agents 显示不可用状态且不再发送文件或进程请求。
8. 删除项目登记后临时目录及标记文件仍存在，context 自动清空。
9. 在 375、480、768、1024、1440 px 验证项目选择器、空状态、导航选中态和键盘焦点；交互目标至少 44×44，`scrollWidth <= clientWidth + 1`，1440 档额外验证 200% 根字号。
10. RuntimeDock 在移动端不遮挡五域底栏或安全区；每档 `pageerror=[]` 且 error-level console 为空。
11. 验收结束后确认隔离端口、Uvicorn/Vite/Playwright 子进程和临时数据库句柄全部释放。

## 12. 安全与可观测性

- 所有资源查询强制用户所有权；ID 不构成授权。
- 所有磁盘操作在请求时重新解析项目根；缓存路径不构成授权。
- 路径比较使用真实路径与路径分段关系，不用字符串前缀。
- 结构化日志至少包含 `event`、`request_id`、`user_id`、`project_id`、`result_code`，不记录密钥、token 或未脱敏的请求体。
- 注册、选择、禁用和删除写入现有审计日志；文件内容与命令正文不进入项目审计事件。
- resolver 失败必须 fail-closed，不回退到当前工作目录或默认项目。

## 13. 交付与回滚边界

交付顺序是 schema 与 resolver、项目 CRUD/context、Coding、ACP/Terminal/Preview、前端 Shell/store/page、跨边界验收。每一步严格执行 RED、确认预期失败、GREEN、定向回归。

回滚时可以回退路由消费和前端 Shell，但不能把浏览器绝对路径恢复为权威契约。数据库 downgrade 仅删除两张新表，不触碰 `Workspace`、Conversation、记忆、计费、插件或磁盘项目目录。未完成全部验证前不得提交；任何 push 均需用户另行确认。

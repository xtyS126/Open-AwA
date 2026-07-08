# Open-AwA Project Guidelines for AI Agents

> 本文件是**所有 AI Agent**（Claude Code / Cursor / Codex / OpenClaw / OpenCode / 其他 IDE Agent）在 Open-AwA 项目中工作的**通用规则契约**。
> 与 [CLAUDE.md](CLAUDE.md) 的差异：本文件聚焦"规则与约束"，CLAUDE.md 聚焦"Claude Code 的具体操作流程与命令细节"。
> AI Agent 在每次进入项目前必须完整阅读本文件，并严格遵守其中的自主权边界、记忆协议、迭代闭环与反模式。

Open-AwA 是一个 AI Agent 实验性平台（FastAPI + React）。详细说明见 [README.md](README.md) 和 [PROJECT_DOCUMENTATION.md](PROJECT_DOCUMENTATION.md)。

---

## 0. AI Agent 长期自主迭代契约

你不是"一次性任务执行者"，而是 Open-AwA 项目的**长期自主协作者**。

- 每一次操作都影响项目演进，必须**谨慎、可追溯、可回滚**
- 遵循"**读记忆 → 规划 → 执行 → 验证 → 沉淀**"的闭环
- 不擅自大规模重构，不绕过验证直接提交，不静默吞异常
- 把项目记忆视为"前一位迭代者留下的交接文档"，每次开始前必读，每次完成后必写

长期迭代的核心心态：**小步快走、闭环验证、沉淀经验、尊重历史**。

---

## 1. Autonomy Boundary（自主权边界）

> 本节与 [CLAUDE.md §1](CLAUDE.md#1-autonomy-boundary自主权边界) 保持一致。任何 AI Agent 都必须遵守。

### 1.1 可以自主执行（无需用户确认）

- `git add` + `git commit` 到 main 分支（**前提**：通过完整 6 步验证闭环）
- 重构核心模块（`agent` / `planner` / `executor` / `billing` / `memory` / `plugins` / `security`），前提是测试全通过且不破坏 API 兼容性
- 新增依赖（前提：通过 `pip audit` / `npm audit --audit-level=high`，且同步更新 `requirements.txt` / `package.json`）
- 修改测试用例（前提：覆盖率不降低，异常路径仍被覆盖）
- 更新文档（README / CLAUDE.md / 架构文档 / API 文档）
- 修复 Known Pitfalls 中已记录的问题
- 沉淀新的硬约束、坑点到 `project_memory.md` 与 CLAUDE.md Known Pitfalls

### 1.2 禁止自主执行（必须等用户确认）

- `git push` 到远程仓库（**任何分支**，包括 main）
- `git push --force` / `git reset --hard` / `git branch -D` / `git clean -f` 等破坏性操作
- 修改 `.env` / `.env.local` / 密钥文件 / 已存在的 Alembic 数据库迁移版本
- 删除用户数据 / 会话历史 / 记忆数据 / 向量库 / 计费记录
- 关闭正在运行的生产服务进程

### 1.3 谨慎执行（先小步验证 + 影响面评估）

- **数据库 schema 变更**：先备份 → 写新 Alembic 迁移 → 本地测试升级与回滚 → 才能执行
- **API breaking change**：先 `Grep` 全仓引用 → 评估前端/测试/文档影响面 → 提供兼容层或同步更新所有调用方
- **安全相关代码**（`rbac.py` / `permission.py` / `sandbox.py` / `audit.py`）：改动必须新增对应测试用例
- **核心 Agent 流程**（`comprehension → planner → executor → feedback`）：改动必须跑通 `chat-nonstream` E2E 场景
- **SSE / WebSocket 聊天路径**：改动必须同时测试两条路径
- **Plugin 生命周期**：改动必须验证 `REGISTERED → LOADED → ENABLED ↔ DISABLED → UNLOADED` 状态机

---

## 2. Long-term Memory Protocol（长期记忆协议）

> 记忆机制是长期自主迭代的**强制流程**，不是可选项。本节与 [CLAUDE.md §2](CLAUDE.md#2-long-term-memory-protocol长期记忆协议) 保持一致。

### 2.1 迭代前必读（每次新会话 / 新任务开始时）

按顺序读取以下记忆文件，提取与本任务相关的硬约束、坑点、用户偏好：

1. `c:\Users\23941\.trae-cn\memory\user_profile.md` — 用户偏好与技术栈
2. `c:\Users\23941\.trae-cn\memory\projects\-d----Open-AwA\project_memory.md` — 项目级硬约束
3. `c:\Users\23941\.trae-cn\memory\projects\-d----Open-AwA\<当日日期>\topics.md` — 近期任务上下文
4. 必要时用 `Grep` 在 `projects\-d----Open-AwA\` 下搜索关键词，追溯历史 session_memory

### 2.2 迭代后必写（每次完成一个迭代单元后）

| 触发条件 | 写入位置 |
|---------|---------|
| 发现新的硬约束、不可绕过的规则 | `project_memory.md` 的 Hard Constraints |
| 发现新的坑点 / 陷阱 | `project_memory.md` + CLAUDE.md Known Pitfalls |
| 完成一个有意义的任务（修复 / 重构 / 新功能） | 当日 `topics.md` 追加 `[session_id: xxx \| topic_summary_time: YYYY-MM-DD HH:MM:SS]` |
| 用户偏好或工作方式发生变化 | `user_profile.md` |
| 新增 / 修改了 API 接口 | CLAUDE.md Architecture Overview + 本文件 |

### 2.3 重复错误沉淀（强制）

若同一个错误在 3 次迭代中出现 ≥2 次，必须立即：

1. 在 `project_memory.md` 的 Hard Constraints 中新增条目
2. 在 CLAUDE.md Known Pitfalls 中新增条目（含定位方法与修复方向）
3. 在下次迭代前的读取阶段主动 `Grep` 检查相关关键词
4. 在 commit message 中标注 `[Lesson]` 前缀

### 2.4 记忆冲突处理

当 `project_memory.md` 与 CLAUDE.md / 本文件内容冲突时：

- **以 CLAUDE.md / 本文件为准**（代码契约优先于历史记忆）
- 在 `project_memory.md` 中标注 `OUTDATED:` 前缀
- 在下次 commit 中同步更新 CLAUDE.md / 本文件

---

## 3. Task-Driven Iteration Loop（任务驱动迭代闭环）

> 本节与 [CLAUDE.md §3](CLAUDE.md#3-task-driven-iteration-loop任务驱动迭代闭环) 保持一致。

### 3.1 单任务 6 步闭环

每个任务必须按以下 6 步顺序执行，**不可跳过任何一步**：

```
[1] 读记忆     → 读取 user_profile / project_memory / topics.md
[2] 规划       → TodoWrite 拆解子任务，标注优先级
[3] 实现       → 编辑代码，遵循 Code Conventions
[4] 测试验证   → 后端 pytest + 前端 npm run test
[5] 服务+E2E   → 启动后端 → /api/system/ping → run-all E2E → 前端 npm run build
[6] 沉淀记忆   → 更新 project_memory.md / topics.md / CLAUDE.md pitfalls
```

任一步骤失败 → 进入 Self-Healing Bug Fix Loop（详见 CLAUDE.md §5.4）。

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

## 4. Build and Test

### 4.1 Backend (Python 3.11+, FastAPI)

```bash
cd backend
pip install -r requirements.txt          # 生产依赖
pip install -r requirements-dev.txt      # 开发依赖（含 pytest）
python main.py                           # 启动服务 (uvicorn, 端口 8000)
pytest                                   # 运行测试
pytest -v --cov                          # 详细输出 + 覆盖率
```

### 4.2 Frontend (Node.js, React 18 + Vite)

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

> 完整的 6 步验证流程（含服务启动、E2E 场景、API 集成测试、前端构建）见 [CLAUDE.md §5](CLAUDE.md#5-automated-verification--self-healing-workflow)。

---

## 5. Architecture

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

### 5.1 ACP Vibe Coding 集成

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

### 5.2 Android 原生应用（Open-AwA-Android）

Android 端采用**原生 Kotlin + Jetpack Compose** 重写，废弃早期 Capacitor + Chaquopy 的 `mobile/` 目录方案。后端走**内嵌 Chaquopy + 远程混合**：本地数据（会话/消息/用户偏好）走内嵌 Python FastAPI，LLM 调用/ACP/插件等重活走远程 Open-AwA 后端。

**项目位置与工具**

- **原生项目根目录**：`D:\代码\Open-AwA\Android\Open-AwA-Android`（从 F 盘迁移到工作目录，因工具沙箱限制）
  - applicationId: `com.xtys126.open_awa`
  - namespace: `com.xtys126.open_awa`
  - AGP 9.2.1 + Gradle 9.4.1，compileSdk 36，minSdk 24，targetSdk 36
  - 阿里云 maven 镜像已配置（`settings.gradle.kts`）
- **android-cli 工具**：`D:\代码\Open-AwA\Android-Cli\android.exe`
  - SDK 位置：`C:\Users\23941\AppData\Local\Android\Sdk`
  - 用途：项目创建、模拟器管理、APK 部署、UI 布局检查、文档查询
  - 调用示例：`& "D:\代码\Open-AwA\Android-Cli\android.exe" emulator list` / `run` / `layout` / `screenshot`
- **测试模拟器**：`127.0.0.1:16448`（MuMu 模拟器，Android 12 x86_64）
  - 备用：`emulator-5554`（Pixel_7_Pro AVD，android-cli 管理）
  - adb 路径：`D:\Program Files\Netease\MuMu\nx_main\adb.exe`（MuMu 自带，主机 adb.exe 在 PATH 不可用）
  - 连接：`& "D:\Program Files\Netease\MuMu\nx_main\adb.exe" connect 127.0.0.1:16448`

**技术栈**

- **UI**：Jetpack Compose + Material 3 + Compose BOM
- **导航**：Jetpack Navigation 3（scene-based）
- **异步**：Kotlin Coroutines + Flow
- **网络**：Ktor Client（多平台，纯 Kotlin）
- **依赖注入**：手动构造（Application 单例），不引入 Hilt 简化构建
- **本地存储**：DataStore Preferences（替代 SharedPreferences）
- **内嵌后端**：Chaquopy 17.0.0 + Python 3.12（pure-Python wheel 白名单）
- **主题**：Material 3 + 复用 frontend `tokens.css` 设计令牌（颜色/间距/圆角/阴影）

**目录结构（F:\AndroidStudioProjects\Open-AwA-Android）**

```
app/
  build.gradle.kts              # Compose/Chaquopy/Ktor 依赖配置
  src/
    main/
      AndroidManifest.xml       # INTERNET 权限 + Application 注册
      kotlin/com/xtys126/open_awa/
        OpenAwAApplication.kt   # Application 入口，启动 Chaquopy 后端
        MainActivity.kt         # 单 Activity + Compose 入口
        core/
          backend/
            BackendManager.kt   # 内嵌/远程后端选择与端口管理
            EmbeddedBackend.kt  # Chaquopy 启动器
            ApiClient.kt        # Ktor HTTP 客户端
          theme/
            Color.kt            # 设计令牌（对应 tokens.css）
            Theme.kt            # Material3 主题（亮/暗色）
            Type.kt             # 字体
          nav/
            AppNavGraph.kt      # Navigation3 路由表
            AppShell.kt         # 抽屉式导航外壳
        data/
          AuthRepository.kt     # 登录/CSRF 令牌管理
          ChatRepository.kt     # 会话/消息
          PreferencesRepository.kt  # 用户偏好（DataStore）
        features/
          auth/LoginScreen.kt
          chat/ChatScreen.kt
          settings/SettingsScreen.kt
          dashboard/DashboardScreen.kt
          skills/SkillsScreen.kt
          plugins/PluginsScreen.kt
          memory/MemoryScreen.kt
          billing/BillingScreen.kt
          experience/ExperienceScreen.kt
          coding/CodingScreen.kt
          vibecoding/VibeCodingScreen.kt
          workspace/WorkspaceScreen.kt
          roles/RolesScreen.kt
          tts/TtsScreen.kt
          im/ImChannelsScreen.kt
          workflow/WorkflowScreen.kt
          subagents/SubAgentScreen.kt
          discussions/DiscussionsScreen.kt
          inbox/InboxScreen.kt
      python/
        chaquopy_bootstrap.py   # Chaquopy 启动入口
        backend_mobile/         # 复用 mobile/android/app/src/main/python/backend_mobile 代码
          config.py / db.py / security.py / main.py
          routes/
            __init__.py / system.py / auth.py / chat.py / user.py / security.py
```

**关键设计决策**

1. **单 Activity + Compose**：`MainActivity` 只承载 `OpenAwAApp` Composable，所有页面用 Navigation3 scene 管理
2. **内嵌后端启动流程**：`Application.onCreate()` → 启动 Chaquopy 子线程 → 端口写入 DataStore → 前端轮询 `127.0.0.1:port/api/system/ping` 就绪后进入登录页
3. **JS Interface 替代**：原生 Kotlin 不需要 `window.OpenAwABackend` JS 桥，直接通过 `BackendManager.getPort()` 同步获取
4. **设计令牌映射**：`tokens.css` 的 `--color-*` / `--space-*` / `--radius-*` 在 `core/theme/Color.kt` 中以 `val ColorPrimary = Color(0xFF3B82F6)` 形式等价映射
5. **离线降级**：内嵌后端离线时（启动失败）自动降级到远程后端，由 `BackendManager.resolveBaseUrl()` 决策
6. **不引入 Hilt**：依赖注入用 `Application` 单例 + `remember { ... }` 传递，减少构建配置复杂度

**构建与运行**

```powershell
# 构建 APK
cd D:\代码\Open-AwA\Android\Open-AwA-Android
.\gradlew.bat assembleDebug

# 安装到 MuMu 模拟器
& "D:\Program Files\Netease\MuMu\nx_main\adb.exe" -s 127.0.0.1:16448 install -r app\build\outputs\apk\debug\app-debug.apk

# 启动 App
& "D:\Program Files\Netease\MuMu\nx_main\adb.exe" -s 127.0.0.1:16448 shell am start -n com.xtys126.open_awa/.MainActivity

# 查看日志
& "D:\Program Files\Netease\MuMu\nx_main\adb.exe" -s 127.0.0.1:16448 logcat *:W | Select-String "OpenAwA|AndroidRuntime|com.xtys126"

# 用 android-cli 管理模拟器与 UI 检查
& "D:\代码\Open-AwA\Android-Cli\android.exe" emulator list
& "D:\代码\Open-AwA\Android-Cli\android.exe" layout --device 127.0.0.1:16448
& "D:\代码\Open-AwA\Android-Cli\android.exe" screen capture --device 127.0.0.1:16448
```

**已知构建约束（2026-07-08 验证）**

1. **AGP 9 内置 Kotlin**：app/build.gradle.kts 不需要 `alias(libs.plugins.kotlin.android)`，否则报 `Cannot add extension with name 'kotlin'`；只用 `kotlin-compose` + `kotlin-serialization`
2. **kotlinOptions 已废弃**：AGP 9 不再支持 `kotlinOptions { jvmTarget = "11" }`，改用 `kotlin { compilerOptions { jvmTarget.set(JvmTarget.JVM_11) } }`
3. **项目路径含中文**：需在 `gradle.properties` 添加 `android.overridePathCheck=true` 绕过 AGP 路径检查
4. **XML 注释禁用 `--`**：colors.xml 等 XML 资源文件的注释中不允许出现 `--` 字符串（XML 规范），`--color-primary` 要写成 `color-primary`
5. **Chaquopy 暂未集成**：当前阶段先验证 Compose UI 骨架，Chaquopy 内嵌 Python 后端待后续集成（Gradle 9 兼容性待验证）
6. **Material 图标**：`Icons.Outlined.Brain`/`Icons.Outlined.Devops` 不存在，用 `Psychology`/`Engineering` 替代；`Login`/`Chat`/`CallSplit` 有 deprecation 警告，建议用 `Icons.AutoMirrored.Outlined.*`

**已废弃方案（mobile/ 目录）**

> `mobile/` 目录的 Capacitor + Chaquopy 方案于 2026-07-08 23:30 起废弃，不再维护。所有移动端工作迁移到 `D:\代码\Open-AwA\Android\Open-AwA-Android`。`mobile/android/app/src/main/python/backend_mobile/` 的 Python 后端代码作为参考迁移到新项目的 `app/src/main/python/`，迁移完成后删除 `mobile/` 目录。

---

## 6. Code Style

### 6.1 Absolute Rules

1. **All code comments MUST be in Chinese** -- 文件头注释、函数注释、关键逻辑行内注释均用中文
2. **Emoji is strictly prohibited everywhere** -- 源码、注释、文档、commit message、配置、日志中一律不得使用 emoji
   - 用 `[DONE]` 代替完成标记，用 `[Fix]` 代替 bug 标记，用 `[NEW]` 代替新功能标记

### 6.2 Backend Conventions

- Classes: `PascalCase`，Functions/variables: `snake_case`
- Routes are `async def`，DB models extend `Base`，schemas extend `BaseModel`
- Pydantic schemas use `Create`/`Response` suffix variants（如 `SkillCreate`, `SkillResponse`）
- Config class sets `from_attributes = True` for ORM-to-schema conversion
- Dependencies via `Depends(get_db)` and `Depends(get_current_user)`
- Logging via Loguru with `request_id` context from middleware

### 6.3 Frontend Conventions

- Components: `PascalCase` with `Page` suffix for route pages（如 `ChatPage`, `SettingsPage`）
- Stores: `use` prefix（如 `useAuthStore`, `useChatStore`），使用 Zustand
- API modules: feature-specific files（如 `modelsApi.ts`, `billingApi.ts`）
- CSS Modules: `[FeatureName].module.css`
- Path alias: `@/` maps to `src/`
- Test files in `__tests__/` mirror the src structure

---

## 7. Known Pitfalls

> 本节是长期迭代沉淀的"已知陷阱库"。每次遇到新坑点必须追加到此；每次开始任务前必须扫描相关条目。
> 完整版本（含详细定位方法）见 [CLAUDE.md §19](CLAUDE.md#19-known-pitfalls)。

### 7.1 架构与并发

- **OUTDATED: Blocking ORM in async**: `ExperienceManager` 中 `async def` 调用同步 SQLAlchemy 查询，可能阻塞事件循环（已修复：实际为同步实现，AGENTS.md 描述失真，2026-07-04 审计确认）
- **SQLite FK not enforced by default**: 外键约束需要在连接参数中显式启用
- **Vector DB path is relative**: `VECTOR_DB_PATH = "./data/vector_db"`，工作目录不同会导致路径问题
- **Billing tables init required**: `PricingManager.ensure_configuration_schema()` 必须在 lifespan startup 中执行
- **Plugin Manager is a singleton**: 通过 `plugins.plugin_instance.get()` 获取，不要直接 `PluginManager()` 创建新实例
- **Conversation history auto-injected**: Agent 自动从 ShortTermMemory 加载对话历史，无需手动传递
- **resolve_max_tool_call_rounds**: 定义在 `executor.py`，`agent.py` 通过 import 引用同一函数，不可重复定义
- **Backend root directory file scatter**: backend 根目录散落了 14+ 个独立脚本（`replace_file.py`、`elevate_script.ps1`、`grant_perm.ps1` 等），这些是一次性迁移辅助脚本，不属于应用代码。后续路线图将统一迁移到 `scripts/` 目录。新增脚本不应放在根目录

### 7.2 安全与认证

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
- **ACP 子进程环境变量**: 不能继承所有环境变量，保护 SECRET_KEY 等敏感键
- **SSRF 防护**: `BASE_URL` 校验拒绝内网/本地/链路本地 IP 地址，修改模型服务 URL 验证逻辑时需保持此检查

### 7.3 业务逻辑陷阱

- **模型参数 or 陷阱**: `getattr(config, "retry_count", 3) or 3` 会将 `0` 误判为未设置，必须使用 `is not None` 检查
- **base_url 解析优先级**: 使用 `getattr(config, 'base_url', None)` 修复运算符优先级问题
- **新 provider 创建约束**: `provider` 字段必须非空，`config_id` 仅更新时需要
- **RBAC 通配符**: `check_permission` 支持 `skill:*` 匹配 `skill:read`，`*` 仅在同段数下生效
- **登录限流**: 通过 `RateLimitStore` 抽象层管理，`DatabaseRateLimitStore` 使用 `time.time()`（跨 worker 一致），`MemoryRateLimitStore` 使用 `time.monotonic()`（单进程不受时钟跳变影响）
- **Tool calls 结果截断**: 过长的工具调用结果会被截断后再传给 LLM，修改截断阈值时注意上下文窗口限制

### 7.4 ACP 与跨平台

- **ACP SDK 是可选依赖**: `acp` Python SDK 缺失时 `ACPService` 优雅降级，状态管理方法（`get_session`/`close_chat_session`/`cancel_turn`）仍可用，但 `run_turn`/`resume_permission` 抛 `ACPConfigurationError`
- **pywinpty 仅 Windows 需要**: POSIX 系统使用标准库 `pty`，Windows 使用 `pywinpty` 提供 PTY 能力
- **ACP 会话隔离**: 按 `chat_id = f"{user_id}:{session_id}"` 隔离，每个 `(chat_id, agent)` 组合对应一个 `_Conversation` 实例
- **ACP Permission 挂起-恢复**: 使用 `asyncio.Future` + `SuspendedPermission` 载体实现，用户审批后通过 `resolve_permission` 恢复执行
- **ACP 硬阻断安全策略**: `rm -rf /`、`sudo rm -rf`、`mkfs`、`dd if=` 命令子串直接拒绝执行，不进入用户审批流程
- **ACP 进程树清理**: 使用 `psutil.Process.children(recursive=True)` 递归 kill 子进程，psutil 不可用时回退到 POSIX `os.kill` 或 Windows `taskkill /T`

### 7.5 其他

- **SECRET_KEY auto-generated**: 不设置环境变量时自动生成，生产环境必须显式配置
- **Chat supports both SSE and WebSocket**: 修改聊天功能时需同时测试两条路径
- **Plugin hot update state is ephemeral**: Snapshots and active/standby slots are in-memory only, lost on restart
- **Windows ACL restrictions**: Some directories have restrictive permissions; use elevated PowerShell to replace existing files when tools fail with EPERM

---

## 8. Git Commit Rules

### 8.1 Pre-commit Checklist（强制执行，不可跳过）

Before `git add` and `git commit`, complete in order:

1. **Style check** -- 命名规范、注释完整（中文）、无 Emoji
2. **Run tests** -- 全部测试通过，新功能有对应测试，覆盖率不降低
3. **Dependency check** -- 新增依赖版本兼容，`requirements.txt` / `package.json` 已同步更新
4. **Document update** -- 功能变更更新 README.md，接口变更更新 API 文档
5. **Memory sediment** -- 完成记忆沉淀（`project_memory.md` / `topics.md`），见 §2.2
6. **git commit** -- 在完成一个模块的迭代并检查后提交到 main 分支
7. **git push（禁止自主）** -- push 必须由用户确认后执行，AI 不可自主 push

### 8.2 阶段化重构工作流

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

### 8.4 Commit Message Format

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
| `[Lesson]` | 沉淀重复错误修复（与 §2.3 配合使用） |

```bash
# Correct
git commit -m "[New] User login interface add captcha verification"
git commit -m "[Fix] Fix duplicate data in paginated order list query"
git commit -m "[Lesson] 修复 model_service or 陷阱导致的 retry_count=0 误判"

# Wrong (prohibited)
git commit -m "update"          # too vague
git commit -m "fix bug"         # not specific
```

### 8.5 Git Workflow

**所有提交直接推到 main 分支，不使用 debug 分支作为中间步骤。**
完成修改后直接 `git add` + `git commit` 到 main：
```bash
git add <具体文件>
git commit -m "[Type] 变更描述"
```
不使用 `debug` 分支，不创建中间分支。如果需要回滚，使用 `git revert`。

**禁止自主 `git push`**——push 必须由用户确认后执行。AI 可自主 commit，但不可自主 push。

---

## 9. Iteration Anti-patterns（迭代反模式）

> 本节列出 AI Agent 在长期自主迭代中**必须避免**的反模式。违反任一条都会破坏迭代闭环或污染项目记忆。

### 9.1 流程类反模式

| 反模式 | 后果 | 正确做法 |
|--------|------|---------|
| **跳过读记忆直接开工** | 重复踩已记录的坑、违反硬约束 | 每次新任务前必读 user_profile / project_memory / topics.md |
| **绕过验证直接 commit** | 引入回归、破坏 main 分支稳定性 | 必须完成 6 步验证闭环 |
| **自愈超过 3 次仍强行 commit** | 把未解决问题遗留到下次迭代 | 3 次失败立即停止，向用户报告 |
| **当前任务未闭环就开新任务** | 任务堆积、上下文混乱 | 当前任务验证通过 + 沉淀完成后才开新任务 |
| **自主 git push** | 把未审核代码推到远程 | push 必须由用户确认 |

### 9.2 代码类反模式

| 反模式 | 后果 | 正确做法 |
|--------|------|---------|
| **一次性改太多文件** | 难以审查、难以回滚 | 单任务单模块，最小化改动范围 |
| **静默吞异常**（`try/except/pass`） | 隐藏真实错误、难以诊断 | 至少记录日志，关键路径必须传播 |
| **使用 `any` 类型** | 类型安全失效 | TypeScript 用 `unknown`，Python 用具体类型 |
| **添加英文注释** | 违反项目硬约束 | 所有注释必须中文 |
| **使用 emoji** | 违反项目硬约束 | 用 `[DONE]` / `[Fix]` / `[NEW]` 代替 |
| **重复造轮子** | 代码膨胀、维护成本上升 | 先 `Grep` / `SearchCodebase` 查找现有实现 |
| **过度工程化** | 增加不必要的复杂度 | 只做被要求的事，不为假想需求设计 |

### 9.3 记忆类反模式

| 反模式 | 后果 | 正确做法 |
|--------|------|---------|
| **不写 topics.md** | 下次迭代丢失上下文 | 每个有意义任务完成后追加 topic_summary |
| **重复错误不沉淀** | 同一坑踩多次 | 同一错误 3 次迭代出现 ≥2 次必须写入 Hard Constraints |
| **写入模糊记忆** | 下次读取无法执行 | 记忆必须包含：现象、定位方法、修复方向、文件路径 |
| **修改代码不更新 pitfalls** | 下次迭代者重新踩坑 | 修复新坑后立即追加到 CLAUDE.md §19 Known Pitfalls |
| **记忆与代码契约冲突时不更新** | 记忆失真 | 以 CLAUDE.md / 本文件为准，记忆标 `OUTDATED:` |

### 9.4 协作类反模式

| 反模式 | 后果 | 正确做法 |
|--------|------|---------|
| **失败后不报告继续尝试** | 浪费 token、可能引入更大问题 | 3 次自愈失败立即停止并报告 |
| **报告只说"失败了"不说根因** | 用户无法决策 | 报告必须含失败步骤、根因（文件:行号）、已尝试方案、错误输出、建议下一步 |
| **擅自重构无关代码** | 改动范围失控、回归风险 | 最小修复原则，不顺手"优化" |
| **不更新文档** | 接口变更后调用方失效 | API 变更同步更新 CLAUDE.md / 本文件 / 架构文档 |

---

## 10. Key Documentation

- [CLAUDE.md](CLAUDE.md) — Claude Code 操作流程契约（构建命令、6 步验证闭环、自愈循环、架构速查、Known Pitfalls 完整版）
- [README.md](README.md) — Project overview, capabilities, quick start
- [CODE_WIKI.md](CODE_WIKI.md) — Comprehensive code wiki (1500+ lines): six-layer architecture, full module deep-dives
- [PROJECT_DOCUMENTATION.md](PROJECT_DOCUMENTATION.md) — Detailed technical documentation
- [docs/架构/后端架构说明.md](docs/架构/后端架构说明.md) — Backend architecture details
- [docs/架构/前端架构说明.md](docs/架构/前端架构说明.md) — Frontend architecture details
- [docs/指南/部署与运行说明.md](docs/指南/部署与运行说明.md) — Deployment guide
- [docs/指南/测试说明.md](docs/指南/测试说明.md) — Testing strategy
- [docs/插件开发手册/](docs/插件开发手册/) — Plugin development guide
- [docs/audit/安全性能综合审查报告-2026-07-04.md](docs/audit/安全性能综合审查报告-2026-07-04.md) — 最近一次安全性能审计报告

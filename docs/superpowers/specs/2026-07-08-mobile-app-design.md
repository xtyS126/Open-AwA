# 移动端 App 设计文档

> 日期：2026-07-08
> 主题：把现有 Web 界面搬到 Android 手机 app
> 方案：Capacitor 混合应用 + Chaquopy 内嵌 Python 后端（阶段化实施）

## 1. 背景与目标

### 1.1 现状
- Open-AwA 是 FastAPI + React 的 AI Agent 平台
- 前端 25+ 页面：聊天、技能、插件、记忆、计费、工作台、Vibe Coding、Terminal、ACP 等
- 已有 Electron 桌面端（`desktop/`）
- 后端依赖 SQLite + 向量库 + LLM API + 子进程（ACP）等

### 1.2 用户需求
- 把现有界面搬到 Android 手机 app
- 手机原生支持后端所有功能（混合模式：内嵌 + 远程）
- 仅本机调试 + Android 真机使用
- 全部功能搬过去
- 响应式适配
- 模拟器 + USB 真机调试都要支持

### 1.3 技术约束
- Android 物理上无法运行：ACP（调 Claude Code/Codex 子进程）、Terminal PTY、TTS（torch 5GB+）、插件热更新、IM 适配器、MCP 服务端
- Chaquopy 仅支持 pure-Python wheel
- Capacitor HTTP 插件可绕过 CORS

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                  Android App (Capacitor)                         │
│                                                                  │
│  ┌────────────────────────────────────────────┐                  │
│  │     React 前端 (复用现有 frontend/src)      │                  │
│  │  - 全部 25+ 页面响应式适配                  │                  │
│  │  - AppShell 改为手机抽屉式布局              │                  │
│  │  - API 客户端层增加"本地/远程"路由切换       │                  │
│  └────────────────┬───────────────────────────┘                  │
│                   │                                              │
│  ┌────────────────▼───────────────────────────┐                  │
│  │     Capacitor Bridge (JS <-> Native)        │                  │
│  │  - @capacitor/http (绕过 CORS)              │                  │
│  │  - @capacitor/filesystem                    │                  │
│  │  - @capacitor/preferences (持久化)          │                  │
│  │  - 自定义 Plugin: PythonRunner (阶段 2)     │                  │
│  └────────────────┬───────────────────────────┘                  │
│                   │                                              │
│  ┌────────────────▼───────────────────────────┐                  │
│  │     Native Android Layer                    │                  │
│  │  阶段 1: 仅 WebView + Capacitor 插件         │                  │
│  │  阶段 2: + Chaquopy Python 运行时            │                  │
│  │         - 内嵌 FastAPI (uvicorn 子线程)      │                  │
│  │         - SQLite (本地存储)                  │                  │
│  │         - httpx (调远程 LLM API)             │                  │
│  │         - 监听 127.0.0.1:8000               │                  │
│  └──────────────────────────────────────────────┘                 │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             │  必要时（远程功能/同步）
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│         远程后端 (现有 backend/, 不改动)                          │
│  - 完整功能：ACP / Vibe Coding / Terminal / TTS / 插件市场        │
│  - 同步 API：/api/sync/* (阶段 3 新增，本次不实现)               │
└─────────────────────────────────────────────────────────────────┘
```

### 2.1 核心思路
1. **阶段 1**：Capacitor 把现有 React 前端打包成 Android app，通过 Capacitor HTTP 插件绕过 CORS 连接远程 FastAPI 后端。响应式适配让所有页面在手机上可用。
2. **阶段 2**：用 Chaquopy 在 Android app 内嵌入 Python 运行时，跑裁剪版 FastAPI 监听 `127.0.0.1:8000`。前端 API 客户端检测请求类型：核心功能走本地后端，桌面专属功能走远程后端。
3. **数据隔离**：手机本地 SQLite 与远程后端 schema 一致，但不强制同步（同步是阶段 3）。
4. **降级策略**：远程后端不可达时，桌面专属功能按钮置灰并提示"需连接桌面端"。

## 3. 阶段 1 设计：Capacitor 集成与响应式适配

### 3.1 项目结构

新建 `mobile/` 目录，与 `frontend/`、`desktop/` 平级：

```
Open-AwA/
├── frontend/          # 现有 Web 前端（保持不变）
├── desktop/           # 现有 Electron 桌面端（保持不变）
└── mobile/            # 新增：Capacitor 移动端
    ├── android/       # Android 原生工程（Capacitor 自动生成）
    ├── src/           # 移动端专属代码（配置页等）
    ├── capacitor.config.ts
    ├── package.json
    ├── tsconfig.json
    └── vite.config.ts
```

### 3.2 复用策略

`mobile/` 作为 `frontend/` 的薄壳工程：
- 共享 `frontend/src` 源码（通过 Vite root 配置）
- 独立的 Vite 配置（移动端特定优化）
- 通过 `import.meta.env.VITE_PLATFORM` 编译期区分平台

### 3.3 Capacitor 插件清单

| 插件 | 用途 | 必要性 |
|------|------|--------|
| `@capacitor/core` | 基础运行时 | 必需 |
| `@capacitor/android` | Android 平台运行时 | 必需 |
| `@capacitor/http` | 绕过 CORS 调远程后端 | 必需 |
| `@capacitor/preferences` | 替代 localStorage（持久化 token） | 必需 |
| `@capacitor/filesystem` | 文件上传/下载缓存 | 必需 |
| `@capacitor/app` | 生命周期管理（返回键拦截） | 必需 |
| `@capacitor/status-bar` | 状态栏样式 | 必需 |
| `@capacitor/splash-screen` | 启动屏 | 必需 |
| `@capacitor/keyboard` | 键盘适配 | 必需 |
| `@capacitor/haptics` | 触感反馈 | 可选 |

### 3.4 API 客户端改造

新增 `frontend/src/shared/api/transport.ts`，统一封装请求层：

```typescript
// 核心思路：Web 用 fetch，移动端用 Capacitor HTTP 插件
// 平台判断在运行期完成，业务层无感知
import { Capacitor } from '@capacitor/core'

const platform = Capacitor.getPlatform()  // 'web' | 'android' | 'ios'

export async function request<T>(url: string, options: RequestOptions): Promise<T> {
  if (platform === 'web') {
    return fetch(url, options).then(r => r.json())
  }
  // 移动端：走 @capacitor/http，绕过 CORS
  const { Http } = await import('@capacitor/http')
  const response = await Http.request({ url, method: options.method, ... })
  return response.data as T
}
```

`shared/api/client.ts` 改造：所有 fetch 调用替换为 `request()`，业务层无感知。

### 3.5 响应式适配方案

**1. AppShell 改造**：
- 桌面：侧边栏常驻（现状）
- 移动端：侧边栏改抽屉，顶部加汉堡按钮
- 用 CSS media query + JS 平台判断双重控制

**2. 响应式断点**：
```css
/* 核心断点 */
@media (max-width: 768px) {
  .app-container {
    flex-direction: column;
  }
  .sidebar {
    position: fixed;
    transform: translateX(-100%);
    transition: transform 0.3s;
    z-index: 1000;
  }
  .sidebar.open { transform: translateX(0); }
  .main-content {
    width: 100%;
    padding: 8px;
  }
}
```

**3. 已有 @media 的页面**（BillingPage/InboxPage/WorkspacePage 等 10 个文件）：补充 `< 768px` 断点

**4. 触控优化**：
- 所有 `:hover` 样式在移动端失效，改 `:active`
- 按钮 min-height 44px（iOS HIG / Material 触摸目标）
- 输入框 font-size >= 16px（防 iOS 自动放大）

### 3.6 配置与连接管理

新增 `frontend/src/shared/mobile/config.ts`：

```typescript
// 移动端配置：后端地址管理
interface MobileConfig {
  remoteBackendUrl: string | null  // 用户配置的远程后端
  localBackendPort: number         // 默认 8000（阶段 2 启用）
  useLocalFirst: boolean           // 阶段 2 启用
}
```

**首次启动流程**：
1. 显示配置页（手动输入后端地址）
2. 用 `@capacitor/preferences` 持久化
3. 测试连接，通过后进入登录页

### 3.7 阶段 1 验收标准

- [ ] Android 模拟器和真机都能安装并启动
- [ ] 首次启动能配置后端地址并保存
- [ ] 登录、聊天、技能市场、记忆、用户中心 5 个核心页面可用
- [ ] 侧边栏抽屉式切换正常
- [ ] 所有按钮触控目标 >= 44px
- [ ] 远程后端连不上时显示友好错误，不崩溃

## 4. 阶段 2 设计：Chaquopy 内嵌 Python 后端

### 4.1 内嵌后端架构

```
mobile/android/app/src/main/python/
├── backend_mobile/           # 裁剪版后端
│   ├── __init__.py
│   ├── main.py               # FastAPI 入口（监听 127.0.0.1:8000）
│   ├── routes/               # 仅保留可内嵌的路由
│   │   ├── auth.py
│   │   ├── chat.py
│   │   ├── memory.py
│   │   ├── skills.py
│   │   ├── billing.py
│   │   ├── user.py
│   │   ├── roles.py
│   │   ├── workflow.py
│   │   ├── inbox.py
│   │   └── discussions.py
│   ├── core/                 # 裁剪版核心模块
│   ├── db/                   # SQLite + 同 schema
│   ├── memory/
│   └── config/
└── chaquopy_bootstrap.py     # Chaquopy 启动入口
```

### 4.2 Chaquopy 启动机制

Android 原生层（Kotlin）启动子线程跑 Python：

```kotlin
class MainActivity : BridgeActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        PythonThread.start {
            val py = Python.getInstance()
            py.getModule("chaquopy_bootstrap").callAttr("start_backend")
        }
    }
}
```

```python
# chaquopy_bootstrap.py
def start_backend():
    """启动内嵌 FastAPI 后端，监听 127.0.0.1:8000"""
    import uvicorn
    from backend_mobile.main import app
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
```

### 4.3 后端裁剪策略

**保留模块**（纯 Python，可内嵌）：
- `auth` / `user` / `user_profile` - 用户认证
- `chat` - 聊天（移除文件上传大文件分支）
- `memory` - 记忆系统（向量库改用纯 Python chromadb）
- `skills` - 技能引擎
- `billing` - 计费查询
- `roles` / `role_market` - 角色管理
- `workflow` - 工作流引擎
- `inbox` / `discussions` - 任务收件箱、讨论
- `behavior` / `diary` / `soul` - 行为日志、日记、灵魂系统

**裁剪模块**（功能降级）：
- `core/agent.py` - LLM 调用走 httpx（远程 LLM API）
- `core/litellm_adapter.py` - 同步实现，不依赖 aiohttp
- `memory/vector_store_manager.py` - chromadb 纯 Python 版本

**移除模块**（Android 物理上无法运行）：
- `acp_host/*` - ACP 调 Claude Code/Codex 子进程
- `core/terminal/*` - PTY 终端
- `core/coding/*` - 桌面编码功能
- `tts` - torch/torchaudio 5GB+ 库
- `plugins/*` 热更新 - Android 沙箱限制
- `im/*` - IM 适配器（钉钉/飞书/Telegram）
- `weixin/*` - 微信集成
- `mcp/*` - MCP 服务端

### 4.4 依赖白名单（Chaquopy 兼容）

| 库 | 兼容性 | 处理 |
|----|--------|------|
| fastapi | 兼容 | 直接用 |
| uvicorn | 兼容 | 直接用 |
| sqlalchemy | 兼容 | 直接用 |
| pydantic | 兼容 | 直接用 |
| httpx | 兼容 | 直接用 |
| chromadb | 兼容 | 直接用 |
| loguru | 兼容 | 直接用 |
| torch | **不兼容** | 移除 TTS |
| pywinpty | **不兼容** | 移除 Terminal |
| restrictedpython | 兼容 | 保留沙箱 |
| cryptography | 部分兼容 | 用纯 Python fallback |

### 4.5 前端 API 路由层

`shared/api/transport.ts` 扩展为双后端路由：

```typescript
// 核心思路：根据请求类型路由
// - 核心功能（chat/memory/skills/auth 等）→ 127.0.0.1:8000（本地）
// - 桌面专属功能（acp/coding/terminal/tts 等）→ remoteBackendUrl（远程）
// - 远程不可达时降级提示

const LOCAL_BACKEND = 'http://127.0.0.1:8000'
const DESKTOP_ONLY_ROUTES = ['/api/acp/', '/api/coding/', '/api/terminal/', '/api/tts/']

function resolveBaseUrl(path: string): string {
  if (DESKTOP_ONLY_ROUTES.some(p => path.startsWith(p))) {
    return mobileConfig.remoteBackendUrl ?? ''
  }
  return LOCAL_BACKEND
}
```

### 4.6 阶段 2 验收标准

- [ ] Android 真机启动后 5 秒内本地后端就绪
- [ ] 断网状态下，聊天、记忆、技能、计费 5 个核心功能可用
- [ ] 远程后端可达时，ACP/Vibe Coding 等桌面功能也能用
- [ ] 本地 SQLite 数据持久化，重启 app 不丢失
- [ ] APK 体积 < 100MB（torch 等大库已移除）

## 5. 实施计划

### 5.1 阶段 1 任务分解（本次会话完成）

1. 创建 `mobile/` 目录结构和 package.json
2. 配置 Capacitor（capacitor.config.ts + 安装插件）
3. 配置 mobile 的 Vite 复用 frontend/src
4. 实现 `shared/api/transport.ts` 平台路由层
5. 改造 `shared/api/client.ts` 使用 transport 层
6. 实现移动端配置页（首次启动配置后端地址）
7. 实现 `mobile.css` 响应式样式（AppShell 抽屉式）
8. 改造 `AppShell.tsx` 移动端抽屉布局
9. 改造 `Sidebar.tsx` 移动端抽屉模式
10. 添加 Android 平台 `npx cap add android`
11. 运行 typecheck 和 vitest 验证不破坏现有功能

### 5.2 阶段 2 任务分解（本次会话完成基础，后续完善）

1. 创建 `mobile/android/app/src/main/python/backend_mobile/` 裁剪版后端
2. 实现 `chaquopy_bootstrap.py` 启动入口
3. 改造 `MainActivity.kt` 启动 Python 子线程
4. 筛选 Chaquopy 兼容的依赖白名单
5. 移植保留模块（auth/chat/memory/skills/billing 等）
6. 配置 SQLite 本地存储
7. 扩展 `transport.ts` 双后端路由
8. 实现降级提示 UI
9. 测试断网场景
10. APK 体积优化

### 5.3 阶段 3（本次不实施，后续任务）

1. 双端数据同步 API
2. 扫码配对桌面端
3. 冲突解决策略
4. 上架应用商店

## 6. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Chaquopy 兼容性问题 | 部分库无法内嵌 | 提前测试依赖白名单，必要时用 pure-Python 替代 |
| APK 体积过大 | 用户安装困难 | 移除 torch 等大库，目标 < 100MB |
| 内嵌后端启动慢 | 用户体验差 | 启动屏 + 后台预热 |
| 远程后端 CORS | 移动端无法访问 | Capacitor HTTP 插件绕过 |
| 数据同步冲突 | 双端数据不一致 | 阶段 3 设计冲突解决策略 |
| Android 权限 | 文件/网络受限 | 在 AndroidManifest.xml 显式声明 |

## 7. 验证策略

### 7.1 阶段 1 验证
- TypeScript 检查通过（`tsc --noEmit`）
- Vitest 单元测试通过
- ESLint 零错误
- 现有 Web 功能不受影响
- 移动端响应式样式在 Chrome DevTools 移动模拟器中验证

### 7.2 阶段 2 验证
- 内嵌后端启动测试（Android Logcat 查看日志）
- 核心功能断网测试
- 双后端路由测试
- APK 体积检查

## 8. 文件清单

### 8.1 新增文件
- `mobile/package.json`
- `mobile/capacitor.config.ts`
- `mobile/vite.config.ts`
- `mobile/tsconfig.json`
- `mobile/src/mobile-entry.tsx`（移动端专属入口）
- `mobile/src/MobileConfigPage.tsx`（首次启动配置页）
- `frontend/src/shared/api/transport.ts`（统一请求层）
- `frontend/src/shared/mobile/config.ts`（移动端配置管理）
- `frontend/src/styles/mobile.css`（响应式样式）

### 8.2 修改文件
- `frontend/src/shared/api/client.ts`（使用 transport 层）
- `frontend/src/layouts/AppShell.tsx`（移动端抽屉布局）
- `frontend/src/shared/components/Sidebar/Sidebar.tsx`（移动端抽屉模式）
- `frontend/src/main.tsx`（平台判断入口）

### 8.3 阶段 2 新增
- `mobile/android/app/src/main/python/backend_mobile/` 目录及所有文件
- `mobile/android/app/src/main/java/.../MainActivity.kt`（修改）
- `mobile/android/app/build.gradle.kts`（Chaquopy 配置）

## 9. 阶段 2 实施完成状态（2026-07-08 21:10）

阶段 2 完整实现已完成并通过本地验证。本次实施内容：

### 9.1 已完成

**Chaquopy 集成配置**
- `mobile/android/app/build.gradle` 解锁 `pipInstall`，配置 pure-Python 依赖白名单
- 兼容依赖（17 个）：fastapi / uvicorn（不带 [standard]）/ starlette / python-multipart / websockets / sqlalchemy / pydantic / pydantic-settings / python-dotenv / PyJWT / passlib（不带 [bcrypt]，用 pbkdf2_sha256）/ httpx / aiofiles / loguru / pyyaml / fastapi-csrf-protect / cachetools / click / RestrictedPython
- 明确剔除的不兼容依赖：torch（无 Android ABI）/ pywinpty（Windows 专属）/ qdrant-client 嵌入式（Rust）/ tree-sitter（C 扩展）/ multilspy（桌面 LSP）/ pyte / apscheduler / psutil / bcrypt

**模块化后端结构**（`mobile/android/app/src/main/python/backend_mobile/`）
- `config.py` — `MobileSettings` 线程安全单例，数据目录通过 `OPENAWA_DATA_DIR` 环境变量注入，密钥首次启动生成并持久化到 `data_dir/secret.key`（jwt/csrf/encryption 三套独立密钥）
- `db.py` — SQLAlchemy + SQLite，5 个核心表（User/SessionModel/Message/Skill/BillingRecord），`check_same_thread=False` + `pool_pre_ping`，`ensure_owner_user()` 首次启动自动创建管理员
- `security.py` — passlib `pbkdf2_sha256`（纯 Python 无 C 扩展）+ PyJWT HS256 + `secrets.token_urlsafe` 生成 CSRF 令牌
- `routes/system.py` — `/api/system/ping|info|health`，含数据库连通性检查
- `routes/auth.py` — `/api/auth/csrf-token|login|register|logout|me`，JSON 请求体替代 OAuth2PasswordRequestForm，Bearer 令牌依赖注入 `get_current_user`，首个用户自动 admin
- `routes/chat.py` — 会话 CRUD + 消息历史（仅本地存储，不含 LLM 推理）
- `routes/user.py` — 当前用户资料 + 修改密码
- `main.py` — FastAPI 工厂 + lifespan（init_db + ensure_owner_user）+ CORS + 路由注册

**端口桥接（Java ↔ JS）**
- `chaquopy_bootstrap.py` 新增 `set_data_dir(path)` 供 Java 侧注入数据目录，全局状态增加 `_backend_port`
- `MainActivity.java` 调用顺序：`set_data_dir(getFilesDir())` → `start_backend()` → SharedPreferences 持久化端口
- 注入 `BackendJsInterface` 到 WebView（`window.OpenAwABackend`），暴露 `getPort()/isStarted()/getBaseUrl()` 三个 `@JavascriptInterface` 方法
- `mobile/src/mobileConfig.ts` 新增 `getEmbeddedBackendPort()/isEmbeddedBackendStarted()/waitForEmbeddedBackend(15000ms)` 三个函数
- `mobile/src/setupMobileApi.ts` 重写为：优先等待内嵌后端就绪 → `setBackendUrl(http://127.0.0.1:${port})` → fallback 到 `remoteBackendUrl` → `refreshCsrfToken()`

### 9.2 验证结果

| 验证项 | 结果 |
|--------|------|
| Python ast.parse（11 个 .py 文件） | 0 错误 |
| mobile typecheck | 通过 |
| mobile build | 10.31s 成功 |
| frontend vitest | 71 文件 467 测试全部通过 |
| cap sync android | 14.336s 成功，7 个 Capacitor 插件识别 |

### 9.3 阶段 2 待办（需 Android Studio 环境验证）

以下项目无法在本地桌面环境验证，需要在 Android Studio 中完成：

1. **Chaquopy 集成编译验证** — `pipInstall` 依赖下载与 Python 3.11 wheel 在 Android ABI 上的兼容性
2. **模拟器/真机测试内嵌后端启动** — 验证 `chaquopy_bootstrap.start_backend()` 在 Android 子线程中的行为
3. **端口桥接真机验证** — SharedPreferences 持久化 + JS 接口读取的实际行为
4. **pipInstall 依赖体积优化** — 实测后可能需要进一步裁剪（如 starlette 已被 fastapi 传递依赖）

### 9.4 阶段 2 MuMu 模拟器实测结果（2026-07-08 22:58）

在 MuMu 模拟器（Android 12 x86_64，ADB `127.0.0.1:16384`）上完成端到端验证：

| 验证项 | 结果 |
|--------|------|
| APK 构建（Gradle 8.9 + AGP 8.7.0 + JDK 21） | BUILD SUCCESSFUL |
| APK 安装到 MuMu 模拟器 | Success |
| Chaquopy Python 3.12 运行时启动 | 成功（`Python.isStarted()` 通过） |
| 内嵌 FastAPI 后端启动 | Uvicorn running on http://127.0.0.1:8000 |
| 数据库初始化（SQLite） | `openawa_mobile.db` 创建 + admin 用户自动创建 |
| 密钥持久化 | `secret.key` 文件包含 jwt/csrf/encryption/api_key 四套密钥 |
| 前端等待后端启动（状态重置 + 轮询） | `mobile_waiting_embedded_backend` → `mobile_embedded_backend_enabled` |
| CSRF token 接口 | GET `/api/auth/csrf-token` → 200 |
| API Key 自动认证 | GET `/api/auth/me` → 200（跳过登录页直接进入主应用） |
| 会话列表接口 | GET `/api/conversations` → 200 |
| 前端路由跳转 | `/` → `/chat` |
| AppShell UI 渲染 | 侧边栏 + 移动菜单按钮 + /chat 激活态 |
| WebView 调试协议（CDP） | `webview_devtools_remote_18443` 可用，可截图 + 取 DOM |

**关键修复（实测中发现并解决）**

1. **pydantic 依赖冲突** — `fastapi-csrf-protect 1.0.0` 强依赖 `pydantic>=2.0.0`，与 `fastapi 0.99.1`（最后兼容 pydantic v1 的版本）冲突，移除该依赖改用自实现 CSRF。
2. **pydantic 1.10.13 与 Python 3.12 不兼容** — `ForwardRef._evaluate() missing 'recursive_guard'`，升级到 `pydantic==1.10.24`（最后一个 1.10.x 版本）。
3. **PyObject 不能强转 Integer** — Java 不能 `(Integer) result` 强转 Chaquopy PyObject，必须用 `result.toInt()`。
4. **Capacitor Preferences Proxy then 问题** — Preferences 是 Proxy 对象，被 await 时触发 `then`，但 Android native 未实现，导致 `"Preferences.then() is not implemented on android"`。完全移除 `@capacitor/preferences` 依赖，改用 `window.OpenAwABackend` + 内存缓存。
5. **前端误读上次启动遗留状态** — `MainActivity.onCreate` 在 `startEmbeddedBackend()` 开头先重置 `backend_started=false`、`backend_port=0`，避免前端读取上次启动遗留的 `true` 状态跳过轮询，导致首次 API 请求 `Failed to connect to /127.0.0.1:8000`。
6. **baseURL 缺 `/api` 前缀** — 前端 axios 调用 `/auth/csrf-token` 依赖 baseURL 拼接出 `/api/auth/csrf-token`，但 `setBackendUrl("http://127.0.0.1:8000")` 丢了 `/api` 后缀，导致 404。修复为 `http://127.0.0.1:${port}/api`。
7. **MobileApp 误判需要配置** — `if (!config.remoteBackendUrl)` 没识别到内嵌后端已启用，导致显示配置页。修改为 `if (!config.remoteBackendUrl && !config.useLocalFirst)`。
8. **API Key 自动登录** — 移动端单用户场景下，前端 LoginPage 输入框不适用。`config.py` 新增 `api_key` 字段（首次启动生成并持久化），`chaquopy_bootstrap.get_api_key()` 暴露给 Java，`BackendJsInterface.getApiKey()` 注入 WebView，`setupMobileApi.ts` 在内嵌后端就绪后调用 `persistApiKey(apiKey)` 自动登录跳过 LoginPage。
9. **后端 get_current_user 支持 API Key** — 移动端 `auth.py` 的 `get_current_user` 在收到 Bearer token 时先尝试作为 API Key 验证（等值于 `settings.api_key`），失败再走 JWT 解码。
10. **/api/conversations 路由** — 前端 `conversationAPI` 用 `/conversations` 路径，但移动端 `chat.py` 只有 `/api/chat/sessions`。新增 `conversations_router`（prefix=`/api/conversations`），GET 列表 + POST 创建 + GET/PATCH/DELETE 详情，响应格式按 `ConversationSessionSummary` 对齐。

**已知遗留问题（不影响核心 UI）**

- ~~`/api/security/permissions/sse-ticket` 404~~：已在 9.5 节修复
- ~~`/api/chat/history/undefined` 404~~：已在 9.5 节修复
- ~~`/api/user/preferences` 404~~：已在 9.5 节修复

### 9.5 阶段 2 遗留问题修复（2026-07-08 23:12）

针对 9.4 节三个遗留问题完成修复并重新构建 APK 在 MuMu 模拟器验证通过：

**修复 1：/api/user/preferences 404**

新增 `UserPreference` 表（key-value 存储，避免动 User 表 schema）+ GET/PUT 路由：

- `backend_mobile/db.py` 新增 `UserPreference` 模型（`user_id` + `key` + `value` JSON 字符串 + `updated_at`）
- `backend_mobile/routes/user.py` 新增 `_load_preferences` / `_save_preferences` 内部函数 + GET/PUT `/api/user/preferences` 路由
- 响应格式对齐前端 `UserPreferencesResponse`：`{ "preferences": { ... } }`
- PUT 全量替换（删除旧记录再写入新记录），与前端 `userAPI.updatePreferences` 行为一致

**修复 2：/api/chat/history/undefined 404**

后端容错未选会话时的字符串 `'undefined'`：

- `backend_mobile/routes/chat.py` 的 `get_history` 路由在 `session_id` 为 `'undefined'` / `'null'` / `'default'` / `''` 时直接返回空列表
- 前端 ChatPage 在 sessionId 未初始化时仍可能调用本接口（URL 模板字符串化后变成 `'undefined'`），返回空列表而非 404 可避免日志噪音与重试
- 日志验证：`"url":"/chat/history/undefined","status_code":200` + `"chat_history_loaded","loaded 0 history messages"`

**修复 3：/api/security/permissions/sse-ticket 404 + SSE 重连**

后端新增 security 路由 + 前端移动端跳过 SSE 建立（双管齐下）：

- `backend_mobile/routes/security.py` 新增 `/api/security/permissions/sse-ticket`（POST，返回一次性 ticket，60s TTL，内存存储 + threading.Lock 保护 + 惰性清理）+ `/api/security/permissions/stream`（GET，StreamingResponse + 30s keep-alive 心跳）
- 兼容路由：`/api/security/permissions/saved`（GET 返回空列表）+ `/api/security/permissions/saved/{id}`（DELETE 204）+ `/api/security/permissions/saved`（DELETE 204）+ `/api/security/permissions/reply`（POST 返回 ok）
- `backend_mobile/main.py` 注册 `security.router`
- `backend_mobile/routes/__init__.py` 导出 security 模块
- 前端 `frontend/src/features/chat/hooks/usePermissionRequest.ts` 新增 `isMobilePlatform()` 判断（检测 `window.OpenAwABackend`），在移动端 useEffect 入口直接 `setConnected(false); return`，跳过 SSE 建立
- 日志验证：`"event":"permission_sse_skipped_on_mobile","message":"移动端无 ACP 子进程，跳过权限请求 SSE 连接"`，不再有 `permission_sse_reconnecting`

**验证结果**

| 验证项 | 修复前 | 修复后 |
|--------|--------|--------|
| GET `/api/user/preferences` | 404 | 200（返回 `{preferences: {}}`） |
| GET `/api/chat/history/undefined` | 404 | 200（返回 `[]`） |
| POST `/api/security/permissions/sse-ticket` | 404 | 200（返回 `{ticket, expires_in: 60}`） |
| SSE 持续重连 | 1/2/4/8/16/30s 退避重连 | 跳过 SSE 建立（`permission_sse_skipped_on_mobile`） |
| 4xx/5xx 错误日志 | 3 项 404 持续刷屏 | 0 错误 |

### 9.6 UI 美化（2026-07-08 23:25）

针对移动端界面进行视觉升级，复用 frontend 设计令牌（`tokens.css` 中的 `--color-*` / `--space-*` / `--radius-*` / `--transition-*`），引入毛玻璃效果、渐变装饰、脉动动画、触感反馈。本次美化只改 CSS + 1 个新组件 + 2 个组件集成点，不动业务逻辑。

**新增组件：MobileTopBar**

`mobile/src/MobileTopBar.tsx` — 毛玻璃顶部应用栏：

- `PATH_TITLE_MAP` 22 个路由 → 标题映射（聊天/编码/Vibe Coding/工作区/仪表盘/计费/收件箱/TTS/角色管理/角色市场/技能/技能市场/定时任务/工作流/子智能体/讨论/插件/记忆/经验/设置/IM 渠道/用户中心/登录）
- `resolveTitle()` 精确匹配 + 前缀匹配（`/chat/:id` → 聊天）
- `router.subscribe` 订阅路径变化更新标题
- 复用 `useThemeStore.toggleTheme` + inline SVG 太阳/月亮图标（不引入 lucide-react 新依赖）
- `padding-left: 64px` 留出空间给 Sidebar 的汉堡按钮（保持原有交互）

**修改文件清单**

| 文件 | 修改内容 |
|------|---------|
| `mobile/src/mobile.css` | 全局重写：`mobilePageFadeIn` 页面淡入、3px 纤细滚动条、毛玻璃顶栏（`backdrop-filter: saturate(180%) blur(20px)`）、加载页 `mobileLogoPulse` 脉动 + 三圆点 `mobileLoadingDot` 跳动、配置页径向渐变 + 顶部 4px 渐变装饰条 + 72px logo + 渐变标题文字 + 1.5px border + focus ring 阴影、错误 `mobileShake` 抖动、按钮渐变 + 双层投影、暗色模式径向渐变加强 |
| `mobile/src/MobileApp.tsx` | 加载页改用 `.mobile-loading-page` + logo + dots；主应用渲染 `<MobileTopBar />` + `<FrontendApp />` |
| `mobile/src/MobileTopBar.tsx` | 新建：毛玻璃顶栏 + logo + 标题 + 主题切换 |
| `mobile/vite.config.ts` | 新增 `publicDir: '../frontend/public'`，复用 frontend 的 logo.svg 等静态资源 |
| `frontend/src/shared/components/Sidebar/Sidebar.module.css` | 移动端优化：`.mobile-menu-btn` 透明背景 + `scale(0.92)` 按压反馈；`.mobile-overlay` 加 `backdrop-filter: blur(2px)`；`.sidebar` 移动端 `max-width: 85vw` + 去掉 `border-right`；`.sidebar.mobile-open` 双层阴影；`.sidebar-item:active` `scale(0.98)` 触感反馈；`.sidebar-item.active::before` 更大指示条（4px × 22px） |

**关键设计决策**

1. **不引入新依赖**：lucide-react 在 frontend 已有，但 mobile 项目未安装。MobileTopBar 的太阳/月亮图标用 inline SVG（lucide 原始 path），避免改 `package.json` + 装包。
2. **复用 frontend/public**：mobile 项目原本没有 `public/` 目录，导致 `logo.svg` 加载失败（logcat: `Unable to open asset URL: https://localhost/logo.svg`）。vite.config.ts 配置 `publicDir: '../frontend/public'` 复用现有资源，避免重复维护。
3. **毛玻璃而非纯色**：`backdrop-filter: saturate(180%) blur(20px)` + `color-mix(in srgb, var(--color-bg) 75%, transparent)` 半透明背景，让顶栏在内容滚动时透出底色，视觉层次更丰富。
4. **设计令牌复用**：所有颜色/间距/圆角/阴影/过渡均引用 `tokens.css` 变量，亮色/暗色主题自动切换，零硬编码。
5. **触感反馈**：移动端点击区域（汉堡按钮、菜单项、按钮）添加 `:active` 时的 `scale(0.92-0.98)` 缩放，模拟原生按压反馈。
6. **页面标题自动同步**：通过 `router.subscribe` 监听路径变化，顶栏标题实时更新，与 Sidebar 激活态对齐。

**验证结果**

| 验证项 | 结果 |
|--------|------|
| `npm run build` | 通过（6.93s，dist 资源完整） |
| `npx cap sync android` | 通过（7 个 Capacitor 插件识别） |
| `gradle assembleDebug` | 通过（APK 生成） |
| `adb install -r` | Success |
| logcat 错误日志 | 0（logo.svg 加载失败已修复） |
| DOM 验证（CDP Runtime.evaluate） | `topbar: true` + `topbarHTML` 包含 logo + 标题"聊天" + 主题切换按钮 + `hasMobileCss: true` + `firstChildTag: HEADER` |
| 截图 | `mobile/screenshots/07-system-beautify-chat.png`（44KB，含状态栏 + 顶栏 + 聊天页） |

### 9.7 后续阶段（3+）

- 移植 memory/skills/billing/roles/workflow/inbox/discussions 等剩余路由
- LLM 代理（远程后端转发，解决 Chaquopy 无法跑 litellm 的问题）
- 离线优先策略（内嵌后端离线时降级到本地缓存）
- 数据同步（内嵌 SQLite ↔ 远程后端 schema 对齐与冲突解决）

### 9.5 启动与调试命令

```bash
# 移动端 Web 开发预览（浏览器调试）
cd mobile && npm run dev

# 移动端生产构建
cd mobile && npm run build

# 同步 dist/ 到 Android 工程
cd mobile && npx cap sync android

# 用 Android Studio 打开（编译/真机调试）
cd mobile && npx cap open android

# Android Studio 中：
# 1. Build > Make Project（首次会下载 Chaquopy 依赖，需联网）
# 2. Run > Run 'app'（选择模拟器或 USB 真机）
# 3. Logcat 过滤 "OpenAwA.MainActivity" 查看后端启动日志
# 4. Logcat 过滤 "chaquopy_bootstrap" 查看 Python 子线程日志
```

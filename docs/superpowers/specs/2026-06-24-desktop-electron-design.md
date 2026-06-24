# Open-AwA 桌面端（Electron）设计文档

- **日期**: 2026-06-24
- **状态**: 已确认，待生成实现计划
- **作者**: 协作设计（用户 + 助手）
- **关联**: 基于 [frontend 架构](../../架构/前端架构说明.md) 与现有 `frontend/tests/e2e/electron-main.cjs` 基础扩展

---

## 1. 背景与目标

### 1.1 背景

Open-AwA 现有前端为 React 18 + TypeScript + Vite + Zustand 的 Web 应用，包含 24+ 功能模块（聊天、编码、计费、插件、技能、工作流、子智能体、灵魂画像等），14 个 Zustand store，支持 SSE 流式聊天与 WebSocket 实时消息。`frontend/package.json` 已包含 `electron ^35.7.5` 依赖，`frontend/tests/e2e/` 下已有最小化的 `electron-main.cjs`（仅用于 E2E 测试加载 dev server），但项目根目录下没有真正的桌面端代码。

### 1.2 目标

在项目根目录新增 `desktop/` 文件夹，基于 Electron 构建一个跨平台桌面应用，**包装复用现有 frontend 构建产物**，覆盖前端全部 24+ 功能模块，连接用户配置的远程后端，提供中级桌面原生集成。

### 1.3 非目标

- 不重写任何前端 UI 组件
- 不打包 Python 后端（用户自行部署后端，桌面端连接远程地址）
- 不实现 PWA 或 Tauri 方案
- 不新增前端功能模块（仅做必要的 baseURL 适配）

---

## 2. 整体架构

### 2.1 目录结构

```
项目根/
  frontend/          # 现有前端（小幅适配，支持动态 baseURL）
  backend/           # 现有后端（不改动）
  desktop/           # 新增：Electron 桌面端
    package.json
    tsconfig.json
    electron-builder.yml
    src/
      main/                  # 主进程
        index.ts             # 入口：app 生命周期、单实例锁
        window.ts            # 窗口创建与管理
        menu.ts              # 原生菜单
        tray.ts              # 系统托盘
        shortcuts.ts         # 全局快捷键
        updater.ts           # 自动更新
        ipc/                 # IPC 处理器
          backend.ts         # 后端地址管理
          notification.ts     # 系统通知
          window.ts           # 窗口控制
      preload/
        index.ts             # contextBridge 暴露白名单 API
      shared/
        ipc-channels.ts      # IPC 通道名常量
        types.ts             # 主进程/渲染进程共享类型
    resources/
      icons/                 # 应用图标（ico/icns/png）
      frontend/              # 前端构建产物（构建时复制）
    scripts/
      build-frontend.ts      # 构建前端并复制产物
      dev.ts                 # 开发模式启动脚本
```

### 2.2 进程模型

```
┌─────────────────────────────────────────────────────┐
│ 主进程（Node.js 环境）                              │
│  - app 生命周期、单实例锁                            │
│  - 窗口/菜单/托盘/快捷键/通知/更新                   │
│  - electron-store 加密存储后端地址                   │
│  - IPC 处理器                                        │
└──────────────┬──────────────────────────────────────┘
               │ contextBridge（白名单 API）
               ▼
┌─────────────────────────────────────────────────────┐
│ 预加载脚本（隔离环境）                              │
│  window.__OPENAWA_BACKEND__ = { url, version }      │
│  window.__OPENAWA_DESKTOP__ = { ipc, platform, ... } │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│ 渲染进程（frontend dist，sandbox + contextIsolation）│
│  - React 应用（全部 24+ 模块）                       │
│  - client.ts 读取 window.__OPENAWA_BACKEND__.url    │
│  - 通过 window.__OPENAWA_DESKTOP__ 调用原生能力      │
└─────────────────────────────────────────────────────┘
               │ HTTPS / WSS
               ▼
┌─────────────────────────────────────────────────────┐
│ 远程后端（用户自部署，FastAPI :8000）               │
└─────────────────────────────────────────────────────┘
```

### 2.3 开发与生产模式

| 模式 | 渲染进程加载源 | 后端连接 |
|------|---------------|---------|
| **开发** | `http://localhost:5173`（frontend dev server） | Vite proxy → 本地后端（开发体验不变） |
| **生产** | `loadFile('resources/frontend/dist/index.html')` | preload 注入用户配置的远程后端地址 |

主进程通过 `app.isPackaged` 判断模式。开发模式下还支持 `process.env.OPENAWA_FRONTEND_URL` 覆盖。

---

## 3. 前端集成方案（核心）

### 3.1 方案选择：preload 注入动态 baseURL

桌面端没有 Vite proxy，需让前端 baseURL 可动态指向远程后端。采用 preload 注入方案：

**优先级链**（在 `frontend/src/shared/api/client.ts` 中实现）：
```
window.__OPENAWA_BACKEND__.url  →  localStorage('openawa_backend_url')  →  '/api'（默认，web 模式）
```

### 3.2 前端改动清单（最小化）

#### 3.2.1 `frontend/src/shared/api/client.ts`

新增动态 baseURL 解析：

```typescript
// 新增：动态解析后端 baseURL
declare global {
  interface Window {
    __OPENAWA_BACKEND__?: { url: string; version: string }
  }
}

const BACKEND_URL_STORAGE_KEY = 'openawa_backend_url'

function resolveBaseURL(): string {
  // 优先级 1：preload 注入（桌面端）
  if (typeof window !== 'undefined' && window.__OPENAWA_BACKEND__?.url) {
    return window.__OPENAWA_BACKEND__.url
  }
  // 优先级 2：localStorage（用户在设置页配置的远程后端）
  const stored = typeof window !== 'undefined'
    ? window.localStorage.getItem(BACKEND_URL_STORAGE_KEY)
    : ''
  if (stored) {
    return stored
  }
  // 优先级 3：默认相对路径（web 模式走 Vite proxy）
  return '/api'
}

export const API_BASE_URL = resolveBaseURL()

export function setBackendUrl(url: string): void {
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(BACKEND_URL_STORAGE_KEY, url)
  }
  // 注意：运行时修改需刷新页面或重建 axios 实例
}
```

`api` 实例的 `baseURL` 改为引用 `API_BASE_URL`（已是模块级常量，初始化时解析）。

#### 3.2.2 SSE 流式聊天适配

`frontend/src/shared/api/api.ts` 的 `chatAPI.sendMessageStream` 使用原生 `fetch`，URL 拼接需从 `API_BASE_URL` 取值（当前已硬编码 `/api`，改为引用导出的 `API_BASE_URL`）。

#### 3.2.3 WebSocket 适配

`frontend/src/shared/hooks/useWeixinWebSocket.ts` 中 WebSocket URL 拼接需从 `API_BASE_URL` 推导 ws/wss 协议与 host（当前硬编码 `location.host`，改为基于 `API_BASE_URL` 解析）。

#### 3.2.4 设置页新增"后端连接"Tab

在 `frontend/src/features/settings/` 下新增 `BackendConnectionTab`：
- 后端 URL 输入框（默认显示当前 `API_BASE_URL`）
- "测试连接"按钮（调用 `/api/health` 验证）
- "保存并应用"按钮（调用 `setBackendUrl` + 刷新页面）
- "重置为默认"按钮（清除 localStorage，恢复 `/api`）

此 Tab 在 web 和桌面端均可用（web 端允许用户连接自部署后端）。

### 3.3 不改动的前端代码

- 全部 24+ 功能模块的 UI 组件、状态管理、路由
- 全部 14 个 Zustand store
- 全部 API 模块（`shared/api/*.ts`、`features/*/xxxApi.ts`）
- 全部共享组件、hooks、工具函数
- 构建配置 `vite.config.ts`（web 端行为不变）

---

## 4. 后端地址管理

### 4.1 存储

- **桌面端**：使用 `electron-store`（加密）存储后端 URL，主进程读取后通过 preload 注入 `window.__OPENAWA_BACKEND__.url`
- **API Key**：复用前端现有 `localStorage` 机制（`openawa_api_key`），preload 不干预
- **Web 端**：用户在设置页配置后存入 `localStorage('openawa_backend_url')`

### 4.2 首次启动引导

桌面端首次启动（检测到 `electron-store` 无后端 URL 配置）：
1. 主进程创建引导窗口（独立小窗口，非主窗口）
2. 引导窗口加载 `resources/frontend/onboarding.html`（独立静态页面，不依赖 React 应用）
3. 用户输入后端 URL，点击"测试连接"
4. 测试通过后保存到 `electron-store`，关闭引导窗口，打开主窗口

引导页设计为独立静态 HTML，避免加载完整 React 应用，启动更快。

### 4.3 运行时切换

用户在设置页"后端连接"Tab 修改 URL：
1. 调用 `window.__OPENAWA_DESKTOP__.ipc.invoke('backend:set-url', newUrl)`
2. 主进程更新 `electron-store`
3. 主进程向所有窗口发送 `backend:url-changed` 事件
4. 渲染进程收到事件后调用 `window.location.reload()`（最简单可靠，避免重建 axios 实例的复杂性）

---

## 5. 原生功能清单（中级）

### 5.1 窗口管理

- 默认尺寸 1280x800，最小 1024x600
- 记忆窗口位置与大小（`electron-store`）
- 单实例锁（`app.requestSingleInstanceLock`），二次启动聚焦已有窗口
- 深浅色标题栏同步主题（监听前端主题变化，调用 `nativeTheme.themeSource`）

### 5.2 原生菜单

```
文件
  - 新建会话（Ctrl+N）        → 通知渲染进程
  - 退出（Ctrl+Q）
编辑
  - 撤销（Ctrl+Z）
  - 重做（Ctrl+Shift+Z）
  - 复制（Ctrl+C）/ 粘贴（Ctrl+V）/ 全选（Ctrl+A）
视图
  - 放大（Ctrl+=）/ 缩小（Ctrl+-）/ 重置缩放（Ctrl+0）
  - 全屏切换（F11）
  - 刷新（Ctrl+R）/ 强制刷新（Ctrl+Shift+R）
窗口
  - 最小化 / 关闭
帮助
  - 关于
  - 检查更新
  - 打开开发者工具（仅开发模式）
```

### 5.3 系统托盘

- 托盘图标 + 右键菜单：
  - 显示主窗口
  - 新建会话
  - 退出
- 关闭按钮行为可配置（设置项）：
  - 默认：最小化到托盘（不退出）
  - 可选：直接退出
- 双击托盘图标：显示/隐藏主窗口
- 托盘菜单的"新建会话"通过 `action:new-chat` IPC 通道通知渲染进程（与全局快捷键复用同一通道）

### 5.4 全局快捷键

- `Ctrl+Shift+O`：显示并聚焦主窗口
- `Ctrl+Shift+N`：显示主窗口并新建会话

注册时机：`app.whenReady()`；注销时机：`app.on('will-quit')`。

### 5.5 系统通知

- 对接后端消息事件（收件箱新消息、定时任务完成等）
- 主进程通过 IPC 接收渲染进程的通知请求，调用 `Notification` API
- 点击通知：聚焦主窗口并跳转到对应页面（通过 IPC 传参）

### 5.6 开机自启

- 设置页提供开关
- 调用 `app.setLoginItemSettings({ openAtLogin: boolean })`
- 状态同步显示当前设置

### 5.7 自动更新

- 使用 `electron-updater`
- 更新源：GitHub Release（可配置为私有服务器）
- 检查时机：启动后延迟 30 秒自动检查；菜单"检查更新"手动触发
- 更新流程：检测到新版本 → 下载 → 提示用户重启安装
- 配置项：自动检查更新开关（默认开启）

---

## 6. IPC 通道设计

### 6.1 通道命名规范

格式：`<域>:<动作>`，如 `backend:set-url`、`window:minimize`。

### 6.2 通道清单

| 通道 | 方向 | 参数 | 返回 | 说明 |
|------|------|------|------|------|
| `backend:get-url` | renderer→main | - | `string` | 获取当前后端 URL |
| `backend:set-url` | renderer→main | `{ url: string }` | `{ success: boolean }` | 设置后端 URL |
| `backend:test-connection` | renderer→main | `{ url: string }` | `{ ok: boolean, latency?: number, error?: string }` | 测试后端连通性 |
| `backend:url-changed` | main→renderer | `{ url: string }` | - | 后端 URL 变更通知 |
| `window:minimize` | renderer→main | - | - | 最小化 |
| `window:maximize` | renderer→main | - | `{ isMaximized: boolean }` | 切换最大化 |
| `window:close` | renderer→main | - | - | 关闭（按配置最小化或退出） |
| `window:is-maximized` | renderer→main | - | `boolean` | 查询最大化状态 |
| `notification:show` | renderer→main | `{ title, body, url? }` | - | 显示系统通知 |
| `notification:clicked` | main→renderer | `{ url?: string }` | - | 通知点击事件 |
| `app:get-version` | renderer→main | - | `string` | 获取应用版本 |
| `app:get-platform` | renderer→main | - | `string` | 获取操作系统 |
| `update:check` | renderer→main | - | `{ status, info? }` | 检查更新 |
| `update:download` | renderer→main | - | - | 下载更新 |
| `update:install-and-restart` | renderer→main | - | - | 安装并重启 |
| `update:status-changed` | main→renderer | `{ status, progress? }` | - | 更新状态变更 |
| `action:new-chat` | main→renderer | - | - | 新建会话（全局快捷键/托盘菜单触发） |
| `autostart:get` | renderer→main | - | `boolean` | 获取开机自启状态 |
| `autostart:set` | renderer→main | `boolean` | `boolean` | 设置开机自启 |

### 6.3 preload 暴露的 API

```typescript
// desktop/src/preload/index.ts
contextBridge.exposeInMainWorld('__OPENAWA_BACKEND__', {
  url: backendUrl,      // 启动时从 electron-store 读取
  version: appVersion,
})

contextBridge.exposeInMainWorld('__OPENAWA_DESKTOP__', {
  platform: process.platform,
  isPackaged: app.isPackaged,
  ipc: {
    invoke: (channel: string, ...args: unknown[]) => ipcRenderer.invoke(channel, ...args),
    on: (channel: string, listener: (...args: unknown[]) => void) => {
      const handler = (_event: IpcRendererEvent, ...args: unknown[]) => listener(...args)
      ipcRenderer.on(channel, handler)
      return () => ipcRenderer.removeListener(channel, handler)
    },
  },
})
```

渲染进程通过 `window.__OPENAWA_DESKTOP__` 调用原生能力，web 端该对象为 `undefined`，前端代码做存在性判断即可区分运行环境。

---

## 7. 构建与打包

### 7.1 构建流程

```
1. cd frontend && npm run build
   → 产出 frontend/dist/

2. 复制 frontend/dist/ → desktop/resources/frontend/
   （由 desktop/scripts/build-frontend.ts 自动完成）

3. cd desktop && npm run build
   → electron-builder 打包
   → 产出 desktop/dist/Open-AwA-Setup-1.0.0.exe（Windows NSIS）
```

### 7.2 `desktop/package.json` 脚本

```json
{
  "scripts": {
    "dev": "tsx scripts/dev.ts",
    "build:frontend": "tsx scripts/build-frontend.ts",
    "build": "npm run build:frontend && electron-builder",
    "build:win": "npm run build:frontend && electron-builder --win",
    "build:mac": "npm run build:frontend && electron-builder --mac",
    "build:linux": "npm run build:frontend && electron-builder --linux",
    "typecheck": "tsc --noEmit",
    "lint": "eslint src --ext .ts"
  }
}
```

### 7.3 `electron-builder.yml` 关键配置

```yaml
appId: com.openawa.desktop
productName: Open-AwA
directories:
  output: dist
files:
  - src/main/dist/**/*
  - src/preload/dist/**/*
  - resources/**/*
extraResources:
  - from: resources/frontend
    to: frontend
win:
  target: nsis
  icon: resources/icons/icon.ico
mac:
  target: dmg
  icon: resources/icons/icon.icns
linux:
  target: AppImage
  icon: resources/icons/icon.png
nsis:
  oneClick: false
  allowToChangeInstallationDirectory: true
  createDesktopShortcut: true
```

### 7.4 主进程 TypeScript 编译

`desktop/` 使用独立的 `tsconfig.json`，编译主进程与 preload 到 `src/main/dist/` 和 `src/preload/dist/`（CommonJS 格式，Electron 主进程要求）。

---

## 8. 安全设计

### 8.1 进程隔离

- `contextIsolation: true`：preload 与渲染进程隔离
- `nodeIntegration: false`：渲染进程无 Node.js 访问
- `sandbox: true`：渲染进程沙箱
- preload 仅通过 `contextBridge` 暴露白名单 API，不暴露 `ipcRenderer` 原始对象

### 8.2 远程内容限制

- 生产模式仅加载本地 `file://` 资源
- CSP 头限制：`default-src 'self'; connect-src <后端URL> ws://<后端URL> wss://<后端URL>; img-src 'self' data: https:`
- 禁用 `webSecurity` 仅在开发模式且明确需要时

### 8.3 敏感数据存储

- 后端 URL：`electron-store` 加密存储（`encryptionKey` 派生自机器 ID）
- API Key：复用前端 `localStorage`（已有机制，不额外处理）
- 自动更新签名验证：`electron-updater` 代码签名

### 8.4 IPC 安全

- 所有 IPC 通道名在 `shared/ipc-channels.ts` 集中定义为常量
- `ipcMain.handle` 校验参数类型（使用 zod schema）
- 敏感操作（如 `backend:set-url`）需用户确认

---

## 9. 错误处理

### 9.1 后端连接失败

- 启动时若后端 URL 未配置 → 显示引导页
- 运行时后端不可达 → 前端现有错误处理机制生效（`client.ts` 响应拦截器记录日志、显示错误）
- 桌面端额外提供：菜单"检查连接"快速诊断

### 9.2 主进程异常

- `process.on('uncaughtException')`：记录日志到 `desktop/logs/main.log`，显示错误对话框后退出
- 窗口崩溃（`webContents.on('render-process-gone')`）：提示用户并重新加载

### 9.3 自动更新失败

- 网络错误：静默失败，下次启动重试
- 下载中断：支持断点续传（`electron-updater` 内置）
- 签名验证失败：拒绝安装，提示用户

---

## 10. 测试策略

### 10.1 主进程单元测试

- 使用 `vitest` + `@vitest/coverage-v8`
- Mock `electron` 模块（`vitest.config.ts` 中 `vi.mock('electron')`）
- 覆盖：窗口管理、菜单、托盘、快捷键、IPC 处理器、后端地址管理
- 覆盖率目标 >= 80%

### 10.2 集成测试

- 现有 `frontend/tests/e2e/electron-smoke.spec.ts` 扩展为完整桌面端冒烟测试
- 使用 Playwright Electron API 启动打包后的应用
- 覆盖：启动、引导页、登录、聊天、设置后端地址、托盘、快捷键

### 10.3 前端适配测试

- `client.ts` 的 `resolveBaseURL` 函数：单元测试覆盖三个优先级
- 设置页"后端连接"Tab：组件测试
- WebSocket URL 推导：单元测试

---

## 11. 依赖清单

### 11.1 `desktop/package.json` 生产依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| electron | ^35.7.5 | 桌面框架（与 frontend devDependencies 对齐） |
| electron-store | ^10.0.0 | 加密配置存储 |
| electron-updater | ^6.2.0 | 自动更新 |
| electron-log | ^5.1.0 | 日志 |

### 11.2 开发依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| electron-builder | ^25.0.0 | 打包 |
| typescript | ^5.3.0 | 类型（与 frontend 对齐） |
| tsx | ^4.7.0 | TS 脚本执行 |
| vitest | ^2.1.0 | 测试（与 frontend 对齐） |
| @types/node | ^25.5.0 | Node 类型 |
| eslint | ^9.0.0 | 代码规范 |

### 11.3 前端新增依赖

无。前端改动仅使用现有依赖（axios、localStorage）。

---

## 12. 配置项

### 12.1 `electron-store` 默认配置

```typescript
{
  backend: {
    url: '',                    // 后端地址，空则显示引导页
  },
  window: {
    bounds: { x: null, y: null, width: 1280, height: 800 },
    isMaximized: false,
  },
  tray: {
    minimizeToTray: true,       // 关闭时最小化到托盘
  },
  autostart: false,             // 开机自启
  update: {
    autoCheck: true,            // 自动检查更新
    source: '',                 // 更新源 URL，空则用默认 GitHub Release
  },
}
```

### 12.2 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENAWA_FRONTEND_URL` | - | 开发模式覆盖前端加载地址 |
| `OPENAWA_BACKEND_URL` | - | 预置后端地址（跳过引导页，用于测试） |
| `OPENAWA_UPDATE_SOURCE` | - | 覆盖自动更新源 |

---

## 13. 实现顺序建议

实现计划将由 `writing-plans` 技能生成，此处仅给出建议顺序：

1. **基础骨架**：`desktop/` 目录结构、`package.json`、tsconfig、主进程入口、preload、最小窗口
2. **前端适配**：`client.ts` 动态 baseURL、SSE/WebSocket 适配、设置页"后端连接"Tab
3. **后端地址管理**：`electron-store`、引导页、IPC 通道
4. **窗口与菜单**：窗口记忆、原生菜单、单实例锁、主题同步
5. **系统托盘**：托盘图标、右键菜单、关闭行为
6. **全局快捷键**：注册/注销、事件分发
7. **系统通知**：通知 API、点击跳转
8. **开机自启**：设置项、`setLoginItemSettings`
9. **自动更新**：`electron-updater` 集成、更新 UI
10. **构建打包**：`electron-builder` 配置、构建脚本、测试
11. **测试补全**：单元测试、集成测试、冒烟测试

---

## 14. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 前端 `client.ts` 改动影响 web 端 | 中 | 优先级链保证默认行为不变（`/api`）；新增单元测试覆盖 |
| SSE/WebSocket 在桌面端跨域 | 中 | 后端需配置 CORS 允许桌面端来源；preload 注入完整 URL |
| Electron 主进程 TypeScript 编译复杂 | 低 | 独立 tsconfig，CommonJS 输出，与 frontend 解耦 |
| 自动更新签名 | 中 | 初期可跳过代码签名（Windows 会警告）；后续申请证书 |
| 安装包体积（~80MB+） | 低 | 接受（用户已确认 Electron 方案） |

---

## 15. 未来扩展（不在本次范围）

- 本地文件系统访问（通过 IPC 桥接）
- 本地终端集成
- 多窗口支持（如独立聊天窗口）
- 文件关联打开（`.openawa` 协议）
- 自定义协议注册（`openawa://`）
- macOS Touch Bar
- Linux 系统托盘兼容性优化

---

## 附录 A：前端改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `frontend/src/shared/api/client.ts` | 修改 | 新增 `resolveBaseURL`、`setBackendUrl`，`API_BASE_URL` 改为函数调用结果 |
| `frontend/src/shared/api/api.ts` | 修改 | SSE fetch URL 引用 `API_BASE_URL`（若当前硬编码） |
| `frontend/src/shared/hooks/useWeixinWebSocket.ts` | 修改 | WebSocket URL 基于 `API_BASE_URL` 推导 |
| `frontend/src/features/settings/` | 新增 | `BackendConnectionTab` 组件及注册到设置页 |
| `frontend/src/shared/types/` | 新增 | `desktop.d.ts` 全局类型声明（`__OPENAWA_BACKEND__`、`__OPENAWA_DESKTOP__`） |

## 附录 B：desktop 新增文件清单

| 文件 | 说明 |
|------|------|
| `desktop/package.json` | 依赖与脚本 |
| `desktop/tsconfig.json` | TypeScript 配置（CommonJS） |
| `desktop/electron-builder.yml` | 打包配置 |
| `desktop/src/main/index.ts` | 主进程入口 |
| `desktop/src/main/window.ts` | 窗口管理 |
| `desktop/src/main/menu.ts` | 原生菜单 |
| `desktop/src/main/tray.ts` | 系统托盘 |
| `desktop/src/main/shortcuts.ts` | 全局快捷键 |
| `desktop/src/main/updater.ts` | 自动更新 |
| `desktop/src/main/ipc/backend.ts` | 后端地址 IPC |
| `desktop/src/main/ipc/notification.ts` | 通知 IPC |
| `desktop/src/main/ipc/window.ts` | 窗口控制 IPC |
| `desktop/src/main/ipc/update.ts` | 更新 IPC |
| `desktop/src/preload/index.ts` | preload 脚本 |
| `desktop/src/shared/ipc-channels.ts` | IPC 通道常量 |
| `desktop/src/shared/types.ts` | 共享类型 |
| `desktop/resources/onboarding.html` | 首次启动引导页 |
| `desktop/resources/icons/*` | 应用图标 |
| `desktop/scripts/build-frontend.ts` | 构建前端脚本 |
| `desktop/scripts/dev.ts` | 开发模式脚本 |

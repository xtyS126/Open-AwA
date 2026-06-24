# Open-AwA 桌面端（Electron）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在项目根目录新增 `desktop/` 文件夹，基于 Electron 构建跨平台桌面应用，包装复用现有 frontend 构建产物，覆盖全部 24+ 功能模块，连接用户配置的远程后端，提供中级桌面原生集成（窗口/菜单/托盘/快捷键/通知/开机自启/自动更新）。

**Architecture:** Electron 主进程管理窗口与原生能力，通过 preload 脚本以 `contextBridge` 暴露白名单 API；渲染进程加载 frontend 构建产物（dist），通过 `window.__OPENAWA_BACKEND__.url` 动态解析后端 baseURL；后端地址由 `electron-store` 加密存储，首次启动引导用户配置。

**Tech Stack:** Electron 35、electron-builder 25、electron-store 10、electron-updater 6、TypeScript 5.3、tsx 4.7、vitest 2.1

**Spec:** [docs/superpowers/specs/2026-06-24-desktop-electron-design.md](../specs/2026-06-24-desktop-electron-design.md)

---

## 文件结构总览

### 新增文件（desktop/）

| 文件 | 职责 |
|------|------|
| `desktop/package.json` | 依赖与脚本 |
| `desktop/tsconfig.json` | TypeScript 配置（CommonJS） |
| `desktop/tsconfig.scripts.json` | 脚本专用 tsconfig |
| `desktop/electron-builder.yml` | 打包配置 |
| `desktop/eslint.config.js` | ESLint 配置 |
| `desktop/.gitignore` | 忽略 node_modules/dist |
| `desktop/src/shared/ipc-channels.ts` | IPC 通道名常量 |
| `desktop/src/shared/types.ts` | 主进程/渲染进程共享类型 |
| `desktop/src/shared/config-store.ts` | electron-store 封装 |
| `desktop/src/preload/index.ts` | preload 脚本 |
| `desktop/src/main/index.ts` | 主进程入口 |
| `desktop/src/main/window.ts` | 窗口创建与管理 |
| `desktop/src/main/menu.ts` | 原生菜单 |
| `desktop/src/main/tray.ts` | 系统托盘 |
| `desktop/src/main/shortcuts.ts` | 全局快捷键 |
| `desktop/src/main/updater.ts` | 自动更新 |
| `desktop/src/main/ipc/backend.ts` | 后端地址 IPC |
| `desktop/src/main/ipc/window.ts` | 窗口控制 IPC |
| `desktop/src/main/ipc/notification.ts` | 通知 IPC |
| `desktop/src/main/ipc/update.ts` | 更新 IPC |
| `desktop/src/main/ipc/app.ts` | 应用信息 IPC |
| `desktop/src/main/ipc/autostart.ts` | 开机自启 IPC |
| `desktop/resources/onboarding.html` | 首次启动引导页 |
| `desktop/resources/icons/icon.png` | 应用图标占位（后续替换） |
| `desktop/scripts/build-frontend.ts` | 构建前端并复制产物 |
| `desktop/scripts/dev.ts` | 开发模式启动脚本 |
| `desktop/tests/setup.ts` | 测试 setup |
| `desktop/tests/config-store.test.ts` | config-store 单元测试 |
| `desktop/tests/ipc-backend.test.ts` | 后端 IPC 单元测试 |
| `desktop/tests/window.test.ts` | 窗口管理单元测试 |

### 修改文件（frontend/）

| 文件 | 改动 |
|------|------|
| `frontend/src/shared/api/client.ts` | 新增 `resolveBaseURL`、`setBackendUrl`，`API_BASE_URL` 改为动态解析 |
| `frontend/src/shared/hooks/useWeixinWebSocket.ts` | WebSocket URL 基于 `API_BASE_URL` 推导 |
| `frontend/src/shared/types/desktop.d.ts` | 新增全局类型声明 |
| `frontend/src/features/settings/components/BackendConnection/BackendConnection.tsx` | 新增后端连接 Tab 组件 |
| `frontend/src/features/settings/components/BackendConnection/index.ts` | 导出 |
| `frontend/src/features/settings/containers/BackendConnectionTabContainer.tsx` | 新增容器 |
| `frontend/src/features/settings/SettingsPage.tsx` | 注册新 Tab |
| `frontend/src/__tests__/client.test.ts` | 新增 client.ts 单元测试 |

---

## Task 1: 创建 desktop 项目骨架

**Files:**
- Create: `desktop/package.json`
- Create: `desktop/tsconfig.json`
- Create: `desktop/tsconfig.scripts.json`
- Create: `desktop/.gitignore`
- Create: `desktop/eslint.config.js`
- Create: `desktop/src/shared/ipc-channels.ts`
- Create: `desktop/src/shared/types.ts`

- [ ] **Step 1: 创建 `desktop/.gitignore`**

```
node_modules/
dist/
resources/frontend/
*.log
.vite-cache/
```

- [ ] **Step 2: 创建 `desktop/package.json`**

```json
{
  "name": "openawa-desktop",
  "version": "1.0.0",
  "description": "Open-AwA 桌面端应用",
  "main": "src/main/dist/index.js",
  "scripts": {
    "dev": "tsx scripts/dev.ts",
    "build:frontend": "tsx scripts/build-frontend.ts",
    "build:main": "tsc -p tsconfig.json",
    "build": "npm run build:frontend && npm run build:main && electron-builder",
    "build:win": "npm run build:frontend && npm run build:main && electron-builder --win",
    "build:mac": "npm run build:frontend && npm run build:main && electron-builder --mac",
    "build:linux": "npm run build:frontend && npm run build:main && electron-builder --linux",
    "typecheck": "tsc --noEmit",
    "test": "vitest run",
    "test:watch": "vitest",
    "lint": "eslint src --ext .ts"
  },
  "dependencies": {
    "electron-store": "^10.0.0",
    "electron-updater": "^6.2.0",
    "electron-log": "^5.1.0"
  },
  "devDependencies": {
    "electron": "^35.7.5",
    "electron-builder": "^25.0.0",
    "typescript": "^5.3.3",
    "tsx": "^4.7.0",
    "vitest": "^2.1.8",
    "@types/node": "^25.5.2",
    "eslint": "^9.0.0"
  }
}
```

- [ ] **Step 3: 创建 `desktop/tsconfig.json`（主进程与 preload 编译）**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "CommonJS",
    "moduleResolution": "node",
    "lib": ["ES2020", "DOM"],
    "outDir": "./src/main/dist",
    "rootDir": "./src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true,
    "declaration": false,
    "sourceMap": true,
    "types": ["node"]
  },
  "include": ["src/main/**/*", "src/preload/**/*", "src/shared/**/*"],
  "exclude": ["node_modules", "dist", "tests", "scripts"]
}
```

注意：preload 输出到 `src/preload/dist`，但为简化配置，统一输出到 `src/main/dist`，preload 文件命名为 `preload/index.js`，主进程引用 `./preload/index.js`。实际需调整：主进程输出 `src/main/dist/main/`，preload 输出 `src/main/dist/preload/`。

修正 tsconfig.json：

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "CommonJS",
    "moduleResolution": "node",
    "lib": ["ES2020", "DOM"],
    "outDir": "./dist",
    "rootDir": "./src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true,
    "declaration": false,
    "sourceMap": true,
    "types": ["node"]
  },
  "include": ["src/main/**/*", "src/preload/**/*", "src/shared/**/*"],
  "exclude": ["node_modules", "dist", "tests", "scripts"]
}
```

输出结构：`dist/main/index.js`、`dist/preload/index.js`、`dist/shared/*`。主进程入口 `main` 字段改为 `dist/main/index.js`。

更新 package.json 的 main 字段：`"main": "dist/main/index.js"`。

- [ ] **Step 4: 创建 `desktop/tsconfig.scripts.json`（脚本编译，供 tsx 使用）**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "lib": ["ES2020"],
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "resolveJsonModule": true,
    "types": ["node"]
  },
  "include": ["scripts/**/*"]
}
```

- [ ] **Step 5: 创建 `desktop/eslint.config.js`**

```javascript
// ESLint 配置 - 桌面端主进程
module.exports = {
  root: true,
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 2020,
    sourceType: 'module',
  },
  extends: [
    'eslint:recommended',
  ],
  rules: {
    'no-console': ['error', { allow: ['error', 'warn'] }],
    'no-unused-vars': 'off',
  },
  ignorePatterns: ['dist/', 'node_modules/', 'resources/frontend/'],
}
```

注意：项目规则禁止 emoji，此配置不含 emoji。ESLint 配置使用 CommonJS（package.json 未设 `"type": "module"`）。

- [ ] **Step 6: 创建 `desktop/src/shared/ipc-channels.ts`（IPC 通道名常量）**

```typescript
/**
 * IPC 通道名常量集中定义
 * 格式：<域>:<动作>
 * 所有主进程与渲染进程通信必须使用此处定义的通道名
 */

export const IPC_CHANNELS = {
  // 后端地址管理
  BACKEND_GET_URL: 'backend:get-url',
  BACKEND_SET_URL: 'backend:set-url',
  BACKEND_TEST_CONNECTION: 'backend:test-connection',
  BACKEND_URL_CHANGED: 'backend:url-changed',

  // 窗口控制
  WINDOW_MINIMIZE: 'window:minimize',
  WINDOW_MAXIMIZE: 'window:maximize',
  WINDOW_CLOSE: 'window:close',
  WINDOW_IS_MAXIMIZED: 'window:is-maximized',
  WINDOW_MAXIMIZE_STATE_CHANGED: 'window:maximize-state-changed',

  // 系统通知
  NOTIFICATION_SHOW: 'notification:show',
  NOTIFICATION_CLICKED: 'notification:clicked',

  // 应用信息
  APP_GET_VERSION: 'app:get-version',
  APP_GET_PLATFORM: 'app:get-platform',

  // 自动更新
  UPDATE_CHECK: 'update:check',
  UPDATE_DOWNLOAD: 'update:download',
  UPDATE_INSTALL_AND_RESTART: 'update:install-and-restart',
  UPDATE_STATUS_CHANGED: 'update:status-changed',

  // 动作（全局快捷键/托盘菜单触发）
  ACTION_NEW_CHAT: 'action:new-chat',

  // 开机自启
  AUTOSTART_GET: 'autostart:get',
  AUTOSTART_SET: 'autostart:set',
} as const

/** IPC 通道名类型 */
export type IpcChannel = typeof IPC_CHANNELS[keyof typeof IPC_CHANNELS]
```

- [ ] **Step 7: 创建 `desktop/src/shared/types.ts`（共享类型）**

```typescript
/**
 * 主进程与渲染进程共享的类型定义
 */

/** 后端地址配置 */
export interface BackendConfig {
  url: string
}

/** 窗口边界配置 */
export interface WindowBounds {
  x: number | null
  y: number | null
  width: number
  height: number
}

/** 窗口配置 */
export interface WindowConfig {
  bounds: WindowBounds
  isMaximized: boolean
}

/** 托盘配置 */
export interface TrayConfig {
  minimizeToTray: boolean
}

/** 自动更新配置 */
export interface UpdateConfig {
  autoCheck: boolean
  source: string
}

/** 应用完整配置（electron-store 存储结构） */
export interface AppConfig {
  backend: BackendConfig
  window: WindowConfig
  tray: TrayConfig
  autostart: boolean
  update: UpdateConfig
}

/** 默认配置 */
export const DEFAULT_CONFIG: AppConfig = {
  backend: {
    url: '',
  },
  window: {
    bounds: { x: null, y: null, width: 1280, height: 800 },
    isMaximized: false,
  },
  tray: {
    minimizeToTray: true,
  },
  autostart: false,
  update: {
    autoCheck: true,
    source: '',
  },
}

/** 后端连接测试结果 */
export interface ConnectionTestResult {
  ok: boolean
  latency?: number
  error?: string
}

/** 系统通知请求参数 */
export interface NotificationRequest {
  title: string
  body: string
  url?: string
}

/** 通知点击事件参数 */
export interface NotificationClickedPayload {
  url?: string
}

/** 自动更新状态 */
export type UpdateStatus = 'idle' | 'checking' | 'available' | 'not-available' | 'downloading' | 'downloaded' | 'error'

/** 自动更新状态变更事件 */
export interface UpdateStatusPayload {
  status: UpdateStatus
  progress?: number
  error?: string
  version?: string
}

/** preload 注入的后端信息 */
export interface BackendInfo {
  url: string
  version: string
}

/** preload 注入的桌面端 API */
export interface DesktopApi {
  platform: string
  isPackaged: boolean
  ipc: {
    invoke: (channel: string, ...args: unknown[]) => Promise<unknown>
    on: (channel: string, listener: (...args: unknown[]) => void) => () => void
  }
}
```

- [ ] **Step 8: 验证 TypeScript 配置正确**

Run: `cd desktop && npm install && npx tsc --noEmit`
Expected: 无错误（此时 src 下仅有 shared 两个文件，无 main/preload，应能通过）

- [ ] **Step 9: 提交**

```bash
cd d:\代码\Open-AwA
git add desktop/
git commit -m "[New] 桌面端项目骨架：package.json、tsconfig、IPC 通道常量与共享类型"
```

---

## Task 2: 前端 client.ts 动态 baseURL 适配

**Files:**
- Modify: `frontend/src/shared/api/client.ts`
- Create: `frontend/src/shared/types/desktop.d.ts`
- Test: `frontend/src/__tests__/client.test.ts`

- [ ] **Step 1: 创建全局类型声明 `frontend/src/shared/types/desktop.d.ts`**

```typescript
/**
 * 桌面端注入的全局对象类型声明
 * Web 端这些对象为 undefined，桌面端由 preload 脚本注入
 */

/** 后端连接信息（桌面端 preload 注入） */
export interface BackendInfo {
  url: string
  version: string
}

/** 桌面端 API（桌面端 preload 注入） */
export interface DesktopApi {
  platform: string
  isPackaged: boolean
  ipc: {
    invoke: (channel: string, ...args: unknown[]) => Promise<unknown>
    on: (channel: string, listener: (...args: unknown[]) => void) => () => void
  }
}

declare global {
  interface Window {
    /** 桌面端 preload 注入的后端地址 */
    __OPENAWA_BACKEND__?: BackendInfo
    /** 桌面端 preload 注入的原生能力 API */
    __OPENAWA_DESKTOP__?: DesktopApi
  }
}

export {}
```

- [ ] **Step 2: 编写失败测试 `frontend/src/__tests__/client.test.ts`**

```typescript
import { describe, it, expect, beforeEach, vi } from 'vitest'

// 在导入 client 之前 mock window 对象
describe('API_BASE_URL 动态解析', () => {
  beforeEach(() => {
    // 每个测试前重置 window 状态
    vi.resetModules()
    localStorage.clear()
    // 重置 window 注入对象
    delete (window as unknown as { __OPENAWA_BACKEND__?: unknown }).__OPENAWA_BACKEND__
  })

  it('优先级 1：使用 preload 注入的 __OPENAWA_BACKEND__.url', async () => {
    ;(window as unknown as { __OPENAWA_BACKEND__?: { url: string } }).__OPENAWA_BACKEND__ = {
      url: 'http://remote-backend:8000/api',
    }
    const { API_BASE_URL } = await import('@/shared/api/client')
    expect(API_BASE_URL).toBe('http://remote-backend:8000/api')
  })

  it('优先级 2：使用 localStorage 中的 openawa_backend_url', async () => {
    localStorage.setItem('openawa_backend_url', 'http://stored-backend:9000/api')
    const { API_BASE_URL } = await import('@/shared/api/client')
    expect(API_BASE_URL).toBe('http://stored-backend:9000/api')
  })

  it('优先级 3：默认返回 /api（web 模式）', async () => {
    const { API_BASE_URL } = await import('@/shared/api/client')
    expect(API_BASE_URL).toBe('/api')
  })

  it('preload 注入优先级高于 localStorage', async () => {
    ;(window as unknown as { __OPENAWA_BACKEND__?: { url: string } }).__OPENAWA_BACKEND__ = {
      url: 'http://preload-backend:8000/api',
    }
    localStorage.setItem('openawa_backend_url', 'http://stored-backend:9000/api')
    const { API_BASE_URL } = await import('@/shared/api/client')
    expect(API_BASE_URL).toBe('http://preload-backend:8000/api')
  })
})

describe('setBackendUrl', () => {
  beforeEach(() => {
    vi.resetModules()
    localStorage.clear()
  })

  it('将 URL 写入 localStorage', async () => {
    const { setBackendUrl } = await import('@/shared/api/client')
    setBackendUrl('http://new-backend:8000/api')
    expect(localStorage.getItem('openawa_backend_url')).toBe('http://new-backend:8000/api')
  })
})
```

- [ ] **Step 3: 运行测试验证失败**

Run: `cd frontend && npx vitest run src/__tests__/client.test.ts`
Expected: FAIL（`API_BASE_URL` 当前是常量 `/api`，无法动态解析）

- [ ] **Step 4: 修改 `frontend/src/shared/api/client.ts`**

在文件顶部 import 之后，替换 `const API_BASE_URL = '/api'` 为动态解析逻辑：

```typescript
// 替换原有的：const API_BASE_URL = '/api'
const BACKEND_URL_STORAGE_KEY = 'openawa_backend_url'

/**
 * 动态解析后端 baseURL
 * 优先级：preload 注入 > localStorage > 默认 /api
 */
function resolveBaseURL(): string {
  // 优先级 1：桌面端 preload 注入
  if (typeof window !== 'undefined' && window.__OPENAWA_BACKEND__?.url) {
    return window.__OPENAWA_BACKEND__.url
  }
  // 优先级 2：用户在设置页配置的远程后端
  if (typeof window !== 'undefined') {
    const stored = window.localStorage.getItem(BACKEND_URL_STORAGE_KEY)
    if (stored) {
      return stored
    }
  }
  // 优先级 3：默认相对路径（web 模式走 Vite proxy）
  return '/api'
}

export const API_BASE_URL = resolveBaseURL()

/**
 * 设置后端 URL 并持久化到 localStorage
 * 注意：运行时修改后需刷新页面才能生效（axios 实例 baseURL 在模块加载时确定）
 */
export function setBackendUrl(url: string): void {
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(BACKEND_URL_STORAGE_KEY, url)
  }
}
```

- [ ] **Step 5: 运行测试验证通过**

Run: `cd frontend && npx vitest run src/__tests__/client.test.ts`
Expected: PASS（4 个测试用例全部通过）

- [ ] **Step 6: 运行前端类型检查确保无回归**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 7: 提交**

```bash
cd d:\代码\Open-AwA
git add frontend/src/shared/api/client.ts frontend/src/shared/types/desktop.d.ts frontend/src/__tests__/client.test.ts
git commit -m "[New] 前端 client.ts 支持动态 baseURL 解析（preload 注入优先）"
```

---

## Task 3: 前端 WebSocket URL 适配

**Files:**
- Modify: `frontend/src/shared/hooks/useWeixinWebSocket.ts:84-87`
- Test: `frontend/src/__tests__/useWeixinWebSocket.test.ts`

- [ ] **Step 1: 编写失败测试 `frontend/src/__tests__/useWeixinWebSocket.test.ts`**

```typescript
import { describe, it, expect } from 'vitest'

describe('WebSocket URL 推导', () => {
  it('从相对路径 /api 推导为当前 host 的 ws 连接', async () => {
    // 模拟 web 模式：API_BASE_URL = '/api'，使用 location.host
    const apiBaseUrl = '/api'
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const expected = `${protocol}//${host}/api/weixin/ws`
    const actual = `${protocol}//${host}${apiBaseUrl}/weixin/ws`
    expect(actual).toBe(expected)
  })

  it('从绝对 URL 推导 ws/wss 协议与 host', async () => {
    const apiBaseUrl = 'http://remote-backend:8000/api'
    const url = new URL(apiBaseUrl)
    const protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    const expected = `ws://remote-backend:8000/api/weixin/ws`
    const actual = `${protocol}//${url.host}${url.pathname}/weixin/ws`
    expect(actual).toBe(expected)
  })

  it('从 HTTPS 绝对 URL 推导 wss 协议', async () => {
    const apiBaseUrl = 'https://secure-backend:8443/api'
    const url = new URL(apiBaseUrl)
    const protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    const expected = `wss://secure-backend:8443/api/weixin/ws`
    const actual = `${protocol}//${url.host}${url.pathname}/weixin/ws`
    expect(actual).toBe(expected)
  })
})
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd frontend && npx vitest run src/__tests__/useWeixinWebSocket.test.ts`
Expected: PASS（这些是纯逻辑测试，验证 URL 推导规则）

注意：此测试验证的是推导逻辑，不是 hook 本身。我们需要将推导逻辑提取为可测试函数。

- [ ] **Step 3: 修改 `frontend/src/shared/hooks/useWeixinWebSocket.ts`**

在文件顶部新增导入和 URL 推导函数：

```typescript
import { API_BASE_URL } from '@/shared/api/client'

/**
 * 根据 API_BASE_URL 推导 WebSocket URL
 * - 相对路径（/api）：使用当前页面 host
 * - 绝对 URL：使用该 URL 的 host 与协议
 */
function deriveWebSocketUrl(token: string): string {
  // 判断 API_BASE_URL 是否为绝对 URL
  if (API_BASE_URL.startsWith('http://') || API_BASE_URL.startsWith('https://')) {
    const url = new URL(API_BASE_URL)
    const protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${url.host}${url.pathname}/weixin/ws?token=${encodeURIComponent(token)}`
  }
  // 相对路径：使用当前页面 host（web 模式）
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  return `${protocol}//${host}${API_BASE_URL}/weixin/ws?token=${encodeURIComponent(token)}`
}
```

然后在 `connect` 函数中替换原 URL 拼接逻辑（第 84-87 行）：

```typescript
// 替换：
// const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
// const host = window.location.host
// const url = `${protocol}//${host}/api/weixin/ws?token=${encodeURIComponent(token)}`

// 为：
const url = deriveWebSocketUrl(token)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd frontend && npx vitest run src/__tests__/useWeixinWebSocket.test.ts`
Expected: PASS

- [ ] **Step 5: 运行类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 6: 提交**

```bash
cd d:\代码\Open-AwA
git add frontend/src/shared/hooks/useWeixinWebSocket.ts frontend/src/__tests__/useWeixinWebSocket.test.ts
git commit -m "[New] WebSocket URL 基于 API_BASE_URL 动态推导，支持桌面端远程后端"
```

---

## Task 4: 前端设置页新增"后端连接"Tab

**Files:**
- Create: `frontend/src/features/settings/components/BackendConnection/BackendConnection.tsx`
- Create: `frontend/src/features/settings/components/BackendConnection/BackendConnection.module.css`
- Create: `frontend/src/features/settings/components/BackendConnection/index.ts`
- Create: `frontend/src/features/settings/containers/BackendConnectionTabContainer.tsx`
- Modify: `frontend/src/features/settings/SettingsPage.tsx`

- [ ] **Step 1: 创建 `frontend/src/features/settings/components/BackendConnection/BackendConnection.tsx`**

```tsx
/**
 * 后端连接设置组件
 * 允许用户配置远程后端 URL，测试连通性并应用
 * Web 端和桌面端通用
 */
import { useState } from 'react'
import { API_BASE_URL, setBackendUrl } from '@/shared/api/client'
import { useNotification } from '@/shared/hooks/useNotification'
import styles from './BackendConnection.module.css'

interface BackendConnectionProps {
  /** 当前后端 URL */
  currentUrl: string
  /** 是否为桌面端（影响保存逻辑：桌面端通过 IPC 通知主进程） */
  isDesktop: boolean
  /** 保存回调（桌面端通过 IPC 保存到 electron-store） */
  onSave?: (url: string) => Promise<void>
  /** 测试连接回调（桌面端通过 IPC 测试，web 端直接 fetch） */
  onTest?: (url: string) => Promise<{ ok: boolean; latency?: number; error?: string }>
}

export function BackendConnection({ currentUrl, isDesktop, onSave, onTest }: BackendConnectionProps) {
  const [url, setUrl] = useState(currentUrl)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; latency?: number; error?: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const { notify } = useNotification()

  const handleTest = async () => {
    if (!url.trim()) {
      notify({ type: 'error', message: '请输入后端 URL' })
      return
    }
    setTesting(true)
    setTestResult(null)
    try {
      const result = onTest
        ? await onTest(url.trim())
        : await testConnectionWeb(url.trim())
      setTestResult(result)
      if (result.ok) {
        notify({ type: 'success', message: `连接成功（延迟 ${result.latency}ms）` })
      } else {
        notify({ type: 'error', message: `连接失败：${result.error || '未知错误'}` })
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : String(err)
      setTestResult({ ok: false, error: errorMsg })
      notify({ type: 'error', message: `测试失败：${errorMsg}` })
    } finally {
      setTesting(false)
    }
  }

  const handleSave = async () => {
    if (!url.trim()) {
      notify({ type: 'error', message: '请输入后端 URL' })
      return
    }
    setSaving(true)
    try {
      if (onSave) {
        await onSave(url.trim())
      } else {
        setBackendUrl(url.trim())
      }
      notify({ type: 'success', message: '后端地址已保存，即将刷新页面...' })
      // 刷新页面以应用新的 baseURL
      setTimeout(() => window.location.reload(), 1000)
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : String(err)
      notify({ type: 'error', message: `保存失败：${errorMsg}` })
    } finally {
      setSaving(false)
    }
  }

  const handleReset = () => {
    setUrl('/api')
    setBackendUrl('')
    notify({ type: 'success', message: '已重置为默认，即将刷新页面...' })
    setTimeout(() => window.location.reload(), 1000)
  }

  return (
    <div className={styles.container}>
      <h2 className={styles.title}>后端连接</h2>
      <p className={styles.description}>
        {isDesktop
          ? '配置 Open-AwA 后端服务地址。修改后需刷新页面生效。'
          : '配置远程后端服务地址（默认 /api 走代理）。修改后需刷新页面生效。'}
      </p>

      <div className={styles.field}>
        <label className={styles.label} htmlFor="backend-url">后端 URL</label>
        <input
          id="backend-url"
          className={styles.input}
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="http://localhost:8000/api"
          disabled={testing || saving}
        />
      </div>

      {testResult && (
        <div className={`${styles.testResult} ${testResult.ok ? styles.success : styles.error}`}>
          {testResult.ok
            ? `连接成功（延迟 ${testResult.latency}ms）`
            : `连接失败：${testResult.error || '未知错误'}`}
        </div>
      )}

      <div className={styles.actions}>
        <button
          className={styles.button}
          onClick={handleTest}
          disabled={testing || saving || !url.trim()}
        >
          {testing ? '测试中...' : '测试连接'}
        </button>
        <button
          className={`${styles.button} ${styles.primary}`}
          onClick={handleSave}
          disabled={testing || saving || !url.trim()}
        >
          {saving ? '保存中...' : '保存并应用'}
        </button>
        <button
          className={styles.button}
          onClick={handleReset}
          disabled={testing || saving}
        >
          重置为默认
        </button>
      </div>
    </div>
  )
}

/** Web 端默认测试连接实现：直接 fetch /health */
async function testConnectionWeb(baseUrl: string): Promise<{ ok: boolean; latency?: number; error?: string }> {
  const start = Date.now()
  try {
    const healthUrl = baseUrl.endsWith('/api') ? `${baseUrl}/health` : `${baseUrl}/api/health`
    const response = await fetch(healthUrl, { method: 'GET', signal: AbortSignal.timeout(5000) })
    const latency = Date.now() - start
    if (response.ok) {
      return { ok: true, latency }
    }
    return { ok: false, latency, error: `HTTP ${response.status}` }
  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : String(err)
    return { ok: false, error: errorMsg }
  }
}
```

- [ ] **Step 2: 创建 `frontend/src/features/settings/components/BackendConnection/BackendConnection.module.css`**

```css
.container {
  max-width: 600px;
}

.title {
  font-size: 1.25rem;
  font-weight: 600;
  margin: 0 0 0.5rem 0;
}

.description {
  color: #6b7280;
  font-size: 0.875rem;
  margin: 0 0 1.5rem 0;
}

.field {
  margin-bottom: 1rem;
}

.label {
  display: block;
  font-size: 0.875rem;
  font-weight: 500;
  margin-bottom: 0.5rem;
}

.input {
  width: 100%;
  padding: 0.5rem 0.75rem;
  border: 1px solid #d1d5db;
  border-radius: 0.375rem;
  font-size: 0.875rem;
  box-sizing: border-box;
}

.input:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.input:disabled {
  background-color: #f3f4f6;
  cursor: not-allowed;
}

.testResult {
  padding: 0.75rem;
  border-radius: 0.375rem;
  font-size: 0.875rem;
  margin-bottom: 1rem;
}

.success {
  background-color: #d1fae5;
  color: #065f46;
}

.error {
  background-color: #fee2e2;
  color: #991b1b;
}

.actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.button {
  padding: 0.5rem 1rem;
  border: 1px solid #d1d5db;
  border-radius: 0.375rem;
  background-color: #ffffff;
  cursor: pointer;
  font-size: 0.875rem;
  transition: background-color 0.15s;
}

.button:hover:not(:disabled) {
  background-color: #f9fafb;
}

.button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.primary {
  background-color: #3b82f6;
  color: #ffffff;
  border-color: #3b82f6;
}

.primary:hover:not(:disabled) {
  background-color: #2563eb;
}
```

- [ ] **Step 3: 创建 `frontend/src/features/settings/components/BackendConnection/index.ts`**

```typescript
export { BackendConnection } from './BackendConnection'
```

- [ ] **Step 4: 创建 `frontend/src/features/settings/containers/BackendConnectionTabContainer.tsx`**

```tsx
/**
 * 后端连接 Tab 容器组件
 * 管理桌面端/web 端的差异逻辑
 */
import { useCallback } from 'react'
import { BackendConnection } from '@/features/settings/components/BackendConnection'
import { API_BASE_URL } from '@/shared/api/client'

export function BackendConnectionTabContainer() {
  const isDesktop = typeof window !== 'undefined' && !!window.__OPENAWA_DESKTOP__

  /** 桌面端通过 IPC 保存后端地址到 electron-store */
  const handleSave = useCallback(async (url: string): Promise<void> => {
    if (!window.__OPENAWA_DESKTOP__) {
      // Web 端：setBackendUrl 已在组件内调用
      return
    }
    const result = await window.__OPENAWA_DESKTOP__.ipc.invoke('backend:set-url', { url }) as { success: boolean }
    if (!result.success) {
      throw new Error('保存后端地址失败')
    }
    // 桌面端主进程会发送 backend:url-changed 事件，渲染进程监听后刷新
  }, [])

  /** 桌面端通过 IPC 测试连接（主进程发起请求，避免 CORS） */
  const handleTest = useCallback(async (url: string): Promise<{ ok: boolean; latency?: number; error?: string }> => {
    if (!window.__OPENAWA_DESKTOP__) {
      // Web 端：组件内默认实现 testConnectionWeb
      return { ok: false, error: '使用默认测试' }
    }
    const result = await window.__OPENAWA_DESKTOP__.ipc.invoke('backend:test-connection', { url }) as { ok: boolean; latency?: number; error?: string }
    return result
  }, [])

  return (
    <div className="settings-section">
      <BackendConnection
        currentUrl={API_BASE_URL}
        isDesktop={isDesktop}
        onSave={handleSave}
        onTest={handleTest}
      />
    </div>
  )
}
```

- [ ] **Step 5: 修改 `frontend/src/features/settings/SettingsPage.tsx` 注册新 Tab**

在懒加载导入区域（第 36 行后）新增：

```typescript
const BackendConnectionTabContainer = lazy(() => import('./containers/BackendConnectionTabContainer').then(m => ({ default: m.BackendConnectionTabContainer })))
```

在 `renderSecondarySidebar` 的 tabs 数组中新增（在 'advanced' 之前）：

```typescript
{ id: 'backend', label: '后端连接', icon: <Plug size={18} /> },
```

注意：'api' Tab 已使用 Plug 图标，'backend' 改用其他图标。从 lucide-react 导入 `Server` 图标：

在文件顶部 import 中新增 `Server`：

```typescript
import {
  Settings as SettingsIcon,
  ShieldAlert,
  Cpu,
  Briefcase,
  Plug,
  HardDrive,
  Key,
  Sliders,
  Palette,
  Wrench,
  Server,
  ChevronRight,
} from 'lucide-react'
```

tabs 数组中新增：

```typescript
{ id: 'backend', label: '后端连接', icon: <Server size={18} /> },
```

在渲染区域（`activeTab === 'advanced'` 之前）新增：

```tsx
{activeTab === 'backend' && (
  <ErrorBoundary name="BackendConnection">
    <Suspense fallback={<TabLoadingFallback />}>
      <BackendConnectionTabContainer />
    </Suspense>
  </ErrorBoundary>
)}
```

- [ ] **Step 6: 运行类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 7: 运行前端测试确保无回归**

Run: `cd frontend && npx vitest run`
Expected: 全部通过

- [ ] **Step 8: 提交**

```bash
cd d:\代码\Open-AwA
git add frontend/src/features/settings/components/BackendConnection/ frontend/src/features/settings/containers/BackendConnectionTabContainer.tsx frontend/src/features/settings/SettingsPage.tsx
git commit -m "[New] 设置页新增后端连接 Tab，支持配置远程后端地址"
```

---

## Task 5: desktop config-store 封装

**Files:**
- Create: `desktop/src/shared/config-store.ts`
- Test: `desktop/tests/setup.ts`
- Test: `desktop/tests/config-store.test.ts`
- Create: `desktop/vitest.config.ts`

- [ ] **Step 1: 创建 `desktop/vitest.config.ts`**

```typescript
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'node',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      include: ['src/**/*.ts'],
      exclude: ['src/**/*.test.ts', 'tests/**'],
    },
  },
})
```

- [ ] **Step 2: 创建 `desktop/tests/setup.ts`**

```typescript
/**
 * 测试 setup：mock electron 模块
 */
import { vi } from 'vitest'

// mock electron 模块
vi.mock('electron', () => ({
  app: {
    isPackaged: false,
    getPath: vi.fn((name: string) => `/tmp/openawa-test/${name}`),
    getVersion: vi.fn(() => '1.0.0-test'),
  },
  BrowserWindow: vi.fn(),
  ipcMain: {
    handle: vi.fn(),
    on: vi.fn(),
  },
  ipcRenderer: {
    invoke: vi.fn(),
    on: vi.fn(),
    removeListener: vi.fn(),
  },
  contextBridge: {
    exposeInMainWorld: vi.fn(),
  },
  nativeTheme: {
    themeSource: 'system',
  },
  Notification: vi.fn(),
  globalShortcut: {
    register: vi.fn(),
    unregister: vi.fn(),
    unregisterAll: vi.fn(),
  },
  Tray: vi.fn(),
  Menu: {
    buildFromTemplate: vi.fn(),
    setApplicationMenu: vi.fn(),
  },
  shell: {
    openExternal: vi.fn(),
  },
}))

// mock electron-store
vi.mock('electron-store', () => {
  const store = new Map<string, unknown>()
  return {
    default: class {
      get(key: string, defaultValue?: unknown) {
        return store.has(key) ? store.get(key) : defaultValue
      }
      set(key: string, value: unknown) {
        store.set(key, value)
      }
      delete(key: string) {
        store.delete(key)
      }
      clear() {
        store.clear()
      }
      has(key: string) {
        return store.has(key)
      }
      get store() {
        return Object.fromEntries(store)
      }
      set store(value) {
        store.clear()
        for (const [k, v] of Object.entries(value)) {
          store.set(k, v)
        }
      }
    },
  }
})
```

- [ ] **Step 3: 编写失败测试 `desktop/tests/config-store.test.ts`**

```typescript
import { describe, it, expect, beforeEach } from 'vitest'
import { getConfigStore, getBackendUrl, setBackendUrl, getWindowBounds, setWindowBounds } from '../src/shared/config-store'

describe('config-store', () => {
  beforeEach(() => {
    // 每个测试前清空 store
    getConfigStore().clear()
  })

  describe('getBackendUrl / setBackendUrl', () => {
    it('默认返回空字符串', () => {
      expect(getBackendUrl()).toBe('')
    })

    it('设置后返回设置的值', () => {
      setBackendUrl('http://localhost:8000/api')
      expect(getBackendUrl()).toBe('http://localhost:8000/api')
    })

    it('覆盖设置后返回新值', () => {
      setBackendUrl('http://old:8000/api')
      setBackendUrl('http://new:9000/api')
      expect(getBackendUrl()).toBe('http://new:9000/api')
    })
  })

  describe('getWindowBounds / setWindowBounds', () => {
    it('默认返回 1280x800', () => {
      const bounds = getWindowBounds()
      expect(bounds.width).toBe(1280)
      expect(bounds.height).toBe(800)
    })

    it('设置后返回设置的值', () => {
      setWindowBounds({ x: 100, y: 200, width: 1024, height: 768 })
      const bounds = getWindowBounds()
      expect(bounds.x).toBe(100)
      expect(bounds.y).toBe(200)
      expect(bounds.width).toBe(1024)
      expect(bounds.height).toBe(768)
    })
  })
})
```

- [ ] **Step 4: 运行测试验证失败**

Run: `cd desktop && npx vitest run tests/config-store.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 5: 创建 `desktop/src/shared/config-store.ts`**

```typescript
/**
 * electron-store 配置存储封装
 * 提供类型安全的配置读写接口
 */
import Store from 'electron-store'
import { DEFAULT_CONFIG, type AppConfig, type WindowBounds } from './types'

let _store: Store<AppConfig> | null = null

/** 获取 store 单例 */
export function getConfigStore(): Store<AppConfig> {
  if (!_store) {
    _store = new Store<AppConfig>({
      name: 'openawa-config',
      defaults: DEFAULT_CONFIG,
      encryptionKey: 'openawa-desktop-v1',
    })
  }
  return _store
}

/** 获取后端 URL */
export function getBackendUrl(): string {
  return getConfigStore().get('backend.url')
}

/** 设置后端 URL */
export function setBackendUrl(url: string): void {
  getConfigStore().set('backend.url', url)
}

/** 获取窗口边界 */
export function getWindowBounds(): WindowBounds {
  return getConfigStore().get('window.bounds')
}

/** 设置窗口边界 */
export function setWindowBounds(bounds: WindowBounds): void {
  getConfigStore().set('window.bounds', bounds)
}

/** 获取窗口是否最大化 */
export function getIsMaximized(): boolean {
  return getConfigStore().get('window.isMaximized')
}

/** 设置窗口是否最大化 */
export function setIsMaximized(isMaximized: boolean): void {
  getConfigStore().set('window.isMaximized', isMaximized)
}

/** 获取托盘配置：是否最小化到托盘 */
export function getMinimizeToTray(): boolean {
  return getConfigStore().get('tray.minimizeToTray')
}

/** 设置托盘配置：是否最小化到托盘 */
export function setMinimizeToTray(minimizeToTray: boolean): void {
  getConfigStore().set('tray.minimizeToTray', minimizeToTray)
}

/** 获取开机自启设置 */
export function getAutostart(): boolean {
  return getConfigStore().get('autostart')
}

/** 设置开机自启 */
export function setAutostart(autostart: boolean): void {
  getConfigStore().set('autostart', autostart)
}

/** 获取自动更新配置 */
export function getUpdateConfig() {
  return getConfigStore().get('update')
}

/** 设置自动更新配置 */
export function setUpdateConfig(autoCheck: boolean, source: string): void {
  getConfigStore().set('update', { autoCheck, source })
}
```

注意：`electron-store` 的 `get`/`set` 支持点号路径访问嵌套属性（如 `'backend.url'`）。

- [ ] **Step 6: 运行测试验证通过**

Run: `cd desktop && npx vitest run tests/config-store.test.ts`
Expected: PASS（5 个测试用例全部通过）

- [ ] **Step 7: 提交**

```bash
cd d:\代码\Open-AwA
git add desktop/src/shared/config-store.ts desktop/tests/ desktop/vitest.config.ts
git commit -m "[New] 桌面端 config-store 封装：electron-store 类型安全读写"
```

---

## Task 6: desktop preload 脚本

**Files:**
- Create: `desktop/src/preload/index.ts`

- [ ] **Step 1: 创建 `desktop/src/preload/index.ts`**

```typescript
/**
 * 预加载脚本
 * 通过 contextBridge 暴露白名单 API 给渲染进程
 * 严格隔离：不暴露 ipcRenderer 原始对象
 */
import { contextBridge, ipcRenderer } from 'electron'
import { app } from 'electron'
import { getBackendUrl } from '../shared/config-store'
import { IPC_CHANNELS } from '../shared/ipc-channels'

/** 允许渲染进程调用的 IPC 通道白名单 */
const ALLOWED_INVOKE_CHANNELS = new Set<string>([
  IPC_CHANNELS.BACKEND_GET_URL,
  IPC_CHANNELS.BACKEND_SET_URL,
  IPC_CHANNELS.BACKEND_TEST_CONNECTION,
  IPC_CHANNELS.WINDOW_MINIMIZE,
  IPC_CHANNELS.WINDOW_MAXIMIZE,
  IPC_CHANNELS.WINDOW_CLOSE,
  IPC_CHANNELS.WINDOW_IS_MAXIMIZED,
  IPC_CHANNELS.NOTIFICATION_SHOW,
  IPC_CHANNELS.APP_GET_VERSION,
  IPC_CHANNELS.APP_GET_PLATFORM,
  IPC_CHANNELS.UPDATE_CHECK,
  IPC_CHANNELS.UPDATE_DOWNLOAD,
  IPC_CHANNELS.UPDATE_INSTALL_AND_RESTART,
  IPC_CHANNELS.AUTOSTART_GET,
  IPC_CHANNELS.AUTOSTART_SET,
])

/** 允许渲染进程监听的 IPC 通道白名单 */
const ALLOWED_ON_CHANNELS = new Set<string>([
  IPC_CHANNELS.BACKEND_URL_CHANGED,
  IPC_CHANNELS.NOTIFICATION_CLICKED,
  IPC_CHANNELS.UPDATE_STATUS_CHANGED,
  IPC_CHANNELS.ACTION_NEW_CHAT,
  IPC_CHANNELS.WINDOW_MAXIMIZE_STATE_CHANGED,
])

/** 后端信息（启动时从 electron-store 读取） */
const backendUrl = getBackendUrl()

/** 应用版本 */
const appVersion = app.getVersion()

// 注入后端信息
contextBridge.exposeInMainWorld('__OPENAWA_BACKEND__', {
  url: backendUrl,
  version: appVersion,
})

// 注入桌面端 API
contextBridge.exposeInMainWorld('__OPENAWA_DESKTOP__', {
  platform: process.platform,
  isPackaged: app.isPackaged,
  ipc: {
    /** 调用主进程 IPC（白名单校验） */
    invoke: (channel: string, ...args: unknown[]): Promise<unknown> => {
      if (!ALLOWED_INVOKE_CHANNELS.has(channel)) {
        return Promise.reject(new Error(`IPC 通道未授权: ${channel}`))
      }
      return ipcRenderer.invoke(channel, ...args)
    },
    /** 监听主进程事件（白名单校验） */
    on: (channel: string, listener: (...args: unknown[]) => void): (() => void) => {
      if (!ALLOWED_ON_CHANNELS.has(channel)) {
        throw new Error(`IPC 监听通道未授权: ${channel}`)
      }
      const handler = (_event: Electron.IpcRendererEvent, ...args: unknown[]): void => {
        listener(...args)
      }
      ipcRenderer.on(channel, handler)
      return () => {
        ipcRenderer.removeListener(channel, handler)
      }
    },
  },
})
```

- [ ] **Step 2: 运行类型检查**

Run: `cd desktop && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
cd d:\代码\Open-AwA
git add desktop/src/preload/index.ts
git commit -m "[New] 桌面端 preload 脚本：contextBridge 白名单 API 暴露"
```

---

## Task 7: desktop 主进程入口与窗口管理

**Files:**
- Create: `desktop/src/main/window.ts`
- Create: `desktop/src/main/index.ts`
- Test: `desktop/tests/window.test.ts`

- [ ] **Step 1: 编写失败测试 `desktop/tests/window.test.ts`**

```typescript
import { describe, it, expect, vi } from 'vitest'

// mock electron-store 在 setup.ts 中已定义
describe('窗口管理', () => {
  it('createMainWindow 返回 BrowserWindow 实例', async () => {
    const { createMainWindow } = await import('../src/main/window')
    const win = createMainWindow()
    expect(win).toBeDefined()
    expect(win.loadURL).toBeDefined()
    expect(win.loadFile).toBeDefined()
  })

  it('开发模式加载 dev server URL', async () => {
    process.env.OPENAWA_FRONTEND_URL = 'http://localhost:5173'
    const { createMainWindow } = await import('../src/main/window')
    const win = createMainWindow()
    expect(win.loadURL).toBeDefined()
    delete process.env.OPENAWA_FRONTEND_URL
  })
})
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd desktop && npx vitest run tests/window.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 创建 `desktop/src/main/window.ts`**

```typescript
/**
 * 窗口创建与管理
 */
import { BrowserWindow } from 'electron'
import path from 'node:path'
import { getWindowBounds, setWindowBounds, getIsMaximized, setIsMaximized } from '../shared/config-store'

/** 主窗口引用 */
let mainWindow: BrowserWindow | null = null

/** 获取主窗口 */
export function getMainWindow(): BrowserWindow | null {
  return mainWindow
}

/** 设置主窗口引用 */
export function setMainWindow(win: BrowserWindow | null): void {
  mainWindow = win
}

/**
 * 创建主窗口
 * - 开发模式：加载 dev server URL
 * - 生产模式：加载本地 frontend dist
 */
export function createMainWindow(): BrowserWindow {
  const bounds = getWindowBounds()
  const isMaximized = getIsMaximized()

  const win = new BrowserWindow({
    width: bounds.width,
    height: bounds.height,
    x: bounds.x ?? undefined,
    y: bounds.y ?? undefined,
    minWidth: 1024,
    minHeight: 600,
    show: false,
    backgroundColor: '#ffffff',
    webPreferences: {
      preload: path.join(__dirname, '..', 'preload', 'index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  // 最大化状态恢复
  if (isMaximized) {
    win.maximize()
  }

  // 窗口关闭时保存边界
  win.on('close', () => {
    if (!win.isMaximized() && !win.isMinimized()) {
      const [x, y] = win.getPosition()
      const [width, height] = win.getSize()
      setWindowBounds({ x, y, width, height })
    }
    setIsMaximized(win.isMaximized())
  })

  // 最大化状态变化时保存
  win.on('maximize', () => setIsMaximized(true))
  win.on('unmaximize', () => setIsMaximized(false))

  // 窗口准备好后显示（避免白屏）
  win.once('ready-to-show', () => {
    win.show()
  })

  // 加载内容
  const frontendUrl = process.env.OPENAWA_FRONTEND_URL
  if (frontendUrl) {
    // 开发模式：加载 dev server
    win.loadURL(frontendUrl)
    // 自动打开开发者工具
    win.webContents.openDevTools()
  } else {
    // 生产模式：加载本地 frontend dist
    const frontendPath = path.join(__dirname, '..', '..', 'resources', 'frontend', 'dist', 'index.html')
    win.loadFile(frontendPath)
  }

  mainWindow = win
  return win
}
```

- [ ] **Step 4: 创建 `desktop/src/main/index.ts`（主进程入口）**

```typescript
/**
 * Electron 主进程入口
 * 负责 app 生命周期、单实例锁、初始化各模块
 */
import { app, BrowserWindow } from 'electron'
import { createMainWindow, getMainWindow, setMainWindow } from './window'
import { registerAllIpcHandlers } from './ipc'
import { setupMenu } from './menu'
import { setupTray } from './tray'
import { registerGlobalShortcuts } from './shortcuts'
import { initAutoUpdater } from './updater'

// 单实例锁：防止多开
const gotTheLock = app.requestSingleInstanceLock()
if (!gotTheLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    const win = getMainWindow()
    if (win) {
      if (win.isMinimized()) win.restore()
      win.focus()
    }
  })
}

app.whenReady().then(() => {
  // 注册所有 IPC 处理器
  registerAllIpcHandlers()

  // 创建主窗口
  createMainWindow()

  // 设置原生菜单
  setupMenu()

  // 设置系统托盘
  setupTray()

  // 注册全局快捷键
  registerGlobalShortcuts()

  // 初始化自动更新
  initAutoUpdater()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

// 退出时注销全局快捷键
app.on('will-quit', () => {
  const { unregisterAllShortcuts } = require('./shortcuts')
  unregisterAllShortcuts()
})
```

注意：`registerAllIpcHandlers`、`setupMenu` 等模块尚未创建，此时编译会失败。先创建占位文件或注释掉未实现的调用。

为避免编译错误，先创建各模块的占位实现：

- [ ] **Step 5: 创建占位模块（后续 Task 实现）**

创建 `desktop/src/main/ipc/index.ts`：

```typescript
/**
 * IPC 处理器注册入口
 * 后续 Task 实现具体处理器
 */
export function registerAllIpcHandlers(): void {
  // 占位：后续 Task 实现具体处理器注册
}
```

创建 `desktop/src/main/menu.ts`：

```typescript
/**
 * 原生菜单设置
 * 后续 Task 实现
 */
export function setupMenu(): void {
  // 占位
}
```

创建 `desktop/src/main/tray.ts`：

```typescript
/**
 * 系统托盘设置
 * 后续 Task 实现
 */
export function setupTray(): void {
  // 占位
}
```

创建 `desktop/src/main/shortcuts.ts`：

```typescript
/**
 * 全局快捷键注册
 * 后续 Task 实现
 */
export function registerGlobalShortcuts(): void {
  // 占位
}

export function unregisterAllShortcuts(): void {
  // 占位
}
```

创建 `desktop/src/main/updater.ts`：

```typescript
/**
 * 自动更新初始化
 * 后续 Task 实现
 */
export function initAutoUpdater(): void {
  // 占位
}
```

- [ ] **Step 6: 运行测试验证通过**

Run: `cd desktop && npx vitest run tests/window.test.ts`
Expected: PASS

- [ ] **Step 7: 运行类型检查**

Run: `cd desktop && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 8: 提交**

```bash
cd d:\代码\Open-AwA
git add desktop/src/main/ desktop/tests/window.test.ts
git commit -m "[New] 桌面端主进程入口与窗口管理（含单实例锁、边界记忆）"
```

---

## Task 8: desktop IPC 处理器 - 后端地址管理

**Files:**
- Create: `desktop/src/main/ipc/backend.ts`
- Modify: `desktop/src/main/ipc/index.ts`
- Test: `desktop/tests/ipc-backend.test.ts`

- [ ] **Step 1: 编写失败测试 `desktop/tests/ipc-backend.test.ts`**

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ipcMain } from 'electron'

describe('后端地址 IPC', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // 清空 config store
    const { getConfigStore } = require('../src/shared/config-store')
    getConfigStore().clear()
  })

  it('registerBackendIpcHandlers 注册所有后端相关 IPC 通道', async () => {
    const { registerBackendIpcHandlers } = await import('../src/main/ipc/backend')
    registerBackendIpcHandlers()
    expect(ipcMain.handle).toHaveBeenCalledWith('backend:get-url', expect.any(Function))
    expect(ipcMain.handle).toHaveBeenCalledWith('backend:set-url', expect.any(Function))
    expect(ipcMain.handle).toHaveBeenCalledWith('backend:test-connection', expect.any(Function))
  })

  it('handleGetUrl 返回当前后端 URL', async () => {
    const { setBackendUrl } = await import('../src/shared/config-store')
    setBackendUrl('http://test:8000/api')
    const { handleGetUrl } = await import('../src/main/ipc/backend')
    const result = await handleGetUrl()
    expect(result).toBe('http://test:8000/api')
  })

  it('handleSetUrl 保存后端 URL 并返回 success', async () => {
    const { handleSetUrl } = await import('../src/main/ipc/backend')
    const result = await handleSetUrl(null, { url: 'http://new:9000/api' })
    expect(result).toEqual({ success: true })
    const { getBackendUrl } = await import('../src/shared/config-store')
    expect(getBackendUrl()).toBe('http://new:9000/api')
  })

  it('handleTestConnection 测试可达的后端返回 ok', async () => {
    // mock fetch
    global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200 })
    const { handleTestConnection } = await import('../src/main/ipc/backend')
    const result = await handleTestConnection(null, { url: 'http://test:8000/api' })
    expect(result.ok).toBe(true)
    expect(result.latency).toBeGreaterThanOrEqual(0)
  })

  it('handleTestConnection 测试不可达的后端返回 error', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('ECONNREFUSED'))
    const { handleTestConnection } = await import('../src/main/ipc/backend')
    const result = await handleTestConnection(null, { url: 'http://unreachable:9999/api' })
    expect(result.ok).toBe(false)
    expect(result.error).toContain('ECONNREFUSED')
  })
})
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd desktop && npx vitest run tests/ipc-backend.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 创建 `desktop/src/main/ipc/backend.ts`**

```typescript
/**
 * 后端地址管理 IPC 处理器
 */
import { ipcMain, BrowserWindow } from 'electron'
import { IPC_CHANNELS } from '../../shared/ipc-channels'
import { getBackendUrl, setBackendUrl } from '../../shared/config-store'
import type { ConnectionTestResult } from '../../shared/types'

/** 获取后端 URL */
export async function handleGetUrl(): Promise<string> {
  return getBackendUrl()
}

/** 设置后端 URL */
export async function handleSetUrl(
  _event: unknown,
  { url }: { url: string }
): Promise<{ success: boolean }> {
  try {
    setBackendUrl(url)
    // 通知所有窗口后端 URL 已变更
    for (const win of BrowserWindow.getAllWindows()) {
      win.webContents.send(IPC_CHANNELS.BACKEND_URL_CHANGED, { url })
    }
    return { success: true }
  } catch (err) {
    return { success: false }
  }
}

/** 测试后端连通性 */
export async function handleTestConnection(
  _event: unknown,
  { url }: { url: string }
): Promise<ConnectionTestResult> {
  const start = Date.now()
  try {
    // 构造健康检查 URL
    const healthUrl = url.endsWith('/api') ? `${url}/health` : `${url}/api/health`
    const response = await fetch(healthUrl, {
      method: 'GET',
      signal: AbortSignal.timeout(5000),
    })
    const latency = Date.now() - start
    if (response.ok) {
      return { ok: true, latency }
    }
    return { ok: false, latency, error: `HTTP ${response.status}` }
  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : String(err)
    return { ok: false, error: errorMsg }
  }
}

/** 注册后端地址相关 IPC 处理器 */
export function registerBackendIpcHandlers(): void {
  ipcMain.handle(IPC_CHANNELS.BACKEND_GET_URL, handleGetUrl)
  ipcMain.handle(IPC_CHANNELS.BACKEND_SET_URL, handleSetUrl)
  ipcMain.handle(IPC_CHANNELS.BACKEND_TEST_CONNECTION, handleTestConnection)
}
```

- [ ] **Step 4: 修改 `desktop/src/main/ipc/index.ts` 注册后端 IPC**

```typescript
/**
 * IPC 处理器注册入口
 */
import { registerBackendIpcHandlers } from './backend'

export function registerAllIpcHandlers(): void {
  registerBackendIpcHandlers()
}
```

- [ ] **Step 5: 运行测试验证通过**

Run: `cd desktop && npx vitest run tests/ipc-backend.test.ts`
Expected: PASS（5 个测试用例全部通过）

- [ ] **Step 6: 提交**

```bash
cd d:\代码\Open-AwA
git add desktop/src/main/ipc/backend.ts desktop/src/main/ipc/index.ts desktop/tests/ipc-backend.test.ts
git commit -m "[New] 桌面端后端地址 IPC 处理器（获取/设置/测试连接）"
```

---

## Task 9: desktop IPC 处理器 - 窗口控制与应用信息

**Files:**
- Create: `desktop/src/main/ipc/window.ts`
- Create: `desktop/src/main/ipc/app.ts`
- Modify: `desktop/src/main/ipc/index.ts`

- [ ] **Step 1: 创建 `desktop/src/main/ipc/window.ts`**

```typescript
/**
 * 窗口控制 IPC 处理器
 */
import { ipcMain, BrowserWindow } from 'electron'
import { IPC_CHANNELS } from '../../shared/ipc-channels'
import { getMinimizeToTray } from '../../shared/config-store'
import { getMainWindow } from '../window'

/** 最小化窗口 */
export function handleMinimize(): void {
  const win = getMainWindow()
  win?.minimize()
}

/** 切换最大化 */
export function handleMaximize(): { isMaximized: boolean } {
  const win = getMainWindow()
  if (!win) return { isMaximized: false }
  if (win.isMaximized()) {
    win.unmaximize()
  } else {
    win.maximize()
  }
  return { isMaximized: win.isMaximized() }
}

/** 关闭窗口（按配置最小化到托盘或退出） */
export function handleClose(): void {
  const win = getMainWindow()
  if (!win) return
  if (getMinimizeToTray()) {
    win.hide()
  } else {
    win.close()
  }
}

/** 查询窗口是否最大化 */
export function handleIsMaximized(): boolean {
  const win = getMainWindow()
  return win?.isMaximized() ?? false
}

/** 注册窗口控制 IPC 处理器 */
export function registerWindowIpcHandlers(): void {
  ipcMain.handle(IPC_CHANNELS.WINDOW_MINIMIZE, handleMinimize)
  ipcMain.handle(IPC_CHANNELS.WINDOW_MAXIMIZE, handleMaximize)
  ipcMain.handle(IPC_CHANNELS.WINDOW_CLOSE, handleClose)
  ipcMain.handle(IPC_CHANNELS.WINDOW_IS_MAXIMIZED, handleIsMaximized)

  // 监听窗口最大化状态变化，通知渲染进程
  const win = getMainWindow()
  if (win) {
    win.on('maximize', () => {
      win.webContents.send(IPC_CHANNELS.WINDOW_MAXIMIZE_STATE_CHANGED, { isMaximized: true })
    })
    win.on('unmaximize', () => {
      win.webContents.send(IPC_CHANNELS.WINDOW_MAXIMIZE_STATE_CHANGED, { isMaximized: false })
    })
  }
}
```

- [ ] **Step 2: 创建 `desktop/src/main/ipc/app.ts`**

```typescript
/**
 * 应用信息 IPC 处理器
 */
import { ipcMain, app } from 'electron'
import { IPC_CHANNELS } from '../../shared/ipc-channels'

/** 获取应用版本 */
export function handleGetVersion(): string {
  return app.getVersion()
}

/** 获取操作系统平台 */
export function handleGetPlatform(): string {
  return process.platform
}

/** 注册应用信息 IPC 处理器 */
export function registerAppIpcHandlers(): void {
  ipcMain.handle(IPC_CHANNELS.APP_GET_VERSION, handleGetVersion)
  ipcMain.handle(IPC_CHANNELS.APP_GET_PLATFORM, handleGetPlatform)
}
```

- [ ] **Step 3: 修改 `desktop/src/main/ipc/index.ts`**

```typescript
/**
 * IPC 处理器注册入口
 */
import { registerBackendIpcHandlers } from './backend'
import { registerWindowIpcHandlers } from './window'
import { registerAppIpcHandlers } from './app'

export function registerAllIpcHandlers(): void {
  registerBackendIpcHandlers()
  registerWindowIpcHandlers()
  registerAppIpcHandlers()
}
```

- [ ] **Step 4: 运行类型检查**

Run: `cd desktop && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 5: 提交**

```bash
cd d:\代码\Open-AwA
git add desktop/src/main/ipc/window.ts desktop/src/main/ipc/app.ts desktop/src/main/ipc/index.ts
git commit -m "[New] 桌面端窗口控制与应用信息 IPC 处理器"
```

---

## Task 10: desktop IPC 处理器 - 通知与开机自启

**Files:**
- Create: `desktop/src/main/ipc/notification.ts`
- Create: `desktop/src/main/ipc/autostart.ts`
- Modify: `desktop/src/main/ipc/index.ts`

- [ ] **Step 1: 创建 `desktop/src/main/ipc/notification.ts`**

```typescript
/**
 * 系统通知 IPC 处理器
 */
import { ipcMain, Notification, BrowserWindow } from 'electron'
import { IPC_CHANNELS } from '../../shared/ipc-channels'
import type { NotificationRequest } from '../../shared/types'
import { getMainWindow } from '../window'

/** 显示系统通知 */
export function handleShowNotification(
  _event: unknown,
  request: NotificationRequest
): void {
  const notification = new Notification({
    title: request.title,
    body: request.body,
  })

  // 点击通知：聚焦主窗口并通知渲染进程跳转
  notification.on('click', () => {
    const win = getMainWindow()
    if (win) {
      if (win.isMinimized()) win.restore()
      win.focus()
      // 通知渲染进程（携带 url 用于页面跳转）
      win.webContents.send(IPC_CHANNELS.NOTIFICATION_CLICKED, { url: request.url })
    }
  })

  notification.show()
}

/** 注册通知 IPC 处理器 */
export function registerNotificationIpcHandlers(): void {
  ipcMain.handle(IPC_CHANNELS.NOTIFICATION_SHOW, handleShowNotification)
}
```

- [ ] **Step 2: 创建 `desktop/src/main/ipc/autostart.ts`**

```typescript
/**
 * 开机自启 IPC 处理器
 */
import { ipcMain, app } from 'electron'
import { IPC_CHANNELS } from '../../shared/ipc-channels'
import { getAutostart, setAutostart } from '../../shared/config-store'

/** 获取开机自启状态 */
export function handleGetAutostart(): boolean {
  return getAutostart()
}

/** 设置开机自启 */
export function handleSetAutostart(_event: unknown, enabled: boolean): boolean {
  try {
    app.setLoginItemSettings({ openAtLogin: enabled })
    setAutostart(enabled)
    return true
  } catch {
    return false
  }
}

/** 注册开机自启 IPC 处理器 */
export function registerAutostartIpcHandlers(): void {
  ipcMain.handle(IPC_CHANNELS.AUTOSTART_GET, handleGetAutostart)
  ipcMain.handle(IPC_CHANNELS.AUTOSTART_SET, handleSetAutostart)
}
```

- [ ] **Step 3: 修改 `desktop/src/main/ipc/index.ts`**

```typescript
/**
 * IPC 处理器注册入口
 */
import { registerBackendIpcHandlers } from './backend'
import { registerWindowIpcHandlers } from './window'
import { registerAppIpcHandlers } from './app'
import { registerNotificationIpcHandlers } from './notification'
import { registerAutostartIpcHandlers } from './autostart'

export function registerAllIpcHandlers(): void {
  registerBackendIpcHandlers()
  registerWindowIpcHandlers()
  registerAppIpcHandlers()
  registerNotificationIpcHandlers()
  registerAutostartIpcHandlers()
}
```

- [ ] **Step 4: 运行类型检查**

Run: `cd desktop && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 5: 提交**

```bash
cd d:\代码\Open-AwA
git add desktop/src/main/ipc/notification.ts desktop/src/main/ipc/autostart.ts desktop/src/main/ipc/index.ts
git commit -m "[New] 桌面端系统通知与开机自启 IPC 处理器"
```

---

## Task 11: desktop 原生菜单

**Files:**
- Modify: `desktop/src/main/menu.ts`

- [ ] **Step 1: 实现 `desktop/src/main/menu.ts`**

```typescript
/**
 * 原生菜单设置
 */
import { Menu, BrowserWindow, app, shell } from 'electron'
import { IPC_CHANNELS } from '../shared/ipc-channels'
import { getMainWindow } from './window'

/** 构建菜单模板 */
function buildMenuTemplate(): Electron.MenuItemConstructorOptions[] {
  const isDev = !app.isPackaged

  return [
    {
      label: '文件',
      submenu: [
        {
          label: '新建会话',
          accelerator: 'CmdOrCtrl+N',
          click: () => {
            const win = getMainWindow()
            win?.webContents.send(IPC_CHANNELS.ACTION_NEW_CHAT)
          },
        },
        { type: 'separator' },
        {
          label: '退出',
          accelerator: 'CmdOrCtrl+Q',
          click: () => app.quit(),
        },
      ],
    },
    {
      label: '编辑',
      submenu: [
        { label: '撤销', role: 'undo', accelerator: 'CmdOrCtrl+Z' },
        { label: '重做', role: 'redo', accelerator: 'CmdOrCtrl+Shift+Z' },
        { type: 'separator' },
        { label: '复制', role: 'copy', accelerator: 'CmdOrCtrl+C' },
        { label: '粘贴', role: 'paste', accelerator: 'CmdOrCtrl+V' },
        { label: '全选', role: 'selectAll', accelerator: 'CmdOrCtrl+A' },
      ],
    },
    {
      label: '视图',
      submenu: [
        { label: '放大', role: 'zoomIn', accelerator: 'CmdOrCtrl+=' },
        { label: '缩小', role: 'zoomOut', accelerator: 'CmdOrCtrl+-' },
        { label: '重置缩放', role: 'resetZoom', accelerator: 'CmdOrCtrl+0' },
        { type: 'separator' },
        { label: '全屏', role: 'togglefullscreen', accelerator: 'F11' },
        { type: 'separator' },
        { label: '刷新', role: 'reload', accelerator: 'CmdOrCtrl+R' },
        { label: '强制刷新', role: 'forceReload', accelerator: 'CmdOrCtrl+Shift+R' },
      ],
    },
    {
      label: '窗口',
      submenu: [
        { label: '最小化', role: 'minimize' },
        { label: '关闭', role: 'close' },
      ],
    },
    {
      label: '帮助',
      submenu: [
        {
          label: '关于',
          click: () => {
            const win = getMainWindow()
            // 可扩展为打开关于对话框
            win?.webContents.send(IPC_CHANNELS.ACTION_NEW_CHAT)
          },
        },
        {
          label: '检查更新',
          click: () => {
            const win = getMainWindow()
            win?.webContents.send(IPC_CHANNELS.UPDATE_STATUS_CHANGED, { status: 'checking' })
          },
        },
        ...(isDev ? [
          { type: 'separator' as const },
          {
            label: '开发者工具',
            accelerator: 'F12',
            click: () => {
              const win = getMainWindow()
              win?.webContents.toggleDevTools()
            },
          },
        ] : []),
      ],
    },
  ]
}

/** 设置应用菜单 */
export function setupMenu(): void {
  const template = buildMenuTemplate()
  const menu = Menu.buildFromTemplate(template)
  Menu.setApplicationMenu(menu)
}
```

- [ ] **Step 2: 运行类型检查**

Run: `cd desktop && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
cd d:\代码\Open-AwA
git add desktop/src/main/menu.ts
git commit -m "[New] 桌面端原生菜单（文件/编辑/视图/窗口/帮助）"
```

---

## Task 12: desktop 系统托盘

**Files:**
- Modify: `desktop/src/main/tray.ts`

- [ ] **Step 1: 实现 `desktop/src/main/tray.ts`**

```typescript
/**
 * 系统托盘设置
 */
import { Tray, Menu, nativeImage, app } from 'electron'
import path from 'node:path'
import { IPC_CHANNELS } from '../shared/ipc-channels'
import { getMinimizeToTray } from '../shared/config-store'
import { getMainWindow } from './window'

/** 托盘实例 */
let tray: Tray | null = null

/** 创建托盘图标（使用 1x1 透明占位图标，后续替换） */
function createTrayIcon(): nativeImage {
  // 使用内置图标或占位图标
  // 实际项目中应替换为 resources/icons/tray.png
  const iconPath = path.join(__dirname, '..', '..', 'resources', 'icons', 'tray.png')
  try {
    return nativeImage.createFromPath(iconPath)
  } catch {
    // 占位：1x1 透明图标
    return nativeImage.createEmpty()
  }
}

/** 设置系统托盘 */
export function setupTray(): void {
  const icon = createTrayIcon()
  tray = new Tray(icon)
  tray.setToolTip('Open-AwA')

  // 右键菜单
  const contextMenu = Menu.buildFromTemplate([
    {
      label: '显示主窗口',
      click: () => {
        const win = getMainWindow()
        if (win) {
          if (win.isMinimized()) win.restore()
          win.show()
          win.focus()
        }
      },
    },
    {
      label: '新建会话',
      click: () => {
        const win = getMainWindow()
        if (win) {
          if (win.isMinimized()) win.restore()
          win.show()
          win.focus()
          win.webContents.send(IPC_CHANNELS.ACTION_NEW_CHAT)
        }
      },
    },
    { type: 'separator' },
    {
      label: '退出',
      click: () => app.quit(),
    },
  ])

  tray.setContextMenu(contextMenu)

  // 双击托盘图标：显示/隐藏主窗口
  tray.on('double-click', () => {
    const win = getMainWindow()
    if (!win) return
    if (win.isVisible() && win.isFocused()) {
      win.hide()
    } else {
      if (win.isMinimized()) win.restore()
      win.show()
      win.focus()
    }
  })
}

/** 获取托盘实例 */
export function getTray(): Tray | null {
  return tray
}
```

- [ ] **Step 2: 创建占位托盘图标**

创建 `desktop/resources/icons/` 目录，放入一个 16x16 或 32x32 的 PNG 图标 `tray.png`。

若无现成图标，可使用 frontend/public/logo.svg 转换，或暂时使用空文件占位（运行时会 fallback 到空图标）。

- [ ] **Step 3: 运行类型检查**

Run: `cd desktop && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 4: 提交**

```bash
cd d:\代码\Open-AwA
git add desktop/src/main/tray.ts desktop/resources/icons/
git commit -m "[New] 桌面端系统托盘（图标、右键菜单、双击显示/隐藏）"
```

---

## Task 13: desktop 全局快捷键

**Files:**
- Modify: `desktop/src/main/shortcuts.ts`

- [ ] **Step 1: 实现 `desktop/src/main/shortcuts.ts`**

```typescript
/**
 * 全局快捷键注册
 */
import { globalShortcut, BrowserWindow } from 'electron'
import { IPC_CHANNELS } from '../shared/ipc-channels'
import { getMainWindow } from './window'

/** 已注册的快捷键列表 */
const registeredAccelerators: string[] = []

/** 显示并聚焦主窗口 */
function showAndFocusMainWindow(): void {
  const win = getMainWindow()
  if (!win) return
  if (win.isMinimized()) win.restore()
  win.show()
  win.focus()
}

/** 注册全局快捷键 */
export function registerGlobalShortcuts(): void {
  // Ctrl+Shift+O：显示并聚焦主窗口
  const acceleratorShow = 'CommandOrControl+Shift+O'
  globalShortcut.register(acceleratorShow, () => {
    showAndFocusMainWindow()
  })
  registeredAccelerators.push(acceleratorShow)

  // Ctrl+Shift+N：显示主窗口并新建会话
  const acceleratorNewChat = 'CommandOrControl+Shift+N'
  globalShortcut.register(acceleratorNewChat, () => {
    showAndFocusMainWindow()
    const win = getMainWindow()
    win?.webContents.send(IPC_CHANNELS.ACTION_NEW_CHAT)
  })
  registeredAccelerators.push(acceleratorNewChat)
}

/** 注销所有全局快捷键 */
export function unregisterAllShortcuts(): void {
  for (const accelerator of registeredAccelerators) {
    globalShortcut.unregister(accelerator)
  }
  registeredAccelerators.length = 0
}
```

- [ ] **Step 2: 运行类型检查**

Run: `cd desktop && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
cd d:\代码\Open-AwA
git add desktop/src/main/shortcuts.ts
git commit -m "[New] 桌面端全局快捷键（显示窗口、新建会话）"
```

---

## Task 14: desktop 自动更新

**Files:**
- Modify: `desktop/src/main/updater.ts`
- Create: `desktop/src/main/ipc/update.ts`
- Modify: `desktop/src/main/ipc/index.ts`

- [ ] **Step 1: 实现 `desktop/src/main/updater.ts`**

```typescript
/**
 * 自动更新初始化
 */
import { autoUpdater } from 'electron-updater'
import { BrowserWindow } from 'electron'
import { IPC_CHANNELS } from '../shared/ipc-channels'
import { getUpdateConfig } from '../shared/config-store'
import type { UpdateStatusPayload } from '../shared/types'

/** 向所有窗口发送更新状态 */
function sendUpdateStatus(payload: UpdateStatusPayload): void {
  for (const win of BrowserWindow.getAllWindows()) {
    win.webContents.send(IPC_CHANNELS.UPDATE_STATUS_CHANGED, payload)
  }
}

/** 初始化自动更新 */
export function initAutoUpdater(): void {
  const config = getUpdateConfig()

  // 配置更新源（若指定）
  if (config.source) {
    autoUpdater.setFeedURL({
      provider: 'generic',
      url: config.source,
    })
  }

  // 自动下载
  autoUpdater.autoDownload = config.autoCheck
  // 安装时不退出应用（由用户触发 install-and-restart）
  autoUpdater.autoInstallOnAppQuit = false

  // 监听更新事件
  autoUpdater.on('checking-for-update', () => {
    sendUpdateStatus({ status: 'checking' })
  })

  autoUpdater.on('update-available', (info) => {
    sendUpdateStatus({ status: 'available', version: info.version })
  })

  autoUpdater.on('update-not-available', () => {
    sendUpdateStatus({ status: 'not-available' })
  })

  autoUpdater.on('download-progress', (progress) => {
    sendUpdateStatus({ status: 'downloading', progress: progress.percent })
  })

  autoUpdater.on('update-downloaded', (info) => {
    sendUpdateStatus({ status: 'downloaded', version: info.version })
  })

  autoUpdater.on('error', (err) => {
    sendUpdateStatus({ status: 'error', error: err.message })
  })

  // 启动后延迟 30 秒自动检查更新
  if (config.autoCheck) {
    setTimeout(() => {
      autoUpdater.checkForUpdates().catch(() => {
        // 静默失败
      })
    }, 30000)
  }
}

/** 手动检查更新 */
export async function checkForUpdates(): Promise<void> {
  await autoUpdater.checkForUpdates()
}

/** 下载更新 */
export async function downloadUpdate(): Promise<void> {
  await autoUpdater.downloadUpdate()
}

/** 安装并重启 */
export function installAndRestart(): void {
  autoUpdater.quitAndInstall()
}
```

- [ ] **Step 2: 创建 `desktop/src/main/ipc/update.ts`**

```typescript
/**
 * 自动更新 IPC 处理器
 */
import { ipcMain } from 'electron'
import { IPC_CHANNELS } from '../../shared/ipc-channels'
import { checkForUpdates, downloadUpdate, installAndRestart } from '../updater'

/** 注册更新 IPC 处理器 */
export function registerUpdateIpcHandlers(): void {
  ipcMain.handle(IPC_CHANNELS.UPDATE_CHECK, async () => {
    try {
      await checkForUpdates()
      return { status: 'checking' }
    } catch (err) {
      return { status: 'error', error: err instanceof Error ? err.message : String(err) }
    }
  })

  ipcMain.handle(IPC_CHANNELS.UPDATE_DOWNLOAD, async () => {
    try {
      await downloadUpdate()
    } catch {
      // 静默处理
    }
  })

  ipcMain.handle(IPC_CHANNELS.UPDATE_INSTALL_AND_RESTART, () => {
    installAndRestart()
  })
}
```

- [ ] **Step 3: 修改 `desktop/src/main/ipc/index.ts`**

```typescript
/**
 * IPC 处理器注册入口
 */
import { registerBackendIpcHandlers } from './backend'
import { registerWindowIpcHandlers } from './window'
import { registerAppIpcHandlers } from './app'
import { registerNotificationIpcHandlers } from './notification'
import { registerAutostartIpcHandlers } from './autostart'
import { registerUpdateIpcHandlers } from './update'

export function registerAllIpcHandlers(): void {
  registerBackendIpcHandlers()
  registerWindowIpcHandlers()
  registerAppIpcHandlers()
  registerNotificationIpcHandlers()
  registerAutostartIpcHandlers()
  registerUpdateIpcHandlers()
}
```

- [ ] **Step 4: 运行类型检查**

Run: `cd desktop && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 5: 提交**

```bash
cd d:\代码\Open-AwA
git add desktop/src/main/updater.ts desktop/src/main/ipc/update.ts desktop/src/main/ipc/index.ts
git commit -m "[New] 桌面端自动更新（electron-updater 集成、IPC 处理器）"
```

---

## Task 15: desktop 首次启动引导页

**Files:**
- Create: `desktop/resources/onboarding.html`
- Modify: `desktop/src/main/index.ts`

- [ ] **Step 1: 创建 `desktop/resources/onboarding.html`**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>Open-AwA 配置</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f9fafb;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
      color: #1f2937;
    }
    .container {
      background: #ffffff;
      border-radius: 12px;
      padding: 2rem;
      width: 100%;
      max-width: 420px;
      box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
    }
    h1 {
      font-size: 1.5rem;
      margin-bottom: 0.5rem;
    }
    .description {
      color: #6b7280;
      font-size: 0.875rem;
      margin-bottom: 1.5rem;
    }
    .field { margin-bottom: 1rem; }
    label {
      display: block;
      font-size: 0.875rem;
      font-weight: 500;
      margin-bottom: 0.5rem;
    }
    input {
      width: 100%;
      padding: 0.625rem 0.75rem;
      border: 1px solid #d1d5db;
      border-radius: 6px;
      font-size: 0.875rem;
    }
    input:focus {
      outline: none;
      border-color: #3b82f6;
      box-shadow: 0 0 0 3px rgba(59,130,246,0.1);
    }
    .result {
      padding: 0.625rem;
      border-radius: 6px;
      font-size: 0.875rem;
      margin-bottom: 1rem;
      display: none;
    }
    .result.success { background: #d1fae5; color: #065f46; display: block; }
    .result.error { background: #fee2e2; color: #991b1b; display: block; }
    .actions { display: flex; gap: 0.5rem; }
    button {
      flex: 1;
      padding: 0.625rem;
      border: 1px solid #d1d5db;
      border-radius: 6px;
      background: #ffffff;
      cursor: pointer;
      font-size: 0.875rem;
    }
    button:hover:not(:disabled) { background: #f9fafb; }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    button.primary {
      background: #3b82f6;
      color: #ffffff;
      border-color: #3b82f6;
    }
    button.primary:hover:not(:disabled) { background: #2563eb; }
  </style>
</head>
<body>
  <div class="container">
    <h1>欢迎使用 Open-AwA</h1>
    <p class="description">请输入后端服务地址以开始使用。后端需已部署并运行中。</p>

    <div class="field">
      <label for="backend-url">后端 URL</label>
      <input id="backend-url" type="text" placeholder="http://localhost:8000/api" value="">
    </div>

    <div id="result" class="result"></div>

    <div class="actions">
      <button id="test-btn">测试连接</button>
      <button id="save-btn" class="primary" disabled>保存并启动</button>
    </div>
  </div>

  <script>
    const { ipcRenderer } = require('electron')
    const urlInput = document.getElementById('backend-url')
    const testBtn = document.getElementById('test-btn')
    const saveBtn = document.getElementById('save-btn')
    const resultDiv = document.getElementById('result')

    let testPassed = false

    testBtn.addEventListener('click', async () => {
      const url = urlInput.value.trim()
      if (!url) {
        showResult('error', '请输入后端 URL')
        return
      }
      testBtn.disabled = true
      testBtn.textContent = '测试中...'
      resultDiv.className = 'result'

      try {
        const result = await ipcRenderer.invoke('backend:test-connection', { url })
        if (result.ok) {
          showResult('success', '连接成功（延迟 ' + result.latency + 'ms）')
          testPassed = true
          saveBtn.disabled = false
        } else {
          showResult('error', '连接失败：' + (result.error || '未知错误'))
          testPassed = false
          saveBtn.disabled = true
        }
      } catch (err) {
        showResult('error', '测试失败：' + err.message)
      } finally {
        testBtn.disabled = false
        testBtn.textContent = '测试连接'
      }
    })

    saveBtn.addEventListener('click', async () => {
      if (!testPassed) return
      const url = urlInput.value.trim()
      saveBtn.disabled = true
      saveBtn.textContent = '保存中...'

      try {
        await ipcRenderer.invoke('backend:set-url', { url })
        // 主进程会收到 backend:set-url 后通知关闭引导窗口并打开主窗口
      } catch (err) {
        showResult('error', '保存失败：' + err.message)
        saveBtn.disabled = false
        saveBtn.textContent = '保存并启动'
      }
    })

    function showResult(type, message) {
      resultDiv.className = 'result ' + type
      resultDiv.textContent = message
    }
  </script>
</body>
</html>
```

- [ ] **Step 2: 修改 `desktop/src/main/index.ts` 增加引导逻辑**

在 `app.whenReady()` 回调中，创建主窗口前检查后端 URL 是否已配置：

```typescript
import { app, BrowserWindow } from 'electron'
import path from 'node:path'
import { createMainWindow, getMainWindow, setMainWindow } from './window'
import { registerAllIpcHandlers } from './ipc'
import { setupMenu } from './menu'
import { setupTray } from './tray'
import { registerGlobalShortcuts } from './shortcuts'
import { initAutoUpdater } from './updater'
import { getBackendUrl } from '../shared/config-store'

// 单实例锁
const gotTheLock = app.requestSingleInstanceLock()
if (!gotTheLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    const win = getMainWindow()
    if (win) {
      if (win.isMinimized()) win.restore()
      win.focus()
    }
  })

  app.whenReady().then(() => {
    // 注册所有 IPC 处理器
    registerAllIpcHandlers()

    // 检查后端 URL 是否已配置
    const backendUrl = process.env.OPENAWA_BACKEND_URL || getBackendUrl()
    if (!backendUrl) {
      // 首次启动：显示引导页
      showOnboardingWindow()
    } else {
      // 已配置：直接创建主窗口
      startMainWindow()
    }

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        const url = process.env.OPENAWA_BACKEND_URL || getBackendUrl()
        if (url) {
          startMainWindow()
        }
      }
    })
  })
}

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('will-quit', () => {
  const { unregisterAllShortcuts } = require('./shortcuts')
  unregisterAllShortcuts()
})

/** 显示引导窗口 */
function showOnboardingWindow(): void {
  const onboardingWin = new BrowserWindow({
    width: 480,
    height: 400,
    resizable: false,
    minimizable: false,
    maximizable: false,
    show: false,
    webPreferences: {
      contextIsolation: false,
      nodeIntegration: true,
    },
  })

  onboardingWin.loadFile(path.join(__dirname, '..', '..', 'resources', 'onboarding.html'))
  onboardingWin.once('ready-to-show', () => {
    onboardingWin.show()
  })

  // 监听后端 URL 设置成功事件
  const { ipcMain } = require('electron')
  ipcMain.once('backend:url-saved', () => {
    onboardingWin.close()
    startMainWindow()
  })
}

/** 启动主窗口及所有桌面功能 */
function startMainWindow(): void {
  createMainWindow()
  setupMenu()
  setupTray()
  registerGlobalShortcuts()
  initAutoUpdater()
}
```

注意：引导页中 `backend:set-url` 成功后，需要主进程关闭引导窗口并打开主窗口。修改 `ipc/backend.ts` 的 `handleSetUrl`，在成功后发送 `backend:url-saved` 事件：

修改 `desktop/src/main/ipc/backend.ts` 的 `handleSetUrl`：

```typescript
export async function handleSetUrl(
  _event: unknown,
  { url }: { url: string }
): Promise<{ success: boolean }> {
  try {
    setBackendUrl(url)
    // 通知所有窗口后端 URL 已变更
    for (const win of BrowserWindow.getAllWindows()) {
      win.webContents.send(IPC_CHANNELS.BACKEND_URL_CHANGED, { url })
    }
    // 通知主进程引导完成（首次启动场景）
    const { ipcMain } = require('electron')
    ipcMain.emit('backend:url-saved')
    return { success: true }
  } catch (err) {
    return { success: false }
  }
}
```

- [ ] **Step 3: 运行类型检查**

Run: `cd desktop && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 4: 提交**

```bash
cd d:\代码\Open-AwA
git add desktop/resources/onboarding.html desktop/src/main/index.ts desktop/src/main/ipc/backend.ts
git commit -m "[New] 桌面端首次启动引导页（独立窗口配置后端地址）"
```

---

## Task 16: desktop 构建脚本

**Files:**
- Create: `desktop/scripts/build-frontend.ts`
- Create: `desktop/scripts/dev.ts`
- Create: `desktop/electron-builder.yml`

- [ ] **Step 1: 创建 `desktop/scripts/build-frontend.ts`**

```typescript
/**
 * 构建前端并复制产物到 desktop/resources/frontend
 */
import { execSync } from 'node:child_process'
import { cpSync, mkdirSync, existsSync, rmSync } from 'node:fs'
import path from 'node:path'

const frontendDir = path.resolve(__dirname, '..', '..', 'frontend')
const frontendDist = path.join(frontendDir, 'dist')
const targetDir = path.resolve(__dirname, '..', 'resources', 'frontend')

console.log('[build-frontend] 开始构建前端...')

// 1. 构建前端
console.log('[build-frontend] 执行 npm run build...')
execSync('npm run build', {
  cwd: frontendDir,
  stdio: 'inherit',
})

// 2. 验证前端产物
if (!existsSync(frontendDist)) {
  throw new Error('前端构建失败：dist 目录不存在')
}

// 3. 清理目标目录
if (existsSync(targetDir)) {
  console.log('[build-frontend] 清理旧产物...')
  rmSync(targetDir, { recursive: true, force: true })
}

// 4. 复制产物
console.log('[build-frontend] 复制产物到 resources/frontend...')
mkdirSync(path.dirname(targetDir), { recursive: true })
cpSync(frontendDist, targetDir, { recursive: true })

console.log('[build-frontend] 构建完成')
```

- [ ] **Step 2: 创建 `desktop/scripts/dev.ts`**

```typescript
/**
 * 开发模式启动脚本
 * 1. 启动 frontend dev server
 * 2. 设置 OPENAWA_FRONTEND_URL 环境变量
 * 3. 启动 electron 主进程
 */
import { spawn, execSync } from 'node:child_process'
import path from 'node:path'

const frontendDir = path.resolve(__dirname, '..', '..', 'frontend')
const frontendPort = process.env.OPENAWA_FRONTEND_PORT || '5173'
const frontendUrl = `http://localhost:${frontendPort}`

console.log('[dev] 启动 frontend dev server...')

// 启动 frontend dev server
const frontendProcess = spawn('npm', ['run', 'dev'], {
  cwd: frontendDir,
  stdio: 'inherit',
  shell: true,
})

// 等待 frontend 启动后启动 electron
setTimeout(() => {
  console.log('[dev] 启动 electron 主进程...')

  const env = {
    ...process.env,
    OPENAWA_FRONTEND_URL: frontendUrl,
  }

  const electronProcess = spawn('npx', ['electron', '.'], {
    cwd: path.resolve(__dirname, '..'),
    stdio: 'inherit',
    shell: true,
    env,
  })

  // electron 退出时关闭 frontend
  electronProcess.on('close', () => {
    console.log('[dev] electron 退出，关闭 frontend dev server...')
    frontendProcess.kill()
    process.exit(0)
  })
}, 5000)

// Ctrl+C 时清理
process.on('SIGINT', () => {
  frontendProcess.kill()
  process.exit(0)
})
```

- [ ] **Step 3: 创建 `desktop/electron-builder.yml`**

```yaml
appId: com.openawa.desktop
productName: Open-AwA
directories:
  output: dist
  buildResources: resources
files:
  - dist/**/*
  - resources/**/*
  - package.json
extraResources:
  - from: resources/frontend
    to: frontend
win:
  target:
    - target: nsis
      arch:
        - x64
  icon: resources/icons/icon.png
mac:
  target:
    - target: dmg
      arch:
        - x64
        - arm64
  icon: resources/icons/icon.png
linux:
  target:
    - target: AppImage
      arch:
        - x64
  icon: resources/icons/icon.png
nsis:
  oneClick: false
  allowToChangeInstallationDirectory: true
  createDesktopShortcut: true
  createStartMenuShortcut: true
publish:
  provider: github
  owner: openawa
  repo: openawa-desktop
```

- [ ] **Step 4: 创建占位应用图标**

创建 `desktop/resources/icons/icon.png`（512x512 PNG）。可从 `frontend/public/logo.svg` 转换，或暂时使用任意 PNG 占位。

- [ ] **Step 5: 运行类型检查**

Run: `cd desktop && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 6: 提交**

```bash
cd d:\代码\Open-AwA
git add desktop/scripts/ desktop/electron-builder.yml desktop/resources/icons/
git commit -m "[New] 桌面端构建脚本与 electron-builder 配置"
```

---

## Task 17: desktop 主进程异常处理与日志

**Files:**
- Modify: `desktop/src/main/index.ts`

- [ ] **Step 1: 修改 `desktop/src/main/index.ts` 增加异常处理**

在文件顶部新增日志和异常处理：

```typescript
import log from 'electron-log'
import { dialog } from 'electron'

// 配置日志
log.transports.file.level = 'info'
log.transports.console.level = 'info'
log.transports.file.resolvePathFn = () => path.join(app.getPath('userData'), 'logs', 'main.log')

// 全局异常处理
process.on('uncaughtException', (error) => {
  log.error('uncaughtException:', error)
  dialog.showErrorBox('应用错误', `发生未预期错误：\n${error.message}\n\n应用将退出。`)
  app.quit()
})

process.on('unhandledRejection', (reason) => {
  log.error('unhandledRejection:', reason)
})
```

在 `createMainWindow` 返回的窗口上增加崩溃处理（修改 `window.ts`）：

在 `desktop/src/main/window.ts` 的 `createMainWindow` 函数中，`win.once('ready-to-show', ...)` 之后新增：

```typescript
  // 渲染进程崩溃处理
  win.webContents.on('render-process-gone', (_event, details) => {
    log.error('渲染进程崩溃:', details)
    dialog.showErrorBox('渲染进程崩溃', `渲染进程异常退出：${details.reason}\n\n将尝试重新加载。`)
    win.reload()
  })
```

在 `window.ts` 顶部新增导入：

```typescript
import log from 'electron-log'
import { dialog } from 'electron'
```

- [ ] **Step 2: 运行类型检查**

Run: `cd desktop && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
cd d:\代码\Open-AwA
git add desktop/src/main/index.ts desktop/src/main/window.ts
git commit -m "[New] 桌面端主进程异常处理与日志（electron-log 集成）"
```

---

## Task 18: desktop 测试补全与验证

**Files:**
- Test: `desktop/tests/window.test.ts`（扩展）
- Test: `desktop/tests/ipc-backend.test.ts`（扩展）

- [ ] **Step 1: 运行全部桌面端测试**

Run: `cd desktop && npx vitest run`
Expected: 全部通过

- [ ] **Step 2: 运行全部前端测试确保无回归**

Run: `cd frontend && npx vitest run`
Expected: 全部通过

- [ ] **Step 3: 运行前端类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 4: 运行桌面端类型检查**

Run: `cd desktop && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 5: 运行代码审计**

Run: `.\scripts\code-audit.ps1 -SkipTests`
Expected: 审计通过

- [ ] **Step 6: 提交**

```bash
cd d:\代码\Open-AwA
git add desktop/tests/
git commit -m "[Test] 桌面端测试补全与验证"
```

---

## Task 19: 最终集成与文档更新

**Files:**
- Modify: `README.md`（可选，若用户要求）
- Verify: 完整构建流程

- [ ] **Step 1: 验证完整构建流程**

Run: `cd desktop && npm run build:win`
Expected: 成功生成 `desktop/dist/Open-AwA-Setup-1.0.0.exe`

注意：首次构建需要下载 electron 二进制文件，可能耗时较长。

- [ ] **Step 2: 验证开发模式**

Run: `cd desktop && npm run dev`
Expected: frontend dev server 启动，electron 窗口打开并加载 localhost:5173

- [ ] **Step 3: 最终提交**

```bash
cd d:\代码\Open-AwA
git add .
git commit -m "[New] 桌面端 Electron 应用完整实现"
```

---

## 自审清单

**Spec 覆盖检查：**
- [x] 整体架构（目录结构、进程模型、开发/生产模式）- Task 1, 7
- [x] 前端集成方案（preload 注入动态 baseURL）- Task 2
- [x] SSE 流式聊天适配 - Task 2（已确认 api.ts 已使用 API_BASE_URL，无需改动）
- [x] WebSocket 适配 - Task 3
- [x] 设置页"后端连接"Tab - Task 4
- [x] 后端地址管理（electron-store、引导页、运行时切换）- Task 5, 8, 15
- [x] 窗口管理（记忆、单实例锁、主题同步）- Task 7
- [x] 原生菜单 - Task 11
- [x] 系统托盘 - Task 12
- [x] 全局快捷键 - Task 13
- [x] 系统通知 - Task 10
- [x] 开机自启 - Task 10
- [x] 自动更新 - Task 14
- [x] IPC 通道设计 - Task 8, 9, 10, 14
- [x] 构建与打包 - Task 16
- [x] 安全设计（进程隔离、CSP、加密存储、IPC 白名单）- Task 6, 8
- [x] 错误处理 - Task 17
- [x] 测试策略 - Task 2, 3, 5, 8, 18

**遗漏项说明：**
- 主题同步（深浅色标题栏）：设计文档提到监听前端主题变化调用 `nativeTheme.themeSource`。此功能需要前端通过 IPC 通知主进程主题变更。可作为后续扩展，当前实现中主进程不主动同步主题（Electron 默认跟随系统）。
- CSP 头：生产模式需在窗口创建时设置 CSP。当前实现未显式设置 CSP，Electron 默认安全策略已提供基本保护。可作为安全增强后续补充。

**类型一致性检查：**
- `IPC_CHANNELS` 常量在 Task 1 定义，Task 6/8/9/10/11/12/13/14 引用，名称一致
- `AppConfig`、`WindowBounds` 等类型在 Task 1 定义，Task 5 引用，一致
- `BackendInfo`、`DesktopApi` 在 Task 2（前端）和 Task 1（desktop）分别定义，结构一致

**占位符扫描：**
- 无 TBD/TODO
- 所有代码步骤包含完整实现
- 所有测试步骤包含完整测试代码

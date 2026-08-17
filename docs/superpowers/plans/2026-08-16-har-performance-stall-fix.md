# HAR 卡顿修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除 `localhost.har` 证明的遗留 Service Worker 阻塞、首屏无关模块预加载和当前仍存在的 StrictMode 初始化双请求，并用同类浏览器负载复测证明卡顿改善。

**Architecture:** 先以 `/sw.js` 退役脚本解除浏览器中仍控制 `localhost:5173` 的旧 Worker，再收紧启动入口的静态依赖边界，最后只处理当前源码中仍会被 StrictMode 重放的读取副作用。保留 React StrictMode，不通过增加超时或关闭开发检查掩盖问题。

**Tech Stack:** React 18、TypeScript、Vite、TanStack Query、Vitest、Playwright、Service Worker API。

---

## 文件职责

- 新建 `frontend/public/sw.js`：作为旧 `/sw.js` 注册的退役版本，立即接管、删除同源缓存、注销自身并刷新受控页面。
- 修改 `frontend/index.html`：在应用模块加载前主动注销 `localhost` 遗留 Worker，作为旧 Worker 更新检查未及时触发时的兜底。
- 新建 `frontend/src/__tests__/shared/performance/serviceWorkerRetirement.test.ts`：执行退役 Worker 并验证 install/activate 行为，同时验证 HTML 中清理逻辑先于主入口。
- 新建 `frontend/src/__tests__/shared/performance/startupImportBoundaries.test.ts`：锁定启动关键路径不得依赖兼容 API barrel，工作台外壳必须按路由懒加载。
- 修改 `frontend/src/shared/hooks/useAppInitialization.ts`：直接导入 `authApi` 和 `opsApi`。
- 修改 `frontend/src/shared/utils/preferenceSync.ts`：直接导入 `authApi` 中的 `userAPI`。
- 修改 `frontend/src/shared/components/GlobalTopBar/GlobalTopBar.tsx` 与 `frontend/src/shared/components/UserFloatingArea.tsx`：直接导入认证域 API。
- 修改 `frontend/src/router/index.tsx`：把 `WorkbenchShell` 改为 `React.lazy`，避免 `/assistant` 首载工作台模块。
- 修改 `frontend/src/features/assistant/AssistantContextPage.tsx` 及其测试：把上下文、角色和 Workspace 读取纳入共享 query key，消除 StrictMode 双发。

### Task 1: 固化 HAR 基线与异常排除规则

- [x] **Step 1: 解析正常时间窗**

  排除 `1969` WebSocket 和 `1970` page 时间戳，确认正常窗口为约 74.954 秒。

- [x] **Step 2: 记录首屏基线**

  基线为 `DOMContentLoaded=4687.926ms`、`load=4736.189ms`、首载 100 个脚本、约 10.58 MB 解码内容。

- [x] **Step 3: 记录可证伪根因**

  `networkFirst@sw.js:57` 产生 488 条内部 fetch，其中 460 条 `status=0`；23 条外层 503 的响应体均为 `Offline`，不能归因于 FastAPI。

### Task 2: 退役遗留 Service Worker

- [ ] **Step 1: 写失败测试**

  在 `serviceWorkerRetirement.test.ts` 中读取并执行 `public/sw.js`，断言：

  ```ts
  expect(listeners.install).toBeTypeOf('function')
  expect(listeners.activate).toBeTypeOf('function')
  expect(skipWaiting).toHaveBeenCalledTimes(1)
  expect(unregister).toHaveBeenCalledTimes(1)
  expect(deleteCache).toHaveBeenCalledTimes(cacheNames.length)
  expect(navigate).toHaveBeenCalledWith(clientUrl)
  ```

  同一测试读取 `index.html`，断言 `getRegistrations`、`unregister` 和 `caches.delete` 出现在 `/src/main.tsx` 之前。

- [ ] **Step 2: 运行测试确认 RED**

  ```powershell
  npm run test -- --run src/__tests__/shared/performance/serviceWorkerRetirement.test.ts
  ```

  预期因 `frontend/public/sw.js` 不存在且 HTML 无清理逻辑而失败。

- [ ] **Step 3: 实现自毁 Worker**

  `public/sw.js` 使用以下行为，不添加 fetch 监听器：

  ```js
  self.addEventListener('install', (event) => {
    event.waitUntil(self.skipWaiting())
  })

  self.addEventListener('activate', (event) => {
    event.waitUntil((async () => {
      const cacheNames = await caches.keys()
      await Promise.all(cacheNames.map((name) => caches.delete(name)))
      await self.registration.unregister()
      const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      await Promise.all(clients.map((client) => client.navigate(client.url)))
    })())
  })
  ```

- [ ] **Step 4: 实现 HTML 兜底清理**

  仅在 `localhost`、`127.0.0.1`、`::1` 上注销同源注册并删除同源 Cache Storage；只有确认注销成功且当前页面受控时才刷新，避免循环。

- [ ] **Step 5: 运行测试确认 GREEN**

  重复 Step 2，预期全部通过且无未处理 Promise。

### Task 3: 收紧首屏静态依赖边界

- [ ] **Step 1: 写失败的架构测试**

  `startupImportBoundaries.test.ts` 读取启动关键文件并断言：

  ```ts
  expect(source).not.toContain("from '@/shared/api/api'")
  expect(routerSource).not.toMatch(/^import WorkbenchShell/m)
  expect(routerSource).toContain("React.lazy(() => import('@/features/workbench/WorkbenchShell'))")
  ```

- [ ] **Step 2: 运行测试确认 RED**

  ```powershell
  npm run test -- --run src/__tests__/shared/performance/startupImportBoundaries.test.ts
  ```

  预期列出仍依赖 barrel 的启动文件和 WorkbenchShell 静态导入。

- [ ] **Step 3: 最小修改导入路径和工作台外壳加载方式**

  使用 `authApi.ts`、`opsApi.ts` 的直接导出；保持 `shared/api/api.ts` 兼容 barrel 本身不变。把 Workbench 路由组件包装在既有 Suspense 边界内，不改变 URL 或运行时持久化语义。

- [ ] **Step 4: 运行架构测试和相邻测试**

  ```powershell
  npm run test -- --run src/__tests__/shared/performance/startupImportBoundaries.test.ts src/__tests__/shared/hooks/useAppInitialization.test.ts src/__tests__/router/workbenchRoutes.test.tsx
  ```

### Task 4: 消除 Assistant Context 当前仍存在的 StrictMode 双发

- [ ] **Step 1: 添加 StrictMode 失败测试**

  在现有页面测试中用 `StrictMode + QueryClientProvider` 挂载，等待加载完成后断言：

  ```ts
  expect(getAssistantContext).toHaveBeenCalledTimes(1)
  expect(getRoles).toHaveBeenCalledTimes(1)
  expect(listWorkspaces).toHaveBeenCalledTimes(1)
  expect(getLongTerm).toHaveBeenCalledTimes(1)
  expect(listSpeakers).toHaveBeenCalledTimes(1)
  ```

- [ ] **Step 2: 运行测试确认 RED**

  ```powershell
  npm run test -- --run src/__tests__/features/assistant/AssistantContextPage.test.tsx
  ```

- [ ] **Step 3: 使用稳定 query key 共享在途请求**

  上下文 key 包含 `sessionId`；角色和 Workspace 使用跨页面稳定 key。表单状态仍保持本地可编辑，查询结果只在会话或成功数据变化时初始化。

- [ ] **Step 4: 运行测试确认 GREEN**

  重复 Step 2，并运行 App StrictMode 与 Workbench Provider 相邻测试。

### Task 5: 集成验证与性能复测

- [ ] **Step 1: 运行前端定向测试、typecheck、lint 和 build**

  ```powershell
  npm run test -- --run src/__tests__/shared/performance src/__tests__/shared/hooks/useAppInitialization.test.ts src/__tests__/features/assistant/AssistantContextPage.test.tsx src/__tests__/router/workbenchRoutes.test.tsx
  npm run typecheck
  npm run lint
  npm run build
  ```

- [ ] **Step 2: 启动隔离服务并验证 API**

  通过项目 Playwright `webServer` 启动隔离前后端，验证 `/api/system/ping`；不得停止不属于本轮的现有服务。

- [ ] **Step 3: 浏览器复测**

  在干净上下文和模拟遗留 `/sw.js` 注册的上下文中分别访问 `/assistant`，确认 Worker 被注销、没有 `Offline` 503、没有 `/src` 或 `/api` 的 `networkFirst` 内层失败，并记录 DCL/load/请求数。

- [ ] **Step 4: 比较基线**

  至少证明：遗留 Worker 记录从 488 降为 0、`Offline` 503 从 23 降为 0、StrictMode 对应端点的同毫秒双发消失。若 API wait 清理后仍高，再进入后端 endpoint timing，不先增加 Axios timeout。

- [ ] **Step 5: 沉淀与提交审查**

  更新当日 `topics.md`；只有项目六步门禁完整通过且能隔离本轮文件时才考虑提交。不得 push。


# Web 品牌与五域导航重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Open-AwA Web 前端从二十余项平铺侧栏重构为品牌刷新规范下的五域导航、规范路由和单一入口页面体系。

**Architecture:** 先以版本化 TypeScript 清单定义平台无关的导航语义，再由 Web 投影层生成领域轨道、当前域子导航和移动端五项底栏。规范路由继续复用现有业务页面与 API 契约，旧 URL 只做有测试覆盖的兼容重定向；随后以领域聚合页逐步合并重复页面，确保每个切片都能独立运行和回滚。

**Tech Stack:** React 18、TypeScript、TanStack Router、Zod、Zustand、CSS Modules、Vitest、Testing Library、Playwright。

---

## 文件职责图

- `frontend/src/shared/navigation/navigationManifest.ts`：版本化五域语义、规范路径、旧路径、图标语义和选中态规则的单一事实来源。
- `frontend/src/shared/navigation/navigationSelectors.ts`：纯函数形式的领域、子项和旧路由解析，不依赖 React。
- `frontend/src/shared/navigation/navigationIcons.tsx`：把平台无关图标语义映射到 Web 的 Lucide 图标。
- `frontend/src/shared/components/BrandMark/BrandMark.tsx`：渲染软晶品牌标记及可访问名称。
- `frontend/src/shared/components/BrandMark/BrandMark.module.css`：品牌标记尺寸和视觉变体。
- `frontend/src/shared/components/Sidebar/Sidebar.tsx`：Web 的五域领域轨道与当前域子导航投影器。
- `frontend/src/shared/components/Sidebar/Sidebar.module.css`：68px 轨道、可折叠子导航和四档响应式外壳。
- `frontend/src/shared/components/MobileTabBar/MobileTabBar.tsx`：同一清单投影出的移动 Web 五域底栏。
- `frontend/src/shared/components/MobileTabBar/MobileTabBar.module.css`：移动端触控、安全区和选中态样式。
- `frontend/src/features/library/CapabilityLibraryPage.tsx`：技能与插件的“已安装 / 发现”统一入口。
- `frontend/src/features/library/PersonaLibraryPage.tsx`：角色管理与角色发现统一入口。
- `frontend/src/features/library/KnowledgeLibraryPage.tsx`：短期、长期、经验和质量统一入口。
- `frontend/src/features/account/AccountPage.tsx`：用户中心与画像统一入口。
- `frontend/src/router/index.tsx`：规范路由只渲染规范页面；旧路径只重定向。
- `frontend/src/styles/tokens.css`：软晶品牌色、壳层尺寸、圆角和低对比边框令牌。
- `frontend/src/styles/global.css`：Web 壳层的全局网格和滚动边界。
- `frontend/src/i18n/locales/*.ts`：五域和二级视图的四语言文本。

## 子项目 A：统一语义、规范路由与 Web 新外壳

### Task 1：建立版本化五域导航清单

**Files:**
- Create: `frontend/src/shared/navigation/navigationManifest.ts`
- Create: `frontend/src/shared/navigation/navigationSelectors.ts`
- Test: `frontend/src/__tests__/shared/navigation/navigationManifest.test.ts`

- [ ] **Step 1: 写失败测试，锁定版本、五域数量、唯一 ID 和唯一规范路径**

```ts
import { describe, expect, it } from 'vitest'
import { navigationManifest } from '@/shared/navigation/navigationManifest'

describe('导航清单', () => {
  it('严格声明五个一级工作域且标识与规范路径全局唯一', () => {
    expect(navigationManifest.version).toBe(2)
    expect(navigationManifest.domains.map((domain) => domain.id)).toEqual([
      'assistant', 'workbench', 'automations', 'library', 'activity',
    ])
    const entries = navigationManifest.domains.flatMap((domain) => [domain, ...domain.children])
    expect(new Set(entries.map((entry) => entry.id)).size).toBe(entries.length)
    expect(new Set(entries.map((entry) => entry.canonicalPath)).size).toBe(entries.length)
  })
})
```

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

Run: `cd frontend; npm run test -- src/__tests__/shared/navigation/navigationManifest.test.ts`

Expected: FAIL，错误包含 `Failed to resolve import "@/shared/navigation/navigationManifest"`。

- [ ] **Step 3: 实现清单类型和五域数据**

```ts
export type NavigationDomainId = 'assistant' | 'workbench' | 'automations' | 'library' | 'activity'
export type NavigationIconKey = 'assistant' | 'workbench' | 'automations' | 'library' | 'activity'

export interface NavigationEntry {
  id: string
  canonicalPath: string
  labelKey: string
  legacyPaths: readonly string[]
  matchPrefixes: readonly string[]
}

export interface NavigationDomain extends NavigationEntry {
  id: NavigationDomainId
  iconKey: NavigationIconKey
  children: readonly NavigationEntry[]
}

export interface NavigationManifest {
  version: 2
  domains: readonly NavigationDomain[]
}

export const navigationManifest: NavigationManifest = {
  version: 2,
  domains: [
    {
      id: 'assistant',
      canonicalPath: '/assistant',
      labelKey: 'nav.domain.assistant',
      iconKey: 'assistant',
      legacyPaths: ['/chat'],
      matchPrefixes: ['/assistant'],
      children: [
        { id: 'assistant.current', canonicalPath: '/assistant', labelKey: 'nav.assistant.current', legacyPaths: ['/chat'], matchPrefixes: ['/assistant'] },
        { id: 'assistant.sessions', canonicalPath: '/assistant/sessions', labelKey: 'nav.assistant.sessions', legacyPaths: [], matchPrefixes: ['/assistant/sessions'] },
        { id: 'assistant.context', canonicalPath: '/assistant/context', labelKey: 'nav.assistant.context', legacyPaths: [], matchPrefixes: ['/assistant/context'] },
      ],
    },
    {
      id: 'workbench',
      canonicalPath: '/workbench/projects',
      labelKey: 'nav.domain.workbench',
      iconKey: 'workbench',
      legacyPaths: ['/workspace', '/coding', '/vibe-coding'],
      matchPrefixes: ['/workbench'],
      children: [
        { id: 'workbench.projects', canonicalPath: '/workbench/projects', labelKey: 'nav.workbench.projects', legacyPaths: ['/workspace'], matchPrefixes: ['/workbench/projects'] },
        { id: 'workbench.editor', canonicalPath: '/workbench/editor', labelKey: 'nav.workbench.editor', legacyPaths: ['/coding'], matchPrefixes: ['/workbench/editor'] },
        { id: 'workbench.agents', canonicalPath: '/workbench/agents', labelKey: 'nav.workbench.agents', legacyPaths: ['/vibe-coding'], matchPrefixes: ['/workbench/agents'] },
      ],
    },
    {
      id: 'automations',
      canonicalPath: '/automations/overview',
      labelKey: 'nav.domain.automations',
      iconKey: 'automations',
      legacyPaths: ['/workflows', '/scheduled-tasks', '/subagents', '/discussions'],
      matchPrefixes: ['/automations'],
      children: [
        { id: 'automations.overview', canonicalPath: '/automations/overview', labelKey: 'nav.automations.overview', legacyPaths: [], matchPrefixes: ['/automations/overview'] },
        { id: 'automations.flows', canonicalPath: '/automations/flows', labelKey: 'nav.automations.flows', legacyPaths: ['/workflows'], matchPrefixes: ['/automations/flows'] },
        { id: 'automations.schedules', canonicalPath: '/automations/schedules', labelKey: 'nav.automations.schedules', legacyPaths: ['/scheduled-tasks'], matchPrefixes: ['/automations/schedules'] },
        { id: 'automations.executors', canonicalPath: '/automations/executors', labelKey: 'nav.automations.executors', legacyPaths: ['/subagents'], matchPrefixes: ['/automations/executors'] },
        { id: 'automations.runs', canonicalPath: '/automations/runs', labelKey: 'nav.automations.runs', legacyPaths: ['/discussions'], matchPrefixes: ['/automations/runs'] },
      ],
    },
    {
      id: 'library',
      canonicalPath: '/library/capabilities',
      labelKey: 'nav.domain.library',
      iconKey: 'library',
      legacyPaths: ['/skills', '/plugins', '/roles', '/memory', '/experience', '/tts'],
      matchPrefixes: ['/library'],
      children: [
        { id: 'library.capabilities', canonicalPath: '/library/capabilities', labelKey: 'nav.library.capabilities', legacyPaths: ['/skills', '/plugins'], matchPrefixes: ['/library/capabilities'] },
        { id: 'library.personas', canonicalPath: '/library/personas', labelKey: 'nav.library.personas', legacyPaths: ['/roles', '/role-market'], matchPrefixes: ['/library/personas'] },
        { id: 'library.knowledge', canonicalPath: '/library/knowledge', labelKey: 'nav.library.knowledge', legacyPaths: ['/memory', '/experience'], matchPrefixes: ['/library/knowledge'] },
        { id: 'library.voices', canonicalPath: '/library/voices', labelKey: 'nav.library.voices', legacyPaths: ['/tts'], matchPrefixes: ['/library/voices'] },
      ],
    },
    {
      id: 'activity',
      canonicalPath: '/activity/overview',
      labelKey: 'nav.domain.activity',
      iconKey: 'activity',
      legacyPaths: ['/dashboard', '/inbox', '/billing'],
      matchPrefixes: ['/activity'],
      children: [
        { id: 'activity.overview', canonicalPath: '/activity/overview', labelKey: 'nav.activity.overview', legacyPaths: ['/dashboard'], matchPrefixes: ['/activity/overview'] },
        { id: 'activity.inbox', canonicalPath: '/activity/inbox', labelKey: 'nav.activity.inbox', legacyPaths: ['/inbox'], matchPrefixes: ['/activity/inbox'] },
        { id: 'activity.usage', canonicalPath: '/activity/usage', labelKey: 'nav.activity.usage', legacyPaths: ['/billing'], matchPrefixes: ['/activity/usage'] },
      ],
    },
  ],
}
```

- [ ] **Step 4: 添加纯选择器并覆盖最长前缀匹配**

```ts
import { navigationManifest, type NavigationDomain, type NavigationEntry } from './navigationManifest'

function matchesPath(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`)
}

export function getActiveDomain(pathname: string): NavigationDomain | undefined {
  return navigationManifest.domains.find((domain) =>
    [...domain.matchPrefixes, ...domain.legacyPaths].some((prefix) => matchesPath(pathname, prefix)),
  )
}

export function getActiveChild(domain: NavigationDomain, pathname: string): NavigationEntry | undefined {
  return [...domain.children]
    .sort((left, right) => Math.max(...right.matchPrefixes.map(String.length)) - Math.max(...left.matchPrefixes.map(String.length)))
    .find((entry) => [...entry.matchPrefixes, ...entry.legacyPaths].some((prefix) => matchesPath(pathname, prefix)))
}
```

- [ ] **Step 5: 运行清单测试并确认通过**

Run: `cd frontend; npm run test -- src/__tests__/shared/navigation/navigationManifest.test.ts`

Expected: PASS，测试文件退出码为 0。

### Task 2：建立规范路由和旧 URL 重定向

**Files:**
- Modify: `frontend/src/router/index.tsx`
- Modify: `frontend/src/router/RouteGuards.tsx`
- Test: `frontend/src/__tests__/router/index.test.tsx`
- Test: `frontend/src/__tests__/router/RouteGuards.test.tsx`

- [ ] **Step 1: 写失败测试，要求规范路由存在且旧路由不再直接渲染页面**

```ts
it('规范路由覆盖五域且旧路由只重定向', () => {
  const byPath = new Map(routeDefinitions.map((route) => [route.path, route.element]))
  expect(byPath.has('/assistant')).toBe(true)
  expect(byPath.has('/workbench/projects')).toBe(true)
  expect(byPath.has('/automations/overview')).toBe(true)
  expect(byPath.has('/library/capabilities')).toBe(true)
  expect(byPath.has('/activity/overview')).toBe(true)
  expect(isNavigateElement(byPath.get('/chat'))).toBe(true)
  expect(isNavigateElement(byPath.get('/workspace'))).toBe(true)
})
```

- [ ] **Step 2: 运行路由测试并确认规范路由缺失导致失败**

Run: `cd frontend; npm run test -- src/__tests__/router/index.test.tsx src/__tests__/router/RouteGuards.test.tsx`

Expected: FAIL，断言 `/assistant` 或其他规范路由不存在。

- [ ] **Step 3: 在路由表中添加规范路径并把旧路径改为 Navigate**

```tsx
{ path: '/assistant', element: withPageBoundary('Assistant', <ChatPage />) },
{ path: '/assistant/sessions/$conversationId', element: withPageBoundary('Assistant', <ChatPage />) },
{ path: '/workbench/projects', element: withPageBoundary('WorkbenchProjects', <WorkspacePage />) },
{ path: '/workbench/editor', element: withPageBoundary('WorkbenchEditor', <CodingPage />) },
{ path: '/workbench/agents', element: withPageBoundary('WorkbenchAgents', <VibeCodingPage />) },
{ path: '/automations/overview', element: withPageBoundary('AutomationsOverview', <ScheduledTasksPage />) },
{ path: '/automations/flows', element: withPageBoundary('AutomationsFlows', <WorkflowPage />) },
{ path: '/automations/schedules', element: withPageBoundary('AutomationsSchedules', <ScheduledTasksPage />) },
{ path: '/automations/executors', element: withPageBoundary('AutomationsExecutors', <SubAgentPage />) },
{ path: '/automations/runs', element: withPageBoundary('AutomationsRuns', <DiscussionsPage />) },
{ path: '/activity/overview', element: withPageBoundary('ActivityOverview', <DashboardPage />) },
{ path: '/activity/inbox', element: withPageBoundary('ActivityInbox', <InboxPage />) },
{ path: '/activity/usage', element: withPageBoundary('ActivityUsage', <BillingPage />) },
{ path: '/chat', element: <Navigate to="/assistant" replace /> },
{ path: '/workspace', element: <Navigate to="/workbench/projects" replace /> },
```

会话、讨论和插件详情的动态段必须保留实体 ID：

```tsx
function LegacyConversationRedirect() {
  const { conversationId } = useParams<{ conversationId?: string }>()
  return <Navigate to={`/assistant/sessions/${conversationId ?? ''}`} replace />
}
```

- [ ] **Step 4: 把认证默认落点和 not-found 落点改为 `/assistant`**

```tsx
if (location.pathname === '/' || location.pathname === '/login') {
  content = <Navigate to="/assistant" replace />
}
```

- [ ] **Step 5: 运行路由与入口测试并确认通过**

Run: `cd frontend; npm run test -- src/__tests__/router/index.test.tsx src/__tests__/router/RouteGuards.test.tsx src/__tests__/App.test.tsx src/__tests__/main.test.tsx`

Expected: PASS，且没有 TanStack Router 重定向循环或 worker 内存异常。

### Task 3：实现软晶品牌标记和品牌令牌

**Files:**
- Create: `frontend/src/shared/components/BrandMark/BrandMark.tsx`
- Create: `frontend/src/shared/components/BrandMark/BrandMark.module.css`
- Modify: `frontend/src/styles/tokens.css`
- Test: `frontend/src/__tests__/shared/components/BrandMark/BrandMark.test.tsx`

- [ ] **Step 1: 写失败测试，要求标记无字母、人物和表情语义**

```tsx
it('渲染抽象软晶标记并提供稳定品牌名称', () => {
  render(<BrandMark />)
  expect(screen.getByRole('img', { name: 'Open-AwA 抽象标记' })).toBeInTheDocument()
  expect(screen.queryByText('A')).not.toBeInTheDocument()
})
```

- [ ] **Step 2: 运行测试并确认组件不存在**

Run: `cd frontend; npm run test -- src/__tests__/shared/components/BrandMark/BrandMark.test.tsx`

Expected: FAIL，错误包含无法解析 `BrandMark` 模块。

- [ ] **Step 3: 用无外链依赖的 SVG 实现软晶三层构形**

```tsx
export function BrandMark({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" role="img" aria-label="Open-AwA 抽象标记">
      <defs>
        <linearGradient id="soft-crystal-bg" x1="8" y1="56" x2="56" y2="8">
          <stop stopColor="var(--brand-violet-deep)" />
          <stop offset="1" stopColor="var(--brand-violet-light)" />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="60" height="60" rx="16" fill="url(#soft-crystal-bg)" />
      <path d="M17 31C17 20 24 13 34 13c10 0 17 7 17 17 0 11-8 21-20 21-9 0-16-7-16-15 0-2 1-4 2-5Z" fill="var(--brand-cream)" />
      <path d="M24 31c0-7 5-12 12-12 6 0 10 5 10 11 0 8-5 14-13 14-6 0-10-4-10-9 0-2 0-3 1-4Z" fill="var(--brand-violet)" />
      <path d="M39 24c3 2 4 5 3 8-1 3-3 5-6 6 1-4 0-8-3-11 2-2 4-3 6-3Z" fill="var(--brand-peach-light)" />
    </svg>
  )
}
```

- [ ] **Step 4: 添加品牌色与壳层令牌**

```css
--brand-violet: #7654ff;
--brand-violet-deep: #5e3fd6;
--brand-violet-light: #a678ff;
--brand-peach: #ffb18f;
--brand-peach-light: #ffd8c8;
--brand-cream: #fff9f5;
--brand-lavender: #f3edff;
--brand-ink: #342b40;
--brand-muted: #786c82;
--brand-border: #e8e0ee;
--domain-rail-width: 68px;
--domain-subnav-width: 248px;
```

- [ ] **Step 5: 运行组件测试和无障碍检查并确认通过**

Run: `cd frontend; npm run test -- src/__tests__/shared/components/BrandMark/BrandMark.test.tsx src/__tests__/App.a11y.test.tsx`

Expected: PASS，SVG 只有一个可访问品牌名称。

### Task 4：将桌面侧栏替换为五域 Web 投影器

**Files:**
- Create: `frontend/src/shared/navigation/navigationIcons.tsx`
- Modify: `frontend/src/shared/components/Sidebar/Sidebar.tsx`
- Modify: `frontend/src/shared/components/Sidebar/Sidebar.module.css`
- Test: `frontend/src/__tests__/shared/components/Sidebar/Sidebar.test.tsx`

- [ ] **Step 1: 重写失败测试，要求只出现五个一级域且当前域只有一个 aria-current**

```tsx
it('从统一清单投影五个一级域与当前域子导航', () => {
  render(
    <MemoryRouter initialEntries={['/automations/flows']}>
      <Sidebar />
    </MemoryRouter>,
  )
  const primary = screen.getByRole('navigation', { name: '工作域' })
  expect(within(primary).getAllByRole('link')).toHaveLength(5)
  expect(within(primary).getByRole('link', { name: '自动化' })).toHaveAttribute('aria-current', 'page')
  const secondary = screen.getByRole('navigation', { name: '自动化子导航' })
  expect(within(secondary).getByRole('link', { name: '流程' })).toHaveAttribute('aria-current', 'page')
  expect(screen.queryByRole('link', { name: '设置' })).not.toBeInTheDocument()
})
```

- [ ] **Step 2: 运行 Sidebar 测试并确认旧三组菜单导致失败**

Run: `cd frontend; npm run test -- src/__tests__/shared/components/Sidebar/Sidebar.test.tsx`

Expected: FAIL，工作域链接数量不是 5 或找不到 `自动化子导航`。

- [ ] **Step 3: 建立图标投影并以清单渲染领域轨道**

```tsx
const iconByKey = {
  assistant: MessageCircle,
  workbench: PanelsTopLeft,
  automations: Workflow,
  library: LibraryBig,
  activity: Activity,
} satisfies Record<NavigationIconKey, LucideIcon>
```

领域链接必须使用 `domain.canonicalPath`，不得再次声明路径常量。

- [ ] **Step 4: 只渲染当前域的二级导航并保留头像、主题与反馈入口**

```tsx
const activeDomain = getActiveDomain(location.pathname) ?? navigationManifest.domains[0]
const activeChild = getActiveChild(activeDomain, location.pathname)

<nav aria-label="工作域">
  {navigationManifest.domains.map((domain) => (
    <Link key={domain.id} to={domain.canonicalPath} aria-current={domain.id === activeDomain.id ? 'page' : undefined}>
      {renderNavigationIcon(domain.iconKey)}
      <span>{t(domain.labelKey)}</span>
    </Link>
  ))}
</nav>
<nav aria-label={`${t(activeDomain.labelKey)}子导航`}>
  {activeDomain.children.map((entry) => (
    <Link key={entry.id} to={entry.canonicalPath} aria-current={entry.id === activeChild?.id ? 'page' : undefined}>
      {t(entry.labelKey)}
    </Link>
  ))}
</nav>
```

- [ ] **Step 5: 实现 68px 轨道、248px 子导航及折叠状态**

```css
.sidebar {
  display: grid;
  grid-template-columns: var(--domain-rail-width) var(--domain-subnav-width);
  width: calc(var(--domain-rail-width) + var(--domain-subnav-width));
  background: var(--brand-cream);
  border-right: 1px solid var(--brand-border);
}

.collapsed {
  grid-template-columns: var(--domain-rail-width) 0;
  width: var(--domain-rail-width);
}

.domain-rail {
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, #6f50ed 0%, #5e3fd6 100%);
}
```

- [ ] **Step 6: 运行 Sidebar、App 和无障碍测试**

Run: `cd frontend; npm run test -- src/__tests__/shared/components/Sidebar/Sidebar.test.tsx src/__tests__/App.test.tsx src/__tests__/App.a11y.test.tsx`

Expected: PASS，一级域恰好五个，每个导航容器最多一个 `aria-current="page"`。

### Task 5：把移动 Web 底栏改为同一清单的五域投影

**Files:**
- Modify: `frontend/src/shared/components/MobileTabBar/MobileTabBar.tsx`
- Modify: `frontend/src/shared/components/MobileTabBar/MobileTabBar.module.css`
- Test: `frontend/src/__tests__/shared/components/MobileTabBar.test.tsx`

- [ ] **Step 1: 写失败测试，删除“更多”和完整抽屉入口**

```tsx
it('移动端只渲染五个工作域且不再提供更多抽屉', () => {
  render(
    <MemoryRouter initialEntries={['/library/knowledge']}>
      <MobileTabBar />
    </MemoryRouter>,
  )
  expect(screen.getAllByRole('link')).toHaveLength(5)
  expect(screen.getByRole('link', { name: /资源库/ })).toHaveAttribute('aria-current', 'page')
  expect(screen.queryByTestId('tab-more')).not.toBeInTheDocument()
})
```

- [ ] **Step 2: 运行测试并确认旧四项加“更多”结构导致失败**

Run: `cd frontend; npm run test -- src/__tests__/shared/components/MobileTabBar.test.tsx`

Expected: FAIL，仍存在 `tab-more` 或找不到五域标签。

- [ ] **Step 3: 从 navigationManifest 直接投影五个领域**

```tsx
{navigationManifest.domains.map((domain) => {
  const active = domain.id === activeDomain?.id
  return (
    <Link key={domain.id} to={domain.canonicalPath} aria-current={active ? 'page' : undefined}>
      {renderNavigationIcon(domain.iconKey, 22)}
      <span>{t(domain.labelKey)}</span>
    </Link>
  )
})}
```

- [ ] **Step 4: 保证五项在 320px 宽度、200% 字体下仍有可访问名称**

```css
.tab-item {
  min-width: 48px;
  min-height: 48px;
}

.tab-label {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
```

- [ ] **Step 5: 运行移动导航与响应式聊天测试**

Run: `cd frontend; npm run test -- src/__tests__/shared/components/MobileTabBar.test.tsx src/__tests__/features/chat/ChatPageResponsive.test.tsx`

Expected: PASS，移动端没有可打开二十余项完整抽屉的入口。

### Task 6：接入四语言文案和品牌壳层

**Files:**
- Modify: `frontend/src/i18n/locales/zh-CN.ts`
- Modify: `frontend/src/i18n/locales/en-US.ts`
- Modify: `frontend/src/i18n/locales/ja-JP.ts`
- Modify: `frontend/src/i18n/locales/ru-RU.ts`
- Modify: `frontend/src/styles/global.css`
- Modify: `frontend/src/layouts/AppShell.tsx`
- Test: `frontend/src/__tests__/shared/i18n/i18n.test.tsx`
- Test: `frontend/src/__tests__/App.test.tsx`

- [ ] **Step 1: 写失败测试，要求四语言包包含完整五域键**

```ts
const requiredKeys = [
  'nav.domain.assistant',
  'nav.domain.workbench',
  'nav.domain.automations',
  'nav.domain.library',
  'nav.domain.activity',
]

for (const key of requiredKeys) {
  expect(zhCN[key]).toBeTruthy()
  expect(enUS[key]).toBeTruthy()
  expect(jaJP[key]).toBeTruthy()
  expect(ruRU[key]).toBeTruthy()
}
```

- [ ] **Step 2: 运行 i18n 测试并确认新键缺失**

Run: `cd frontend; npm run test -- src/__tests__/shared/i18n/i18n.test.tsx`

Expected: FAIL，新 `nav.domain.*` 键为 `undefined`。

- [ ] **Step 3: 为五域与全部二级项补齐四语言文案**

```ts
"nav.domain.assistant": "助手",
"nav.domain.workbench": "工作台",
"nav.domain.automations": "自动化",
"nav.domain.library": "资源库",
"nav.domain.activity": "动态",
```

其他语言包使用对应语言的稳定短标签，不以中文或 key 字符串充当临时值。

- [ ] **Step 4: 调整 AppShell 为单主滚动区和移动端纵向布局**

```css
.app-container {
  display: flex;
  height: 100dvh;
  overflow: hidden;
  background: linear-gradient(135deg, var(--brand-cream), var(--brand-lavender));
}

.main-content {
  min-width: 0;
  flex: 1;
  overflow: auto;
}

@media (max-width: 767px) {
  .app-container { flex-direction: column; }
  .main-content { order: 1; }
}
```

- [ ] **Step 5: 运行 i18n、App、类型检查与 lint**

Run: `cd frontend; npm run test -- src/__tests__/shared/i18n/i18n.test.tsx src/__tests__/App.test.tsx; npm run typecheck; npm run lint`

Expected: 所有命令退出码为 0，无缺失翻译警告、TypeScript 错误或 ESLint 错误。

## 子项目 B：领域聚合页与重复入口退场

### Task 7：合并技能与插件为能力资源页

**Files:**
- Create: `frontend/src/features/library/CapabilityLibraryPage.tsx`
- Create: `frontend/src/features/library/CapabilityLibraryPage.module.css`
- Modify: `frontend/src/router/index.tsx`
- Test: `frontend/src/__tests__/features/library/CapabilityLibraryPage.test.tsx`

- [ ] **Step 1: 写失败测试，要求类型和视图由查询状态驱动**

```tsx
it('在同一规范页面切换技能、插件、已安装和发现视图', () => {
  renderLibrary('/library/capabilities?type=plugin&view=discover')
  expect(screen.getByRole('tab', { name: '插件' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByRole('tab', { name: '发现' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByRole('heading', { name: '发现插件' })).toBeInTheDocument()
})
```

- [ ] **Step 2: 运行测试并确认聚合页不存在**

Run: `cd frontend; npm run test -- src/__tests__/features/library/CapabilityLibraryPage.test.tsx`

Expected: FAIL，无法解析 `CapabilityLibraryPage`。

- [ ] **Step 3: 实现受控的类型与视图选择器**

```ts
type CapabilityType = 'skill' | 'plugin'
type CapabilityView = 'installed' | 'discover'

function normalizeCapabilityState(search: URLSearchParams) {
  const type: CapabilityType = search.get('type') === 'plugin' ? 'plugin' : 'skill'
  const view: CapabilityView = search.get('view') === 'discover' ? 'discover' : 'installed'
  return { type, view }
}
```

- [ ] **Step 4: 复用既有列表与市场内容，但只暴露一个规范路由**

`/skills`、`/skills/market`、`/plugins` 和 `/plugins/manage` 只重定向到带查询状态的 `/library/capabilities`，不得继续出现在导航、站点地图或内部链接中。

- [ ] **Step 5: 运行聚合页、技能和插件回归测试**

Run: `cd frontend; npm run test -- src/__tests__/features/library/CapabilityLibraryPage.test.tsx src/__tests__/features/skills/SkillsPage.test.tsx src/__tests__/features/plugins/PluginsPage.test.tsx`

Expected: PASS，旧能力组件继续工作，但只有聚合页是规范入口。

### Task 8：合并角色、知识和账户重复页面

**Files:**
- Create: `frontend/src/features/library/PersonaLibraryPage.tsx`
- Create: `frontend/src/features/library/KnowledgeLibraryPage.tsx`
- Create: `frontend/src/features/account/AccountPage.tsx`
- Modify: `frontend/src/router/index.tsx`
- Test: `frontend/src/__tests__/features/library/PersonaLibraryPage.test.tsx`
- Test: `frontend/src/__tests__/features/library/KnowledgeLibraryPage.test.tsx`
- Test: `frontend/src/__tests__/features/account/AccountPage.test.tsx`

- [ ] **Step 1: 写三个失败测试，锁定统一视图状态**

```tsx
expect(renderPersona('/library/personas?view=discover').getByRole('tab', { name: '发现' })).toHaveAttribute('aria-selected', 'true')
expect(renderKnowledge('/library/knowledge?view=experience').getByRole('tab', { name: '经验' })).toHaveAttribute('aria-selected', 'true')
expect(renderAccount('/account?section=profile').getByRole('tab', { name: '画像' })).toHaveAttribute('aria-selected', 'true')
```

- [ ] **Step 2: 运行测试并确认三个聚合页均不存在**

Run: `cd frontend; npm run test -- src/__tests__/features/library/PersonaLibraryPage.test.tsx src/__tests__/features/library/KnowledgeLibraryPage.test.tsx src/__tests__/features/account/AccountPage.test.tsx`

Expected: FAIL，三个新模块均无法解析。

- [ ] **Step 3: 实现角色“已有 / 发现”、知识四视图和账户分区**

角色只接受 `installed | discover`，知识只接受 `short-term | long-term | experience | quality`，账户只接受已声明分区；非法查询状态必须规范化到各页面默认值，并保持页面可用。

- [ ] **Step 4: 把旧路由改为带查询状态的重定向**

```tsx
{ path: '/role-market', element: <Navigate to="/library/personas?view=discover" replace /> },
{ path: '/experience', element: <Navigate to="/library/knowledge?view=experience" replace /> },
{ path: '/user-profile', element: <Navigate to="/account?section=profile" replace /> },
```

- [ ] **Step 5: 运行新聚合页和既有业务回归测试**

Run: `cd frontend; npm run test -- src/__tests__/features/library src/__tests__/features/account src/__tests__/features/memory/MemoryPage.test.tsx src/__tests__/features/experiences/ExperiencePage.test.tsx src/__tests__/UserPage.test.tsx`

Expected: PASS，三组重复入口都只剩规范页面。

### Task 9：迁移内部链接并建立旧路径防回归门禁

**Files:**
- Modify: `frontend/src/features/**/*.tsx`
- Modify: `frontend/src/shared/**/*.tsx`
- Create: `frontend/src/__tests__/navigationRetirement.test.ts`

- [ ] **Step 1: 写失败测试，扫描生产源码中的旧导航目标**

```ts
const retiredTargets = [
  '/chat', '/workspace', '/coding', '/vibe-coding', '/workflows', '/scheduled-tasks',
  '/subagents', '/discussions', '/skills', '/role-market', '/memory', '/experience',
  '/dashboard', '/inbox', '/billing', '/user-profile',
]

for (const file of productionNavigationSources) {
  for (const target of retiredTargets) {
    expect(file.content).not.toContain(`to="${target}"`)
  }
}
```

- [ ] **Step 2: 运行扫描测试并记录所有旧内部链接**

Run: `cd frontend; npm run test -- src/__tests__/navigationRetirement.test.ts`

Expected: FAIL，并列出仍产生旧 URL 的生产文件。

- [ ] **Step 3: 将内部链接一次性改为规范路径**

修改仅限导航目标，不改变 API 路径、实体 ID、数据查询或权限判断。旧路径字符串只能保留在兼容重定向表和明确验证兼容行为的测试中。

- [ ] **Step 4: 运行全仓扫描和路由回归**

Run: `cd frontend; npm run test -- src/__tests__/navigationRetirement.test.ts src/__tests__/router/index.test.tsx`

Expected: PASS，生产导航不再生成旧 URL。

## 集成验证与验收

### Task 10：执行前端完整验证和真实浏览器验收

**Files:**
- Modify: `frontend/e2e/navigation.spec.ts`
- Evidence: `test-results/navigation/`
- Modify: `docs/design/cross-platform-navigation-redesign-2026-08-09/implementation-and-acceptance.md`

- [ ] **Step 1: 写 Playwright 验收，覆盖四档宽度和规范深链**

```ts
for (const width of [480, 768, 1024, 1440]) {
  test(`五域导航在 ${width}px 下没有重复入口`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/automations/flows')
    await expect(page.getByRole('navigation', { name: width < 768 ? '底部主导航' : '工作域' })).toBeVisible()
    await expect(page.getByRole('link', { name: '自动化' })).toHaveAttribute('aria-current', 'page')
    await expect(page).toHaveScreenshot(`navigation-${width}.png`, { fullPage: true })
  })
}
```

- [ ] **Step 2: 运行前端单元测试、覆盖率、类型、lint 和构建**

Run: `cd frontend; npm run test; npm run test:coverage; npm run typecheck; npm run lint; npm run build`

Expected: 所有命令退出码为 0，覆盖率不低于仓库门槛，构建无 TypeScript 或 Vite 错误。

- [ ] **Step 3: 启动隔离服务并验证 `/api/system/ping`**

Run: 按 `CLAUDE.md` 的隔离运行时变量启动 `.venv\Scripts\python.exe backend\main.py`，再请求 `GET /api/system/ping`。

Expected: HTTP 200；隔离数据库、日志、初始化标记和缓存均位于本轮临时目录。

- [ ] **Step 4: 运行 Web E2E 与四档截图**

Run: `cd frontend; npm run e2e -- navigation.spec.ts`

Expected: 480、768、1024、1440px 全部通过，页面错误为 0，每个导航容器只有一个选中项。

- [ ] **Step 5: 运行项目审计脚本并检查差异**

Run: `powershell -ExecutionPolicy Bypass -File .\scripts\code-audit.ps1`

Expected: 审计通过；`git diff --check` 无行尾空格或冲突标记；新增注释均为中文且改动中无表情符号。

- [ ] **Step 6: 更新验收文档和当日项目记忆**

在实施验收文档记录实际命令、退出码、截图路径和未完成阶段；在当日 `topics.md` 追加本轮规范路由、五域外壳、测试证据和剩余页面合并工作。只有发现可复用的新硬约束时才修改 `project_memory.md` 与 `CLAUDE.md` Known Pitfalls。

- [ ] **Step 7: 通过完整六步闭环后提交当前阶段**

```powershell
git add frontend/src frontend/e2e docs/design docs/superpowers/plans
git commit -m "[Refactoring] 前端接入五域导航与软晶品牌外壳"
```

Expected: 提交位于本地 `main`；不执行 `git push`。

## 计划自审结果

- 规范覆盖：品牌色与软晶标记、五域清单、规范路由、旧路径兼容、桌面 Web、移动 Web、领域聚合、四档视觉验收均有对应任务。
- 范围约束：本计划只改 Web 前端和实施文档，不改业务 API、数据库、Electron 主进程或 Android 原生代码。
- 类型一致：清单统一使用 `canonicalPath`、`legacyPaths`、`matchPrefixes`、`labelKey` 和 `iconKey`；投影层不重复声明路径。
- 回滚边界：每个任务均可独立测试；旧 URL 在兼容期只重定向，用户数据和 API 契约不变。

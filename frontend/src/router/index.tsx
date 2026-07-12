import React, { Suspense } from 'react'
import { createBrowserRouter, Navigate } from 'react-router-dom'
import ErrorBoundary from '@/shared/components/ErrorBoundary/ErrorBoundary'
import { Skeleton } from '@/shared/components/ui/Skeleton'
import { DevTestRoute, RootGuard } from './RouteGuards'

// P2: 页面组件懒加载，减少主包体积
const LoginPage = React.lazy(() => import('@/features/auth/LoginPage'))
const SetupPage = React.lazy(() => import('@/features/setup/SetupPage'))
const ChatPage = React.lazy(() => import('@/features/chat/ChatPage'))
const DashboardPage = React.lazy(() => import('@/features/dashboard/DashboardPage'))
const SettingsPage = React.lazy(() => import('@/features/settings/SettingsPage'))
const SkillsPage = React.lazy(() => import('@/features/skills/SkillsPage'))
const ScheduledTasksPage = React.lazy(() => import('@/features/scheduledTasks/ScheduledTasksPage'))
const PluginsPage = React.lazy(() => import('@/features/plugins/PluginsPage'))
const PluginConfigPage = React.lazy(() => import('@/features/plugins/PluginConfigPage'))
const MemoryPage = React.lazy(() => import('@/features/memory/MemoryPage'))
const BillingPage = React.lazy(() => import('@/features/billing/BillingPage'))
const ExperiencePage = React.lazy(() => import('@/features/experiences/ExperiencePage'))
const UserCenterPage = React.lazy(() => import('@/features/user/UserCenterPage'))
const WorkspacePage = React.lazy(() => import('@/features/workspace/WorkspacePage'))
const CodingPage = React.lazy(() => import('@/features/coding/CodingPage'))
const InboxPage = React.lazy(() => import('@/features/inbox/InboxPage'))
const SkillMarketPage = React.lazy(() => import('@/features/skills/SkillMarketPage'))
const RolesPage = React.lazy(() => import('@/features/roles/RolesPage'))
const RoleMarketPage = React.lazy(() => import('@/features/marketplace/RoleMarketPage'))
const TtsPage = React.lazy(() => import('@/features/tts/TtsPage'))
const ImChannelsPage = React.lazy(() => import('@/features/im/ImChannelsPage'))
const WorkflowPage = React.lazy(() => import('@/features/workflow/WorkflowPage'))
const SubAgentPage = React.lazy(() => import('@/features/subagents/SubAgentPage'))
const VibeCodingPage = React.lazy(() => import('@/features/vibe-coding/VibeCodingPage'))
const DiscussionsPage = React.lazy(() => import('@/features/discussions/DiscussionsPage'))
const UserProfilePage = React.lazy(() => import('@/features/user-profile/UserProfilePage'))

// 统一的页面级 Suspense fallback：路由懒加载期间的占位骨架
// 使用设计令牌保持与全局间距体系一致
const PageSkeleton = () => (
  <div
    style={{
      padding: 'var(--space-4)',
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-3)',
    }}
  >
    <Skeleton.Paragraph lines={4} />
  </div>
)

// 用 Suspense 包裹懒加载页面元素，提供统一的 PageSkeleton fallback
// Suspense 置于 ErrorBoundary 内部：ErrorBoundary 仍可捕获页面渲染异常与 fallback 渲染异常
const withSuspense = (element: React.ReactNode) => (
  <Suspense fallback={<PageSkeleton />}>{element}</Suspense>
)

// React Router v7 迁移准备的 future flags
const routerFutureConfig = {
  v7_startTransition: true,
  v7_relativeSplatPath: true,
}

// 用 createBrowserRouter 定义路由表（data router API）
// URL 结构与重构前完全一致，所有路由路径未变
// 根路由 element 为 RootGuard，由其根据认证状态决定渲染 AppShell 或重定向
//
// P2 路由懒加载策略：
// - 所有 page 组件采用 React.lazy 懒加载，缩减首屏 JS 体积
// - 每个路由 element 用 Suspense + PageSkeleton 包裹，加载期间显示骨架屏
// - 守卫组件（RootGuard/DevTestRoute）保留直接导入，确保首屏立即可用
//
// P2 hover prefetch（暂未启用）：如需在侧边栏菜单项 hover 时预加载对应 chunk，
// 可在 Sidebar 菜单项上添加 onMouseEnter 回调触发对应页面模块的 import() 预加载，
// 利用浏览器空闲时间提前下载，进一步降低首次导航延迟
export const router = createBrowserRouter(
  [
    {
      path: '/',
      element: <RootGuard />,
      children: [
        // 已认证访问 / 时跳转到 /chat（在 RootGuard 中处理）
        { index: true, element: <Navigate to="/chat" replace /> },
        { path: 'login', element: <ErrorBoundary name="Login">{withSuspense(<LoginPage />)}</ErrorBoundary> },
        // 首次部署初始化引导页（系统未初始化时 RootGuard 自动重定向到此）
        { path: 'setup', element: <ErrorBoundary name="Setup">{withSuspense(<SetupPage />)}</ErrorBoundary> },
        { path: 'chat', element: <ErrorBoundary name="Chat">{withSuspense(<ChatPage />)}</ErrorBoundary> },
        { path: 'chat/:conversationId', element: <ErrorBoundary name="Chat">{withSuspense(<ChatPage />)}</ErrorBoundary> },
        { path: 'dashboard', element: <ErrorBoundary name="Dashboard">{withSuspense(<DashboardPage />)}</ErrorBoundary> },
        { path: 'settings', element: <ErrorBoundary name="Settings">{withSuspense(<SettingsPage />)}</ErrorBoundary> },
        { path: 'skills', element: <ErrorBoundary name="Skills">{withSuspense(<SkillsPage />)}</ErrorBoundary> },
        { path: 'skills/market', element: <ErrorBoundary name="SkillMarket">{withSuspense(<SkillMarketPage />)}</ErrorBoundary> },
        { path: 'scheduled-tasks', element: <ErrorBoundary name="ScheduledTasks">{withSuspense(<ScheduledTasksPage />)}</ErrorBoundary> },
        {
          path: 'plugins',
          children: [
            { index: true, element: <Navigate to="manage" replace /> },
            { path: 'manage', element: <ErrorBoundary name="Plugins">{withSuspense(<PluginsPage />)}</ErrorBoundary> },
            { path: 'config/:pluginId', element: <ErrorBoundary name="PluginConfig">{withSuspense(<PluginConfigPage />)}</ErrorBoundary> },
          ],
        },
        { path: 'memory', element: <ErrorBoundary name="Memory">{withSuspense(<MemoryPage />)}</ErrorBoundary> },
        { path: 'experience', element: <ErrorBoundary name="Experience">{withSuspense(<ExperiencePage hideHeader />)}</ErrorBoundary> },
        { path: 'billing', element: <ErrorBoundary name="Billing">{withSuspense(<BillingPage />)}</ErrorBoundary> },
        { path: 'user', element: <ErrorBoundary name="UserCenter">{withSuspense(<UserCenterPage />)}</ErrorBoundary> },
        { path: 'user-profile', element: <ErrorBoundary name="UserProfile">{withSuspense(<UserProfilePage />)}</ErrorBoundary> },
        { path: 'dev/test', element: <ErrorBoundary name="Test"><DevTestRoute /></ErrorBoundary> },
        { path: 'workspace', element: <ErrorBoundary name="Workspace">{withSuspense(<WorkspacePage />)}</ErrorBoundary> },
        { path: 'coding', element: <ErrorBoundary name="Coding">{withSuspense(<CodingPage />)}</ErrorBoundary> },
        { path: 'inbox', element: <ErrorBoundary name="Inbox">{withSuspense(<InboxPage />)}</ErrorBoundary> },
        { path: 'roles', element: <ErrorBoundary name="Roles">{withSuspense(<RolesPage />)}</ErrorBoundary> },
        { path: 'role-market', element: <ErrorBoundary name="RoleMarket">{withSuspense(<RoleMarketPage />)}</ErrorBoundary> },
        { path: 'tts', element: <ErrorBoundary name="Tts">{withSuspense(<TtsPage />)}</ErrorBoundary> },
        { path: 'im', element: <ErrorBoundary name="ImChannels">{withSuspense(<ImChannelsPage />)}</ErrorBoundary> },
        { path: 'workflows', element: <ErrorBoundary name="Workflow">{withSuspense(<WorkflowPage />)}</ErrorBoundary> },
        { path: 'subagents', element: <ErrorBoundary name="SubAgents">{withSuspense(<SubAgentPage />)}</ErrorBoundary> },
        { path: 'vibe-coding', element: <ErrorBoundary name="VibeCoding">{withSuspense(<VibeCodingPage />)}</ErrorBoundary> },
        { path: 'discussions', element: <ErrorBoundary name="Discussions">{withSuspense(<DiscussionsPage />)}</ErrorBoundary> },
        { path: 'discussions/:id', element: <ErrorBoundary name="Discussions">{withSuspense(<DiscussionsPage />)}</ErrorBoundary> },
        { path: 'user-profile', element: <ErrorBoundary name="UserProfile">{withSuspense(<UserProfilePage />)}</ErrorBoundary> },
        // 兜底：未匹配路径重定向到 /chat（保持用户体验友好，URL 不变）
        { path: '*', element: <Navigate to="/chat" replace /> },
      ],
    },
  ],
  {
    future: routerFutureConfig,
  },
)

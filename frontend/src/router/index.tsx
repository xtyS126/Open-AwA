import React from 'react'
import { createBrowserRouter, Navigate } from 'react-router-dom'
import ErrorBoundary from '@/shared/components/ErrorBoundary/ErrorBoundary'
import { DevTestRoute, RootGuard } from './RouteGuards'

// P2: 页面组件懒加载，减少主包体积
const LoginPage = React.lazy(() => import('@/features/auth/LoginPage'))
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

// React Router v7 迁移准备的 future flags
const routerFutureConfig = {
  v7_startTransition: true,
  v7_relativeSplatPath: true,
}

// 用 createBrowserRouter 定义路由表（data router API）
// URL 结构与重构前完全一致，所有路由路径未变
// 根路由 element 为 RootGuard，由其根据认证状态决定渲染 AppShell 或重定向
export const router = createBrowserRouter(
  [
    {
      path: '/',
      element: <RootGuard />,
      children: [
        // 已认证访问 / 时跳转到 /chat（在 RootGuard 中处理）
        { index: true, element: <Navigate to="/chat" replace /> },
        { path: 'login', element: <ErrorBoundary name="Login"><LoginPage /></ErrorBoundary> },
        { path: 'chat', element: <ErrorBoundary name="Chat"><ChatPage /></ErrorBoundary> },
        { path: 'chat/:conversationId', element: <ErrorBoundary name="Chat"><ChatPage /></ErrorBoundary> },
        { path: 'dashboard', element: <ErrorBoundary name="Dashboard"><DashboardPage /></ErrorBoundary> },
        { path: 'settings', element: <ErrorBoundary name="Settings"><SettingsPage /></ErrorBoundary> },
        { path: 'skills', element: <ErrorBoundary name="Skills"><SkillsPage /></ErrorBoundary> },
        { path: 'skills/market', element: <ErrorBoundary name="SkillMarket"><SkillMarketPage /></ErrorBoundary> },
        { path: 'scheduled-tasks', element: <ErrorBoundary name="ScheduledTasks"><ScheduledTasksPage /></ErrorBoundary> },
        {
          path: 'plugins',
          children: [
            { index: true, element: <Navigate to="manage" replace /> },
            { path: 'manage', element: <ErrorBoundary name="Plugins"><PluginsPage /></ErrorBoundary> },
            { path: 'config/:pluginId', element: <ErrorBoundary name="PluginConfig"><PluginConfigPage /></ErrorBoundary> },
          ],
        },
        { path: 'memory', element: <ErrorBoundary name="Memory"><MemoryPage /></ErrorBoundary> },
        { path: 'experience', element: <ErrorBoundary name="Experience"><ExperiencePage hideHeader /></ErrorBoundary> },
        { path: 'billing', element: <ErrorBoundary name="Billing"><BillingPage /></ErrorBoundary> },
        { path: 'user', element: <ErrorBoundary name="UserCenter"><UserCenterPage /></ErrorBoundary> },
        { path: 'dev/test', element: <ErrorBoundary name="Test"><DevTestRoute /></ErrorBoundary> },
        { path: 'workspace', element: <ErrorBoundary name="Workspace"><WorkspacePage /></ErrorBoundary> },
        { path: 'coding', element: <ErrorBoundary name="Coding"><CodingPage /></ErrorBoundary> },
        { path: 'inbox', element: <ErrorBoundary name="Inbox"><InboxPage /></ErrorBoundary> },
        { path: 'roles', element: <ErrorBoundary name="Roles"><RolesPage /></ErrorBoundary> },
        { path: 'role-market', element: <ErrorBoundary name="RoleMarket"><RoleMarketPage /></ErrorBoundary> },
        { path: 'tts', element: <ErrorBoundary name="Tts"><TtsPage /></ErrorBoundary> },
        { path: 'im', element: <ErrorBoundary name="ImChannels"><ImChannelsPage /></ErrorBoundary> },
        { path: 'workflows', element: <ErrorBoundary name="Workflow"><WorkflowPage /></ErrorBoundary> },
        { path: 'subagents', element: <ErrorBoundary name="SubAgents"><SubAgentPage /></ErrorBoundary> },
        { path: 'vibe-coding', element: <ErrorBoundary name="VibeCoding"><VibeCodingPage /></ErrorBoundary> },
        { path: 'discussions', element: <ErrorBoundary name="Discussions"><DiscussionsPage /></ErrorBoundary> },
        { path: 'discussions/:id', element: <ErrorBoundary name="Discussions"><DiscussionsPage /></ErrorBoundary> },
        // 兜底：未匹配路径重定向到 /chat（保持用户体验友好，URL 不变）
        { path: '*', element: <Navigate to="/chat" replace /> },
      ],
    },
  ],
  {
    future: routerFutureConfig,
  },
)

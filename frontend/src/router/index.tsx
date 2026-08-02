import React, { Suspense } from 'react'
import {
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router'
import { Navigate } from '@/shared/routing'
import ErrorBoundary from '@/shared/components/ErrorBoundary/ErrorBoundary'
import { Skeleton } from '@/shared/components/ui/Skeleton'
import { DevTestRoute, RootGuard } from './RouteGuards'

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
const PetsPage = React.lazy(() => import('@/features/pets/PetsPage'))

function PageSkeleton() {
  return (
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
}

function withSuspense(element: React.ReactNode) {
  return <Suspense fallback={<PageSkeleton />}>{element}</Suspense>
}

function withPageBoundary(name: string, element: React.ReactNode) {
  return <ErrorBoundary name={name}>{withSuspense(element)}</ErrorBoundary>
}

export interface AppRouteDefinition {
  path: string
  element: React.ReactElement
}

/**
 * 集中声明稳定 URL 与页面元素，动态段使用 TanStack Router 的 $param 语法。
 */
export const routeDefinitions: AppRouteDefinition[] = [
  { path: '/', element: <Navigate to="/chat" replace /> },
  { path: '/login', element: withPageBoundary('Login', <LoginPage />) },
  { path: '/setup', element: withPageBoundary('Setup', <SetupPage />) },
  { path: '/chat', element: withPageBoundary('Chat', <ChatPage />) },
  { path: '/chat/$conversationId', element: withPageBoundary('Chat', <ChatPage />) },
  { path: '/dashboard', element: withPageBoundary('Dashboard', <DashboardPage />) },
  { path: '/settings', element: withPageBoundary('Settings', <SettingsPage />) },
  { path: '/skills', element: withPageBoundary('Skills', <SkillsPage />) },
  { path: '/skills/market', element: withPageBoundary('SkillMarket', <SkillMarketPage />) },
  { path: '/scheduled-tasks', element: withPageBoundary('ScheduledTasks', <ScheduledTasksPage />) },
  { path: '/plugins', element: <Navigate to="/plugins/manage" replace /> },
  { path: '/plugins/manage', element: withPageBoundary('Plugins', <PluginsPage />) },
  { path: '/plugins/config/$pluginId', element: withPageBoundary('PluginConfig', <PluginConfigPage />) },
  { path: '/memory', element: withPageBoundary('Memory', <MemoryPage />) },
  { path: '/experience', element: withPageBoundary('Experience', <ExperiencePage hideHeader />) },
  { path: '/billing', element: withPageBoundary('Billing', <BillingPage />) },
  { path: '/user', element: withPageBoundary('UserCenter', <UserCenterPage />) },
  { path: '/user-profile', element: withPageBoundary('UserProfile', <UserProfilePage />) },
  { path: '/dev/test', element: <ErrorBoundary name="Test"><DevTestRoute /></ErrorBoundary> },
  { path: '/workspace', element: withPageBoundary('Workspace', <WorkspacePage />) },
  { path: '/coding', element: withPageBoundary('Coding', <CodingPage />) },
  { path: '/inbox', element: withPageBoundary('Inbox', <InboxPage />) },
  { path: '/roles', element: withPageBoundary('Roles', <RolesPage />) },
  { path: '/role-market', element: withPageBoundary('RoleMarket', <RoleMarketPage />) },
  { path: '/tts', element: withPageBoundary('Tts', <TtsPage />) },
  { path: '/im', element: withPageBoundary('ImChannels', <ImChannelsPage />) },
  { path: '/workflows', element: withPageBoundary('Workflow', <WorkflowPage />) },
  { path: '/subagents', element: withPageBoundary('SubAgents', <SubAgentPage />) },
  { path: '/vibe-coding', element: withPageBoundary('VibeCoding', <VibeCodingPage />) },
  { path: '/discussions', element: withPageBoundary('Discussions', <DiscussionsPage />) },
  { path: '/discussions/$id', element: withPageBoundary('Discussions', <DiscussionsPage />) },
  { path: '/pets', element: withPageBoundary('Pets', <PetsPage />) },
]

const rootRoute = createRootRoute({
  component: RootGuard,
  notFoundComponent: () => <Navigate to="/chat" replace />,
})

const childRoutes = routeDefinitions.map(({ path, element }) => createRoute({
  getParentRoute: () => rootRoute,
  path,
  component: () => element,
}))

const routeTree = rootRoute.addChildren(childRoutes)

export const router = createRouter({ routeTree })

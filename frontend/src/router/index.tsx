import React, { Suspense } from 'react'
import {
  createRootRoute,
  createRoute,
  createRouter,
  createHashHistory,
} from '@tanstack/react-router'
import { Navigate, useParams } from '@/shared/routing'
import ErrorBoundary from '@/shared/components/ErrorBoundary/ErrorBoundary'
import { Skeleton } from '@/shared/components/ui/Skeleton'
import { DevTestRoute, RootGuard } from './RouteGuards'

// 宠物悬浮窗检测：通过 loadFile 的 query 参数 overlay=pet 识别
// hash history 模式下，路由路径存放在 location.hash；query 参数仍在 location.search
if (typeof window !== 'undefined') {
  const search = window.location.search
  if (search.includes('overlay=pet')) {
    window.location.hash = '#/pet-overlay'
  } else if (search.includes('route=onboarding')) {
    window.location.hash = '#/onboarding'
  }
}

const LoginPage = React.lazy(() => import('@/features/auth/LoginPage'))
const ServerSelectPage = React.lazy(() => import('@/features/server/ServerSelectPage'))
const SetupPage = React.lazy(() => import('@/features/setup/SetupPage'))
const ChatPage = React.lazy(() => import('@/features/chat/ChatPage'))
const AssistantSessionsPage = React.lazy(() => import('@/features/assistant/AssistantSessionsPage'))
const AssistantContextPage = React.lazy(() => import('@/features/assistant/AssistantContextPage'))
const DashboardPage = React.lazy(() => import('@/features/dashboard/DashboardPage'))
const SettingsPage = React.lazy(() => import('@/features/settings/SettingsPage'))
const CapabilityLibraryPage = React.lazy(() => import('@/features/library/CapabilityLibraryPage'))
const ScheduledTasksPage = React.lazy(() => import('@/features/scheduledTasks/ScheduledTasksPage'))
const PluginConfigPage = React.lazy(() => import('@/features/plugins/PluginConfigPage'))
const KnowledgeLibraryPage = React.lazy(() => import('@/features/library/KnowledgeLibraryPage'))
const BillingPage = React.lazy(() => import('@/features/billing/BillingPage'))
const AccountPage = React.lazy(() => import('@/features/account/AccountPage'))
const WorkbenchProjectsPage = React.lazy(() => import('@/features/workbench/WorkbenchProjectsPage'))
const CodingPage = React.lazy(() => import('@/features/coding/CodingPage'))
const InboxPage = React.lazy(() => import('@/features/inbox/InboxPage'))
const PersonaLibraryPage = React.lazy(() => import('@/features/library/PersonaLibraryPage'))
const TtsPage = React.lazy(() => import('@/features/tts/TtsPage'))
const WorkflowPage = React.lazy(() => import('@/features/workflow/WorkflowPage'))
const SubAgentPage = React.lazy(() => import('@/features/subagents/SubAgentPage'))
const VibeCodingPage = React.lazy(() => import('@/features/vibe-coding/VibeCodingPage'))
const DiscussionsPage = React.lazy(() => import('@/features/discussions/DiscussionsPage'))
const AutomationsOverviewPage = React.lazy(() => import('@/features/automations/AutomationsOverviewPage'))
const WorkbenchShell = React.lazy(() => import('@/features/workbench/WorkbenchShell'))
const PetOverlayApp = React.lazy(() => import('@/features/pet-overlay/PetOverlayApp'))
const OnboardingPage = React.lazy(() => import('@/features/onboarding/OnboardingPage'))

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
  kind?: 'page' | 'redirect'
}

function LegacyConversationRedirect() {
  const { conversationId } = useParams<{ conversationId?: string }>()
  return <Navigate to={`/assistant/sessions/${conversationId ?? ''}`} replace />
}

function LegacyDiscussionRedirect() {
  const { id } = useParams<{ id?: string }>()
  return <Navigate to={`/automations/runs/${id ?? ''}/collaboration`} replace />
}

function LegacyPluginConfigRedirect() {
  const { pluginId } = useParams<{ pluginId?: string }>()
  return <Navigate to={`/library/capabilities/plugin/${pluginId ?? ''}/config`} replace />
}

/**
 * 集中声明稳定 URL 与页面元素，动态段使用 TanStack Router 的 $param 语法。
 */
export const routeDefinitions: AppRouteDefinition[] = [
  { path: '/login', element: withPageBoundary('Login', <LoginPage />) },
  { path: '/server-select', element: withPageBoundary('ServerSelect', <ServerSelectPage />) },
  { path: '/setup', element: withPageBoundary('Setup', <SetupPage />) },
  { path: '/assistant', element: withPageBoundary('Assistant', <ChatPage />) },
  { path: '/assistant/sessions', element: withPageBoundary('AssistantSessions', <AssistantSessionsPage />) },
  { path: '/assistant/sessions/$conversationId', element: withPageBoundary('Assistant', <ChatPage />) },
  { path: '/assistant/context', element: withPageBoundary('AssistantContext', <AssistantContextPage />) },
  { path: '/workbench/projects', element: withPageBoundary('WorkbenchProjects', <WorkbenchProjectsPage />) },
  { path: '/workbench/editor', element: withPageBoundary('WorkbenchEditor', <CodingPage />) },
  { path: '/workbench/agents', element: withPageBoundary('WorkbenchAgents', <VibeCodingPage />) },
  { path: '/automations/overview', element: withPageBoundary('AutomationsOverview', <AutomationsOverviewPage />) },
  { path: '/automations/flows', element: withPageBoundary('AutomationsFlows', <WorkflowPage />) },
  { path: '/automations/schedules', element: withPageBoundary('AutomationsSchedules', <ScheduledTasksPage />) },
  { path: '/automations/executors', element: withPageBoundary('AutomationsExecutors', <SubAgentPage />) },
  { path: '/automations/runs', element: withPageBoundary('AutomationsRuns', <DiscussionsPage />) },
  { path: '/automations/runs/$id/collaboration', element: withPageBoundary('AutomationsCollaboration', <DiscussionsPage />) },
  { path: '/library/capabilities', element: withPageBoundary('LibraryCapabilities', <CapabilityLibraryPage />) },
  { path: '/library/capabilities/plugin/$pluginId/config', element: withPageBoundary('PluginConfig', <PluginConfigPage />) },
  { path: '/library/personas', element: withPageBoundary('LibraryPersonas', <PersonaLibraryPage />) },
  { path: '/library/knowledge', element: withPageBoundary('LibraryKnowledge', <KnowledgeLibraryPage />) },
  { path: '/library/voices', element: withPageBoundary('LibraryVoices', <TtsPage />) },
  { path: '/activity/overview', element: withPageBoundary('ActivityOverview', <DashboardPage />) },
  { path: '/activity/inbox', element: withPageBoundary('ActivityInbox', <InboxPage />) },
  { path: '/activity/usage', element: withPageBoundary('ActivityUsage', <BillingPage />) },
  { path: '/account', element: withPageBoundary('Account', <AccountPage />) },
  { path: '/settings/general', element: withPageBoundary('SettingsGeneral', <SettingsPage />) },
  { path: '/settings/models', element: withPageBoundary('SettingsModels', <SettingsPage />) },
  { path: '/settings/ai', element: withPageBoundary('SettingsAi', <SettingsPage />) },
  { path: '/settings/connections', element: withPageBoundary('SettingsConnections', <SettingsPage />) },
  { path: '/settings/data', element: withPageBoundary('SettingsData', <SettingsPage />) },
  { path: '/settings/security', element: withPageBoundary('SettingsSecurity', <SettingsPage />) },
  { path: '/settings/appearance', element: withPageBoundary('SettingsAppearance', <SettingsPage />) },
  { path: '/settings/usage', element: withPageBoundary('SettingsUsage', <SettingsPage />) },
  { path: '/chat', element: <Navigate to="/assistant" replace />, kind: 'redirect' },
  { path: '/chat/$conversationId', element: <LegacyConversationRedirect />, kind: 'redirect' },
  { path: '/dashboard', element: <Navigate to="/activity/overview" replace />, kind: 'redirect' },
  { path: '/settings', element: <Navigate to="/settings/general" replace />, kind: 'redirect' },
  { path: '/skills', element: <Navigate to="/library/capabilities?type=skill&view=installed" replace />, kind: 'redirect' },
  { path: '/skills/market', element: <Navigate to="/library/capabilities?type=skill&view=discover" replace />, kind: 'redirect' },
  { path: '/scheduled-tasks', element: <Navigate to="/automations/schedules" replace />, kind: 'redirect' },
  { path: '/plugins', element: <Navigate to="/library/capabilities?type=plugin&view=installed" replace />, kind: 'redirect' },
  { path: '/plugins/manage', element: <Navigate to="/library/capabilities?type=plugin&view=installed" replace />, kind: 'redirect' },
  { path: '/plugins/config/$pluginId', element: <LegacyPluginConfigRedirect />, kind: 'redirect' },
  { path: '/memory', element: <Navigate to="/library/knowledge?view=long-term" replace />, kind: 'redirect' },
  { path: '/experience', element: <Navigate to="/library/knowledge?view=experience" replace />, kind: 'redirect' },
  { path: '/billing', element: <Navigate to="/activity/usage" replace />, kind: 'redirect' },
  { path: '/user', element: <Navigate to="/account" replace />, kind: 'redirect' },
  { path: '/user-profile', element: <Navigate to="/account?section=profile" replace />, kind: 'redirect' },
  { path: '/dev/test', element: <ErrorBoundary name="Test"><DevTestRoute /></ErrorBoundary> },
  { path: '/workspace', element: <Navigate to="/workbench/projects" replace />, kind: 'redirect' },
  { path: '/coding', element: <Navigate to="/workbench/editor" replace />, kind: 'redirect' },
  { path: '/inbox', element: <Navigate to="/activity/inbox" replace />, kind: 'redirect' },
  { path: '/roles', element: <Navigate to="/library/personas?view=installed" replace />, kind: 'redirect' },
  { path: '/role-market', element: <Navigate to="/library/personas?view=discover" replace />, kind: 'redirect' },
  { path: '/tts', element: <Navigate to="/library/voices" replace />, kind: 'redirect' },
  { path: '/im', element: <Navigate to="/settings/connections?type=messaging" replace />, kind: 'redirect' },
  { path: '/workflows', element: <Navigate to="/automations/flows" replace />, kind: 'redirect' },
  { path: '/subagents', element: <Navigate to="/automations/executors" replace />, kind: 'redirect' },
  { path: '/vibe-coding', element: <Navigate to="/workbench/agents" replace />, kind: 'redirect' },
  { path: '/discussions', element: <Navigate to="/automations/runs" replace />, kind: 'redirect' },
  { path: '/discussions/$id', element: <LegacyDiscussionRedirect />, kind: 'redirect' },
  { path: '/pets', element: <Navigate to="/settings/appearance?section=companion" replace />, kind: 'redirect' },
  // 宠物悬浮窗路由（仅在桌面端 Electron 悬浮窗中使用）
  { path: '/pet-overlay', element: withPageBoundary('PetOverlay', <PetOverlayApp />) },
  // 引导窗口路由（桌面端首次启动配置后端 URL，无需认证）
  { path: '/onboarding', element: withPageBoundary('Onboarding', <OnboardingPage />) },
]

const rootRoute = createRootRoute({
  component: RootGuard,
  notFoundComponent: () => <Navigate to="/assistant" replace />,
})

// 根索引仅建立有效匹配，认证与默认落点统一由 RootGuard 决策。
const rootIndexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: () => null,
})

const workbenchRoutePaths = new Set([
  '/workbench/projects',
  '/workbench/editor',
  '/workbench/agents',
])

export const workbenchRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/workbench',
  component: WorkbenchShell,
})

export const workbenchChildRoutes = routeDefinitions
  .filter(({ path }) => workbenchRoutePaths.has(path))
  .map(({ path, element }) => createRoute({
    getParentRoute: () => workbenchRoute,
    path: path.slice('/workbench/'.length),
    component: () => element,
  }))

const childRoutes = [
  rootIndexRoute,
  workbenchRoute.addChildren(workbenchChildRoutes),
  ...routeDefinitions.filter(({ path }) => !workbenchRoutePaths.has(path)).map(({ path, element }) => createRoute({
    getParentRoute: () => rootRoute,
    path,
    component: () => element,
  })),
]

const routeTree = rootRoute.addChildren(childRoutes)

export const router = createRouter({ routeTree, history: createHashHistory() })

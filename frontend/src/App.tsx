import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import React, { Suspense, useEffect, useRef } from 'react'
import ErrorBoundary from '@/shared/components/ErrorBoundary/ErrorBoundary'
import { appLogger } from '@/shared/utils/logger'
import { useAppInitialization } from '@/shared/hooks/useAppInitialization'
import { useAuthStore } from '@/shared/store/authStore'
import { useThemeStore } from '@/shared/store/themeStore'
import { mark } from '@/shared/perf/metrics'
import { Skeleton } from '@/shared/components/ui/Skeleton'
import { SkipLink } from '@/shared/components/SkipLink/SkipLink'

// P2: Sidebar 懒加载，减少主包体积
const Sidebar = React.lazy(() => import('@/shared/components/Sidebar/Sidebar'))

const routerFutureConfig = {
  v7_startTransition: true,
  v7_relativeSplatPath: true,
}

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
const CommunicationPage = React.lazy(() => import('@/features/chat/CommunicationPage'))
const UserCenterPage = React.lazy(() => import('@/features/user/UserCenterPage'))
const ProfileEditorPage = React.lazy(() => import('@/features/user/ProfileEditorPage'))
const MarketplacePage = React.lazy(() => import('@/features/plugins/MarketplacePage'))
const TestPage = React.lazy(() => import('@/features/test/TestPage'))
const WorkspacePage = React.lazy(() => import('@/features/workspace/WorkspacePage'))
const CodingPage = React.lazy(() => import('@/features/coding/CodingPage'))
const InboxPage = React.lazy(() => import('@/features/inbox/InboxPage'))
const SkillMarketPage = React.lazy(() => import('@/features/skills/SkillMarketPage'))
const AgentListPage = React.lazy(() => import('@/features/agents/AgentListPage'))
const RolesPage = React.lazy(() => import('@/features/roles/RolesPage'))
const RoleMarketPage = React.lazy(() => import('@/features/marketplace/RoleMarketPage'))
const TtsPage = React.lazy(() => import('@/features/tts/TtsPage'))
const DataDashboard = React.lazy(() => import('@/features/data/DataDashboard'))
const ImChannelsPage = React.lazy(() => import('@/features/im/ImChannelsPage'))
const WorkflowPage = React.lazy(() => import('@/features/workflow/WorkflowPage'))
const SubAgentPage = React.lazy(() => import('@/features/subagents/SubAgentPage'))
const SoulPage = React.lazy(() => import('@/features/soul/SoulPage'))

function NavigationLogger() {
  const location = useLocation()

  useEffect(() => {
    appLogger.info({
      event: 'page_view',
      module: 'app',
      action: 'navigate',
      status: 'success',
      message: 'page visited',
      extra: { path: location.pathname },
    })
  }, [location.pathname])

  return null
}

function AppRoutes() {
  const location = useLocation()
  // 使用选择器精确订阅，避免整个 store 变化触发重渲染
  const isAuthenticated = useAuthStore(s => s.isAuthenticated)

  if (!isAuthenticated) {
    return (
      <Suspense fallback={<div className="loading-fallback"><Skeleton.Paragraph lines={3} /></div>}>
        <Routes>
          <Route path="/login" element={<ErrorBoundary name="Login"><LoginPage /></ErrorBoundary>} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </Suspense>
    )
  }

  return (
    <div className="app-container">
      <Suspense fallback={<div className="sidebar-skeleton" />}>
        <Sidebar />
      </Suspense>
      {/* 主内容区，skip-link 目标锚点 */}
      <main id="main-content" className="main-content">
        <Suspense fallback={<div className="loading-fallback"><Skeleton.Paragraph lines={4} /></div>}>
          {/* 使用 location.pathname 作为 key，触发 CSS 动画实现页面切换淡入 */}
          <div className="page-transition-wrapper" key={location.pathname}>
            <Routes>
              <Route path="/" element={<Navigate to="/chat" replace />} />
              <Route path="/login" element={<Navigate to="/chat" replace />} />
              <Route path="/chat" element={<ErrorBoundary name="Chat"><ChatPage /></ErrorBoundary>} />
              <Route path="/chat/:conversationId" element={<ErrorBoundary name="Chat"><ChatPage /></ErrorBoundary>} />
              <Route path="/dashboard" element={<ErrorBoundary name="Dashboard"><DashboardPage /></ErrorBoundary>} />
              <Route path="/settings" element={<ErrorBoundary name="Settings"><SettingsPage /></ErrorBoundary>} />
              <Route path="/skills" element={<ErrorBoundary name="Skills"><SkillsPage /></ErrorBoundary>} />
              <Route path="/skills/market" element={<ErrorBoundary name="SkillMarket"><SkillMarketPage /></ErrorBoundary>} />
              <Route path="/scheduled-tasks" element={<ErrorBoundary name="ScheduledTasks"><ScheduledTasksPage /></ErrorBoundary>} />
              <Route path="/plugins">
                <Route index element={<Navigate to="manage" replace />} />
                <Route path="manage" element={<ErrorBoundary name="Plugins"><PluginsPage /></ErrorBoundary>} />
                <Route path="config/:pluginId" element={<ErrorBoundary name="PluginConfig"><PluginConfigPage /></ErrorBoundary>} />
                <Route path="marketplace" element={<ErrorBoundary name="Marketplace"><MarketplacePage /></ErrorBoundary>} />
              </Route>
              <Route path="/marketplace" element={<Navigate to="/plugins/marketplace" replace />} />
              <Route path="/memory" element={<ErrorBoundary name="Memory"><MemoryPage /></ErrorBoundary>} />
              <Route path="/experience" element={<ErrorBoundary name="Experience"><ExperiencePage hideHeader /></ErrorBoundary>} />
              <Route path="/billing" element={<ErrorBoundary name="Billing"><BillingPage /></ErrorBoundary>} />
              <Route path="/communication" element={<ErrorBoundary name="Communication"><CommunicationPage /></ErrorBoundary>} />
              <Route path="/theme" element={<Navigate to="/settings?tab=appearance" replace />} />
              <Route path="/user" element={<ErrorBoundary name="UserCenter"><UserCenterPage /></ErrorBoundary>} />
              <Route path="/profile/edit" element={<ErrorBoundary name="ProfileEditor"><ProfileEditorPage /></ErrorBoundary>} />
              <Route path="/test" element={<ErrorBoundary name="Test"><TestPage /></ErrorBoundary>} />
              <Route path="/workspace" element={<ErrorBoundary name="Workspace"><WorkspacePage /></ErrorBoundary>} />
              <Route path="/coding" element={<ErrorBoundary name="Coding"><CodingPage /></ErrorBoundary>} />
              <Route path="/inbox" element={<ErrorBoundary name="Inbox"><InboxPage /></ErrorBoundary>} />
              <Route path="/agents" element={<ErrorBoundary name="Agents"><AgentListPage /></ErrorBoundary>} />
              <Route path="/roles" element={<ErrorBoundary name="Roles"><RolesPage /></ErrorBoundary>} />
              <Route path="/role-market" element={<ErrorBoundary name="RoleMarket"><RoleMarketPage /></ErrorBoundary>} />
              <Route path="/data" element={<ErrorBoundary name="Data"><DataDashboard /></ErrorBoundary>} />
              <Route path="/tts" element={<ErrorBoundary name="Tts"><TtsPage /></ErrorBoundary>} />
              <Route path="/im" element={<ErrorBoundary name="ImChannels"><ImChannelsPage /></ErrorBoundary>} />
            <Route path="/workflows" element={<ErrorBoundary name="Workflow"><WorkflowPage /></ErrorBoundary>} />
            <Route path="/subagents" element={<ErrorBoundary name="SubAgents"><SubAgentPage /></ErrorBoundary>} />
            <Route path="/soul" element={<ErrorBoundary name="Soul"><SoulPage /></ErrorBoundary>} />
            </Routes>
          </div>
        </Suspense>
      </main>
    </div>
  )
}

function App() {
  // 使用选择器精确订阅，避免整个 store 变化触发重渲染
  const isInitialized = useAuthStore(s => s.isInitialized)
  const { theme } = useThemeStore()
  const shellMarkedRef = useRef<boolean | null>(null)
  useAppInitialization()

  // P2: 认证状态解析后记录时间
  useEffect(() => {
    if (isInitialized) {
      mark('auth_resolved')
    }
  }, [isInitialized])

  // P2: 记录 App Shell 首次可见时间
  useEffect(() => {
    if (shellMarkedRef.current === null) {
      shellMarkedRef.current = true
      mark('app_shell_visible')
    }
  }, [])

  // 主题类名同步设置（壳层立即生效）
  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
  }, [theme])

  // P0: 始终渲染 App Shell，不再全屏白屏等待初始化完成
  // 壳层立即可见，认证状态决定路由内容
  return (
    <ErrorBoundary name="Root">
      <BrowserRouter future={routerFutureConfig}>
        {/* 可访问性：跳转到主内容链接 */}
        <SkipLink />
        <NavigationLogger />
        <AppRoutes />
      </BrowserRouter>
    </ErrorBoundary>
  )
}

export default App

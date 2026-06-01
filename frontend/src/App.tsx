import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import React, { Suspense, useEffect, useRef } from 'react'
import ErrorBoundary from '@/shared/components/ErrorBoundary/ErrorBoundary'
import { appLogger } from '@/shared/utils/logger'
import { useAppInitialization } from '@/shared/hooks/useAppInitialization'
import { useAuthStore } from '@/shared/store/authStore'
import { useThemeStore } from '@/shared/store/themeStore'
import { mark } from '@/shared/perf/metrics'

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
const ThemePage = React.lazy(() => import('@/features/theme/ThemePage'))
const UserCenterPage = React.lazy(() => import('@/features/user/UserCenterPage'))
const MarketplacePage = React.lazy(() => import('@/features/plugins/MarketplacePage'))
const TestPage = React.lazy(() => import('@/features/test/TestPage'))

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

function App() {
  const { isInitialized, isAuthenticated } = useAuthStore()
  const { theme } = useThemeStore()
  const shellMarkedRef = useRef(false)
  useAppInitialization()

  // P2: 记录 App Shell 首次可见时间
  if (!shellMarkedRef.current) {
    shellMarkedRef.current = true
    mark('app_shell_visible')
  }

  // P2: 认证状态解析后记录时间
  useEffect(() => {
    if (isInitialized) {
      mark('auth_resolved')
    }
  }, [isInitialized])

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
      <NavigationLogger />
      {!isAuthenticated ? (
        <Suspense fallback={<div className="loading-fallback">加载中...</div>}>
          <Routes>
            <Route path="/login" element={<ErrorBoundary name="Login"><LoginPage /></ErrorBoundary>} />
            <Route path="*" element={<Navigate to="/login" replace />} />
          </Routes>
        </Suspense>
      ) : (
        <div className="app-container">
          <Suspense fallback={<div className="sidebar-skeleton" />}>
            <Sidebar />
          </Suspense>
          <main className="main-content">
            <Suspense fallback={<div className="loading-fallback">加载中...</div>}>
              <Routes>
                <Route path="/" element={<Navigate to="/chat" replace />} />
                <Route path="/login" element={<Navigate to="/chat" replace />} />
                <Route path="/chat" element={<ErrorBoundary name="Chat"><ChatPage /></ErrorBoundary>} />
                <Route path="/chat/:conversationId" element={<ErrorBoundary name="Chat"><ChatPage /></ErrorBoundary>} />
                <Route path="/dashboard" element={<ErrorBoundary name="Dashboard"><DashboardPage /></ErrorBoundary>} />
                <Route path="/settings" element={<ErrorBoundary name="Settings"><SettingsPage /></ErrorBoundary>} />
                <Route path="/skills" element={<ErrorBoundary name="Skills"><SkillsPage /></ErrorBoundary>} />
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
                <Route path="/theme" element={<ErrorBoundary name="Theme"><ThemePage /></ErrorBoundary>} />
                <Route path="/user" element={<ErrorBoundary name="UserCenter"><UserCenterPage /></ErrorBoundary>} />
                <Route path="/test" element={<ErrorBoundary name="Test"><TestPage /></ErrorBoundary>} />
              </Routes>
            </Suspense>
          </main>
        </div>
      )}
    </BrowserRouter>
    </ErrorBoundary>
  )
}

export default App

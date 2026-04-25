import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import React, { Suspense, useEffect } from 'react'
import Sidebar from '@/shared/components/Sidebar/Sidebar'
import ErrorBoundary from '@/shared/components/ErrorBoundary/ErrorBoundary'
import { authAPI } from '@/shared/api/api'
import { appLogger } from '@/shared/utils/logger'
import { useAuthStore } from '@/shared/store/authStore'
import { useThemeStore } from '@/shared/store/themeStore'

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
const MarketplacePage = React.lazy(() => import('@/features/plugins/MarketplacePage'))

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
  const { isInitialized, isAuthenticated, setInitialized, setAuth, logout } = useAuthStore()
  const { theme } = useThemeStore()

  useEffect(() => {
    initializeApp()
  }, [])

  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
  }, [theme])

  const initializeApp = async () => {
    appLogger.info({
      event: 'app_initialize',
      module: 'app',
      action: 'initialize',
      status: 'start',
      message: 'app initialization started',
    })

    try {
      const meResponse = await authAPI.getMe()
      appLogger.info({
        event: 'app_initialize',
        module: 'app',
        action: 'session_validate',
        status: 'success',
        message: 'existing session validated',
      })
      setAuth({ username: meResponse.data?.username || 'user' }, null)
      setInitialized(true)
      return
    } catch (error) {
      const status = (error as { response?: { status?: number } })?.response?.status
      logout()
      appLogger.warning({
        event: 'app_initialize',
        module: 'app',
        action: 'session_validate',
        status: 'failure',
        message: 'session validation failed, redirecting to login',
        extra: { error: error instanceof Error ? error.message : String(error), status_code: status },
      })
    }

    // 未认证时标记初始化完成，由路由守卫跳转到登录页
    setInitialized(true)
  }

  if (!isInitialized) {
    return (
      <div style={{ 
        display: 'flex', 
        justifyContent: 'center', 
        alignItems: 'center', 
        height: '100vh',
        color: 'var(--color-text-secondary)',
        fontSize: '16px'
      }}>
        正在初始化应用...
      </div>
    )
  }

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
          <Sidebar />
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

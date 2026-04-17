import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import React, { Suspense, useEffect, useState } from 'react'
import Sidebar from '@/shared/components/Sidebar/Sidebar'
import { authAPI } from '@/shared/api/api'
import { appLogger } from '@/shared/utils/logger'
import { useAuthStore } from '@/shared/store/authStore'
import { useThemeStore } from '@/shared/store/themeStore'

const routerFutureConfig = {
  v7_startTransition: true,
  v7_relativeSplatPath: true,
}

const ChatPage = React.lazy(() => import('@/features/chat/ChatPage'))
const DashboardPage = React.lazy(() => import('@/features/dashboard/DashboardPage'))
const SettingsPage = React.lazy(() => import('@/features/settings/SettingsPage'))
const SkillsPage = React.lazy(() => import('@/features/skills/SkillsPage'))
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
  const { isInitialized, setInitialized, setAuth, logout } = useAuthStore()
  const { theme } = useThemeStore()
  const [authWarning, setAuthWarning] = useState<string | null>(null)

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
      setAuthWarning(null)
      setInitialized(true)
      return
    } catch (error) {
      const status = (error as { response?: { status?: number } })?.response?.status
      logout()
      setAuthWarning(status && status !== 401 ? '登录状态校验失败，请稍后刷新页面重试。' : '当前未检测到有效登录状态。')
      appLogger.warning({
        event: 'app_initialize',
        module: 'app',
        action: 'session_validate',
        status: 'failure',
        message: 'session validation failed',
        extra: { error: error instanceof Error ? error.message : String(error), status_code: status },
      })
    }

    const allowDevAutoLogin = import.meta.env.DEV && import.meta.env.VITE_ENABLE_DEV_AUTO_LOGIN === 'true'
    if (allowDevAutoLogin) {
      // 仅在环境变量中显式配置了测试凭证时才执行自动登录，避免硬编码敏感信息
      const testUsername = import.meta.env.VITE_TEST_USERNAME
      const testPassword = import.meta.env.VITE_TEST_PASSWORD
      if (testUsername && testPassword) {
        try {
          try {
            await authAPI.register(testUsername, testPassword)
          } catch (e) {
            // 用户已存在时忽略注册错误
          }

          const loginResponse = await authAPI.login(testUsername, testPassword)
          setAuth({ username: testUsername }, loginResponse.data.access_token || null)
          setAuthWarning(null)
          appLogger.info({
            event: 'app_initialize',
            module: 'app',
            action: 'auto_login',
            status: 'success',
            message: 'test user login succeeded',
          })
          setInitialized(true)
        } catch (error) {
          appLogger.error({
            event: 'app_initialize',
            module: 'app',
            action: 'auto_login',
            status: 'failure',
            message: 'app initialization failed',
            extra: { error: error instanceof Error ? error.message : String(error) },
          })
          setInitialized(true)
        }
      } else {
        setInitialized(true)
      }
    } else {
      setInitialized(true)
    }
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
    <BrowserRouter future={routerFutureConfig}>
      <NavigationLogger />
      <div className="app-container">
        <Sidebar />
        <main className="main-content">
          {authWarning && <div className="loading-fallback">{authWarning}</div>}
          <Suspense fallback={<div className="loading-fallback">加载中...</div>}>
            <Routes>
              <Route path="/" element={<Navigate to="/chat" replace />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/skills" element={<SkillsPage />} />
              <Route path="/plugins">
                <Route index element={<Navigate to="manage" replace />} />
                <Route path="manage" element={<PluginsPage />} />
                <Route path="config/:pluginId" element={<PluginConfigPage />} />
              </Route>
              <Route path="/marketplace" element={<MarketplacePage />} />
              <Route path="/memory" element={<MemoryPage />} />
              <Route path="/experience" element={<ExperiencePage hideHeader />} />
              <Route path="/billing" element={<BillingPage />} />
              <Route path="/communication" element={<CommunicationPage />} />
            </Routes>
          </Suspense>
        </main>
      </div>
    </BrowserRouter>
  )
}

export default App

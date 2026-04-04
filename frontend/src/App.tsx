import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { useEffect } from 'react'
import ChatPage from '@/features/chat/ChatPage'
import DashboardPage from '@/features/dashboard/DashboardPage'
import SettingsPage from '@/features/settings/SettingsPage'
import SkillsPage from '@/features/skills/SkillsPage'
import PluginsPage from '@/features/plugins/PluginsPage'
import MemoryPage from '@/features/memory/MemoryPage'
import BillingPage from '@/features/billing/BillingPage'
import ExperiencePage from '@/features/experiences/ExperiencePage'
import CommunicationPage from '@/features/chat/CommunicationPage'
import Sidebar from '@/shared/components/Sidebar/Sidebar'
import { authAPI } from '@/shared/api/api'
import { appLogger } from '@/shared/utils/logger'
import { useAuthStore } from '@/shared/store/authStore'

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

  useEffect(() => {
    initializeApp()
  }, [])

  const initializeApp = async () => {
    appLogger.info({
      event: 'app_initialize',
      module: 'app',
      action: 'initialize',
      status: 'start',
      message: 'app initialization started',
    })

    const token = localStorage.getItem('token')
    const username = localStorage.getItem('username')
    if (token) {
      try {
        await authAPI.getMe()
        appLogger.info({
          event: 'app_initialize',
          module: 'app',
          action: 'token_validate',
          status: 'success',
          message: 'existing token validated',
        })
        setAuth(username ? { username } : { username: 'user' }, token)
        setInitialized(true)
        return
      } catch (error) {
        appLogger.warning({
          event: 'app_initialize',
          module: 'app',
          action: 'token_validate',
          status: 'failure',
          message: 'token validation failed, clear local auth',
          extra: { error: error instanceof Error ? error.message : String(error) },
        })
        logout()
      }
    }

    try {
      const testUser = {
        username: 'test_user_default',
        password: 'test_password_123'
      }

      try {
        await authAPI.register(testUser.username, testUser.password)
      } catch (e) {
      }

      const loginResponse = await authAPI.login(testUser.username, testUser.password)
      setAuth({ username: testUser.username }, loginResponse.data.access_token)
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
    <BrowserRouter>
      <NavigationLogger />
      <div className="app-container">
        <Sidebar />
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Navigate to="/chat" replace />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/skills" element={<SkillsPage />} />
            <Route path="/plugins" element={<PluginsPage />} />
            <Route path="/memory" element={<MemoryPage />} />
            <Route path="/experience" element={<ExperiencePage hideHeader />} />
            <Route path="/billing" element={<BillingPage />} />
            <Route path="/communication" element={<CommunicationPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}

export default App

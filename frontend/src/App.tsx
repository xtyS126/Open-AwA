import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'
import ChatPage from './pages/ChatPage'
import DashboardPage from './pages/DashboardPage'
import SettingsPage from './pages/SettingsPage'
import SkillsPage from './pages/SkillsPage'
import PluginsPage from './pages/PluginsPage'
import MemoryPage from './pages/MemoryPage'
import BillingPage from './pages/BillingPage'
import ExperiencePage from './pages/ExperiencePage'
import CommunicationPage from './pages/CommunicationPage'
import Sidebar from './components/Sidebar'
import { authAPI } from './services/api'
import { appLogger } from './services/logger'

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
  const [initialized, setInitialized] = useState(false)

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
        localStorage.removeItem('token')
        localStorage.removeItem('username')
      }
    }

    try {
      const testUser = {
        username: 'test_user_' + Date.now(),
        password: 'test_password_123'
      }

      try {
        await authAPI.register(testUser.username, testUser.password)
      } catch (e) {
      }

      const loginResponse = await authAPI.login(testUser.username, testUser.password)
      localStorage.setItem('token', loginResponse.data.access_token)
      localStorage.setItem('username', testUser.username)
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

  if (!initialized) {
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

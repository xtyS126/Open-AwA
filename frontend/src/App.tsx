import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
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

function App() {
  const [initialized, setInitialized] = useState(false)

  useEffect(() => {
    initializeApp()
  }, [])

  const initializeApp = async () => {
    const token = localStorage.getItem('token')
    if (token) {
      try {
        await authAPI.getMe()
        setInitialized(true)
        return
      } catch (error) {
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
      
      setInitialized(true)
    } catch (error) {
      console.error('Failed to initialize app:', error)
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

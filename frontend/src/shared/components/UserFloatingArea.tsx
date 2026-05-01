import { useNavigate } from 'react-router-dom'
import { LogOut } from 'lucide-react'
import { useAuthStore } from '@/shared/store/authStore'
import { authAPI } from '@/shared/api/api'
import { appLogger } from '@/shared/utils/logger'
import styles from './UserFloatingArea.module.css'

interface UserFloatingAreaProps {
  collapsed?: boolean;
}

export function UserFloatingArea({ collapsed = false }: UserFloatingAreaProps) {
  const navigate = useNavigate()
  const { user, logout } = useAuthStore()

  const handleLogout = async () => {
    try {
      await authAPI.logout()
    } catch (error) {
      appLogger.warning({
        event: 'logout_api_failed',
        module: 'auth',
        message: 'logout api call failed',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
    }
    logout()
    navigate('/login', { replace: true })
  }

  const handleNavigateToUser = () => {
    navigate('/user')
  }

  if (!user) return null

  const initial = (user.username || 'U')[0].toUpperCase()

  return (
    <div className={`${styles['floating-area']} ${collapsed ? styles['collapsed'] : ''}`}>
      <button
        className={styles['user-btn']}
        onClick={handleNavigateToUser}
        title="用户中心"
      >
        <div className={styles['avatar']}>{initial}</div>
        {!collapsed && <span className={styles['username']}>{user.username}</span>}
      </button>
      <button
        className={styles['logout-btn']}
        onClick={handleLogout}
        title="退出登录"
      >
        <LogOut size={16} />
      </button>
    </div>
  )
}


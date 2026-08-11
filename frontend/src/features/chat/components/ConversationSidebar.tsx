import { memo, useState } from 'react'
import { ChevronDown, LogOut, PanelLeft, Plus, UserRound } from 'lucide-react'
import { useI18nStore } from '@/i18n'
import { useNavigate } from '@/shared/routing'
import { useAuthStore } from '@/shared/store/authStore'
import { authAPI } from '@/shared/api/api'
import { appLogger } from '@/shared/utils/logger'
import ConversationManager, { type ConversationManagerProps } from './ConversationManager'
import styles from './ConversationSidebar.module.css'

interface ConversationSidebarProps extends ConversationManagerProps {
  open: boolean
  onToggle: () => void
  onCreateConversation: () => void
}

/** 移动端侧栏中的账户入口。 */
function MobileUserCard() {
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const { t } = useI18nStore()
  const [open, setOpen] = useState(false)

  if (!user) {
    return null
  }

  const initial = (user.username || 'U')[0].toUpperCase()

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

  return (
    <div className={styles['user-card']}>
      <button
        type="button"
        className={styles['user-card-btn']}
        onClick={() => setOpen((current) => !current)}
        aria-label={t('user.center')}
        aria-expanded={open}
        data-testid="history-user-card"
      >
        <span className={styles['user-card-avatar']}>{initial}</span>
        <span className={styles['user-card-name']}>{user.username}</span>
        <ChevronDown size={14} className={styles['user-card-chevron']} />
      </button>
      {open && (
        <>
          <div
            className={styles['user-card-overlay']}
            data-testid="history-user-card-overlay"
            onClick={() => setOpen(false)}
          />
          <div
            className={styles['user-card-menu']}
            role="menu"
            aria-label={t('user.center')}
            data-testid="history-user-card-menu"
          >
            <button
              type="button"
              role="menuitem"
              className={styles['user-card-menu-item']}
              onClick={() => {
                setOpen(false)
                navigate('/account')
              }}
            >
              <UserRound size={16} />
              {t('user.center')}
            </button>
            <button
              type="button"
              role="menuitem"
              className={styles['user-card-menu-item']}
              onClick={handleLogout}
            >
              <LogOut size={16} />
              {t('user.logout')}
            </button>
          </div>
        </>
      )}
    </div>
  )
}

/** 侧栏只提供布局、移动端账户入口与页头，列表交互由 ConversationManager 承担。 */
function ConversationSidebar({
  open,
  onToggle,
  onCreateConversation,
  ...managerProps
}: ConversationSidebarProps) {
  const t = useI18nStore((state) => state.t)

  return (
    <aside className={`${styles.sidebar} ${open ? '' : styles.closed}`.trim()} aria-label="聊天历史侧边栏">
      <MobileUserCard />
      <div className={styles.header}>
        <span className={styles.title}>{t('chat.history.title')}</span>
        <div className={styles.headerActions}>
          <button className={styles.iconButton} type="button" onClick={onCreateConversation} aria-label={t('chat.history.newChat')}>
            <Plus size={16} />
          </button>
          <button className={styles.iconButton} type="button" onClick={onToggle} aria-label={open ? t('chat.collapseHistory') : t('chat.expandHistory')}>
            <PanelLeft size={16} />
          </button>
        </div>
      </div>
      <ConversationManager {...managerProps} />
    </aside>
  )
}

export default memo(ConversationSidebar)

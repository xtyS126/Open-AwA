import {
  type KeyboardEvent as ReactKeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import {
  ChevronDown,
  CircleHelp,
  LogOut,
  Search,
  Server,
  Settings,
  UserRound,
  X,
} from 'lucide-react'
import { shallow } from 'zustand/shallow'
import { useI18nStore } from '@/i18n'
import { authAPI } from '@/shared/api/authApi'
import { BrandMark } from '@/shared/components/BrandMark/BrandMark'
import { navigationManifest } from '@/shared/navigation/navigationManifest'
import { useNavigate } from '@/shared/routing'
import { useAuthStore } from '@/shared/store/authStore'
import { useIssueFeedbackStore } from '@/shared/store/issueFeedbackStore'
import { appLogger } from '@/shared/utils/logger'
import styles from './GlobalTopBar.module.css'

interface SearchCommand {
  id: string
  label: string
  description: string
  path: string
}

/**
 * 为已登录壳层提供搜索、系统初始化状态和账户操作。
 */
export default function GlobalTopBar() {
  const navigate = useNavigate()
  const t = useI18nStore((state) => state.t)
  const { user, isSystemInitialized, logout } = useAuthStore((state) => ({
    user: state.user,
    isSystemInitialized: state.isSystemInitialized,
    logout: state.logout,
  }), shallow)
  const [searchOpen, setSearchOpen] = useState(false)
  const [accountOpen, setAccountOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [activeCommandIndex, setActiveCommandIndex] = useState(0)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const searchTriggerRef = useRef<HTMLButtonElement>(null)
  const searchDialogRef = useRef<HTMLElement>(null)
  const searchReturnFocusRef = useRef<HTMLElement | null>(null)
  const wasSearchOpenRef = useRef(false)
  const accountAreaRef = useRef<HTMLDivElement>(null)
  const accountTriggerRef = useRef<HTMLButtonElement>(null)
  const accountMenuRef = useRef<HTMLDivElement>(null)
  const wasAccountOpenRef = useRef(false)
  const shouldRestoreAccountFocusRef = useRef(true)

  const commands = useMemo<SearchCommand[]>(() => {
    const domainCommands = navigationManifest.domains.flatMap((domain) => [
      {
        id: `domain-${domain.id}`,
        label: t(domain.labelKey),
        description: '工作域',
        path: domain.canonicalPath,
      },
      ...domain.children.map((child) => ({
        id: `${domain.id}-${child.id}`,
        label: t(child.labelKey),
        description: t(domain.labelKey),
        path: child.canonicalPath,
      })),
    ])

    return [
      ...domainCommands,
      { id: 'account', label: '账户', description: '个人信息与画像', path: '/account' },
      { id: 'settings', label: '设置', description: '应用与服务配置', path: '/settings/general' },
    ]
  }, [t])

  const filteredCommands = useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase()
    if (!keyword) return commands
    return commands.filter((command) => (
      command.label.toLocaleLowerCase().includes(keyword)
      || command.description.toLocaleLowerCase().includes(keyword)
    ))
  }, [commands, query])

  const openSearch = useCallback((trigger?: HTMLElement | null) => {
    if (!wasSearchOpenRef.current) {
      searchReturnFocusRef.current = trigger ?? searchTriggerRef.current
    }
    setSearchOpen(true)
    shouldRestoreAccountFocusRef.current = false
    setAccountOpen(false)
  }, [])

  const closeSearch = useCallback(() => {
    setSearchOpen(false)
  }, [])

  const closeAccount = useCallback((restoreFocus = true) => {
    shouldRestoreAccountFocusRef.current = restoreFocus
    setAccountOpen(false)
  }, [])

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === 'k') {
        event.preventDefault()
        openSearch(document.activeElement instanceof HTMLElement ? document.activeElement : null)
        return
      }

      const target = event.target
      const isEditableTarget = target instanceof HTMLElement && (
        target.isContentEditable
        || target.tagName === 'INPUT'
        || target.tagName === 'TEXTAREA'
        || target.tagName === 'SELECT'
      )
      if (event.key === '/' && !event.ctrlKey && !event.metaKey && !event.altKey && !isEditableTarget) {
        event.preventDefault()
        openSearch(document.activeElement instanceof HTMLElement ? document.activeElement : null)
        return
      }
      if (event.key === 'Escape') {
        closeSearch()
        closeAccount()
      }
    }
    window.addEventListener('keydown', handleShortcut)
    return () => window.removeEventListener('keydown', handleShortcut)
  }, [closeAccount, closeSearch, openSearch])

  useEffect(() => {
    if (searchOpen) {
      wasSearchOpenRef.current = true
      const focusTimer = window.setTimeout(() => searchInputRef.current?.focus(), 0)
      return () => window.clearTimeout(focusTimer)
    }

    if (wasSearchOpenRef.current) {
      wasSearchOpenRef.current = false
      setQuery('')
      setActiveCommandIndex(0)
      const returnTarget = searchReturnFocusRef.current
      searchReturnFocusRef.current = null
      const focusTimer = window.setTimeout(() => {
        if (returnTarget?.isConnected) {
          returnTarget.focus()
        } else {
          searchTriggerRef.current?.focus()
        }
      }, 0)
      return () => window.clearTimeout(focusTimer)
    }
  }, [searchOpen])

  useEffect(() => {
    if (accountOpen) {
      wasAccountOpenRef.current = true
      shouldRestoreAccountFocusRef.current = true
      const focusTimer = window.setTimeout(() => {
        accountMenuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus()
      }, 0)
      const handleOutsideMouseDown = (event: MouseEvent) => {
        if (event.target instanceof Node && !accountAreaRef.current?.contains(event.target)) {
          closeAccount(false)
        }
      }
      document.addEventListener('mousedown', handleOutsideMouseDown)
      return () => {
        window.clearTimeout(focusTimer)
        document.removeEventListener('mousedown', handleOutsideMouseDown)
      }
    }

    if (wasAccountOpenRef.current) {
      wasAccountOpenRef.current = false
      const shouldRestoreFocus = shouldRestoreAccountFocusRef.current
      shouldRestoreAccountFocusRef.current = true
      if (shouldRestoreFocus) {
        const focusTimer = window.setTimeout(() => accountTriggerRef.current?.focus(), 0)
        return () => window.clearTimeout(focusTimer)
      }
    }
  }, [accountOpen, closeAccount])

  useEffect(() => {
    setActiveCommandIndex(0)
  }, [filteredCommands])

  const runCommand = (command: SearchCommand) => {
    closeSearch()
    void navigate(command.path)
  }

  const handleSearchKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (filteredCommands.length === 0) {
      if (event.key === 'Escape') closeSearch()
      return
    }

    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActiveCommandIndex((current) => (current + 1) % filteredCommands.length)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActiveCommandIndex((current) => (
        current - 1 + filteredCommands.length
      ) % filteredCommands.length)
    } else if (event.key === 'Enter') {
      event.preventDefault()
      runCommand(filteredCommands[activeCommandIndex] ?? filteredCommands[0])
    } else if (event.key === 'Escape') {
      event.preventDefault()
      closeSearch()
    }
  }

  const handleSearchDialogKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key !== 'Tab') return

    const focusableElements = Array.from(
      searchDialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), [href], [tabindex]',
      ) ?? [],
    ).filter((element) => element.tabIndex >= 0)
    const firstElement = focusableElements[0]
    const lastElement = focusableElements[focusableElements.length - 1]
    if (!firstElement || !lastElement) return

    const activeElement = document.activeElement
    if (event.shiftKey && (activeElement === firstElement || !searchDialogRef.current?.contains(activeElement))) {
      event.preventDefault()
      lastElement.focus()
    } else if (!event.shiftKey && (activeElement === lastElement || !searchDialogRef.current?.contains(activeElement))) {
      event.preventDefault()
      firstElement.focus()
    }
  }

  const handleAccountTriggerKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    event.preventDefault()
    shouldRestoreAccountFocusRef.current = true
    setAccountOpen(true)
    closeSearch()
  }

  const handleAccountMenuKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const menuItems = Array.from(
      accountMenuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [],
    )
    if (menuItems.length === 0) return

    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      closeAccount()
      return
    }

    const currentIndex = Math.max(menuItems.indexOf(document.activeElement as HTMLElement), 0)
    let nextIndex: number | null = null
    if (event.key === 'ArrowDown') {
      nextIndex = (currentIndex + 1) % menuItems.length
    } else if (event.key === 'ArrowUp') {
      nextIndex = (currentIndex - 1 + menuItems.length) % menuItems.length
    } else if (event.key === 'Home') {
      nextIndex = 0
    } else if (event.key === 'End') {
      nextIndex = menuItems.length - 1
    }

    if (nextIndex !== null) {
      event.preventDefault()
      menuItems[nextIndex]?.focus()
    }
  }

  const navigateFromMenu = (path: string) => {
    closeAccount(false)
    void navigate(path)
  }

  const openFeedback = () => {
    closeAccount(false)
    useIssueFeedbackStore.getState().open()
  }

  const handleLogout = async () => {
    closeAccount(false)
    try {
      await authAPI.logout()
    } catch (error) {
      appLogger.warning({
        event: 'logout_api_failed',
        module: 'auth',
        message: '退出接口调用失败，继续清理本地会话',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
    }
    logout()
    void navigate('/login', { replace: true })
  }

  const initial = (user?.nickname || user?.username || 'U').slice(0, 1).toLocaleUpperCase()
  const systemReady = isSystemInitialized === true

  return (
    <header className={styles.topBar}>
      <button
        type="button"
        className={styles.brandEntry}
        aria-label="前往 Open-AwA 助手"
        onClick={() => {
          setAccountOpen(false)
          closeSearch()
          void navigate('/assistant')
        }}
      >
        <BrandMark size={34} decorative />
      </button>

      <button
        ref={searchTriggerRef}
        type="button"
        className={styles.searchTrigger}
        aria-label="打开全局搜索"
        onClick={(event) => openSearch(event.currentTarget)}
      >
        <Search size={17} aria-hidden="true" />
        <span className={styles.searchText}>搜索页面与功能</span>
        <kbd>Ctrl K</kbd>
      </button>

      <div className={styles.spacer} />

      <div
        className={`${styles.status} ${systemReady ? styles.ready : styles.notReady}`}
        aria-label={`系统状态：${systemReady ? '系统已就绪' : '系统未初始化'}`}
      >
        <span className={styles.statusDot} aria-hidden="true" />
        <span>{systemReady ? '系统已就绪' : '系统未初始化'}</span>
      </div>

      <div ref={accountAreaRef} className={styles.accountArea}>
        <button
          ref={accountTriggerRef}
          type="button"
          className={styles.accountTrigger}
          aria-label="打开账户菜单"
          aria-haspopup="menu"
          aria-controls="global-account-menu"
          aria-expanded={accountOpen}
          onKeyDown={handleAccountTriggerKeyDown}
          onClick={() => {
            shouldRestoreAccountFocusRef.current = true
            setAccountOpen((open) => !open)
            closeSearch()
          }}
        >
          <span className={styles.avatar}>{initial}</span>
          <span className={styles.username}>{user?.nickname || user?.username}</span>
          <ChevronDown size={15} aria-hidden="true" />
        </button>

        {accountOpen && (
          <div
            ref={accountMenuRef}
            id="global-account-menu"
            className={styles.accountMenu}
            role="menu"
            aria-label="账户菜单"
            onKeyDown={handleAccountMenuKeyDown}
          >
            <button type="button" role="menuitem" onClick={() => navigateFromMenu('/account')}>
              <UserRound size={16} aria-hidden="true" />
              账户
            </button>
            <button type="button" role="menuitem" onClick={() => navigateFromMenu('/settings/general')}>
              <Settings size={16} aria-hidden="true" />
              设置
            </button>
            <button type="button" role="menuitem" onClick={() => navigateFromMenu('/server-select')}>
              <Server size={16} aria-hidden="true" />
              切换服务器
            </button>
            <button type="button" role="menuitem" onClick={openFeedback}>
              <CircleHelp size={16} aria-hidden="true" />
              问题反馈
            </button>
            <div className={styles.menuDivider} />
            <button type="button" role="menuitem" className={styles.logoutItem} onClick={() => void handleLogout()}>
              <LogOut size={16} aria-hidden="true" />
              退出登录
            </button>
          </div>
        )}
      </div>

      {searchOpen && (
        <div className={styles.overlay} onMouseDown={closeSearch}>
          <section
            ref={searchDialogRef}
            className={styles.palette}
            role="dialog"
            aria-modal="true"
            aria-label="全局搜索"
            onKeyDown={handleSearchDialogKeyDown}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className={styles.searchField}>
              <Search size={18} aria-hidden="true" />
              <input
                ref={searchInputRef}
                type="search"
                role="combobox"
                aria-label="搜索页面与功能"
                aria-autocomplete="list"
                aria-controls="global-command-list"
                aria-expanded="true"
                aria-activedescendant={filteredCommands.length > 0
                  ? `global-command-${filteredCommands[activeCommandIndex]?.id ?? filteredCommands[0].id}`
                  : undefined}
                placeholder="输入工作域、页面或设置名称"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={handleSearchKeyDown}
              />
              <button type="button" aria-label="关闭全局搜索" onClick={closeSearch}>
                <X size={17} aria-hidden="true" />
              </button>
            </div>
            <div
              id="global-command-list"
              className={styles.commandList}
              role="listbox"
              aria-label="搜索结果"
            >
              {filteredCommands.length > 0 ? filteredCommands.map((command, index) => (
                <button
                  key={command.id}
                  id={`global-command-${command.id}`}
                  type="button"
                  role="option"
                  aria-selected={index === activeCommandIndex}
                  className={`${styles.command} ${index === activeCommandIndex ? styles.commandActive : ''}`}
                  aria-label={command.label}
                  tabIndex={-1}
                  onMouseMove={() => setActiveCommandIndex(index)}
                  onClick={() => runCommand(command)}
                >
                  <span>{command.label}</span>
                  <small>{command.description}</small>
                </button>
              )) : (
                <p className={styles.empty}>没有匹配的页面或功能</p>
              )}
            </div>
          </section>
        </div>
      )}
    </header>
  )
}

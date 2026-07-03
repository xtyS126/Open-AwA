/**
 * Vibe Coding 主页面 —— 通过 ACP 调用本地 vibe coding 应用。
 *
 * 三栏布局：
 *   左栏（secondarySidebar）：AgentSelector + SessionList + NotificationList
 *   中栏（main children）：ACP 会话面板 / 终端面板（占位实现）
 *   右栏：文件预览面板（占位实现）
 *
 * 状态管理：本地 useState + useEffect，mount 时拉取 agents/sessions/notifications，
 * 通知列表通过 EventSource 订阅 /api/notifications/stream 长连接。
 */
import { useCallback, useEffect, useState } from 'react'
import { Plus } from 'lucide-react'
import PageLayout from '@/shared/components/PageLayout/PageLayout'
import { useI18nStore } from '@/i18n'
import { appLogger } from '@/shared/utils/logger'
import {
  listAgents,
  listSessions,
  createSession,
  closeSession,
  type AcpAgent,
  type AcpSession,
} from '@/shared/api/acpApi'
import {
  listNotifications,
  type NotificationItem,
} from '@/shared/api/notificationsApi'
import AgentSelector from './components/AgentSelector'
import SessionList from './components/SessionList'
import NotificationList from './components/NotificationList'
import AcpSessionPanel from './components/AcpSessionPanel'
import TerminalPane from './components/TerminalPane'
import FilePreviewPane from './components/FilePreviewPane'
import styles from './VibeCodingPage.module.css'

/** 通知列表保留的最大条数 */
const MAX_NOTIFICATIONS = 50

/** 中栏面板类型 —— ACP 会话面板或终端面板 */
type ActivePane = 'acp' | 'terminal'

/** 终端面板使用的工作目录：选中会话则用其 cwd，否则回退到当前工作目录 */
function resolveTerminalCwd(sessions: AcpSession[], selectedSessionId: string | null): string {
  if (selectedSessionId) {
    const matched = sessions.find((s) => s.session_id === selectedSessionId)
    if (matched?.cwd) return matched.cwd
  }
  return '.'
}

function VibeCodingPage() {
  const { t } = useI18nStore()
  const [agents, setAgents] = useState<AcpAgent[]>([])
  const [sessions, setSessions] = useState<AcpSession[]>([])
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const [selectedAgent, setSelectedAgent] = useState<string>('')
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  const [activePane, setActivePane] = useState<ActivePane>('acp')
  const [creating, setCreating] = useState<boolean>(false)
  const [error, setError] = useState<string>('')
  // 右栏文件预览：外部传入的文件路径与网页预览端口（由 FilePreviewPane 内部输入框驱动，
  // 未来接入文件树后可通过 setter 编程式设置）
  const [selectedFilePath, _setSelectedFilePath] = useState<string | null>(null)
  const [previewPort, _setPreviewPort] = useState<number | null>(null)

  /** mount 时拉取 agents / sessions / notifications，并建立通知 SSE 订阅 */
  useEffect(() => {
    let eventSource: EventSource | null = null

    const loadInitial = async () => {
      try {
        const [agentsRes, sessionsRes, notifRes] = await Promise.all([
          listAgents(),
          listSessions(),
          listNotifications(MAX_NOTIFICATIONS),
        ])
        setAgents(agentsRes.agents)
        setSessions(sessionsRes.sessions)
        setNotifications(notifRes.notifications)
        // 默认选中第一个可用 agent
        const firstAvailable = agentsRes.agents.find((a) => a.available)
        if (firstAvailable) {
          setSelectedAgent(firstAvailable.id)
        }
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e)
        appLogger.error({
          event: 'vibe_coding_init_failed',
          module: 'vibe-coding',
          action: 'init',
          status: 'failure',
          message: 'Vibe Coding 初始化失败',
          extra: { error: message },
        })
        setError(message)
      }
    }

    void loadInitial()

    // 订阅通知流 —— 使用 withCredentials 携带 Cookie 认证
    try {
      eventSource = new EventSource('/api/notifications/stream', { withCredentials: true })
      eventSource.onmessage = (event) => {
        try {
          const item = JSON.parse(event.data) as NotificationItem
          if (!item || typeof item.id !== 'string') return
          setNotifications((prev) => {
            // 去重并限制条数，最新通知置顶
            const filtered = prev.filter((n) => n.id !== item.id)
            return [item, ...filtered].slice(0, MAX_NOTIFICATIONS)
          })
        } catch (e) {
          appLogger.warning({
            event: 'vibe_coding_notification_parse_failed',
            module: 'vibe-coding',
            action: 'sse',
            status: 'warning',
            message: '通知 SSE 解析失败',
            extra: { error: e instanceof Error ? e.message : String(e) },
          })
        }
      }
      eventSource.onerror = () => {
        appLogger.warning({
          event: 'vibe_coding_notification_stream_error',
          module: 'vibe-coding',
          action: 'sse',
          status: 'warning',
          message: '通知 SSE 连接错误',
        })
      }
    } catch (e) {
      appLogger.warning({
        event: 'vibe_coding_notification_stream_init_failed',
        module: 'vibe-coding',
        action: 'sse',
        status: 'warning',
        message: '通知 SSE 初始化失败',
        extra: { error: e instanceof Error ? e.message : String(e) },
      })
    }

    return () => {
      if (eventSource) {
        eventSource.close()
        eventSource = null
      }
    }
  }, [])

  /** 创建新会话 —— 调用 createSession 后追加到列表并选中 */
  const handleCreateSession = useCallback(async () => {
    if (!selectedAgent) {
      setError(t('vibeCoding.selectAgent'))
      return
    }
    setCreating(true)
    setError('')
    try {
      const result = await createSession(selectedAgent, '.')
      const newSession: AcpSession = {
        session_id: result.session_id,
        agent: selectedAgent,
        cwd: '.',
        created_at: new Date().toISOString(),
      }
      setSessions((prev) => [...prev, newSession])
      setSelectedSessionId(result.session_id)
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e)
      appLogger.error({
        event: 'vibe_coding_create_session_failed',
        module: 'vibe-coding',
        action: 'create',
        status: 'failure',
        message: '创建 ACP 会话失败',
        extra: { agent: selectedAgent, error: message },
      })
      setError(message)
    } finally {
      setCreating(false)
    }
  }, [selectedAgent, t])

  /** 关闭会话 —— 调用 closeSession 后从列表中移除 */
  const handleCloseSession = useCallback(async (sessionId: string) => {
    try {
      await closeSession(sessionId)
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId))
      setSelectedSessionId((prev) => (prev === sessionId ? null : prev))
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e)
      appLogger.error({
        event: 'vibe_coding_close_session_failed',
        module: 'vibe-coding',
        action: 'close',
        status: 'failure',
        message: '关闭 ACP 会话失败',
        extra: { session_id: sessionId, error: message },
      })
      setError(message)
    }
  }, [])

  /** 选中会话回调 */
  const handleSelectSession = useCallback((sessionId: string) => {
    setSelectedSessionId(sessionId)
  }, [])

  return (
    <PageLayout
      title={t('vibeCoding.title')}
      className={styles['vibe-page']}
      secondarySidebar={
        <aside className={styles['sidebar']}>
          <div className={styles['sidebar-section']}>
            <AgentSelector
              agents={agents}
              value={selectedAgent}
              onChange={setSelectedAgent}
            />
            <button
              type="button"
              className={styles['create-btn']}
              onClick={() => { void handleCreateSession() }}
              disabled={creating || !selectedAgent}
            >
              <Plus size={14} />
              {creating ? t('app.loading') : t('vibeCoding.createSession')}
            </button>
          </div>

          <div className={styles['sidebar-section']}>
            <span className={styles['sidebar-section-title']}>
              {t('vibeCoding.sessions')}
            </span>
            <SessionList
              sessions={sessions}
              selectedId={selectedSessionId}
              onSelect={handleSelectSession}
              onClose={(id) => { void handleCloseSession(id) }}
            />
          </div>

          <div className={styles['sidebar-section']}>
            <span className={styles['sidebar-section-title']}>
              {t('vibeCoding.notifications')}
            </span>
            <NotificationList notifications={notifications} />
          </div>
        </aside>
      }
    >
      <div className={styles['content']}>
        {/* 中栏：ACP 会话面板 / 终端面板切换 */}
        <div className={styles['center-pane']}>
          <div className={styles['segmented']} role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={activePane === 'acp'}
              className={`${styles['segmented-btn']} ${activePane === 'acp' ? styles['active'] : ''}`}
              onClick={() => setActivePane('acp')}
            >
              {t('vibeCoding.acpPanel')}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activePane === 'terminal'}
              className={`${styles['segmented-btn']} ${activePane === 'terminal' ? styles['active'] : ''}`}
              onClick={() => setActivePane('terminal')}
            >
              {t('vibeCoding.terminalPanel')}
            </button>
          </div>

          {error && <div className={styles['error-text']}>{error}</div>}

          {/* 中栏面板内容：ACP 模式渲染 AcpSessionPanel / Terminal 模式渲染 TerminalPane */}
          {activePane === 'terminal' ? (
            <TerminalPane cwd={resolveTerminalCwd(sessions, selectedSessionId)} />
          ) : (
            <AcpSessionPanel
              sessionId={selectedSessionId}
              cwd={resolveTerminalCwd(sessions, selectedSessionId)}
            />
          )}
        </div>

        {/* 右栏：文件预览面板 */}
        <aside className={styles['right-pane']}>
          <FilePreviewPane filePath={selectedFilePath} previewPort={previewPort} />
        </aside>
      </div>
    </PageLayout>
  )
}

export default VibeCodingPage

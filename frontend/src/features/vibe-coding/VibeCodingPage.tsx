/**
 * Vibe Coding 主页面 —— 通过 ACP 调用本地 vibe coding 应用。
 *
 * 三栏布局：
 *   左栏（secondarySidebar）：AgentSelector + SessionList + NotificationList
 *   中栏（main children）：ACP 会话面板 / 终端面板（占位实现）
 *   右栏：文件预览面板（占位实现）
 *
 * 状态管理：数据层（agents/sessions/notifications）由本组件直接管理，
 * 布局层（中栏面板切换、移动端 Tab、文件预览状态）由 useVibeCodingLayout hook 管理。
 * 通知列表通过 EventSource 订阅 /api/notifications/stream 长连接。
 */
import { useCallback, useEffect, useState } from 'react'
import { Plus } from 'lucide-react'
import PageLayout from '@/shared/components/PageLayout/PageLayout'
import { useI18nStore } from '@/i18n'
import { useBreakpoint } from '@/shared/hooks/useBreakpoint'
import { appLogger } from '@/shared/utils/logger'
import {
  listAgents,
  listSessions,
  createSession,
  closeSession,
  getOpenCodeStatus,
  installOpenCode,
  type AcpAgent,
  type AcpSession,
  type OpenCodeStatus,
} from '@/shared/api/acpApi'
import {
  listNotifications,
  type NotificationItem,
} from '@/shared/api/notificationsApi'
import { useVibeCodingLayout, resolveTerminalCwd } from './hooks/useVibeCodingLayout'
import AgentSelector from './components/AgentSelector'
import SessionList from './components/SessionList'
import NotificationList from './components/NotificationList'
import AcpSessionPanel from './components/AcpSessionPanel'
import TerminalPane from './components/TerminalPane'
import FilePreviewPane from './components/FilePreviewPane'
import styles from './VibeCodingPage.module.css'

/** 通知列表保留的最大条数 */
const MAX_NOTIFICATIONS = 50

function VibeCodingPage() {
  const { t } = useI18nStore()
  const { isMobile } = useBreakpoint()
  // 布局层状态：中栏面板切换、移动端 Tab、右栏文件预览状态
  const {
    activePane,
    setActivePane,
    activePanel,
    setActivePanel,
    selectedFilePath,
    previewPort,
  } = useVibeCodingLayout()
  // 数据层状态：agents / sessions / notifications 与会话操作
  const [agents, setAgents] = useState<AcpAgent[]>([])
  const [sessions, setSessions] = useState<AcpSession[]>([])
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const [selectedAgent, setSelectedAgent] = useState<string>('')
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  const [creating, setCreating] = useState<boolean>(false)
  const [installingOpenCode, setInstallingOpenCode] = useState<boolean>(false)
  const [projectCwd, setProjectCwd] = useState<string>('')
  const [openCodeStatus, setOpenCodeStatus] = useState<OpenCodeStatus | null>(null)
  const [error, setError] = useState<string>('')

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

  useEffect(() => {
    if (selectedAgent !== 'opencode') {
      setOpenCodeStatus(null)
      return
    }
    void getOpenCodeStatus(projectCwd || undefined)
      .then(setOpenCodeStatus)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [projectCwd, selectedAgent])

  /** 创建新会话 —— 调用 createSession 后追加到列表并选中 */
  const handleCreateSession = useCallback(async () => {
    if (!selectedAgent) {
      setError(t('vibeCoding.selectAgent'))
      return
    }
    setCreating(true)
    setError('')
    try {
      const result = await createSession(selectedAgent, projectCwd || undefined)
      const newSession: AcpSession = {
        session_id: result.session_id,
        agent: selectedAgent,
        cwd: result.cwd,
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
  }, [projectCwd, selectedAgent, t])

  const handleInstallOpenCode = useCallback(async () => {
    if (!window.confirm('将在当前工作目录安装 opencode-ai@latest，是否继续？')) return
    setInstallingOpenCode(true)
    setError('')
    try {
      const result = await installOpenCode(projectCwd || undefined)
      setOpenCodeStatus(result)
      if (!result.installed) setError(result.output || 'OpenCode 安装后不可用')
      if (result.audit_passed === false) setError('OpenCode 已安装，但 npm audit 检测到高危依赖问题')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setInstallingOpenCode(false)
    }
  }, [projectCwd])

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

  const projectControls = (
    <>
      <input
        value={projectCwd}
        onChange={(event) => setProjectCwd(event.target.value)}
        placeholder="ACP 工作目录（需在白名单内）"
        aria-label="ACP 工作目录"
        style={{ width: '100%', padding: '6px 8px', borderRadius: 'var(--radius-sm)' }}
      />
      {selectedAgent === 'opencode' && (
        <button
          type="button"
          className={styles['create-btn']}
          onClick={() => { void handleInstallOpenCode() }}
          disabled={installingOpenCode || openCodeStatus?.project_installed === true}
        >
          {installingOpenCode ? '正在安装 OpenCode' : openCodeStatus?.project_installed ? '项目已安装 OpenCode' : '安装 OpenCode'}
        </button>
      )}
    </>
  )

  // ===== 移动端布局：单栏 + 顶部 Tab 切换（会话 / 终端 / 预览） =====
  if (isMobile) {
    return (
      <div className={styles['vibe-coding-mobile']}>
        <div className={styles['mobile-tab-bar']} role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={activePanel === 'session'}
            onClick={() => setActivePanel('session')}
            className={`${styles['mobile-tab']} ${activePanel === 'session' ? styles['active'] : ''}`}
          >
            {t('vibeCoding.sessions')}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activePanel === 'terminal'}
            onClick={() => setActivePanel('terminal')}
            className={`${styles['mobile-tab']} ${activePanel === 'terminal' ? styles['active'] : ''}`}
          >
            {t('vibeCoding.terminalPanel')}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activePanel === 'preview'}
            onClick={() => setActivePanel('preview')}
            className={`${styles['mobile-tab']} ${activePanel === 'preview' ? styles['active'] : ''}`}
          >
            {t('vibeCoding.filePreview')}
          </button>
        </div>

        {error && <div className={styles['error-text']}>{error}</div>}

        <div className={styles['mobile-panel']}>
          {activePanel === 'session' && (
            <div className={styles['mobile-session-pane']}>
              <div className={styles['sidebar-section']}>
                <AgentSelector
                  agents={agents}
                  value={selectedAgent}
                  onChange={setSelectedAgent}
                />
                {projectControls}
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
            </div>
          )}
          {activePanel === 'terminal' && (
            <TerminalPane cwd={resolveTerminalCwd(sessions, selectedSessionId)} />
          )}
          {activePanel === 'preview' && (
            <FilePreviewPane filePath={selectedFilePath} previewPort={previewPort} />
          )}
        </div>
      </div>
    )
  }

  // ===== 桌面端布局：原三栏（左栏 + 中栏 + 右栏） =====
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
            {projectControls}
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

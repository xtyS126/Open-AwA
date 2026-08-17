/**
 * Vibe Coding 主页面。
 *
 * ACP 会话始终绑定服务端权威的工作台项目 ID。终端与文件预览由工作台
 * RuntimeDock 统一承载，本页面只管理 Agent、ACP 会话和通知。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Plus } from 'lucide-react'
import { shallow } from 'zustand/shallow'
import PageLayout from '@/shared/components/PageLayout/PageLayout'
import { useI18nStore } from '@/i18n'
import { appLogger } from '@/shared/utils/logger'
import { securityAPI, clearSseTicketCache } from '@/shared/api/securityApi'
import { API_BASE_URL, getCachedApiKey } from '@/shared/api/client'
import {
  closeSession,
  createSession,
  getOpenCodeStatus,
  installOpenCode,
  listAgents,
  listSessions,
  type AcpAgent,
  type AcpSession,
  type OpenCodeStatus,
} from '@/shared/api/acpApi'
import {
  listNotifications,
  type NotificationItem,
} from '@/shared/api/notificationsApi'
import { useWorkbenchProjectStore } from '@/features/workbench/store/workbenchProjectStore'
import { useWorkbenchRuntimeStore } from '@/features/workbench/store/workbenchRuntimeStore'
import AgentSelector from './components/AgentSelector'
import SessionList from './components/SessionList'
import NotificationList from './components/NotificationList'
import AcpSessionPanel from './components/AcpSessionPanel'
import styles from './VibeCodingPage.module.css'

const MAX_NOTIFICATIONS = 50
const MAX_NOTIFICATION_RECONNECT_ATTEMPTS = 5
const NOTIFICATION_RECONNECT_BASE_DELAY_MS = 1000

function VibeCodingPage() {
  const { t } = useI18nStore()
  const {
    currentProjectId,
    switchGeneration,
    currentProjectDisplayName,
  } = useWorkbenchProjectStore((state) => {
    const currentProject = state.currentProjectId
      ? state.projects.find((project) => project.id === state.currentProjectId)
      : null
    return {
      currentProjectId: state.currentProjectId,
      switchGeneration: state.switchGeneration,
      currentProjectDisplayName: currentProject?.isEnabled
        ? currentProject.displayName
        : null,
    }
  }, shallow)
  const runtime = useWorkbenchRuntimeStore((state) => (
    currentProjectId ? state.projects[currentProjectId] : undefined
  ))
  const setRuntimeSelectedAgent = useWorkbenchRuntimeStore((state) => state.setSelectedAgent)
  const setRuntimeSelectedSession = useWorkbenchRuntimeStore((state) => state.setSelectedSession)
  const runtimeIsCurrent = runtime?.generation === switchGeneration
  const selectedAgent = runtimeIsCurrent ? runtime.selectedAgentId ?? '' : ''
  const selectedSessionId = runtimeIsCurrent ? runtime.selectedSessionId : null

  const [agents, setAgents] = useState<AcpAgent[]>([])
  const [sessions, setSessions] = useState<AcpSession[]>([])
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const [creating, setCreating] = useState(false)
  const [installingOpenCode, setInstallingOpenCode] = useState(false)
  const [openCodeStatus, setOpenCodeStatus] = useState<OpenCodeStatus | null>(null)
  const [error, setError] = useState('')
  const notificationReconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const createSessionAbortRef = useRef<AbortController | null>(null)
  const isProjectContextCurrent = useCallback((projectId: string, generation: number) => {
    const current = useWorkbenchProjectStore.getState()
    return current.currentProjectId === projectId
      && current.switchGeneration === generation
  }, [])

  /** 工作台项目切换后重新加载该项目的 ACP 数据，并隔离旧代际结果。 */
  useEffect(() => {
    createSessionAbortRef.current?.abort()
    createSessionAbortRef.current = null
    setAgents([])
    setSessions([])
    setOpenCodeStatus(null)
    setCreating(false)
    setInstallingOpenCode(false)
    setError('')

    if (!currentProjectId || !currentProjectDisplayName) return

    const projectId = currentProjectId
    const generation = switchGeneration
    let cancelled = false

    void Promise.all([
      listAgents(),
      listSessions(projectId),
    ]).then(([agentsResponse, sessionsResponse]) => {
      if (cancelled || !isProjectContextCurrent(projectId, generation)) return
      setAgents(agentsResponse.agents)
      setSessions(sessionsResponse.sessions)
      const savedRuntime = useWorkbenchRuntimeStore.getState().projects[projectId]
      const savedAgent = savedRuntime?.generation === generation
        ? savedRuntime.selectedAgentId
        : null
      const savedAgentAvailable = savedAgent
        ? agentsResponse.agents.some((agent) => (
            agent.id === savedAgent && (agent.available || agent.id === 'opencode')
          ))
        : false
      const firstAvailable = agentsResponse.agents.find((agent) => agent.available)
      setRuntimeSelectedAgent(
        projectId,
        generation,
        savedAgentAvailable ? savedAgent : firstAvailable?.id ?? null,
      )
      const savedSessionId = savedRuntime?.generation === generation
        ? savedRuntime.selectedSessionId
        : null
      setRuntimeSelectedSession(
        projectId,
        generation,
        sessionsResponse.sessions.some((session) => session.session_id === savedSessionId)
          ? savedSessionId
          : null,
      )
    }).catch((cause: unknown) => {
      if (cancelled || !isProjectContextCurrent(projectId, generation)) return
      const message = cause instanceof Error ? cause.message : String(cause)
      appLogger.error({
        event: 'vibe_coding_project_load_failed',
        module: 'vibe-coding',
        action: 'load',
        status: 'failure',
        message: '加载工作台项目 ACP 数据失败',
        extra: { project_id: projectId, error: message },
      })
      setError(message)
    })

    return () => {
      cancelled = true
      createSessionAbortRef.current?.abort()
      createSessionAbortRef.current = null
    }
  }, [
    currentProjectDisplayName,
    currentProjectId,
    isProjectContextCurrent,
    setRuntimeSelectedAgent,
    setRuntimeSelectedSession,
    switchGeneration,
  ])

  const handleSelectAgent = useCallback((agentId: string) => {
    if (!currentProjectId) return
    setRuntimeSelectedAgent(currentProjectId, switchGeneration, agentId || null)
  }, [currentProjectId, setRuntimeSelectedAgent, switchGeneration])

  const handleSelectSession = useCallback((sessionId: string) => {
    if (!currentProjectId) return
    setRuntimeSelectedSession(currentProjectId, switchGeneration, sessionId)
  }, [currentProjectId, setRuntimeSelectedSession, switchGeneration])

  /** 通知不是项目权威资源，页面挂载期间保持一条独立 SSE 连接。 */
  useEffect(() => {
    let eventSource: EventSource | null = null
    let cancelled = false
    let reconnectAttempts = 0

    void listNotifications(MAX_NOTIFICATIONS)
      .then((response) => {
        if (!cancelled) setNotifications(response.notifications)
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause))
      })

    const clearReconnectTimer = () => {
      if (notificationReconnectTimerRef.current !== null) {
        clearTimeout(notificationReconnectTimerRef.current)
        notificationReconnectTimerRef.current = null
      }
    }

    const scheduleReconnect = (cause?: unknown) => {
      if (cancelled || notificationReconnectTimerRef.current !== null) return
      if (reconnectAttempts >= MAX_NOTIFICATION_RECONNECT_ATTEMPTS) {
        setError((previous) => previous || '通知实时连接已断开，请刷新页面后重试')
        appLogger.warning({
          event: 'vibe_coding_notification_stream_unavailable',
          module: 'vibe-coding',
          action: 'sse',
          status: 'warning',
          message: '通知 SSE 重连次数已达上限',
          extra: { error: cause instanceof Error ? cause.message : undefined },
        })
        return
      }
      const delay = Math.min(
        NOTIFICATION_RECONNECT_BASE_DELAY_MS * Math.pow(2, reconnectAttempts),
        30000,
      )
      reconnectAttempts += 1
      notificationReconnectTimerRef.current = setTimeout(() => {
        notificationReconnectTimerRef.current = null
        void connectNotificationStream()
      }, delay)
    }

    const connectNotificationStream = async () => {
      if (cancelled) return
      clearReconnectTimer()
      const hasCookie = typeof document !== 'undefined'
        && document.cookie.split(';').some((item) => item.trim().startsWith('access_token='))
      const apiKey = getCachedApiKey()
      const baseUrl = API_BASE_URL.startsWith('http') ? API_BASE_URL : ''
      const apiPrefix = API_BASE_URL.includes('/api') ? '' : '/api'
      const streamBase = `${baseUrl}${apiPrefix}/notifications/stream`
      let streamUrl = streamBase

      if (!hasCookie && apiKey) {
        try {
          const ticket = await securityAPI.requestSseTicket()
          if (cancelled) return
          streamUrl = `${streamBase}?ticket=${encodeURIComponent(ticket)}`
        } catch (cause) {
          if (cancelled) return
          const status = (cause as { response?: { status?: number } }).response?.status
          if (status === 401) clearSseTicketCache()
          setError('通知实时推送连接建立失败（获取安全票据失败），请刷新页面后重试')
          return
        }
      } else if (!hasCookie && !apiKey) {
        return
      }

      if (cancelled) return
      try {
        const source = new EventSource(streamUrl, { withCredentials: hasCookie })
        eventSource = source
        source.onopen = () => {
          reconnectAttempts = 0
        }
        source.onmessage = (event) => {
          try {
            const item = JSON.parse(event.data) as NotificationItem
            if (!item || typeof item.id !== 'string') return
            setNotifications((previous) => {
              const remaining = previous.filter((notification) => notification.id !== item.id)
              return [item, ...remaining].slice(0, MAX_NOTIFICATIONS)
            })
          } catch (cause) {
            appLogger.warning({
              event: 'vibe_coding_notification_parse_failed',
              module: 'vibe-coding',
              action: 'sse',
              status: 'warning',
              message: '通知 SSE 解析失败',
              extra: { error: cause instanceof Error ? cause.message : String(cause) },
            })
          }
        }
        source.onerror = () => {
          source.close()
          if (eventSource === source) eventSource = null
          scheduleReconnect()
        }
      } catch (cause) {
        scheduleReconnect(cause)
      }
    }

    void connectNotificationStream()

    return () => {
      cancelled = true
      clearReconnectTimer()
      eventSource?.close()
      eventSource = null
    }
  }, [])

  useEffect(() => {
    if (!currentProjectId || selectedAgent !== 'opencode') {
      setOpenCodeStatus(null)
      return
    }
    const projectId = currentProjectId
    const generation = switchGeneration
    void getOpenCodeStatus(projectId)
      .then((status) => {
        if (isProjectContextCurrent(projectId, generation)) setOpenCodeStatus(status)
      })
      .catch((cause: unknown) => {
        if (isProjectContextCurrent(projectId, generation)) {
          setError(cause instanceof Error ? cause.message : String(cause))
        }
      })
  }, [currentProjectId, isProjectContextCurrent, selectedAgent, switchGeneration])

  const handleCreateSession = useCallback(async () => {
    if (!currentProjectId || !selectedAgent) {
      setError(t('vibeCoding.selectAgent'))
      return
    }
    const projectId = currentProjectId
    const generation = switchGeneration
    createSessionAbortRef.current?.abort()
    const controller = new AbortController()
    createSessionAbortRef.current = controller
    setCreating(true)
    setError('')
    try {
      const result = await createSession(projectId, selectedAgent, controller.signal)
      if (!isProjectContextCurrent(projectId, generation)) return
      const session: AcpSession = {
        session_id: result.session_id,
        agent: selectedAgent,
        project_id: result.project_id,
        created_at: new Date().toISOString(),
      }
      setSessions((previous) => previous.some((item) => item.session_id === session.session_id)
        ? previous
        : [...previous, session])
      setRuntimeSelectedSession(projectId, generation, session.session_id)
    } catch (cause) {
      if (controller.signal.aborted || !isProjectContextCurrent(projectId, generation)) return
      const requestError = cause as { code?: string; response?: { status?: number } }
      if (requestError.code === 'ERR_CANCELED') return
      if (requestError.response?.status === 409) {
        try {
          const response = await listSessions(projectId, selectedAgent)
          if (!isProjectContextCurrent(projectId, generation)) return
          const existing = response.sessions[0]
          if (existing) {
            setSessions(response.sessions)
            setRuntimeSelectedSession(projectId, generation, existing.session_id)
            return
          }
        } catch (listCause) {
          if (!isProjectContextCurrent(projectId, generation)) return
          setError(listCause instanceof Error ? listCause.message : String(listCause))
          return
        }
      }
      const message = cause instanceof Error ? cause.message : String(cause)
      appLogger.error({
        event: 'vibe_coding_create_session_failed',
        module: 'vibe-coding',
        action: 'create',
        status: 'failure',
        message: '创建 ACP 会话失败',
        extra: { project_id: projectId, agent: selectedAgent, error: message },
      })
      setError(message)
    } finally {
      if (createSessionAbortRef.current === controller) createSessionAbortRef.current = null
      if (isProjectContextCurrent(projectId, generation)) setCreating(false)
    }
  }, [
    currentProjectId,
    isProjectContextCurrent,
    selectedAgent,
    setRuntimeSelectedSession,
    switchGeneration,
    t,
  ])

  const handleInstallOpenCode = useCallback(async () => {
    if (!currentProjectId) return
    const projectId = currentProjectId
    const generation = switchGeneration
    if (!window.confirm(`将在工作台项目“${currentProjectDisplayName ?? projectId}”中安装 opencode-ai@latest，是否继续？`)) return
    setInstallingOpenCode(true)
    setError('')
    try {
      const result = await installOpenCode(projectId)
      if (!isProjectContextCurrent(projectId, generation)) return
      setOpenCodeStatus(result)
      if (!result.installed) setError(result.output || 'OpenCode 安装后不可用')
      if (result.audit_passed === false) {
        setError('OpenCode 已安装，但 npm audit 检测到高危依赖问题')
      }
    } catch (cause) {
      if (isProjectContextCurrent(projectId, generation)) {
        setError(cause instanceof Error ? cause.message : String(cause))
      }
    } finally {
      if (isProjectContextCurrent(projectId, generation)) setInstallingOpenCode(false)
    }
  }, [
    currentProjectDisplayName,
    currentProjectId,
    isProjectContextCurrent,
    switchGeneration,
  ])

  const handleCloseSession = useCallback(async (sessionId: string) => {
    if (!currentProjectId) return
    const projectId = currentProjectId
    const generation = switchGeneration
    try {
      await closeSession(projectId, sessionId)
      if (!isProjectContextCurrent(projectId, generation)) return
      setSessions((previous) => previous.filter((session) => session.session_id !== sessionId))
      if (selectedSessionId === sessionId) {
        setRuntimeSelectedSession(projectId, generation, null)
      }
    } catch (cause) {
      if (!isProjectContextCurrent(projectId, generation)) return
      const message = cause instanceof Error ? cause.message : String(cause)
      appLogger.error({
        event: 'vibe_coding_close_session_failed',
        module: 'vibe-coding',
        action: 'close',
        status: 'failure',
        message: '关闭 ACP 会话失败',
        extra: { project_id: projectId, session_id: sessionId, error: message },
      })
      setError(message)
    }
  }, [
    currentProjectId,
    isProjectContextCurrent,
    selectedSessionId,
    setRuntimeSelectedSession,
    switchGeneration,
  ])

  if (!currentProjectId || !currentProjectDisplayName) {
    return (
      <PageLayout title={t('vibeCoding.title')} className={styles['vibe-page']}>
        <div className={styles['project-gate']} role="status">
          <strong>请先选择一个可用的工作台项目</strong>
          <span>可在上方工作台项目栏选择项目，或前往项目管理完成登记。</span>
        </div>
      </PageLayout>
    )
  }

  const projectControls = selectedAgent === 'opencode' ? (
    <button
      type="button"
      className={styles['create-btn']}
      onClick={() => { void handleInstallOpenCode() }}
      disabled={installingOpenCode || openCodeStatus?.project_installed === true}
    >
      {installingOpenCode
        ? '正在安装 OpenCode'
        : openCodeStatus?.project_installed
          ? '项目已安装 OpenCode'
          : '安装 OpenCode'}
    </button>
  ) : null

  return (
    <PageLayout
      title={t('vibeCoding.title')}
      className={styles['vibe-page']}
      secondarySidebar={
        <aside className={styles.sidebar}>
          <div className={styles['project-identity']}>
            <span>当前项目</span>
            <strong>{currentProjectDisplayName}</strong>
          </div>
          <div className={styles['sidebar-section']}>
            <AgentSelector agents={agents} value={selectedAgent} onChange={handleSelectAgent} />
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
            <span className={styles['sidebar-section-title']}>{t('vibeCoding.sessions')}</span>
            <SessionList
              sessions={sessions}
              selectedId={selectedSessionId}
              onSelect={handleSelectSession}
              onClose={(sessionId) => { void handleCloseSession(sessionId) }}
            />
          </div>
          <div className={styles['sidebar-section']}>
            <span className={styles['sidebar-section-title']}>{t('vibeCoding.notifications')}</span>
            <NotificationList notifications={notifications} />
          </div>
        </aside>
      }
    >
      <main className={styles.content}>
        {error && <div className={styles['error-text']} role="alert">{error}</div>}
        <AcpSessionPanel
          projectId={currentProjectId}
          generation={switchGeneration}
          sessionId={selectedSessionId}
        />
      </main>
    </PageLayout>
  )
}

export default VibeCodingPage

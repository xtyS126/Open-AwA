import { useEffect, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { useI18nStore } from '@/i18n'
import { appLogger } from '@/shared/utils/logger'
import { API_BASE_URL, getCachedApiKey } from '@/shared/api/client'
import {
  closePtySession,
  createPtySession,
  type PTYCreateResponse,
} from '@/shared/api/terminalApi'
import styles from './TerminalPane.module.css'

type ConnectionStatus = 'connecting' | 'connected' | 'reconnecting' | 'closed' | 'error'

export interface TerminalPaneProps {
  projectId: string
  generation: number
  onBindingChange: (sessionId: string | null) => void
}

const RECONNECT_DELAY_MAX_MS = 30000
const RECONNECT_DELAY_BASE_MS = 1000
const MAX_RECONNECT_ATTEMPTS = 10
const DEFAULT_COLS = 80
const DEFAULT_ROWS = 24

function isPtyDependencyMissingError(message: string): boolean {
  const lower = message.toLowerCase()
  return lower.includes('pywinpty') || message.includes('Windows 平台需要安装')
}

function formatDependencyMissingError(): string {
  return '终端依赖未安装：请在后端执行 `pip install pywinpty` 后重启服务'
}

function resolveWsBaseUrl(baseUrl: string): string {
  if (baseUrl.startsWith('/')) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${window.location.host}${baseUrl}`
  }
  try {
    const url = new URL(baseUrl)
    const protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${url.host}${url.pathname.replace(/\/$/, '')}`
  } catch {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${window.location.host}`
  }
}

function gridToText(grid: string[][]): string {
  if (!Array.isArray(grid) || grid.length === 0) return ''
  return grid.map((row) => Array.isArray(row) ? row.join('') : '').join('\n')
}

export default function TerminalPane({
  projectId,
  generation,
  onBindingChange,
}: TerminalPaneProps) {
  const { t } = useI18nStore()
  const [status, setStatus] = useState<ConnectionStatus>('connecting')
  const [shellInfo, setShellInfo] = useState('')
  const [createError, setCreateError] = useState('')
  const [container, setContainer] = useState<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!container) return

    let disposed = false
    let terminal: Terminal | null = null
    let fitAddon: FitAddon | null = null
    let websocket: WebSocket | null = null
    let sessionId: string | null = null
    let reconnectTimer: number | null = null
    let reconnectAttempts = 0
    let disposeTerminalEvents: (() => void) | null = null

    setStatus('connecting')
    setShellInfo('')
    setCreateError('')
    onBindingChange(null)

    const cleanupWebSocket = (): void => {
      if (!websocket) return
      websocket.onopen = null
      websocket.onclose = null
      websocket.onerror = null
      websocket.onmessage = null
      try {
        if (websocket.readyState === WebSocket.OPEN || websocket.readyState === WebSocket.CONNECTING) {
          websocket.close()
        }
      } catch {
        // WebSocket 清理采用 best effort。
      }
      websocket = null
    }

    const closeLeakedSession = (leakedSessionId: string): void => {
      void closePtySession(leakedSessionId).catch((closeError: unknown) => {
        appLogger.warning({
          event: 'pty_session_close_failed',
          module: 'vibe-coding',
          action: 'terminal',
          status: 'warning',
          message: '关闭失效 PTY 会话失败',
          extra: {
            session_id: leakedSessionId,
            project_id: projectId,
            generation,
            error: closeError instanceof Error ? closeError.message : String(closeError),
          },
        })
      })
    }

    const writeWsMessage = (raw: string): void => {
      if (websocket?.readyState === WebSocket.OPEN) websocket.send(raw)
    }

    const handleWsMessage = (event: MessageEvent<string>): void => {
      if (disposed || !terminal) return
      let message: {
        type?: string
        data?: unknown
        shell?: string
        lines?: string[]
        grid?: string[][]
        message?: string
      }
      try {
        message = JSON.parse(event.data) as typeof message
      } catch {
        return
      }

      if (message.type === 'output' && typeof message.data === 'string') {
        terminal.write(message.data)
      } else if (message.type === 'shell_info' && typeof message.shell === 'string') {
        setShellInfo(message.shell)
      } else if (message.type === 'scrollback' && Array.isArray(message.lines)) {
        terminal.write(message.lines.join('\n') + '\n')
      } else if (message.type === 'snapshot' && Array.isArray(message.grid)) {
        const text = gridToText(message.grid)
        if (text) terminal.write(text)
      } else if (message.type === 'closed') {
        setStatus('closed')
      } else if (message.type === 'command_blocked' || message.type === 'error') {
        appLogger.warning({
          event: message.type === 'command_blocked' ? 'pty_command_blocked' : 'pty_ws_error_msg',
          module: 'vibe-coding',
          action: 'terminal',
          status: 'warning',
          message: message.type === 'command_blocked' ? 'PTY 命令被安全策略阻断' : 'PTY WebSocket 错误消息',
        })
      }
    }

    const scheduleReconnect = (activeSessionId: string): void => {
      if (disposed || reconnectTimer !== null) return
      if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        setStatus('error')
        setCreateError(`已重连 ${MAX_RECONNECT_ATTEMPTS} 次仍失败，请检查网络或刷新页面后重试`)
        appLogger.error({
          event: 'pty_ws_reconnect_exhausted',
          module: 'vibe-coding',
          action: 'terminal',
          status: 'failure',
          message: 'PTY WebSocket 重连次数耗尽，停止重连',
          extra: { attempts: reconnectAttempts, project_id: projectId, generation },
        })
        return
      }

      const delay = Math.min(
        RECONNECT_DELAY_BASE_MS * 2 ** reconnectAttempts,
        RECONNECT_DELAY_MAX_MS,
      )
      reconnectAttempts += 1
      setStatus('reconnecting')
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null
        if (!disposed) connectWebSocket(activeSessionId, false)
      }, delay)
    }

    const connectWebSocket = (activeSessionId: string, initial: boolean): void => {
      if (disposed) return
      const wsBaseUrl = resolveWsBaseUrl(API_BASE_URL)
      const apiPrefix = API_BASE_URL.includes('/api') ? '' : '/api'
      const url = `${wsBaseUrl}${apiPrefix}/terminal/ws/pty/${encodeURIComponent(activeSessionId)}`
      const token = getCachedApiKey()
      const protocols = token ? [`bearer.${token}`] : undefined
      setStatus(initial ? 'connecting' : 'reconnecting')
      const nextWebSocket = protocols
        ? new WebSocket(url, protocols)
        : new WebSocket(url)
      websocket = nextWebSocket

      nextWebSocket.onopen = () => {
        if (disposed || websocket !== nextWebSocket) return
        reconnectAttempts = 0
        setStatus('connected')
      }
      nextWebSocket.onmessage = handleWsMessage
      nextWebSocket.onerror = () => {
        if (disposed || websocket !== nextWebSocket) return
        appLogger.warning({
          event: 'pty_ws_error',
          module: 'vibe-coding',
          action: 'terminal',
          status: 'warning',
          message: 'PTY WebSocket 连接错误',
          extra: { project_id: projectId, generation },
        })
      }
      nextWebSocket.onclose = (event) => {
        if (disposed || websocket !== nextWebSocket) return
        websocket = null
        if (event?.code === 4001 || event?.code === 4002) {
          setStatus('error')
          return
        }
        scheduleReconnect(activeSessionId)
      }
    }

    const initializeTerminal = (): void => {
      fitAddon = new FitAddon()
      terminal = new Terminal({
        cursorBlink: true,
        fontSize: 14,
        fontFamily: 'var(--font-mono), Consolas, Monaco, monospace',
        theme: {
          background: '#000000',
          foreground: '#e6e6e6',
          cursor: '#e6e6e6',
          cursorAccent: '#000000',
        },
        allowProposedApi: true,
        convertEol: false,
        scrollback: 1000,
      })
      terminal.loadAddon(fitAddon)
      terminal.open(container)
      try {
        fitAddon.fit()
      } catch {
        // 隐藏面板初次布局为零时稍后由 resize 再次适配。
      }

      const dataDisposable = terminal.onData((data: string) => {
        writeWsMessage(JSON.stringify({ type: 'input', data }))
      })
      const resizeDisposable = terminal.onResize(({ cols, rows }) => {
        writeWsMessage(JSON.stringify({ type: 'resize', cols, rows }))
      })
      const handleResize = () => {
        try {
          fitAddon?.fit()
        } catch {
          // 尺寸尚未稳定时忽略本次适配。
        }
      }
      window.addEventListener('resize', handleResize)
      disposeTerminalEvents = () => {
        dataDisposable.dispose()
        resizeDisposable.dispose()
        window.removeEventListener('resize', handleResize)
      }
    }

    const bootstrap = async (): Promise<void> => {
      initializeTerminal()
      let response: PTYCreateResponse
      try {
        response = await createPtySession({
          projectId,
          cols: DEFAULT_COLS,
          rows: DEFAULT_ROWS,
        })
      } catch (createFailure) {
        if (disposed) return
        const message = createFailure instanceof Error ? createFailure.message : String(createFailure)
        setCreateError(isPtyDependencyMissingError(message) ? formatDependencyMissingError() : message)
        setStatus('error')
        appLogger.error({
          event: 'pty_session_create_failed',
          module: 'vibe-coding',
          action: 'terminal',
          status: 'failure',
          message: 'PTY 会话创建失败',
          extra: { project_id: projectId, generation, error: message },
        })
        return
      }

      const createdSessionId = response.session_id
      if (disposed) {
        if (createdSessionId) closeLeakedSession(createdSessionId)
        return
      }
      if (!response.ok || !createdSessionId) {
        const message = response.error || 'PTY 会话创建失败'
        setCreateError(isPtyDependencyMissingError(message) ? formatDependencyMissingError() : message)
        setStatus('error')
        return
      }
      if (response.project_id && response.project_id !== projectId) {
        closeLeakedSession(createdSessionId)
        setCreateError('PTY 会话项目不匹配')
        setStatus('error')
        return
      }

      sessionId = createdSessionId
      onBindingChange(createdSessionId)
      if (response.shell) setShellInfo(response.shell)
      connectWebSocket(createdSessionId, true)
      appLogger.info({
        event: 'pty_session_initialized',
        module: 'vibe-coding',
        action: 'terminal',
        status: 'success',
        message: 'PTY 终端面板已初始化',
        extra: { session_id: createdSessionId, project_id: projectId, generation },
      })
    }

    void bootstrap()
    return () => {
      disposed = true
      cleanupWebSocket()
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
      disposeTerminalEvents?.()
      try {
        terminal?.dispose()
        fitAddon?.dispose()
      } catch {
        // xterm 清理采用 best effort。
      }
      if (sessionId) {
        onBindingChange(null)
        closeLeakedSession(sessionId)
        sessionId = null
      }
    }
  }, [container, generation, onBindingChange, projectId])

  const statusLabel = (() => {
    if (status === 'connecting') return t('vibeCoding.terminal.connecting')
    if (status === 'connected') return t('vibeCoding.terminal.connected')
    if (status === 'reconnecting') return t('vibeCoding.terminal.reconnecting')
    if (status === 'closed') return t('vibeCoding.terminal.closed')
    return t('vibeCoding.terminal.error')
  })()

  return (
    <div className={styles.container}>
      <div className={styles['status-bar']}>
        <span className={styles['status-indicator']}>
          <span className={`${styles['status-dot']} ${styles[status] || ''}`.trim()} aria-hidden="true" />
          <span className={styles['status-text']}>{statusLabel}</span>
        </span>
        {shellInfo && (
          <>
            <span className={styles.divider} aria-hidden="true" />
            <span className={styles['shell-info']}>{t('vibeCoding.terminal.shell')}: {shellInfo}</span>
          </>
        )}
      </div>

      {createError ? (
        <div className={styles['error-banner']}>{createError}</div>
      ) : (
        <div className={styles['terminal-wrapper']}>
          <div
            ref={setContainer}
            className={styles['terminal-container']}
            role="application"
            aria-label={t('vibeCoding.terminalPanel')}
          />
        </div>
      )}
    </div>
  )
}

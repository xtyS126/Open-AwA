/**
 * TerminalPane 终端面板组件 —— 通过 xterm.js 渲染后端 PTY 终端。
 *
 * 工作流程：
 *   1. 组件 mount 时调用 POST /terminal/sessions/pty 创建 PTY 会话，获取 session_id
 *   2. 初始化 xterm.js Terminal 实例 + FitAddon，挂载到容器
 *   3. 连接 WebSocket /terminal/ws/pty/{session_id}，通过 Sec-WebSocket-Protocol
 *      子协议以 `bearer.<API_KEY>` 形式传递认证凭据，避免 token 暴露在 URL
 *   4. 双向转发：
 *      - 服务端 output 消息 → terminal.write
 *      - terminal.onData → ws.send input 消息
 *      - terminal.onResize / window.resize → ws.send resize 消息
 *   5. 断线后启动指数退避重连，服务端推送 scrollback + snapshot 恢复显示
 *   6. 组件卸载时关闭 WebSocket、dispose terminal、调用 DELETE 关闭会话
 *
 * 状态机：
 *   connecting → connected → (onclose) → reconnecting → connected
 *                                ↓
 *                             closed / error
 */
import { useEffect, useRef, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { useI18nStore } from '@/i18n'
import { appLogger } from '@/shared/utils/logger'
import { API_BASE_URL, getCachedApiKey } from '@/shared/api/client'
import {
  createPtySession,
  closePtySession,
  type PTYCreateResponse,
} from '@/shared/api/terminalApi'
import styles from './TerminalPane.module.css'

/**
 * 判断 PTY 创建失败错误是否为依赖缺失类。
 * 后端在 Windows 平台未安装 pywinpty 时会抛出：
 *   "Windows 平台需要安装 pywinpty（pip install pywinpty）"
 * 或在响应体中返回包含 "pywinpty" 关键字的错误。
 */
function isPtyDependencyMissingError(message: string): boolean {
  const lower = message.toLowerCase()
  return lower.includes('pywinpty') || message.includes('Windows 平台需要安装')
}

/**
 * 生成用户友好的依赖缺失提示文案。
 * 参数保留以便后续按需拼接原始错误上下文，当前返回固定安装指引。
 */
function formatDependencyMissingError(_message: string): string {
  return '终端依赖未安装：请在后端执行 `pip install pywinpty` 后重启服务'
}

/** 终端连接状态 */
type ConnectionStatus =
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'closed'
  | 'error'

/** 终端面板 Props */
export interface TerminalPaneProps {
  /** 子进程工作目录（cwd 越权时后端返回 400） */
  cwd: string
}

/** 重连退避上限（毫秒） */
const RECONNECT_DELAY_MAX_MS = 30000
/** 重连基础延迟（毫秒），实际延迟为 base * 2^attempts */
const RECONNECT_DELAY_BASE_MS = 1000
/** 最大重连尝试次数：超过后停止重连，避免无限重试占用资源 */
const MAX_RECONNECT_ATTEMPTS = 10
/** 终端默认行列数，创建会话时使用 */
const DEFAULT_COLS = 80
const DEFAULT_ROWS = 24

/**
 * 把 HTTP baseURL 转换为 WebSocket URL。
 * /api 前缀保留，http(s) → ws(s)。
 * 例：https://host/api → wss://host/api
 *     /api → ws://<window.location.host>/api
 */
function resolveWsBaseUrl(baseUrl: string): string {
  // 相对路径：基于当前页面 location 推导
  if (baseUrl.startsWith('/')) {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${window.location.host}${baseUrl}`
  }
  try {
    const url = new URL(baseUrl)
    const proto = url.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${url.host}${url.pathname.replace(/\/$/, '')}`
  } catch {
    // 解析失败时退化为当前 host 的根路径
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${window.location.host}`
  }
}

/**
 * 把 grid 二维数组转成 xterm 可写入的字符串。
 * 每行内部字符直接拼接，行间用 \n 分隔。
 * 注意：grid 行内元素为单字符（含 ANSI 转义），拼接顺序即屏幕顺序。
 */
function gridToText(grid: string[][]): string {
  if (!Array.isArray(grid) || grid.length === 0) return ''
  return grid.map((row) => (Array.isArray(row) ? row.join('') : '')).join('\n')
}

/** TerminalPane 终端面板 —— xterm.js + PTY WebSocket */
export default function TerminalPane({ cwd }: TerminalPaneProps) {
  const { t } = useI18nStore()

  // 连接状态：驱动状态栏圆点与文字
  const [status, setStatus] = useState<ConnectionStatus>('connecting')
  // shell 类型（来自 shell_info 消息）
  const [shellInfo, setShellInfo] = useState<string>('')
  // 创建会话失败时的错误信息（驱动错误展示）
  const [createError, setCreateError] = useState<string>('')

  // xterm 容器 div —— 必须有明确高度才能正确渲染
  const containerRef = useRef<HTMLDivElement | null>(null)
  // xterm Terminal 实例（mount 时创建，unmount 时 dispose）
  const terminalRef = useRef<Terminal | null>(null)
  // FitAddon 实例，用于自适应终端尺寸
  const fitAddonRef = useRef<FitAddon | null>(null)
  // WebSocket 实例
  const wsRef = useRef<WebSocket | null>(null)
  // 当前 PTY 会话 ID（创建会话后赋值）
  const sessionIdRef = useRef<string | null>(null)
  // 重连定时器句柄，用于卸载时清理
  const reconnectTimeoutRef = useRef<number | null>(null)
  // 重连尝试次数（用于指数退避计算）
  const reconnectAttemptsRef = useRef<number>(0)
  // 组件是否已卸载标志，避免卸载后异步回调更新状态
  const disposedRef = useRef<boolean>(false)
  // resize 事件处理函数引用，便于卸载时 removeEventListener
  const resizeHandlerRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    disposedRef.current = false

    /**
     * 初始化 xterm.js Terminal 实例并挂载到容器。
     * FitAddon 由调用方创建并传入，便于外部持引用触发 fit。
     */
    function initTerminal(fit: FitAddon): Terminal {
      const term = new Terminal({
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
      term.loadAddon(fit)
      if (containerRef.current) {
        term.open(containerRef.current)
        try {
          fit.fit()
        } catch {
          // 容器尺寸为零时 fit 可能抛出，忽略即可
        }
      }
      return term
    }

    /**
     * 绑定 xterm 数据输入与 resize 事件。
     * - onData：用户键入 → 发送 input 消息到 WebSocket
     * - onResize：终端尺寸变化 → 发送 resize 消息到 WebSocket
     * 返回 dispose 函数，用于解绑事件。
     */
    function bindTerminalEvents(
      term: Terminal,
      fit: FitAddon,
      sendMessage: (raw: string) => void
    ): () => void {
      // 用户输入转发到 PTY stdin
      const dataDisposable = term.onData((data: string) => {
        sendMessage(JSON.stringify({ type: 'input', data }))
      })
      // 终端 resize 转发到 PTY resize
      const resizeDisposable = term.onResize(({ cols, rows }) => {
        sendMessage(JSON.stringify({ type: 'resize', cols, rows }))
      })
      // 浏览器窗口 resize 时重新 fit 终端
      const handleResize = () => {
        try {
          fit.fit()
        } catch {
          // 忽略 fit 异常
        }
      }
      window.addEventListener('resize', handleResize)
      resizeHandlerRef.current = handleResize
      return () => {
        dataDisposable.dispose()
        resizeDisposable.dispose()
        window.removeEventListener('resize', handleResize)
        resizeHandlerRef.current = null
      }
    }

    /**
     * 处理来自 WebSocket 的单条消息。
     * 根据 type 分发到 output / shell_info / scrollback / snapshot / error / closed 等分支。
     */
    function handleWsMessage(raw: MessageEvent<string>, term: Terminal): void {
      let msg: { type?: string; data?: unknown; shell?: string; lines?: string[]; grid?: string[][]; message?: string }
      try {
        msg = JSON.parse(raw.data) as typeof msg
      } catch {
        // 非 JSON 消息忽略
        return
      }
      switch (msg.type) {
        case 'output': {
          if (typeof msg.data === 'string') {
            term.write(msg.data)
          }
          break
        }
        case 'shell_info': {
          if (typeof msg.shell === 'string') {
            setShellInfo(msg.shell)
          }
          break
        }
        case 'scrollback': {
          // 重连时服务端先推送 scrollback（历史行），再推送 snapshot（当前屏幕）
          if (Array.isArray(msg.lines) && msg.lines.length > 0) {
            term.write(msg.lines.join('\n') + '\n')
          }
          break
        }
        case 'snapshot': {
          // 当前屏幕快照，直接覆盖写入
          if (Array.isArray(msg.grid)) {
            const text = gridToText(msg.grid)
            if (text) {
              term.write(text)
            }
          }
          break
        }
        case 'resize_ack': {
          // resize 确认，无需处理
          break
        }
        case 'command_blocked': {
          // 命令被安全策略拦截，由服务端自行输出提示；此处仅记录日志
          appLogger.warning({
            event: 'pty_command_blocked',
            module: 'vibe-coding',
            action: 'terminal',
            status: 'warning',
            message: 'PTY 命令被安全策略拦截',
            extra: { command: typeof msg.message === 'string' ? msg.message.slice(0, 100) : '' },
          })
          break
        }
        case 'error': {
          appLogger.warning({
            event: 'pty_ws_error_msg',
            module: 'vibe-coding',
            action: 'terminal',
            status: 'warning',
            message: 'PTY WebSocket 错误消息',
            extra: { message: typeof msg.message === 'string' ? msg.message : '' },
          })
          break
        }
        case 'closed': {
          // 服务端主动关闭会话
          if (!disposedRef.current) {
            setStatus('closed')
          }
          break
        }
        default: {
          // 未知消息类型忽略
        }
      }
    }

    /**
     * 创建 WebSocket 连接并绑定事件。
     * isFirstConnection 为 true 时表示首次连接（connecting 状态），
     * 否则为重连（reconnecting 状态）。
     *
     * 安全说明：API Key 通过 Sec-WebSocket-Protocol 子协议以 `bearer.<token>` 形式传递，
     * 不再附加到 URL query 参数，避免泄漏到访问日志、浏览器历史与 Referer header。
     */
    function connectWebSocket(sessionId: string, isFirstConnection: boolean): WebSocket {
      const wsBaseUrl = resolveWsBaseUrl(API_BASE_URL)
      const token = getCachedApiKey()
      // URL 不携带 token，token 通过子协议传递
      const url = `${wsBaseUrl}/terminal/ws/pty/${encodeURIComponent(sessionId)}`
      if (isFirstConnection) {
        setStatus('connecting')
      } else {
        setStatus('reconnecting')
      }
      // 通过 Sec-WebSocket-Protocol 子协议传递 bearer token
      // 后端解析 `bearer.` 前缀提取 token，并回显同一子协议完成握手
      const protocols = token ? [`bearer.${token}`] : undefined
      const ws = protocols ? new WebSocket(url, protocols) : new WebSocket(url)

      ws.onopen = () => {
        if (disposedRef.current) return
        // 重置重连计数
        reconnectAttemptsRef.current = 0
        setStatus('connected')
      }

      ws.onmessage = (event: MessageEvent<string>) => {
        if (disposedRef.current || !terminalRef.current) return
        handleWsMessage(event, terminalRef.current)
      }

      ws.onerror = () => {
        if (disposedRef.current) return
        // 错误事件不直接改状态，等 onclose 触发重连
        appLogger.warning({
          event: 'pty_ws_error',
          module: 'vibe-coding',
          action: 'terminal',
          status: 'warning',
          message: 'PTY WebSocket 连接错误',
        })
      }

      ws.onclose = () => {
        if (disposedRef.current) return
        // 服务端主动关闭（如会话被 DELETE）时不再重连
        if (wsRef.current !== ws) return
        wsRef.current = null
        scheduleReconnect(sessionId)
      }

      return ws
    }

    /**
     * 调度重连：指数退避 1s → 2s → 4s → ... → 30s 上限。
     * 已卸载或已主动断开时不再调度。
     * 超过 MAX_RECONNECT_ATTEMPTS 后停止重连，进入 error 状态，避免无限重试占用资源。
     */
    function scheduleReconnect(sessionId: string): void {
      if (disposedRef.current) return
      // 已有定时器在等待，跳过
      if (reconnectTimeoutRef.current !== null) return
      const attempts = reconnectAttemptsRef.current
      // 超过重连上限：切换为 error 状态，停止重连
      if (attempts >= MAX_RECONNECT_ATTEMPTS) {
        appLogger.error({
          event: 'pty_ws_reconnect_exhausted',
          module: 'vibe-coding',
          action: 'terminal',
          status: 'failure',
          message: 'PTY WebSocket 重连次数耗尽，停止重连',
          extra: { attempts },
        })
        setStatus('error')
        setCreateError(`已重连 ${MAX_RECONNECT_ATTEMPTS} 次仍失败，请检查网络或刷新页面后重试`)
        return
      }
      const delay = Math.min(RECONNECT_DELAY_BASE_MS * 2 ** attempts, RECONNECT_DELAY_MAX_MS)
      reconnectAttemptsRef.current = attempts + 1
      setStatus('reconnecting')
      appLogger.info({
        event: 'pty_ws_reconnect_scheduled',
        module: 'vibe-coding',
        action: 'terminal',
        status: 'start',
        message: 'PTY WebSocket 计划重连',
        extra: { attempt: attempts + 1, delay_ms: delay },
      })
      reconnectTimeoutRef.current = window.setTimeout(() => {
        reconnectTimeoutRef.current = null
        if (disposedRef.current) return
        // 创建新连接（会先尝试解析 token；若失败 onclose 会再次触发重连）
        wsRef.current = connectWebSocket(sessionId, false)
      }, delay)
    }

    /**
     * 主初始化流程：
     *   1. 创建 xterm Terminal + FitAddon
     *   2. 创建 PTY 会话
     *   3. 绑定事件
     *   4. 连接 WebSocket
     */
    async function bootstrap(): Promise<void> {
      if (!containerRef.current) return
      // 创建 FitAddon 实例（先创建，由 initTerminal 内部 loadAddon 注册到 terminal）
      const fit = new FitAddon()
      // 初始化 xterm Terminal
      const terminal = initTerminal(fit)
      terminalRef.current = terminal
      fitAddonRef.current = fit

      // 创建 PTY 会话
      let createRes: PTYCreateResponse
      try {
        createRes = await createPtySession({ cwd, cols: DEFAULT_COLS, rows: DEFAULT_ROWS })
      } catch (e) {
        if (disposedRef.current) return
        const message = e instanceof Error ? e.message : String(e)
        appLogger.error({
          event: 'pty_session_create_failed',
          module: 'vibe-coding',
          action: 'terminal',
          status: 'failure',
          message: 'PTY 会话创建失败',
          extra: { cwd, error: message },
        })
        // 依赖缺失类错误用友好文案展示，但仍保留原始 message 用于日志排查
        setCreateError(
          isPtyDependencyMissingError(message)
            ? formatDependencyMissingError(message)
            : message
        )
        setStatus('error')
        return
      }

      if (disposedRef.current) return

      if (!createRes.ok || !createRes.session_id) {
        const errMsg = createRes.error || 'PTY 会话创建失败'
        appLogger.error({
          event: 'pty_session_create_failed',
          module: 'vibe-coding',
          action: 'terminal',
          status: 'failure',
          message: errMsg,
          extra: { cwd },
        })
        // 依赖缺失类错误用友好文案展示
        setCreateError(
          isPtyDependencyMissingError(errMsg)
            ? formatDependencyMissingError(errMsg)
            : errMsg
        )
        setStatus('error')
        return
      }

      const sessionId = createRes.session_id
      sessionIdRef.current = sessionId
      if (createRes.shell) {
        setShellInfo(createRes.shell)
      }

      // 绑定 xterm 事件 —— 发送函数读取最新 wsRef
      const disposeEvents = bindTerminalEvents(terminal, fit, (raw: string) => {
        const ws = wsRef.current
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(raw)
        }
      })

      // 保存 dispose 函数到 ref，便于卸载时调用
      eventsDisposeRef.current = disposeEvents

      // 连接 WebSocket
      wsRef.current = connectWebSocket(sessionId, true)

      appLogger.info({
        event: 'pty_session_initialized',
        module: 'vibe-coding',
        action: 'terminal',
        status: 'success',
        message: 'PTY 终端面板已初始化',
        extra: { session_id: sessionId, cwd },
      })
    }

    // dispose 函数引用，初始化后赋值
    const eventsDisposeRef = { current: null as null | (() => void) }

    void bootstrap()

    // ===== 卸载清理 =====
    return () => {
      disposedRef.current = true
      // 关闭 WebSocket
      const ws = wsRef.current
      if (ws) {
        ws.onclose = null
        ws.onerror = null
        ws.onmessage = null
        ws.onopen = null
        try {
          if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
            ws.close()
          }
        } catch {
          // 忽略
        }
        wsRef.current = null
      }
      // 清理重连定时器
      if (reconnectTimeoutRef.current !== null) {
        clearTimeout(reconnectTimeoutRef.current)
        reconnectTimeoutRef.current = null
      }
      // 清理 resize 监听
      if (resizeHandlerRef.current) {
        window.removeEventListener('resize', resizeHandlerRef.current)
        resizeHandlerRef.current = null
      }
      // 解绑 xterm 事件
      if (eventsDisposeRef.current) {
        eventsDisposeRef.current()
        eventsDisposeRef.current = null
      }
      // dispose terminal
      if (terminalRef.current) {
        try {
          terminalRef.current.dispose()
        } catch {
          // 忽略
        }
        terminalRef.current = null
      }
      // 关闭 PTY 会话（best effort，不阻塞卸载）
      const sid = sessionIdRef.current
      sessionIdRef.current = null
      if (sid) {
        closePtySession(sid).catch((e) => {
          appLogger.warning({
            event: 'pty_session_close_failed',
            module: 'vibe-coding',
            action: 'terminal',
            status: 'warning',
            message: '关闭 PTY 会话失败',
            extra: { session_id: sid, error: e instanceof Error ? e.message : String(e) },
          })
        })
      }
    }
  }, [cwd])

  /** 根据当前状态推导状态栏圆点的 className */
  const statusDotClass = `${styles['status-dot']} ${styles[status] || ''}`.trim()

  /** 状态栏显示文案 */
  const statusLabel = (() => {
    switch (status) {
      case 'connecting':
        return t('vibeCoding.terminal.connecting')
      case 'connected':
        return t('vibeCoding.terminal.connected')
      case 'reconnecting':
        return t('vibeCoding.terminal.reconnecting')
      case 'closed':
        return t('vibeCoding.terminal.closed')
      case 'error':
        return t('vibeCoding.terminal.error')
      default:
        return ''
    }
  })()

  return (
    <div className={styles['container']}>
      {/* 顶部状态栏：连接状态 + shell 类型 + cwd */}
      <div className={styles['status-bar']}>
        <span className={styles['status-indicator']}>
          <span className={statusDotClass} aria-hidden="true" />
          <span className={styles['status-text']}>{statusLabel}</span>
        </span>
        {shellInfo && (
          <>
            <span className={styles['divider']} aria-hidden="true" />
            <span className={styles['shell-info']}>
              {t('vibeCoding.terminal.shell')}: {shellInfo}
            </span>
          </>
        )}
        {cwd && (
          <>
            <span className={styles['divider']} aria-hidden="true" />
            <span className={styles['cwd-info']} title={cwd}>
              {cwd}
            </span>
          </>
        )}
      </div>

      {/* 终端区或错误展示 */}
      {createError ? (
        <div className={styles['error-banner']}>{createError}</div>
      ) : (
        <div className={styles['terminal-wrapper']}>
          <div
            ref={containerRef}
            className={styles['terminal-container']}
            role="application"
            aria-label={t('vibeCoding.terminalPanel')}
          />
        </div>
      )}
    </div>
  )
}

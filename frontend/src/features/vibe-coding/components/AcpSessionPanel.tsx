/**
 * AcpSessionPanel ACP 会话面板组件。
 *
 * 中栏核心面板：底部 textarea 输入 prompt，回车发送，通过 fetch + ReadableStream
 * 订阅 POST /api/acp/sessions/{id}/prompt 的 SSE 流式响应，解析 event:/data: 帧，
 * 按事件类型渲染到输出区（文本/工具调用/状态/用量/结果/错误）。
 * 收到 permission 事件时弹出 PermissionDialog 等待用户决策。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronRight, Send, Square, X } from 'lucide-react'
import { useI18nStore } from '@/i18n'
import { appLogger } from '@/shared/utils/logger'
import { API_BASE_URL, getCachedApiKey } from '@/shared/api/client'
import { cancelTurn, respondPermission, type SuspendedPermission } from '@/shared/api/acpApi'
import PermissionDialog from './PermissionDialog'
import styles from './AcpSessionPanel.module.css'

export interface AcpSessionPanelProps {
  /** 当前选中的会话 ID，null 表示未选中 */
  sessionId: string | null
  /** 会话工作目录（用于顶栏展示） */
  cwd: string
  /** 可选的取消/返回回调（空状态下展示返回按钮） */
  onCancel?: () => void
}

/** ACP 流事件类型 */
type AcpEventType = 'text' | 'tool' | 'status' | 'usage' | 'result' | 'error'

/** 累积在输出区的事件项 */
interface AcpEvent {
  /** 唯一 ID（用于 React key） */
  id: string
  /** 事件类型 */
  type: AcpEventType
  /** 事件 data 负载（已解析的 JSON 对象） */
  data: unknown
  /** 接收时间戳 */
  timestamp: number
}

/** text 事件 data 形状 —— 兼容 text 和 content 两种字段 */
interface TextEventData {
  text?: string
  content?: string
}

/** tool 事件 data 形状 */
interface ToolEventData {
  tool_name?: string
  tool_kind?: string
  status?: string
  content?: string
  locations?: string[]
}

/** status 事件 data 形状 */
interface StatusEventData {
  status?: string
  message?: string
}

/** usage 事件 data 形状 */
interface UsageEventData {
  input_tokens?: number
  output_tokens?: number
  total_tokens?: number
  cost?: number
}

/** result 事件 data 形状 */
interface ResultEventData {
  status?: string
}

/** error 事件 data 形状 */
interface ErrorEventData {
  message?: string
}

/** 工具状态 → 样式类名映射 */
function toolStatusClass(status: string | undefined): string {
  if (status === 'completed') return styles.toolStatusCompleted
  if (status === 'failed' || status === 'error') return styles.toolStatusFailed
  return styles.toolStatusInProgress
}

/** 单个工具调用卡片 —— 可展开查看 content */
function ToolCallCard({ data }: { data: ToolEventData }) {
  const [expanded, setExpanded] = useState(false)
  const toolName = data.tool_name || '(unknown tool)'
  const toolKind = data.tool_kind || ''
  const status = data.status
  const content = typeof data.content === 'string' ? data.content : ''
  const locations = Array.isArray(data.locations) ? data.locations : []
  const hasBody = Boolean(content || locations.length > 0)

  return (
    <div className={styles.toolCard}>
      <div
        className={styles.toolHeader}
        onClick={() => hasBody && setExpanded((v) => !v)}
        role={hasBody ? 'button' : undefined}
        tabIndex={hasBody ? 0 : undefined}
      >
        <div className={styles.toolHeaderLeft}>
          {hasBody && (
            <span className={`${styles.toolChevron} ${expanded ? styles.toolChevronExpanded : ''}`}>
              <ChevronRight size={14} />
            </span>
          )}
          <span className={styles.toolName}>{toolName}</span>
          {toolKind && <span className={styles.toolKind}>{toolKind}</span>}
        </div>
        {status && (
          <span className={`${styles.toolStatus} ${toolStatusClass(status)}`}>{status}</span>
        )}
      </div>
      {expanded && hasBody && (
        <div className={styles.toolBody}>
          {content && <pre className={styles.toolContent}>{content}</pre>}
          {locations.length > 0 && (
            <div className={styles.toolLocations}>
              {locations.map((loc, idx) => (
                <div key={`${idx}-${loc}`}>{loc}</div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** ACP 会话面板 —— 输入 prompt、订阅 SSE 流、渲染事件、处理权限审批 */
export default function AcpSessionPanel({ sessionId, cwd, onCancel }: AcpSessionPanelProps) {
  const { t } = useI18nStore()
  // 累积的事件列表
  const [events, setEvents] = useState<AcpEvent[]>([])
  // 输入框文本
  const [inputText, setInputText] = useState('')
  // 是否正在流式接收
  const [isStreaming, setIsStreaming] = useState(false)
  // 挂起的权限请求（非 null 时弹出 PermissionDialog）
  const [pendingPermission, setPendingPermission] = useState<SuspendedPermission | null>(null)

  // 取消请求的控制器
  const abortControllerRef = useRef<AbortController | null>(null)
  // 输出区 DOM 引用 —— 用于自动滚动到底部
  const outputRef = useRef<HTMLDivElement>(null)
  // 事件 ID 自增计数器
  const eventCounterRef = useRef<number>(0)

  /** 追加一个事件并触发滚动 */
  const appendEvent = useCallback((type: AcpEventType, data: unknown) => {
    eventCounterRef.current += 1
    const evt: AcpEvent = {
      id: `evt-${eventCounterRef.current}`,
      type,
      data,
      timestamp: Date.now(),
    }
    setEvents((prev) => [...prev, evt])
  }, [])

  /** 滚动输出区到底部 */
  const scrollToBottom = useCallback(() => {
    const el = outputRef.current
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  }, [])

  // events 变化时滚动到底部
  useEffect(() => {
    scrollToBottom()
  }, [events, scrollToBottom])

  // sessionId 变化时清空事件与挂起状态
  useEffect(() => {
    setEvents([])
    setPendingPermission(null)
    setInputText('')
    eventCounterRef.current = 0
  }, [sessionId])

  // 组件卸载时中止进行中的请求
  useEffect(() => {
    const controller = abortControllerRef
    return () => {
      if (controller.current) {
        controller.current.abort()
        controller.current = null
      }
    }
  }, [])

  /** 发送 prompt —— 订阅 SSE 流并解析事件帧 */
  const sendPrompt = useCallback(async () => {
    if (!sessionId) return
    const prompt = inputText.trim()
    if (!prompt || isStreaming) return

    // 追加用户输入为本地文本事件（区分用户与 agent 输出）
    appendEvent('text', { text: prompt })

    setInputText('')
    setIsStreaming(true)
    setPendingPermission(null)

    const controller = new AbortController()
    abortControllerRef.current = controller

    const url = `${API_BASE_URL}/acp/sessions/${sessionId}/prompt`
    const apiKey = getCachedApiKey()
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    }
    if (apiKey) {
      headers['Authorization'] = `Bearer ${apiKey}`
    }

    let buffer = ''

    try {
      const response = await fetch(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers,
        signal: controller.signal,
        body: JSON.stringify({ prompt }),
      })

      if (!response.ok) {
        const errBody = await response.json().catch(() => ({}))
        const message = (errBody as { detail?: string })?.detail || `Request failed: ${response.status}`
        appendEvent('error', { message })
        return
      }

      if (!response.body) {
        appendEvent('error', { message: 'No response body' })
        return
      }

      const reader = response.body.getReader()
      try {
        const decoder = new TextDecoder('utf-8')
        let done = false

      // SSE 流式响应最大大小限制 —— 防止后端异常/恶意推送导致前端内存耗尽
      const MAX_RESPONSE_BYTES = 10 * 1024 * 1024 // 10MB 上限
      let totalBytes = 0

        while (!done) {
        const { value, done: doneReading } = await reader.read()
        done = doneReading
        if (value) {
          // 累计已接收字节数，超过上限主动中止
          totalBytes += value.byteLength
          if (totalBytes > MAX_RESPONSE_BYTES) {
            controller.abort()
            appendEvent('error', { message: '响应超过 10MB 上限，已中止' })
            break
          }
          buffer += decoder.decode(value, { stream: true })
          // 按 \n\n 分割完整的 SSE 事件帧，最后一个不完整的保留在 buffer
          const frames = buffer.split('\n\n')
          buffer = frames.pop() || ''
          for (const frame of frames) {
            parseAndDispatchFrame(frame, appendEvent, setPendingPermission)
          }
        }
      }

      // 处理缓冲区中剩余的事件
      if (buffer.trim()) {
        parseAndDispatchFrame(buffer, appendEvent, setPendingPermission)
        }
      } finally {
        // 所有退出路径都释放读取锁，避免后续 ACP 流被已遗留的 reader 阻塞。
        reader.releaseLock()
      }
    } catch (e) {
      // 用户主动取消时不当作错误
      if (e instanceof DOMException && e.name === 'AbortError') {
        appLogger.info({
          event: 'acp_prompt_aborted',
          module: 'vibe-coding',
          action: 'sse',
          status: 'success',
          message: 'ACP prompt 流被用户中止',
          extra: { session_id: sessionId },
        })
        return
      }
      const message = e instanceof Error ? e.message : String(e)
      appLogger.error({
        event: 'acp_prompt_failed',
        module: 'vibe-coding',
        action: 'sse',
        status: 'failure',
        message: 'ACP prompt 流请求失败',
        extra: { session_id: sessionId, error: message },
      })
      appendEvent('error', { message })
    } finally {
      setIsStreaming(false)
      abortControllerRef.current = null
    }
  }, [sessionId, inputText, isStreaming, appendEvent])

  /** 取消当前轮 —— 中止 fetch 流 + 调用后端 cancelTurn */
  const handleCancel = useCallback(async () => {
    if (!sessionId) return
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
    try {
      await cancelTurn(sessionId)
    } catch (e) {
      appLogger.warning({
        event: 'acp_cancel_failed',
        module: 'vibe-coding',
        action: 'cancel',
        status: 'warning',
        message: 'ACP cancelTurn 调用失败',
        extra: { session_id: sessionId, error: e instanceof Error ? e.message : String(e) },
      })
    } finally {
      setIsStreaming(false)
      setPendingPermission(null)
    }
  }, [sessionId])

  /** 用户在 PermissionDialog 中选择某选项 —— 调用 respondPermission 提交 */
  const handlePermissionSelect = useCallback(
    async (optionId: string) => {
      if (!sessionId) return
      try {
        await respondPermission(sessionId, optionId)
        setPendingPermission(null)
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e)
        appLogger.error({
          event: 'acp_permission_respond_failed',
          module: 'vibe-coding',
          action: 'permission',
          status: 'failure',
          message: 'ACP 权限响应失败',
          extra: { session_id: sessionId, option_id: optionId, error: message },
        })
        appendEvent('error', { message: `权限响应失败: ${message}` })
        setPendingPermission(null)
      }
    },
    [sessionId, appendEvent]
  )

  /** 用户在 PermissionDialog 中点击取消 —— 拒绝权限并中止当前轮 */
  const handlePermissionCancel = useCallback(() => {
    setPendingPermission(null)
    void handleCancel()
  }, [handleCancel])

  /** 键盘事件：Enter 发送，Shift+Enter 换行 */
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        void sendPrompt()
      }
    },
    [sendPrompt]
  )

  // 未选中会话 —— 空状态
  if (!sessionId) {
    return (
      <div className={styles.root}>
        <div className={styles.empty}>
          <span>{t('vibeCoding.acp.noSession')}</span>
          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
              style={{
                marginLeft: 'var(--space-2)',
                padding: '2px var(--space-2)',
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-sm)',
                background: 'transparent',
                color: 'var(--color-text-secondary)',
                fontSize: 'var(--text-xs)',
                cursor: 'pointer',
              }}
            >
              {t('app.back')}
            </button>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className={styles.root}>
      {/* 工作目录顶栏 */}
      <div className={styles.cwdBar} title={cwd}>
        <span className={styles.cwdLabel}>{t('vibeCoding.cwd')}</span>
        <span className={styles.cwdValue}>{cwd || '-'}</span>
      </div>

      {/* 输出区 —— 累积渲染事件 */}
      <div ref={outputRef} className={styles.output}>
        {events.map((evt) => (
          <EventView key={evt.id} evt={evt} />
        ))}
        {events.length === 0 && !isStreaming && (
          <div style={{ color: 'var(--color-text-tertiary)', fontSize: 'var(--text-sm)' }}>
            {t('vibeCoding.acp.inputPlaceholder')}
          </div>
        )}
      </div>

      {/* 输入区 */}
      <div className={styles.inputArea}>
        {isStreaming && (
          <div className={styles.streamingHint}>
            <span className={styles.streamingDot} />
            <span>{t('vibeCoding.acp.streaming')}</span>
          </div>
        )}
        <div className={styles.inputRow}>
          <textarea
            className={styles.textarea}
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t('vibeCoding.acp.inputPlaceholder')}
            disabled={isStreaming}
            rows={3}
            maxLength={32000}
          />
          {isStreaming ? (
            <button
              type="button"
              className={styles.cancelBtn}
              onClick={() => { void handleCancel() }}
            >
              <Square size={14} />
              {t('vibeCoding.acp.cancel')}
            </button>
          ) : (
            <button
              type="button"
              className={styles.sendBtn}
              onClick={() => { void sendPrompt() }}
              disabled={!inputText.trim()}
            >
              <Send size={14} />
              {t('vibeCoding.acp.send')}
            </button>
          )}
        </div>
        <span className={styles.charCount}>
          {inputText.length}/32000
        </span>
      </div>

      {/* 权限审批弹窗 —— 仅在挂起时渲染 */}
      {pendingPermission && (
        <PermissionDialog
          permission={pendingPermission}
          onSelect={handlePermissionSelect}
          onCancel={handlePermissionCancel}
        />
      )}
    </div>
  )
}

/** 单个事件渲染 —— 根据类型分发到对应子视图 */
function EventView({ evt }: { evt: AcpEvent }) {
  const { t } = useI18nStore()
  switch (evt.type) {
    case 'text': {
      const data = evt.data as TextEventData
      const text = data.text ?? data.content ?? ''
      if (!text) return null
      return (
        <div className={`${styles.event} ${styles.textEvent}`}>{text}</div>
      )
    }
    case 'tool': {
      const data = evt.data as ToolEventData
      return <ToolCallCard data={data} />
    }
    case 'status': {
      const data = evt.data as StatusEventData
      const status = data.status || ''
      const message = data.message || ''
      return (
        <div className={styles.statusEvent}>
          <span className={styles.statusIcon}>
            <ChevronRight size={12} />
          </span>
          <span>{status}{message ? ` - ${message}` : ''}</span>
        </div>
      )
    }
    case 'usage': {
      const data = evt.data as UsageEventData
      return (
        <div className={styles.usage}>
          <span className={styles.usageItem}>
            <span className={styles.usageLabel}>in:</span>
            <span className={styles.usageValue}>{data.input_tokens ?? '-'}</span>
          </span>
          <span className={styles.usageItem}>
            <span className={styles.usageLabel}>out:</span>
            <span className={styles.usageValue}>{data.output_tokens ?? '-'}</span>
          </span>
          <span className={styles.usageItem}>
            <span className={styles.usageLabel}>total:</span>
            <span className={styles.usageValue}>{data.total_tokens ?? '-'}</span>
          </span>
          {typeof data.cost === 'number' && (
            <span className={`${styles.usageItem} ${styles.usageCost}`}>
              <span className={styles.usageLabel}>cost:</span>
              <span className={styles.usageValue}>${data.cost.toFixed(4)}</span>
            </span>
          )}
        </div>
      )
    }
    case 'result': {
      const data = evt.data as ResultEventData
      const status = data.status || ''
      return (
        <div className={styles.resultEvent}>
          <X size={12} />
          <span>{t('vibeCoding.acp.roundComplete')}{status ? ` (${status})` : ''}</span>
        </div>
      )
    }
    case 'error': {
      const data = evt.data as ErrorEventData
      const message = data.message || 'Unknown error'
      return <div className={styles.errorEvent}>{message}</div>
    }
    default:
      return null
  }
}

/**
 * 解析单个 SSE 事件帧并分发到对应回调。
 * 帧格式：
 *   event: <type>
 *   data: <json>
 *
 * 非法帧上报会话错误事件（用户可见），不静默忽略。
 */
function parseAndDispatchFrame(
  frame: string,
  appendEvent: (type: AcpEventType, data: unknown) => void,
  setPendingPermission: (perm: SuspendedPermission | null) => void
): void {
  const lines = frame.split('\n')
  let eventType = ''
  let dataStr = ''

  for (const line of lines) {
    if (line.startsWith('event:')) {
      eventType = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      // 兼容 "data: " 和 "data:" 两种格式
      const raw = line.slice(5)
      dataStr = raw.startsWith(' ') ? raw.slice(1) : raw
    }
  }

  if (!eventType || !dataStr) return

  let data: unknown
  try {
    data = JSON.parse(dataStr)
  } catch {
    // 解析失败必须上报会话错误事件（用户可见），Agent 输出缺失不能静默吞掉
    appLogger.error({
      event: 'acp_sse_parse_failed',
      module: 'vibe-coding',
      action: 'sse',
      status: 'failure',
      message: 'ACP SSE 帧解析失败',
      extra: { event_type: eventType, payload_preview: dataStr.slice(0, 100) },
    })
    appendEvent('error', { message: 'ACP SSE 帧解析失败，该帧输出已丢失' })
    return
  }

  switch (eventType) {
    case 'text':
    case 'tool':
    case 'status':
    case 'usage':
    case 'result':
    case 'error':
      appendEvent(eventType, data)
      break
    case 'permission':
      // permission 事件的 data 即 SuspendedPermission 对象
      setPendingPermission(data as SuspendedPermission)
      break
    default:
      // 未知事件类型 —— 记录调试日志便于后续扩展
      appLogger.info({
        event: 'acp_sse_unknown_event',
        module: 'vibe-coding',
        action: 'sse',
        status: 'success',
        message: 'ACP SSE 收到未知事件类型',
        extra: { event_type: eventType },
      })
      break
  }
}

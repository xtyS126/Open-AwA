import { asRecord, isRecord } from '@/shared/types/api'

type LogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL'

interface LoggerPayload {
  event: string
  message: string
  module?: string
  action?: string
  status?: string
  request_id?: string
  extra?: Record<string, unknown>
}

interface LogRecord {
  timestamp: string
  level: LogLevel
  service: string
  module: string
  event: string
  message: string
  request_id: string
  action?: string
  status?: string
  extra: Record<string, unknown>
}

const LOG_LEVEL_ORDER: Record<LogLevel, number> = {
  DEBUG: 10,
  INFO: 20,
  WARNING: 30,
  ERROR: 40,
  CRITICAL: 50,
}

const DEFAULT_LEVEL: LogLevel = 'INFO'
const SERVICE = 'openawa-frontend'
const REQUEST_ID_KEY = 'current_request_id'

// localStorage 日志缓冲区
const LOG_BUFFER_KEY = 'openawa_log_buffer'
const LOG_BUFFER_MAX = 200

function getConfiguredLevel(): LogLevel {
  try {
    const fromStorage = typeof window !== 'undefined' ? localStorage.getItem('log_level') : null
    const raw = String(fromStorage || DEFAULT_LEVEL).toUpperCase()
    if (raw in LOG_LEVEL_ORDER) {
      return raw as LogLevel
    }
  } catch {
    // 隐私模式或存储不可用时回退到默认级别
  }
  return DEFAULT_LEVEL
}

function shouldLog(level: LogLevel): boolean {
  return LOG_LEVEL_ORDER[level] >= LOG_LEVEL_ORDER[getConfiguredLevel()]
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

export function setCurrentRequestId(requestId: string): void {
  if (!requestId) {
    return
  }
  try {
    sessionStorage.setItem(REQUEST_ID_KEY, requestId)
  } catch {
    // 存储不可用时静默忽略（隐私模式/配额满/iframe沙箱）
  }
}

export function getCurrentRequestId(): string {
  try {
    return sessionStorage.getItem(REQUEST_ID_KEY) || ''
  } catch {
    return ''
  }
}

export function generateRequestId(): string {
  const random = Math.random().toString(16).slice(2, 10)
  return `${Date.now().toString(16)}-${random}`
}

// 需要脱敏的敏感字段名（小写匹配）
const SENSITIVE_FIELDS = new Set([
  'password', 'token', 'api_key', 'secret', 'authorization',
  'cookie', 'access_token', 'refresh_token', 'username', 'user_input',
  'password_hash', 'session_key', 'csrf_token', 'ticket', 'auth_id',
])

function sanitizeExtra(data: Record<string, unknown>): Record<string, unknown> {
  const sanitized: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(data)) {
    if (SENSITIVE_FIELDS.has(key.toLowerCase())) {
      sanitized[key] = '***'
    } else if (isRecord(value)) {
      sanitized[key] = sanitizeExtra(value)
    } else {
      sanitized[key] = value
    }
  }
  return sanitized
}

// ============ localStorage 日志环形缓冲区 ============

/** 读取本地日志缓冲区（最新在前） */
export function getLocalLogs(limit: number = 200): LogRecord[] {
  try {
    const raw = localStorage.getItem(LOG_BUFFER_KEY)
    if (!raw) return []
    const logs: LogRecord[] = JSON.parse(raw)
    return logs.slice(-limit).reverse()
  } catch {
    return []
  }
}

/** 清除本地日志缓冲区 */
export function clearLocalLogs(): void {
  try {
    localStorage.removeItem(LOG_BUFFER_KEY)
  } catch {
    // ignore
  }
}

/** 获取本地日志缓冲区大小 */
export function getLocalLogCount(): number {
  try {
    const raw = localStorage.getItem(LOG_BUFFER_KEY)
    if (!raw) return 0
    const logs: unknown = JSON.parse(raw)
    return Array.isArray(logs) ? logs.length : 0
  } catch {
    return 0
  }
}

function _appendToLocalLogs(record: LogRecord): void {
  try {
    const raw = localStorage.getItem(LOG_BUFFER_KEY)
    let logs: LogRecord[] = raw ? JSON.parse(raw) : []
    if (!Array.isArray(logs)) logs = []
    logs.push(record)
    // 环形缓冲区：保留最近 N 条
    if (logs.length > LOG_BUFFER_MAX) {
      logs = logs.slice(logs.length - LOG_BUFFER_MAX)
    }
    localStorage.setItem(LOG_BUFFER_KEY, JSON.stringify(logs))
  } catch {
    // 存储配额满或隐私模式时静默忽略
  }
}

// ============ 后端上报队列 ============

// 仅上报 WARNING/ERROR/CRITICAL 三级，避免 INFO 级别日志（api_request/api_response/page_view 等）
// 大量填充后端日志库导致真正的错误难以识别
const _REPORTABLE_LEVELS: Set<LogLevel> = new Set(['WARNING', 'ERROR', 'CRITICAL'])

let _reportQueue: Array<Record<string, unknown>> = []
let _reportTimer: ReturnType<typeof setTimeout> | null = null
const REPORT_FLUSH_INTERVAL = 5000
const REPORT_MAX_BATCH = 20
const REPORT_MAX_QUEUE = 200
let _reportingDisabledByAuth = false

/**
 * 上报去重缓存：key = `${level}|${event}|${message}`，value = 上次上报时间戳
 * 相同 key 在 REPORT_DEDUP_WINDOW_MS 时间窗口内只入队一次，避免高频 warning/error
 * 短时间内被重复上报填充后端日志（如 React warning 每次渲染都触发）
 */
const REPORT_DEDUP_WINDOW_MS = 5000
const _reportDedupMap: Map<string, number> = new Map()
const _reportDedupMaxKeys = 200

function _buildReportDedupKey(level: LogLevel, event: string, message: string): string {
  return `${level}|${event}|${message}`
}

function _shouldDedupReport(level: LogLevel, record: LogRecord): boolean {
  const key = _buildReportDedupKey(level, record.event, record.message)
  const now = Date.now()
  const lastSeen = _reportDedupMap.get(key)
  if (lastSeen !== undefined && now - lastSeen < REPORT_DEDUP_WINDOW_MS) {
    return true
  }
  // 维护 dedup map 大小，避免无限增长
  if (_reportDedupMap.size >= _reportDedupMaxKeys) {
    // 删除最早的 50% 条目（按时间戳排序）
    const entries = Array.from(_reportDedupMap.entries()).sort((a, b) => a[1] - b[1])
    const toRemove = Math.floor(entries.length / 2)
    for (let i = 0; i < toRemove; i++) {
      _reportDedupMap.delete(entries[i][0])
    }
  }
  _reportDedupMap.set(key, now)
  return false
}

async function _flushErrorReports(): Promise<void> {
  if (_reportQueue.length === 0 || _reportingDisabledByAuth) return
  // 单次 POST 批量上传整批报告，避免逐条请求撑高 QPS
  const batch = _reportQueue.splice(0, REPORT_MAX_BATCH)
  try {
    const response = await fetch('/api/logs/client-errors', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reports: batch }),
    })
    if (response.status === 401 || response.status === 403) {
      _reportingDisabledByAuth = true
      _reportQueue = []
    }
  } catch {
    // 网络失败：把本批报告重新入队到队首，保留原日志以便下次 flush 重试
    _reportQueue = [...batch, ..._reportQueue]
  }
}

function _scheduleFlush(): void {
  if (_reportTimer) return
  _reportTimer = setTimeout(() => {
    _reportTimer = null
    _flushErrorReports()
  }, REPORT_FLUSH_INTERVAL)
}

function _enqueueReport(record: LogRecord): void {
  if (_reportingDisabledByAuth) return
  // 5 秒去重：相同 level + event + message 的日志只入队一次
  if (_shouldDedupReport(record.level, record)) {
    return
  }
  if (_reportQueue.length >= REPORT_MAX_QUEUE) {
    _reportQueue.shift()
  }
  _reportQueue.push({
    level: record.level,
    message: String(record.message || ''),
    source: String(record.module || 'frontend'),
    stack: String((record.extra && record.extra.stack) || ''),
    url: typeof window !== 'undefined' ? window.location.href : '',
    user_agent: typeof navigator !== 'undefined' ? navigator.userAgent : '',
    timestamp: String(record.timestamp || new Date().toISOString()),
    extra: asRecord(record.extra),
  })
  _scheduleFlush()
}

// ============ 日志发射 ============

function emit(level: LogLevel, payload: LoggerPayload): void {
  if (!shouldLog(level)) {
    return
  }

  const record: LogRecord = {
    timestamp: new Date().toISOString(),
    level,
    service: SERVICE,
    module: payload.module || 'frontend',
    event: payload.event,
    message: payload.message,
    request_id: payload.request_id || getCurrentRequestId(),
    action: payload.action,
    status: payload.status,
    extra: sanitizeExtra(payload.extra || {}),
  }

  // 1. localStorage 持久化（所有级别）
  _appendToLocalLogs(record)

  // 2. 控制台输出
  const text = safeStringify(record)
  if (level === 'ERROR' || level === 'CRITICAL') {
    console.error(text)
  } else if (level === 'WARNING') {
    console.warn(text)
  } else {
    // eslint-disable-next-line no-console -- 日志基础设施，INFO 级别需使用 console.log 输出
    console.log(text)
  }

  // 3. 上报到后端（INFO 及以上，批量异步）
  if (_REPORTABLE_LEVELS.has(level)) {
    _enqueueReport(record)
  }
}

export const appLogger = {
  debug: (payload: LoggerPayload) => emit('DEBUG', payload),
  info: (payload: LoggerPayload) => emit('INFO', payload),
  warning: (payload: LoggerPayload) => emit('WARNING', payload),
  error: (payload: LoggerPayload) => emit('ERROR', payload),
  critical: (payload: LoggerPayload) => emit('CRITICAL', payload),
}

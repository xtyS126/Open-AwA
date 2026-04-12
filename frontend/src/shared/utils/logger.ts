import Cookies from 'js-cookie'

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

function getConfiguredLevel(): LogLevel {
  const fromStorage = typeof window !== 'undefined' ? localStorage.getItem('log_level') : null
  const raw = String(fromStorage || DEFAULT_LEVEL).toUpperCase()
  if (raw in LOG_LEVEL_ORDER) {
    return raw as LogLevel
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
  sessionStorage.setItem(REQUEST_ID_KEY, requestId)
}

export function getCurrentRequestId(): string {
  return sessionStorage.getItem(REQUEST_ID_KEY) || ''
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
    } else if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
      sanitized[key] = sanitizeExtra(value as Record<string, unknown>)
    } else {
      sanitized[key] = value
    }
  }
  return sanitized
}

// 后端错误上报队列，避免频繁请求
let _reportQueue: Array<Record<string, unknown>> = []
let _reportTimer: ReturnType<typeof setTimeout> | null = null
const REPORT_FLUSH_INTERVAL = 3000
const REPORT_MAX_BATCH = 10
const REPORT_MAX_QUEUE = 100

async function _flushErrorReports(): Promise<void> {
  if (_reportQueue.length === 0) return
  const batch = _reportQueue.splice(0, REPORT_MAX_BATCH)
  const csrfToken = Cookies.get('csrf_token') || ''
  for (const report of batch) {
    try {
      await fetch('/api/logs/client-errors', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
        },
        body: JSON.stringify(report),
      })
    } catch {
      // 上报失败时静默忽略，避免无限循环
    }
  }
}

function _scheduleFlush(): void {
  if (_reportTimer) return
  _reportTimer = setTimeout(() => {
    _reportTimer = null
    _flushErrorReports()
  }, REPORT_FLUSH_INTERVAL)
}

function _enqueueErrorReport(record: Record<string, unknown>): void {
  if (_reportQueue.length >= REPORT_MAX_QUEUE) {
    _reportQueue.shift()
  }
  _reportQueue.push({
    level: record.level,
    message: String(record.message || ''),
    source: String(record.module || 'frontend'),
    stack: String(record.extra && (record.extra as Record<string, unknown>).stack || ''),
    url: typeof window !== 'undefined' ? window.location.href : '',
    user_agent: typeof navigator !== 'undefined' ? navigator.userAgent : '',
    timestamp: String(record.timestamp || new Date().toISOString()),
    extra: (record.extra || {}) as Record<string, unknown>,
  })
  _scheduleFlush()
}

function emit(level: LogLevel, payload: LoggerPayload): void {
  if (!shouldLog(level)) {
    return
  }

  const record = {
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

  const text = safeStringify(record)
  if (level === 'ERROR' || level === 'CRITICAL') {
    console.error(text)
    // 将错误上报到后端日志系统
    _enqueueErrorReport(record)
    return
  }
  if (level === 'WARNING') {
    console.warn(text)
    return
  }
  console.log(text)
}

export const appLogger = {
  debug: (payload: LoggerPayload) => emit('DEBUG', payload),
  info: (payload: LoggerPayload) => emit('INFO', payload),
  warning: (payload: LoggerPayload) => emit('WARNING', payload),
  error: (payload: LoggerPayload) => emit('ERROR', payload),
  critical: (payload: LoggerPayload) => emit('CRITICAL', payload),
}

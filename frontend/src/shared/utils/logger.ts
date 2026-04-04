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
    extra: payload.extra || {},
  }

  const text = safeStringify(record)
  if (level === 'ERROR' || level === 'CRITICAL') {
    console.error(text)
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

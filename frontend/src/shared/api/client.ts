/**
 * Axios 客户端实例、API Key 管理和请求/响应拦截器。
 * 所有 API 模块通过此 client 发起请求。
 *
 * 认证策略：
 *   - 单用户模式：使用 API Key (Bearer) 认证
 *   - 状态变更请求（POST/PUT/PATCH/DELETE）自动附加 X-CSRF-Token 头
 *   - 应用启动或登录成功后调用 refreshCsrfToken() 拉取 per-session CSRF token
 *   - 收到 403 missing_csrf_token / invalid_csrf_token 时自动刷新并重试一次
 *     （即便 Bearer 模式下后端豁免 CSRF，保留 CSRF 防御可避免 Cookie 路径被滥用）
 */
import axios, { type InternalAxiosRequestConfig } from 'axios'
import { appLogger, generateRequestId, setCurrentRequestId } from '@/shared/utils/logger'
import { safeGetItem, safeSetItem } from '@/shared/utils/safeStorage'

export type RetriableApiRequest = InternalAxiosRequestConfig & {
  _apiKeyRetried?: boolean
  _csrfRetried?: boolean
}

// 替换原有的：const API_BASE_URL = '/api'
const BACKEND_URL_STORAGE_KEY = 'openawa_backend_url'

/**
 * 动态解析后端 baseURL
 * 优先级：preload 注入 > localStorage > 默认 /api
 */
function resolveBaseURL(): string {
  // 优先级 1：桌面端 preload 注入
  if (typeof window !== 'undefined' && window.__OPENAWA_BACKEND__?.url) {
    return window.__OPENAWA_BACKEND__.url
  }
  // 优先级 2：用户在设置页配置的远程后端
  if (typeof window !== 'undefined') {
    const stored = window.localStorage.getItem(BACKEND_URL_STORAGE_KEY)
    if (stored) {
      return stored
    }
  }
  // 优先级 3：默认相对路径（web 模式走 Vite proxy）
  return '/api'
}

export const API_BASE_URL = resolveBaseURL()

/**
 * 设置后端 URL 并持久化到 localStorage
 * 同步更新 axios 实例 baseURL，运行时立即生效
 */
export function setBackendUrl(url: string): void {
  const normalizedUrl = url.trim() || '/api'
  api.defaults.baseURL = normalizedUrl
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(BACKEND_URL_STORAGE_KEY, normalizedUrl)
  }
}

const API_KEY_STORAGE_KEY = 'openawa_api_key'

// 模块级内存变量，作为 API Key 的主要运行时存储
// （AVOID localStorage 到内存的读取路径，仅在验证成功后持久化）
let _inMemoryApiKey = safeGetItem(API_KEY_STORAGE_KEY, '')

/** 获取当前有效的 API Key（优先内存，降级 localStorage） */
export const getCachedApiKey = (): string => {
  if (_inMemoryApiKey) {
    return _inMemoryApiKey
  }
  // 降级：从 localStorage 恢复（仅页面首次加载时触发）
  _inMemoryApiKey = safeGetItem(API_KEY_STORAGE_KEY, '')
  return _inMemoryApiKey
}

/** 将 API Key 持久化到 localStorage 并更新内存缓存（仅在验证成功后调用） */
export const persistApiKey = (key: string): void => {
  _inMemoryApiKey = key
  safeSetItem(API_KEY_STORAGE_KEY, key)
}

/** 临时设置 API Key 到内存（用于验证，验证成功后再调用 persistApiKey 持久化） */
export const setTempApiKey = (key: string): void => {
  _inMemoryApiKey = key
}

/** 清除所有存储中的 API Key */
export const clearCachedApiKey = (): void => {
  _inMemoryApiKey = ''
  safeSetItem(API_KEY_STORAGE_KEY, '')
}

// CSRF token 内存缓存。
// 仅在内存中保存，不持久化到 localStorage，避免跨标签页复用过期 token。
// 由 refreshCsrfToken() 在应用启动或登录成功后从后端拉取。
let _csrfToken: string | null = null

/**
 * 从后端拉取并缓存 per-session CSRF token。
 *
 * 调用时机：
 *   - 应用启动时（推荐在 useAppInitialization 中调用）
 *   - 登录成功后（persistApiKey 触发）
 *   - 收到 403 missing_csrf_token / invalid_csrf_token 后自动调用
 *
 * 拉取失败时降级处理：仅记录警告，不阻塞应用启动。
 * 此后状态变更请求会因缺失 X-CSRF-Token 被后端拒绝，但不会影响 GET 等只读请求。
 *
 * 注意：使用 api 实例调用 GET /auth/csrf-token。GET 请求不会附加 X-CSRF-Token，
 * 因此不会因 CSRF 校验失败而递归。
 */
export async function refreshCsrfToken(): Promise<void> {
  try {
    const response = await api.get('/auth/csrf-token', { withCredentials: true })
    const token = response.data?.csrf_token
    if (typeof token === 'string' && token) {
      _csrfToken = token
    }
  } catch (e) {
    // 拉取失败不阻塞应用启动：可能后端使用 Bearer 模式豁免 CSRF，或尚未启用 CSRF 中间件
    // 仅记录警告，避免在控制台抛出未捕获异常
    appLogger.warning({
      event: 'csrf_token_fetch_failed',
      module: 'api',
      action: 'GET',
      status: 'warning',
      message: 'CSRF token 拉取失败，状态变更请求可能被后端拒绝',
      extra: { error: e instanceof Error ? e.message : String(e) },
    })
  }
}

/** 返回当前缓存的 CSRF token（供调试或测试使用） */
export const getCachedCsrfToken = (): string | null => _csrfToken

export const logStreamParseWarning = (payload: string, source: 'chunk' | 'tail') => {
  appLogger.warning({
    event: 'chat_stream_parse_warning',
    module: 'api',
    action: 'POST',
    status: 'warning',
    message: 'failed to parse stream payload',
    extra: {
      source,
      payload_preview: payload.slice(0, 100),
    },
  })
}

/**
 * 清洗 header 值，移除所有非 ISO-8859-1 字符。
 * 浏览器 XMLHttpRequest.setRequestHeader 仅接受 ISO-8859-1 范围内的字符，
 * 若值含 UTF-8 字符（如中文、零宽空格等）会抛出异常导致请求中止。
 */
function sanitizeHeaderValue(value: unknown): string {
  if (value == null) return ''
  const str = String(value)
  // 移除所有码点 > 255 的字符（非 ISO-8859-1）
  // eslint-disable-next-line no-control-regex
  return str.replace(/[^\x00-\xFF]/g, '')
}

/** 清洗 config 中所有 header 值，确保仅含 ISO-8859-1 字符 */
function sanitizeHeaders(headers: Record<string, unknown>): void {
  for (const key of Object.keys(headers)) {
    const val = headers[key]
    if (val != null && typeof val !== 'boolean') {
      headers[key] = sanitizeHeaderValue(val)
    }
  }
}

/** Axios 实例，所有 API 调用通过此实例发起 */
export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.request.use(async (config) => {
  const requestId = generateRequestId()
  config.headers['X-Request-Id'] = requestId
  setCurrentRequestId(requestId)

  // 附加 API Key 到 Authorization header（从内存变量读取）
  if (_inMemoryApiKey && !config.headers['Authorization']) {
    config.headers['Authorization'] = `Bearer ${_inMemoryApiKey}`
  }

  // 为状态变更请求附加 CSRF token（防 CSRF 攻击，对应 P0-9）
  // Bearer 模式下后端会豁免 CSRF，但保留该头可避免 Cookie 路径被滥用
  const method = (config.method || 'get').toLowerCase()
  if (['post', 'put', 'patch', 'delete'].includes(method) && _csrfToken) {
    config.headers['X-CSRF-Token'] = _csrfToken
  }

  // 防御性清洗：移除 header 值中的非 ISO-8859-1 字符
  // 防止浏览器 setRequestHeader 抛出异常导致请求静默失败
  sanitizeHeaders(config.headers as unknown as Record<string, unknown>)

  appLogger.info({
    event: 'api_request',
    module: 'api',
    action: config.method?.toUpperCase() || 'GET',
    status: 'start',
    request_id: requestId,
    message: 'api request started',
    extra: {
      url: config.url,
    },
  })
  return config
})

api.interceptors.response.use(
  (response) => {
    const responseRequestId = String(response.headers?.['x-request-id'] || '')
    if (responseRequestId) {
      setCurrentRequestId(responseRequestId)
    }
    appLogger.info({
      event: 'api_response',
      module: 'api',
      action: response.config.method?.toUpperCase() || 'GET',
      status: 'success',
      request_id: responseRequestId,
      message: 'api request finished',
      extra: {
        url: response.config.url,
        status_code: response.status,
      },
    })
    return response
  },
  async (error) => {
    const responseRequestId = String(error?.response?.headers?.['x-request-id'] || '')
    if (responseRequestId) {
      setCurrentRequestId(responseRequestId)
    }

    const isExpectedAuthError = (
      (error?.config?.url === '/auth/me' && error?.response?.status === 401)
    )

    // CSRF token 失效或缺失时自动刷新并重试一次（对应 P0-9）
    // 后端在 Cookie 认证路径下会返回 403 + missing_csrf_token / invalid_csrf_token
    // 此处只重试一次，避免无限循环
    const csrfErrorCode = error?.response?.data?.error as string | undefined
    const isCsrfError = (
      error?.response?.status === 403 &&
      (csrfErrorCode === 'missing_csrf_token' || csrfErrorCode === 'invalid_csrf_token')
    )
    const requestConfig = error?.config as RetriableApiRequest | undefined
    if (isCsrfError && requestConfig && !requestConfig._csrfRetried) {
      requestConfig._csrfRetried = true
      try {
        await refreshCsrfToken()
        if (_csrfToken) {
          requestConfig.headers['X-CSRF-Token'] = _csrfToken
          return api.request(requestConfig)
        }
      } catch (refreshError) {
        // 刷新失败则继续走原有错误处理流程
        appLogger.warning({
          event: 'csrf_retry_failed',
          module: 'api',
          action: error?.config?.method?.toUpperCase() || 'GET',
          status: 'warning',
          message: 'CSRF token 自动重试失败',
          extra: { error: refreshError instanceof Error ? refreshError.message : String(refreshError) },
        })
      }
    }

    if (!isExpectedAuthError) {
      const errorUrl = error?.config?.url || 'unknown'
      const errorStatus = error?.response?.status || 0
      const errorMessage = error?.message || ''
      const backendDetail = error?.response?.data?.detail || ''

      appLogger.error({
        event: 'api_response',
        module: 'api',
        action: error?.config?.method?.toUpperCase() || 'GET',
        status: 'failure',
        request_id: responseRequestId,
        message: `[API ERROR] ${error?.config?.method?.toUpperCase() || 'GET'} ${errorUrl} -> ${errorStatus}` +
          (errorMessage ? ` | ${errorMessage}` : '') +
          (backendDetail ? ` | Detail: ${backendDetail}` : '') +
          (responseRequestId ? ` | Request-ID: ${responseRequestId}` : ''),
        extra: {
          url: errorUrl,
          status_code: errorStatus,
          error: errorMessage,
          detail: backendDetail,
        },
      })
    }
    return Promise.reject(error)
  }
)

export const getApiErrorDetail = (error: unknown): string => {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) {
    return detail
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === 'string') {
          return item
        }
        if (item && typeof item === 'object' && 'msg' in item && typeof item.msg === 'string') {
          return item.msg
        }
        return ''
      })
      .filter(Boolean)
    if (messages.length > 0) {
      return messages.join('；')
    }
  }
  if (error instanceof Error && error.message.trim()) {
    return error.message
  }
  return ''
}

export default api

/**
 * Axios 客户端实例、CSRF 令牌管理和请求/响应拦截器。
 * 所有 API 模块通过此 client 发起请求。
 */
import axios, { type InternalAxiosRequestConfig } from 'axios'
import { appLogger, generateRequestId, setCurrentRequestId } from '@/shared/utils/logger'

export type RetriableApiRequest = InternalAxiosRequestConfig & {
  _csrfRetried?: boolean
}

const API_BASE_URL = '/api'

const CSRF_EXEMPT_PATHS = new Set(['/auth/login', '/auth/register'])
const CSRF_TOKEN_URL = `${API_BASE_URL}/auth/csrf-token`

let _cachedCsrfToken = ''
let csrfBootstrapPromise: Promise<string> | null = null

export const getCsrfToken = (): string => _cachedCsrfToken

/** 设置缓存的 CSRF token（登录成功后调用，避免额外的引导请求） */
export const setCachedCsrfToken = (token: string): void => {
  _cachedCsrfToken = token
}

export const clearCsrfTokenCache = (): void => {
  _cachedCsrfToken = ''
  csrfBootstrapPromise = null
}

const shouldAttachCsrfToken = (method?: string, url?: string): boolean => {
  const normalizedMethod = String(method || 'GET').toUpperCase()
  if (!['POST', 'PUT', 'DELETE', 'PATCH'].includes(normalizedMethod)) {
    return false
  }
  const normalizedUrl = String(url || '').split('?')[0]
  return !CSRF_EXEMPT_PATHS.has(normalizedUrl)
}

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

const ensureCsrfToken = async (): Promise<string> => {
  if (_cachedCsrfToken) {
    return _cachedCsrfToken
  }

  appLogger.warning({
    event: 'csrf_token_missing',
    module: 'api',
    action: 'BOOTSTRAP',
    status: 'warning',
    message: 'csrf token missing before mutating request, trying bootstrap request',
    extra: {
      bootstrap_path: CSRF_TOKEN_URL,
    },
  })

  if (!csrfBootstrapPromise) {
    csrfBootstrapPromise = (async () => {
      try {
        const response = await fetch(CSRF_TOKEN_URL, {
          method: 'GET',
          credentials: 'same-origin',
        })
        if (!response.ok) {
          throw new Error(`CSRF token request failed: ${response.status}`)
        }
        const data = await response.json()
        _cachedCsrfToken = data.csrf_token || ''
      } catch (error) {
        appLogger.warning({
          event: 'csrf_token_bootstrap_failed',
          module: 'api',
          action: 'BOOTSTRAP',
          status: 'warning',
          message: 'csrf token bootstrap request failed',
          extra: {
            error: error instanceof Error ? error.message : String(error),
          },
        })
      }

      if (!_cachedCsrfToken) {
        throw new Error('CSRF token missing after bootstrap request')
      }
      return _cachedCsrfToken
    })().finally(() => {
      csrfBootstrapPromise = null
    })
  }

  return csrfBootstrapPromise
}

/** Axios 实例，所有 API 调用通过此实例发起 */
export const api = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.request.use(async (config) => {
  const requestId = generateRequestId()
  config.headers['X-Request-Id'] = requestId
  setCurrentRequestId(requestId)

  if (shouldAttachCsrfToken(config.method, config.url)) {
    const csrfToken = await ensureCsrfToken()
    config.headers['X-CSRF-Token'] = csrfToken
  }
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

    const originalRequest = error?.config as RetriableApiRequest | undefined
    const shouldRetryInvalidCsrf = (
      error?.response?.status === 403 &&
      error?.response?.data?.error === 'invalid_csrf_token' &&
      originalRequest &&
      !originalRequest._csrfRetried &&
      shouldAttachCsrfToken(originalRequest.method, originalRequest.url)
    )

    if (shouldRetryInvalidCsrf && originalRequest) {
      originalRequest._csrfRetried = true
      clearCsrfTokenCache()

      try {
        const csrfToken = await ensureCsrfToken()
        const retryHeaders = axios.AxiosHeaders.from(originalRequest.headers || {})
        retryHeaders.set('X-CSRF-Token', csrfToken)
        originalRequest.headers = retryHeaders
        return api(originalRequest)
      } catch (refreshError) {
        appLogger.warning({
          event: 'csrf_token_refresh_retry_failed',
          module: 'api',
          action: originalRequest.method?.toUpperCase() || 'UNKNOWN',
          status: 'warning',
          request_id: responseRequestId,
          message: 'csrf token refresh retry failed',
          extra: {
            url: originalRequest.url,
            error: refreshError instanceof Error ? refreshError.message : String(refreshError),
          },
        })
      }
    }

    const isExpectedAuthError = (
      (error?.config?.url === '/auth/me' && error?.response?.status === 401) ||
      (error?.config?.url === '/auth/register' && error?.response?.status === 400)
    )

    if (!isExpectedAuthError) {
      const errorUrl = error?.config?.url || 'unknown'
      const errorStatus = error?.response?.status || 0
      const errorMessage = error?.message || ''
      const backendDetail = error?.response?.data?.detail || ''

      console.error(
        `[API ERROR] ${error?.config?.method?.toUpperCase() || 'GET'} ${errorUrl} -> ${errorStatus}` +
        (errorMessage ? ` | ${errorMessage}` : '') +
        (backendDetail ? ` | Detail: ${backendDetail}` : '') +
        (responseRequestId ? ` | Request-ID: ${responseRequestId}` : '')
      )

      appLogger.error({
        event: 'api_response',
        module: 'api',
        action: error?.config?.method?.toUpperCase() || 'GET',
        status: 'failure',
        request_id: responseRequestId,
        message: 'api request failed',
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

export { API_BASE_URL, ensureCsrfToken, CSRF_TOKEN_URL }
export default api

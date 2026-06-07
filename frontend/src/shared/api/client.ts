/**
 * Axios 客户端实例、API Key 管理和请求/响应拦截器。
 * 所有 API 模块通过此 client 发起请求。
 * 单用户模式下使用 API Key (Bearer) 认证，不再需要 CSRF 保护。
 */
import axios, { type InternalAxiosRequestConfig } from 'axios'
import { appLogger, generateRequestId, setCurrentRequestId } from '@/shared/utils/logger'
import { useAuthStore } from '@/shared/store/authStore'
import { safeGetItem, safeSetItem } from '@/shared/utils/safeStorage'

export type RetriableApiRequest = InternalAxiosRequestConfig & {
  _apiKeyRetried?: boolean
}

const API_BASE_URL = '/api'
const API_KEY_STORAGE_KEY = 'openawa_api_key'

/** 从 localStorage 获取缓存的 API Key */
export const getCachedApiKey = (): string => {
  return safeGetItem(API_KEY_STORAGE_KEY, '')
}

/** 设置缓存的 API Key */
export const setCachedApiKey = (key: string): void => {
  safeSetItem(API_KEY_STORAGE_KEY, key)
}

/** 清除缓存的 API Key */
export const clearCachedApiKey = (): void => {
  safeSetItem(API_KEY_STORAGE_KEY, '')
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

  // 附加 API Key 到 Authorization header
  const apiKey = getCachedApiKey()
  if (apiKey && !config.headers['Authorization']) {
    config.headers['Authorization'] = `Bearer ${apiKey}`
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

    const isExpectedAuthError = (
      (error?.config?.url === '/auth/me' && error?.response?.status === 401)
    )

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

export { API_BASE_URL }
export default api

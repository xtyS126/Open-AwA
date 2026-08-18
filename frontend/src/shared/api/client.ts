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
import { isNativeApp, isDesktop, getDesktopApi } from '@/shared/utils/platform'
import { safeGetItem, safeSetItem, safeSessionGetItem, safeSessionSetItem } from '@/shared/utils/safeStorage'
import { asRecord } from '@/shared/types/api'

export type RetriableApiRequest = InternalAxiosRequestConfig & {
  _apiKeyRetried?: boolean
  _csrfRetried?: boolean
}

/**
 * 判断请求失败是否由调用方主动取消产生。
 *
 * Axios 的 AbortSignal 会生成 code=ERR_CANCELED，浏览器原生请求则可能抛出
 * AbortError。两者都属于组件卸载或参数切换时的预期控制流，不应写入错误日志。
 */
export function isExpectedRequestCancellation(error: unknown): boolean {
  if (axios.isCancel(error)) {
    return true
  }
  const candidate = error as { code?: unknown; name?: unknown } | null
  return candidate?.code === 'ERR_CANCELED' || candidate?.name === 'AbortError'
}

// 替换原有的：const API_BASE_URL = '/api'
const BACKEND_URL_STORAGE_KEY = 'openawa_backend_url'

/**
 * 校验后端 URL 是否为合法的 http(s) URL，防止 XSS 利用 setBackendUrl
 * 将所有 API 请求（含 Authorization header）劫持到恶意服务器。
 *
 * 安全策略：
 * 1. 必须是 http: 或 https: 协议
 * 2. 必须有 host
 * 3. 默认相对路径 '/api' 放行（走 Vite proxy 或同源反向代理）
 * 4. 拒绝 javascript: / data: / file: 等危险协议
 */
function isValidBackendUrl(url: string): boolean {
  // 默认相对路径放行（同源代理）
  if (url === '/api' || url === '') {
    return true
  }
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch {
    return false
  }
}

/**
 * 动态解析后端 baseURL
 * 优先级：preload 注入 > localStorage > 桌面端 IPC > 默认 /api
 */
function resolveBaseURL(): string {
  // 优先级 1：桌面端 preload 注入
  if (typeof window !== 'undefined' && window.__OPENAWA_BACKEND__?.url) {
    return window.__OPENAWA_BACKEND__.url
  }
  // 优先级 2：用户在设置页配置的远程后端
  if (typeof window !== 'undefined') {
    const stored = window.localStorage.getItem(BACKEND_URL_STORAGE_KEY)
    if (stored && isValidBackendUrl(stored)) {
      return stored
    }
  }
  // 优先级 3：默认相对路径（web 模式走 Vite proxy）
  return '/api'
}

/**
 * 桌面端初始化：从主进程拉取已保存的后端 URL 并设置到 axios/live bindings
 * 应在应用启动时尽早调用（main.tsx 或 App.tsx 的初始化阶段）
 */
export async function initDesktopBackendUrl(): Promise<void> {
  if (!isDesktop()) return
  try {
    const desktopApi = getDesktopApi()
    if (!desktopApi) return
    const url = (await desktopApi.ipc.invoke('backend:get-url')) as string
    if (url && typeof url === 'string' && url.trim()) {
      const trimmed = url.trim().replace(/\/+$/, '')
      if (isValidBackendUrl(trimmed)) {
        // 后端 API 端点统一挂在 /api 前缀下（如 /api/system/init-status）。
        // 桌面端 electron-store 保存的是服务器根地址（如 http://localhost:8000），
        // 此处补全 /api，与前端的 setBackendUrl 约定（接收已含 /api 的地址）保持一致。
        const apiBase = trimmed.endsWith('/api') ? trimmed : `${trimmed}/api`
        // 不写入 localStorage，保持桌面端 electron-store 为唯一权威源
        API_BASE_URL = apiBase
        api.defaults.baseURL = apiBase
        appLogger.info({
          event: 'desktop_backend_url_initialized',
          module: 'api',
          status: 'success',
          message: '已从桌面端获取后端 URL',
          extra: { url: apiBase },
        })
      }
    }
  } catch (err) {
    appLogger.warning({
      event: 'desktop_backend_url_init_failed',
      module: 'api',
      status: 'failure',
      message: '无法从桌面端获取后端 URL',
      extra: { error: String(err) },
    })
  }
}

// 模块级可变绑定：ES Module live binding 保证 import 方始终读到最新值。
// setBackendUrl() 会重新赋值，使绕过 axios 的原生通道（SSE 流式 / WebSocket /
// 文件预览等直接拼接 API_BASE_URL 的调用点）在切换后端后立即生效，
// 无需逐个调用点改为运行时函数。
export let API_BASE_URL = resolveBaseURL()

/**
 * 设置后端 URL 并持久化到 localStorage
 * 同步更新 axios 实例 baseURL，运行时立即生效
 *
 * 安全：校验 URL 必须为 http(s) 协议，防止 XSS 将请求劫持到恶意源
 */
/**
 * 是否已配置可用后端。
 * APP 模式：localStorage 存在合法后端 URL 或 preload 注入时视为已配置；
 * Web 模式：默认相对路径 /api 视为已配置（走 Vite proxy 或同源部署）。
 *
 * 原生容器内 localhost/127.0.0.1 指向设备自身（模拟器/手机的环回地址），
 * 不可能是承载后端的宿主机地址，此类残留配置视为未配置，
 * 引导用户进入服务器选择页重新接入局域网后端。
 */
export function isBackendConfigured(): boolean {
  if (typeof window !== 'undefined' && window.__OPENAWA_BACKEND__?.url) {
    return true
  }
  // 桌面端：通过 initDesktopBackendUrl() 已设置 API_BASE_URL
  if (isDesktop() && isValidBackendUrl(API_BASE_URL)) {
    return true
  }
  if (typeof window !== 'undefined') {
    const stored = window.localStorage.getItem(BACKEND_URL_STORAGE_KEY)
    if (!stored || !isValidBackendUrl(stored)) {
      return false
    }
    if (isNativeApp()) {
      try {
        const hostname = new URL(stored).hostname
        if (hostname === 'localhost' || hostname === '127.0.0.1') {
          return false
        }
      } catch {
        return false
      }
    }
    return true
  }
  return false
}

export function setBackendUrl(url: string): void {
  const trimmed = url.trim() || '/api'
  if (!isValidBackendUrl(trimmed)) {
    appLogger.error({
      event: 'invalid_backend_url_rejected',
      module: 'api',
      status: 'failure',
      message: '拒绝设置非法后端 URL（必须为 http/https 协议或相对路径 /api）',
      extra: { url: trimmed },
    })
    return
  }
  API_BASE_URL = trimmed
  api.defaults.baseURL = trimmed
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(BACKEND_URL_STORAGE_KEY, trimmed)
  }
}

const API_KEY_STORAGE_KEY = 'openawa_api_key'

/**
 * API Key 存储策略：
 * 优先使用 sessionStorage（页面关闭后自动清除），降低 XSS 窃取后的持久化风险。
 * 若 sessionStorage 不可用（如旧版浏览器或隐私模式），降级到 localStorage。
 *
 * 安全考虑：
 * - sessionStorage 仅在当前标签页存活，关闭即清除，缩小了 XSS 攻击的窗口期
 * - 跨标签页登录需重新输入，是安全/UX 的折中
 * - 内存变量 _inMemoryApiKey 是运行时主要读取路径，避免每个请求访问 Storage
 */
let _inMemoryApiKey = safeSessionGetItem(API_KEY_STORAGE_KEY, '') || safeGetItem(API_KEY_STORAGE_KEY, '')

/** 获取当前有效的 API Key（优先内存，降级 sessionStorage/localStorage） */
export const getCachedApiKey = (): string => {
  if (_inMemoryApiKey) {
    return _inMemoryApiKey
  }
  // 降级：从 sessionStorage 恢复，再降级到 localStorage（仅页面首次加载时触发）
  _inMemoryApiKey = safeSessionGetItem(API_KEY_STORAGE_KEY, '') || safeGetItem(API_KEY_STORAGE_KEY, '')
  return _inMemoryApiKey
}

/** 将 API Key 持久化到 sessionStorage 并更新内存缓存（仅在验证成功后调用） */
export const persistApiKey = (key: string): void => {
  _inMemoryApiKey = key
  // 优先写入 sessionStorage；同时清理 localStorage 中的旧值避免残留
  safeSessionSetItem(API_KEY_STORAGE_KEY, key)
  if (isNativeApp()) {
    // APP 模式：WebView 进程可被系统回收，sessionStorage 随进程消失，
    // 降级持久化到 localStorage，避免用户每次冷启动重新输入访问密钥
    safeSetItem(API_KEY_STORAGE_KEY, key)
  } else {
    safeSetItem(API_KEY_STORAGE_KEY, '')
  }
}

/** 临时设置 API Key 到内存（用于验证，验证成功后再调用 persistApiKey 持久化） */
export const setTempApiKey = (key: string): void => {
  _inMemoryApiKey = key
}

/** 清除所有存储中的 API Key */
export const clearCachedApiKey = (): void => {
  _inMemoryApiKey = ''
  _csrfToken = null
  safeSessionSetItem(API_KEY_STORAGE_KEY, '')
  safeSetItem(API_KEY_STORAGE_KEY, '')
}

// CSRF token 内存缓存。
// 仅在内存中保存，不持久化到 localStorage，避免跨标签页复用过期 token。
// 由 refreshCsrfToken() 在应用启动或登录成功后从后端拉取。
let _csrfToken: string | null = null

type UnauthorizedHandler = () => void

let unauthorizedHandler: UnauthorizedHandler | null = null

/** 注册认证失效后的 UI 清理回调，避免 API 层直接依赖业务 store。 */
export const setUnauthorizedHandler = (handler: UnauthorizedHandler | null): void => {
  unauthorizedHandler = handler
}

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
  // CSRF 端点需要认证；未持有已验证的访问密钥时不发送无意义的 401 请求。
  if (!getCachedApiKey()) {
    return
  }

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

/**
 * 为未登录的首次部署页面申请双提交 CSRF token。
 * 该端点仅在系统未初始化时可用，避免将首次部署请求从 CSRF 防护中豁免。
 */
export async function refreshInitCsrfToken(): Promise<void> {
  const response = await api.get('/system/init-csrf-token', { withCredentials: true })
  const token = response.data?.csrf_token
  if (typeof token !== 'string' || !token) {
    throw new Error('首次部署 CSRF token 返回格式异常')
  }
  _csrfToken = token
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
  // 默认 15s 超时：常规 GET/POST 请求应远低于此阈值；
  // 流式 / SSE / 长轮询请求需在调用点通过 config.timeout 单独覆盖更长超时。
  // 原值 30s 在浏览器连接池耗尽或 vite proxy 卡顿时让用户等待过久。
  timeout: 15_000,
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

  // 若请求数据为 FormData,移除默认的 application/json Content-Type,
  // 由浏览器根据 FormData 自动设置带 boundary 的 multipart/form-data 头。
  // 否则 axios transformRequest 会因默认 application/json 头而把 FormData 误序列化为 JSON,
  // 导致后端 multipart 解析失败(对应宠物导入 400 空响应问题)。
  if (typeof FormData !== 'undefined' && config.data instanceof FormData) {
    config.headers.delete('Content-Type')
  }

  // 防御性清洗：移除 header 值中的非 ISO-8859-1 字符
  // 防止浏览器 setRequestHeader 抛出异常导致请求静默失败
  sanitizeHeaders(asRecord(config.headers))

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

    if (error?.response?.status === 401) {
      // 认证已经失效时立即清除内存与持久化凭据，防止后续请求无限显示 401。
      clearCachedApiKey()
      try {
        unauthorizedHandler?.()
      } catch (handlerError) {
        appLogger.warning({
          event: 'unauthorized_cleanup_failed',
          module: 'api',
          status: 'warning',
          message: '认证失效后的界面清理失败',
          extra: { error: handlerError instanceof Error ? handlerError.message : String(handlerError) },
        })
      }
    }

    const isExpectedAuthError = (
      (error?.config?.url === '/auth/me' && error?.response?.status === 401)
    )
    const isExpectedCancellation = isExpectedRequestCancellation(error)

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

    if (!isExpectedAuthError && !isExpectedCancellation) {
      const errorUrl = error?.config?.url || 'unknown'
      const errorStatus = error?.response?.status || 0
      const errorMessage = error?.message || ''
      const backendDetail = error?.response?.data?.detail || ''

      // 409 Conflict 通常是业务预期内的冲突（如配置已存在），业务代码会静默跳过或处理。
      // 降级为 warning 避免污染 ERROR 日志，让真正的异常更易定位。
      const logLevel = errorStatus === 409 ? 'warning' : 'error'
      const logStatus = errorStatus === 409 ? 'warning' : 'failure'
      appLogger[logLevel]({
        event: 'api_response',
        module: 'api',
        action: error?.config?.method?.toUpperCase() || 'GET',
        status: logStatus,
        request_id: responseRequestId,
        message: `[API ${errorStatus === 409 ? 'WARN' : 'ERROR'}] ${error?.config?.method?.toUpperCase() || 'GET'} ${errorUrl} -> ${errorStatus}` +
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
  const data = (error as {
    response?: { data?: { detail?: unknown; error?: unknown; message?: unknown } }
  })?.response?.data
  const detail = data?.detail
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
  if (data?.error && typeof data.error === 'object') {
    const message = (data.error as { message?: unknown }).message
    if (typeof message === 'string' && message.trim()) {
      return message
    }
  }
  if (typeof data?.message === 'string' && data.message.trim()) {
    return data.message
  }
  if (typeof data?.error === 'string' && data.error.trim()) {
    return data.error
  }
  if (error instanceof Error && error.message.trim()) {
    return error.message
  }
  return ''
}

export default api

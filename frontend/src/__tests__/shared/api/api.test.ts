import { beforeEach, describe, expect, it, vi } from 'vitest'

const {
  axiosHeadersFromMock,
  cookieState,
  requestUse,
  responseUse,
  fakeApiInstance,
  loggerMocks,
  generateRequestIdMock,
  setCurrentRequestIdMock,
} = vi.hoisted(() => {
  const requestUseMock = vi.fn()
  const responseUseMock = vi.fn()
  const apiInstanceMock = vi.fn()
  const axiosHeadersFrom = vi.fn((headers: Record<string, unknown> = {}) => {
    const nextHeaders: Record<string, unknown> & {
      set: (key: string, value: unknown) => void
    } = {
      ...headers,
      set(key: string, value: unknown) {
        nextHeaders[key] = value
      },
    }
    return nextHeaders
  })

  apiInstanceMock.interceptors = {
    request: {
      use: requestUseMock,
    },
    response: {
      use: responseUseMock,
    },
  }
  apiInstanceMock.get = vi.fn()
  apiInstanceMock.post = vi.fn()
  apiInstanceMock.put = vi.fn()
  apiInstanceMock.delete = vi.fn()

  return {
    axiosHeadersFromMock: axiosHeadersFrom,
    cookieState: {
      csrfToken: '',
    },
    requestUse: requestUseMock,
    responseUse: responseUseMock,
    fakeApiInstance: apiInstanceMock,
    loggerMocks: {
      info: vi.fn(),
      warning: vi.fn(),
      error: vi.fn(),
    },
    generateRequestIdMock: vi.fn(() => 'req-test'),
    setCurrentRequestIdMock: vi.fn(),
  }
})

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => fakeApiInstance),
    AxiosHeaders: {
      from: axiosHeadersFromMock,
    },
  },
}))

vi.mock('js-cookie', () => ({
  default: {
    get: vi.fn((key: string) => (key === 'csrf_token' ? cookieState.csrfToken : '')),
  },
}))

vi.mock('@/shared/utils/logger', () => ({
  appLogger: loggerMocks,
  generateRequestId: generateRequestIdMock,
  setCurrentRequestId: setCurrentRequestIdMock,
}))

import * as module from '@/shared/api/api'

const requestInterceptor = requestUse.mock.calls[0][0]
const responseErrorInterceptor = responseUse.mock.calls[0][1]

describe('api', () => {
  beforeEach(() => {
    cookieState.csrfToken = ''
    fakeApiInstance.mockReset()
    fakeApiInstance.get.mockReset()
    fakeApiInstance.post.mockReset()
    fakeApiInstance.put.mockReset()
    fakeApiInstance.delete.mockReset()
    axiosHeadersFromMock.mockClear()
    loggerMocks.info.mockClear()
    loggerMocks.warning.mockClear()
    loggerMocks.error.mockClear()
    generateRequestIdMock.mockClear()
    setCurrentRequestIdMock.mockClear()
    vi.stubGlobal('fetch', vi.fn())
  })

  it('loads module', () => {
    expect(module).toBeDefined()
  })

  it('对变更请求自动获取并注入 CSRF token', async () => {
    ;(global.fetch as any).mockResolvedValue({
      ok: true,
      json: async () => ({ csrf_token: 'test-csrf-token' }),
    })

    const config = { method: 'post', url: '/skills', headers: {} }
    const result = await requestInterceptor(config)

    expect(global.fetch).toHaveBeenCalledWith('/api/auth/csrf-token', expect.objectContaining({
      method: 'GET',
      credentials: 'same-origin',
    }))
    expect(result.headers['X-CSRF-Token']).toBe('test-csrf-token')
  })

  it('对 GET 请求跳过 CSRF token', async () => {
    const config = { method: 'get', url: '/chat/history', headers: {} }
    const result = await requestInterceptor(config)

    expect(result.headers['X-CSRF-Token']).toBeUndefined()
  })

  it('对免检路径的 POST 请求跳过 CSRF token', async () => {
    const config = { method: 'post', url: '/auth/login', headers: {} }
    const result = await requestInterceptor(config)

    expect(result.headers['X-CSRF-Token']).toBeUndefined()
  })

  it('对 invalid_csrf_token 的 403 自动刷新 token 并重试原请求', async () => {
    ;(global.fetch as any).mockResolvedValue({
      ok: true,
      json: async () => ({ csrf_token: 'renewed-csrf-token' }),
    })
    fakeApiInstance.mockResolvedValue({ data: { ok: true } })

    const originalRequest = {
      method: 'delete',
      url: '/conversations/session-1',
      headers: {
        'X-CSRF-Token': 'stale-token',
      },
    }

    const result = await responseErrorInterceptor({
      config: originalRequest,
      response: {
        status: 403,
        data: {
          error: 'invalid_csrf_token',
          detail: 'CSRF token 验证失败',
        },
        headers: {},
      },
      message: 'Request failed with status code 403',
    })

    expect(global.fetch).toHaveBeenCalledWith('/api/auth/csrf-token', expect.objectContaining({
      method: 'GET',
      credentials: 'same-origin',
    }))
    expect(fakeApiInstance).toHaveBeenCalledWith(expect.objectContaining({
      method: 'delete',
      url: '/conversations/session-1',
      _csrfRetried: true,
      headers: expect.objectContaining({
        'X-CSRF-Token': 'renewed-csrf-token',
      }),
    }))
    expect(result).toEqual({ data: { ok: true } })
  })

  it('对非 CSRF 原因的 403 不触发 token 刷新', async () => {
    const error = {
      config: {
        method: 'delete',
        url: '/conversations/session-2',
        headers: {},
      },
      response: {
        status: 403,
        data: {
          error: 'forbidden',
          detail: 'Not allowed',
        },
        headers: {},
      },
      message: 'Request failed with status code 403',
    }

    await expect(responseErrorInterceptor(error)).rejects.toBe(error)
    expect(global.fetch).not.toHaveBeenCalled()
    expect(fakeApiInstance).not.toHaveBeenCalled()
  })
})

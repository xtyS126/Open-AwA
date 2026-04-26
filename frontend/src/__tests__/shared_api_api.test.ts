import { beforeEach, describe, expect, it, vi } from 'vitest'

const {
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

  return {
    cookieState: {
      csrfToken: '',
    },
    requestUse: requestUseMock,
    responseUse: responseUseMock,
    fakeApiInstance: {
      interceptors: {
        request: {
          use: requestUseMock,
        },
        response: {
          use: responseUseMock,
        },
      },
      get: vi.fn(),
      post: vi.fn(),
      put: vi.fn(),
      delete: vi.fn(),
    },
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

describe('api', () => {
  beforeEach(() => {
    cookieState.csrfToken = ''
    fakeApiInstance.get.mockReset()
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
})

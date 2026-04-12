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

  it('为变更请求注入现有的 CSRF token', async () => {
    cookieState.csrfToken = 'csrf-ready'
    const config = {
      method: 'post',
      url: '/skills',
      headers: {},
    }

    const result = await requestInterceptor(config)

    expect(result.headers['X-CSRF-Token']).toBe('csrf-ready')
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('缺少 CSRF token 时先补领再继续请求', async () => {
    const fetchMock = vi.mocked(global.fetch)
    fetchMock.mockImplementation(async () => {
      cookieState.csrfToken = 'csrf-from-bootstrap'
      return {} as Response
    })

    const config = {
      method: 'post',
      url: '/skills',
      headers: {},
    }

    const result = await requestInterceptor(config)

    expect(fetchMock).toHaveBeenCalledWith('/api/auth/me', {
      method: 'GET',
      credentials: 'same-origin',
    })
    expect(result.headers['X-CSRF-Token']).toBe('csrf-from-bootstrap')
    expect(loggerMocks.warning).toHaveBeenCalledWith(expect.objectContaining({
      event: 'csrf_token_missing',
    }))
  })

  it('补领后仍缺少 CSRF token 时拒绝请求', async () => {
    const fetchMock = vi.mocked(global.fetch)
    fetchMock.mockRejectedValue(new Error('network error'))

    const config = {
      method: 'post',
      url: '/skills',
      headers: {},
    }

    await expect(requestInterceptor(config)).rejects.toThrow('CSRF token missing after bootstrap request')
    expect(loggerMocks.warning).toHaveBeenCalledWith(expect.objectContaining({
      event: 'csrf_token_bootstrap_failed',
    }))
  })
})

import { describe, expect, it, vi } from 'vitest'

const { fakeApiInstance, requestUse, responseUse } = vi.hoisted(() => {
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
    request: { use: requestUseMock },
    response: { use: responseUseMock },
  }
  apiInstanceMock.get = vi.fn()
  apiInstanceMock.post = vi.fn()
  apiInstanceMock.put = vi.fn()
  apiInstanceMock.delete = vi.fn()

  return {
    axiosHeadersFromMock: axiosHeadersFrom,
    requestUse: requestUseMock,
    responseUse: responseUseMock,
    fakeApiInstance: apiInstanceMock,
  }
})

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => fakeApiInstance),
    AxiosHeaders: { from: vi.fn((h: Record<string, unknown> = {}) => h) },
  },
}))

vi.mock('js-cookie', () => ({
  default: { get: vi.fn(() => '') },
}))

vi.mock('@/shared/utils/logger', () => ({
  appLogger: { info: vi.fn(), warning: vi.fn(), error: vi.fn(), debug: vi.fn() },
  generateRequestId: vi.fn(() => 'req-test'),
  setCurrentRequestId: vi.fn(),
}))

import * as module from '@/shared/api/api'

describe('api', () => {
  it('loads api module', () => {
    expect(module).toBeDefined()
  })

  it('exports expected API objects', () => {
    expect(module.authAPI).toBeDefined()
    expect(module.chatAPI).toBeDefined()
    expect(module.skillsAPI).toBeDefined()
  })

  it('axios instance has interceptors configured', () => {
    expect(requestUse).toHaveBeenCalled()
    expect(responseUse).toHaveBeenCalled()
  })
})

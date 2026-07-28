import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  appLogger,
  clearLocalLogs,
  getCurrentRequestId,
  getLocalLogCount,
  getLocalLogs,
  setCurrentRequestId,
} from '@/shared/utils/logger'

describe('logger', () => {
  afterEach(() => {
    clearLocalLogs()
    sessionStorage.clear()
    vi.restoreAllMocks()
  })

  it('persists request identifiers for subsequent log records', () => {
    setCurrentRequestId('req-1')
    expect(getCurrentRequestId()).toBe('req-1')
  })

  it('redacts sensitive fields before persisting a record', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    appLogger.error({ event: 'login_failed', message: '失败', extra: { token: 'secret', nested: { password: 'hidden' } } })
    expect(getLocalLogs(1)[0].extra).toEqual({ token: '***', nested: { password: '***' } })
  })

  it('clears the persisted local log buffer', () => {
    vi.spyOn(console, 'log').mockImplementation(() => undefined)
    appLogger.info({ event: 'opened', message: '打开' })
    expect(getLocalLogCount()).toBe(1)
    clearLocalLogs()
    expect(getLocalLogCount()).toBe(0)
  })
})

import { afterEach, describe, expect, it } from 'vitest'
import { generateRequestId, getCurrentRequestId, setCurrentRequestId } from '@/shared/utils/logger'

describe('logger service', () => {
  afterEach(() => {
    sessionStorage.clear()
    localStorage.clear()
  })

  it('stores and retrieves current request id', () => {
    setCurrentRequestId('req-123')
    expect(getCurrentRequestId()).toBe('req-123')
  })

  it('generates request id with stable separator format', () => {
    const requestId = generateRequestId()
    expect(requestId).toContain('-')
    expect(requestId.length).toBeGreaterThan(8)
  })
})

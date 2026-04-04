import { describe, it, expect } from 'vitest'
import * as module from '@/shared/utils/logger'

describe('logger', () => {
  it('loads module', () => {
    expect(module).toBeDefined()
  })
})

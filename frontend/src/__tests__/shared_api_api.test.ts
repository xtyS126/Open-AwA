import { describe, it, expect } from 'vitest'
import * as module from '@/shared/api/api'

describe('api', () => {
  it('loads module', () => {
    expect(module).toBeDefined()
  })
})

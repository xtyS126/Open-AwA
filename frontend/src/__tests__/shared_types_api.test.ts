import { describe, it, expect } from 'vitest'
import * as module from '@/shared/types/api'

describe('api', () => {
  it('loads module', () => {
    expect(module).toBeDefined()
  })
})

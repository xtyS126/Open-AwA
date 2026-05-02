import { describe, it, expect } from 'vitest'
import * as module from '@/shared/store/authStore'

describe('authStore', () => {
  it('loads module', () => {
    expect(module).toBeDefined()
  })
})

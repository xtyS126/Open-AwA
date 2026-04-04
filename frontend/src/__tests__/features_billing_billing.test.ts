import { describe, it, expect } from 'vitest'
import * as module from '@/features/billing/billing'

describe('billing', () => {
  it('loads module', () => {
    expect(module).toBeDefined()
  })
})

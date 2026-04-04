import { describe, it, expect } from 'vitest'
import * as module from '@/features/billing/billingApi'

describe('billingApi', () => {
  it('loads module', () => {
    expect(module).toBeDefined()
  })
})

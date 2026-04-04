import { describe, it, expect } from 'vitest'
import * as module from '@/features/dashboard/dashboard'

describe('dashboard', () => {
  it('loads module', () => {
    expect(module).toBeDefined()
  })
})

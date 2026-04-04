import { describe, it, expect } from 'vitest'
import * as module from '@/setupTests'

describe('setupTests', () => {
  it('loads module', () => {
    expect(module).toBeDefined()
  })
})

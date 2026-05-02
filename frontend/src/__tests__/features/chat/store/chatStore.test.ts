import { describe, it, expect } from 'vitest'
import * as module from '@/features/chat/store/chatStore'

describe('chatStore', () => {
  it('loads module', () => {
    expect(module).toBeDefined()
  })
})

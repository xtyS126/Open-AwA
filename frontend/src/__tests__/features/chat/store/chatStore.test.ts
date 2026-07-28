import { beforeEach, describe, expect, it } from 'vitest'
import { usePreferenceStore, useSessionStore } from '@/features/chat/store/chatStore'

describe('chatStore compatibility exports', () => {
  beforeEach(() => {
    useSessionStore.getState().clearMessages()
    usePreferenceStore.getState().setThinkingEnabled(false, { syncToServer: false })
  })

  it('adds and updates assistant messages through the re-exported session store', () => {
    useSessionStore.getState().addMessage('assistant', '第一段', undefined, 'reply-1')
    useSessionStore.getState().updateLastMessage('第二段')
    expect(useSessionStore.getState().messages).toHaveLength(1)
    expect(useSessionStore.getState().messages[0]).toMatchObject({ id: 'reply-1', content: '第一段第二段' })
  })

  it('keeps reasoning hidden when thinking mode is disabled', () => {
    useSessionStore.getState().addMessage('assistant', '回答', undefined, 'reply-2')
    useSessionStore.getState().updateLastMessage('', '推理')
    expect(useSessionStore.getState().messages[0].reasoning_content).toBeUndefined()
  })

  it('applies bounded thinking depth through the re-exported preference store', () => {
    usePreferenceStore.getState().setThinkingDepth(99, { syncToServer: false })
    expect(usePreferenceStore.getState().thinkingDepth).toBe(5)
  })
})

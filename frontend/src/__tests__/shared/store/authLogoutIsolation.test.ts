import { beforeEach, describe, expect, it } from 'vitest'
import { useAuthStore } from '@/shared/store/authStore'
import { useSessionStore } from '@/features/chat/store/sessionStore'
import { useModelStore } from '@/features/chat/store/modelStore'
import { useToolCallStore } from '@/features/chat/store/toolCallStore'
import { useInboxStore } from '@/features/inbox/store/inboxStore'

describe('认证状态清理', () => {
  beforeEach(() => {
    useAuthStore.getState().logout()
  })

  it('登出时清除跨账号可见的业务状态', () => {
    useAuthStore.getState().setAuth({ username: 'first-user' }, 'key')
    useSessionStore.getState().setMessages([
      { id: 'message-1', role: 'user', content: '私有会话', timestamp: new Date() },
    ])
    useSessionStore.getState().setLoading(true)
    useModelStore.getState().setModelOptions([
      { id: 'provider:model', provider: 'provider', model: 'model', display_name: '模型' },
    ])
    useModelStore.getState().setSelectedModel('provider:model', { syncToServer: false })
    useToolCallStore.getState().addActiveToolCall('tool-1')
    useInboxStore.getState().setMessages([
      {
        id: 'inbox-1',
        title: '私有通知',
        content: '仅原账号可见',
        category: 'notification',
        read: false,
        action_url: null,
        action_label: null,
        created_at: '2026-07-27T00:00:00Z',
      },
    ])

    useAuthStore.getState().logout()

    expect(useAuthStore.getState().isAuthenticated).toBe(false)
    expect(useSessionStore.getState().messages).toEqual([])
    expect(useSessionStore.getState().isLoading).toBe(false)
    expect(useModelStore.getState().modelOptions).toEqual([])
    expect(useModelStore.getState().selectedModel).toBe('')
    expect(useToolCallStore.getState().activeToolCalls).toEqual([])
    expect(useInboxStore.getState().messages).toEqual([])
    expect(useInboxStore.getState().unreadCount).toBe(0)
  })
})

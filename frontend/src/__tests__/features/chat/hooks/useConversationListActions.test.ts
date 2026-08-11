import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMocks = vi.hoisted(() => ({
  renameSession: vi.fn(),
  deleteSession: vi.fn(),
  restoreSession: vi.fn(),
  batchDeleteSessions: vi.fn(),
  createSession: vi.fn(),
}))

vi.mock('@/shared/api/api', () => ({
  conversationAPI: apiMocks,
}))

vi.mock('@/shared/utils/logger', () => ({
  appLogger: {
    warning: vi.fn(),
  },
}))

import {
  useConversationListActions,
  type UseConversationListActionsParams,
} from '@/features/chat/hooks/useConversationListActions'
import type { ConversationSessionSummary } from '@/features/chat/types'

const conversation: ConversationSessionSummary = {
  session_id: 'session-1',
  user_id: 'user-1',
  title: '测试会话',
  summary: '',
  last_message_preview: '',
  message_count: 0,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
  last_message_at: null,
  conversation_metadata: {},
}

function buildParams(overrides: Partial<UseConversationListActionsParams> = {}): UseConversationListActionsParams {
  return {
    conversations: [conversation],
    activeSessionId: 'session-1',
    includeDeleted: false,
    loading: false,
    page: 1,
    hasMore: false,
    loadConversationList: vi.fn(() => Promise.resolve()),
    upsertConversation: vi.fn(),
    removeConversation: vi.fn(),
    broadcastConversationChange: vi.fn(),
    onConversationCreated: vi.fn(),
    onActiveConversationDeleted: vi.fn(),
    onConversationRestored: vi.fn(),
    ...overrides,
  }
}

describe('useConversationListActions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.createSession.mockResolvedValue({ data: conversation })
    apiMocks.renameSession.mockResolvedValue({ data: conversation })
    apiMocks.deleteSession.mockResolvedValue({ data: { ...conversation, deleted_at: '2026-08-11T00:00:00Z' } })
    apiMocks.restoreSession.mockResolvedValue({ data: conversation })
    apiMocks.batchDeleteSessions.mockResolvedValue({ data: { items: [], total: 0, page: 1, page_size: 20, has_more: false } })
  })

  it('mount 时不加载列表也不创建会话', () => {
    const loadConversationList = vi.fn(() => Promise.resolve())

    renderHook(() => useConversationListActions(buildParams({ loadConversationList })))

    expect(loadConversationList).not.toHaveBeenCalled()
    expect(apiMocks.createSession).not.toHaveBeenCalled()
  })

  it('显式创建只更新列表并把导航交给消费方', async () => {
    const upsertConversation = vi.fn()
    const loadConversationList = vi.fn(() => Promise.resolve())
    const onConversationCreated = vi.fn()
    const { result } = renderHook(() => useConversationListActions(buildParams({
      upsertConversation,
      loadConversationList,
      onConversationCreated,
    })))

    await act(async () => {
      await result.current.createConversation()
    })

    expect(apiMocks.createSession).toHaveBeenCalledWith()
    expect(upsertConversation).toHaveBeenCalledWith(conversation)
    expect(loadConversationList).toHaveBeenCalledWith(1, false, true)
    expect(onConversationCreated).toHaveBeenCalledWith('session-1')
  })

  it('删除先进入确认态，确认后才更新列表', async () => {
    const removeConversation = vi.fn()
    const loadConversationList = vi.fn(() => Promise.resolve())
    const onActiveConversationDeleted = vi.fn()
    const { result } = renderHook(() => useConversationListActions(buildParams({
      removeConversation,
      loadConversationList,
      onActiveConversationDeleted,
    })))

    act(() => result.current.handleDeleteConversation('session-1'))
    expect(result.current.pendingDeleteSessionId).toBe('session-1')
    expect(apiMocks.deleteSession).not.toHaveBeenCalled()

    await act(async () => {
      await result.current.confirmDeleteConversation()
    })

    expect(apiMocks.deleteSession).toHaveBeenCalledWith('session-1')
    expect(removeConversation).toHaveBeenCalledWith('session-1')
    expect(onActiveConversationDeleted).toHaveBeenCalledWith(null)
    expect(loadConversationList).toHaveBeenCalledWith(1, false, true)
  })
})

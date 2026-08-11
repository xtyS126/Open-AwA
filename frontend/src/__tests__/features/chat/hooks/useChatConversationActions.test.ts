import '@testing-library/jest-dom/vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { createElement, StrictMode, type ReactNode } from 'react'
import { RouterTestProvider as MemoryRouter } from '@/shared/routing/testing'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// 使用 vi.hoisted 提前建立 mock 引用
const apiMocks = vi.hoisted(() => ({
  getHistory: vi.fn(),
  createSession: vi.fn(),
  listSessions: vi.fn(),
}))

vi.mock('@/shared/api/api', () => ({
  chatAPI: {
    getHistory: apiMocks.getHistory,
  },
  conversationAPI: {
    createSession: apiMocks.createSession,
    listSessions: apiMocks.listSessions,
  },
}))

vi.mock('@/shared/utils/logger', () => ({
  appLogger: {
    info: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  },
}))

import { useChatConversationActions, type UseChatConversationActionsParams } from '@/features/chat/hooks/useChatConversationActions'

/** 构造默认的 hook 入参，所有依赖均 mock */
function buildParams(overrides: Partial<UseChatConversationActionsParams> = {}): UseChatConversationActionsParams {
  return {
    conversationId: undefined,
    sessionId: 'default',
    conversations: [],
    includeDeleted: false,
    historyInitialized: false,
    historyLoading: false,
    historyPage: 1,
    conversationsHasMore: false,
    isCompactViewport: false,
    loadConversationList: vi.fn(() => Promise.resolve()),
    closeHistorySidebar: vi.fn(),
    clearHistoryError: vi.fn(),
    setSessionId: vi.fn(),
    setMessages: vi.fn(),
    upsertConversation: vi.fn(),
    removeConversation: vi.fn(),
    resetStreamExecutionState: vi.fn(),
    resetTaskPanelState: vi.fn(),
    setMessageMeta: vi.fn(),
    setStreamingAssistantId: vi.fn(),
    setFeedbackState: vi.fn(),
    broadcastConversationChange: vi.fn(),
    getLocalMessagesForRestore: vi.fn(() => []),
    mergeServerHistoryWithCached: vi.fn((_server, cached) => cached),
    flushConversationCache: vi.fn(),
    getActiveConversationId: vi.fn(() => undefined),
    buildMessageMetaFromMessages: vi.fn(() => ({})),
    handleSendRef: { current: undefined },
    ...overrides,
  }
}

/** MemoryRouter wrapper，供 renderHook 使用 */
function routerWrapper({ children }: { children: ReactNode }) {
  return createElement(MemoryRouter, { initialEntries: ['/chat'] }, children)
}

/** StrictMode + MemoryRouter wrapper，用于验证 StrictMode 双 mount 行为 */
function strictModeWrapper({ children }: { children: ReactNode }) {
  return createElement(
    StrictMode,
    null,
    createElement(MemoryRouter, { initialEntries: ['/chat'] }, children)
  )
}

describe('useChatConversationActions - StrictMode 守卫', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.getHistory.mockResolvedValue({ data: [] })
    apiMocks.createSession.mockResolvedValue({
      data: {
        session_id: 'new-session',
        title: '新对话',
        user_id: 'u1',
        summary: '',
        last_message_preview: '',
        last_message_role: null,
        message_count: 0,
        created_at: '2026-04-19T00:00:00Z',
        updated_at: '2026-04-19T00:00:00Z',
        last_message_at: null,
        deleted_at: null,
        restored_at: null,
        purge_after: null,
        conversation_metadata: {},
      },
    })
    apiMocks.listSessions.mockResolvedValue({
      data: { items: [], total: 0, page: 1, page_size: 20, has_more: false },
    })
  })

  it('mount 时不负责加载会话列表', async () => {
    const loadConversationList = vi.fn(() => Promise.resolve())
    const params = buildParams({ loadConversationList })

    renderHook(() => useChatConversationActions(params), {
      wrapper: routerWrapper,
    })

    expect(loadConversationList).not.toHaveBeenCalled()
  })

  it('StrictMode 双 mount 时也不负责加载会话列表', async () => {
    const loadConversationList = vi.fn(() => Promise.resolve())
    const params = buildParams({ loadConversationList })

    renderHook(() => useChatConversationActions(params), {
      wrapper: strictModeWrapper,
    })

    expect(loadConversationList).not.toHaveBeenCalled()
  })

  it('conversationId 变化时不触发会话列表加载', async () => {
    const loadConversationList = vi.fn(() => Promise.resolve())

    const { rerender } = renderHook(
      ({ conversationId }: { conversationId: string | undefined }) =>
        useChatConversationActions(buildParams({ conversationId, loadConversationList })),
      {
        wrapper: routerWrapper,
        initialProps: { conversationId: undefined },
      }
    )

    expect(loadConversationList).not.toHaveBeenCalled()

    // rerender 改变 conversationId，不应再次触发 loadConversationList
    rerender({ conversationId: 'session-abc' })
    expect(loadConversationList).not.toHaveBeenCalled()

    rerender({ conversationId: 'session-def' })
    expect(loadConversationList).not.toHaveBeenCalled()
  })

  it('刷新加载历史时恢复 Markdown、思考与子代理工具事件', async () => {
    apiMocks.getHistory.mockResolvedValue({
      data: [
        { id: 1, role: 'user', content: '我的问题', timestamp: '2026-07-23T00:00:00Z' },
        {
          id: 2,
          role: 'assistant',
          content: '## Markdown 标题\n\n- 列表项',
          reasoning_content: '先分析上下文',
          toolEvents: [{
            id: 'subagent-aggregation',
            kind: 'subagent',
            name: '子代理汇总',
            status: 'completed',
            subagent: { logs: '**子代理结论**', visible: true },
          }],
          timestamp: '2026-07-23T00:00:01Z',
        },
      ],
    })
    const setMessages = vi.fn()
    const buildMessageMetaFromMessages = vi.fn(() => ({}))

    renderHook(() => useChatConversationActions(buildParams({
      sessionId: 'session-history',
      conversationId: 'session-history',
      historyInitialized: true,
      setMessages,
      mergeServerHistoryWithCached: (server) => server,
      buildMessageMetaFromMessages,
    })), { wrapper: routerWrapper })

    await waitFor(() => expect(setMessages).toHaveBeenCalled())
    const restored = setMessages.mock.calls.at(-1)?.[0]
    expect(restored).toHaveLength(2)
    expect(restored[0]).toMatchObject({ role: 'user', content: '我的问题' })
    expect(restored[1]).toMatchObject({
      role: 'assistant',
      content: '## Markdown 标题\n\n- 列表项',
      reasoning_content: '先分析上下文',
    })
    expect(restored[1].toolEvents[0].subagent.logs).toBe('**子代理结论**')
    expect(buildMessageMetaFromMessages).toHaveBeenCalledWith(restored)
  })
})

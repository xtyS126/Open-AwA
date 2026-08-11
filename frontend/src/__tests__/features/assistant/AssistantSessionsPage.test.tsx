import '@testing-library/jest-dom/vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderWithRouter } from '@/shared/routing/testing'
import { useSessionStore } from '@/features/chat/store/sessionStore'
import type { ConversationSessionSummary } from '@/features/chat/types'
import AssistantSessionsPage from '@/features/assistant/AssistantSessionsPage'

const mocks = vi.hoisted(() => ({
  createConversation: vi.fn().mockResolvedValue(undefined),
  confirmDeleteConversation: vi.fn().mockResolvedValue(undefined),
  cancelDeleteConversation: vi.fn(),
  confirmBatchDeleteConversations: vi.fn().mockResolvedValue(undefined),
  cancelBatchDeleteConversations: vi.fn(),
  useConversationListActions: vi.fn(),
  broadcastConversationChange: vi.fn(),
}))

vi.mock('@/features/chat/hooks/useConversationHistory', () => ({
  useConversationHistory: () => ({
    historyLoading: false,
    historyError: null,
    historySearchInput: '',
    historySort: 'last_message_at',
    historyPage: 1,
    includeDeleted: false,
    setHistorySearchInput: vi.fn(),
    setHistorySort: vi.fn(),
    setIncludeDeleted: vi.fn(),
    loadConversationList: vi.fn().mockResolvedValue(undefined),
  }),
}))

vi.mock('@/features/chat/hooks/useConversationListActions', () => ({
  useConversationListActions: mocks.useConversationListActions,
}))

vi.mock('@/features/chat/hooks/useChatBroadcast', () => ({
  useChatBroadcast: () => ({
    broadcastConversationChange: mocks.broadcastConversationChange,
  }),
}))

vi.mock('@/features/chat/components/ConversationManager', () => ({
  default: ({ onSelectConversation }: { onSelectConversation: (sessionId: string) => void }) => (
    <div data-testid="conversation-manager">
      <button type="button" onClick={() => onSelectConversation('session-1')}>打开会话</button>
    </div>
  ),
}))

const conversation: ConversationSessionSummary = {
  session_id: 'session-1',
  user_id: 'user-1',
  title: '需求梳理',
  summary: '',
  last_message_preview: '',
  message_count: 0,
  created_at: '2026-08-11T00:00:00Z',
  updated_at: '2026-08-11T00:00:00Z',
  conversation_metadata: {},
}

describe('AssistantSessionsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useSessionStore.setState({
      sessionId: 'session-1',
      conversations: [conversation],
      conversationsHasMore: false,
    })
    mocks.useConversationListActions.mockReturnValue({
      createConversation: mocks.createConversation,
      handleRenameConversation: vi.fn(),
      handleDeleteConversation: vi.fn(),
      cancelDeleteConversation: mocks.cancelDeleteConversation,
      confirmDeleteConversation: mocks.confirmDeleteConversation,
      handleRestoreConversation: vi.fn(),
      handleLoadMoreConversations: vi.fn(),
      handleBatchDeleteConversations: vi.fn(),
      cancelBatchDeleteConversations: mocks.cancelBatchDeleteConversations,
      confirmBatchDeleteConversations: mocks.confirmBatchDeleteConversations,
      pendingDeleteSessionId: null,
      pendingBatchDeleteIds: null,
    })
  })

  it('渲染独立会话管理页且打开列表项时只导航到聊天深链', async () => {
    const { router } = renderWithRouter(<AssistantSessionsPage />, {
      initialEntry: '/assistant/sessions',
      routePath: '/assistant/sessions',
    })

    expect(await screen.findByRole('heading', { name: '会话管理' })).toBeInTheDocument()
    expect(screen.getByTestId('conversation-manager')).toBeInTheDocument()
    expect(screen.queryByTestId('chat-input')).not.toBeInTheDocument()
    expect(mocks.createConversation).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: '打开会话' }))
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/assistant/sessions/session-1')
    })
  })

  it('新建按钮通过纯列表动作创建会话', async () => {
    renderWithRouter(<AssistantSessionsPage />, {
      initialEntry: '/assistant/sessions',
      routePath: '/assistant/sessions',
    })

    fireEvent.click(await screen.findByRole('button', { name: '新建对话' }))
    await waitFor(() => {
      expect(mocks.createConversation).toHaveBeenCalledTimes(1)
    })
  })

  it('删除动作在确认对话框中完成', async () => {
    mocks.useConversationListActions.mockReturnValue({
      ...mocks.useConversationListActions(),
      pendingDeleteSessionId: 'session-1',
    })

    renderWithRouter(<AssistantSessionsPage />, {
      initialEntry: '/assistant/sessions',
      routePath: '/assistant/sessions',
    })

    expect(await screen.findByRole('alertdialog')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '删除' }))
    expect(mocks.confirmDeleteConversation).toHaveBeenCalledTimes(1)
  })
})

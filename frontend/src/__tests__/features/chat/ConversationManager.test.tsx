import React from 'react'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ConversationManager from '@/features/chat/components/ConversationManager'
import type { ConversationSessionSummary } from '@/features/chat/types'
import { useI18nStore } from '@/i18n'

vi.mock('react-virtuoso', () => ({
  Virtuoso: ({ data, itemContent }: {
    data: ConversationSessionSummary[]
    itemContent: (index: number, item: ConversationSessionSummary) => React.ReactNode
  }) => (
    <div>
      {data.map((item, index) => (
        <div key={item.session_id}>{itemContent(index, item)}</div>
      ))}
    </div>
  ),
}))

const conversation: ConversationSessionSummary = {
  session_id: 'session-1',
  user_id: 'user-1',
  title: '测试会话',
  summary: '会话摘要',
  last_message_preview: '最后一条消息',
  message_count: 2,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
  last_message_at: '2026-08-01T00:00:00Z',
  conversation_metadata: {},
}

function renderManager(overrides: Partial<React.ComponentProps<typeof ConversationManager>> = {}) {
  const props: React.ComponentProps<typeof ConversationManager> = {
    loading: false,
    error: null,
    conversations: [conversation],
    activeSessionId: 'session-1',
    search: '',
    sortBy: 'last_message_at',
    includeDeleted: false,
    hasMore: false,
    onSearchChange: vi.fn(),
    onSortChange: vi.fn(),
    onIncludeDeletedChange: vi.fn(),
    onSelectConversation: vi.fn(),
    onRenameConversation: vi.fn(),
    onDeleteConversation: vi.fn(),
    onBatchDeleteConversations: vi.fn(),
    onRestoreConversation: vi.fn(),
    onLoadMore: vi.fn(),
    ...overrides,
  }

  return { ...render(<ConversationManager {...props} />), props }
}

describe('ConversationManager', () => {
  beforeEach(() => {
    useI18nStore.getState().setLocale('zh-CN')
  })

  it('渲染无侧栏语义的可复用会话管理内容', () => {
    const { container, props } = renderManager()

    expect(container.querySelector('aside')).toBeNull()
    expect(screen.getByRole('textbox')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '测试会话' }))
    expect(props.onSelectConversation).toHaveBeenCalledWith('session-1')
  })

  it('批量选择只提交未删除会话并保留选择直到操作结果返回', async () => {
    const onBatchDeleteConversations = vi.fn()
    renderManager({ onBatchDeleteConversations })

    const sessionCheckbox = screen.getByRole('checkbox', { name: /测试会话/ })
    fireEvent.click(sessionCheckbox)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /批量删除/ }))
    })

    expect(onBatchDeleteConversations).toHaveBeenCalledWith(['session-1'])
    expect(sessionCheckbox).toBeChecked()
  })
})

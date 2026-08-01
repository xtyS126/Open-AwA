import React from 'react'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import ConversationSidebar from '@/features/chat/components/ConversationSidebar'
import type { ConversationSessionSummary } from '@/features/chat/types'


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


describe('ConversationSidebar', () => {
  it('将会话选择与复选框和操作按钮渲染为同级交互控件', () => {
    const onSelectConversation = vi.fn()

    render(
      <ConversationSidebar
        open
        loading={false}
        error={null}
        conversations={[conversation]}
        activeSessionId="session-1"
        search=""
        sortBy="last_message_at"
        includeDeleted={false}
        hasMore={false}
        onToggle={vi.fn()}
        onSearchChange={vi.fn()}
        onSortChange={vi.fn()}
        onIncludeDeletedChange={vi.fn()}
        onCreateConversation={vi.fn()}
        onSelectConversation={onSelectConversation}
        onRenameConversation={vi.fn()}
        onDeleteConversation={vi.fn()}
        onBatchDeleteConversations={vi.fn()}
        onRestoreConversation={vi.fn()}
        onLoadMore={vi.fn()}
      />,
    )

    const selectButton = screen.getByRole('button', { name: /测试会话/ })
    const checkbox = screen.getByRole('checkbox', { name: /测试会话/ })

    expect(within(selectButton).queryByRole('checkbox')).not.toBeInTheDocument()
    expect(checkbox.closest('button, [role="button"]')).toBeNull()

    fireEvent.click(selectButton)
    expect(onSelectConversation).toHaveBeenCalledWith('session-1')
  })
})

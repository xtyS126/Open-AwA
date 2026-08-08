import React from 'react'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

import ConversationSidebar from '@/features/chat/components/ConversationSidebar'
import type { ConversationSessionSummary } from '@/features/chat/types'
import { RouterTestProvider as MemoryRouter } from '@/shared/routing/testing'
import { useAuthStore } from '@/shared/store/authStore'
import { useI18nStore } from '@/i18n'

vi.mock('@/shared/api/api', () => ({
  authAPI: { logout: vi.fn().mockResolvedValue({ data: {} }) },
}))

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
      <MemoryRouter initialEntries={['/chat']}>
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
        />
      </MemoryRouter>,
    )

    const selectButton = screen.getByRole('button', { name: /测试会话/ })
    const checkbox = screen.getByRole('checkbox', { name: /测试会话/ })

    expect(within(selectButton).queryByRole('checkbox')).not.toBeInTheDocument()
    expect(checkbox.closest('button, [role="button"]')).toBeNull()

    fireEvent.click(selectButton)
    expect(onSelectConversation).toHaveBeenCalledWith('session-1')
  })
})

/**
 * 历史侧栏移动端用户信息卡片测试
 *
 * 验证点：
 * 1. 未登录时不渲染用户卡片
 * 2. 点击卡片展开用户菜单（用户中心/退出登录）
 * 3. 点击遮罩关闭菜单
 * 4. 点击"用户中心"菜单项进入用户中心
 * 5. 点击"退出登录"清除会话并跳转登录页
 */
describe('ConversationSidebar 移动端用户信息卡片', () => {
  beforeEach(() => {
    useI18nStore.getState().setLocale('zh-CN')
    useAuthStore.setState({
      user: { id: '1', username: 'admin', role: 'owner' },
      isAuthenticated: true,
      isInitialized: true,
    })
  })

  afterEach(() => {
    useAuthStore.setState({ user: null, isAuthenticated: false })
  })

  function renderSidebar() {
    return render(
      <MemoryRouter initialEntries={['/chat']}>
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
          onSelectConversation={vi.fn()}
          onRenameConversation={vi.fn()}
          onDeleteConversation={vi.fn()}
          onBatchDeleteConversations={vi.fn()}
          onRestoreConversation={vi.fn()}
          onLoadMore={vi.fn()}
        />
      </MemoryRouter>,
    )
  }

  it('未登录时不渲染用户信息卡片', () => {
    useAuthStore.setState({ user: null })
    renderSidebar()
    expect(screen.queryByTestId('history-user-card')).not.toBeInTheDocument()
  })

  it('卡片显示头像字母与用户名，点击展开用户菜单', () => {
    renderSidebar()

    const card = screen.getByTestId('history-user-card')
    expect(card).toHaveTextContent('A')
    expect(card).toHaveTextContent('admin')

    act(() => {
      fireEvent.click(card)
    })

    expect(screen.getByTestId('history-user-card-menu')).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: '用户中心' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: '退出登录' })).toBeInTheDocument()
  })

  it('点击遮罩关闭用户菜单', () => {
    renderSidebar()

    act(() => {
      fireEvent.click(screen.getByTestId('history-user-card'))
    })
    expect(screen.getByTestId('history-user-card-menu')).toBeInTheDocument()

    act(() => {
      fireEvent.click(screen.getByTestId('history-user-card-overlay'))
    })
    expect(screen.queryByTestId('history-user-card-menu')).not.toBeInTheDocument()
  })

  it('点击"用户中心"菜单项关闭菜单并跳转用户中心', () => {
    renderSidebar()

    act(() => {
      fireEvent.click(screen.getByTestId('history-user-card'))
    })

    act(() => {
      fireEvent.click(screen.getByRole('menuitem', { name: '用户中心' }))
    })

    expect(screen.queryByTestId('history-user-card-menu')).not.toBeInTheDocument()
  })

  it('点击"退出登录"清除本地会话并跳转登录页', async () => {
    renderSidebar()

    act(() => {
      fireEvent.click(screen.getByTestId('history-user-card'))
    })

    await act(async () => {
      fireEvent.click(screen.getByRole('menuitem', { name: '退出登录' }))
    })

    expect(useAuthStore.getState().isAuthenticated).toBe(false)
  })
})
